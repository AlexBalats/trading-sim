"""Small tools shared by the tests."""

from collections import Counter

from sim.agents import BaseAgent
from sim.logger import RunLogger
from sim.schemas import NegotiationResponse, OfferSpec
from sim.setup import build_world


def small_world(config):
    """The seed-1 world, with A01-A03 given simple known holdings. Money is in pence."""
    world = build_world(config)
    world.day = 1
    world.agents["A01"].inventory = Counter({"R01": 2, "M01": 1})
    world.agents["A01"].money = 1000
    world.agents["A02"].inventory = Counter({"U01": 1})
    world.agents["A02"].money = 2000
    world.agents["A03"].inventory = Counter({"M02": 3})
    world.agents["A03"].money = 500
    return world


def quiet_logger(config, world):
    return RunLogger(None, config, world)


def offer(**kw) -> OfferSpec:
    return OfferSpec(**kw)


class Scripted(BaseAgent):
    """Gives pre-written responses in order, for testing negotiations."""

    def __init__(self, responses):
        self.responses = list(responses)

    async def respond(self, view, negotiation):
        response, counter = self.responses.pop(0)
        return NegotiationResponse(reason="scripted", response=response, counter_offer=counter)
