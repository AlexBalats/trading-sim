import pytest

from sim.config import ConfigError, config_hash, load_config


def test_placeholder_config_loads(config):
    assert config.scenario.agent_type == "random"   # CLI-style override applied
    assert config.seed == 1
    assert len(config.cards.cards) == 24


def edit(path, old, new):
    text = path.read_text(encoding="utf-8")
    assert old in text, f"test setup: {old!r} not found in {path.name}"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def load(config_dir):
    return load_config(config_dir / "scenarios" / "baseline.yaml")


def test_misspelt_key_is_an_error(config_copy):
    edit(config_copy / "scenarios" / "baseline.yaml", "price_k: 2", "price_K: 2")
    with pytest.raises(ConfigError, match="price_K"):
        load(config_copy)


def test_mix_must_add_up_to_one(config_copy):
    edit(config_copy / "personas.yaml", "collector: 0.2,", "collector: 0.5,")
    with pytest.raises(ConfigError, match="add up to"):
        load(config_copy)


def test_mix_needs_defined_types(config_copy):
    edit(config_copy / "personas.yaml", "newcomer: 0.15}", "newbie: 0.15}")
    with pytest.raises(ConfigError, match="newbie"):
        load(config_copy)


def test_tracked_card_must_exist(config_copy):
    edit(config_copy / "cards.yaml", "hype_target: [R03]", "hype_target: [R99]")
    with pytest.raises(ConfigError, match="R99"):
        load(config_copy)


def test_duplicate_card_ids(config_copy):
    edit(config_copy / "cards.yaml", "id: C02,", "id: C01,")
    with pytest.raises(ConfigError, match="more than once"):
        load(config_copy)


def test_unknown_model(config_copy):
    edit(config_copy / "scenarios" / "baseline.yaml", "model: claude-haiku-4-5", "model: gpt-x")
    with pytest.raises(ConfigError, match="gpt-x"):
        load(config_copy)


def test_bad_informed_override(config_copy):
    edit(config_copy / "scenarios" / "baseline.yaml", "informed_override: {}", "informed_override: {Z9: true}")
    with pytest.raises(ConfigError, match="Z9"):
        load(config_copy)


def test_hash_changes_when_config_changes(config_copy):
    before = config_hash(load(config_copy).paths)
    edit(config_copy / "cards.yaml", "Velvet Comet", "Velvet Comet II")
    assert config_hash(load(config_copy).paths) != before


def test_money_must_be_whole_pennies(config_copy):
    edit(config_copy / "scenarios" / "baseline.yaml", "starting_money: 30 ", "starting_money: 30.005 ")
    with pytest.raises(ConfigError, match="penny"):
        load(config_copy)


def test_pennies_allowed(config_copy):
    edit(config_copy / "cards.yaml", "start_prices: {common: 1,", "start_prices: {common: 1.25,")
    assert load(config_copy).cards.start_prices["common"] == 1.25


def test_desire_must_be_on_the_scale(config_copy):
    edit(config_copy / "personas.yaml", "desire: {base: 5, favourite: 10,", "desire: {base: 5, favourite: 11,")
    with pytest.raises(ConfigError, match="desire 11"):
        load(config_copy)


def test_too_many_extra_desires(config_copy):
    edit(config_copy / "personas.yaml", "extra: {count: 3,", "extra: {count: 99,")
    with pytest.raises(ConfigError, match="99 extra cards"):
        load(config_copy)


def test_active_share_must_be_a_share(config_copy):
    edit(config_copy / "scenarios" / "baseline.yaml", "active_share: 0.5", "active_share: 1.5")
    with pytest.raises(ConfigError, match="active_share"):
        load(config_copy)
