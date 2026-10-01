"""Verify the engine in stages on the built database, as the suite's
tests/verification/inference/test_stages.py does on the synthetic World: the null
objective, then the meta alone, then dummy heuristics. The playbook in
force keeps its limits and its assumptions throughout; its heuristics are
left out, so each stage adds one thing.

    null        the meta at 0: the legal space against its analytic count,
                every six tied (the board's tie count), and over SEEDS
                boards' seeds how often the draw seats each hero - each
                role's spread, and any hero never seated
    meta        the meta in force: on BOARDS, whose locks leave a space a
                brute force lists in seconds, the search's best sixes
                against the enumeration's, bit for bit; the six at every
                meta above 0 the same
    heuristics  dummy rules on a metric beside the meta, on and off: the
                same brute force, and the rule's normalised value in the
                optimal six against its weight, never falling

Run from the repo root, as a module of the tests' package; pytest does not
collect it. It prints a report, the verdict of each check on its line, and
exits 1 where one fails. Nothing here prints a rate:

    .venv/bin/python -m tests.verification.inference.verify_engine
"""

import dataclasses
import itertools
import math
import sys
import tempfile
import time
from collections.abc import Iterator
from typing import NamedTuple

import psycopg

from db import psql
from facts import tables
from facts.draft import Draft
from facts.model import ROLES, Hero, World
from inference import catalog, engine, scoring
from inference.base import OFF, BaseWeights
from inference.scoring import Candidate, rank_key
from inference.shapes import legal_shapes
from inference.solver import RANK_CAP, Solver
from inference.strategy import Strategy

K = 6                        # the sixes a board's seat keeps
SEEDS = 2000                 # the boards' seeds the null draw is counted over


class Board(NamedTuple):
    """A board small enough to list: the map, red's picks, the locked
    picks, the bans and the side."""
    map_name: str
    red: tuple[str, ...]
    locked: tuple[str, ...]
    bans: tuple[str, ...]
    side: str


BOARDS = {
    "samoa-three-locks": Board("Samoa", ("D.Va", "Roadhog", "Sombra"), ("Ana", "Reinhardt",
                                                                        "Genji"), (), ""),
    "kings-row-three-locks": Board("King's Row", ("Zarya", "Pharah"),
                                   ("Mercy", "Winston", "Tracer"), ("Kiriko",), "attack"),
    "ilios-bans": Board("Ilios", ("Winston", "Tracer", "Genji", "Kiriko"),
                        ("Lúcio", "Sigma", "Echo"), ("Ana", "Sojourn", "Reinhardt", "Moira"),
                        ""),
}
DUMMIES = {
    "more-cc": ("team.cc_count", "maximize", 2.5),
    "fewer-squishies": ("team.squish_count", "minimize", 1.0),
}


def _world() -> World:
    with psycopg.connect(psql.default_dsn()) as cx:
        return tables.load(cx)


def _limits() -> list[Strategy]:
    """The playbook in force without its heuristics: its limits and its
    assumptions."""
    return [s for s in catalog.load() if s.kind != "heuristic"]


def _dummies(weight: float) -> list[Strategy]:
    """The dummy rules, `more-cc` at `weight`, beside the playbook's limits
    and assumptions, loaded from a scratch folder."""
    with tempfile.TemporaryDirectory() as directory:
        for sid, (metric, direction, w) in DUMMIES.items():
            with open("%s/%s.md" % (directory, sid), "w", encoding="utf-8") as handle:
                handle.write("---\nname: dummy %s\nkind: heuristic\nmetric: %s\ndirection: %s\n"
                             "weight: %s\n---\nA dummy rule.\n"
                             % (sid, metric, direction, weight if sid == "more-cc" else w))
        return [*_limits(), *catalog.load(directory)]


def _solver(world: World, board: Board, playbook: list[Strategy], base: BaseWeights) -> Solver:
    m, red, locked, banned = world.resolve(board.map_name, board.red, board.locked, board.bans)
    return Solver(world, m, red=red, locked=locked, banned=banned, side=board.side,
                  catalog=playbook, base=base)


def _sixes(solver: Solver) -> Iterator[list[Hero]]:
    """Every legal six of the board, without the search."""
    taken = {h.id for h in solver.locked} | solver.banned
    roster = {r: sorted((h for h in solver.world.heroes.values()
                         if h.role == r and h.released and h.id not in taken),
                        key=lambda h: h.id) for r in ROLES}
    for shape in solver.shapes():
        need = [shape[i] - sum(1 for h in solver.locked if h.role == r)
                for i, r in enumerate(ROLES)]
        for combo in itertools.product(*(itertools.combinations(roster[r], need[i])
                                         for i, r in enumerate(ROLES))):
            yield [*solver.locked, *(h for part in combo for h in part)]


def _enumerated(solver: Solver) -> list[Candidate]:
    solver.freeze_scale()
    scored = [solver.score(solver.prepare(Candidate(six)), detail=False)
        for six in _sixes(solver)]
    return sorted((c for c in scored if not c.violations), key=rank_key)[:K]


def _verdicts(sixes: list[Candidate]) -> list[tuple[float, float, list[str]]]:
    return [(c.score, c.tiebreak, sorted(c.names)) for c in sixes]


def _analytic(world: World, playbook: list[Strategy]) -> int:
    free = {r: sum(1 for h in world.heroes.values() if h.role == r and h.released)
            for r in ROLES}
    shapes = legal_shapes(playbook)
    return sum(math.prod(math.comb(free[r], s[i]) for i, r in enumerate(ROLES)) for s in shapes)


class Report:
    """Each check's verdict, printed as it lands."""

    def __init__(self) -> None:
        self.failed = 0

    def check(self, ok: bool, what: str) -> None:
        self.failed += not ok
        print("  %s  %s" % ("ok  " if ok else "FAIL", what), flush=True)


def null(world: World, report: Report) -> None:
    print("\nthe null objective: the meta at 0, the limits and assumptions alone")
    playbook = _limits()
    count = _analytic(world, playbook)
    result = engine.infer(world, Draft("King's Row", side="attack"), catalog=playbook, base=OFF)
    report.check(result.considered == count,
                 "an open board covers %s legal sixes, the analytic count %s"
                 % (format(result.considered, ","), format(count, ",")))
    report.check(result.score == 0.0 and tuple(result.tied) == (RANK_CAP, True),
                 "every six scores 0, and the board says: %s" % result.to_dict()["tie"])
    counts = {h.id: 0 for h in world.heroes.values() if h.released}
    seeds = iter(range(10 ** 9))
    board_seed = scoring.board_seed
    scoring.board_seed = lambda m, side: "verify %d" % next(seeds)
    m = world.resolve("King's Row", (), (), ())[0]
    started = time.time()
    try:
        for _ in range(SEEDS):
            six = Solver(world, m, red=[], locked=[], catalog=playbook,
                         base=OFF).solve(top=1).ranked[0]
            for h in six.heroes:
                counts[h.id] += 1
    finally:
        scoring.board_seed = board_seed
    print("  the draw over %d seeds, %.0fs:" % (SEEDS, time.time() - started))
    for role in ROLES:
        seen = sorted(((n, world.heroes[i].name) for i, n in counts.items()
                       if world.heroes[i].role == role))
        mean = sum(n for n, _ in seen) / len(seen)
        line = ("    %-8s %d heroes, seated %.0f times each on average (%.1f%% of boards);"
                " fewest %s %d, most %s %d")
        print(line % (role, len(seen), mean, 100 * mean / SEEDS, seen[0][1], seen[0][0],
                      seen[-1][1], seen[-1][0]))
        report.check(all(abs(n - mean) <= mean / 4 for n, _ in seen),
                     "every %s is seated within a quarter of the role's mean" % role)
    never = [world.heroes[i].name for i, n in counts.items() if not n]
    report.check(not never, "every released hero is seated on some seed%s"
                 % (": never %s" % ", ".join(never) if never else ""))


def meta(world: World, report: Report) -> None:
    print("\nthe meta alone: the meta in force, the limits and assumptions")
    playbook, weights = _limits(), catalog.engine_weights()
    for name, board in BOARDS.items():
        solver = _solver(world, board, playbook, weights)
        started = time.time()
        searched = solver.solve(top=K).ranked
        took = time.time() - started
        truth = _enumerated(_solver(world, board, playbook, weights))
        report.check(_verdicts(searched) == _verdicts(truth),
                     "%s: the search's best %d are the enumeration's, bit for bit, over %s"
                     " sixes (search %.2fs)" % (name, K, format(solver.considered, ","), took))
        keys = {tuple(c.key for c in _solver(world, board, playbook, dataclasses.replace(
            weights, meta=x)).solve(top=K).ranked) for x in (0.25, 1.0, 4.0)}
        report.check(len(keys) == 1, "%s: the meta at 0.25, 1 and 4 gives the same sixes" % name)


def heuristics(world: World, report: Report) -> None:
    print("\ndummy heuristics: more crowd control (2.5), fewer squishies (1)")
    for base_name, weights in (("meta off", OFF), ("meta on", catalog.engine_weights())):
        for name, board in BOARDS.items():
            playbook = _dummies(DUMMIES["more-cc"][2])
            solver = _solver(world, board, playbook, weights)
            searched = solver.solve(top=K).ranked
            truth = _enumerated(_solver(world, board, playbook, weights))
            report.check(_verdicts(searched) == _verdicts(truth),
                         "%s, %s: the search's best %d are the enumeration's"
                         % (base_name, name, K))
        board = BOARDS["samoa-three-locks"]
        reads = []
        for weight in (0.0, 0.25, 1.0, 2.5, 4.0, 10.0):
            best = _solver(world, board, _dummies(weight), weights).solve(top=1).ranked[0]
            reads.append(next(c["norm"] for c in best.contributions if c["id"] == "more-cc"))
        report.check(reads == sorted(reads),
                     "%s: more-cc's weight 0 to 10 never lowers its value in the optimal six"
                     " (%s)" % (base_name, ", ".join("%.2f" % r for r in reads)))


def main() -> int:
    started = time.time()
    world = _world()
    released = sum(1 for h in world.heroes.values() if h.released)
    print("the engine in stages on the built database: %d released heroes" % released)
    report = Report()
    null(world, report)
    meta(world, report)
    heuristics(world, report)
    print("\n%s in %.0fs" % ("all checks hold" if not report.failed
                             else "%d checks FAILED" % report.failed, time.time() - started))
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
