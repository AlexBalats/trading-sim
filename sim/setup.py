"""Build the world on day 0: agents, personas, starting packs, friendships, prices.

Every random choice here comes from one random.Random(seed), always in the
same order (personas, then each agent's favourite and desires, packs, network).
That is what makes the same seed build the same world every time.
"""

from __future__ import annotations

import random
from collections import Counter

from .config import Config, score_range
from .money import fmt, to_pence
from .state import Agent, Card, World


def build_world(config: Config) -> World:
    rng = random.Random(config.seed)
    cards = {c.id: Card(c.id, c.name, c.rarity, to_pence(config.cards.start_price(c)), c.favourite_weight)
             for c in config.cards.cards}
    world = World(
        seed=config.seed,
        rng=rng,
        cards=cards,
        agents={},
        prices={cid: float(card.start_price) for cid, card in cards.items()},
        currency=config.scenario.currency,
        tracked=config.cards.tracked,
    )
    for agent in make_agents(config, cards, rng):
        world.agents[agent.id] = agent
    open_starting_packs(config, world)
    build_network(config, world)
    return world


def persona_counts(mix: dict[str, float], n: int) -> dict[str, int]:
    """Turn shares into whole agents, as close to the shares as possible.

    Largest-remainder rounding: everyone gets the whole part of their share,
    then the leftover agents go to the biggest fractional parts. Using exact
    counts (not a random draw per agent) means every seed has the same mix,
    so the mix isn't another source of noise between runs.
    """
    exact = {name: share * n for name, share in mix.items()}
    counts = {name: int(x) for name, x in exact.items()}
    leftover = n - sum(counts.values())
    by_remainder = sorted(mix, key=lambda name: exact[name] - counts[name], reverse=True)
    for name in by_remainder[:leftover]:
        counts[name] += 1
    return counts


def make_agents(config: Config, cards: dict[str, Card], rng: random.Random) -> list[Agent]:
    s, personas = config.scenario, config.personas
    types = [name for name, count in persona_counts(personas.mix, s.agents).items()
             for _ in range(count)]
    rng.shuffle(types)

    card_ids = list(cards)
    weights = [cards[cid].favourite_weight for cid in card_ids]

    agents = []
    for agent_id, persona_type in zip(config.agent_ids(), types):
        favourite = rng.choices(card_ids, weights=weights)[0]
        persona = personas.types[persona_type]
        desire = draw_desires(persona.desire, favourite, card_ids, weights, rng)
        agents.append(Agent(
            id=agent_id,
            name=f"Agent {agent_id[1:]}",
            agent_type=s.agent_type,
            persona_type=persona_type,
            persona_text=persona.text.replace("{favourite_card}", cards[favourite].name),
            favourite_card=favourite,
            informed=s.informed_override.get(agent_id, persona.informed),
            desire=desire,
            personal_value=personal_values(desire, cards, personas.desire_scale, rng),
            money=to_pence(s.starting_money),
        ))
    return agents


def draw_score(score, rng: random.Random) -> int:
    lo, hi = score_range(score)
    return rng.randint(lo, hi)


def draw_desires(rule, favourite: str, card_ids: list[str], weights: list[float],
                 rng: random.Random) -> dict[str, int]:
    """How much this agent wants each card (1-10), following its persona's desire rule."""
    desire = {cid: draw_score(rule.base, rng) for cid in card_ids}
    taken = set()
    if rule.favourite is not None:
        desire[favourite] = draw_score(rule.favourite, rng)
        taken.add(favourite)
    if rule.extra is not None:
        # Pick distinct cards, more popular cards (favourite_weight) more often.
        for _ in range(rule.extra.count):
            pool = [(c, w) for c, w in zip(card_ids, weights) if c not in taken and w > 0]
            if not pool:
                break
            cid = rng.choices([c for c, _ in pool], weights=[w for _, w in pool])[0]
            desire[cid] = draw_score(rule.extra.score, rng)
            taken.add(cid)
    return desire


def personal_values(desire: dict[str, int], cards: dict[str, Card], scale, rng: random.Random) -> dict[str, int]:
    """What each card is worth to this agent, in pence: start price x a multiplier
    drawn from its desire level's range. Fixed for the whole run."""
    out = {}
    for cid, level in desire.items():
        lo, hi = scale[level].multiplier
        out[cid] = round(cards[cid].start_price * rng.uniform(lo, hi))
    return out


def open_pack(config: Config, rng: random.Random) -> list[str]:
    """One pack: for each slot, pick the rarity, then a card of that rarity at random."""
    by_rarity: dict[str, list[str]] = {}
    for c in config.cards.cards:
        by_rarity.setdefault(c.rarity, []).append(c.id)

    pulled = []
    for slot in config.cards.pack.slots:
        for _ in range(slot.count):
            if slot.rarity is not None:
                rarity = slot.rarity
            else:
                names = list(slot.rarity_weights)
                rarity = rng.choices(names, weights=[slot.rarity_weights[r] for r in names])[0]
            pulled.append(rng.choice(by_rarity[rarity]))
    return pulled


def open_starting_packs(config: Config, world: World) -> None:
    for agent in world.agents.values():
        for _ in range(config.scenario.starting_packs):
            agent.inventory.update(open_pack(config, world.rng))


def build_network(config: Config, world: World) -> None:
    """Friendship groups, plus a few popular agents with friends in other groups.

    Groups: shuffle everyone, then cut off groups with sizes drawn from
    group_size. Anyone left over (too few for a whole group) joins an existing
    group, one per group. Everyone in a group can meet everyone else in it.
    Popular agents also get one friend in each of `popular_links` other groups,
    which is how news and trades can cross between groups.
    """
    net, rng = config.scenario.network, world.rng
    lo, hi = net.group_size

    if net.mode == "everyone":
        # One big group: no friendships, no popular agents, anyone can meet anyone.
        everyone = sorted(world.agents)
        for a in everyone:
            world.agents[a].group = 0
            world.agents[a].neighbours = set(everyone) - {a}
        world.groups, world.popular = [everyone], []
        return

    ids = sorted(world.agents)
    rng.shuffle(ids)
    groups: list[list[str]] = []
    i = 0
    while len(ids) - i >= lo:
        size = min(rng.randint(lo, hi), len(ids) - i)
        groups.append(ids[i:i + size])
        i += size
    for j, agent_id in enumerate(ids[i:]):
        groups[j % len(groups)].append(agent_id)

    for g, members in enumerate(groups):
        for a in members:
            world.agents[a].group = g
            world.agents[a].neighbours.update(m for m in members if m != a)

    popular = rng.sample(sorted(world.agents), net.popular_count)
    for p in popular:
        own = world.agents[p].group
        others = [g for g in range(len(groups)) if g != own]
        for g in rng.sample(others, min(net.popular_links, len(others))):
            friend = rng.choice(groups[g])
            world.agents[p].neighbours.add(friend)
            world.agents[friend].neighbours.add(p)

    world.groups = groups
    world.popular = popular


def describe_world(world: World, config: Config) -> str:
    """A readable summary of day 0, for checking a config by eye."""
    lines = [f"World for scenario '{config.scenario.name}', seed {world.seed}", ""]

    counts = Counter(a.persona_type for a in world.agents.values())
    informed = sum(a.informed for a in world.agents.values())
    lines.append("Personas: " + ", ".join(f"{t} {counts[t]}" for t in config.personas.mix)
                 + f"   ({informed}/{len(world.agents)} informed)")

    lines.append("")
    lines.append("Friendship groups:")
    for g, members in enumerate(world.groups):
        lines.append(f"  group {g + 1} ({len(members)}): " + ", ".join(sorted(members)))
    lines.append("Popular agents: " + ", ".join(
        f"{p} (friends in groups {sorted({world.agents[n].group + 1 for n in world.agents[p].neighbours})})"
        for p in sorted(world.popular)))

    lines.append("")
    total = world.card_counts()
    cur = config.scenario.currency
    lines.append(f"Cards in circulation: {sum(total.values())}   money: {fmt(world.total_money(), cur)}")
    for rarity in dict.fromkeys(c.rarity for c in world.cards.values()):
        ids = [cid for cid, c in world.cards.items() if c.rarity == rarity]
        lines.append(f"  {rarity:9s} " + "  ".join(f"{cid}x{total[cid]}" for cid in ids))

    lines.append("")
    lines.append("Agents:")
    for a in sorted(world.agents.values(), key=lambda a: a.id):
        value = world.collection_value(a)
        liked = sorted((cid for cid, d in a.desire.items() if d >= 7), key=lambda cid: -a.desire[cid])
        wants = "  wants " + " ".join(f"{cid}:{a.desire[cid]}" for cid in liked) if liked else ""
        lines.append(f"  {a.id} {a.persona_type:9s} {'informed  ' if a.informed else 'uninformed'}"
                     f" group {a.group + 1}  fav {a.favourite_card}  money {fmt(a.money, cur)}"
                     f"  cards {sum(a.inventory.values())} (worth {fmt(value, cur)})"
                     f"  happiness {fmt(world.happiness(a), cur)}  meets {len(a.neighbours)}{wants}")
    return "\n".join(lines)
