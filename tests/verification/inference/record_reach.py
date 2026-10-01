"""Record a board per released hero that seats it, for the reach test.

Runs inference.reach.search for every released hero, in name order, on the
built database, the playbook in force and the default engine at its meta.md's
weights, and writes the boards it finds to tests/fixtures/reach.json beside
that playbook's digest and the engine's stamp (inference.base.stamp).
Minutes of solving in one process. Run from the repo root, as a module of
the tests' package; pytest does not collect it, and test_reach.py runs it
on the synthetic World:

    .venv/bin/python -m tests.verification.inference.record_reach

A hero its own search finds no board for is not yet unseated: every six
already recorded is checked first - the boards this run found for the other
heroes, then the boards the fixture held, each solved afresh - and a board
whose optimal six holds the hero is recorded for it too. It prints the
heroes no board seats, each with the gap its own search fell short by, so
UNSEATED in tests/verification/inference/test_reach.py can be checked against them.
"""
import json
import os

import psycopg

from db import ROOT, psql
from facts import tables
from facts.model import World
from inference import base, catalog, reach

OUT = os.path.join(ROOT, "tests", "fixtures", "reach.json")


def _recorded() -> list[reach.Reach]:
    """The boards the fixture held before this run, or none."""
    try:
        with open(OUT, encoding="utf-8") as handle:
            boards: list[reach.Reach] = json.load(handle)["boards"]
    except (OSError, ValueError, KeyError):
        return []
    return boards


def _board(board: reach.Reach) -> tuple[str, str, tuple[str, ...], tuple[str, ...]]:
    return board["map"], board["side"], tuple(board["red"]), tuple(board["banned"])


def _elsewhere(
        world: World, unseated: list[str], found: list[reach.Reach]) -> dict[str, reach.Reach]:
    """{hero: a board whose optimal six holds it} for each unseated hero an
    already recorded six seats: this run's boards as found, then the
    fixture's boards this run did not find, each solved afresh."""
    boards = list(found)
    seen = {_board(b) for b in found}
    # solved only while a hero is left unplaced: each is a solve
    pending = [b for b in _recorded() if _board(b) not in seen] if unseated else []
    placed: dict[str, reach.Reach] = {}
    for name in unseated:
        board = next((b for b in boards if name in b["six"]), None)
        while board is None and pending:
            prior = pending.pop(0)
            if _board(prior) in seen:
                continue
            seen.add(_board(prior))
            solved: reach.Reach = {**prior, "six": reach.six(world, prior)}
            boards.append(solved)
            if name in solved["six"]:
                board = solved
        if board is not None:
            placed[name] = {**board, "hero": name, "seated": True, "gap": 0.0}
    return placed


def main() -> int:
    """Search every released hero, record the boards that seat one -> 0."""
    with psycopg.connect(psql.default_dsn()) as cx:
        world = tables.load(cx)
    released = sorted(h.name for h in world.heroes.values() if h.released)
    searched = {name: reach.search(world, name) for name in released}
    found = [b for b in searched.values() if b["seated"]]
    placed = _elsewhere(world, [n for n in released if not searched[n]["seated"]], found)
    seated = [
        searched[n] if searched[n]["seated"] else placed[n]
        for n in released if searched[n]["seated"] or n in placed]
    unseated = ["%s %.3f" % (n, searched[n]["gap"])
                for n in released if not searched[n]["seated"] and n not in placed]
    playbook = catalog.playbook_digest()
    with open(OUT, "w", encoding="utf-8") as handle:
        json.dump({"playbook": playbook, "base": base.stamp(catalog.engine_weights()),
                   "boards": seated}, handle, indent=1)
    print(
        "recorded %d seated heroes under playbook %s and the default engine, %d of them after"
        " bans, %d on a six recorded for another; unseated: %s"
        % (
            len(seated), playbook[:12], sum(1 for b in seated if b["banned"]), len(placed),
            ", ".join(unseated) or "none"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
