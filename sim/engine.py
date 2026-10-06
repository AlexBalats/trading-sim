"""The day loop: the heart of the simulation. Read `run` top to bottom.

The rule that matters most: agents only *propose*. The engine checks every
offer against the rules, and only market.py actually moves cards or money.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from pathlib import Path

from .agents import BaseAgent, build_view, make_agents
from .config import Config
from .events import apply_events
from .logger import RunLogger
from .market import add_post, execute_trade, update_prices, validate_offer
from .money import fmt, offer_in_pounds, to_pounds, valuations_in_pounds
from .schemas import Decision
from .setup import build_world
from .state import Negotiation, World


class InvariantError(Exception):
    """Money or cards appeared or vanished. Always a bug: stop the run."""


async def run(config: Config, run_dir: Path | None = None, prediction: Path | None = None) -> tuple[World, RunLogger]:
    world = build_world(config)                      # packs, personas, network - all from the seed
    log = RunLogger(run_dir, config, world, prediction)
    agents = make_agents(world, config)
    start_money, start_cards = world.total_money(), world.card_counts()
    log.event("setup", [], groups=world.groups, popular=world.popular,
              personas={a.id: a.persona_type for a in world.agents.values()},
              desires={a.id: a.desire for a in world.agents.values()},
              personal_values={a.id: {cid: to_pounds(v) for cid, v in a.personal_value.items()}
                               for a in world.agents.values()})
    log.day(world, sales={}, seen_posts={})          # day 0: the starting position, for the charts

    for day in range(1, config.scenario.days + 1):
        world.day = day
        for a in world.agents.values():              # fresh day: everyone may post and receive again
            a.posted_today, a.incoming_today = False, 0

        apply_events(day, world)                     # empty until iteration 2

        # Only some agents choose an action today (fewer LLM calls, and real kids
        # don't trade every day). Everyone can still be offered a trade.
        active = pick_active(world, config.scenario.active_share)
        partners = assign_partners(world, active)    # one random friend each to meet today

        # Everyone active decides at the same time, all looking at the same
        # start-of-day world, so nobody gains from happening to go first.
        views = {a: build_view(world, world.agents[a], partners[a], config, world.rng) for a in active}
        decisions = dict(zip(views, await asyncio.gather(*(agents[a].decide(v) for a, v in views.items()))))
        seen_posts = {a: [p["id"] for p in v.board] for a, v in views.items()}

        # Carry out the decisions in a random (seeded) order. Order matters:
        # an agent can only take so many offers a day, and first come first served.
        order = list(active)
        world.rng.shuffle(order)
        negotiations = []
        for a in order:
            neg = handle_decision(world, config, log, a, decisions[a], partners[a])
            if neg:
                negotiations.append(neg)

        # Different negotiations happen at the same time; each one's turns go in order.
        await asyncio.gather(*(negotiate(world, config, agents, log, n) for n in negotiations))

        # Accepted deals happen now, in the order they were opened. Each is
        # checked again first: an earlier trade may have used up the cards.
        sales: dict[str, list[float]] = {cid: [] for cid in world.cards}
        for neg in negotiations:
            if neg.status == "accepted":
                result = execute_trade(world, neg)
                if isinstance(result, list):
                    log.event("trade_failed_stale", [neg.proposer, neg.responder],
                              negotiation=neg.id, errors=result)
                else:
                    log.event("trade", [result.a, result.b], trade=result.id, kind=result.kind,
                              a_gives={"cards": result.a_cards, "money": to_pounds(result.a_money)},
                              b_gives={"cards": result.b_cards, "money": to_pounds(result.b_money)},
                              happiness_a=to_pounds(result.happiness_a), happiness_b=to_pounds(result.happiness_b))
                    if result.kind == "sale":
                        sales[result.card_id].append(result.unit_price)

        world.prices = update_prices(world.prices, sales, config.scenario.price_k)   # Decision 4
        check_invariants(world, start_money, start_cards)    # stop loudly if money or cards leaked
        log.day(world, sales, seen_posts)

    log.finish(world, summarise(world, config, log))
    return world, log


# ---------------------------------------------------------------- helpers

def pick_active(world: World, share: float) -> list[str]:
    """Today's active agents: a random `share` of everyone (at least one), sorted by id."""
    everyone = sorted(world.agents)
    n = max(1, round(share * len(everyone)))
    return sorted(world.rng.sample(everyone, n))


def assign_partners(world: World, active: list[str]) -> dict[str, str]:
    """Each active agent meets one of its friends today, picked at random."""
    return {a: world.rng.choice(sorted(world.agents[a].neighbours)) for a in active}


def handle_decision(world: World, config: Config, log: RunLogger, agent_id: str,
                    d: Decision, partner: str) -> Negotiation | None:
    """Turn one agent's decision into a post or an opened negotiation."""
    log.event("decision", [agent_id], action=d.action, reason=d.reason,
              valuations=valuations_in_pounds(d.valuations))

    if d.action == "pass":
        return None

    if d.action == "post":
        if d.post is None:
            return invalid(log, agent_id, d, ["a post action needs a post"])
        result = add_post(world, agent_id, d.post)
        if isinstance(result, str):
            return invalid(log, agent_id, d, [result])
        log.event("post", [agent_id], post=result.id, kind=result.kind, card=result.card_id,
                  price=None if result.price is None else to_pounds(result.price), text=result.text)
        return None

    # propose_trade or reply_to_post: work out who the offer goes to.
    if d.action == "propose_trade":
        receiver, origin = partner, "encounter"
    else:
        older = [p for p in world.board if p.day_created < world.day]
        shown = {p.id: p for p in older[-config.scenario.board_visible:]} if config.scenario.board_visible else {}
        post = shown.get(d.post_id)
        if post is None or post.author == agent_id:
            return invalid(log, agent_id, d, [f"post {d.post_id} isn't one you can reply to"])
        receiver, origin = post.author, f"post:{post.id}"

    if d.offer is None:
        return invalid(log, agent_id, d, ["a trade action needs an offer"])
    errors = validate_offer(world, agent_id, receiver, d.offer, check_receiver_money=False)
    if errors:
        return invalid(log, agent_id, d, errors)          # from M2: one repair try first

    if world.agents[receiver].incoming_today >= config.scenario.max_incoming_per_day:
        log.event("auto_declined", [agent_id, receiver], reason="receiver already has the most offers allowed today")
        return None
    world.agents[receiver].incoming_today += 1

    neg = Negotiation(id=world.new_id("N"), day=world.day, proposer=agent_id, responder=receiver,
                      origin=origin, offer=d.offer, offerer=agent_id)
    neg.messages.append({"from": agent_id, "kind": "offer", "offer": d.offer.model_dump()})
    log.event("offer", [agent_id, receiver], negotiation=neg.id, origin=origin, offer=offer_in_pounds(d.offer))
    return neg


def invalid(log: RunLogger, agent_id: str, d: Decision, errors: list[str]) -> None:
    log.event("action_invalid", [agent_id], action=d.action, errors=errors)
    return None


async def negotiate(world: World, config: Config, agents: dict[str, BaseAgent],
                    log: RunLogger, neg: Negotiation) -> None:
    """Offers go back and forth until someone accepts or rejects, or the
    message limit is reached (then it counts as rejected)."""
    limit = config.scenario.negotiation_max_messages
    while True:
        receiver = neg.responder if neg.offerer == neg.proposer else neg.proposer
        both = [neg.proposer, neg.responder]
        # Nobody can see the other side's money, so an offer may ask for more
        # than the receiver has. They simply say no.
        if world.agents[receiver].money < neg.offer.get_money:
            neg.status = "rejected"
            neg.messages.append({"from": receiver, "kind": "reject", "offer": None})
            log.event("reject", both, negotiation=neg.id, by=receiver, reason="can't afford it")
            return
        view = build_view(world, world.agents[receiver], neg.offerer, config, world.rng)
        r = await agents[receiver].respond(view, neg)
        neg.messages.append({"from": receiver, "kind": r.response,
                             "offer": r.counter_offer.model_dump() if r.counter_offer else None})
        valuations = valuations_in_pounds(r.valuations)

        if r.response == "accept":
            neg.status = "accepted"
            log.event("accept", both, negotiation=neg.id, by=receiver, reason=r.reason, valuations=valuations)
            return
        if r.response == "reject":
            neg.status = "rejected"
            log.event("reject", both, negotiation=neg.id, by=receiver, reason=r.reason, valuations=valuations)
            return

        # A counter-offer: check it, then the roles swap.
        errors = (["a counter needs a counter_offer"] if r.counter_offer is None
                  else validate_offer(world, receiver, neg.offerer, r.counter_offer, check_receiver_money=False))
        if errors:
            neg.status = "rejected"
            log.event("reject", both, negotiation=neg.id, by=receiver, reason="invalid counter-offer",
                      errors=errors, valuations=valuations)
            return
        log.event("counter", both, negotiation=neg.id, by=receiver, reason=r.reason,
                  offer=offer_in_pounds(r.counter_offer), valuations=valuations)
        neg.offer, neg.offerer = r.counter_offer, receiver
        if len(neg.messages) >= limit:
            neg.status = "rejected"
            log.event("reject", both, negotiation=neg.id, by=None, reason="max_messages")
            return


def check_invariants(world: World, start_money: int, start_cards: Counter) -> None:
    problems = []
    if world.total_money() != start_money:
        problems.append(f"total money changed: {fmt(start_money, world.currency)} -> {fmt(world.total_money(), world.currency)}")
    if world.card_counts() != start_cards:
        problems.append("card counts changed")
    for a in world.agents.values():
        if a.money < 0:
            problems.append(f"{a.id} has negative money ({a.money})")
        if any(n < 0 for n in a.inventory.values()):
            problems.append(f"{a.id} has a negative card count")
    if problems:
        raise InvariantError(f"day {world.day}: " + "; ".join(problems))


def summarise(world: World, config: Config, log: RunLogger) -> dict:
    kinds = Counter(t.kind for t in world.trades)
    types = Counter(e["type"] for e in log.events)
    first_prices = {c.id: to_pounds(c.start_price) for c in world.cards.values()}   # logs are in pounds
    tracked = [cid for ids in world.tracked.values() for cid in ids]
    max_move = {}
    for cid in tracked:
        history = [first_prices[cid]] + [d["prices"][cid] for d in log.daily]
        max_move[cid] = round(max(abs(p - first_prices[cid]) for p in history), 4)
    # Happiness change per agent (end minus start), grouped two ways, for the fairness question.
    start = log.daily[0]["agents"]
    change = {a.id: to_pounds(world.happiness(a)) - start[a.id]["happiness"] for a in world.agents.values()}

    def mean_change(group_of) -> dict:
        groups: dict[str, list[float]] = {}
        for a in sorted(world.agents.values(), key=lambda a: a.id):
            groups.setdefault(group_of(a), []).append(change[a.id])
        return {g: round(sum(v) / len(v), 2) for g, v in sorted(groups.items())}

    sales_count = Counter()
    for t in world.trades:
        if t.kind == "sale":
            sales_count[t.card_id] += 1

    return {
        "days": config.scenario.days,
        "agents": len(world.agents),
        "trades": {"sale": kinds["sale"], "swap": kinds["swap"], "mixed": kinds["mixed"],
                   "total": len(world.trades)},
        "offers": types["offer"], "counters": types["counter"],
        "accepted": types["accept"], "rejected": types["reject"],
        "auto_declined": types["auto_declined"], "failed_stale": types["trade_failed_stale"],
        "invalid_actions": types["action_invalid"], "posts": types["post"],
        "final_prices": {cid: to_pounds(p) for cid, p in world.prices.items()},
        "tracked_max_move_from_start": max_move,
        "tracked_sales": {cid: sales_count[cid] for cid in tracked},
        "happiness_change_mean": {
            "by_persona": mean_change(lambda a: a.persona_type),
            "by_knowledge": mean_change(lambda a: "informed" if a.informed else "uninformed"),
        },
        "invariants": "ok",
        "cost_usd": 0.0,
    }
