"""The plan stage by stage (inference.swaps.chain) held to a full
enumeration on the synthetic World: each phase of Harbor Gate's route the
best six reachable from the phase before under the swap cost, each arena of
Ember Ruins reached from the origin, the chosen stage the origin with the
phases before it played, two stages on one ground one search, the blurb's
sentences dropped when they have nothing to say, and the rows on the
board's payload. Scratch rules on map.objective and map.hazards make the
stages score apart. No database."""

import copy
import dataclasses
import os

import pytest

from facts.draft import Draft
from inference import catalog, engine, plan, swaps
from inference.base import OFF
from inference.result import StageRules
from inference.scoring import Candidate, quantized
from inference.solver import Solver
from tests.verification.inference import ASSUMPTIONS_ONLY, DEFAULT, FIXTURE_PLAYBOOK
from tests.verification.inference.enumeration import netted, plain_seat

COST = 5.0                  # share points of blue's span a hero changed costs
RULES = {
    "payload-needs-control": (
        "---\nname: payload needs control\nkind: heuristic\nmetric: team.cc_count\n"
        "direction: maximize\nweight: 4\nwhen: map.objective == 'payload'\n---\nA rule.\n"),
    "hazards-want-mobility": (
        "---\nname: hazards want mobility\nkind: heuristic\nmetric: team.mobility_count\n"
        "direction: maximize\nweight: 4\nwhen: map.hazards >= 1\n---\nA rule.\n"),
}


@pytest.fixture()
def staged(tmp_path):
    """The reference playbook's assumptions and two scratch rules that read
    the ground in play: a payload wants crowd control, hazards want
    mobility."""
    for sid, text in RULES.items():
        with open(os.path.join(tmp_path, sid + ".md"), "w", encoding="utf-8") as handle:
            handle.write(text)
    return [*ASSUMPTIONS_ONLY, *catalog.load(str(tmp_path))]


@pytest.fixture()
def forged(synthetic_world):
    """The synthetic World with Ember Ruins's hazards read low on the map as
    a whole, so the hazards Forge's own text stresses stand out on Forge
    alone."""
    world = copy.deepcopy(synthetic_world)
    ember = world.resolve("Ember Ruins", (), (), ())[0]
    ember.terrain_z = {**ember.terrain_z, "hazards": -1.0}
    return world


def planned(world, draft, playbook, base, origin, memo=None):
    """The plan's rows for `draft` from `origin` (hero names), as the board
    walks them, and the plain Solver and raw cost they were walked on."""
    plain, span = plain_seat(world, draft, playbook, base)
    raw = swaps.raw_cost(COST, span) or 0.0
    six = world.resolve(None, (), tuple(origin)).blue
    rows = swaps.chain(swaps.ChainStart(plain=plain, chosen=draft.stage, origin=six, raw=raw,
                                        cost=COST), memo)
    return rows, plain, raw


def reachable(plain, stage, reference, raw):
    """The six a stage's row must hold, found by enumeration: every legal six
    of the stage scored on the board's scale less `raw` a reference hero
    dropped; the reference itself where no six beats it."""
    solver = Solver(plain.world, plain.m, red=plain.red, locked=(), side=plain.side,
                    stage=stage, catalog=plain.catalog, base=plain.base)
    solver.adopt_scale(plain)
    heroes = plain.world.resolve(None, (), tuple(reference)).blue
    ref = solver.score(solver.prepare(Candidate(heroes)), detail=False)
    net, best = netted(solver, heroes, raw)[0]
    if {h.id for h in heroes} <= set(best.key) or (
            not ref.violations and quantized(net) <= quantized(ref.score)):
        return sorted(reference)
    return sorted(best.names)


ORIGIN = ("Anvil", "Kite", "Rook", "Needle", "Balm", "Myrrh")


@pytest.mark.parametrize("base", [OFF, DEFAULT], ids=["base-off", "base-on"])
def test_each_phase_is_the_enumerated_best_from_the_phase_before(synthetic_world, staged, base):
    """On Harbor Gate's route, the first phase's six is the best reachable
    from the origin and the second's the best reachable from the first's,
    each hero changed costing the swap cost, element for element with an
    enumeration; the payload's rule makes the second phase score apart."""
    draft = Draft("Harbor Gate", ("Mortar", "Gale"), side="attack")
    rows, plain, raw = planned(synthetic_world, draft, staged, base, ORIGIN)
    assert [(r["stage"], r["kind"]) for r in rows] == [("Assault", "phase"), ("Escort", "phase")]
    reference = ORIGIN
    for row in rows:
        assert row["solved"] and not row["played"] and not row["current"]
        assert sorted(row["six"]) == reachable(plain, row["stage"], reference, raw), row
        reference = tuple(row["six"])
    assert rows[1]["rules"]["on"] == ["payload needs control"]


def test_each_arena_is_reached_from_the_origin(forged, staged):
    """Ember Ruins's arenas come up in no fixed order, so each is the best
    reachable from the origin, never from the arena listed before it; the
    hazards Forge's text stresses turn its rule on there alone."""
    draft = Draft("Ember Ruins", ("Mortar", "Gale"))
    rows, plain, raw = planned(forged, draft, staged, DEFAULT, ORIGIN)
    assert [(r["stage"], r["kind"]) for r in rows] == [
        ("Courtyard", "arena"), ("Forge", "arena"), ("Spire", "arena")]
    for row in rows:
        assert sorted(row["six"]) == reachable(plain, row["stage"], ORIGIN, raw), row
    forge = rows[1]
    assert forge["rules"]["on"] == ["hazards want mobility"]
    assert [g["feature"] for g in forge["ground"] if g["source"] == "stage"] == ["hazards"]


def test_the_chosen_stage_is_the_origin_and_the_phases_before_it_are_played(
        synthetic_world, staged):
    """With the board on Harbor Gate's second phase, the first is played
    and holds no six, and the chosen phase holds the origin itself, marked
    as the board's."""
    draft = Draft("Harbor Gate", ("Mortar", "Gale"), side="attack", stage="Escort")
    rows, _, _ = planned(synthetic_world, draft, staged, DEFAULT, ORIGIN)
    assault, escort = rows
    assert assault["played"] and not assault["six"] and not assault["current"]
    assert escort["current"] and sorted(escort["six"]) == sorted(ORIGIN)
    assert "Play the six the board suggests here" in escort["blurb"]


def test_a_withheld_swap_leaves_the_chosen_stage_the_origin(synthetic_world, monkeypatch):
    """A swap the fight odds hold back is no answer on the board's chosen
    stage: its row plays the six the board suggests, as a board that
    searched no swap reads, and never says no swap pays for its cost."""
    draft = Draft("Harbor Gate", ("Mortar", "Gale"), ORIGIN, side="attack", stage="Escort")
    worse = {"odds": {"blue": 0, "red": 100}}
    monkeypatch.setattr(engine._Pass, "_against", lambda self, draft, six: worse)
    board = engine.board(synthetic_world, draft, catalog=catalog.load(FIXTURE_PLAYBOOK),
                         brief=engine.Brief(base=DEFAULT, solve_countered=False, swap=COST))
    assert board.swaps["status"] == "withheld"
    [escort] = [r for r in board.stages if r["current"]]
    assert sorted(escort["six"]) == sorted(ORIGIN) and escort["swaps"] == []
    assert "Play the six the board suggests here" in escort["blurb"]
    assert "no swap pays" not in escort["blurb"]


def test_an_unscored_seat_walks_its_stages_at_no_cost(synthetic_world):
    """A seat nothing scores has no span to take a share of: its stages are
    walked at no swap cost, and each row that keeps the six quotes that
    cost, not the one the board was asked for."""
    draft = Draft("Harbor Gate", ("Mortar",), ORIGIN, side="attack")
    board = engine.board(synthetic_world, draft, catalog=ASSUMPTIONS_ONLY,
                         brief=engine.Brief(base=OFF, solve_countered=False, swap=COST))
    assert board.swaps["status"] == "none" and len(board.stages) == 2
    for row in board.stages:
        assert "Keep the six: no swap pays for its cost (0)." in row["blurb"], row


def test_two_stages_on_one_ground_are_one_search(forged, staged):
    """Courtyard has no text and Spire's names its high ground one mention
    short, so both read as Ember Ruins and score every six alike: from the
    same origin they are one memoised search, and Forge, whose hazards
    stand out, is another."""
    memo: swaps.Memo = {}
    rows, _, _ = planned(forged, Draft("Ember Ruins", ("Mortar", "Gale")), staged, DEFAULT,
                         ORIGIN, memo)
    assert len(rows) == 3 and len(memo) == 2
    assert rows[0]["six"] == rows[2]["six"]


def test_a_stage_blurb_drops_the_sentences_that_have_nothing_to_say(synthetic_world):
    """A stage with no text of its own, no rule it turns, no swap and no
    turn in the lean reads its ground and that the six holds; a stage with
    swaps names them and what the six gains on; each sentence ends once."""
    m = synthetic_world.resolve("Ember Ruins", (), (), ())[0]
    none = StageRules(on=[], off=[])
    quiet = plan.stage_blurb(m, "Courtyard", (0, 0), none, [], [], COST)
    assert quiet == ("Courtyard: the wiki says too little of it, so it reads as Ember Ruins."
                     " Keep the six: no swap pays for its cost (5).")
    busy = plan.stage_blurb(m, "Forge", (0, 0), StageRules(on=["hazards want mobility"], off=[]),
                            [{"out": "Rook", "in": "Flint"}], ["hazards want mobility"], COST)
    assert busy.startswith("Forge: its own text stresses ")
    assert "Hazards want mobility counts here." in busy
    assert "Swap Rook for Flint: the six gains most on hazards want mobility." in busy
    assert ".." not in busy and busy.count(".") == 3


def test_the_board_carries_the_plan_on_a_staged_map_and_none_elsewhere(synthetic_world, staged):
    """A board on a staged map carries a row a stage, in the payload and in
    the text the board tool prints; a map without stages carries none, and
    a brief can leave the plan out."""
    brief = engine.Brief(base=DEFAULT, solve_countered=False)
    board = engine.board(synthetic_world, Draft("Harbor Gate", ("Mortar",), ORIGIN,
                                                side="attack"), catalog=staged, brief=brief)
    assert [r["stage"] for r in board.to_dict()["stages"]] == ["Assault", "Escort"]
    assert "stages:\n  Assault: " in board.rendered()
    flat = engine.board(synthetic_world, Draft("Salt Flats", ("Mortar",), ORIGIN),
                        catalog=staged, brief=brief)
    assert flat.stages == []
    off = engine.board(synthetic_world, Draft("Harbor Gate", ("Mortar",), ORIGIN, side="attack"),
                       catalog=staged, brief=dataclasses.replace(brief, walk_stages=False))
    assert off.stages == []


def test_the_swaps_between_stages_meet_their_own_role_first(synthetic_world):
    """A stage's swaps pair each hero that goes with an incoming hero of its
    own role wherever the six has one, before any leftover is matched across
    roles, as the board's swaps are paired."""
    heroes = {h.name: h for h in synthetic_world.heroes.values()}
    reference = [heroes[n] for n in ("Anvil", "Kite", "Rook", "Needle", "Balm", "Myrrh")]
    six = [heroes[n] for n in ("Kite", "Needle", "Flint", "Balm", "Myrrh", "Sorrel")]
    got = swaps.moved(reference, six)
    assert sorted(s["out"] for s in got) == ["Anvil", "Rook"]
    for s in got:
        out, into = heroes[s["out"]], heroes[s["in"]]
        same = [h for h in six if h.role == out.role and h not in reference]
        assert not same or into.role == out.role, s


def test_a_stage_no_six_can_hold_says_so_and_not_that_it_ran_out(synthetic_world):
    """A stage whose limits no six keeps reads that, not that the search ran
    out of its budget."""
    m = synthetic_world.resolve("Ember Ruins", (), (), ())[0]
    none = StageRules(on=[], off=[])
    stuck = plan.stage_blurb(m, "Forge", (0, 0), none, [], [], COST, outcome="infeasible")
    assert "No six keeps this stage's limits" in stuck and "budget" not in stuck
    assert "budget" in plan.stage_blurb(m, "Forge", (0, 0), none, [], [], COST,
                                        outcome="unsolved")
