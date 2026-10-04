"""The scale's field read lean (Objective.lean_keys, measure_lean): on a
playbook whose heuristics read team keys under gates the board settles, or
gates the six decides from team keys, the field read on those keys alone
gives the bounds and the floor the field prepared whole gives, bit for bit;
a playbook that needs more - a matchup metric, a gate that reads one, a
limit on a metric - is prepared whole. No database."""

import os

import pytest

from facts.draft import Draft
from inference import catalog
from inference.scoring import Objective
from tests.verification.inference import ASSUMPTIONS_ONLY, DEFAULT, FIXTURE_PLAYBOOK
from tests.verification.inference.enumeration import seated

RULES = {
    "points-reward-control": ("team.cc_count", "maximize", 1, "map.chokes >= 0.5"),
    "hazards-want-mobility": ("team.mobility_count", "maximize", 2.5, "map.hazards >= 1"),
    "short-reach-loses": ("team.range_min", "maximize", 1, None),
    "fewer-barriers": ("team.barrier_hp", "minimize", 0.25, "map.mode == 'Control'"),
    "enemy-dives": ("team.flyers", "maximize", 1, "enemy.flyers >= 1"),
}


def playbook(directory, rules=RULES):
    """The reference playbook's assumptions and heuristics on team keys, each
    under a gate the board settles or none, or the given rules'."""
    for sid, (metric, direction, weight, when) in rules.items():
        guard = "when: %s\n" % when if when else ""
        with open(os.path.join(directory, sid + ".md"), "w", encoding="utf-8") as handle:
            handle.write("---\nname: %s\nkind: heuristic\nmetric: %s\ndirection: %s\n"
                         "weight: %s\n%s---\nA rule.\n" % (sid, metric, direction, weight, guard))
    return [*ASSUMPTIONS_ONLY, *catalog.load(directory)]


@pytest.mark.parametrize("draft", [Draft("Harbor Gate", ("Mortar", "Gale"), side="attack"),
                                   Draft("Ember Ruins", ("Kite",), stage="Forge")],
                         ids=["harbor", "forge"])
def test_the_lean_field_measures_what_the_whole_one_does(synthetic_world, tmp_path, monkeypatch,
                                                         draft):
    """The same board frozen twice - its field read lean, then prepared
    whole - holds the same scale and the same floor, bit for bit."""
    rules = playbook(str(tmp_path))
    lean = seated(synthetic_world, draft, rules, DEFAULT)
    assert lean.lean_keys() == frozenset({"cc_count", "mobility_count", "range_min",
                                          "barrier_hp", "flyers"})
    lean.freeze_scale()
    monkeypatch.setattr(Objective, "lean_keys", lambda self: None)
    whole = seated(synthetic_world, draft, rules, DEFAULT)
    whole.freeze_scale()
    assert lean.scale == whole.scale and lean.floor == whole.floor


def test_a_need_the_six_decides_from_team_keys_is_read_lean_too(synthetic_world, tmp_path,
                                                                monkeypatch):
    """A need guarded on the six's own team keys - two tanks wanting reach -
    reads its guard's keys on the lean bag and counts only where the guard
    holds, as prepare(measure=True) does: the same scale and floor."""
    rules = {**RULES, "two-tanks-want-reach": ("team.range_median", "maximize", 1,
                                               "team.tanks >= 2")}
    draft = Draft("Harbor Gate", ("Mortar", "Gale"), side="attack")
    book = playbook(str(tmp_path), rules)
    lean = seated(synthetic_world, draft, book, DEFAULT)
    assert {"tanks", "range_median"} <= lean.lean_keys()
    lean.freeze_scale()
    monkeypatch.setattr(Objective, "lean_keys", lambda self: None)
    whole = seated(synthetic_world, draft, book, DEFAULT)
    whole.freeze_scale()
    assert lean.scale == whole.scale and lean.floor == whole.floor
    assert "two-tanks-want-reach" in whole.scale


def test_a_playbook_that_needs_more_is_prepared_whole(synthetic_world):
    """The reference playbook reads matchup metrics, so its field is
    prepared whole."""
    solver = seated(synthetic_world, Draft("Harbor Gate", ("Mortar",)),
                    catalog.load(FIXTURE_PLAYBOOK), DEFAULT)
    assert solver.lean_keys() is None
