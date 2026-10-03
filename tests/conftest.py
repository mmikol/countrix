"""Shared fixtures.

Two kinds of test:

    unit         pure functions - no database, no network
    invariant    properties the built database must hold

A unit test that needs a World takes synthetic_world, built by hand in
tests/synthetic.py. The second kind defaults to the repo's own build at
db/psql/cluster, the database `.venv/bin/python -m door.mcp call db_rebuild` produces,
and skips itself when it is absent. DATABASE_URL overrides the target;
COUNTRIX_NO_DATABASE=1 runs the suite with no database. A run that starts
with no cluster ends with none.
"""

import os
import shutil

import pytest

from db import DEFAULT_DB_DIR, psql
from tests import synthetic


def _dsn():
    if os.environ.get("COUNTRIX_NO_DATABASE"):
        return None            # no database: the db-bound tests skip
    try:
        return psql.default_dsn()   # the code's own answer, which creates no cluster
    except psql.NoDatabaseError:
        return None


@pytest.fixture(scope="session", autouse=True)
def no_cluster_after_a_database_free_run():
    """A run that starts with no cluster at db/psql/cluster ends with none:
    only db_rebuild creates one, through psql.boot, and a probe, a served
    /health or a test that reads resolves through default_dsn, which never
    does. CI never sets COUNTRIX_NO_DATABASE, and a fresh clone with
    pgserver installed is where a first touch once created one, so the check
    holds whatever that variable says."""
    absent = not os.path.exists(DEFAULT_DB_DIR)
    yield
    if absent:
        assert not os.path.exists(DEFAULT_DB_DIR), "a database-free run created db/psql/cluster"


@pytest.fixture(scope="session")
def dsn(db):
    """The connection string the suite runs against, password included (a
    connection's own `info.dsn` drops it). It rides on `db` so it skips the
    same way."""
    return _dsn()


@pytest.fixture(scope="session")
def db():
    dsn = _dsn()
    if not dsn:
        pytest.skip("no database: run `.venv/bin/python -m door.mcp call db_rebuild` first")
    import psycopg

    try:
        connection = psycopg.connect(dsn)
    except psycopg.Error as error:
        pytest.skip("database unreachable: %s" % error)
    if connection.execute(
        "SELECT count(*) FROM pg_tables WHERE schemaname='public'"
    ).fetchone()[0] == 0:
        pytest.skip("database is empty: run `.venv/bin/python -m door.mcp call db_rebuild`")
    yield connection
    connection.close()


@pytest.fixture(scope="module")
def world(db):
    """The World the facts and the inference tests read, built once per module.
    The load runs a read transaction; rolling it back leaves the session
    connection clean for the next fixture."""
    from facts import tables

    w = tables.load(db)
    db.rollback()
    return w


@pytest.fixture()
def synthetic_world():
    """A fresh synthetic World for each test, which may change it: twelve
    released heroes, an announced one and three maps, and no database."""
    return synthetic.world()


@pytest.fixture()
def catalog_copy(tmp_path):
    """A private copy of the reference playbook - its strategy files and its
    meta.md - in tmp_path, to write to without touching the repo."""
    from inference import catalog
    from tests.verification.inference import FIXTURE_PLAYBOOK

    for name in [*catalog.strategy_files(FIXTURE_PLAYBOOK), catalog.META_FILE]:
        shutil.copy(os.path.join(FIXTURE_PLAYBOOK, name), tmp_path / name)
    return str(tmp_path)


@pytest.fixture(scope="session")
def rows(db):
    return lambda sql, *args: db.execute(sql, args or None).fetchall()


@pytest.fixture(scope="session")
def one(db):
    return lambda sql, *args: db.execute(sql, args or None).fetchone()[0]
