"""Prove the exact search on the built database: a brute force of every
legal six on a board, against the search's own answer.

The search (inference.solver) is exact by construction and the suite
checks it against a full enumeration on the synthetic World. This checks it
on real boards, where a board holds millions of legal sixes: every one is
enumerated here without the search - itertools over each role's released,
unbanned heroes by id, shape by shape - prepared and scored by the one
objective, and ranked by scoring.rank_key. The enumeration runs in slices,
each a process of its own under five minutes; `merge` then compares the
slices' merged best sixes with the search's, bit for bit - each score's
float, its tie-break and its names - the legal count with the search's
`considered`, and, for a board with a full six, the sixes that outscore
it with the search's count. Run from the repo root, as a module of the
tests' package; pytest does not collect it:

    .venv/bin/python -m tests.verification.inference.prove_exact world  OUT
    .venv/bin/python -m tests.verification.inference.prove_exact slice  OUT BOARD INDEX COUNT
    .venv/bin/python -m tests.verification.inference.prove_exact merge  OUT BOARD COUNT

`world` pickles the database's World into OUT once, so the slices do not
each load it; start COUNT slices of a board at once, in the background,
then merge. BOARDS names the boards; the playbook is the one in force.
Each slice writes OUT/BOARD.INDEX-of-COUNT.json.

A swap board (`keep` set) proves blue's swap search (inference.swaps): its
Solver carries the keep term - the cost, in share points of the unlocked
board's span, for each reference hero a six holds - on the unlocked
board's scale, and the enumeration scores every six around its locks by
that one objective. Its locks hold some of the reference and leave the
rest open, so a kept hero is met both locked and searched; `engine` off
runs it at base.OFF, where the keep term is the bound's own part alone.
"""

import itertools
import json
import os
import pickle  # nosec B403  # a World this module pickled itself, into the caller's folder
import sys
import time
from typing import NamedTuple

import psycopg

from db import psql
from facts import tables
from facts.model import ROLES, World
from inference import catalog, swaps
from inference.base import OFF
from inference.result import Span
from inference.scoring import Candidate, quantized, rank_key
from inference.solver import RANK_CAP, Solver

K = 6                        # the sixes a board's seat keeps


class Board(NamedTuple):
    """A board to prove: the map, red's picks, the locked picks, the bans,
    the side, a full six to rank (empty for none), and for a swap board
    the reference picks, the swap cost in share points and whether the
    default engine is on."""
    map_name: str | None
    red: tuple[str, ...]
    locked: tuple[str, ...]
    bans: tuple[str, ...]
    side: str
    six: tuple[str, ...] = ()
    keep: tuple[str, ...] = ()
    cost: float = 0.0
    engine: bool = True


# the swap boards' red, reference and locks: a full reference with three of
# its heroes locked, and a half-drafted one whose locks hold one of its three
SWAP_RED = ("Reinhardt", "Zarya", "Genji", "Tracer", "Ana", "Lúcio")
SWAP_FULL = ("Sigma", "Winston", "Cassidy", "Sojourn", "Kiriko", "Mercy")
SWAP_HALF = ("D.Va", "Echo", "Baptiste")


BOARDS = {
    # the board the investigation found the per-role pool search missing
    "samoa": Board("Samoa", ("D.Va", "Roadhog", "Sombra", "Lúcio", "Brigitte"), (), (), ""),
    "kings-row": Board("King's Row", (), (), (), "attack"),
    "kings-row-fill": Board("King's Row", ("Zarya", "Pharah"), ("Ana", "Reinhardt"), (),
                            "attack"),
    "ilios-bans": Board("Ilios", ("Winston", "Tracer", "Genji", "Kiriko"), (),
                        ("Ana", "Sojourn", "Reinhardt", "Moira"), ""),
    # a fill against red's full six, as the countered case solves one
    "havana-countered": Board("Havana", ("Reinhardt", "Zarya", "Genji", "Tracer", "Ana", "Lúcio"),
                              ("Kiriko",), (), "attack"),
    # a full six the search puts fortieth: its rank is counted exactly
    "junkertown-fortieth": Board("Junkertown", ("Ramattra", "Doomfist", "Bastion", "Reaper"),
                                 (), (), "defense", ("Ashe", "Baptiste", "D.Mon", "Juno",
                                                     "Widowmaker", "Zenyatta")),
    # a full six far outside RANK_CAP: the search says so
    "junkertown-rank": Board("Junkertown", ("Ramattra", "Doomfist", "Bastion", "Reaper"), (), (),
                             "defense", ("Reinhardt", "Zarya", "Soldier: 76", "Cassidy", "Ana",
                                         "Kiriko")),
}
for _cost in (0.0, 10.0, 25.0):
    for _on in (True, False):
        _tag = "%d%s" % (_cost, "" if _on else "-off")
        BOARDS["kings-row-swap-" + _tag] = Board(
            "King's Row", SWAP_RED, ("Sigma", "Cassidy", "Kiriko"), (), "attack",
            keep=SWAP_FULL, cost=_cost, engine=_on)
        BOARDS["havana-swap-" + _tag] = Board(
            "Havana", SWAP_RED, ("D.Va", "Ashe", "Lifeweaver"), (), "defense",
            keep=SWAP_HALF, cost=_cost, engine=_on)
# the swap search as a board runs it: nothing locked, every legal six searched
BOARDS["kings-row-swap-open"] = Board("King's Row", SWAP_RED, (), (), "attack",
                                      keep=SWAP_FULL, cost=10.0)


def _world(out: str) -> World:
    """The World pickled in `out`, else the database's."""
    path = os.path.join(out, "world.pkl")
    if os.path.exists(path):
        with open(path, "rb") as handle:
            world: World = pickle.load(handle)  # nosec B301  # written by `world` above
            return world
    with psycopg.connect(psql.default_dsn()) as cx:
        return tables.load(cx)


def _solver(world: World, name: str) -> Solver:
    """The Solver of a named board, its scale frozen; a swap board's with
    the keep term, on the unlocked board's scale."""
    board = BOARDS[name]
    m, red, locked, banned = world.resolve(board.map_name, board.red, board.locked, board.bans)
    weights = catalog.engine_weights() if board.engine else OFF
    if not board.keep:
        solver = Solver(world, m, red=red, locked=locked, banned=banned, side=board.side,
                        catalog=catalog.load(), base=weights)
        solver.freeze_bounds()
        return solver
    plain = Solver(world, m, red=red, locked=(), banned=banned, side=board.side,
                   catalog=catalog.load(), base=weights)
    best = plain.solve(top=1).ranked[0]
    raw = swaps.raw_cost(board.cost, Span(best=best.score, floor=plain.floor))
    solver = Solver(world, m, red=red, locked=locked, banned=banned, side=board.side,
                    catalog=plain.catalog, base=weights,
                    keep=frozenset(h.id for h in world.resolve(None, (), board.keep).blue),
                    swap=raw or 0.0)
    solver.adopt_scale(plain)
    return solver


def _sixes(solver: Solver):
    """Every legal six of the board, without the search: each legal shape's
    open slots filled from each role's released, unbanned heroes by id."""
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


def _verdict(c: Candidate) -> list[object]:
    return [c.score, c.tiebreak, sorted(c.names)]


def slice_(out: str, name: str, index: int, count: int) -> None:
    """Every `count`-th legal six from `index`, prepared, scored and ranked:
    its best K, how many it holds, how many keep the limits, and how many
    rank above the board's full six."""
    started = time.time()
    world = _world(out)
    solver = _solver(world, name)
    target = BOARDS[name].six
    bar = None
    if target:
        six = solver.prepare(Candidate(world.resolve(None, (), target).blue))
        bar = rank_key(solver.score(six, detail=False))
    best: list[Candidate] = []
    size = feasible = above = 0
    for position, heroes in enumerate(_sixes(solver)):
        size += 1
        if position % count != index:
            continue
        cand = solver.prepare(Candidate(heroes))
        if cand.violations:
            continue
        feasible += 1
        solver.slim(solver.score(cand, detail=False))
        if bar is not None and rank_key(cand) < bar:
            above += 1
        best.append(cand)
        if len(best) > 4 * K:
            best = sorted(best, key=rank_key)[:K]
    best = sorted(best, key=rank_key)[:K]
    path = os.path.join(out, "%s.%d-of-%d.json" % (name, index, count))
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"size": size, "feasible": feasible, "above": above,
                   "best": [_verdict(c) for c in best],
                   "seconds": round(time.time() - started, 1)}, handle)


def merge(out: str, name: str, count: int) -> bool:
    """The slices merged against the search -> whether they agree."""
    parts = []
    for index in range(count):
        with open(os.path.join(out, "%s.%d-of-%d.json" % (name, index, count)),
                  encoding="utf-8") as handle:
            parts.append(json.load(handle))
    brute = sorted((v for p in parts for v in p["best"]), key=lambda v: (
        -quantized(v[0]), -v[1], v[2]))[:K]
    world = _world(out)
    solver = _solver(world, name)
    started = time.time()
    solved = solver.solve(top=K)
    seconds = time.time() - started
    got = [_verdict(c) for c in solved.ranked]
    size = parts[0]["size"]
    same = got == brute and solver.considered == size
    report = {
        "board": name, "legal": size, "feasible": sum(p["feasible"] for p in parts),
        "brute_seconds": max(p["seconds"] for p in parts), "search_seconds": round(seconds, 3),
        "nodes": solver.nodes, "scored": solver.leaves, "considered": solver.considered,
        "equal": same, "brute": brute[:3], "search": got[:3]}
    if BOARDS[name].six:
        above = sum(p["above"] for p in parts)
        six = solver.prepare(Candidate(world.resolve(None, (), BOARDS[name].six).blue))
        counted = solver.outranking(solver.score(six, detail=False))
        report["above"], report["counted"] = above, counted
        agrees = counted == above if above < RANK_CAP else counted is None
        report["rank_equal"] = agrees
        same = same and agrees
    print(json.dumps(report, ensure_ascii=False))
    return same


def main(argv: list[str]) -> int:
    """world OUT | slice OUT BOARD INDEX COUNT | merge OUT BOARD COUNT -> 0, or 1 where the
    search and the brute force disagree."""
    command, out = argv[0], argv[1]
    if command == "world":
        with psycopg.connect(psql.default_dsn()) as cx:
            world = tables.load(cx)
        with open(os.path.join(out, "world.pkl"), "wb") as handle:
            pickle.dump(world, handle, pickle.HIGHEST_PROTOCOL)
        return 0
    if command == "slice":
        slice_(out, argv[2], int(argv[3]), int(argv[4]))
        return 0
    return 0 if merge(out, argv[2], int(argv[3])) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
