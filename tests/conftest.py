import shutil
from pathlib import Path

import pytest

from sim.config import load_config

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "config" / "scenarios" / "baseline.yaml"


@pytest.fixture
def config():
    return load_config(BASELINE, seed=1, agent_type="random")


@pytest.fixture
def config_copy(tmp_path):
    """A throwaway copy of config/ that a test can break on purpose."""
    dest = tmp_path / "config"
    shutil.copytree(ROOT / "config", dest)
    return dest
