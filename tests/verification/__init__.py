"""The code against its spec, a folder per layer - db, facts, inference,
door, ui - beside the orchestrator's tests: the units, the search against a
full enumeration, the database's invariants, and the hand-run provers in
inference/, which pytest does not collect. healthy() is the stack's /health
replies with every layer ready, which the orchestrator's tests share."""

from typing import Any


def healthy() -> dict[str, Any]:
    """The stack's /health replies with every layer ready, and the board the
    readiness probe solved: 36 tables, 54 heroes - one announced - rates
    captured 2026-09-14, 38 strategies, 30 maps. A fresh copy each call, for
    a test to change."""
    return {
        "data": {"status": "ok", "state": "current", "table_count": 36, "heroes": 54,
                 "announced": 1, "pending_migrations": [], "newest_capture": "2026-09-14"},
        "inference": {"status": "ok", "strategies": 38, "heroes": 54, "pending": 0},
        "ui": {"heroes": [{}] * 54, "maps": [{}] * 30},
        "board": {"seconds": 1.0, "picks": []}}
