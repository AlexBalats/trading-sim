import asyncio

from helpers import Scripted, offer, quiet_logger, small_world

from sim.engine import handle_decision, negotiate
from sim.schemas import Decision
from sim.state import Negotiation


def open_neg(world, o):
    return Negotiation(id="N1", day=world.day, proposer="A01", responder="A02",
                       origin="encounter", offer=o, offerer="A01",
                       messages=[{"from": "A01", "kind": "offer"}])


def run_neg(config, world, agents, neg):
    log = quiet_logger(config, world)
    asyncio.run(negotiate(world, config, agents, log, neg))
    return log


def test_accept(config):
    w = small_world(config)
    n = open_neg(w, offer(give_cards=["R01"], get_money=800))
    run_neg(config, w, {"A02": Scripted([("accept", None)])}, n)
    assert n.status == "accepted" and len(n.messages) == 2


def test_reject(config):
    w = small_world(config)
    n = open_neg(w, offer(give_cards=["R01"], get_money=800))
    run_neg(config, w, {"A02": Scripted([("reject", None)])}, n)
    assert n.status == "rejected"


def test_counter_then_accept(config):
    w = small_world(config)
    n = open_neg(w, offer(give_cards=["R01"], get_money=800))
    counter = offer(give_money=601, get_cards=["R01"])        # A02's side: £6.01 for the R01
    agents = {"A02": Scripted([("counter", counter)]), "A01": Scripted([("accept", None)])}
    run_neg(config, w, agents, n)
    assert n.status == "accepted"
    assert n.offerer == "A02" and n.offer == counter
    assert [m["kind"] for m in n.messages] == ["offer", "counter", "accept"]


def test_endless_counters_stop_at_limit(config):
    w = small_world(config)
    assert config.scenario.negotiation_max_messages == 4
    n = open_neg(w, offer(give_cards=["R01"], get_money=800))
    a2_counter = offer(give_money=600, get_cards=["R01"])
    a1_counter = offer(give_cards=["R01"], get_money=700)
    agents = {"A02": Scripted([("counter", a2_counter)] * 5), "A01": Scripted([("counter", a1_counter)] * 5)}
    log = run_neg(config, w, agents, n)
    assert n.status == "rejected"
    assert len(n.messages) == 4
    assert log.events[-1]["reason"] == "max_messages"


def test_invalid_counter_is_a_reject(config):
    w = small_world(config)
    n = open_neg(w, offer(give_cards=["R01"], get_money=800))
    bad = offer(give_money=2001, get_cards=["R01"])           # A02 only has £20.00
    run_neg(config, w, {"A02": Scripted([("counter", bad)])}, n)
    assert n.status == "rejected"


def test_incoming_cap(config):
    w = small_world(config)
    log = quiet_logger(config, w)
    cap = config.scenario.max_incoming_per_day
    d = Decision(reason="t", action="propose_trade", offer=offer(give_money=100, get_cards=["U01"]))
    opened = []
    for proposer in ["A01", "A03", "A04", "A05"][:cap + 1]:
        w.agents[proposer].money = 1000
        opened.append(handle_decision(w, config, log, proposer, d, "A02"))
    assert all(n is not None for n in opened[:cap])
    assert opened[cap] is None
    assert log.events[-1]["type"] == "auto_declined"


def test_offer_the_receiver_cant_afford_is_turned_down(config):
    w = small_world(config)
    n = Negotiation(id="N1", day=w.day, proposer="A01", responder="A03", origin="encounter",
                    offer=offer(give_cards=["R01"], get_money=501), offerer="A01",   # A03 has £5.00
                    messages=[{"from": "A01", "kind": "offer"}])
    log = run_neg(config, w, {"A03": Scripted([("accept", None)])}, n)
    assert n.status == "rejected"
    assert log.events[-1]["reason"] == "can't afford it"
