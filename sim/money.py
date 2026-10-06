"""Money is stored as whole pence, so totals are always exact.

Computers can't add decimal pounds exactly (0.1 + 0.2 is not quite 0.3), and
"the total money never changes" must hold exactly. So inside the engine 101
means £1.01. Config files, logs and charts all use pounds; this file is the
only place that converts between the two.
"""

from __future__ import annotations


def to_pence(pounds: float) -> int:
    pence = round(pounds * 100)
    if abs(pounds * 100 - pence) > 1e-6:
        raise ValueError(f"{pounds} has more than 2 decimal places; money goes down to the penny")
    return pence


def to_pounds(pence: float) -> float:
    return round(pence / 100, 4)


def fmt(pence: float, currency: str) -> str:
    """'£1.01' for a symbol, '1.01 tokens' for a word."""
    amount = f"{pence / 100:.2f}"
    return f"{currency}{amount}" if len(currency) == 1 else f"{amount} {currency}"


def offer_in_pounds(offer) -> dict:
    d = offer.model_dump()
    d["give_money"], d["get_money"] = to_pounds(d["give_money"]), to_pounds(d["get_money"])
    return d


def valuations_in_pounds(valuations) -> list[dict]:
    out = []
    for v in valuations:
        d = v.model_dump(exclude_none=True)
        for key in ("max_buy", "min_sell"):
            if key in d:
                d[key] = to_pounds(d[key])
        out.append(d)
    return out
