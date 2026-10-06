"""Command line: python -m analysis <command> ...

  plot <run_dir>     (re)draw the three charts for one run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .plots import draw_all


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m analysis")
    commands = parser.add_subparsers(dest="command", required=True)
    plot = commands.add_parser("plot", help="draw the charts for one run")
    plot.add_argument("run_dir", type=Path)
    args = parser.parse_args(argv)

    if args.command == "plot":
        for p in draw_all(args.run_dir):
            print(p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
