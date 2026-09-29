"""The engine verified in stages, before any strategy is trusted to it: the
null objective, then the meta alone, then dummy heuristics, each held to a
full enumeration of the synthetic World's legal sixes.

    the null objective   the meta at 0 and a playbook that scores nothing:
                         the legal space is the analytic count, every six
                         in it ties, the board says so, and the tie-break's
                         draw - blind to the rates and the names - picks
                         each hero of a role about as often as any other
    the meta alone       the default engine and no scoring rule: the search
                         is the enumeration's argmax, scaling the meta moves
                         no six, and a hero whose rate rises never leaves
                         the optimal six once it is in it
    dummy heuristics     scratch rules on a metric and on an expression:
                         the search is the enumeration's argmax with the
                         meta on and off, and a rule's weight raised never
                         lowers what the optimal six reads on its metric

No database: CI runs every stage."""

import copy
import dataclasses
import math
import os

import pytest

from facts.draft import Draft
from facts.model import ROLES
from inference import catalog, engine, scoring
from inference.base import OFF
from inference.shapes import legal_shapes
from inference.solver import RANK_CAP, Solver
from tests.inference import ASSUMPTIONS_ONLY, DEFAULT
from tests.inference.test_solver import enumerated, seated, verdicts, widened

K = 6                   # the sixes a board's seat keeps: its best and BOARD_TOP alternatives
BOARDS = (
    Draft("Harbor Gate", side="attack"),
    Draft("Ember Ruins", ("Mortar", "Gale")),
    Draft("Salt Flats", ("Anvil",), ("Kite",), ("Myrrh",)),
    Draft("Harbor Gate", ("Mortar", "Gale", "Needle"), ("Balm", "Rook"), side="defense"))


def analytic(world, playbook, locked=(), banned=()):
    """The legal sixes counted without listing one: over each legal shape,
    the product of each role's choices among its released, unbanned,
    unlocked heroes."""
    taken = {h.id for h in (*locked, *banned)}
    free = {r: sum(1 for h in world.heroes.values()
                   if h.role == r and h.released and h.id not in taken) for r in ROLES}
    held = {r: sum(1 for h in locked if h.role == r) for r in ROLES}
    def ways(shape):
        return math.prod(math.comb(free[r], shape[i] - held[r]) if shape[i] >= held[r] else 0
                         for i, r in enumerate(ROLES))
    return sum(ways(shape) for shape in legal_shapes(playbook))


def playbook(directory, rules):
    """The reference playbook's assumptions and these scratch rules, each a
    file's text by id, loaded from `directory`."""
    for sid, text in rules.items():
        with open(os.path.join(directory, "%s.md" % sid), "w", encoding="utf-8") as handle:
            handle.write(text)
    return [*ASSUMPTIONS_ONLY, *catalog.load(directory)]


def heuristic(metric, direction, weight, when=None):
    """A scratch heuristic on a metric, as a playbook file's text."""
    guard = "when: %s\n" % when if when else ""
    return ("---\nname: dummy %s\nkind: heuristic\nmetric: %s\ndirection: %s\nweight: %s\n%s"
            "---\nA dummy rule.\n" % (metric, metric, direction, weight, guard))


# --- the null objective -------------------------------------------------------------


@pytest.mark.parametrize("draft", BOARDS, ids=["open", "red", "locked-banned", "three-red"])
def test_with_nothing_scoring_every_legal_six_ties(synthetic_world, draft):
    """With the meta at 0 and a playbook that scores nothing, the search
    covers the analytic count of legal sixes, every one of them scores 0,
    and its best sixes are the enumeration's, element for element: on a
    plateau the draws alone order them."""
    solver = seated(synthetic_world, draft, ASSUMPTIONS_ONLY, OFF)
    solved = solver.solve(top=K)
    everything = enumerated(solver)
    _, _, locked, banned = synthetic_world.resolve(draft.map_name, draft.red, draft.blue,
                                                   draft.bans)
    assert solver.considered == len(everything) == analytic(synthetic_world, ASSUMPTIONS_ONLY,
                                                            locked, banned)
    assert {c.score for c in everything} == {0.0}
    assert verdicts(solved.ranked) == verdicts(everything[:K])


def test_the_board_says_how_many_sixes_tie(synthetic_world):
    """The optimal six under the null objective reports its tie: at least
    RANK_CAP on an open board, whose legal space is larger, and the exact
    count where fewer sixes are legal; the words say none of them is
    better. A scoring board reports none."""
    open_board = engine.infer(synthetic_world, Draft("Harbor Gate"), catalog=ASSUMPTIONS_ONLY,
                              base=OFF)
    assert tuple(open_board.tied) == (RANK_CAP, True)
    assert "one of at least %d sixes tied" % RANK_CAP in open_board.to_dict()["tie"]
    assert "none of them is better" in open_board.rendered()
    narrow = Draft("Ember Ruins", (), ("Mortar", "Gale", "Needle"), ("Balm", "Kite"))
    few = engine.infer(synthetic_world, narrow, catalog=ASSUMPTIONS_ONLY, base=OFF)
    solver = seated(synthetic_world, narrow, ASSUMPTIONS_ONLY, OFF)
    assert tuple(few.tied) == (len(enumerated(solver)), False) and few.tied.sixes > 1
    scoring_board = engine.infer(synthetic_world, Draft("Harbor Gate"),
                                 catalog=ASSUMPTIONS_ONLY, base=DEFAULT)
    assert tuple(scoring_board.tied) == (1, False) and scoring_board.to_dict()["tie"] is None


def test_the_tie_break_reads_no_rate_and_no_name(synthetic_world):
    """The null optimum is the legal six whose draws sum highest, and a
    world whose rates are shuffled among the heroes and whose names are
    changed gives the same six by id: the tie leaks nothing of the meta."""
    draft = Draft("Harbor Gate", side="attack")
    solver = seated(synthetic_world, draft, ASSUMPTIONS_ONLY, OFF)
    best = solver.solve(top=1).ranked[0]
    by_draws = max(enumerated(solver), key=lambda c: c.tiebreak)
    assert best.key == by_draws.key
    other = copy.copy(synthetic_world)
    heroes = sorted(synthetic_world.heroes.values(), key=lambda h: h.id)
    rolled = heroes[1:] + heroes[:1]                   # each hero takes the next one's rates
    other.heroes = {h.id: dataclasses.replace(
        h, name="Hero %d" % h.id, win=r.win, pick=r.pick, map_rates=dict(r.map_rates))
        for h, r in zip(heroes, rolled, strict=True)}
    moved = Solver(other, solver.m, red=[], locked=[], side=draft.side,
                   catalog=ASSUMPTIONS_ONLY, base=OFF).solve(top=1).ranked[0]
    assert moved.key == best.key


def test_the_draw_gives_every_hero_of_a_role_the_same_chance(synthetic_world, monkeypatch):
    """Over 600 boards' seeds, the null optimum seats each hero of a role
    about as often as any other - within a quarter of the role's mean - and
    seats every released hero; one board's seed gives one six every time."""
    counts = {h.id: 0 for h in synthetic_world.heroes.values() if h.released}
    seeds = iter(range(10 ** 6))
    monkeypatch.setattr(scoring, "board_seed", lambda m, side: "board %d" % next(seeds))
    m = synthetic_world.resolve("Harbor Gate", (), (), ())[0]
    for _ in range(600):
        six = Solver(synthetic_world, m, red=[], locked=[], catalog=ASSUMPTIONS_ONLY,
                     base=OFF).solve(top=1).ranked[0]
        for h in six.heroes:
            counts[h.id] += 1
    assert all(counts.values())
    for role in ROLES:
        seen = [n for i, n in counts.items() if synthetic_world.heroes[i].role == role]
        mean = sum(seen) / len(seen)
        assert all(abs(n - mean) <= mean / 4 for n in seen), (role, seen)
    monkeypatch.undo()
    twice = [Solver(synthetic_world, m, red=[], locked=[], catalog=ASSUMPTIONS_ONLY,
                    base=OFF).solve(top=1).ranked[0].key for _ in range(2)]
    assert twice[0] == twice[1]


# --- the meta alone -------------------------------------------------------------


@pytest.mark.parametrize("draft", BOARDS, ids=["open", "red", "locked-banned", "three-red"])
def test_the_meta_alone_is_the_enumerations_argmax(synthetic_world, draft):
    """With the default engine on and no scoring rule, the search's best
    sixes are the enumeration's, element for element, and the optimal six
    scores above the plateau the null objective left: the meta decides."""
    solver = seated(synthetic_world, draft, ASSUMPTIONS_ONLY, DEFAULT)
    everything = enumerated(solver)
    assert verdicts(solver.solve(top=K).ranked) == verdicts(everything[:K])
    assert everything[0].score > everything[-1].score


def test_scaling_the_meta_alone_moves_no_six(synthetic_world):
    """Under a playbook that scores nothing, the meta multiplies every
    six's score alike, so the optimal six and its order hold at every meta
    above 0."""
    draft = Draft("Ember Ruins", ("Mortar", "Gale"))
    sixes = {meta: [c.key for c in seated(
        synthetic_world, draft, ASSUMPTIONS_ONLY,
        dataclasses.replace(DEFAULT, meta=meta)).solve(top=K).ranked]
        for meta in (0.25, 0.5, 1.0, 2.0, 4.0, 10.0)}
    assert len({tuple(v) for v in sixes.values()}) == 1


def test_a_hero_whose_rate_rises_joins_the_optimal_six_and_stays(synthetic_world):
    """Raising a benched hero's win rate on the map step by step, the
    optimal six's score never falls, the hero joins the six at some step,
    and never leaves it at a later one: the search leans toward the meta."""
    draft = Draft("Harbor Gate", side="attack")
    first = seated(synthetic_world, draft, ASSUMPTIONS_ONLY, DEFAULT).solve(top=1).ranked[0]
    benched = next(h for h in sorted(synthetic_world.heroes.values(), key=lambda h: h.id)
                   if h.released and h.id not in first.key)
    m = synthetic_world.resolve(draft.map_name, (), (), ())[0]
    seated_at, scores = [], []
    for lift in range(0, 41, 2):
        world = copy.copy(synthetic_world)
        world.heroes = dict(world.heroes)
        rates = dict(benched.map_rates)
        row = rates.get(m.id)
        if row is not None:
            rates[m.id] = row._replace(win=row.win + lift)
        world.heroes[benched.id] = dataclasses.replace(benched, win=benched.win + lift,
                                                       map_rates=rates)
        best = seated(world, draft, ASSUMPTIONS_ONLY, DEFAULT).solve(top=1).ranked[0]
        seated_at.append(benched.id in best.key)
        scores.append(best.score)
    assert scores == sorted(scores)
    assert seated_at[-1] and not seated_at[0]
    assert seated_at == sorted(seated_at)              # once in, never out


# --- dummy heuristics ----------------------------------------------------------------


@pytest.mark.parametrize("base", [OFF, DEFAULT], ids=["meta-off", "meta-on"])
def test_dummy_heuristics_are_the_enumerations_argmax(synthetic_world, tmp_path, base):
    """Scratch rules - a maximised metric, a minimised one, a need guarded
    on the six's own shape and a scored bonus - under the meta off and on:
    on every board the search's best sixes are the enumeration's, element
    for element, and on a widened roster too."""
    rules = playbook(str(tmp_path), {
        "more-cc": heuristic("team.cc_count", "maximize", 2.5),
        "fewer-squishies": heuristic("team.squish_count", "minimize", 1),
        "one-support-needs-mobility": heuristic("team.mobility_count", "maximize", 1,
                                                when="team.supports <= 1"),
        "flat-bonus": ("---\nname: flat bonus\nkind: heuristic\nweight: 0.5\n"
                       "when: team.tanks >= 2\nbonus: min(team.cc_count, 3)\n---\nx\n")})
    assert {s.form for s in rules if s.kind == "heuristic"} == {"heuristic", "scored"}
    worlds = [synthetic_world] * len(BOARDS) + [widened(synthetic_world)]
    drafts = [*BOARDS, Draft("Ember Ruins", ("Rook",), ("Balm",))]
    for world, draft in zip(worlds, drafts, strict=True):
        solver = seated(world, draft, rules, base)
        assert verdicts(solver.solve(top=K).ranked) == verdicts(enumerated(solver)[:K]), draft


@pytest.mark.parametrize("base", [OFF, DEFAULT], ids=["meta-off", "meta-on"])
def test_a_heavier_weight_never_lowers_its_metric_in_the_optimal_six(synthetic_world, tmp_path,
                                                                     base):
    """A rule's weight raised from 0 to 10 beside a rival rule, the optimal
    six reads the rule's normalised value no lower at each step - the exact
    argmax trades toward the heavier rule, as it must for any objective
    plus a weight times a term - and with the meta off, at the top weight,
    it reaches the enumeration's best value of it."""
    draft = Draft("Harbor Gate", ("Mortar", "Gale"))
    reads = []
    for weight in (0, 0.25, 1, 2.5, 4, 10):
        directory = tmp_path / ("w%s" % weight)
        directory.mkdir()
        rules = playbook(str(directory), {
            "more-cc": heuristic("team.cc_count", "maximize", weight),
            "more-squishies": heuristic("team.squish_count", "maximize", 1)})
        solver = seated(synthetic_world, draft, rules, base)
        reads.append(norm(solver.solve(top=1).ranked[0], "more-cc"))
    assert reads == sorted(reads)
    if not base.on:
        assert reads[-1] == max(norm(solver.hydrate(c), "more-cc") for c in enumerated(solver))


def norm(cand, sid):
    """A scored six's normalised value on one heuristic, from its breakdown."""
    return next(c["norm"] for c in cand.contributions if c["id"] == sid)
