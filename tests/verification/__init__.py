"""The code against its spec, a folder per layer - db, facts, inference,
door, ui - beside the orchestrator's tests: the units, the search against a
full enumeration, the database's invariants, and the hand-run provers in
inference/, which pytest does not collect. healthy() is the stack's /health
replies with every layer ready, which the orchestrator's tests share.
KIT_LAGS and MAP_LAGS name what Blizzard shipped and the wiki has not
written yet, the holes the invariant tests excuse by name; the patch fixes
(facts/patch_notes.py) fill a kit lag's figures in the World from
Blizzard's notes, and the database keeps the hole until the wiki writes it."""

from typing import Any, NamedTuple


class WikiLag(NamedTuple):
    """A hero or a map Blizzard ships that the wiki has not caught up with:
    the day it shipped, and the pieces Blizzard lists that the wiki holds no
    row for. The invariant test that excuses it fails once the wiki writes
    them, so the entry goes in the change that pulls them."""
    name: str
    since: str
    missing: tuple[str, ...] = ()


# Sombra's rework into a support: Blizzard's page lists Hotfix, "Heal an ally
# over time", and Cyberspace, a zone that "heals allies"; the wiki's article of
# 2026-11-14 has no Cyberspace block and Hack's rows under Hotfix's name, so
# the stored Cyberspace has no kind, and the patch fixes give both their rows
KIT_LAGS = (WikiLag("Sombra", "2026-10-06", ("Cyberspace",)),)
# The notes of October 6 ship the Escort map ("New Escort Map - Grímsvötn"),
# and pull_patch_notes pools it under that label, so its rates are read; the
# wiki's Maps article of 2026-11-14 files it under Upcoming, titled Watchpoint:
# Grimsvötn, so it has no stages and no terrain until the wiki pools it
MAP_LAGS = (WikiLag("Grímsvötn", "2026-10-06"),)


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
