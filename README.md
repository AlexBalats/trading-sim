# Trading Sim

An agent-based simulation of a small trading-card market. The full brief is `../trading-sim-mvp.md`. The M1 build plan is `../planning/m1-plan.md`.

**`config/` is the designer's** (cards, personas, scenarios). **`sim/` and `analysis/` are the engine.** No card name, persona or number from config ever appears in the Python code, and a test enforces this.

## Setup

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

## Commands

```
python -m sim world config/scenarios/baseline.yaml --seed 1                  # look at the starting world
python -m sim run config/scenarios/baseline.yaml --agent-type random --seed 1 --dev
python -m sim run config/scenarios/baseline.yaml --seed 1 --prediction predictions/<date>-baseline.md
python -m analysis plot runs/baseline/<run folder>                           # redraw charts
python -m pytest                                                             # all tests
```

Each run writes a folder under `runs/<scenario>/` containing:
- the config used;
- `meta.json`;
- `events.jsonl` (everything that happened);
- `daily.jsonl` (the state at the end of each day, day 0 included);
- `summary.json`;
- `charts/`.

## Where to start reading

`sim/engine.py`: the `run` function is the whole day loop, top to bottom.
