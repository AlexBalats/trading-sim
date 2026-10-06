"""The three charts for one run, drawn from the run folder alone.

They read only meta.json and daily.jsonl (never engine objects), so the same
code can later draw real class-game trades converted to the same format.
"""

from __future__ import annotations

import json
from pathlib import Path
from statistics import median

import matplotlib

matplotlib.use("Agg")   # draw to files, no window
import matplotlib.pyplot as plt

# Categorical colours, used in this fixed order (checked for colour-blind safety).
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
INK, INK_2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
LINESTYLES = ["-", "--", ":", "-."]


def load(run_dir: Path) -> tuple[dict, list[dict]]:
    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    daily = [json.loads(line) for line in (run_dir / "daily.jsonl").read_text(encoding="utf-8").splitlines() if line]
    return meta, daily


def style(ax, title: str, ylabel: str) -> None:
    ax.set_title(title, loc="left", color=INK, fontsize=12, pad=10)
    ax.set_xlabel("Day", color=INK_2)
    ax.set_ylabel(ylabel, color=INK_2)
    ax.set_facecolor(SURFACE)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK_2)


def currency_label(meta: dict) -> str:
    cur = meta.get("currency", "")
    return f"({cur})" if cur else ""


def draw_prices(meta: dict, daily: list[dict], out: Path) -> None:
    """One panel per rarity, each with its own price scale, so cheap cards'
    moves are visible too. One line per tracked card, coloured by tier;
    each sale is a faint dot."""
    days = [d["day"] for d in daily]
    rarity = dict(meta["card_rarity"])
    colour, tier_of = {}, {}
    for tier_i, (tier, card_ids) in enumerate(meta["tracked"]):
        for cid in card_ids:
            colour[cid], tier_of[cid] = SERIES[tier_i % len(SERIES)], tier
    tracked = [cid for _, ids in meta["tracked"] for cid in ids]
    rarities = [r for r in dict.fromkeys(r for _, r in meta["card_rarity"])
                if any(rarity[cid] == r for cid in tracked)]

    fig, axes = plt.subplots(len(rarities), 1, figsize=(10, 2.6 * len(rarities) + 0.8),
                             sharex=True, facecolor=SURFACE, squeeze=False)
    for ax, r in zip(axes[:, 0], rarities):
        top, bottom = 0.0, float("inf")
        for j, cid in enumerate(c for c in tracked if rarity[c] == r):
            prices = [d["prices"][cid] for d in daily]
            sale_days = [d["day"] for d in daily for _ in d["sales"].get(cid, [])]
            sale_prices = [p for d in daily for p in d["sales"].get(cid, [])]
            ax.plot(days, prices, color=colour[cid], linewidth=2, linestyle=LINESTYLES[j % len(LINESTYLES)],
                    label=f"{cid} {meta['card_names'].get(cid, '')} ({tier_of[cid]})", solid_capstyle="round")
            ax.scatter(sale_days, sale_prices, color=colour[cid], alpha=0.35, s=18, linewidths=0)
            top = max(top, max(prices), max(sale_prices, default=0))
            bottom = min(bottom, min(prices), min(sale_prices, default=bottom))
        pad = max((top - bottom) * 0.25, top * 0.05, 0.01)
        ax.set_ylim(max(0, bottom - pad), top + pad * 1.5)   # headroom: event markers go here in iteration 2
        style(ax, r, f"Price {currency_label(meta)}")
        ax.title.set_fontsize(10)
        ax.legend(fontsize=8, frameon=False, loc="upper left", bbox_to_anchor=(1.01, 1), labelcolor=INK)
    axes[-1, 0].set_xlim(days[0], days[-1])
    for ax in axes[:-1, 0]:
        ax.set_xlabel("")
    fig.suptitle("Prices of tracked cards by rarity (dots = individual sales)", x=0.01, ha="left",
                 color=INK, fontsize=12)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def draw_volume(meta: dict, daily: list[dict], out: Path) -> None:
    """Trades per day, split into sales, swaps and mixed trades."""
    fig, ax = plt.subplots(figsize=(10, 4.5), facecolor=SURFACE)
    days = [d["day"] for d in daily if d["day"] > 0]
    bottom = [0] * len(days)
    for i, kind in enumerate(["sale", "swap", "mixed"]):
        counts = [sum(t["kind"] == kind for t in d["trades"]) for d in daily if d["day"] > 0]
        ax.bar(days, counts, bottom=bottom, color=SERIES[i], width=0.7, label={"sale": "sales", "swap": "swaps", "mixed": "mixed"}[kind],
               edgecolor=SURFACE, linewidth=2)
        bottom = [b + c for b, c in zip(bottom, counts)]
    style(ax, "Trades per day", "Trades")
    ax.set_xticks(days)
    ax.legend(fontsize=9, frameon=False, ncols=3, loc="upper left", labelcolor=INK)
    ax.set_ylim(0, max(bottom, default=0) * 1.2 + 1)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def draw_wealth(meta: dict, daily: list[dict], out: Path) -> None:
    """Each agent's money + cards at that day's prices: poorest, middle, richest."""
    fig, ax = plt.subplots(figsize=(10, 4.5), facecolor=SURFACE)
    days = [d["day"] for d in daily]
    wealth = [[a["money"] + a["collection_value"] for a in d["agents"].values()] for d in daily]
    low, mid, high = [min(w) for w in wealth], [median(w) for w in wealth], [max(w) for w in wealth]
    ax.fill_between(days, low, high, color=SERIES[0], alpha=0.15, linewidth=0, label="poorest to richest")
    ax.plot(days, mid, color=SERIES[0], linewidth=2, label="median agent")
    ax.plot(days, low, color=SERIES[0], linewidth=1, alpha=0.6)
    ax.plot(days, high, color=SERIES[0], linewidth=1, alpha=0.6)
    style(ax, "Wealth: money + cards at current prices", f"Wealth {currency_label(meta)}")
    ax.set_ylim(0, max(high) * 1.15)
    ax.legend(fontsize=9, frameon=False, loc="upper left", labelcolor=INK)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def draw_all(run_dir: Path) -> list[Path]:
    run_dir = Path(run_dir)
    meta, daily = load(run_dir)
    charts = run_dir / "charts"
    charts.mkdir(exist_ok=True)
    paths = [charts / "prices.png", charts / "volume.png", charts / "wealth.png"]
    draw_prices(meta, daily, paths[0])
    draw_volume(meta, daily, paths[1])
    draw_wealth(meta, daily, paths[2])
    return paths
