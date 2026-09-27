"""The owner's recorded matches, written: the one writer of `matches` and
`match_picks`. The door's record_match resolves a match's names and checks
it against the queue and the roster, then hands this module ids, and it
stores them. The facts layer reads them back (facts.matches).

    StoredMatch   one match as it is written: ids, not names
    store         one match and its picks -> its match_id
    delete        one match, its picks with it -> whether it was there
"""

import datetime
from typing import NamedTuple

import psycopg

from db import psql


class StoredMatch(NamedTuple):
    """One recorded map as the tables hold it: the day, the map's id, blue's
    side and result, the playbook's digest, the note, and the hero ids of
    blue's six, red's six and the bans, each in the order entered."""
    played_on: datetime.date
    map_id: int
    side: str
    result: str
    playbook_digest: str
    note: str
    blue: tuple[int, ...]
    red: tuple[int, ...]
    bans: tuple[int, ...]


def store(cursor: psycopg.Cursor, match: StoredMatch, source_id: int) -> int:
    """Insert one match and its picks under `source_id` -> its match_id."""
    cursor.execute(
        "INSERT INTO matches (played_on, map_id, side, result, playbook_digest, note,"
        " source_id) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING match_id", (
            match.played_on, match.map_id, match.side, match.result, match.playbook_digest,
            match.note, source_id))
    stored: int = psql.scalar(cursor)
    for team, heroes in (("blue", match.blue), ("red", match.red), ("ban", match.bans)):
        for position, hero_id in enumerate(heroes, 1):
            cursor.execute(
                "INSERT INTO match_picks (match_id, team, position, hero_id, source_id)"
                " VALUES (%s, %s, %s, %s, %s)", (stored, team, position, hero_id, source_id))
    return stored


def delete(cursor: psycopg.Cursor, match_id: int) -> bool:
    """Delete one match; its picks cascade -> whether there was one."""
    cursor.execute("DELETE FROM matches WHERE match_id = %s", (match_id,))
    return cursor.rowcount == 1
