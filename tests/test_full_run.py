import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from conftest import BASELINE, ROOT

from sim.engine import InvariantError, check_invariants, run
from sim.setup import build_world


def run_to(config, folder: Path):
    folder.mkdir()
    return asyncio.run(run(config, folder))


def test_invariants_hold_every_day(config, tmp_path):
    world, log = run_to(config, tmp_path / "r")
    start = log.daily[0]
    cards_at_start = sum(sum(a["inventory"].values()) for a in start["agents"].values())
    for day in log.daily:
        assert day["total_money"] == start["total_money"]
        assert sum(sum(a["inventory"].values()) for a in day["agents"].values()) == cards_at_start
        for a in day["agents"].values():
            assert a["money"] >= 0
            assert all(n > 0 for n in a["inventory"].values())
    assert len(world.trades) > 0, "a run with no trades at all suggests something is broken"


def test_same_seed_identical_logs(config, tmp_path):
    run_to(config, tmp_path / "a")
    run_to(config, tmp_path / "b")
    for name in ("events.jsonl", "daily.jsonl", "summary.json"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes(), name


def test_different_seed_different_logs(config, tmp_path):
    run_to(config, tmp_path / "a")
    config.seed = 2
    run_to(config, tmp_path / "b")
    assert (tmp_path / "a" / "daily.jsonl").read_bytes() != (tmp_path / "b" / "daily.jsonl").read_bytes()


def test_same_seed_identical_across_processes(tmp_path):
    """Python shuffles set order per process; this catches code that relies on it."""
    outputs = []
    for hash_seed in ("0", "12345"):
        out = tmp_path / f"h{hash_seed}"
        env = {**os.environ, "PYTHONHASHSEED": hash_seed}
        subprocess.run([sys.executable, "-m", "sim", "run", str(BASELINE), "--agent-type", "random",
                        "--seed", "1", "--dev", "--no-charts", "--out", str(out)],
                       cwd=ROOT, env=env, check=True, capture_output=True)
        (run_dir,) = out.glob("*/*")
        outputs.append((run_dir / "events.jsonl").read_bytes() + (run_dir / "daily.jsonl").read_bytes())
    assert outputs[0] == outputs[1]


def test_fast_enough(config):
    started = time.time()
    asyncio.run(run(config))
    assert time.time() - started < 5


def test_invariant_check_catches_leaks(config):
    world = build_world(config)
    money, cards = world.total_money(), world.card_counts()
    world.agents["A01"].money += 1
    with pytest.raises(InvariantError):
        check_invariants(world, money, cards)


def test_only_active_agents_decide(config):
    world, log = asyncio.run(run(config))
    expected = max(1, round(config.scenario.active_share * config.scenario.agents))
    for day in range(1, config.scenario.days + 1):
        deciders = [e for e in log.events if e["type"] == "decision" and e["day"] == day]
        assert len(deciders) == expected
