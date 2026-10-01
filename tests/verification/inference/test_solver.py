"""The search on a board, held to a full enumeration: the best sixes of
every legal six, element for element, on both seats, around locked picks,
past bans, in the countered case and on a plateau where every six ties;
a full six's rank; shape limits, a charge for a rule broken that never
prunes, a bonus that reads a name refused by its expression, a need and
its budget, partners that only pay together, the scale
a ban leaves alone, the ranking order and its tie-breaks, the reference
sample of a small roster, and the budget a search refuses past. Every
board is the synthetic World's: no database."""

import copy
import dataclasses
import itertools
import os
import shutil

import pytest

from db import Refusal
from db.data.normalizer import name_key
from facts.draft import Draft, opposite
from facts.records import Synergy
from facts.team import team_metrics
from inference import catalog
from inference.base import OFF
from inference.scoring import Candidate, rank_key
from inference.shapes import legal_shapes
from tests.verification.inference import (
    ASSUMPTIONS_ONLY,
    DEFAULT,
    FIXTURE_PLAYBOOK,
    evaluated,
    heal_rate,
)

# the reference playbook's shape limit tightened to Role Queue's two-two-two
ROLE_QUEUE = (
    "---\nname: role queue\nkind: constraint\nrequire: team.tanks == 2 and team.damage == 2"
    " and team.supports == 2\n---\nx\n")
K = 6                   # the sixes a board's seat keeps: its best and BOARD_TOP alternatives
# a swap search's reference picks and its raw cost a pick dropped: the keep term
# the gate holds the bound to beside the plain objective
KEEP, KEEP_COST = ("Kite", "Needle", "Myrrh"), 0.4


def shape(six):
    """A six's (tanks, damage, supports)."""
    return tuple(sum(1 for h in six if h.role == r) for r in ("tank", "damage", "support"))


def legal_sixes(world, playbook, locked=(), banned=()):
    """Every six of the world's released heroes that holds the locked picks,
    fields no banned hero and takes a shape the playbook allows."""
    shapes = set(legal_shapes(playbook))
    taken = {h.id for h in (*locked, *banned)}
    free = [h for h in world.heroes.values() if h.released and h.id not in taken]
    sixes = ([*locked, *rest] for rest in itertools.combinations(free, 6 - len(locked)))
    return [six for six in sixes if shape(six) in shapes]


def enumerated(solver):
    """Every legal six of a solver's board that keeps the limits, scored by
    the solver's own objective and ranked: the answer the search must give,
    found without it."""
    sixes = legal_sixes(solver.world, solver.catalog, solver.locked, solver.banned_heroes)
    scored = [solver.score(solver.prepare(Candidate(six)), detail=False) for six in sixes]
    return sorted((c for c in scored if not c.violations), key=rank_key)


def verdicts(sixes):
    """Sixes as the comparison reads them: the score's float, the tie-break
    and the names."""
    return [(c.score, c.tiebreak, sorted(c.names)) for c in sixes]


def seated(world, draft, playbook, base, scale_of=None, keep=(), swap=0.0):
    """The Solver of a board's seat, on `scale_of`'s scale where given; with
    `keep`, the swap search's keep term: `swap` for each of those heroes a
    six holds."""
    from inference.solver import Solver
    m, red, locked, banned = world.resolve(draft.map_name, draft.red, draft.blue, draft.bans)
    solver = Solver(world, m, red=red, locked=locked, banned=banned, side=draft.side,
                    stage=draft.stage, catalog=playbook, base=base,
                    keep=frozenset(world.hero(name).id for name in keep), swap=swap)
    if scale_of is not None:
        solver.adopt_scale(scale_of)
    return solver


def widened(world):
    """The world with three stronger twins of each role's best hero: seven a
    role, 38,038 legal sixes under the open queue, room for the bound to
    prune."""
    world = copy.copy(world)
    world.heroes, world.by_key = dict(world.heroes), dict(world.by_key)
    next_id = max(world.heroes) + 1
    for role in ("tank", "damage", "support"):
        best = max((h for h in world.heroes.values() if h.role == role and h.released),
                   key=lambda h: h.win)
        for i in range(3):
            twin = dataclasses.replace(best, id=next_id, name="%s %d" % (best.name, i + 2),
                                       win=best.win + 1 + i)
            world.heroes[twin.id] = twin
            world.by_key[name_key(twin.name)] = twin.id
            next_id += 1
    return world


def paired(world, a, b):
    """A copy of the world whose one synergy pair is `a` and `b`."""
    out = copy.copy(world)
    pair = Synergy(1, "scratch")
    out.synergies = {frozenset((a.id, b.id)): pair}
    out.partners = {a.id: {b.id: pair}, b.id: {a.id: pair}}
    return out


@pytest.mark.parametrize(("base", "pair"), [(OFF, ("Anvil", "Tansy")),
                                            (DEFAULT, ("Anvil", "Balm"))],
                         ids=["base-off", "base-on"])
def test_the_search_reaches_the_enumerated_maximum(synthetic_world, catalog_copy, base, pair):
    """The regression gate on the search. On every board here - no red, red
    revealed, one lock, two locks, two bans, a pair that pays only together,
    each under a two-two-two role queue and under the open queue's shapes,
    and two on a widened roster of seven a role under the role queue - every
    legal six is enumerated and
    scored, and the search's best sixes are the enumeration's first, element
    for element: the score's float, the tie-break and the names. It holds
    with the default engine under the reference playbook and without it,
    and on some board the search scores fewer sixes than it enumerates, so
    the bound prunes. The pair is two heroes worth nothing apart, made the
    one synergy pair of a copy of the world, and the best six fields both.
    The swap search's keep term - a bonus for each of three reference
    heroes a six holds, some locked or banned - is held to the same
    enumeration on every board. A board this misses is a solver defect:
    fix the search, never swap the board out."""
    from inference import engine
    open_queue = catalog.load(catalog_copy)
    with open(os.path.join(catalog_copy, "role-queue.md"), "w", encoding="utf-8") as handle:
        handle.write(ROLE_QUEUE)
    role_queue = catalog.load(catalog_copy)
    assert any(s.weighs for s in role_queue)
    a, b = (synthetic_world.hero(name) for name in pair)
    together = paired(synthetic_world, a, b)
    boards = [
        (synthetic_world, Draft("Harbor Gate", side="attack")),
        (synthetic_world, Draft("Ember Ruins", ("Mortar", "Gale"))),
        (synthetic_world, Draft("Harbor Gate", ("Mortar", "Gale"), ("Balm",), side="defense")),
        (synthetic_world, Draft("Salt Flats", ("Anvil",), ("Kite", "Needle"))),
        (synthetic_world, Draft("Ember Ruins", ("Rook",), (), ("Myrrh", "Flint"))),
        (together, Draft("Salt Flats", ("Anvil",))),
        (widened(synthetic_world), Draft("Harbor Gate", ("Mortar", "Gale"), ("Kite",),
                                         side="attack")),
        (widened(synthetic_world), Draft("Ember Ruins", ("Rook",), ("Balm",), ("Needle",)))]
    missed, pruned = [], False
    for playbook in (role_queue, open_queue):
        for world, draft in boards:
            if len(world.heroes) > len(synthetic_world.heroes) and playbook is open_queue:
                continue                   # the widened roster's open field is slow to enumerate
            solver = seated(world, draft, playbook, base)
            got = solver.solve(top=K)
            full = enumerated(solver)
            assert full[0].score > full[-1].score, draft      # the playbook tells sixes apart
            if verdicts(got.ranked) != verdicts(full[:K]):
                missed.append("%s: %s, enumerated %s" % (draft, verdicts(got.ranked)[:2],
                                                         verdicts(full[:2])))
            kept = seated(world, draft, playbook, base, keep=KEEP, swap=KEEP_COST)
            ranked = kept.solve(top=K).ranked
            if verdicts(ranked) != verdicts(enumerated(kept)[:K]):
                missed.append("%s, keeping %s: %s" % (draft, KEEP, verdicts(ranked)[:2]))
            pruned = pruned or solver.leaves < len(full)
            assert solver.considered == len(legal_sixes(
                world, playbook, solver.locked, solver.banned_heroes))
            if world is together:
                assert {a.name, b.name} <= set(full[0].names)   # the pair pays, and is fielded
            top = engine.infer(world, draft, catalog=playbook, top=K - 1, base=base)
            assert [sorted(top.blue), *(sorted(alt["blue"]) for alt in top.alternatives)] == [
                sorted(c.names) for c in full[:K]], draft
    assert not missed, "the search misses the enumerated maximum:\n  " + "\n  ".join(missed)
    assert pruned


@pytest.mark.parametrize("base", [OFF, DEFAULT], ids=["base-off", "base-on"])
def test_every_seat_of_a_board_is_the_enumerated_maximum(synthetic_world, base):
    """A board's seats are each an exact search: blue's optimal against red's
    picks, red's against blue's on the other side, the fill around blue's
    picks on blue's scale, red's fill on red's, and the countered case -
    blue's best counter to red's optimal six, and blue's picks filled against
    it on that scale. Each is the enumeration's best six, and the board shows
    each seat's six and alternatives in the enumeration's order."""
    from inference import engine
    playbook = catalog.load(FIXTURE_PLAYBOOK)
    for draft in (Draft("Harbor Gate", ("Mortar", "Gale"), ("Balm", "Rook"), side="attack"),
                  Draft("Ember Ruins", ("Anvil",), ("Needle",), ("Myrrh",))):
        board = engine.board(synthetic_world, draft, catalog=playbook,
                             brief=engine.Brief(base=base, swaps=False))
        blue_seat = dataclasses.replace(draft, blue=())
        red_seat = Draft(draft.map_name, draft.blue, (), draft.bans, opposite(draft.side))
        blue = seated(synthetic_world, blue_seat, playbook, base)
        red = seated(synthetic_world, red_seat, playbook, base)
        blue.freeze_scale()
        red.freeze_scale()
        theirs = Draft(draft.map_name, draft.blue, draft.red, draft.bans, opposite(draft.side))
        against = dataclasses.replace(draft, red=tuple(board.red.blue), blue=())
        countered = seated(synthetic_world, against, playbook, base)
        countered.freeze_scale()
        seats = [(board.blue, blue), (board.red, red),
                 (board.fill, seated(synthetic_world, draft, playbook, base, blue)),
                 (board.countered, seated(synthetic_world, dataclasses.replace(
                     against, blue=draft.blue), playbook, base, countered))]
        for result, solver in seats:
            full = enumerated(solver)
            assert verdicts(solver.solve(top=K).ranked) == verdicts(full[:K]), draft
            shown = [sorted(result.blue), *(sorted(a["blue"]) for a in result.alternatives)]
            assert shown == [sorted(c.names) for c in full[:len(shown)]], draft
            assert abs(result.score - full[0].score) < 1e-12
        red_fill = seated(synthetic_world, theirs, playbook, base, red)
        assert verdicts(red_fill.solve(top=K).ranked) == verdicts(enumerated(red_fill)[:K])


@pytest.mark.parametrize("playbook", ["assumptions", "healing floor"])
def test_a_plateau_is_ranked_by_its_tie_break_and_then_its_names(
        synthetic_world, tmp_path, playbook):
    """With the default engine off, a playbook of assumptions scores every
    six 0, and the healing floor alone scores 0 every six that heals
    enough: the best sixes are the tie-break's and then the names', exactly
    as the enumeration ranks them, and the search proves it without scoring
    every six."""
    rules = ASSUMPTIONS_ONLY if playbook == "assumptions" else heal_rate(str(tmp_path))
    wide = widened(synthetic_world)
    for world, draft in ((synthetic_world, Draft("Harbor Gate", side="attack")),
                         (synthetic_world, Draft("Salt Flats", ("Kite",))),
                         (wide, Draft("Ember Ruins", ("Rook",), ("Balm",), ("Myrrh",)))):
        solver = seated(world, draft, rules, OFF)
        got = solver.solve(top=K)
        full = enumerated(solver)
        assert full[0].score == full[K].score == 0.0
        assert verdicts(got.ranked) == verdicts(full[:K]), draft
        assert solver.leaves < len(full)


def test_a_six_that_ties_the_optimal_ranks_where_the_tie_break_puts_it(synthetic_world):
    """On a plateau every six scores the same, and a six's rank is its
    place in the order the alternatives are listed in - the tie-break, then
    the names - never first for tying the optimal's score. Read off the
    search's top K, or counted by a search of its own past it."""
    from inference import solver as solver_module
    solver = seated(synthetic_world, Draft("Harbor Gate", side="attack"), ASSUMPTIONS_ONLY, OFF)
    solved = solver.solve(top=K)
    full = enumerated(solver)
    assert full[0].score == full[K + 5].score == 0.0
    for place in (0, 1, K - 1, K, K + 5):
        evaluation = solver_module.evaluate_comp(solved, full[place].heroes)
        assert evaluation.rank == place + 1 and not evaluation.outranked, place


def test_a_full_six_is_ranked_against_every_legal_six(synthetic_world, monkeypatch):
    """A full six's rank is its place in the enumeration's rank order, one
    more than the legal sixes that rank above it: read off the seat's
    search where the six reaches its top K, counted by a search of its own
    where it does not, and none past RANK_CAP, where the six reads as
    outranked."""
    from inference import solver as solver_module
    playbook = catalog.load(FIXTURE_PLAYBOOK)
    draft = Draft("Harbor Gate", ("Mortar", "Gale"), side="attack")
    blue = seated(synthetic_world, draft, playbook, DEFAULT)
    solved = blue.solve(top=K)
    full = enumerated(blue)
    for place in (0, 3, K + 4, 60):
        six = full[place]
        evaluation = solver_module.evaluate_comp(solved, six.heroes)
        above = sum(1 for c in full if rank_key(c) < rank_key(six))
        assert above == place
        assert evaluation.rank == 1 + above and not evaluation.outranked, place
        result = evaluated(synthetic_world, dataclasses.replace(
            draft, blue=tuple(six.names)), catalog=playbook)
        assert result.rank == 1 + above
    monkeypatch.setattr(solver_module, "RANK_CAP", 5)
    weak = full[len(full) // 2]
    evaluation = solver_module.evaluate_comp(solved, weak.heroes)
    assert evaluation.rank is None and evaluation.outranked
    result = evaluated(synthetic_world, dataclasses.replace(draft, blue=tuple(weak.names)),
                       catalog=playbook)
    assert result.rank is None and result.outranked
    assert "(outside the top " in result.rendered()


def test_a_search_past_its_budget_refuses_rather_than_guesses(synthetic_world, monkeypatch):
    """A search that has not proved its answer within its budget raises
    Unbounded, a refusal: the answer is exact or refused, never a guess."""
    from inference import solver as solver_module
    playbook = catalog.load(FIXTURE_PLAYBOOK)
    monkeypatch.setattr(solver_module, "SCORE_BUDGET", 3)
    solver = seated(synthetic_world, Draft("Harbor Gate", side="attack"), playbook, DEFAULT)
    with pytest.raises(solver_module.Unbounded):
        solver.solve(top=K)
    assert issubclass(solver_module.Unbounded, Refusal)
    monkeypatch.setattr(solver_module, "SCORE_BUDGET", 10_000)
    monkeypatch.setattr(solver_module, "NODE_BUDGET", 10)
    monkeypatch.setattr(solver_module, "CHECK_EVERY", 4)
    busy = seated(synthetic_world, Draft("Harbor Gate", side="attack"), playbook, DEFAULT)
    with pytest.raises(solver_module.Unbounded):
        busy.solve(top=K)


def test_shape_limits_bound_the_search_and_a_stricter_one_narrows_it(synthetic_world, tmp_path):
    from inference import engine
    world = synthetic_world
    fix = catalog.load(FIXTURE_PLAYBOOK)
    # two tanks is allowed under the two-tank limit; a third is not, and is the queue's
    r = engine.infer(world, Draft("Harbor Gate", ("Needle",), ("Anvil", "Kite")), catalog=fix,
                     base=DEFAULT)
    assert {"Anvil", "Kite"} <= set(r.blue)
    with pytest.raises(Refusal, match="the queue allows at most 2 tanks"):
        engine.infer(world, Draft("Harbor Gate", (), ("Anvil", "Kite", "Mortar")),
                     catalog=fix, base=DEFAULT)
    # a stricter authored limit narrows the search the same way
    for name in os.listdir(FIXTURE_PLAYBOOK):
        if name != "open-queue-tanks.md":
            shutil.copy(os.path.join(FIXTURE_PLAYBOOK, name), tmp_path / name)
    (tmp_path / "shape.md").write_text(ROLE_QUEUE, "utf-8")
    cat = catalog.load(str(tmp_path))
    r = engine.infer(world, Draft("Harbor Gate", ("Needle",), ("Balm",)), catalog=cat,
                     base=DEFAULT)
    roles = sorted(world.hero(n).role for n in r.blue)
    assert roles == ["damage", "damage", "support", "support", "tank", "tank"]


def test_a_shape_limit_on_a_dial_is_still_a_shape_limit(tmp_path):
    """A cap written on a dial - `team.supports <= params.MAX_SUPPORTS` -
    reads the six's shape and its own number: the shapes the roster enforces
    and the search enumerates leave out every six past the dial, and moving
    the dial moves the cap."""
    shutil.copytree(FIXTURE_PLAYBOOK, tmp_path, dirs_exist_ok=True)
    everything = legal_shapes(catalog.load(str(tmp_path)))
    for cap in (3, 2):
        (tmp_path / "support-cap.md").write_text(
            "---\nname: support cap\nkind: constraint\nrequire: team.supports <="
            " params.MAX_SUPPORTS\nparams:\n  MAX_SUPPORTS: %d\n---\nx\n" % cap, "utf-8")
        shapes = legal_shapes(catalog.load(str(tmp_path)))
        assert shapes == [s for s in everything if s.supports <= cap], cap


def test_a_charge_for_a_rule_broken_is_a_heuristic_and_never_prunes(synthetic_world):
    """The reference playbook's anti-air charges rather than forbids, so it is
    a scored heuristic, `when: <a flier> and not (<a hitscan answer>)`: against
    red's flier, a six with no hitscan stays a candidate and pays its 2.5."""
    from inference import scoring
    w = synthetic_world
    objective = scoring.Objective(w, w.map("Harbor Gate"), red=[w.hero("Gale")],
                                  catalog=catalog.load(FIXTURE_PLAYBOOK), base=DEFAULT)
    cand = scoring.Candidate(
        [w.hero(n) for n in ("Anvil", "Mortar", "Balm", "Myrrh", "Sorrel", "Tansy")])
    objective.score(objective.prepare(cand))
    assert cand.violations == []
    [term] = [c for c in cand.contributions if c["id"] == "anti-air"]
    assert (term["kind"], term["form"]) == ("heuristic", "scored") and "ok" not in term
    assert term["applies"] and term["penalty"] == 2.5 and term["weighted"] == -2.5


def test_a_bonus_that_reads_a_name_is_refused_naming_its_expression(synthetic_world, tmp_path):
    """A bonus or penalty is a number. One that reads a text metric passes
    the catalog, which checks only that its names are registered, and the
    score refuses it with an ExprError naming the expression."""
    from inference import scoring
    from inference.expr import ExprError
    (tmp_path / "lean.md").write_text(
        "---\nname: lean\nkind: heuristic\nbonus: team.style_lean\n---\nx\n", "utf-8")
    w = synthetic_world
    objective = scoring.Objective(w, w.map("Harbor Gate"), red=[],
                                  catalog=catalog.load(str(tmp_path)), base=OFF)
    cand = scoring.Candidate(
        [w.hero(n) for n in ("Anvil", "Mortar", "Balm", "Myrrh", "Sorrel", "Tansy")])
    with pytest.raises(ExprError, match=r"'team\.style_lean' - a bonus or penalty is a number"):
        objective.score(objective.prepare(cand))


def test_a_rule_guarded_on_the_six_itself_is_a_need_and_a_state_has_a_budget(
        synthetic_world, tmp_path):
    """"A solo healer needs an escape" must not pay a six for fielding one
    support: met in full it costs nothing, unmet it costs the weight, and the
    needs written on one guard cost NEED_BUDGET together at most. A guard on
    the board (red, the map) stays a reward."""
    from inference import scoring
    world = synthetic_world
    shutil.copy(os.path.join(FIXTURE_PLAYBOOK, "open-queue-tanks.md"), tmp_path)
    rule = ("---\nname: %s\nkind: heuristic\ndirection: maximize\nmetric: %s\nweight: 2\n"
            "when: %s\n---\nx\n")
    for i, metric in enumerate(("team.mobility_count", "team.cc_count", "team.armor_total")):
        (tmp_path / ("solo-%d.md" % i)).write_text(
            rule % ("Solo %d" % i, metric, "team.supports <= 1"), "utf-8")
    (tmp_path / "their-fliers.md").write_text(
        rule % ("Their fliers", "team.hitscan", "enemy.light_flyers >= 1"), "utf-8")
    scratch = catalog.load(str(tmp_path))
    # Gale flies for red; blue fields Balm as its one support
    solo = evaluated(world, Draft("Harbor Gate", ("Gale",),
                                  ("Anvil", "Mortar", "Rook", "Needle", "Flint", "Balm")),
                     catalog=scratch).to_dict()
    terms = {c["id"]: c for c in solo["contributions"]}
    needs = [terms["solo-%d" % i] for i in range(3)]
    assert all(c["applies"] and c["need"] and c["weighted"] <= 0 for c in needs)
    assert sum(c["weighted"] for c in needs) >= -scoring.NEED_BUDGET - 1e-9
    assert terms["their-fliers"]["need"] is False and terms["their-fliers"]["weighted"] >= 0
    paired = ("Anvil", "Mortar", "Rook", "Needle", "Balm", "Tansy")
    pair = evaluated(world, Draft("Harbor Gate", ("Gale",), paired),
                     catalog=scratch).to_dict()
    assert all(
        not c["applies"] and c["weighted"] == 0
        for c in pair["contributions"] if c["id"].startswith("solo-"))


def test_a_need_alone_on_its_guard_weighs_its_own_weight(synthetic_world, tmp_path):
    """The budget the needs on one guard share is NEED_BUDGET or their
    largest weight, whichever is more, so no slider is capped: a need alone
    on its guard weighs what its file or its slider says, past the budget
    too, and two needs on one guard cost the larger weight together."""
    from inference import scoring
    world = synthetic_world
    rule = ("---\nname: %s\nkind: heuristic\ndirection: maximize\nmetric: %s\nweight: %s\n"
            "when: team.supports <= 1\n---\nx\n")
    (tmp_path / "solo.md").write_text(rule % ("Solo", "team.mobility_count", 1), "utf-8")
    alone = catalog.load(str(tmp_path))
    m = world.map("Harbor Gate")

    def weights(playbook):
        objective = scoring.Objective(world, m, red=[], catalog=playbook, base=OFF)
        return {n.strategy.id: n.weight for n in objective.norms}
    assert weights(alone) == {"solo": 1.0}
    for slider in (2.0, 5.0, 10.0):
        assert weights(catalog.weighted(alone, {"solo": slider})) == {"solo": slider}
    (tmp_path / "solo-cc.md").write_text(rule % ("Solo cc", "team.cc_count", 1), "utf-8")
    both = catalog.weighted(catalog.load(str(tmp_path)), {"solo": 3.0})
    assert weights(both) == {"solo": 2.25, "solo-cc": 0.75}
    assert weights(catalog.weighted(both, {"solo": 0.5})) == {"solo": 0.5, "solo-cc": 1.0}


def test_partners_that_only_pay_together_are_brought_in_together(synthetic_world, tmp_path):
    """One slot at a time, a pair worth nothing apart is never met: each
    partner alone only costs. The playbook here pays one synergy pair, the
    two weakest heroes of their roles on a roster of seven a role, and the
    best six holds both, with the locked pick, the ban and the shape kept -
    the enumeration's own best six, which the bound reaches because a
    candidate's pairs count toward its branch before it is picked."""
    world = widened(synthetic_world)
    (tmp_path / "shape.md").write_text(ROLE_QUEUE, "utf-8")
    rule = "---\nname: %s\nkind: heuristic\ndirection: maximize\nmetric: %s\nweight: %s\n---\nx\n"
    (tmp_path / "winning.md").write_text(rule % ("Winning", "team.win_mean", 1), "utf-8")
    (tmp_path / "together.md").write_text(rule % ("Together", "team.synergy_edges", 0.5), "utf-8")
    scratch = catalog.load(str(tmp_path))
    draft = Draft(None, (), ("Anvil",), ("Needle",))
    weakest = {}
    for r in ("tank", "damage", "support"):
        rest = [h for h in world.heroes.values()
                if h.role == r and h.released and h.name not in ("Anvil", "Needle")]
        weakest[r] = sorted(rest, key=lambda h: (h.win, h.name))
    for a, b in ((weakest["support"][0], weakest["support"][1]),
                 (weakest["tank"][0], weakest["damage"][0])):
        lonely = seated(paired(world, a, a), draft, scratch, OFF)
        alone = lonely.solve(top=1).ranked[0]
        assert not {a.name, b.name} & set(alone.names)       # apart, neither is picked
        solver = seated(paired(world, a, b), draft, scratch, OFF)
        top = solver.hydrate(solver.solve(top=1).ranked[0])
        assert {a.name, b.name, "Anvil"} <= set(top.names) and "Needle" not in top.names
        assert sorted(h.role for h in top.heroes) == ["damage"] * 2 + ["support"] * 2 + ["tank"] * 2
        assert any(c["id"] == "together" and c["raw"] == 1 for c in top.contributions)
        assert verdicts([top]) == verdicts(enumerated(solver)[:1])


def test_a_ban_does_not_rescale_the_board(synthetic_world):
    """The reference sample fixes every heuristic's [lo, hi], so it must not
    depend on the bans: banning a hero on neither team would otherwise move the
    score of an unchanged six, and `the best six here` would stop being a
    function of the six. Bans screen the candidate field, not the scale. The
    reference playbook scores: under one that scores nothing every six reads
    0 and the check could not fail."""
    from inference import catalog as catalog_module
    from inference import scoring
    from inference import solver as solver_module
    world = synthetic_world
    catalog = catalog_module.load(FIXTURE_PLAYBOOK)
    assert any(s.weighs for s in catalog)
    red = ["Mortar", "Gale"]
    six = ["Anvil", "Kite", "Rook", "Needle", "Balm", "Tansy"]
    absent = [
        h.name for h in world.heroes.values()
        if h.released and h.name not in six and h.name not in red][:3]

    def score_under(bans):
        m, red_h, _, bans_h = world.resolve("Harbor Gate", red, [], bans)
        solver = solver_module.Solver(world, m, red=red_h, locked=[], banned=bans_h,
                                      side="attack", catalog=catalog, base=DEFAULT)
        solver.freeze_scale()
        cand = solver.prepare(scoring.Candidate([world.hero(n) for n in six]))
        return solver.score(cand, detail=False).score

    # the same six, the same number of bans, a different hero banned
    first = score_under([absent[0], absent[2]])
    second = score_under([absent[1], absent[2]])
    assert abs(first - second) < 1e-9, (first, second)


def test_the_order_of_a_six_does_not_decide_its_score_or_its_rank(synthetic_world):
    """A six is scored in one seat order, whatever order it arrives in, so
    its score is a function of its heroes down to the last bit; rank_key's
    third element breaks ties, so it too is a property of the hero set - in
    arrival order one set would key 720 ways."""
    from inference import scoring
    world = synthetic_world
    heroes = [world.hero(n) for n in ("Anvil", "Kite", "Rook", "Needle", "Balm", "Tansy")]
    objective = scoring.Objective(world, world.map("Harbor Gate"), red=[world.hero("Gale")],
                                  catalog=catalog.load(FIXTURE_PLAYBOOK), base=DEFAULT)
    scores = set()
    for order in itertools.permutations(heroes):
        scores.add(objective.score(objective.prepare(scoring.Candidate(order)), detail=False).score)
    assert len(scores) == 1
    one = scoring.Candidate(heroes)
    other = scoring.Candidate(list(reversed(heroes)))
    assert one.heroes == other.heroes
    one.score = other.score = 1.0
    one.tiebreak = other.tiebreak = 0.5
    assert rank_key(one) == rank_key(other)
    close = scoring.Candidate(list(reversed(heroes)))
    close.score, close.tiebreak = 1.0 + 1e-12, 0.4          # a tie at SCORE_PLACES
    assert rank_key(one) < rank_key(close)


def test_style_ties_break_by_name_so_hash_order_cannot_reach_the_answer(synthetic_world):
    """A set of style names iterates in an order that changes with the process's
    hash seed; the tie-breaks must not depend on it - two views of the same
    heroes whose style sets iterate in opposite orders agree on every metric,
    and the same board solves to the same six twice in a row. Flint carries
    two styles, so its set has two orders."""
    from inference import engine
    world = synthetic_world
    heroes = [world.hero(n) for n in ("Anvil", "Kite", "Flint", "Needle", "Balm", "Sorrel")]
    forward = team_metrics(world, heroes, world.map("Ember Ruins"), [])

    from facts import model

    class Reversed(model.Hero):                # the same hero, its styles iterated backwards
        def __init__(self, hero):
            self.__dict__ = dict(hero.__dict__)
            self.styles = sorted(hero.styles, reverse=True)   # the other iteration order
    backward = team_metrics(world, [Reversed(h) for h in heroes], world.map("Ember Ruins"), [])
    for key in ("style_top", "style_lean", "style_counts", "style_fit"):
        assert forward[key] == backward[key], key
    ember = world.map("Ember Ruins")
    derived = dict(ember.styles)
    ember.styles = {"poke": 1.0, "dive": 0.2, "brawl": 1.0}
    try:
        assert ember.style_top == "brawl" and ember.style_margin == 0
    finally:
        ember.styles = derived
    fix = catalog.load(FIXTURE_PLAYBOOK)
    draft = Draft("Harbor Gate", ("Mortar", "Gale"), ("Balm",))
    once = engine.infer(world, draft, catalog=fix, base=DEFAULT)
    twice = engine.infer(world, draft, catalog=fix, base=DEFAULT)
    assert once.blue == twice.blue and abs(once.score - twice.score) < 1e-12


def test_a_roster_with_fewer_legal_sixes_than_the_reference_is_sampled_whole(synthetic_world):
    """Twelve heroes, four a role, hold fewer distinct sixes than REFERENCE_SIZE
    asks for. The reference is then every legal six once, in the seeded order,
    where the draw used to spin forever looking for more."""
    from inference import scale, scoring
    playbook = catalog.load(FIXTURE_PLAYBOOK)
    legal = {frozenset(h.id for h in six) for six in legal_sixes(synthetic_world, playbook)}
    objective = scoring.Objective(synthetic_world, None, red=[], catalog=playbook, base=DEFAULT)
    drawn = scale.sample(objective)
    assert len(legal) < scale.REFERENCE_SIZE
    assert [c.key for c in drawn] == [c.key for c in scale.sample(objective)]
    assert sorted(sorted(c.key) for c in drawn) == sorted(sorted(six) for six in legal)


def test_the_floor_is_the_lowest_reference_six(synthetic_world):
    """A seat's floor, a share's 0, is the lowest score among the reference
    sixes its scale draws, and a fill that takes the seat's scale takes its
    floor too."""
    from inference import scale
    from inference import solver as solver_module
    world = synthetic_world
    m, red, locked, _ = world.resolve("Harbor Gate", ["Mortar", "Gale"], ["Balm"], [])
    playbook = catalog.load(FIXTURE_PLAYBOOK)
    solver = solver_module.Solver(world, m, red=red, locked=[], side="attack",
                                  catalog=playbook, base=DEFAULT)
    solver.freeze_scale()
    scores = [solver.score(c, detail=False).score for c in scale._prepared(solver)]
    assert solver.floor == min(scores) < max(scores)
    fill = solver_module.Solver(world, m, red=red, locked=locked, side="attack",
                                catalog=playbook, base=DEFAULT)
    fill.adopt_scale(solver)
    assert fill.floor == solver.floor and fill.scale == solver.scale


# a board that reads the terrain: a rule and a limit Forge's hazards turn on
HAZARD_RULES = {
    "hazard-cc": "---\nname: Hazards reward crowd control\nkind: heuristic\n"
                 "metric: team.cc_count\ndirection: maximize\nweight: 1\n"
                 "when: map.hazards >= 1.5\n---\nPush them off.\n",
    "hazard-needs-cc": "---\nname: Hazards need crowd control\nkind: constraint\n"
                       "require: team.cc_count >= 1 or map.hazards < 1.5\n---\nAlways.\n"}


def hazard_playbook(world, directory):
    """The reference playbook's assumptions and HAZARD_RULES, and Ember
    Ruins' Forge stage whose text raises its hazards past the map's."""
    for sid, text in HAZARD_RULES.items():
        with open(os.path.join(directory, "%s.md" % sid), "w", encoding="utf-8") as handle:
            handle.write(text)
    world.map("Ember Ruins").stage_z["Forge"]["hazards"] = 2.5
    return [*ASSUMPTIONS_ONLY, *catalog.load(str(directory))]


def test_every_stage_of_a_map_shares_one_scale_and_reads_its_own_floor(
        synthetic_world, tmp_path):
    """The scale is measured on the whole map, each heuristic read wherever
    the board settles its gate: a stage that turns a rule on and a limit
    that reads the terrain move no low or high. The floor is the board's own -
    the lowest reference six under its stage's gates and limits - so a
    stage that reads as the map floors where the map does, off the same
    measured sixes. Each stage is searched exactly: its best sixes are the
    enumeration's."""
    from inference import scale
    from inference import solver as solver_module
    world = synthetic_world
    playbook = hazard_playbook(world, tmp_path)
    m = world.map("Ember Ruins")
    solvers = {
        stage: solver_module.Solver(world, m, red=[], locked=[], stage=stage, catalog=playbook,
                                    base=DEFAULT)
        for stage in ("", "Courtyard", "Forge")}
    for solver in solvers.values():
        solver.freeze_scale()
    assert [solvers[s].gates["hazard-cc"] for s in solvers] == [False, False, True]
    assert [solvers[s].reads_the_stage() for s in solvers] == [False, False, True]
    assert solvers[""].scale == solvers["Courtyard"].scale == solvers["Forge"].scale
    assert "hazard-cc" in solvers[""].scale
    for solver in solvers.values():
        scores = [solver.score(c, detail=False).score for c in scale._prepared(solver)]
        assert solver.floor == min(scores)
        applies = {c.raw[0] is not None for c in scale._prepared(solver)}
        assert applies == {solver.stage == "Forge"}
    assert solvers["Courtyard"].floor == solvers[""].floor != solvers["Forge"].floor
    for solver in solvers.values():
        assert verdicts(solver.solve(top=6).ranked) == verdicts(enumerated(solver)[:6])
    assert verdicts(solvers["Forge"].solve(top=1).ranked) != verdicts(
        solvers[""].solve(top=1).ranked)
