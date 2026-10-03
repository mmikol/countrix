"""A board's facts: everything the database holds about it, as a numbered
FactSet.

    generate(world, Draft("King's Row", red=("Zarya", "Pharah"), blue=("Ana",)))

The equation of the FACTS, independent and dependent per domain, is the
math page's and docs/architecture.md's.

FACTS are derived from the authoritative data - what the sources say about
the heroes, the maps and the meta, pulled and set - for this board, and
every domain yields both kinds: the independent facts are a selection's
own row (a hero's kit, rates and style; the map's mode and stages; the
meta's vintage); the dependent facts are the selection joined with others
(map_meta is heroes ⋈ maps ⋈ meta, counters and synergies are heroes ⋈
heroes, the team is the six joined, the matchup the twelve, the bans join
both teams), and a join belongs to every domain it touches - the
dependent facts are where the domains' fact sets intersect.
Independent facts per hero and for the map come first; the joins per team
appear once a team has picks, and the matchup once both teams do. Each is
structured (scope, subject, key, value) so the inference layer can read
it by key, and rendered as a sentence so a person - or the /comp skill -
can read it as evidence. Ids are dense and stable within a board.

This module writes the meta, the bans and the map; facts.hero_facts writes
a hero's facts, and facts.team_facts a team's and the matchup's.
"""

from typing import NotRequired, TypedDict

from facts import compute, hero_facts, team_facts
from facts.compute import TERRAIN_STANDOUT, GroundSource
from facts.draft import MAX_BANS, Draft, Side, board_side, board_stage, is_sided, opposite
from facts.factset import FactSet
from facts.model import TERRAIN_FEATURES, Map, Resolved, World


class TerrainValue(TypedDict):
    """A map.terrain fact's value, and each feature of a map.stage_terrain
    fact's: the feature, its z over the ordinary map or stage, and its
    mentions per thousand words - a stage's with the count behind them."""
    feature: str
    z: float
    per_thousand: float
    mentions: NotRequired[int]


class StageTerrainValue(TypedDict):
    """A map.stage_terrain fact's value: the stage and the features its own
    text stresses, largest first."""
    stage: str
    features: list[TerrainValue]


class GroundValue(TypedDict):
    """A feature of a map.ground fact's value: the feature, its z on the
    ground in play, and whose text it was read off (compute.ground)."""
    feature: str
    z: float
    source: GroundSource


class GroundFact(TypedDict):
    """A map.ground fact's value: the stage in play and its features above
    the ordinary map, largest first."""
    stage: str
    features: list[GroundValue]


# --- the board -------------------------------------------------------------

def generate(world: World, draft: Draft) -> FactSet:
    """The FactSet for a board: the map (and blue's side on a sided map, and
    the stage in play where one is named), the red and blue picks, and the
    match's bans (each team's two and the lobby's - up to five, all
    optional). A banned hero cannot be picked and cannot be recommended;
    every name World.resolve refuses is a Refusal, as is a stage the map
    does not list. The FactSet's draft holds the resolved names and the
    side the map keeps."""
    board = world.resolve(draft.map_name, draft.red, draft.blue, draft.bans, allow_announced=True)
    side, stage = board_side(board.map, draft.side), board_stage(board.map, draft.stage)
    fs = FactSet(Draft(
        map_name=board.map.name if board.map else None,
        red=tuple(h.name for h in board.red), blue=tuple(h.name for h in board.blue),
        bans=tuple(h.name for h in board.banned), side=side, stage=stage))
    _meta_facts(fs, world)
    if board.banned:
        _ban_facts(fs, world, board)
    if board.map is not None:
        _map_facts(fs, world, board.map, side, stage)
    for h in board.red:
        hero_facts.write(fs, world, board, h, "red")
    for h in board.blue:
        hero_facts.write(fs, world, board, h, "blue")
    team_facts.write(fs, world, board)
    return fs


def _meta_facts(fs: FactSet, world: World) -> None:
    for s in world.snapshots:                 # one per source: its newest capture
        fs.add("meta", "snapshot", "meta.snapshot",
            "%s rates: captured %s, %s (%s) - %s, %s, %s"
            % (s["source"], s["captured"], s["patch"] or "an unknown patch",
                s["released"] or "-",
                s["queue"].replace("competitive_", "").replace("_", " "), s["platform"],
                s["region"] or "region unstated"),
            value=s, source="meta_snapshots")
    if world.newer_patches:
        name, released = world.newer_patches[0]
        fs.add("meta", "snapshot", "meta.vintage_warning",
            "WARNING: %d patch(es) shipped since the rates were captured,"
            " newest %s (%s) - treat rates as pre-patch"
            % (len(world.newer_patches), name, released),
            value=len(world.newer_patches), source="patches", warn=True)


def _ban_facts(fs: FactSet, world: World, board: Resolved) -> None:
    """What the bans took off the table, for both sides."""
    banned = board.banned
    fs.add("bans", "match", "bans.count", "bans this match: %d of %d - %s"
        % (len(banned), MAX_BANS, ", ".join(h.name for h in banned)),
        value=[h.name for h in banned], source="derived:bans.count")
    for h in banned:
        fs.add("bans", h.name, "bans.hero", "%s is banned this match - neither team"
            " can pick them" % h.name, value=h.name, source="derived:bans.hero")
        answered = [e.name for e in board.red if world.is_countered_by(e.id, h.id)]
        if answered:
            fs.add("bans", h.name, "bans.answered_red", "banned %s answered red %s -"
                " that answer is off the table" % (h.name, ", ".join(answered)),
                value=answered, source="counters")
        threatened = [a.name for a in board.blue if world.is_countered_by(a.id, h.id)]
        if threatened:
            fs.add("bans", h.name, "bans.answered_blue", "banned %s answered blue %s -"
                " that threat is gone" % (h.name, ", ".join(threatened)),
                value=threatened, source="counters")


# --- the map ---------------------------------------------------------------

def _map_facts(fs: FactSet, world: World, m: Map, side: Side = "", stage: str = "") -> None:
    """The map's own facts - its mode and sides, its ground and the ground
    in play, the styles it rewards - then the heroes who do well on it."""
    _map_mode(fs, m, side)
    _map_terrain(fs, m)
    if stage:
        _map_ground(fs, m, stage)
    _map_styles(fs, m)
    _map_heroes(fs, world, m)


def _map_mode(fs: FactSet, m: Map, side: Side) -> None:
    """The mode, who attacks, and the stages in play order: the arenas, or
    the phases of a route."""
    fs.add("map", m.name, "map.mode", "%s is a %s map" % (m.name, m.mode),
        value=m.mode, source="map_modes")
    if is_sided(m):
        if side:
            verb = {"attack": "attacks", "defense": "defends"}
            fs.add("map", m.name, "map.side", "blue %s %s; red %s" % (
                verb[side], m.name, verb[opposite(side)]), value=side,
                source="derived:map.side")
        else:
            fs.add("map", m.name, "map.side", "%s has an attacking and a defending side"
                "; blue's side is not set" % m.name, value="",
                source="derived:map.side")
        fs.add("map", m.name, "map.side_caveat", "the rates do not split by side on"
            " %s: side-specific advice comes from the kit facts and the side"
            " strategies, not from win rates" % m.name, value=m.mode,
            source="derived:map.side_caveat")
    else:
        fs.add("map", m.name, "map.side", "%s (%s) has no attacking or defending side"
            % (m.name, m.mode), value="", source="derived:map.side")
    if compute.arenas(m):
        fs.add("map", m.name, "map.arenas", "%s stages: %s"
            % (m.name, ", ".join(m.stages)), value=m.stages, source="map_stages")
    elif compute.phases(m):
        fs.add("map", m.name, "map.phases", "%s phases, in order: %s"
            % (m.name, ", ".join(m.stages)), value=m.stages, source="map_stages")


def _map_terrain(fs: FactSet, m: Map) -> None:
    """The ground the wiki's articles stress: each stage's, then the map's."""
    for stage in m.stages:
        standouts = compute.stage_standouts(m, stage)
        if standouts:
            fs.add("map", m.name, "map.stage_terrain",
                "%s - %s: %s" % (m.name, stage, "; ".join(
                    "%s, %.1f sd above the ordinary stage (%d mentions in the wiki's article)"
                    % (f.replace("_", " "), z, m.stage_terrain[stage][f].mentions)
                    for f, z in standouts)),
                value=StageTerrainValue(stage=stage, features=[
                    TerrainValue(
                        feature=f, z=z, per_thousand=m.stage_terrain[stage][f].per_thousand,
                        mentions=m.stage_terrain[stage][f].mentions)
                    for f, z in standouts]),
                source="stage_terrain")
    if m.terrain:
        for feature in sorted(TERRAIN_FEATURES, key=lambda f: (-abs(m.terrain_z[f]), f)):
            z = m.terrain_z[feature]
            if abs(z) >= TERRAIN_STANDOUT:
                fs.add("map", m.name, "map.terrain", "%s: %s, %.1f sd %s the ordinary map (the"
                    " wiki's article)" % (m.name, feature.replace("_", " "), abs(z),
                        "below" if z < 0 else "above"),
                    value=TerrainValue(feature=feature, z=z, per_thousand=m.terrain[feature]),
                    source="map_terrain")
    else:
        fs.add("map", m.name, "map.terrain_unread", "%s: the wiki's article has too little on"
            " the ground; its terrain metrics read 0" % m.name, value=0,
            source="map_terrain")


def _map_ground(fs: FactSet, m: Map, stage: str) -> None:
    """The ground in play on a stage: each terrain feature above the
    ordinary map as the board's map.* metrics read it (compute.ground),
    largest first, and whose text it came from. The fact carries each
    feature's map.* metric, so a rule gated on the terrain cites it."""
    read = sorted((compute.ground(m, stage, f) for f in TERRAIN_FEATURES),
                  key=lambda g: (-g.z, g.feature))
    above = [g for g in read if round(g.z, 1) > 0]           # as the sentence words it
    source = {"stage": "the stage's text", "map": "the map's article"}
    said = "; ".join("%s %.1f sd above the ordinary (%s)"
                     % (g.feature.replace("_", " "), g.z, source[g.source])
                     for g in above)
    fs.add("map", m.name, "map.ground", "%s - %s is the ground in play: %s" % (
        m.name, stage, said or "no terrain feature above the ordinary map"),
        value=GroundFact(stage=stage, features=[
            GroundValue(feature=g.feature, z=g.z, source=g.source) for g in above]),
        source="stage_terrain+map_terrain", also=["map.%s" % g.feature for g in above])


def _map_styles(fs: FactSet, m: Map) -> None:
    """The styles the map rewards, each score with its terrain and rates
    halves, and the style on top."""
    for style in sorted(m.styles, key=lambda s: (-m.styles[s], s)):
        fs.add("map", m.name, "map.style", "%s on %s: %+.1f sd (%s)"
            % (style, m.name, m.styles[style], _halves(m, style)),
            value={"style": style, "score": m.styles[style],
                "terrain": m.terrain_lean.get(style), "rates": m.rate_lift.get(style)},
            source="derived:map.style")
    top = m.style_top                   # None exactly when the map has no styles
    if top is not None:
        fs.add("map", m.name, "map.style_top", "%s rewards %s: %s (%g sd over the runner-up)"
            % (m.name, top, _halves(m, top), m.style_margin),
            value=top, source="derived:map.style_top")


def _halves(m: Map, style: str) -> str:
    """The two halves of a map's style score, as the fact words them."""
    parts = [("terrain", m.terrain_lean.get(style)), ("rates", m.rate_lift.get(style))]
    return ", ".join("%s %+.1f" % (word, z) if z is not None else "no %s" % word
        for word, z in parts)


def _map_heroes(fs: FactSet, world: World, m: Map) -> None:
    """Who wins on the map and who struggles, whose top map it is, and who
    holds up in each style it rewards."""
    wins = {h.id: win for h in world.heroes.values() if (win := h.map_win(m.id)) is not None}
    ranked = sorted((h for h in world.heroes.values() if h.id in wins),
        key=lambda h: -wins[h.id])
    for h in ranked[:10]:
        fs.add("map", m.name, "map.leader", "on %s: %s wins %.1f%% (picked %.1f%%)"
            % (m.name, h.name, wins[h.id], h.map_pick(m.id) or 0),
            value={"hero": h.name, "win": wins[h.id]}, source="map_meta")
    if len(ranked) > 6:
        fs.add("map", m.name, "map.strugglers", "struggle on %s: %s" % (m.name, ", ".join(
            "%s (%.1f%%)" % (h.name, wins[h.id]) for h in ranked[-6:][::-1])),
            value=[h.name for h in ranked[-6:]], source="map_meta")
    for h in world.heroes_by_role():
        if m.id in h.best_maps:
            fs.add("map", m.name, "map.home_map_of", "%s is %s's top-%d map by Blizzard's"
                " map rates" % (m.name, h.name, h.best_maps.index(m.id) + 1),
                value=h.name, source="derived:map.home_map_of")
    for style in sorted(m.styles, key=lambda s: (-m.styles[s], s)):
        fits = [h for h in ranked if style in h.styles][:6]
        if fits:
            fs.add("map", m.name, "map.style_fit", "%s heroes who hold up on %s: %s"
                % (style, m.name, ", ".join(
                    "%s (%.1f%%)" % (h.name, wins[h.id]) for h in fits)),
                value=[h.name for h in fits], source="playstyle+map_meta")
