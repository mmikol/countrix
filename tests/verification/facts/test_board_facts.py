"""A board's facts from facts/board_facts.py, on the synthetic World: the
order and the numbering, the team and matchup facts, the warnings, the bans
and the sides, each worded from what tests/synthetic.py sets. No database."""

import pytest

from db import Refusal
from facts import board_facts
from facts.draft import Draft
from facts.records import Patch


def test_every_fact_is_keyed_and_the_meta_comes_first(synthetic_world):
    fs = board_facts.generate(synthetic_world, Draft("Harbor Gate", ("Mortar", "Gale"), ("Balm",)))
    assert all(f.key and f.scope and f.text for f in fs.facts)
    assert fs.facts[0].scope == "meta" and fs.facts[0].text == (
        "blizzard rates: captured 2026-09-01, September 1, 2026 Patch (2026-09-01)"
        " - role queue, pc, Americas")
    assert {"map", "hero", "team", "matchup"} <= {f.scope for f in fs.facts}


def test_facts_are_numbered_densely_in_the_order_they_are_written(synthetic_world):
    # FACTS = INDEPENDENT ∪ DEPENDENT, F1..
    fs = board_facts.generate(synthetic_world, Draft("Harbor Gate", ("Mortar", "Gale"), ("Balm",)))
    assert [f.id for f in fs.facts] == ["F%d" % i for i in range(1, len(fs.facts) + 1)]
    assert {f.scope for f in fs.facts} <= {"meta", "bans", "map", "hero", "team", "matchup"}
    assert fs.count == len(fs.facts) == fs.to_dict()["count"]
    lines = fs.rendered().splitlines()
    assert lines[0].startswith("[F1] ") and lines[-1].startswith("[F%d] " % fs.count)
    assert len(lines) == fs.count


def test_each_side_reads_tank_damage_support_and_the_draft_keeps_the_order_named(
        synthetic_world):
    """The facts take each side as every view shows a six (by_role): its
    heroes' facts tanks first, then damage, then supports, each role in the
    order named, and a sentence that lists a side lists it the same way. The
    FactSet's draft, which the facts route echoes, keeps the order named."""
    red, blue = ("Gale", "Balm", "Mortar"), ("Sorrel", "Rook", "Anvil", "Kite")
    fs = board_facts.generate(synthetic_world, Draft("Harbor Gate", red, blue))
    # a heading a run of one hero's facts, as the facts tab draws them
    heads = []
    for f in fs.facts:
        if f.scope == "hero" and (not heads or heads[-1] != (f.team, f.subject)):
            heads.append((f.team, f.subject))
    assert heads == [("red", "Mortar"), ("red", "Gale"), ("red", "Balm"), ("blue", "Anvil"),
                     ("blue", "Kite"), ("blue", "Rook"), ("blue", "Sorrel")]
    [size] = fs.find("team.size", "blue")
    assert size.text == "blue team: 4 picks locked (Anvil, Kite, Rook, Sorrel), 2 slots open"
    [size] = fs.find("team.size", "red")
    assert size.text == "red team: 3 picks locked (Mortar, Gale, Balm), 3 slots open"
    assert (fs.draft.red, fs.draft.blue) == (red, blue)
    assert (fs.to_dict()["red"], fs.to_dict()["blue"]) == (list(red), list(blue))


def test_team_facts_appear_per_side_and_matchup_only_with_both(synthetic_world):
    w = synthetic_world
    fs = board_facts.generate(w, Draft("Harbor Gate", ("Mortar", "Gale")))
    scopes = {f.scope for f in fs.facts}
    assert "team" in scopes and "matchup" not in scopes
    assert fs.find("team.tanks", "red")
    fs = board_facts.generate(w, Draft("Harbor Gate", ("Mortar", "Gale"), ("Balm", "Anvil")))
    assert fs.find("team.coverage", "blue") and fs.find("matchup.coverage_share")


def test_a_board_fact_that_warns_carries_its_flag(synthetic_world):
    """A warning carries its flag, which the board marks it by; a patch
    shipped since the rates is one. The sentences are test_hero_facts' and
    test_team_facts'."""
    w = synthetic_world
    fs = board_facts.generate(w, Draft(None, ("Anvil",), ("Mortar",)))
    assert [f.key for f in fs.facts if f.warn] == ["hero.vs_answered_by"]
    w.newer_patches = [Patch("a patch", "2026-09-30")]
    (vintage,) = board_facts.generate(w, Draft()).find("meta.vintage_warning")
    assert vintage.warn and vintage.text.startswith("WARNING: 1 patch(es) shipped")


def test_bans_become_facts_and_a_banned_pick_is_refused(synthetic_world):
    w = synthetic_world
    fs = board_facts.generate(w, Draft("Harbor Gate", ("Mortar", "Gale"), ("Balm",),
                                       bans=("Needle", "Rook")))
    assert fs.draft.bans == ("Needle", "Rook")
    assert fs.find("bans.count")[0].text == "bans this match: 2 of 5 - Needle, Rook"
    assert len(fs.find("bans.hero")) == 2
    # Needle answers Gale and Rook answers Balm: each ban took an answer off the table
    assert fs.find("bans.answered_red")[0].text == (
        "banned Needle answered red Gale - that answer is off the table")
    assert fs.find("bans.answered_blue")[0].text == (
        "banned Rook answered blue Balm - that threat is gone")
    with pytest.raises(Refusal, match="banned this match"):
        board_facts.generate(w, Draft(None, ("Mortar",), ("Balm",), bans=("Balm",)))
    with pytest.raises(Refusal, match="unknown heroes"):
        board_facts.generate(w, Draft(bans=("Nemo",)))


def test_sides_exist_only_on_escort_and_hybrid(synthetic_world):
    w = synthetic_world
    fs = board_facts.generate(w, Draft("Harbor Gate", ("Mortar",), ("Balm",), side="attack"))
    assert fs.draft.side == "attack"
    assert [f.text for f in fs.find("map.side")] == ["blue attacks Harbor Gate; red defends"]
    assert fs.find("map.side_caveat")
    fs = board_facts.generate(w, Draft("Ember Ruins", side="attack"))
    assert fs.draft.side == ""
    assert [f.text for f in fs.find("map.side")] == [
        "Ember Ruins (Control) has no attacking or defending side"]


def test_the_ground_in_play_is_a_fact_only_where_a_stage_is_named(synthetic_world):
    """A stage named, the map.ground fact states each feature above the
    ordinary map as the map.* metrics read it there - largest first, each
    saying whose text it came from - and is filed under those metrics, so a
    rule gated on the terrain cites it. The whole map has no such fact, and
    a stage the map does not list is refused."""
    w = synthetic_world
    whole = board_facts.generate(w, Draft("Ember Ruins"))
    assert not whole.find("map.ground") and whole.to_dict()["stage"] == ""
    w.map("Ember Ruins").stage_z["Forge"]["hazards"] = 2.5
    fs = board_facts.generate(w, Draft("Ember Ruins", stage="forge"))
    assert fs.draft.stage == "Forge" and fs.to_dict()["stage"] == "Forge"
    (ground,) = fs.find("map.ground", "Ember Ruins")
    assert ground.text == (
        "Ember Ruins - Forge is the ground in play: hazards 2.5 sd above the ordinary (the"
        " stage's text); flanks 1.0 sd above the ordinary (the map's article); high ground"
        " 1.0 sd above the ordinary (the map's article); open ground 1.0 sd above the"
        " ordinary (the map's article)")
    assert ground.value["features"][0] == {"feature": "hazards", "z": 2.5, "source": "stage"}
    assert fs.find("map.hazards", "Ember Ruins") == [ground]
    assert not fs.find("map.chokes")                    # below the ordinary: not stated
    with pytest.raises(Refusal, match="Ember Ruins has no stage 'Well'"):
        board_facts.generate(w, Draft("Ember Ruins", stage="Well"))
