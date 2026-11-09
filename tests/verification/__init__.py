"""The code against its spec, a folder per layer - db, facts, inference,
door, ui - beside the orchestrator's tests: the units, the search against a
full enumeration, the database's invariants, and the hand-run provers in
inference/, which pytest does not collect. healthy() is the stack's /health
replies with every layer ready, which the orchestrator's tests share.
KIT_LAGS and MAP_LAGS name what Blizzard shipped and the wiki has not
written yet, the holes the invariant tests excuse by name."""

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
# 2026-11-09 has no Cyberspace block and Hack's rows under Hotfix's name, so
# Cyberspace has no kind and she reads as a support that heals nothing
KIT_LAGS = (WikiLag("Sombra", "2026-10-06", ("Cyberspace",)),)
# Blizzard's rates filter lists the Escort map; the wiki's Maps article of
# 2026-11-09 still files it under Upcoming, so the pool lacks it and the rates
# pull skips it
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
