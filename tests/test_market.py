import random

from helpers import offer, small_world

from sim.market import add_post, classify, execute_trade, validate_offer, visible_posts
from sim.schemas import PostSpec
from sim.state import Negotiation


# ------------------------------------------------------------ classification

def test_sale():
    assert classify(["R01"], 0, [], 8) == ("sale", "R01", 1, 8.0)
    assert classify([], 8, ["R01"], 0) == ("sale", "R01", 1, 8.0)


def test_sale_of_two_copies_has_unit_price():
    assert classify(["M01", "M01"], 0, [], 3) == ("sale", "M01", 2, 1.5)


def test_swap():
    assert classify(["R01"], 0, ["U01"], 0)[0] == "swap"


def test_mixed():
    assert classify(["R01"], 2, ["U01"], 0)[0] == "mixed"            # card + money for a card
    assert classify(["R01", "M01"], 0, [], 9)[0] == "mixed"          # two different cards for money


# ---------------------------------------------------------------- validation

def test_valid_offer(config):
    w = small_world(config)
    assert validate_offer(w, "A01", "A02", offer(give_cards=["R01"], get_money=800)) == []


def test_unowned_card(config):
    w = small_world(config)
    errors = validate_offer(w, "A01", "A02", offer(give_cards=["C01"], get_money=800))
    assert any("C01" in e and "own 0" in e for e in errors)


def test_too_few_copies(config):
    w = small_world(config)
    assert validate_offer(w, "A01", "A02", offer(give_cards=["R01"] * 3, get_money=800))


def test_not_enough_money(config):
    w = small_world(config)
    assert validate_offer(w, "A01", "A02", offer(give_money=1001, get_cards=["U01"]))
    assert validate_offer(w, "A01", "A03", offer(give_cards=["R01"], get_money=501))   # A03 has £5.00
    # When an offer is made, the receiver's money isn't checked: nobody can see it.
    assert validate_offer(w, "A01", "A03", offer(give_cards=["R01"], get_money=501), check_receiver_money=False) == []


def test_asking_for_what_partner_lacks(config):
    w = small_world(config)
    assert validate_offer(w, "A01", "A02", offer(give_money=500, get_cards=["M02"]))


def test_self_trade_and_unknowns(config):
    w = small_world(config)
    assert validate_offer(w, "A01", "A01", offer(give_cards=["R01"], get_money=100))
    assert validate_offer(w, "A01", "A99", offer(give_cards=["R01"], get_money=100))
    assert validate_offer(w, "A01", "A02", offer(give_cards=["ZZZ"], get_money=100))


def test_each_side_must_give_something(config):
    w = small_world(config)
    assert validate_offer(w, "A01", "A02", offer(get_cards=["U01"]))            # a gift request
    assert validate_offer(w, "A01", "A02", offer(give_cards=["R01"]))           # a gift
    assert validate_offer(w, "A01", "A02", offer(give_money=200, get_money=10000))  # money for money


# ----------------------------------------------------------------- execution

def neg(world, proposer, responder, o):
    return Negotiation(id="N1", day=world.day, proposer=proposer, responder=responder,
                       origin="encounter", offer=o, offerer=proposer, status="accepted")


def test_execute_moves_everything(config):
    w = small_world(config)
    t = execute_trade(w, neg(w, "A01", "A02", offer(give_cards=["R01"], give_money=100, get_cards=["U01"])))
    assert t.kind == "mixed"
    assert w.agents["A01"].inventory == {"R01": 1, "M01": 1, "U01": 1}
    assert w.agents["A02"].inventory == {"R01": 1}
    assert (w.agents["A01"].money, w.agents["A02"].money) == (900, 2100)
    assert t.value_a == w.prices["R01"] + 100 and t.value_b == w.prices["U01"]


def test_counter_offer_direction(config):
    """When the responder made the final offer, it is the giver of that offer."""
    w = small_world(config)
    n = neg(w, "A01", "A02", offer(give_cards=["U01"], get_money=401))
    n.offerer = "A02"
    t = execute_trade(w, n)
    assert (t.a, t.b, t.kind, t.unit_price) == ("A02", "A01", "sale", 401.0)
    assert w.agents["A01"].inventory["U01"] == 1 and w.agents["A01"].money == 599


def test_stale_trade_changes_nothing(config):
    w = small_world(config)
    first = neg(w, "A02", "A01", offer(give_cards=["U01"], get_money=500))
    second = neg(w, "A02", "A03", offer(give_cards=["U01"], get_money=500))   # the same single copy
    before = {a: (dict(x.inventory), x.money) for a, x in w.agents.items()}
    assert not isinstance(execute_trade(w, first), list)
    middle = {a: (dict(x.inventory), x.money) for a, x in w.agents.items()}
    errors = execute_trade(w, second)
    assert isinstance(errors, list) and errors
    after = {a: (dict(x.inventory), x.money) for a, x in w.agents.items()}
    assert after == middle != before
    assert len(w.trades) == 1


# --------------------------------------------------------------------- board

def test_one_post_per_day(config):
    w = small_world(config)
    assert not isinstance(add_post(w, "A01", PostSpec(kind="chat", text="hi")), str)
    assert isinstance(add_post(w, "A01", PostSpec(kind="chat", text="again")), str)


def test_posts_appear_next_day_newest_first(config):
    w = small_world(config)
    rng = random.Random(0)
    add_post(w, "A01", PostSpec(kind="chat", text="day 1"))
    assert visible_posts(w, 10, rng) == []                   # not on the day it was made
    w.day = 2
    w.agents["A02"].posted_today = False
    add_post(w, "A02", PostSpec(kind="chat", text="day 2"))
    w.day = 3
    shown = visible_posts(w, 10, rng)
    assert [p.text for p in shown] == ["day 2", "day 1"]
    assert [p.text for p in visible_posts(w, 1, rng)] == ["day 2"]   # capped at n


def test_receiver_money_never_shown_in_errors(config):
    """The error goes back to the offerer, so it mustn't reveal how much the other side has."""
    w = small_world(config)
    errors = validate_offer(w, "A01", "A03", offer(give_cards=["R01"], get_money=501))
    assert errors and not any("5.00" in e for e in errors)


def test_trade_records_happiness_change(config):
    w = small_world(config)
    a1, a2 = w.agents["A01"], w.agents["A02"]
    n = neg(w, "A01", "A02", offer(give_cards=["R01"], get_money=800))
    t = execute_trade(w, n)
    assert t.happiness_a == 800 - a1.personal_value["R01"]
    assert t.happiness_b == a2.personal_value["R01"] - 800
