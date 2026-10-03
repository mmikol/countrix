"""The derivations facts/tables.py runs after its reads, on the synthetic
World: the terrain's z-scores and lean, the rates' lift, the styles they sum
to, the stages' z-scores and each hero's best maps, every expected value
worked by hand from tests/synthetic.py. No database."""

import pytest

from facts import tables
from facts.model import TERRAIN_FEATURES, Map
from facts.records import MapRate
from facts.team import pair_score


def _maps(w):
    return w.map("Harbor Gate"), w.map("Ember Ruins"), w.map("Salt Flats")


def test_terrain_z_is_one_sd_either_side_across_two_texts_and_zero_without_one(synthetic_world):
    harbor, ember, salt = _maps(synthetic_world)
    assert harbor.terrain_z == {
        "chokes": 1.0, "interiors": 1.0, "high_ground": -1.0, "flanks": -1.0,
        "sightlines": 1.0, "open_ground": -1.0, "hazards": -1.0, "cover": 1.0}
    assert ember.terrain_z == {f: -z for f, z in harbor.terrain_z.items()}
    assert salt.terrain_z == dict.fromkeys(TERRAIN_FEATURES, 0.0)


def test_a_styles_terrain_lean_is_the_mean_of_its_features_z_scored_again(synthetic_world):
    """Harbor Gate's chokes and interiors both read +1, its high ground,
    flanks and hazards -1; its sightlines +1 and open ground -1 cancel, and
    Ember Ruins' cancel the same way, so poke's two means are equal and
    z-score to 0."""
    harbor, ember, salt = _maps(synthetic_world)
    assert harbor.terrain_lean == {"brawl": 1.0, "dive": -1.0, "poke": 0.0}
    assert ember.terrain_lean == {"brawl": -1.0, "dive": 1.0, "poke": 0.0}
    assert salt.terrain_lean == {}


def test_a_styles_rate_lift_is_its_heroes_mean_lift_z_scored_across_the_maps(synthetic_world):
    """Brawl's five heroes run +10 summed on Harbor Gate, 0 on Ember Ruins and
    -10 on Salt Flats: a mean lift of +2, 0, -2, which z-scores to 1.225, 0
    and -1.225. Flint carries dive and poke and counts a half in each: poke's
    -6 - 1, -8 + 1 and 14 + 0 over 3.5 read -2, -2, +4, z -0.707, -0.707,
    1.414; counted whole, poke would read -2, -1.5, +3.5."""
    harbor, ember, salt = _maps(synthetic_world)
    assert harbor.rate_lift == {"brawl": 1.225, "dive": -1.225, "poke": -0.707}
    assert ember.rate_lift == {"brawl": 0.0, "dive": 1.225, "poke": -0.707}
    assert salt.rate_lift == {"brawl": -1.225, "dive": 0.0, "poke": 1.414}


def test_a_maps_style_is_the_rates_lift_plus_the_terrains_lean(synthetic_world):
    harbor, ember, salt = _maps(synthetic_world)
    assert harbor.styles == {"brawl": 2.225, "dive": -2.225, "poke": -0.707}
    assert ember.styles == {"brawl": -1.0, "dive": 2.225, "poke": -0.707}
    assert salt.styles == salt.rate_lift     # the rates alone
    assert (harbor.style_top, harbor.style_margin) == ("brawl", 2.932)
    assert (ember.style_top, ember.style_margin) == ("dive", 2.932)
    assert (salt.style_top, salt.style_margin) == ("poke", 1.414)


def test_an_announced_hero_moves_no_maps_style(synthetic_world):
    w = synthetic_world
    wisp = w.hero("Wisp")
    before = {m.id: (dict(m.styles), dict(m.rate_lift)) for m in w.maps.values()}
    wisp.win = 99.0
    wisp.map_rates = {
        m.id: MapRate(win, None) for m, win in zip(_maps(w), (1.0, 99.0, 99.0), strict=True)}
    tables.derive_map_styles(w)
    assert before == {m.id: (dict(m.styles), dict(m.rate_lift)) for m in w.maps.values()}
    # released, the same rates move dive on every map
    wisp.status = "released"
    tables.derive_map_styles(w)
    assert all(m.rate_lift["dive"] != before[m.id][1]["dive"] for m in w.maps.values())


def test_a_stages_terrain_is_z_scored_across_the_stages_with_text(synthetic_world):
    """Only Forge and Spire have text of their own: each feature one stage
    stresses and the other does not sits one sd either side, and a feature
    neither names reads 0."""
    harbor, ember, salt = _maps(synthetic_world)
    assert set(ember.stage_z) == {"Forge", "Spire"}               # not Courtyard
    zero = dict.fromkeys(TERRAIN_FEATURES, 0.0)
    assert ember.stage_z["Forge"] == {**zero, "hazards": 1.0, "high_ground": -1.0}
    assert ember.stage_z["Spire"] == {**zero, "hazards": -1.0, "high_ground": 1.0}
    assert harbor.stage_z == {} and salt.stage_z == {}


def test_a_heros_best_maps_are_its_largest_positive_lifts_ties_by_name(synthetic_world):
    w = synthetic_world
    best = {h.name: [w.maps[mid].name for mid in h.best_maps] for h in w.heroes.values()}
    assert best == {
        "Anvil": ["Harbor Gate"],                     # +2.5; Salt Flats' -3 is no best map
        "Kite": ["Ember Ruins", "Salt Flats"],        # +3, then +1
        "Mortar": ["Harbor Gate", "Ember Ruins"], "Quarry": ["Salt Flats"],
        "Flint": ["Ember Ruins"], "Gale": ["Ember Ruins"], "Needle": ["Salt Flats"],
        "Rook": ["Harbor Gate"], "Balm": ["Harbor Gate"],
        "Myrrh": ["Ember Ruins", "Harbor Gate"],      # +1.5 on both: by name
        "Sorrel": ["Ember Ruins"], "Tansy": ["Salt Flats"],
        "Wisp": []}                                   # no rates, no best maps
    # three at most: ahead on four maps, Kite keeps the three largest lifts
    w.maps[4] = Map(4, "Anchor Bay", "Push")
    kite = w.hero("Kite")
    kite.map_rates[w.map("Harbor Gate").id] = MapRate(kite.win + 2.0, 8.0)
    kite.map_rates[4] = MapRate(kite.win + 3.0, 5.0)
    tables.derive_best_maps(w)
    assert [w.maps[mid].name for mid in kite.best_maps] == [
        "Anchor Bay", "Ember Ruins", "Harbor Gate"]


def test_a_cell_no_article_writes_reads_the_written_cells_claim_share(synthetic_world):
    """The five claims hold eight cells, and with two cells written off ten
    are written: a cell no article writes reads 0.8, the share that claim,
    whether or not the cells name the claims. A pair has two cells, one in
    each hero's article: Anvil+Rook, written by neither, reads 1.6, the
    mean of the seven written pairs as they read; Gale+Sorrel, which
    Gale's claims, 1.8; Anvil+Mortar, which Anvil's writes off, 0.8. A
    second cell written off moves both. With no cell on record the share
    is 0 and no cell is unwritten, as a database migrated and not pulled
    again reads."""
    w = synthetic_world
    ids = {h.name: h.id for h in w.heroes.values()}
    tables.impute_synergy(w)
    assert w.synergy_cell == 0.0 and w.unwritten_cells(ids["Anvil"], ids["Rook"]) == 0
    off = {(ids["Anvil"], ids["Mortar"]), (ids["Kite"], ids["Rook"])}
    claims = {(ids[a], ids[b]) for a, b in (
        ("Anvil", "Balm"), ("Balm", "Anvil"), ("Kite", "Gale"), ("Gale", "Kite"),
        ("Gale", "Sorrel"), ("Needle", "Tansy"), ("Tansy", "Needle"), ("Mortar", "Myrrh"))}
    for written in (off, off | claims):
        w.synergy_written = written
        tables.impute_synergy(w)
        assert w.synergy_cell == 0.8
    cells = {pair: w.unwritten_cells(ids[pair[0]], ids[pair[1]]) for pair in (
        ("Anvil", "Rook"), ("Rook", "Anvil"), ("Gale", "Sorrel"), ("Anvil", "Mortar"),
        ("Anvil", "Balm"))}
    assert cells == {("Anvil", "Rook"): 2, ("Rook", "Anvil"): 2, ("Gale", "Sorrel"): 1,
                     ("Anvil", "Mortar"): 1, ("Anvil", "Balm"): 0}
    scores = [pair_score(w, ids[a], ids[b]) for a, b in (
        ("Anvil", "Mortar"), ("Anvil", "Rook"), ("Gale", "Sorrel"), ("Anvil", "Balm"))]
    assert scores == [0.8, 1.6, 1.8, 2]
    written_pairs = {frozenset(cell) for cell in off | claims}
    assert len(written_pairs) == 7 and sum(
        pair_score(w, *pair) for pair in written_pairs) / 7 == pytest.approx(1.6)
    # Mortar's article writes Anvil off too: the pair reads 0, and eight of eleven claim
    w.synergy_written = off | claims | {(ids["Mortar"], ids["Anvil"])}
    tables.impute_synergy(w)
    assert pair_score(w, ids["Anvil"], ids["Mortar"]) == 0 and w.synergy_cell == 8 / 11
