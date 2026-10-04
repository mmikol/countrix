"""The maps the load builds from the database: every terrain feature read for
each map with text, King's Row's chokes and the style they lean it to, every
style scored on every map, the same on every load, the stages per mode and
each stage's terrain. The wiki's own maps are the point; the z-scores, the
lean, the rates' lift and the styles they sum to are worked by hand on
hand-built maps in tests/verification/facts/test_tables.py."""

import pytest

from facts import compute, model, tables

pytestmark = pytest.mark.invariant


def test_every_map_with_text_reads_every_feature_and_kings_row_the_most_chokes(world, rows):
    features = model.TERRAIN_FEATURES
    assert set(features) == {f for (f,) in rows("select distinct feature from map_terrain")}
    assert set(features) < set(compute.MAP_METRICS)
    assert not {"map." + f for f in features} & compute.TEXT_METRICS
    assert all("map." + f in compute.registry() for f in features)
    read = [m for m in world.maps.values() if m.terrain]
    assert len(read) == rows("select count(distinct map_id) from map_terrain")[0][0] >= 2
    for m in read:
        assert set(m.terrain) == set(features)             # all eight rows, zeros included
    for f in features:                                     # each feature sets the maps apart
        assert len({m.terrain[f] for m in read}) > 1, f
    # the wiki's King's Row: narrow streets and a first chokepoint
    kings = world.map("King's Row")
    assert max(features, key=lambda f: kings.terrain_z[f]) == "chokes"
    assert kings.terrain_z["chokes"] == max(m.terrain_z["chokes"] for m in read)


def test_kings_rows_terrain_leans_it_to_brawl_and_every_map_scores_every_style(world):
    assert model.TERRAIN_LEAN == {
        "brawl": ("chokes", "interiors"), "dive": ("high_ground", "flanks", "hazards"),
        "poke": ("sightlines", "open_ground")}
    styles = {s for h in world.heroes.values() for s in h.styles}
    assert styles and all(set(m.styles) == styles for m in world.maps.values())
    # the wiki's chokes outweigh King's Row's rates: the terrain rectifies the style
    kings = world.map("King's Row")
    assert max(kings.terrain_lean, key=kings.terrain_lean.get) == "brawl"
    assert kings.style_top == max(kings.styles, key=lambda s: kings.styles[s])


def test_the_terrain_and_the_style_are_the_same_on_every_load(world, db):
    again = tables.load(db)
    db.rollback()
    for m in world.maps.values():
        other = again.maps[m.id]
        assert (m.terrain, m.terrain_z, m.terrain_lean, m.rate_lift, m.styles) == (
            other.terrain, other.terrain_z, other.terrain_lean, other.rate_lift, other.styles)
        assert (list(compute.map_metrics(m, ban_count=0))
                == list(compute.map_metrics(other, ban_count=0)))
    before = {m.id: (dict(m.terrain_z), dict(m.terrain_lean)) for m in world.maps.values()}
    tables.derive_map_terrain(world)
    assert before == {m.id: (dict(m.terrain_z), dict(m.terrain_lean)) for m in world.maps.values()}


def test_stages_are_read_per_mode_as_the_wiki_holds_them(world, rows):
    stored = {}
    for name, stage in rows("""select m.name, s.name from map_stages s join maps m
            using(map_id) order by m.name, s.position"""):
        stored.setdefault(name, []).append(stage)
    assert {m.name: m.stages for m in world.maps.values() if m.stages} == stored
    by_mode = {}
    for m in world.maps.values():
        by_mode.setdefault(m.mode, []).append(m)
    assert all(len(m.stages) == 3 for m in by_mode["Control"])
    assert all(len(m.stages) == 5 for m in by_mode["Flashpoint"])
    assert all(m.stages == ["Assault", "Escort"] for m in by_mode["Hybrid"])   # point, then payload
    assert all(m.stages == [] for m in by_mode["Push"])
    # an Escort map holds the three stretches its own article names, or none
    assert {len(m.stages) for m in by_mode["Escort"]} == {0, 3}
    assert world.map("Havana").stages == ["City Streets", "Distillery", "Sea Fort"]
    assert world.map("Dorado").stages == []
    assert world.map("Ilios").stages == ["Lighthouse", "Well", "Ruins"]


def test_every_stage_with_text_reads_every_feature_as_the_wiki_states_it(world, rows):
    features = model.TERRAIN_FEATURES
    read = [(m, stage) for m in world.maps.values() for stage in m.stage_terrain]
    assert len(read) == rows("select count(distinct stage_id) from stage_terrain")[0][0] >= 2
    for m, stage in read:
        assert stage in m.stages and set(m.stage_terrain[stage]) == set(features)
        assert set(m.stage_z[stage]) == set(features)
    (rate, mentions, words), = rows("""select t.per_thousand, t.mentions, t.words
        from stage_terrain t join map_stages s using(stage_id) join maps m using(map_id)
        where m.name = 'Ilios' and s.name = 'Well' and t.feature = 'hazards'""")
    assert world.map("Ilios").stage_terrain["Well"]["hazards"] == (float(rate), mentions, words)
    # the same on every pass
    before = {m.id: {s: dict(z) for s, z in m.stage_z.items()} for m in world.maps.values()}
    tables.derive_stage_terrain(world)
    assert before == {m.id: m.stage_z for m in world.maps.values()}
