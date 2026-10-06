"""The rules of the market. Nothing else in the code moves cards or money.

- validate_offer: is this offer allowed right now?
- execute_trade:  do it, all or nothing
- classify:       sale, swap or mixed
- update_prices:  the end-of-day price rule (Decision 4)
- add_post / visible_posts: the shared board
"""

from __future__ import annotations

import random
from collections import Counter
from statistics import median

from .money import fmt
from .schemas import OfferSpec, PostSpec
from .state import Negotiation, Post, Trade, World


# ------------------------------------------------------------------ offers

def validate_offer(world: World, offerer: str, receiver: str, offer: OfferSpec,
                   check_receiver_money: bool = True) -> list[str]:
    """Every reason this offer can't happen, in plain words ([] means it's fine).

    The messages are written to the offerer ("you"), because from M2 they are
    sent back to the LLM so it can fix its offer.

    Agents can't see each other's money, so when an offer is *made* the
    receiver's money isn't checked (check_receiver_money=False): an offer they
    can't afford is turned down in the negotiation instead. At execution
    everything is checked.
    """
    if offerer == receiver:
        return ["you can't trade with yourself"]
    for agent_id in (offerer, receiver):
        if agent_id not in world.agents:
            return [f"there is no agent called {agent_id}"]

    errors = []
    for cid in sorted(set(offer.give_cards + offer.get_cards)):
        if cid not in world.cards:
            errors.append(f"there is no card {cid}")
    if errors:
        return errors

    if not offer.give_cards and offer.give_money == 0:
        errors.append("you must give something")
    if not offer.get_cards and offer.get_money == 0:
        errors.append("you must ask for something")
    if not offer.give_cards and not offer.get_cards:
        errors.append("a trade must include at least one card")

    me, them = world.agents[offerer], world.agents[receiver]
    cur = world.currency
    for cid, n in sorted(Counter(offer.give_cards).items()):
        if me.inventory[cid] < n:
            errors.append(f"you offered {n} x {cid} but you own {me.inventory[cid]}")
    if me.money < offer.give_money:
        errors.append(f"you offered {fmt(offer.give_money, cur)} but you have {fmt(me.money, cur)}")
    for cid, n in sorted(Counter(offer.get_cards).items()):
        if them.inventory[cid] < n:
            errors.append(f"you asked for {n} x {cid} but {receiver} owns {them.inventory[cid]}")
    if check_receiver_money and them.money < offer.get_money:
        errors.append(f"you asked for {fmt(offer.get_money, cur)} but {receiver} can't pay that much")
    return errors


def classify(a_cards: list[str], a_money: int, b_cards: list[str], b_money: int):
    """Sale, swap or mixed. Only sales set prices.

    A sale: one side gives only copies of a single card, the other side only money.
    Returns (kind, card_id, copies, unit_price).
    """
    def only_one_card(cards, money):
        return cards and money == 0 and len(set(cards)) == 1

    if only_one_card(a_cards, a_money) and not b_cards and b_money > 0:
        return "sale", a_cards[0], len(a_cards), b_money / len(a_cards)
    if only_one_card(b_cards, b_money) and not a_cards and a_money > 0:
        return "sale", b_cards[0], len(b_cards), a_money / len(b_cards)
    if a_money == 0 and b_money == 0:
        return "swap", None, 0, None
    return "mixed", None, 0, None


def execute_trade(world: World, neg: Negotiation) -> Trade | list[str]:
    """Carry out an accepted negotiation, or explain why it can no longer happen.

    Other trades earlier today may have used up the cards or money, so we
    check again now. All checks run before anything moves, so a trade happens
    completely or not at all.
    """
    a = neg.offerer
    b = neg.responder if a == neg.proposer else neg.proposer
    offer = neg.offer
    errors = validate_offer(world, a, b, offer)
    if errors:
        return errors

    giver, taker = world.agents[a], world.agents[b]
    giver.inventory.subtract(offer.give_cards)
    taker.inventory.update(offer.give_cards)
    taker.inventory.subtract(offer.get_cards)
    giver.inventory.update(offer.get_cards)
    giver.money += offer.get_money - offer.give_money
    taker.money += offer.give_money - offer.get_money
    giver.inventory, taker.inventory = +giver.inventory, +taker.inventory   # drop zero counts

    kind, card_id, copies, unit_price = classify(offer.give_cards, offer.give_money,
                                                 offer.get_cards, offer.get_money)
    # Value both sides at today's prices (prices only change at the end of the day),
    # so swaps and mixed trades can be checked for fairness later.
    trade = Trade(
        id=world.new_id("T"), day=world.day, negotiation_id=neg.id, a=a, b=b,
        a_cards=list(offer.give_cards), a_money=offer.give_money,
        b_cards=list(offer.get_cards), b_money=offer.get_money,
        kind=kind, card_id=card_id, copies=copies, unit_price=unit_price,
        value_a=sum(world.prices[c] for c in offer.give_cards) + offer.give_money,
        value_b=sum(world.prices[c] for c in offer.get_cards) + offer.get_money,
        # Happiness change for each side: what they got minus what they gave, at
        # their own personal values. Positive means the trade made them happier.
        happiness_a=(sum(giver.personal_value[c] for c in offer.get_cards) + offer.get_money
                     - sum(giver.personal_value[c] for c in offer.give_cards) - offer.give_money),
        happiness_b=(sum(taker.personal_value[c] for c in offer.give_cards) + offer.give_money
                     - sum(taker.personal_value[c] for c in offer.get_cards) - offer.get_money),
    )
    world.trades.append(trade)
    return trade


# ------------------------------------------------------------------ prices

def update_prices(prices: dict[str, float], sales: dict[str, list[float]], k: float) -> dict[str, float]:
    """Move each card's price part of the way towards today's median sale price.

        m = median of today's sale prices, n = number of sales
        w = n / (n + k)
        new price = old price + w * (m - old price)

    One sale only nudges the price; many sales move it most of the way.
    A card with no sales keeps its price.
    """
    new = dict(prices)
    for cid, unit_prices in sales.items():
        if not unit_prices:
            continue
        n, m = len(unit_prices), median(unit_prices)
        w = n / (n + k)
        new[cid] = prices[cid] + w * (m - prices[cid])
    return new


# ------------------------------------------------------------------- board

def add_post(world: World, author: str, spec: PostSpec) -> Post | str:
    agent = world.agents[author]
    if agent.posted_today:
        return "you have already posted today"
    if spec.card_id is not None and spec.card_id not in world.cards:
        return f"there is no card {spec.card_id}"
    post = Post(id=world.new_id("P"), day_created=world.day, author=author, kind=spec.kind,
                card_id=spec.card_id, price=spec.price, text=spec.text)
    world.board.append(post)
    agent.posted_today = True
    return post


def visible_posts(world: World, n: int, rng: random.Random) -> list[Post]:
    """The newest n posts from before today, newest day first.

    Posts from the same day have no natural order, so they are shuffled, to
    stop agents favouring whatever happens to be listed first.
    """
    older = [p for p in world.board if p.day_created < world.day]
    newest = older[-n:] if n else []
    by_day: dict[int, list[Post]] = {}
    for p in newest:
        by_day.setdefault(p.day_created, []).append(p)
    shown = []
    for day in sorted(by_day, reverse=True):
        same_day = by_day[day]
        rng.shuffle(same_day)
        shown.extend(same_day)
    return shown
