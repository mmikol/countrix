"""The load: every data table read into one World, fresh on each request, so
the facts layer always reads what the data layer stored.

    world = tables.load(cx)

Loading is 25 queries and a few thousand rows; cheap enough to do per
click, and it is what lets the inference layer's solver evaluate thousands
of candidate compositions without a query each. Each read step fills one
part of the World from its tables, and load runs them in the order each
relies on, then derives what the rows imply. Every data table is named
here: a test greps this module's source for each one.
"""

import statistics
from collections.abc import Iterable
from typing import NamedTuple, SupportsFloat

import psycopg
from psycopg.rows import TupleRow

from db import KIND_WEAPON
from db.data.normalizer import name_key
from db.data.wiki.terrain import WORDS_PER_RATE
from facts import counters, kit_format, scalars
from facts.draft import EXPECTED_SHAPE
from facts.kit import KitPiece, Stat
from facts.model import REMECH, ROLES, TERRAIN_FEATURES, TERRAIN_LEAN, Hero, Map, World
from facts.records import (
    KitLine,
    KitListMiss,
    MapRate,
    Patch,
    Rates,
    Snapshot,
    StageTerrain,
    Synergy,
)
from facts.scalars import ally_lifesteal, derive_scalars

type Connection = psycopg.Connection[TupleRow]

NO_TEXT = StageTerrain(0.0, 0, 0)
# The words of its map's rate a stage's own rate is pulled toward. A stage's
# text runs from 20 words to a few hundred, where one mention swings its rate
# per thousand words by 5 to 50: read alone, a 20-word sentence that names a
# feature once reads 50 a thousand, several times the maps' mean on every
# feature. 100 words, about one paragraph on the stage, is where its own text
# weighs even with the map's: a 20-word text counts a sixth, a 200-word one
# two thirds. That weighs the text, not the z it yields: weighed at a sixth,
# the one mention still lifts the rate about 8 a thousand, a sd or more on a
# feature the maps name seldom, so compute.ground raises a feature only on
# compute.STAGE_MENTIONS mentions.
STAGE_PRIOR_WORDS = 100

# Every kit list, by its constant's name: the pieces the wiki has no field for
# (facts/scalars.py, the kit lists), each with every name it holds - a pair's
# two, a heal and the weapon that triggers it, a refund and its beam, a
# booster and what it boosts. check_kit_lists holds each name to the roster.
KIT_LISTS: dict[str, tuple[str, ...]] = {
    "PILOT_GUNS": scalars.PILOT_GUNS,
    "OFF_FIGHT": scalars.OFF_FIGHT,
    "FORM_GATED": scalars.FORM_GATED,
    "SAVE_TOOLS": scalars.SAVE_TOOLS,
    "UPTIME": tuple(scalars.UPTIME),
    "SPRAYS": scalars.SPRAYS,
    "TRIGGERED": (*scalars.TRIGGERED, *(weapon for weapon, _ in scalars.TRIGGERED.values())),
    "EMPTY_WAIT": tuple(scalars.EMPTY_WAIT),
    "TICK_RATES": tuple(scalars.TICK_RATES),
    "ENERGY_REFUND": (
        *scalars.ENERGY_REFUND, *(beam for beam, _ in scalars.ENERGY_REFUND.values())),
    "NOT_BESIDE": scalars.NOT_BESIDE,
    "OWN_HEALS": scalars.OWN_HEALS,
    "BOOSTS": (*scalars.BOOSTS, *scalars.BOOSTS.values()),
    "HELD": scalars.HELD,
    "CASTER": scalars.CASTER,
    "AIMED": scalars.AIMED,
    "REMECH": REMECH,
    "FLAG_FAMILIES": tuple(counters.FLAG_FAMILIES),
}

LATEST_BLIZZARD = """(select ms.snapshot_id from meta_snapshots ms
    join sources s on s.source_id = ms.source_id where s.code = 'blizzard'
    order by ms.captured_at desc, ms.snapshot_id desc limit 1)"""
# the latest earlier capture whose rates differ from the latest: a repeat pull
# stores the same rates again, and a date would turn on the session's timezone
PREVIOUS_BLIZZARD = """(select ms.snapshot_id from meta_snapshots ms
    join sources s on s.source_id = ms.source_id where s.code = 'blizzard'
    and exists (select 1 from hero_meta a join hero_meta b
                on b.hero_id = a.hero_id and b.tier_id = a.tier_id and b.region_id = a.region_id
                where a.snapshot_id = ms.snapshot_id and b.snapshot_id = %s
                  and a.win_rate is distinct from b.win_rate)
    order by ms.captured_at desc, ms.snapshot_id desc limit 1)""" % LATEST_BLIZZARD


def _rows(cx: Connection, sql: str) -> list[TupleRow]:
    return cx.execute(sql).fetchall()


class Scale(NamedTuple):
    """A population's mean and sd: what a z-score is read against."""
    mean: float
    sd: float


def _scale(values: Iterable[float]) -> Scale:
    """The values' mean and population sd."""
    population = list(values)
    return Scale(statistics.fmean(population), statistics.pstdev(population))


def _z(value: float, scale: Scale) -> float:
    """The value in sd from the scale's mean, to three places; 0 where sd is 0."""
    return round((value - scale.mean) / scale.sd, 3) if scale.sd else 0.0


def _z_scores[K](values: dict[K, float]) -> dict[K, float]:
    """{key: value} -> {key: z}, by the population's mean and sd; 0 where sd is 0."""
    if not values:
        return {}
    scale = _scale(values.values())
    return {k: _z(v, scale) for k, v in values.items()}


def terrain_scales(w: World) -> dict[str, Scale]:
    """{F: the mean and sd of the maps' mentions of F per thousand words},
    across the maps that have text: the scale every terrain z is read on,
    a map's and a stage's alike. Empty while no map has text."""
    read = [m for m in w.maps.values() if m.terrain]
    if not read:
        return {}
    return {f: _scale(m.terrain.get(f, 0.0) for m in read) for f in TERRAIN_FEATURES}


def derive_map_terrain(w: World) -> None:
    """Map.terrain_z[F]: the map's mentions of F per thousand words, z-scored
    across the maps that have text (terrain_scales); 0 for every F on a map
    with none. Map.terrain_lean[S]: the mean of terrain_z over
    TERRAIN_LEAN[S], z-scored across the same maps; absent on a map with no
    text."""
    read = sorted((m for m in w.maps.values() if m.terrain), key=lambda m: m.id)
    for m in w.maps.values():
        m.terrain_z = dict.fromkeys(TERRAIN_FEATURES, 0.0)
        m.terrain_lean = {}
    for feature, scale in terrain_scales(w).items():
        for m in read:
            m.terrain_z[feature] = _z(m.terrain.get(feature, 0.0), scale)
    for style, features in sorted(TERRAIN_LEAN.items()):
        means = {m.id: statistics.fmean(m.terrain_z[f] for f in features) for m in read}
        for mid, z in _z_scores(means).items():
            w.maps[mid].terrain_lean[style] = z


def stage_rate(mentions: int, words: int, prior: float) -> float:
    """A stage's mentions of a feature per thousand words: its own text's
    rate pulled toward `prior`, its map's, by STAGE_PRIOR_WORDS words of it -
    the two rates' mean weighted by the stage's words and the prior's."""
    return ((WORDS_PER_RATE * mentions + STAGE_PRIOR_WORDS * prior)
            / (words + STAGE_PRIOR_WORDS))


def derive_stage_terrain(w: World) -> None:
    """Map.stage_z[stage][F]: the stage's stage_rate of F - pulled toward its
    map's rate, the maps' mean on a map with no text - in sd on the maps'
    scale (terrain_scales), so a stage reads against the maps as its map
    does and no other stage's text moves it. A stage without counted text -
    no rows, or rows of 0 words, stored before the words were - holds
    nothing and reads as its map."""
    scales = terrain_scales(w)
    for m in w.maps.values():
        m.stage_z = {}
        for stage, said in m.stage_terrain.items():
            words = max((t.words for t in said.values()), default=0)
            if not words or not scales:
                continue
            m.stage_z[stage] = {
                f: _z(stage_rate(said.get(f, NO_TEXT).mentions, words,
                                 m.terrain.get(f, 0.0) if m.terrain else scale.mean), scale)
                for f, scale in scales.items()}


def derive_map_styles(w: World) -> None:
    """Map.rate_lift[S]: for a playstyle S and a map, the mean, over released
    heroes tagged S, each weighted 1/(its tag count), of the hero's win rate
    on the map minus its overall win rate, z-scored across the maps.
    Map.styles[S]: rate_lift[S] + terrain_lean[S]; a missing half is 0."""
    rated = sorted(
        ((h, h.win) for h in w.heroes.values() if h.released and h.styles and h.win is not None),
        key=lambda pair: pair[0].id)
    maps = sorted(w.maps.values(), key=lambda m: m.id)
    for m in maps:
        m.rate_lift = {}
    for style in sorted({s for h, _ in rated for s in h.styles}):
        lifts: dict[int, float] = {}
        for m in maps:
            total = weight = 0.0
            for h, overall in rated:
                win = h.map_win(m.id)
                if style in h.styles and win is not None:
                    total += (win - overall) / len(h.styles)
                    weight += 1 / len(h.styles)
            if weight:
                lifts[m.id] = total / weight
        for mid, z in _z_scores(lifts).items():
            w.maps[mid].rate_lift[style] = z
    for m in maps:
        m.styles = {
            s: round(m.rate_lift.get(s, 0.0) + m.terrain_lean.get(s, 0.0), 3)
            for s in sorted(set(m.rate_lift) | set(m.terrain_lean))}


def derive_best_maps(w: World) -> None:
    """Hero.best_maps: the three maps with the largest (map win rate - overall
    win rate), only where positive; ties by map name."""
    for h in w.heroes.values():
        overall = h.win
        if overall is None:
            continue
        lifts = sorted(
            (-round(rate.win - overall, 3), w.maps[mid].name, mid)
            for mid, rate in h.map_rates.items() if rate.win > overall)
        h.best_maps = [mid for _, _, mid in lifts[:3]]


# --- the read steps: each fills its part of the World -----------------------

def _add_stats(pieces: dict[int, KitPiece], rows: list[TupleRow]) -> None:
    """Each stat row - piece id, code, value, the two units, the magnitude
    underneath, condition, text - onto its piece."""
    for piece_id, code, value, un, ud, dv, cond, text in rows:
        pieces[piece_id].stats[code].append(Stat(
            code=code, value=value, unit_num=un, unit_den=ud, den_value=dv, condition=cond,
            text=text))


def _read_heroes(cx: Connection, w: World) -> None:
    """The heroes with their role, subrole and playstyles; the role icons and
    the subroles' passives."""
    for hid, name, role, sub, hp, sh, ar, portrait, status, released in _rows(cx, """
            select h.hero_id, h.name, r.code, sr.name, coalesce(h.health, 0),
                   coalesce(h.shield, 0), coalesce(h.armor, 0), h.portrait_url,
                   h.status, h.release_date
            from heroes h join roles r using(role_id)
            join subroles sr on sr.subrole_id = h.subrole_id"""):
        w.heroes[hid] = Hero(
            id=hid, name=name, role=role, subrole=sub, health=hp, shield=sh, armor=ar,
            portrait=portrait, status=status, release_date=released)
        w.by_key[name_key(name)] = hid
    for code, url in _rows(cx, "select code, icon_url from roles"):
        w.role_icons[code] = url
    for sub, passive in _rows(cx, "select name, passive_description from subroles"):
        w.subrole_passives[sub] = passive
    for hid, style in _rows(cx, "select hero_id, style from playstyle"):
        w.heroes[hid].styles.add(style)


def _read_abilities(cx: Connection, w: World) -> None:
    """Each hero's abilities in order, and their stats."""
    abilities: dict[int, KitPiece] = {}
    for aid, hid, name, kind, desc, kw in _rows(cx, """
            select a.ability_id, a.hero_id, a.name, coalesce(k.code, 'ability'),
                   a.description, a.keywords
            from abilities a left join ability_kinds k using(kind_id)
            order by a.hero_id, a.position"""):
        piece = KitPiece(name, kind, description=desc, keywords=kw)
        abilities[aid] = piece
        w.heroes[hid].abilities.append(piece)
    _add_stats(abilities, _rows(cx, """
            select s.ability_id, k.code, s.value, s.unit_numerator,
                   s.unit_denominator, s.denominator_value, s.condition,
                   s.value_text
            from ability_stats s join stat_keys k using(stat_key_id)
            order by s.ability_stat_id"""))


def _read_weapons(cx: Connection, w: World) -> None:
    """Each hero's weapons, one kit piece per firing config, and their stats."""
    configs: dict[int, KitPiece] = {}
    for cid, hid, wname, cname, wtype, kw, slot in _rows(cx, """
            select c.config_id, w.hero_id, w.name, c.name, c.weapon_type,
                   c.keywords, s.code
            from weapon_configs c join weapons w using(weapon_id)
            join weapon_config_slots s on s.slot_id = c.slot_id
            order by w.hero_id, w.position, c.position"""):
        piece = KitPiece(cname or wname, KIND_WEAPON, description="", keywords=kw)
        piece.extra["weapon"] = wname
        piece.extra["weapon_type"] = wtype
        piece.extra["slot"] = slot
        configs[cid] = piece
        w.heroes[hid].weapons.append(piece)
    _add_stats(configs, _rows(cx, """
            select s.config_id, k.code, s.value, s.unit_numerator,
                   s.unit_denominator, s.denominator_value, s.condition,
                   s.value_text
            from weapon_stats s join stat_keys k using(stat_key_id)
            order by s.weapon_stat_id"""))


def _read_perks(cx: Connection, w: World) -> None:
    """Each hero's perks by tier, and their stats."""
    perks: dict[int, KitPiece] = {}
    for pid, hid, name, tier, desc in _rows(cx, """
            select p.perk_id, p.hero_id, p.name, t.code, p.description
            from perks p join perk_tiers t using(tier_id)
            order by p.hero_id, p.tier_id, p.position"""):
        piece = KitPiece(name, "perk:" + tier, description=desc)
        perks[pid] = piece
        w.heroes[hid].perks.append(piece)
    _add_stats(perks, _rows(cx, """
            select s.perk_id, k.code, s.value, s.unit_numerator,
                   s.unit_denominator, s.denominator_value, s.condition,
                   s.value_text
            from perk_stats s join stat_keys k using(stat_key_id)
            order by s.perk_stat_id"""))


def _read_kit_6v6(cx: Connection, w: World) -> None:
    """Each hero's 6v6 kit as stored: the pools the wiki gives a 6v6 figure
    for, and its 6v6 lines, in the order the pull stored them."""
    for hid, health, shield, armor in _rows(cx, """
            select hero_id, health_6v6, shield_6v6, armor_6v6 from heroes
            where num_nonnulls(health_6v6, shield_6v6, armor_6v6) > 0"""):
        w.heroes[hid].six_pools = {
            pool: value for pool, value in (("health", health), ("shield", shield),
                                            ("armor", armor)) if value is not None}
    for hid, piece, stat, before, after, text in _rows(cx, """
            select k.hero_id, k.piece, s.code, k.from_value, k.to_value, k.value_text
            from kit_6v6 k left join stat_keys s using(stat_key_id)
            order by k.kit_6v6_id"""):
        w.heroes[hid].six_lines.append(KitLine(
            piece=piece, stat=stat, before=_rate(before), after=_rate(after), text=text))


def _rate(value: SupportsFloat | None) -> float | None:
    """A stored rate as a float; None where the capture publishes none."""
    return float(value) if value is not None else None


def _read_rates(cx: Connection, w: World) -> None:
    """Each hero's rates in the latest Blizzard capture, overall and per tier
    up the ladder, and its overall win rate in the capture before; the
    tiers' names."""
    for code, name in _rows(cx, "select code, name from competitive_tiers order by rank_order"):
        w.tier_names[code] = name
    for hid, tier, win, pick, ban in _rows(cx, """
            select m.hero_id, t.code, m.win_rate, m.pick_rate, m.ban_rate
            from hero_meta m join competitive_tiers t on t.tier_id = m.tier_id
            where m.snapshot_id = %s
            order by t.rank_order""" % LATEST_BLIZZARD):
        h = w.heroes[hid]
        rates = Rates(win=_rate(win), pick=_rate(pick), ban=_rate(ban))
        if tier == "all":
            h.win, h.pick, h.ban = rates
        else:
            h.by_tier[tier] = rates
    for hid, win in _rows(cx, """
            select m.hero_id, m.win_rate from hero_meta m
            join competitive_tiers t on t.tier_id = m.tier_id
            where t.code = 'all' and m.snapshot_id = %s""" % PREVIOUS_BLIZZARD):
        if win is not None:
            w.heroes[hid].prev_win = float(win)
    for hero in w.heroes.values():
        hero.derive_rates()


def _read_maps(cx: Connection, w: World) -> None:
    """The maps with their mode, and their stages in play order."""
    for mid, name, mode in _rows(cx, """
            select m.map_id, m.name, g.name from maps m
            left join map_modes mm using(map_id)
            left join game_modes g using(mode_id)"""):
        w.maps[mid] = Map(mid, name, mode)
        w.maps_by_key[name_key(name)] = mid
    for mid, stage in _rows(cx, "select map_id, name from map_stages order by map_id, position"):
        w.maps[mid].stages.append(stage)


def _read_map_rates(cx: Connection, w: World) -> None:
    """Each hero's overall rates on each map in the latest Blizzard capture, and
    the best maps they make."""
    for hid, mid, win, pick, ban in _rows(cx, """
            select m.hero_id, m.map_id, m.win_rate, m.pick_rate, m.ban_rate from map_meta m
            join competitive_tiers t on t.tier_id = m.tier_id
            where t.code = 'all' and m.snapshot_id = %s""" % LATEST_BLIZZARD):
        if win is not None:
            w.heroes[hid].map_rates[mid] = MapRate(
                float(win), float(pick) if pick is not None else None)
            if ban is not None:
                w.heroes[hid].map_bans[mid] = float(ban)
    derive_best_maps(w)


def _read_terrain(cx: Connection, w: World) -> None:
    """The terrain the wiki describes, per map and per stage - a stage's with
    the words of its text - with their z-scores."""
    for mid, feature, rate in _rows(cx, "select map_id, feature, per_thousand from map_terrain"):
        w.maps[mid].terrain[feature] = float(rate)
    derive_map_terrain(w)
    for mid, stage, feature, rate, mentions, words in _rows(cx, """
            select s.map_id, s.name, t.feature, t.per_thousand, t.mentions, t.words
            from stage_terrain t join map_stages s using(stage_id)"""):
        w.maps[mid].stage_terrain.setdefault(stage, {})[feature] = StageTerrain(
            float(rate), mentions, words)
    derive_stage_terrain(w)


def impute_synergy(w: World) -> None:
    """World.synergy_cell: the share of the written Team Synergy cells that
    claim their pair - what team.synergy_score reads a cell no article
    writes at, since its score is unknown, not zero (docs/inference.md, Why
    an unwritten synergy pair is not zero). It is 0 while no cell is on
    record, as in a database migrated and not yet pulled again, where no
    cell is known to be unwritten (World.unwritten_cells)."""
    pairs = {frozenset(cell) for cell in w.synergy_written} | set(w.synergies)
    written = sum(2 - w.unwritten_cells(*sorted(pair)) for pair in pairs)
    w.synergy_cell = (sum(s.score or 0 for s in w.synergies.values()) / written
                      if w.synergy_written and written else 0.0)


def _read_relations(cx: Connection, w: World) -> None:
    """The wiki's counters, both ways, each with where it was read, its
    synergy pairs, the synergy cells its articles write, each as (the
    article's hero, the teammate), and what a cell no article writes reads
    at."""
    for loser, winner, basis in _rows(
            cx, "select hero_id, countered_by_id, basis from counters order by 1, 2, 3"):
        w.counters.add((loser, winner))
        w.counter_basis[(loser, winner)].add(basis)
        w.answered_by[loser].add(winner)
        w.answers[winner].add(loser)
    for a, b, score, note in _rows(cx, "select hero_id, other_id, score, note from synergies"):
        pair = Synergy(score, note)
        w.synergies[frozenset((a, b))] = pair
        w.partners[a][b] = pair
        w.partners[b][a] = pair
    for a, b in _rows(cx, "select hero_id, other_id from synergy_cells"):
        w.synergy_written.add((a, b))
    impute_synergy(w)


def _read_provenance(cx: Connection, w: World) -> None:
    """Where the rates come from: each source's newest capture, and the
    patches shipped since."""
    w.snapshots = [
        Snapshot(
            source=src, captured=str(cap), patch=patch, released=str(rel) if rel else None,
            queue=queue, platform=platform, region=region)
        for src, cap, patch, rel, queue, platform, region in _rows(cx, """
            select src.code, ms.captured_at::date, p.name, p.released, ms.queue, ms.platform,
                   (select string_agg(distinct r.name, ', ') from hero_meta hm
                   join regions r using(region_id)
                   where hm.snapshot_id = ms.snapshot_id)
            from meta_snapshots ms join sources src using(source_id)
            left join patches p using(patch_id)
            where ms.snapshot_id in (
                select distinct on (source_id, queue) snapshot_id from meta_snapshots
                order by source_id, queue, captured_at desc)
            order by ms.captured_at desc""")]
    w.newer_patches = [Patch(name=n, released=str(r)) for n, r in _rows(cx, """
            select p.name, p.released from patches p
            where p.released > (select coalesce(max(pp.released), '1900-01-01')
                from meta_snapshots ms join patches pp using(patch_id))
            order by p.released desc""")]


def check_kit_lists(w: World) -> None:
    """World.kit_list_misses: each name a kit list holds (KIT_LISTS) that no
    hero's ability or weapon config carries, once, with the lists that hold
    it, in KIT_LISTS' order. A list matches a piece by its whole name, so a
    pull that renames a piece leaves the old name here, and the piece reads
    as an ordinary one until its lists take the new name; the board warns of
    it (board_facts)."""
    carried = {p.name for h in w.heroes.values() for p in (*h.abilities, *h.weapons)}
    holding: dict[str, list[str]] = {}
    for kit_list, names in KIT_LISTS.items():
        for name in dict.fromkeys(names):
            if name not in carried:
                holding.setdefault(name, []).append(kit_list)
    w.kit_list_misses = [KitListMiss(name, tuple(lists)) for name, lists in holding.items()]


def _derive_ally_lifesteal(w: World) -> None:
    """A heal that rides the teammates' damage (Cardiac Overdrive) at what the
    caster's five teammates of a 2-2-2 deal: each role's median dps over the
    released heroes, the caster's own seat taken out."""
    released = [h for h in w.heroes.values() if h.released]
    medians = {
        role: statistics.median(h.dps for h in released if h.role == role)
        for role in ROLES if any(h.role == role for h in released)}
    for hero in w.heroes.values():
        seats = {role: n - (role == hero.role) for role, n in EXPECTED_SHAPE.items()}
        ally = sum(n * medians.get(role, 0.0) for role, n in seats.items()) / sum(seats.values())
        ally_lifesteal(hero, ally)


def _derive_benches(w: World) -> None:
    """The roster's healing benches, each role's median pool and the ultimate
    cap, over the released heroes' derived numbers: an announced hero sets
    nothing."""
    supports = [
        h.peak_heal for h in w.heroes.values()
        if h.role == "support" and h.released and h.peak_heal]
    w.heal_bench = 2 * statistics.median(supports) if supports else 0.0
    rates = [h.hps for h in w.heroes.values() if h.role == "support" and h.released and h.hps]
    w.hps_bench = 2 * statistics.median(rates) if rates else 0.0
    # a pool as team.pool_total reads it: a form's armor on top of the spawn pool
    released = [h for h in w.heroes.values() if h.released]
    w.pool_medians = {
        role: statistics.median(h.pool + h.form_armor for h in released if h.role == role)
        for role in ROLES if any(h.role == role for h in released)}
    # one ultimate's damage is worth, at most, the largest single figure one
    # publishes: a beam held for twenty seconds is not seven Self-Destructs
    flat_ults = [
        s.value for h in w.heroes.values() if h.released for u in h.ults
        for s in u.flat("damage")]
    w.ult_cap = max(flat_ults, default=0.0)
    for hero in w.heroes.values():
        hero.cap_ult(w.ult_cap)


def load(cx: Connection) -> World:
    """The whole database -> World, its kit read in 6v6 (draft.KIT_FORMAT).
    `cx` is an open psycopg connection; this module never opens one of its
    own. The steps run in the order each relies on: the kit, and the 6v6
    laid over it, before derive_scalars and the kit lists' check, the rates
    before derive_rates, derive_best_maps and derive_map_styles, the
    terrain before derive_map_styles, the teammates' lifesteal and the
    benches over the derived roster, and the counter matrix over the
    derived kit and the wiki's counters, last."""
    w = World()
    _read_heroes(cx, w)
    _read_abilities(cx, w)
    _read_weapons(cx, w)
    _read_perks(cx, w)
    _read_kit_6v6(cx, w)
    kit_format.apply(w)
    check_kit_lists(w)
    _read_rates(cx, w)
    _read_maps(cx, w)
    _read_map_rates(cx, w)
    _read_terrain(cx, w)
    _read_relations(cx, w)
    _read_provenance(cx, w)
    derive_map_styles(w)
    for hero in w.heroes.values():
        derive_scalars(hero)
    _derive_ally_lifesteal(w)
    _derive_benches(w)
    counters.derive(w)
    return w
