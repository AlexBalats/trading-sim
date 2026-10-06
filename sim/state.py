"""Everything that exists in the simulated world, as plain data.

No rules live here - those are in market.py. This file only says what a card,
an agent, a post, a negotiation and a trade *are*.
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass, field

from .schemas import OfferSpec


@dataclass
class Card:
    id: str
    name: str
    rarity: str
    start_price: float     # pence
    favourite_weight: float


@dataclass
class Agent:
    id: str
    name: str
    agent_type: str            # "random" or "llm"
    persona_type: str
    persona_text: str          # with {favourite_card} already filled in
    favourite_card: str        # card id
    informed: bool             # sees the price list or not
    desire: dict[str, int] = field(default_factory=dict)          # card id -> 1..10, shown to it as words
    personal_value: dict[str, int] = field(default_factory=dict)  # card id -> pence; never shown to it
    money: int = 0             # in pence: 101 means £1.01 (see money.py)
    inventory: Counter = field(default_factory=Counter)   # card id -> copies
    neighbours: set[str] = field(default_factory=set)     # agent ids this agent can meet
    group: int = -1                                       # index of its friendship group
    events: list[dict] = field(default_factory=list)      # everything it took part in or saw
    posted_today: bool = False
    incoming_today: int = 0


@dataclass
class Post:
    id: str
    day_created: int           # visible to others from the next day
    author: str
    kind: str                  # buying / selling / chat
    card_id: str | None
    price: int | None
    text: str


@dataclass
class Negotiation:
    """Offers going back and forth between two agents.

    `offer` is the offer currently on the table, written from the side of
    `offerer`. A counter-offer swaps who is the offerer.
    """

    id: str
    day: int
    proposer: str              # who started it
    responder: str
    origin: str                # "encounter" or "post:<post id>"
    offer: OfferSpec
    offerer: str
    messages: list[dict] = field(default_factory=list)
    status: str = "open"       # open / accepted / rejected


@dataclass
class Trade:
    id: str
    day: int
    negotiation_id: str
    a: str                     # gives a_cards + a_money
    b: str                     # gives b_cards + b_money
    a_cards: list[str]
    a_money: int
    b_cards: list[str]
    b_money: int
    kind: str                  # sale / swap / mixed
    card_id: str | None = None         # sales only: which card was sold
    copies: int = 0                    # sales only
    unit_price: float | None = None    # sales only: pence per copy
    value_a: float = 0.0               # what a gave, at that day's prices
    value_b: float = 0.0               # what b gave, at that day's prices
    happiness_a: int = 0               # change in a's happiness from this trade (pence)
    happiness_b: int = 0               # change in b's happiness from this trade (pence)


@dataclass
class World:
    seed: int
    rng: random.Random
    cards: dict[str, Card]
    agents: dict[str, Agent]
    prices: dict[str, float]           # pence; can be fractional (an average of sales)
    currency: str
    tracked: dict[str, list[str]]      # tier -> card ids, from cards.yaml
    groups: list[list[str]] = field(default_factory=list)
    popular: list[str] = field(default_factory=list)
    day: int = 0
    board: list[Post] = field(default_factory=list)
    trades: list[Trade] = field(default_factory=list)
    id_counters: Counter = field(default_factory=Counter)

    def new_id(self, prefix: str) -> str:
        self.id_counters[prefix] += 1
        return f"{prefix}{self.id_counters[prefix]}"

    def total_money(self) -> int:
        return sum(a.money for a in self.agents.values())

    def card_counts(self) -> Counter:
        total = Counter()
        for a in self.agents.values():
            total.update(a.inventory)
        return +total   # drop zero entries

    def collection_value(self, agent: Agent) -> float:
        return sum(self.prices[cid] * n for cid, n in agent.inventory.items())

    def happiness(self, agent: Agent) -> int:
        """Money left plus what the cards held are worth *to this agent* (pence).

        Uses personal values from desire scores, not market prices, so a
        collector who overpays for their dream card can still end up happier.
        """
        return agent.money + sum(agent.personal_value[cid] * n for cid, n in agent.inventory.items())
