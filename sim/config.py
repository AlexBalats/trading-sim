"""Load the YAML files in config/ into checked, typed objects.

Why: a typo in a config file should stop the program at startup with a clear
message, not crash the simulation halfway through a run.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .money import to_pence


class ConfigError(Exception):
    """A problem in one of the YAML files, explained in plain words."""


class Strict(BaseModel):
    # Unknown keys are errors: a misspelt `price_K` must not silently fall back to a default.
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- cards.yaml

class PackSlot(Strict):
    count: int = Field(ge=1)
    rarity: str | None = None
    rarity_weights: dict[str, float] | None = None

    @model_validator(mode="after")
    def exactly_one_rarity_rule(self):
        if (self.rarity is None) == (self.rarity_weights is None):
            raise ValueError("a pack slot needs exactly one of 'rarity' or 'rarity_weights'")
        return self

    def rarities(self) -> list[str]:
        return [self.rarity] if self.rarity else list(self.rarity_weights)


class Pack(Strict):
    price: float = Field(ge=0)   # pounds
    slots: list[PackSlot] = Field(min_length=1)


class CardDef(Strict):
    id: str
    name: str
    rarity: str
    start_price: float | None = Field(default=None, ge=0)
    favourite_weight: float = Field(default=1.0, ge=0)


class CardsConfig(Strict):
    set_name: str
    pack: Pack
    start_prices: dict[str, float]
    cards: list[CardDef] = Field(min_length=1)
    tracked: dict[str, list[str]]

    @model_validator(mode="after")
    def cross_checks(self):
        ids = [c.id for c in self.cards]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"card ids used more than once: {dupes}")
        # Every amount of money must be whole pennies.
        to_pence(self.pack.price)
        for amount in self.start_prices.values():
            to_pence(amount)
        for c in self.cards:
            if c.start_price is not None:
                to_pence(c.start_price)
        for c in self.cards:
            if c.start_price is None and c.rarity not in self.start_prices:
                raise ValueError(f"card {c.id} has rarity '{c.rarity}', which has no entry in start_prices")
        rarities = {c.rarity for c in self.cards}
        for slot in self.pack.slots:
            for r in slot.rarities():
                if r not in rarities:
                    raise ValueError(f"a pack slot uses rarity '{r}', but no card has that rarity")
        for tier, card_ids in self.tracked.items():
            for cid in card_ids:
                if cid not in ids:
                    raise ValueError(f"tracked card {cid} (in '{tier}') is not in the card list")
        return self

    def start_price(self, card: CardDef) -> float:
        """In pounds, as written in the file."""
        return card.start_price if card.start_price is not None else self.start_prices[card.rarity]


# ------------------------------------------------------------- personas.yaml

Score = int | tuple[int, int]      # one desire score, or [low, high] for a random whole number


def score_range(score: Score) -> tuple[int, int]:
    return (score, score) if isinstance(score, int) else tuple(score)


class ExtraDesire(Strict):
    count: int = Field(ge=0)
    score: Score


class DesireRule(Strict):
    """How much one persona type wants each card, from 1 (not at all) to 10 (dream card)."""

    base: Score                    # every card, unless a line below says otherwise
    favourite: Score | None = None # the agent's favourite card (leave out: no special favourite)
    extra: ExtraDesire | None = None   # a few other cards, picked at random


class PersonaType(Strict):
    informed: bool
    text: str
    desire: DesireRule


class DesireLevel(Strict):
    multiplier: tuple[float, float]   # personal value = start price x a number in this range
    words: str                        # what the agent is told; never a price


class PersonasConfig(Strict):
    version: int
    desire_scale: dict[int, DesireLevel]
    types: dict[str, PersonaType] = Field(min_length=1)
    mix: dict[str, float] = Field(min_length=1)

    @model_validator(mode="after")
    def cross_checks(self):
        for level, d in self.desire_scale.items():
            lo, hi = d.multiplier
            if not 0 <= lo <= hi:
                raise ValueError(f"desire_scale {level}: multiplier must be [low, high] with 0 <= low <= high")
        for name, t in self.types.items():
            rule = t.desire
            scores = [rule.base, rule.favourite, rule.extra.score if rule.extra else None]
            for score in scores:
                if score is None:
                    continue
                lo, hi = score_range(score)
                if lo > hi:
                    raise ValueError(f"persona '{name}': desire range [{lo}, {hi}] has low above high")
                for level in range(lo, hi + 1):
                    if level not in self.desire_scale:
                        raise ValueError(f"persona '{name}' uses desire {level}, which is not in desire_scale")
        for name, share in self.mix.items():
            if name not in self.types:
                raise ValueError(f"mix uses persona type '{name}', which is not defined in types")
            if share < 0:
                raise ValueError(f"mix share for '{name}' is negative")
        total = sum(self.mix.values())
        if abs(total - 1) > 0.001:
            raise ValueError(f"mix shares add up to {total:.3f}, not 1")
        return self


# --------------------------------------------------------------- models.yaml

class ModelPrice(Strict):
    input: float = Field(ge=0)    # $ per million input tokens
    output: float = Field(ge=0)   # $ per million output tokens


class ModelsConfig(Strict):
    models: dict[str, ModelPrice]


# ------------------------------------------------------------ scenario yaml

class NetworkConfig(Strict):
    # groups: friendship groups + popular agents.  everyone: anyone can meet anyone
    # (then the three settings below are ignored).
    mode: Literal["groups", "everyone"] = "groups"
    group_size: tuple[int, int]
    popular_count: int = Field(ge=0)
    popular_links: int = Field(ge=1)

    @model_validator(mode="after")
    def sizes(self):
        lo, hi = self.group_size
        if not 2 <= lo <= hi:
            raise ValueError(f"group_size must be [min, max] with 2 <= min <= max, got {list(self.group_size)}")
        return self


class LLMSettings(Strict):
    concurrency: int = Field(default=8, ge=1)


class ScenarioConfig(Strict):
    name: str
    framing: Literal["adult", "kid"]
    agents: int = Field(ge=2)
    agent_type: Literal["llm", "random"]
    days: int = Field(ge=1)
    seeds: list[int] = Field(min_length=1)
    starting_packs: int = Field(ge=0)
    starting_money: float = Field(ge=0)    # pounds
    currency: str = "£"            # the label agents and charts see for money
    goal: str
    network: NetworkConfig
    informed_override: dict[str, bool] = {}
    active_share: float = Field(gt=0, le=1)   # share of agents who choose an action each day
    board_visible: int = Field(ge=0)
    max_incoming_per_day: int = Field(ge=0)
    negotiation_max_messages: int = Field(ge=1)
    price_k: float = Field(gt=0)
    recent_events: int = Field(ge=0)
    model: str
    llm: LLMSettings = LLMSettings()
    max_cost_usd: float = Field(gt=0)
    events: list = []

    @field_validator("starting_money", "max_cost_usd")
    @classmethod
    def whole_pennies(cls, v):
        to_pence(v)
        return v


# ------------------------------------------------------------------ loading

class Config(BaseModel):
    """Everything one run needs: the four files plus the chosen seed."""

    scenario: ScenarioConfig
    cards: CardsConfig
    personas: PersonasConfig
    models: ModelsConfig
    seed: int
    paths: list[Path]   # every YAML file used, for copying into the run folder

    def agent_ids(self) -> list[str]:
        width = max(2, len(str(self.scenario.agents)))
        return [f"A{i:0{width}d}" for i in range(1, self.scenario.agents + 1)]


def _read(path: Path, model: type[BaseModel]):
    if not path.exists():
        raise ConfigError(f"{path}: file not found")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ConfigError(f"{path}: not valid YAML\n{e}") from None
    try:
        return model.model_validate(data)
    except ValidationError as e:
        lines = []
        for err in e.errors():
            where = " -> ".join(str(p) for p in err["loc"]) or "(top level)"
            lines.append(f"  {where}: {err['msg']}")
        raise ConfigError(f"{path}: problems found\n" + "\n".join(lines)) from None


def load_config(scenario_path: str | Path, seed: int | None = None,
                agent_type: str | None = None) -> Config:
    """Read a scenario and the shared config files next to it.

    Layout: config/scenarios/<name>.yaml, with cards/personas/models.yaml in config/.
    `seed` and `agent_type` override the scenario file for this one run.
    """
    scenario_path = Path(scenario_path)
    config_dir = scenario_path.parent.parent
    paths = [scenario_path, config_dir / "cards.yaml",
             config_dir / "personas.yaml", config_dir / "models.yaml"]

    scenario = _read(paths[0], ScenarioConfig)
    if agent_type is not None:
        scenario = ScenarioConfig.model_validate({**scenario.model_dump(), "agent_type": agent_type})
    config = Config(
        scenario=scenario,
        cards=_read(paths[1], CardsConfig),
        personas=_read(paths[2], PersonasConfig),
        models=_read(paths[3], ModelsConfig),
        seed=seed if seed is not None else scenario.seeds[0],
        paths=paths,
    )
    _cross_file_checks(config)
    return config


def _cross_file_checks(config: Config) -> None:
    s = config.scenario
    if s.network.mode == "groups" and s.agents < s.network.group_size[0]:
        raise ConfigError(f"{s.agents} agents is fewer than the smallest friendship group ({s.network.group_size[0]})")
    if s.network.mode == "groups" and s.network.popular_count > s.agents:
        raise ConfigError(f"popular_count ({s.network.popular_count}) is more than the number of agents ({s.agents})")
    if s.model not in config.models.models:
        raise ConfigError(f"model '{s.model}' is not listed in models.yaml")
    for name, t in config.personas.types.items():
        extra = t.desire.extra
        if extra and extra.count > len(config.cards.cards) - 1:
            raise ConfigError(f"persona '{name}' wants {extra.count} extra cards, but the set only has "
                              f"{len(config.cards.cards)} cards")
    ids = set(config.agent_ids())
    for agent_id in s.informed_override:
        if agent_id not in ids:
            raise ConfigError(f"informed_override names '{agent_id}', but agent ids run "
                              f"{min(ids)}..{max(ids)}")


def config_hash(paths: list[Path]) -> str:
    """One fingerprint for the exact config of a run: any edit changes it."""
    h = hashlib.sha256()
    for p in paths:
        h.update(p.name.encode())
        h.update(p.read_bytes())
    return h.hexdigest()[:16]
