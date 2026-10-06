import random
from dataclasses import asdict

from sim.agents import build_view
from sim.setup import build_world


def keys_anywhere(obj) -> set[str]:
    """Every dictionary key, however deeply nested."""
    if isinstance(obj, dict):
        return set(obj) | set().union(*(keys_anywhere(v) for v in obj.values()))
    if isinstance(obj, (list, tuple)):
        return set().union(*(keys_anywhere(v) for v in obj)) if obj else set()
    return set()


def test_uninformed_agents_never_see_prices(config):
    world = build_world(config)
    world.day = 1
    for a in world.agents.values():
        view = build_view(world, a, sorted(a.neighbours)[0], config, random.Random(0))
        if a.informed:
            assert view.prices == world.prices
            continue
        assert view.prices is None
        # Board posts may quote prices (that's market chatter, allowed).
        # Nothing else in the view may carry the official price list.
        rest = asdict(view)
        rest.pop("prices"), rest.pop("board")
        assert "prices" not in keys_anywhere(rest)
        assert "price" not in keys_anywhere(rest)


def test_views_can_reply_only_when_there_are_posts(config):
    world = build_world(config)
    world.day = 1
    a = world.agents["A01"]
    view = build_view(world, a, sorted(a.neighbours)[0], config, random.Random(0))
    assert "reply_to_post" not in view.valid_actions


def test_views_hide_partner_money_and_personal_values(config):
    world = build_world(config)
    world.day = 1
    words = {level.words for level in config.personas.desire_scale.values()}
    for a in world.agents.values():
        view = build_view(world, a, sorted(a.neighbours)[0], config, random.Random(0))
        assert not hasattr(view, "partner_money")
        assert "personal_value" not in keys_anywhere(asdict(view))
        assert set(view.desires) == set(world.cards)
        assert set(view.desires.values()) <= words          # desire reaches the agent as words only
        assert all(set(info) == {"name", "rarity"} for info in view.cards.values())
