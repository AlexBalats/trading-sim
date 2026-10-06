"""Agents: what each one is allowed to see, and how it decides.

AgentView is the only window an agent has onto the world. It is also the one
place the informed/uninformed rule is applied: an uninformed agent's view
never contains prices. From M2 the LLM prompt is built only from a view, so
prices can't leak into it by accident.

Two more things a view deliberately leaves out: the partner's money (you can
see a friend's cards, not their wallet), and personal values in pounds (an
agent is told how much it wants a card in words only).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from .market import visible_posts
from .money import fmt
from .schemas import Decision, NegotiationResponse, OfferSpec, PostSpec, Valuation
from .state import Agent, Negotiation, World


@dataclass
class AgentView:
    agent_id: str
    name: str
    currency: str
    persona_text: str
    goal: str
    informed: bool
    day: int
    days_total: int
    money: int                                  # pence
    inventory: list[tuple[str, int]]            # (card id, copies), shuffled order
    cards: dict[str, dict]                      # card id -> name and rarity (everyone sees rarity)
    desires: dict[str, str]                     # card id -> how much it wants it, in words
    prices: dict[str, float] | None             # None for uninformed agents, always
    partner_id: str                             # today's encounter partner, or the other side of a negotiation
    partner_name: str
    partner_inventory: list[tuple[str, int]]
    board: list[dict]                           # visible posts, newest first
    recent_events: list[dict]
    valid_actions: list[str] = field(default_factory=list)


def build_view(world: World, agent: Agent, partner_id: str, config, rng: random.Random) -> AgentView:
    s, scale = config.scenario, config.personas.desire_scale
    partner = world.agents[partner_id]
    board = [vars(p).copy() for p in visible_posts(world, s.board_visible, rng)]

    def shuffled(inventory):
        items = sorted(inventory.items())
        rng.shuffle(items)          # shuffled to avoid order bias in LLM prompts
        return items

    actions = ["propose_trade", "post", "pass"]
    if any(p["author"] != agent.id for p in board):
        actions.insert(1, "reply_to_post")

    return AgentView(
        agent_id=agent.id, name=agent.name, currency=world.currency, persona_text=agent.persona_text, goal=s.goal,
        informed=agent.informed, day=world.day, days_total=s.days,
        money=agent.money, inventory=shuffled(agent.inventory),
        cards={cid: {"name": c.name, "rarity": c.rarity} for cid, c in world.cards.items()},
        desires={cid: scale[level].words for cid, level in agent.desire.items()},
        prices=dict(world.prices) if agent.informed else None,
        partner_id=partner.id, partner_name=partner.name,
        partner_inventory=shuffled(partner.inventory),
        board=board,
        recent_events=agent.events[-s.recent_events:] if s.recent_events else [],
        valid_actions=actions,
    )


class BaseAgent:
    """What every kind of agent must be able to do.

    Both methods are async so LLM agents (M3) can wait for API calls while
    other agents carry on. Random agents simply return straight away.
    """

    async def decide(self, view: AgentView) -> Decision:
        raise NotImplementedError

    async def respond(self, view: AgentView, negotiation: Negotiation) -> NegotiationResponse:
        raise NotImplementedError


class RandomAgent(BaseAgent):
    """A zero-intelligence trader (Gode & Sunder 1993): the control group.

    It acts at random but never makes a deal it thinks is bad. Every LLM result
    is compared against these agents, to show the pattern came from behaviour
    and not from the market rules alone.

    Unlike other agents it always knows the current prices, informed or not:
    pricing randomly around the market price is what defines it. It gets them
    from `prices` (the live price list) rather than from its view.
    """

    def __init__(self, rng: random.Random, prices: callable):
        self.rng = rng
        self.prices = prices              # function returning today's price list
        self.values: dict[str, float] = {}
        self.values_day = -1

    def jitter(self, price: float) -> float:
        """A price 30% either side. Callers round it to the nearest penny."""
        return price * self.rng.uniform(0.7, 1.3)

    def value(self, card_id: str, day: int) -> float:
        """What this agent thinks a card is worth today: a fresh guess each morning."""
        if day != self.values_day:
            self.values = {cid: self.jitter(p) for cid, p in sorted(self.prices().items())}
            self.values_day = day
        return self.values[card_id]

    def valuations(self, card_ids, owned: set[str], day: int) -> list[Valuation]:
        out = []
        for cid in sorted(set(card_ids)):
            v = round(self.value(cid, day))
            out.append(Valuation(card_id=cid, min_sell=v) if cid in owned
                       else Valuation(card_id=cid, max_buy=v))
        return out

    # ---------------------------------------------------------------- decide

    async def decide(self, view: AgentView) -> Decision:
        action = self.rng.choice(view.valid_actions)
        if action == "propose_trade":
            offer = self.random_offer(view)
            if offer:
                return self.decision(view, "propose_trade", offer=offer)
        elif action == "reply_to_post":
            others = [p for p in view.board if p["author"] != view.agent_id]
            post = self.rng.choice(others)
            offer = self.offer_for_post(view, post)
            if offer:
                return self.decision(view, "reply_to_post", offer=offer, post_id=post["id"])
        elif action == "post":
            return self.decision(view, "post", post=self.random_post(view))
        return self.decision(view, "pass")

    def decision(self, view, action, offer=None, post_id=None, post=None) -> Decision:
        mentioned = []
        if offer:
            mentioned = offer.give_cards + offer.get_cards
        if post and post.card_id:
            mentioned = [post.card_id]
        owned = {cid for cid, _ in view.inventory}
        return Decision(reason="random", action=action, offer=offer, post_id=post_id, post=post,
                        valuations=self.valuations(mentioned, owned, view.day))

    def random_offer(self, view: AgentView) -> OfferSpec | None:
        """Sell one card for money, or swap one card for one of the partner's.

        It can't see the partner's money, so a sale may ask for more than they
        have. The engine then turns it down for them ("can't afford it")."""
        mine = [cid for cid, _ in sorted(view.inventory)]
        theirs = [cid for cid, _ in sorted(view.partner_inventory)]
        kinds = ["sell", "swap"]
        self.rng.shuffle(kinds)
        for kind in kinds:                       # try one kind, fall back to the other
            if kind == "sell" and mine:
                card = self.rng.choice(mine)
                ask = max(1, round(self.jitter(self.prices()[card])))
                return OfferSpec(give_cards=[card], get_money=ask)
            if kind == "swap" and mine and theirs:
                return OfferSpec(give_cards=[self.rng.choice(mine)], get_cards=[self.rng.choice(theirs)])
        return None

    def offer_for_post(self, view: AgentView, post: dict) -> OfferSpec | None:
        """Answer a selling post by buying, or a buying post by selling."""
        card = post["card_id"]
        if card is None:
            return None
        price = max(1, round(self.value(card, view.day)))
        owned = dict(view.inventory)
        if post["kind"] == "selling" and price <= view.money:
            return OfferSpec(give_money=price, get_cards=[card])
        if post["kind"] == "buying" and owned.get(card, 0) > 0:
            return OfferSpec(give_cards=[card], get_money=price)
        return None

    def random_post(self, view: AgentView) -> PostSpec:
        kind = self.rng.choice(["buying", "selling", "chat"])
        mine = [cid for cid, _ in sorted(view.inventory)]
        if kind == "selling" and mine:
            card = self.rng.choice(mine)
        elif kind == "buying":
            card = self.rng.choice(sorted(self.prices()))
        else:
            return PostSpec(kind="chat", text="just looking around")
        price = max(1, round(self.jitter(self.prices()[card])))
        return PostSpec(kind=kind, card_id=card, price=price,
                        text=f"{kind} {card} for {fmt(price, view.currency)}")

    # --------------------------------------------------------------- respond

    async def respond(self, view: AgentView, negotiation: Negotiation) -> NegotiationResponse:
        """Accept only if what it gets is worth at least what it gives, by its own guesses."""
        offer = negotiation.offer      # written from the other side: their give = my get
        day = view.day
        get = sum(self.value(c, day) for c in offer.give_cards) + offer.give_money
        give = sum(self.value(c, day) for c in offer.get_cards) + offer.get_money
        owned = {cid for cid, _ in view.inventory}
        return NegotiationResponse(
            reason="random",
            response="accept" if get >= give else "reject",
            valuations=self.valuations(offer.give_cards + offer.get_cards, owned, day),
        )


def make_agents(world: World, config) -> dict[str, BaseAgent]:
    agents: dict[str, BaseAgent] = {}
    for agent_id, agent in sorted(world.agents.items()):
        if agent.agent_type == "random":
            # Each agent gets its own random stream, seeded from the world's,
            # so the same seed still replays exactly.
            agents[agent_id] = RandomAgent(random.Random(world.rng.random()), lambda: world.prices)
        else:
            raise NotImplementedError("LLM agents arrive in M2/M3. Use --agent-type random for now.")
    return agents
