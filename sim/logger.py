"""Writes everything that happens in a run to its run folder.

events.jsonl and daily.jsonl hold no clock times or folder paths, so two runs
with the same seed produce byte-identical files. Times live in meta.json only.
"""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from .config import Config, config_hash
from .money import to_pounds
from .state import World

# Events that go into an agent's own memory (the "last 3 events" in M3 prompts).
MEMORY_EVENTS = {"offer", "counter", "accept", "reject", "auto_declined", "trade", "trade_failed_stale"}


def dumps(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def make_run_dir(root: Path, config: Config) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = root / config.scenario.name / f"{stamp}_{config.scenario.agent_type}_seed{config.seed}"
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def git_hash(folder: Path) -> str:
    try:
        out = subprocess.run(["git", "-C", str(folder), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=5)
        dirty = subprocess.run(["git", "-C", str(folder), "status", "--porcelain"],
                               capture_output=True, text=True, timeout=5).stdout.strip()
        return (out.stdout.strip() or "no-commits") + ("-dirty" if dirty else "")
    except (OSError, subprocess.SubprocessError):
        return "unknown"


class RunLogger:
    """Pass run_dir=None to keep logs in memory only (used by fast tests)."""

    def __init__(self, run_dir: Path | None, config: Config, world: World, prediction: Path | None = None):
        self.run_dir, self.config, self.world = run_dir, config, world
        self.seq = 0
        self.events: list[dict] = []     # also kept in memory, for tests and the summary
        self.daily: list[dict] = []
        self.meta = {
            "scenario": config.scenario.name,
            "agent_type": config.scenario.agent_type,
            "seed": config.seed,
            "model": config.scenario.model if config.scenario.agent_type == "llm" else None,
            "persona_version": config.personas.version,
            "config_hash": config_hash(config.paths),
            "code_version": git_hash(Path(__file__).resolve().parents[1]),
            "python": platform.python_version(),
            "started": datetime.now().isoformat(timespec="seconds"),
            # So charts can be drawn from the run folder alone:
            "currency": config.scenario.currency,
            "money_unit": "pounds",   # every amount in the logs is in pounds
            "tracked": [[tier, ids] for tier, ids in config.cards.tracked.items()],   # a list keeps the config order
            "card_names": {c.id: c.name for c in config.cards.cards},
            "card_rarity": [[c.id, c.rarity] for c in config.cards.cards],   # a list keeps the config order
        }
        if run_dir is None:
            return
        (run_dir / "config").mkdir()
        for p in config.paths:
            shutil.copy(p, run_dir / "config" / p.name)
        (run_dir / "config" / "hash.txt").write_text(self.meta["config_hash"] + "\n")
        if prediction is not None:
            shutil.copy(prediction, run_dir / "prediction.md")
        for name in ("events.jsonl", "daily.jsonl", "llm_calls.jsonl"):
            (run_dir / name).write_text("")
        self._write_json("meta.json", self.meta)

    def _append(self, name: str, record: dict) -> None:
        if self.run_dir is not None:
            with open(self.run_dir / name, "a", encoding="utf-8") as f:
                f.write(dumps(record) + "\n")

    def _write_json(self, name: str, obj) -> None:
        if self.run_dir is not None:
            (self.run_dir / name).write_text(json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False),
                                             encoding="utf-8")

    def event(self, type_: str, agents: list[str], **data) -> dict:
        """Record one thing that happened. `agents` are everyone involved."""
        self.seq += 1
        record = {"seq": self.seq, "day": self.world.day, "type": type_, "agents": agents, **data}
        self.events.append(record)
        self._append("events.jsonl", record)
        if type_ in MEMORY_EVENTS:
            for a in agents:
                self.world.agents[a].events.append(record)
        return record

    def day(self, world: World, sales: dict[str, list[float]], seen_posts: dict[str, list[str]]) -> None:
        today = [t for t in world.trades if t.day == world.day]
        record = {
            "day": world.day,
            "prices": {cid: to_pounds(p) for cid, p in world.prices.items()},
            "sales": {cid: [to_pounds(x) for x in xs] for cid, xs in sales.items() if xs},
            "agents": {
                a.id: {
                    "money": to_pounds(a.money),
                    "inventory": dict(sorted(a.inventory.items())),
                    "informed": a.informed,
                    "persona": a.persona_type,
                    "collection_value": to_pounds(world.collection_value(a)),
                    "happiness": to_pounds(world.happiness(a)),
                } for a in sorted(world.agents.values(), key=lambda a: a.id)
            },
            "trades": [{"id": t.id, "a": t.a, "b": t.b, "kind": t.kind, "card": t.card_id,
                        "copies": t.copies, "unit_price": None if t.unit_price is None else to_pounds(t.unit_price),
                        "a_gives": {"cards": t.a_cards, "money": to_pounds(t.a_money)},
                        "b_gives": {"cards": t.b_cards, "money": to_pounds(t.b_money)},
                        "value_a": to_pounds(t.value_a), "value_b": to_pounds(t.value_b),
                        "happiness_a": to_pounds(t.happiness_a), "happiness_b": to_pounds(t.happiness_b)}
                       for t in today],
            "posts": [{**vars(p), "price": None if p.price is None else to_pounds(p.price)}
                      for p in world.board if p.day_created == world.day],
            "seen_posts": seen_posts,
            "total_money": to_pounds(world.total_money()),
        }
        self.daily.append(record)
        self._append("daily.jsonl", record)

    def finish(self, world: World, summary: dict) -> None:
        self.meta["finished"] = datetime.now().isoformat(timespec="seconds")
        self._write_json("meta.json", self.meta)
        self._write_json("summary.json", summary)
