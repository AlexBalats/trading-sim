import pytest

from sim.money import fmt, to_pence, to_pounds


def test_round_trip():
    for pounds in (0, 0.01, 1.01, 30, 25.5, 99.99):
        assert to_pounds(to_pence(pounds)) == pounds


def test_sub_penny_rejected():
    with pytest.raises(ValueError):
        to_pence(1.005)


def test_format():
    assert fmt(101, "£") == "£1.01"
    assert fmt(3000, "£") == "£30.00"
    assert fmt(250, "tokens") == "2.50 tokens"
