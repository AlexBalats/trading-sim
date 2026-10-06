"""What an agent is allowed to say.

Random agents build these directly. From M2, the LLM's structured output is
checked against these same models, so both kinds of agent speak one language.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OfferSpec(Schema):
    """A trade offer, always from the side of whoever makes it.

    Repeated card ids mean several copies: [id, id] is two copies of that card.
    """

    give_cards: list[str] = []
    give_money: int = Field(default=0, ge=0)
    get_cards: list[str] = []
    get_money: int = Field(default=0, ge=0)

    def flipped(self) -> OfferSpec:
        """The same trade seen from the other side."""
        return OfferSpec(give_cards=self.get_cards, give_money=self.get_money,
                         get_cards=self.give_cards, get_money=self.give_money)


class PostSpec(Schema):
    kind: Literal["buying", "selling", "chat"]
    card_id: str | None = None
    price: int | None = Field(default=None, ge=0)
    text: str


class Valuation(Schema):
    """Willingness to pay: the most for a card you lack, the least for one you own."""

    card_id: str
    max_buy: int | None = None
    min_sell: int | None = None


class Decision(Schema):
    """An agent's one action for the day."""

    reason: str
    action: Literal["propose_trade", "reply_to_post", "post", "pass"]
    offer: OfferSpec | None = None
    post_id: str | None = None
    post: PostSpec | None = None
    valuations: list[Valuation] = []


class NegotiationResponse(Schema):
    reason: str
    response: Literal["accept", "reject", "counter"]
    counter_offer: OfferSpec | None = None
    valuations: list[Valuation] = []
