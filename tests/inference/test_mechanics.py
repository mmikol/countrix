"""The objective and the search as mechanisms, before any heuristic ships:
the properties an argmax over a sum of terms has to hold whatever the
terms say. Each is checked on the synthetic World, whose four heroes a
role let a pool of six hold the whole roster, so infer there is an exact
argmax, and a pool of two leaves the search to reach the rest, which a
full enumeration then checks. The playbook is the reference, the shipped
healing floor on top of it, or one rule written here; the default engine
is on unless a test says otherwise. No database.

    weight response     a weight of 0 is the objective without the rule; the
                        optimum's metric moves toward a maximise rule and away
                        for a minimise one as the weight grows, never back
    limits              a hard limit's optimum meets it and is the best six
                        that does; a soft limit with no penalty prunes nothing
    needs and guards    a need never pays; a guard that fails costs and pays
                        nothing, and a rule the board's guard turns off leaves
                        the optimum where it was
    the breakdown       every six's contributions sum to its score
    order               a six scores the same in any seat order, and a draft's
                        picks and bans in any order solve to the same six
    symmetry            each seat of a board is infer on that seat's draft,
                        its score the solver's for that six, its fill infer
                        around the locks, its current comp evaluate's
    scale               scaling every weight by ten moves no six a search
                        visits, the answer and its alternatives included
    the search          at pool two, under open queue, with the default engine
                        and the healing floor, infer returns what a full
                        enumeration finds on every board
"""

import copy
import dataclasses
import itertools
import os
import shutil

import pytest

from facts.draft import Draft, board_side, opposite
from inference import catalog, engine, scale, scoring
from inference import solver as solver_module
from inference.base import DEFAULT, OFF, BaseWeights
from inference.shapes import legal_shapes
from tests.inference import FIXTURE_PLAYBOOK, heal_rate

# the boards the search is checked on: no red, red revealed, a lock, two locks
# and a red pick, and two bans, on each synthetic map and both sides
BOARDS = (
    Draft("Harbor Gate", side="attack"),
    Draft("Ember Ruins", ("Mortar", "Gale")),
    Draft("Harbor Gate", ("Mortar", "Gale"), ("Balm",), side="defense"),
    Draft("Salt Flats", ("Anvil",), ("Kite", "Needle")),
    Draft("Ember Ruins", ("Rook",), (), ("Myrrh", "Flint")))
SIX = ("Anvil", "Kite", "Rook", "Needle", "Balm", "Tansy")
RULE = "---\nname: %s\nkind: %s\n%s---\nx\n"
# a need on the six's own state, and a rule no board with a map turns on
SOLO = "direction: maximize\nmetric: team.mobility_count\nweight: 3\nwhen: team.supports <= 1\n"
OFF_BOARD = "direction: maximize\nmetric: team.dps_floor\nweight: 10\nwhen: map.known == 0\n"


def playbook(directory, *, reference=True, heal=True, rules=()):
    """A playbook written to `directory`: the reference's files, the shipped
    healing floor, and each (id, kind, frontmatter lines) rule, loaded."""
    os.makedirs(directory, exist_ok=True)
    if reference:
        shutil.copytree(FIXTURE_PLAYBOOK, directory, dirs_exist_ok=True)
    for rid, kind, lines in rules:
        with open(os.path.join(directory, "%s.md" % rid), "w", encoding="utf-8") as handle:
            handle.write(RULE % (rid, kind, lines))
    return heal_rate(directory) if heal else catalog.load(directory)


def shape(six):
    """A six's (tanks, damage, supports)."""
    return tuple(sum(1 for h in six if h.role == r) for r in ("tank", "damage", "support"))


def enumerated(world, rules, draft, base, pool_size=2):
    """Every legal six of the board scored on the solver's own scale, the
    feasible ones in rank order, and that solver."""
    m, red, locked, banned = world.resolve(draft.map_name, draft.red, draft.blue, draft.bans)
    solver = solver_module.Solver(world, m, red=red, locked=locked, banned=banned,
                                  side=board_side(m, draft.side), catalog=rules, base=base,
                                  pool_size=pool_size)
    solver.freeze_bounds()
    shapes = set(legal_shapes(rules))
    taken = {h.id for h in (*locked, *banned)}
    free = [h for h in world.heroes.values() if h.released and h.id not in taken]
    sixes = ([*locked, *rest] for rest in itertools.combinations(free, 6 - len(locked)))
    scored = [
        solver.score(solver.prepare(scoring.Candidate(six)), detail=False)
        for six in sixes if shape(six) in shapes]
    return sorted((c for c in scored if not c.violations), key=solver._rank_key), solver


def metric_of(world, result, key):
    """A result's six's value of one team metric, as the objective reads it."""
    m = world.map(result.map_name) if result.map_name else None
    objective = scoring.Objective(world, m, red=[world.hero(n) for n in result.red],
                                  catalog=[], base=OFF)
    cand = objective.prepare(scoring.Candidate([world.hero(n) for n in result.blue]))
    return cand.ns["team"][key]


# --- the weight response -------------------------------------------------------

def test_a_rule_at_weight_zero_is_the_objective_without_it(synthetic_world, tmp_path):
    """A heuristic weighed 0 adds 0 to every six, so the optimum, its score
    and its alternatives are those of the playbook without it."""
    without = playbook(str(tmp_path / "without"))
    zero = playbook(str(tmp_path / "zero"), rules=[
        ("dps", "heuristic", "direction: maximize\nmetric: team.dps_floor\nweight: 0\n")])
    for draft in BOARDS:
        a = engine.infer(synthetic_world, draft, catalog=without, top=5)
        b = engine.infer(synthetic_world, draft, catalog=zero, top=5)
        assert (a.blue, a.score) == (b.blue, b.score), draft
        assert [x["blue"] for x in a.alternatives] == [x["blue"] for x in b.alternatives]


@pytest.mark.parametrize("direction", ["maximize", "minimize"])
@pytest.mark.parametrize("key", ["dps_floor", "hps_floor", "supports"])
def test_the_optimum_moves_with_a_rules_weight_and_never_back(
        synthetic_world, tmp_path, direction, key):
    """As a heuristic's weight grows from 0 to 10, the optimum's metric moves
    toward a maximise rule's end, and toward the low end for minimise, one
    weight at a time and never back: at w2 > w1 the optimum of each is at
    least as good on the metric, since each beats the other under its own
    weight. Pool six holds the synthetic roster, so each is the exact argmax.
    By 10 it has moved, off the base's own six."""
    seen = []
    for weight in (0, 0.5, 1, 2, 4, 10):
        folder = tmp_path / ("w%s" % weight)
        line = "direction: %s\nmetric: team.%s\nweight: %s\n" % (direction, key, weight)
        rules = playbook(str(folder), reference=False, rules=[("rule", "heuristic", line)])
        result = engine.infer(synthetic_world, Draft("Harbor Gate", side="attack"),
                              catalog=rules, top=1)
        seen.append(metric_of(synthetic_world, result, key))
    better = seen if direction == "maximize" else [-v for v in seen]
    assert better == sorted(better), seen
    assert better[-1] > better[0], seen


# --- limits ----------------------------------------------------------------------

@pytest.mark.parametrize("base", [OFF, DEFAULT], ids=["base-off", "base-on"])
def test_a_hard_limits_optimum_meets_it_and_is_the_best_six_that_does(
        synthetic_world, tmp_path, base):
    """Under a limit on the six's own state the search returns the enumerated
    best of the sixes that meet it, at pool two, where the pools alone seat
    few of them."""
    rules = playbook(str(tmp_path), rules=[
        ("three-supports", "constraint", "require: team.supports >= 3\n")])
    for draft in (BOARDS[0], BOARDS[1], BOARDS[3]):
        feasible, _ = enumerated(synthetic_world, rules, draft, base)
        got = engine.infer(synthetic_world, draft, catalog=rules, pool_size=2, top=1, base=base)
        assert got.violations == [] and shape([synthetic_world.hero(n) for n in got.blue])[2] >= 3
        assert sorted(got.blue) == sorted(feasible[0].names), draft
        assert got.score == pytest.approx(feasible[0].score, abs=1e-9)


def test_a_soft_limit_that_charges_nothing_prunes_nothing(synthetic_world, tmp_path):
    """A soft limit only charges: at penalty 0 every board solves as it does
    without the limit, the six and its score alike."""
    without = playbook(str(tmp_path / "without"))
    free = playbook(str(tmp_path / "free"), rules=[
        ("free", "constraint", "require: team.supports >= 3\nsoft: true\npenalty: 0\n")])
    for draft in BOARDS:
        a = engine.infer(synthetic_world, draft, catalog=without, top=1)
        b = engine.infer(synthetic_world, draft, catalog=free, top=1)
        assert (a.blue, a.score) == (b.blue, b.score), draft


# --- needs and guards ----------------------------------------------------------------

def test_a_need_never_pays_and_a_failed_guard_neither_costs_nor_pays(
        synthetic_world, tmp_path):
    """Across the reference sample, a need adds weight x (norm - 1), at most
    0, where its guard holds, and nothing where it fails; a rule guarded on
    the board that the board turns off adds nothing to any six and leaves
    the optimum where it was."""
    rules = playbook(str(tmp_path / "rules"), rules=[
        ("solo", "heuristic", SOLO),
        ("off", "heuristic", OFF_BOARD)])
    w = synthetic_world
    objective = scoring.Objective(w, w.map("Harbor Gate"), red=[w.hero("Gale")], side="attack",
                                  catalog=rules, base=DEFAULT)
    objective.adopt_bounds(scale.reference_bounds(objective))
    held = 0
    for cand in scale.sample(objective)[:300]:
        objective.score(objective.prepare(cand))
        terms = {c["id"]: c for c in cand.contributions}
        solo, off = terms["solo"], terms["off"]
        assert solo["weighted"] <= 0 and off["weighted"] == 0 and not off["applies"]
        held += solo["applies"]
        assert solo["applies"] == (shape(cand.heroes)[2] <= 1)
        if not solo["applies"]:
            assert solo["weighted"] == 0
    assert held                                      # the sample meets the guard somewhere
    without = playbook(str(tmp_path / "without"))
    only_off = playbook(str(tmp_path / "only-off"), rules=[
        ("off", "heuristic", OFF_BOARD)])
    for draft in BOARDS:
        a = engine.infer(w, draft, catalog=without, top=1)
        b = engine.infer(w, draft, catalog=only_off, top=1)
        assert (a.blue, a.score) == (b.blue, b.score), draft


# --- the breakdown and the order --------------------------------------------------------

def test_every_sixs_breakdown_sums_to_its_score(synthetic_world, tmp_path):
    """The contributions are the score, term by term: the default engine's
    three, the healing floor, and every form of the reference playbook, on
    each sampled six of three boards."""
    rules = playbook(str(tmp_path))
    w = synthetic_world
    for draft in BOARDS[:3]:
        m, red, _, banned = w.resolve(draft.map_name, draft.red, (), draft.bans)
        solver = solver_module.Solver(w, m, red=red, locked=[], banned=banned, side=draft.side,
                                      catalog=rules, base=DEFAULT)
        solver.freeze_bounds()
        for cand in scale.sample(solver)[:200]:
            solver.score(solver.prepare(cand))
            assert sum(c["weighted"] for c in cand.contributions) == pytest.approx(
                cand.score, abs=1e-9), (draft, cand.names)
            assert {c["id"] for c in cand.contributions} >= {"heal-rate", "base.rates"}


def test_a_six_scores_the_same_in_any_seat_order_and_a_draft_in_any_order(
        synthetic_world, tmp_path):
    """Seat order is a construction artifact: every one of a six's orders
    scores the same to the last bit, and a draft's red picks, locks and
    bans given in another order solve to the same six and score."""
    rules = playbook(str(tmp_path))
    w = synthetic_world
    m, red, _, _ = w.resolve("Harbor Gate", ("Mortar", "Gale"), (), ())
    solver = solver_module.Solver(w, m, red=red, locked=[], side="defense", catalog=rules,
                                  base=DEFAULT)
    solver.freeze_bounds()
    six = [w.hero(n) for n in SIX]
    orders = itertools.islice(itertools.permutations(six), 0, 720, 37)
    scores = {
        solver.score(solver.prepare(scoring.Candidate(order)), detail=False).score
        for order in orders}
    assert len(scores) == 1
    for draft in BOARDS:
        flipped = Draft(draft.map_name, tuple(reversed(draft.red)), tuple(reversed(draft.blue)),
                        tuple(reversed(draft.bans)), side=draft.side)
        a = engine.infer(w, draft, catalog=rules, top=1)
        b = engine.infer(w, flipped, catalog=rules, top=1)
        assert (sorted(a.blue), a.score) == (sorted(b.blue), b.score), draft


# --- symmetry: the board is infer, seat by seat -------------------------------------------

@pytest.mark.parametrize("draft", [
    Draft("Harbor Gate", side="attack"),
    Draft("Harbor Gate", (), ("Balm", "Anvil"), side="attack"),
    Draft("Ember Ruins", ("Mortar", "Gale"), ("Balm",)),
    Draft("Salt Flats", ("Anvil",), ("Kite", "Rook", "Needle", "Balm", "Tansy", "Mortar"))],
    ids=["empty", "blue-locks", "both", "full-six"])
def test_each_seat_of_a_board_is_infer_on_that_seats_draft(synthetic_world, tmp_path, draft):
    """blue is infer on the draft without blue's picks, red infer on the
    mirror - blue's picks as red's red, the other side - the fill infer
    around blue's locks, and a full six evaluate's; each seat's score is
    what a fresh solver scores that six. Under the healing floor, whose
    shortfall reads the other side, a seat reading an unrevealed side
    differently from infer shows here."""
    rules = playbook(str(tmp_path))
    w = synthetic_world
    b = engine.board(w, draft, catalog=rules, brief=engine.Brief(countered=False))
    blue = engine.infer(w, dataclasses.replace(draft, blue=()), catalog=rules,
                        top=engine.BOARD_TOP)
    assert (b.blue.blue, b.blue.red) == (blue.blue, blue.red)
    assert b.blue.score == pytest.approx(blue.score, abs=1e-9)
    assert [a["blue"] for a in b.blue.alternatives] == [a["blue"] for a in blue.alternatives]
    mirror = Draft(draft.map_name, draft.blue, (), draft.bans, side=opposite(draft.side))
    red = engine.infer(w, mirror, catalog=rules, top=engine.BOARD_TOP)
    assert b.red.blue == red.blue and b.red.score == pytest.approx(red.score, abs=1e-9)
    if 0 < len(draft.blue) < 6:
        fill = engine.infer(w, draft, catalog=rules, top=engine.BOARD_TOP)
        assert b.fill.blue == fill.blue and b.fill.score == pytest.approx(fill.score, abs=1e-9)
    if len(draft.blue) == 6:
        evaluated = engine.evaluate(w, draft, catalog=rules)
        assert b.current.score == pytest.approx(evaluated.score, abs=1e-9)
        assert b.current.rank == evaluated.rank
    m, red_h, _, banned = w.resolve(draft.map_name, draft.red, (), draft.bans)
    fresh = solver_module.Solver(w, m, red=red_h, locked=[], banned=banned,
                                 side=board_side(m, draft.side), catalog=rules, base=DEFAULT)
    fresh.freeze_bounds()
    six = fresh.score(fresh.prepare(scoring.Candidate([w.hero(n) for n in b.blue.blue])))
    assert six.score == pytest.approx(b.blue.score, abs=1e-9)
    assert sum(c["weighted"] for c in b.blue.contributions) == pytest.approx(b.blue.score,
                                                                             abs=1e-9)


# --- the scale ---------------------------------------------------------------------------

def test_scaling_every_weight_by_ten_moves_no_six_the_search_visits(synthetic_world, tmp_path):
    """Nothing the search decides reads a score in absolute points: with the
    default engine's weights, the heuristic's and the healing floor's all
    ten times over, infer at pool two returns the same six and the same
    alternatives in the same order on every board with no lock, where no
    partner bonus ranks a pool."""
    rules = playbook(str(tmp_path), rules=[
        ("dps", "heuristic", "direction: maximize\nmetric: team.dps_floor\nweight: 1\n")])
    tenfold = []
    for h in rules:
        h = copy.copy(h)
        h.weight *= 10
        tenfold.append(h)
    heavy = BaseWeights(rate=DEFAULT.rate * 10, synergy=DEFAULT.synergy * 10,
                        counter=DEFAULT.counter * 10)
    for draft in (d for d in BOARDS if not d.blue):
        a = engine.infer(synthetic_world, draft, catalog=rules, pool_size=2, top=5)
        b = engine.infer(synthetic_world, draft, catalog=tenfold, pool_size=2, top=5,
                         base=heavy)
        assert a.blue == b.blue and b.score == pytest.approx(10 * a.score), draft
        assert [x["blue"] for x in a.alternatives] == [x["blue"] for x in b.alternatives]


# --- the search against a full enumeration ---------------------------------------------------

@pytest.mark.parametrize("base", [OFF, DEFAULT], ids=["base-off", "base-on"])
def test_under_open_queue_and_the_healing_floor_the_search_reaches_the_enumerated_maximum(
        synthetic_world, tmp_path, base):
    """The regression gate's twin under open queue: the reference playbook,
    whose only shape limit is two tanks, and the shipped healing floor on
    top, each role's pool cut to two. Every legal six is enumerated and
    scored, and infer returns the best, tie-break included. The pools alone
    seat no shape with three of a role, so a shape that needs more of a role
    than the pool holds has to take the role's next heroes. A board this
    misses is a solver defect."""
    rules = playbook(str(tmp_path))
    missed = []
    wide = 0
    for draft in BOARDS:
        feasible, _ = enumerated(synthetic_world, rules, draft, base)
        best = feasible[0]
        assert best.score > feasible[-1].score, draft
        wide += max(shape(best.heroes)) >= 3
        got = engine.infer(synthetic_world, draft, catalog=rules, pool_size=2, top=1, base=base)
        if sorted(got.blue) != sorted(best.names) or abs(got.score - best.score) > 1e-9:
            missed.append("%s: %s, enumerated %s" % (draft, sorted(got.blue), sorted(best.names)))
    assert not missed, "the search misses the enumerated maximum:\n  " + "\n  ".join(missed)
    assert wide                       # some board's best holds three of a role
