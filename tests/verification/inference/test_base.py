"""The default engine: each of its three terms worked by hand, the pick
rate's pull toward a coin flip, the other side it reads - the likely six
until that side locks a pick, from either seat - a board the same under
any hash seed, the facts its terms cite, and a playbook of
assumptions alone scored by it, its best six the enumerated maximum. Every
board is the synthetic World's: no database."""

import copy
import dataclasses
import itertools
import json
import os
import shutil
import subprocess
import sys

import pytest

from db import ROOT
from facts import compute, counters
from facts.draft import Draft
from facts.factset import FactSet
from facts.records import DerivedEdge, Fired, MapRate
from inference import base, catalog, engine, scoring
from inference.base import OFF
from tests.verification.inference import (
    ASSUMPTIONS_ONLY,
    BRIEF,
    DEFAULT,
    FIXTURE_PLAYBOOK,
    timeless,
)

SIX = ("Anvil", "Kite", "Rook", "Needle", "Balm", "Tansy")


def heroes(world, names):
    return [world.hero(n) for n in names]


def prepared(world, map_name, red, six, playbook=ASSUMPTIONS_ONLY, weights=DEFAULT, banned=()):
    """The Objective of a board and a six prepared and scored on it."""
    m = world.map(map_name) if map_name else None
    objective = scoring.Objective(world, m, red=heroes(world, red), catalog=playbook,
                                  base=weights, banned=heroes(world, banned))
    return objective, objective.score(objective.prepare(scoring.Candidate(heroes(world, six))))


def test_the_rate_term_is_each_picks_edge_over_a_coin_flip_trusted_by_its_pick_rate(
        synthetic_world):
    """On Harbor Gate a pick's win and pick rate are the map's; with no map,
    or no row for the hero, its overall ones; a row with no pick rate takes
    the overall pick rate. The term is the mean over the six, in points."""
    w = synthetic_world
    harbor = w.map("Harbor Gate")
    half = base.RATE_PICK_HALF
    # Harbor Gate's rows: Anvil 52.5 on 12, Kite 50 on 8, Rook 53.5 on 7, Needle 50 on 9,
    # Balm 52 on 10, Tansy 49 on 4.5
    edges = [
        12 / (12 + half) * 2.5, 0.0, 7 / (7 + half) * 3.5, 0.0, 10 / (10 + half) * 2.0,
        4.5 / (4.5 + half) * -1.0]
    for name, edge in zip(SIX, edges, strict=True):
        assert base.rate_edge(w.hero(name), harbor) == pytest.approx(edge), name
    _, cand = prepared(w, "Harbor Gate", ("Mortar", "Gale"), SIX)
    assert cand.terms.rates == pytest.approx(sum(edges) / 6)
    # no map: Rook's overall 51.5 on 8
    rook = w.hero("Rook")
    assert base.rate_edge(rook, None) == pytest.approx(8 / (8 + half) * 1.5)
    unrowed = copy.copy(rook)
    unrowed.map_rates = {k: v for k, v in rook.map_rates.items() if k != harbor.id}
    assert base.rate_edge(unrowed, harbor) == base.rate_edge(rook, None)
    unpicked = copy.copy(rook)
    unpicked.map_rates = {**rook.map_rates, harbor.id: MapRate(53.5, None)}
    assert base.rate_edge(unpicked, harbor) == pytest.approx(8 / (8 + half) * 3.5)


def test_a_rarely_picked_heroes_edge_is_pulled_toward_a_coin_flip(synthetic_world):
    """trust = p / (p + RATE_PICK_HALF): half the edge at RATE_PICK_HALF, less
    below it, none at no pick rate, nearly all of it for a staple."""
    rook = copy.copy(synthetic_world.hero("Rook"))
    rook.map_rates = {}
    rook.win = 54.0

    def edge(pick):
        rook.pick = pick
        return base.rate_edge(rook, None)
    half = base.RATE_PICK_HALF
    assert edge(half) == pytest.approx(2.0)
    assert edge(half / 3) == pytest.approx(1.0) and edge(0.0) == 0.0 and edge(None) == 0.0
    assert 3.9 < edge(100 * half) < 4.0
    picks = [0.5, 1.0, half, 2 * half, 10 * half]
    assert [edge(p) for p in picks] == sorted(edge(p) for p in picks)
    rook.win = 46.0
    assert edge(half) == pytest.approx(-2.0)          # a weak hero's deficit is pulled in too


def test_the_synergy_and_counter_terms_read_the_wikis_pairs_and_edges(synthetic_world):
    """Synergy is team.synergy_score (Anvil+Balm 2, Needle+Tansy 2); against
    red's locked picks the counter term is the graph's weight each way, every
    edge here the wiki's at WIKI_WEIGHT: Anvil answers Mortar, Needle answers
    Gale, Gale answers Anvil - two in, one back, twice team.net_edges. Each
    term is its weight times its raw value, and the score their sum."""
    objective, cand = prepared(synthetic_world, "Harbor Gate", ("Mortar", "Gale"), SIX)
    team = cand.ns["team"]
    assert cand.terms.synergy == team["synergy_score"] == 4
    assert (cand.terms.answers, cand.terms.exposures) == (4, 2)
    assert cand.terms.counters == counters.WIKI_WEIGHT * team["net_edges"] == 2
    assert objective.base.opponent == base.Opponent(
        heroes=tuple(heroes(synthetic_world, ("Mortar", "Gale"))), likely=False)
    terms = {c["id"]: c for c in cand.contributions}
    assert list(terms) == [base.RATES, base.SYNERGY, base.COUNTERS]    # nothing else scores
    for key, raw, weight in ((base.RATES, cand.terms.rates, DEFAULT.rate),
                             (base.SYNERGY, 4, DEFAULT.synergy),
                             (base.COUNTERS, 2, DEFAULT.counter)):
        c = terms[key]
        assert c["kind"] == c["form"] == "base" and c["applies"]
        assert c["raw"] == pytest.approx(raw) and c["weight"] == weight
        assert c["weighted"] == pytest.approx(weight * raw)
    assert cand.score == pytest.approx(sum(c["weighted"] for c in cand.contributions))
    assert terms[base.COUNTERS]["against"] == ["Mortar", "Gale"]


def test_off_adds_nothing_and_the_playbook_scores_alone(synthetic_world):
    """OFF: no base terms, no base breakdown, and a six scores what the
    playbook's terms sum to; the default engine adds exactly its value."""
    fix = catalog.load(FIXTURE_PLAYBOOK)
    off_objective, off = prepared(synthetic_world, "Harbor Gate", ("Mortar", "Gale"), SIX, fix,
                                  OFF)
    assert off_objective.base is None and off.terms is None
    assert not any(c["kind"] == "base" for c in off.contributions)
    on_objective, on = prepared(synthetic_world, "Harbor Gate", ("Mortar", "Gale"), SIX, fix)
    on_objective.adopt_bounds(off_objective.bounds)
    assert on.score - off.score == pytest.approx(on_objective.base.value(on.terms))


def test_the_counters_read_the_likely_six_until_the_other_side_locks_a_pick(synthetic_world):
    """With no red pick the counter term reads red's likely six on the map,
    past the bans - the six the board's red panel shows - and nothing else
    does: team.net_edges and every enemy.* key still read an empty red. One
    locked pick and the term reads that pick alone."""
    w = synthetic_world
    likely = [p["hero"] for p in compute.expected_picks(w, w.map("Harbor Gate"),
                                                        banned=heroes(w, ("Needle",)))]
    assert "Needle" not in likely and len(likely) == 6
    objective, cand = prepared(w, "Harbor Gate", (), SIX, banned=("Needle",))
    assert objective.base.opponent.likely and objective.red == []
    assert [h.name for h in objective.base.opponent.heroes] == likely
    answers = sum(counters.WIKI_WEIGHT for e in likely for h in SIX
                  if w.is_countered_by(w.hero(e).id, w.hero(h).id))
    exposures = sum(counters.WIKI_WEIGHT for h in SIX for e in likely
                    if w.is_countered_by(w.hero(h).id, w.hero(e).id))
    assert (cand.terms.answers, cand.terms.exposures) == (answers, exposures) != (0, 0)
    assert cand.ns["team"]["net_edges"] == 0 and cand.ns["enemy"]["size"] == 0
    assert objective.static["enemy"] == scoring.team_metrics(w, [], w.map("Harbor Gate"), ())
    _, locked = prepared(w, "Harbor Gate", ("Gale",), SIX, banned=("Needle",))
    # Needle answers Gale, Gale answers Anvil: a wiki edge each way
    assert (locked.terms.answers, locked.terms.exposures) == (2, 2)
    [c] = [c for c in locked.contributions if c["id"] == base.COUNTERS]
    assert c["against"] == ["Gale"] and c["likely"] is False
    # handed exactly the likely six as picks, as the board hands blue's seat, it is
    # the likely six still
    objective, _ = prepared(w, "Harbor Gate", likely, SIX[:1], banned=("Needle",))
    assert objective.base.opponent.likely


def test_each_seat_reads_the_other_sides_likely_six_or_its_picks(synthetic_world):
    """The board's two seats alike: before blue picks, red's optimal reads
    blue's likely six as blue's optimal reads red's; once blue locks a pick,
    red's reads that pick. Each counter term cites the fact that says which."""
    empty = engine.board(synthetic_world, Draft("Harbor Gate", side="attack"),
                         catalog=ASSUMPTIONS_ONLY, brief=BRIEF)
    likely = empty.expected.blue
    # the plan says the six counters it, and names the engine's terms it is built on
    assert "No red pick yet: the six counters their likely six (" in empty.plan
    assert "Above all: win rates here" in empty.plan
    for seat, other in ((empty.blue, "red"), (empty.red, "blue")):
        [c] = [c for c in seat.contributions if c["id"] == base.COUNTERS]
        assert sorted(c["against"]) == sorted(likely) and c["likely"], seat.seat
        assert c["text"] == "counters read %s's likely six on Harbor Gate: %s - %d into it, %d" \
            " back (%+d), a wiki edge 2 and a derived one 1" % (
                other, ", ".join(c["against"]), c["answers"], c["exposures"],
                c["answers"] - c["exposures"])
    held = engine.board(synthetic_world, Draft("Harbor Gate", (), ("Balm",), side="attack"),
                        catalog=ASSUMPTIONS_ONLY, brief=BRIEF)
    [c] = [c for c in held.red.contributions if c["id"] == base.COUNTERS]
    assert c["against"] == ["Balm"] and not c["likely"]
    assert c["text"].startswith("counters read blue as it stands: Balm - ")
    [c] = [c for c in held.blue.contributions if c["id"] == base.COUNTERS]
    assert c["likely"] and sorted(c["against"]) == sorted(likely)


# red revealed and one blue pick locked on a sided map: every seat of the board solves
TRACED = Draft("Harbor Gate", ("Anvil",), ("Balm",), side="attack")

# one board solved in a fresh process, its payload printed as JSON less the seconds
ONE_BOARD = """
import json, sys
from facts.draft import Draft
from inference import catalog, engine
from tests import synthetic
from tests.verification.inference import timeless
map_name, side, red, blue = json.loads(sys.argv[1])
board = engine.board(synthetic.world(), Draft(map_name, tuple(red), tuple(blue), side=side),
                     catalog=catalog.load(), brief=engine.Brief())
print(json.dumps(timeless(board.to_dict()), sort_keys=True, default=str))
"""


@pytest.mark.parametrize("playbook", ["reference", "assumptions"])
def test_a_board_is_the_same_under_any_hash_seed(tmp_path, playbook):
    """The search is exact and ranks by a total order, so nothing a set or a
    dict iterates in reaches the answer: each board, solved in two fresh
    processes whose string hashes differ, is the same payload, the seconds
    aside - with the default engine on, under the reference playbook and
    under assumptions alone, with red revealed and red's likely six in its
    place, and a full six on either side."""
    folder = FIXTURE_PLAYBOOK
    if playbook == "assumptions":
        folder = str(tmp_path)
        for name in [s.id + ".md" for s in ASSUMPTIONS_ONLY] + [catalog.META_FILE]:
            shutil.copy(os.path.join(FIXTURE_PLAYBOOK, name), tmp_path)
    for draft in (Draft("Harbor Gate", side="attack"), TRACED,
                  Draft("Harbor Gate", ("Mortar",), SIX, side="attack"),
                  Draft("Harbor Gate", SIX, side="attack")):
        board = json.dumps([draft.map_name, draft.side, draft.red, draft.blue])
        payloads = [subprocess.run(
            [sys.executable, "-c", ONE_BOARD, board], cwd=ROOT, capture_output=True, text=True,
            check=True, env={**os.environ, "PYTHONHASHSEED": seed,
                             "COUNTRIX_STRATEGIES": folder}).stdout
            for seed in ("1", "2")]
        assert payloads[0] == payloads[1] and '"blue": {' in payloads[0], draft


def test_every_base_term_cites_a_fact_the_result_carries(synthetic_world):
    """The rate and counter terms cite facts of their own, written after the
    board's; the synergy term cites the board's cohesion fact. The page reads
    them through `cited`."""
    r = engine.infer(synthetic_world, Draft("Harbor Gate", ("Mortar",), side="attack"),
                     catalog=ASSUMPTIONS_ONLY, base=DEFAULT)
    board_facts = engine._board_facts(synthetic_world, r, "attack").facts
    cited = r.to_dict()["cited"]
    for c in r.contributions:
        assert c["fact"] in cited and cited[c["fact"]] == c["text"], c["id"]
    terms = {c["id"]: c for c in r.contributions}
    assert terms[base.SYNERGY]["fact"] in {f.id for f in board_facts}
    assert terms[base.RATES]["text"].startswith("blue's six on Harbor Gate: ")
    assert terms[base.COUNTERS]["text"].startswith("counters read red as it stands: Mortar")
    assert int(terms[base.RATES]["fact"][1:]) > len([f for f in board_facts if f.id[0] == "F"])


def test_a_playbook_of_assumptions_scores_by_the_engine_and_its_best_six_is_the_maximum(
        synthetic_world):
    """A playbook of assumptions alone, as the shipped one was before its
    first rule. Every seat scores, no badge reads unscored, and blue's
    optimal is the best of every legal six by the engine's terms, the
    tie-break after them, found by enumeration."""
    w = synthetic_world
    draft = Draft("Ember Ruins", ("Mortar",), side="")
    b = engine.board(w, draft, catalog=ASSUMPTIONS_ONLY, brief=BRIEF)
    d = b.to_dict()
    for key in ("blue", "red", "current", "red_current"):
        assert d[key]["scoring"] is True and d[key]["unscored"] is None, key
    badges = d["momentum"]["badges"]
    assert badges["blue"]["label"] == "100 / 100"
    assert badges["red"]["label"] == "%d / 100" % d["momentum"]["red"]   # red's pick, filled
    objective = scoring.Objective(w, w.map("Ember Ruins"), red=heroes(w, ("Mortar",)),
                                  catalog=ASSUMPTIONS_ONLY, base=DEFAULT)
    released = [h for h in w.heroes.values() if h.released]
    sixes = [
        scoring.Candidate(six) for six in itertools.combinations(released, 6)
        if sum(1 for h in six if h.role == "tank") <= 2]
    ranked = sorted((objective.score(objective.prepare(c), detail=False) for c in sixes),
                    key=lambda c: (-c.score, -c.tiebreak, sorted(c.names)))
    assert sorted(b.blue.blue) == sorted(ranked[0].names)
    assert b.blue.score == pytest.approx(ranked[0].score) and ranked[0].score > ranked[1].score
    assert b.blue.alternatives[0]["score"] == pytest.approx(ranked[1].score, abs=1e-3)


def test_a_derived_edge_counts_half_a_wiki_edge_and_the_fact_names_it(synthetic_world):
    """The kit derives Mortar answering Kite on a pair the wiki leaves out:
    against red's Mortar a six holding Kite takes DERIVED_WEIGHT back, where
    the wiki's Anvil over Mortar gives WIKI_WEIGHT in; the counter fact names
    the derived edge with its mechanism and numbers, and a derived edge on a
    pair the wiki reads either way counts nothing."""
    w = synthetic_world
    kite, mortar, anvil = w.hero("Kite"), w.hero("Mortar"), w.hero("Anvil")
    fired = (Fired("antiair", 1.0, "hitscan against a flier", "Longshot, hitscan, 60 m"),)
    w.derived[(kite.id, mortar.id)] = DerivedEdge(
        winner=mortar.id, loser=kite.id, score=1.0, net=1.0, fired=fired)
    w.derived[(anvil.id, mortar.id)] = DerivedEdge(      # the wiki reads Anvil over Mortar
        winner=mortar.id, loser=anvil.id, score=1.0, net=1.0, fired=fired)
    six = ("Anvil", "Kite", "Needle", "Sorrel", "Balm", "Tansy")
    _, cand = prepared(w, "Harbor Gate", ("Mortar",), six)
    assert (cand.terms.answers, cand.terms.exposures) == (
        counters.WIKI_WEIGHT, counters.DERIVED_WEIGHT) == (2, 1)
    [c] = [c for c in cand.contributions if c["id"] == base.COUNTERS]
    assert c["derived"] == [
        "Mortar answers Kite - derived: hitscan against a flier (Longshot, hitscan, 60 m)"]
    fs = FactSet(Draft("Harbor Gate", ("Mortar",), six))
    fact = base.write_counters_fact(
        fs, seat="blue", map_name="Harbor Gate", against=c["against"], likely=False,
        answers=c["answers"], exposures=c["exposures"], derived=c["derived"])
    assert fact.text.endswith("(+1), a wiki edge 2 and a derived one 1; Mortar answers Kite -"
                              " derived: hitscan against a flier (Longshot, hitscan, 60 m)")


def test_the_stamp_holds_a_derived_edges_weight_and_what_an_unwritten_pair_reads():
    stamped = base.stamp(DEFAULT)
    assert stamped is not None and stamped["derived"] == 0.5
    assert stamped["unwritten"] == base.UNWRITTEN_SYNERGY == "the written cells' claim share a cell"
    assert (stamped["meta"], stamped["counter"]) == (DEFAULT.meta, DEFAULT.counter)
    assert base.stamp(OFF) is None


def test_the_synergy_term_reads_a_cell_no_article_writes_at_half_the_prior(synthetic_world):
    """SIX holds two claimed pairs (Anvil+Balm, Needle+Tansy, 4 in all) and
    thirteen pairs no article claims. A cell written off reads 0, and one
    no article writes the written cells' claim share: ten pairs written off
    in both articles, two in one article and one in neither leave four
    blank cells, and the term and its fact say so."""
    w = synthetic_world
    six = heroes(w, SIX)
    others = [
        (a.id, b.id) for a, b in itertools.combinations(six, 2) if w.synergy(a.id, b.id) is None]
    assert len(others) == 13
    w.synergy_written = {(a, b) for a, b in others[:12]} | {(b, a) for a, b in others[:10]}
    w.synergy_cell = 0.25
    _, cand = prepared(w, "Harbor Gate", ("Mortar", "Gale"), SIX)
    assert cand.ns["team"]["unwritten_cells"] == 4
    assert cand.terms.synergy == cand.ns["team"]["synergy_score"] == 4 + 4 * 0.25
    [c] = [c for c in cand.contributions if c["id"] == base.SYNERGY]
    assert c["raw"] == 5.0 and c["weighted"] == pytest.approx(DEFAULT.synergy * 5.0)
    assert "a cell no article writes at the written cells' claim share" in c["metric"]


def test_the_reference_weights_are_the_calibrated_engine_and_off_is_meta_zero():
    """The reference playbook's meta.md holds the weights the engine was
    first calibrated at, while an unwritten synergy pair read 0 - the rate
    term in win-rate points, synergy and counter at half its median spread
    each - under a meta of 1, whatever the live file moves to; OFF is the
    meta at 0,
    and a meta of 0 over any dials scores nothing, as OFF does."""
    assert DEFAULT.record() == {"meta": 1.0, "rate": 1.0, "synergy": 0.1, "counter": 0.05}
    assert DEFAULT.on and OFF.meta == 0 and not OFF.on
    assert not DEFAULT.metered({base.META: 0.0}).on
    assert DEFAULT.scaled() == base.TermWeights(rate=1.0, synergy=0.1, counter=0.05)


def test_the_meta_scales_every_term_and_nothing_else(synthetic_world):
    """At meta 2 each base term weighs twice its dial and the engine's value
    doubles, bit for bit; the playbook's terms do not move. A board's
    weights set the meta for that board alone (BaseWeights.metered), and
    leave a weights mapping without it as they found it."""
    fix = catalog.load(FIXTURE_PLAYBOOK)
    doubled = DEFAULT.metered({base.META: 2.0, "coverage": 3.0})
    assert doubled.record() == dict(DEFAULT.record(), meta=2.0)
    assert DEFAULT.metered({"coverage": 3.0}) is DEFAULT and DEFAULT.metered(None) is DEFAULT
    one_objective, one = prepared(synthetic_world, "Harbor Gate", ("Mortar", "Gale"), SIX, fix)
    two_objective, two = prepared(synthetic_world, "Harbor Gate", ("Mortar", "Gale"), SIX, fix,
                                  doubled)
    assert two_objective.base.value(two.terms) == 2 * one_objective.base.value(one.terms)
    assert two.score - one.score == pytest.approx(one_objective.base.value(one.terms))
    ones = {c["id"]: c for c in one.contributions}
    for c in two.contributions:
        if c["kind"] == "base":
            assert c["weight"] == 2 * ones[c["id"]]["weight"]
            assert c["weighted"] == 2 * ones[c["id"]]["weighted"]
        else:
            assert c["weighted"] == ones[c["id"]]["weighted"], c["id"]


def test_a_board_at_meta_zero_is_the_board_off(synthetic_world):
    """The Meta slider at 0 is OFF: every seat of the board scores, ranks and
    reads as it does with the engine off, blue's swaps too, and only the
    weights each result records say which it was."""
    fix = catalog.load(FIXTURE_PLAYBOOK)
    draft = Draft("Harbor Gate", ("Mortar",), ("Balm",), side="attack")
    zero = engine.board(synthetic_world, draft, catalog=fix, brief=engine.Brief(
        base=DEFAULT, weights={base.META: 0.0}, swap=10.0)).to_dict()
    off = engine.board(synthetic_world, draft, catalog=fix,
                       brief=engine.Brief(base=OFF, swap=10.0)).to_dict()
    assert zero["swaps"] is not None
    seats = ("blue", "red", "current", "red_current", "fill", "countered", "expected")
    assert [zero[k]["base"] for k in seats] == [dict(DEFAULT.record(), meta=0.0)] * len(seats)
    assert [off[k]["base"] for k in seats] == [OFF.record()] * len(seats)
    for payload in (zero, off):
        for k in seats:
            payload[k].pop("base")
    assert timeless(zero) == timeless(off)


def test_a_board_that_names_no_weights_reads_the_playbooks_meta_file(
        synthetic_world, monkeypatch, tmp_path):
    """No base on the brief is the playbook in force's meta.md: a copy of the
    reference playbook whose meta.md says 0.5 scores every seat at half the
    engine, and says so in every result."""
    for name in os.listdir(FIXTURE_PLAYBOOK):
        shutil.copy(os.path.join(FIXTURE_PLAYBOOK, name), tmp_path)
    meta = tmp_path / catalog.META_FILE
    meta.write_text(meta.read_text(encoding="utf-8").replace("meta: 1\n", "meta: 0.5\n"),
                    encoding="utf-8")
    monkeypatch.setenv("COUNTRIX_STRATEGIES", str(tmp_path))
    halved = dataclasses.replace(DEFAULT, meta=0.5)
    assert catalog.engine_weights() == halved == engine.weights_in_force(None)
    b = engine.board(synthetic_world, Draft("Harbor Gate", ("Mortar",), side="attack"))
    assert b.blue.base == halved and b.to_dict()["blue"]["base"]["meta"] == 0.5
    rates = next(c for c in b.blue.contributions if c["id"] == base.RATES)
    assert rates["weight"] == 0.5 * DEFAULT.rate
    assert engine.infer(synthetic_world, Draft("Harbor Gate")).base == halved
    assert "under the meta at 0.5," in b.blue.rendered()
