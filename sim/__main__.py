"""Command line: python -m sim <command> ...

  world <scenario.yaml> [--seed N]
      Print the day-0 world, to check a config by eye.

  run <scenario.yaml> [--seed N] [--agent-type random|llm] [--dev | --prediction FILE] [--out runs]
      Run a simulation. A real run (without --dev) needs a prediction file,
      written before the run, which is copied into the run folder.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

from .config import ConfigError, load_config
from .engine import run
from .logger import make_run_dir
from .money import fmt
from .setup import build_world, describe_world


def main(argv: list[str] | None = None) -> int:
    # Windows pipes default to an old code page that can't show "£" properly.
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="python -m sim")
    commands = parser.add_subparsers(dest="command", required=True)

    world_cmd = commands.add_parser("world", help="print the day-0 world for a scenario")
    world_cmd.add_argument("scenario")
    world_cmd.add_argument("--seed", type=int)

    run_cmd = commands.add_parser("run", help="run a simulation")
    run_cmd.add_argument("scenario")
    run_cmd.add_argument("--seed", type=int)
    run_cmd.add_argument("--agent-type", choices=["random", "llm"])
    run_cmd.add_argument("--dev", action="store_true", help="a test run: no prediction needed")
    run_cmd.add_argument("--prediction", type=Path, help="the dated prediction written before this run")
    run_cmd.add_argument("--out", type=Path, default=Path("runs"))
    run_cmd.add_argument("--no-charts", action="store_true")

    args = parser.parse_args(argv)
    try:
        config = load_config(args.scenario, seed=args.seed, agent_type=getattr(args, "agent_type", None))
    except ConfigError as e:
        print(f"Config problem:\n{e}", file=sys.stderr)
        return 2

    if args.command == "world":
        print(describe_world(build_world(config), config))
        return 0

    if not args.dev and args.prediction is None:
        print("A real run needs --prediction <file> (written before the run). Use --dev for a test run.",
              file=sys.stderr)
        return 2
    if args.prediction is not None and not args.prediction.exists():
        print(f"Prediction file not found: {args.prediction}", file=sys.stderr)
        return 2

    run_dir = make_run_dir(args.out, config)
    started = time.time()
    try:
        world, log = asyncio.run(run(config, run_dir, args.prediction))
    except NotImplementedError as e:
        print(e, file=sys.stderr)
        return 2
    if not args.no_charts:
        from analysis.plots import draw_all
        draw_all(run_dir)
    report(world, log, config, run_dir, time.time() - started)
    return 0


def report(world, log, config, run_dir: Path, seconds: float) -> None:
    import json
    s = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    cur = config.scenario.currency
    t = s["trades"]
    print(f"{config.scenario.name}, {config.scenario.agent_type} agents, seed {config.seed}: "
          f"{s['agents']} agents x {s['days']} days in {seconds:.1f}s")
    print(f"Trades: {t['total']} ({t['sale']} sales, {t['swap']} swaps, {t['mixed']} mixed)   "
          f"offers {s['offers']}, accepted {s['accepted']}, rejected {s['rejected']}, "
          f"auto-declined {s['auto_declined']}, failed stale {s['failed_stale']}, invalid {s['invalid_actions']}")
    print("Tracked cards, start -> end price (number of sales):")
    for tier, ids in world.tracked.items():
        for cid in ids:
            start = world.cards[cid].start_price
            print(f"  {tier:14s} {cid} {world.cards[cid].name:16s} "
                  f"{fmt(start, cur):>7s} -> {fmt(world.prices[cid], cur):>7s}  ({s['tracked_sales'][cid]} sales)")
    h = s["happiness_change_mean"]
    print("Mean happiness change: " + ", ".join(f"{k} {v:+.2f}" for k, v in h["by_persona"].items()))
    print("                       " + ", ".join(f"{k} {v:+.2f}" for k, v in h["by_knowledge"].items()))
    print(f"Invariants: {s['invariants']}   Cost: ${s['cost_usd']:.2f}")
    print(f"Run folder: {run_dir}")


if __name__ == "__main__":
    sys.exit(main())
