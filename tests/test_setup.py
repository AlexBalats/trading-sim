from collections import Counter

from sim.money import to_pence
from sim.setup import build_world, open_pack, persona_counts


def cards_per_pack(config):
    return sum(slot.count for slot in config.cards.pack.slots)


def test_every_agent_starts_the_same(config):
    world = build_world(config)
    s = config.scenario
    for a in world.agents.values():
        assert a.money == to_pence(s.starting_money)
        assert sum(a.inventory.values()) == s.starting_packs * cards_per_pack(config)
    assert world.total_money() == s.agents * to_pence(s.starting_money)


def test_pack_follows_slots(config):
    import random
    # Read from config, so this still holds after the card set is rewritten.
    # (Assumes no rarity appears in two different slots.)
    rarity = {c.id: c.rarity for c in config.cards.cards}
    for seed in range(50):
        pulled = Counter(rarity[cid] for cid in open_pack(config, random.Random(seed)))
        for slot in config.cards.pack.slots:
            assert sum(pulled[r] for r in slot.rarities()) == slot.count


def test_persona_counts_are_exact():
    mix = {"a": 0.2, "b": 0.15, "c": 0.15, "d": 0.2, "e": 0.15, "f": 0.15}
    assert persona_counts(mix, 20) == {"a": 4, "b": 3, "c": 3, "d": 4, "e": 3, "f": 3}
    for n in (7, 20, 30, 33, 100):
        assert sum(persona_counts(mix, n).values()) == n


def test_world_mix_matches_config(config):
    world = build_world(config)
    actual = Counter(a.persona_type for a in world.agents.values())
    assert actual == Counter(persona_counts(config.personas.mix, config.scenario.agents))
    for a in world.agents.values():
        assert a.informed == config.personas.types[a.persona_type].informed
        assert "{favourite_card}" not in a.persona_text


def test_groups(config):
    lo, hi = config.scenario.network.group_size
    for seed in range(30):
        config.seed = seed
        world = build_world(config)
        members = [a for g in world.groups for a in g]
        assert sorted(members) == sorted(world.agents)          # everyone in exactly one group
        for g in world.groups:
            assert lo <= len(g) <= hi + 1                        # +1 allowed for leftovers
        for a in world.agents.values():
            assert len(a.neighbours) >= 1
            assert a.id not in a.neighbours
            for n in a.neighbours:
                assert a.id in world.agents[n].neighbours       # friendships go both ways


def test_popular_agents_reach_other_groups(config):
    world = build_world(config)
    links = config.scenario.network.popular_links
    assert len(world.popular) == config.scenario.network.popular_count
    for p in world.popular:
        agent = world.agents[p]
        other_groups = {world.agents[n].group for n in agent.neighbours} - {agent.group}
        assert len(other_groups) >= min(links, len(world.groups) - 1)


def test_same_seed_same_world(config):
    def fingerprint(world):
        return [(a.id, a.persona_type, a.favourite_card, sorted(a.inventory.items()),
                 sorted(a.neighbours)) for a in world.agents.values()]

    assert fingerprint(build_world(config)) == fingerprint(build_world(config))
    config.seed = 2
    assert fingerprint(build_world(config)) != fingerprint(build_world(config.model_copy(update={"seed": 1})))


def test_everyone_mode_connects_all(config):
    config.scenario.network.mode = "everyone"
    world = build_world(config)
    n = len(world.agents)
    assert world.popular == []
    for a in world.agents.values():
        assert len(a.neighbours) == n - 1


def test_desires_follow_persona_rules(config):
    """Read from config, so this still holds after the personas are rewritten."""
    from sim.config import score_range
    for seed in range(10):
        config.seed = seed
        world = build_world(config)
        for a in world.agents.values():
            rule = config.personas.types[a.persona_type].desire
            assert set(a.desire) == set(world.cards)
            assert all(1 <= d <= 10 for d in a.desire.values())
            if rule.favourite is not None:
                lo, hi = score_range(rule.favourite)
                assert lo <= a.desire[a.favourite_card] <= hi
            if rule.extra is None and rule.favourite is None:
                lo, hi = score_range(rule.base)
                assert all(lo <= d <= hi for d in a.desire.values())


def test_personal_values_follow_the_scale(config):
    world = build_world(config)
    scale = config.personas.desire_scale
    for a in world.agents.values():
        for cid, level in a.desire.items():
            lo, hi = scale[level].multiplier
            start = world.cards[cid].start_price
            assert round(start * lo) <= a.personal_value[cid] <= round(start * hi)


def test_happiness_at_start(config):
    world = build_world(config)
    a = world.agents["A01"]
    assert world.happiness(a) == a.money + sum(a.personal_value[c] * n for c, n in a.inventory.items())
