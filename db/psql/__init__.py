"""The database: where it is, and the small things every writer needs.

    default_dsn         where to read and write: $DATABASE_URL, or the
                        embedded cluster at db/psql/cluster once one is
                        built (pgserver starts it on first touch); it never
                        creates a cluster
    boot                the same for db_rebuild alone, creating the
                        embedded cluster when none is built
    NoDatabaseError     no DATABASE_URL and no embedded cluster to use; a
                        host without pgserver must set DATABASE_URL
    UNREACHABLE         the errors that mean the database is out of reach
    register_source     the `sources` row a page or a file becomes, upserted;
                        every table's rows carry its source_id
    identifier          a table or column name on its way into SQL text,
                        checked and returned as a psycopg.sql.Identifier
    lookup_ids          {value: id} over one column, each value as stored;
                        a name a source writes is matched through
                        db.data.normalizer.index
    scalar              the one value a statement returns: a count, an
                        upsert's RETURNING
    now, current_patch  what a capture is stamped with

    schema              the migrations applied and recorded in the ledger,
                        pending, rebuild, the generated docs, and state():
                        how ready the database is
    migrations/         NNN_name.sql, the schema as a sequence

Nothing here knows a particular source.
"""

import json
import os
import re
import threading
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.sql import SQL, Identifier

from db import DEFAULT_DB_DIR, Source

try:
    import pgserver
except ImportError:     # the image and CI filter it out of requirements.txt
    # the ignore is used where pgserver is installed (it ships types) and
    # unused in CI, where it is not
    pgserver = None     # type: ignore[assignment, unused-ignore]


class NoDatabaseError(Exception):
    """DATABASE_URL is unset and there is no embedded cluster to use: none is
    built at db/psql/cluster, or there is no pgserver to run one. Readers
    report it as the database out of reach; db_rebuild creates the cluster
    through boot."""


# Every way the database can be out of reach, which a health endpoint reports
# as degraded: the connection and its queries (psycopg.Error); no DATABASE_URL
# and no cluster to use, or an embedded cluster that would not start
# (NoDatabaseError, from default_dsn); the embedded cluster's files and socket
# (OSError); and pgserver's .handle_pids.json, left empty by a process killed
# while writing it (JSONDecodeError).
UNREACHABLE = (psycopg.Error, NoDatabaseError, OSError, json.JSONDecodeError)

# pgserver's own lock (fasteners, over fcntl) excludes other processes but
# not this process's threads, and get_server reads its instance cache before
# taking it, so two first touches from a threaded server (ui/board.py) could
# interleave the read-truncate-write of the pid file. The first touch is
# serialised here. What remains: a .handle_pids.json left empty by a process
# killed mid-write makes the first touch in each later process raise
# JSONDecodeError, reported as degraded, and later touches in that process
# get pgserver's cached handle, with the process unregistered. The file is
# pgserver's and is not repaired here; removing it while no process uses the
# cluster clears the fault (pgserver 0.1.4's DiskList reads a missing file
# as []).
_FIRST_TOUCH = threading.Lock()


def default_dsn() -> str:
    """Where to read and write: $DATABASE_URL, or the embedded cluster at
    db/psql/cluster once one is built, started on first touch when it is not
    running. It never creates a cluster: with neither, NoDatabaseError, which
    the readers report as the database out of reach."""
    explicit = os.environ.get("DATABASE_URL")
    if explicit:
        return explicit
    if not os.path.isfile(os.path.join(DEFAULT_DB_DIR, "PG_VERSION")):     # initdb's mark
        raise NoDatabaseError("no DATABASE_URL and no embedded cluster at db/psql/cluster:"
                              " set DATABASE_URL, or build one with db_rebuild")
    return _embedded()


def boot() -> str:
    """Where db_rebuild writes: $DATABASE_URL, or the embedded cluster,
    created at db/psql/cluster when none is built. Only that tool calls it;
    every reader resolves through default_dsn."""
    return os.environ.get("DATABASE_URL") or _embedded()


def _embedded() -> str:
    """The embedded cluster's URI: pgserver starts the cluster when it is not
    running and runs initdb when it is not built. A host without pgserver
    has none to run: NoDatabaseError, naming DATABASE_URL. A start that
    fails in a way UNREACHABLE does not name - pg_ctl's error or its
    ten-second timeout, a pid file with no socket or port, the handle a
    failed start leaves cached for the rest of the process - is
    NoDatabaseError too, so every reader reports it as the database out of
    reach."""
    if pgserver is None:
        raise NoDatabaseError("no DATABASE_URL and no embedded cluster: pgserver is not"
                              " installed here (the image and CI filter it out; linux/arm64"
                              " has no wheel) - set DATABASE_URL")
    with _FIRST_TOUCH:
        try:
            return pgserver.get_server(DEFAULT_DB_DIR).get_uri()
        except UNREACHABLE:
            raise
        except Exception as error:      # any other pgserver failure: the cluster is out of reach
            raise NoDatabaseError(
                "the embedded cluster at db/psql/cluster did not start (%s - %s) - see"
                " db/psql/cluster/log and restart this process after a failed start"
                % (type(error).__name__, error)) from error


IDENTIFIER_RE = re.compile(r"[a-z_][a-z0-9_]*\Z")


def identifier(name: str) -> Identifier:
    """A table or column name on its way into SQL text: checked against the
    lowercase allowlist IDENTIFIER_RE, then quoted by psycopg. A query
    parameter carries a value, never a name, so every writer that names a
    table in the statement itself composes it with psycopg.sql through here.
    The names all come from a literal or from the catalog today, and this is
    what keeps it so."""
    if not IDENTIFIER_RE.match(name):
        raise ValueError("not a SQL identifier: %r" % (name,))
    return Identifier(name)


def lookup_ids(
        cursor: psycopg.Cursor, table: str, key_column: str, id_column: str) -> dict[str, int]:
    """{value: id} over key_column, each value as stored. A code needs no
    fold: ability_kinds is seeded with db.ABILITY_KINDS, in lower case. A
    hero or map name a source writes is matched through
    db.data.normalizer.index, which rekeys this by name_key."""
    return {
        row[0]: row[1]
        for row in cursor.execute(
            SQL("SELECT {}, {} FROM {}").format(
                identifier(key_column), identifier(id_column), identifier(table))
        ).fetchall()
    }


def scalar(cursor: psycopg.Cursor) -> Any:
    """The first column of the row the last statement returned - an aggregate,
    an upsert's RETURNING, a lookup by key - for a statement that always
    returns one. No row is a bug in the statement, and raises. The value is
    typed Any, as psycopg types a row's cells: the statement decides what the
    column holds."""
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError("a statement that always returns a row returned none")
    return row[0]


def now() -> datetime:
    """One timestamp for a run."""
    return datetime.now(UTC)


def register_source(cursor: psycopg.Cursor, source: Source, cao: datetime) -> int:
    """Upsert one source and return its source_id. `cao` ("current as of")
    is refreshed every time a source is read."""
    cursor.execute(
        "INSERT INTO sources (code, name, url, cao) VALUES (%s, %s, %s, %s)"
        " ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name,"
        " url = EXCLUDED.url, cao = EXCLUDED.cao RETURNING source_id",
        (source.code, source.name, source.url, cao),
    )
    return scalar(cursor)


def current_patch(cursor: psycopg.Cursor, captured: datetime) -> int | None:
    """The patch live at a capture, to stamp on its snapshot: the most recent
    released on or before the capture's date, taken in the session's time
    zone, as a snapshot's captured_at::date reads it."""
    row = cursor.execute(
        "SELECT patch_id FROM patches WHERE released <= %s::date"
        " ORDER BY released DESC, patch_id DESC LIMIT 1", (captured,)
    ).fetchone()
    return row[0] if row else None

