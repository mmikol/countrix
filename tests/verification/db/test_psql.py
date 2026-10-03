"""db/psql: where the database is, psql/__init__.py - the first touch,
which resolves and never creates, holds its lock, names DATABASE_URL to a
host without pgserver and reports every way the embedded cluster fails to
start as the database out of reach, which /health answers degraded - and
psql/schema.py's readiness, its probe and a migration that fails. pgserver
is stubbed and no connection reaches a database, so no cluster starts."""

import contextlib
import json
import re
import subprocess

import psycopg
import pytest

from db import psql
from db.psql import schema
from ui import serve


def _failing(failure):
    """A pgserver whose get_server raises `failure`."""
    class Server:
        @staticmethod
        def get_server(pgdata):
            raise failure
    return Server


def test_a_cluster_that_will_not_start_is_the_database_out_of_reach(monkeypatch, tmp_path):
    """pgserver re-raises pg_ctl's error and its timeout, a pid file with no
    socket is a RuntimeError, and the handle a failed start leaves cached
    fails an assert: none is in UNREACHABLE, so each leaves default_dsn as
    NoDatabaseError, naming the failure and the remedy, with the lock free.
    A failure UNREACHABLE names already leaves as it is."""
    (tmp_path / "PG_VERSION").write_text("16\n")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(psql, "DEFAULT_DB_DIR", str(tmp_path))
    for failure in (subprocess.CalledProcessError(1, ["pg_ctl", "start"]),
                    subprocess.TimeoutExpired(["pg_ctl", "start"], 10),
                    RuntimeError("postmaster.pid names no socket or port"),
                    AssertionError()):
        monkeypatch.setattr(psql, "pgserver", _failing(failure))
        with pytest.raises(psql.NoDatabaseError, match=re.escape(
                "did not start (%s - " % type(failure).__name__)) as refused:
            psql.default_dsn()
        assert "restart this process" in str(refused.value)
        assert refused.value.__cause__ is failure
        assert not psql._FIRST_TOUCH.locked()
    socket = OSError("no socket")
    monkeypatch.setattr(psql, "pgserver", _failing(socket))
    with pytest.raises(OSError) as raised:
        psql.default_dsn()
    assert raised.value is socket and isinstance(raised.value, psql.UNREACHABLE)


def test_a_host_without_pgserver_is_told_to_set_database_url(monkeypatch, tmp_path):
    """The image and CI carry no pgserver. With no DATABASE_URL either there is
    no database, even beside a built cluster, and the one useful answer names
    the variable to set: a NoDatabaseError, which /health reports as
    degraded. The cluster here is a PG_VERSION file, so the test reaches the
    missing pgserver on every host."""
    (tmp_path / "PG_VERSION").write_text("16\n")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(psql, "DEFAULT_DB_DIR", str(tmp_path))
    monkeypatch.setattr(psql, "pgserver", None)
    with pytest.raises(psql.NoDatabaseError, match=r"pgserver is not installed.*DATABASE_URL"):
        psql.default_dsn()
    data, code = serve.handle_health()
    assert code == 200 and data["status"] == "degraded" and "DATABASE_URL" in data["error"]


def test_a_probe_with_no_cluster_is_degraded_and_creates_none(monkeypatch, tmp_path):
    """default_dsn resolves and never creates: with no DATABASE_URL and no
    cluster built it raises NoDatabaseError before pgserver is asked, and
    /health answers degraded with the variable to set. Only db_rebuild
    creates a cluster, through psql.boot."""
    cluster = tmp_path / "cluster"

    class NoServer:
        @staticmethod
        def get_server(pgdata):
            raise AssertionError("the resolver asked pgserver for %s" % pgdata)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(psql, "DEFAULT_DB_DIR", str(cluster))
    monkeypatch.setattr(psql, "pgserver", NoServer)
    with pytest.raises(psql.NoDatabaseError, match="db_rebuild"):
        psql.default_dsn()
    data, code = serve.handle_health()
    assert code == 200 and data["status"] == "degraded" and "DATABASE_URL" in data["error"]
    assert not cluster.exists()


def test_the_first_touch_holds_the_lock_and_leaves_the_pid_file_alone(monkeypatch, tmp_path):
    """The first touch asks pgserver once, under the process's own lock, so
    two threads cannot interleave its pid file; an emptied file is pgserver's
    and is reported, never rewritten, and the lock is free afterwards."""
    (tmp_path / "PG_VERSION").write_text("16\n")
    pids = tmp_path / ".handle_pids.json"
    pids.write_text("")
    held = []

    class Server:
        @staticmethod
        def get_server(pgdata):
            held.append(psql._FIRST_TOUCH.locked())
            raise json.JSONDecodeError("Expecting value", "", 0)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(psql, "DEFAULT_DB_DIR", str(tmp_path))
    monkeypatch.setattr(psql, "pgserver", Server)
    with pytest.raises(psql.NoDatabaseError, match=re.escape(
            "did not start (JSONDecodeError - Expecting value")) as refused:
        psql.default_dsn()
    assert isinstance(refused.value.__cause__, json.JSONDecodeError)
    assert held == [True]
    assert pids.read_text() == ""
    assert not psql._FIRST_TOUCH.locked()


def test_readiness_is_the_first_unmet_condition(monkeypatch):
    """One definition of ready for the entrypoint, compose, /health and the
    orchestrator: no tables, then a pending migration, then no heroes."""

    class Rows:
        def __init__(self, n):
            self.n = n

        def fetchone(self):
            return (self.n,)

    class Connection:
        def __init__(self, heroes):
            self.heroes = heroes

        def execute(self, sql, params=None):
            assert "heroes" in sql
            return Rows(self.heroes)

    def board(tables, pending, heroes):
        monkeypatch.setattr(schema, "table_count", lambda cx: tables)
        monkeypatch.setattr(schema, "pending", lambda cx: pending)
        return schema.state(Connection(heroes))

    assert board(0, ["001_initial_schema.sql"], 0) == "empty"
    assert board(35, ["099_future.sql"], 0) == "stale"
    assert board(35, ["099_future.sql"], 54) == "stale"
    assert board(35, [], 0) == "unfilled"
    assert board(35, [], 54) == "current"


def test_the_probe_exits_one_when_the_database_never_answers(monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody@127.0.0.1:9/nowhere")
    monkeypatch.setattr(schema, "CONNECT_TRIES", 2)
    monkeypatch.setattr(schema.time, "sleep", lambda seconds: None)
    assert schema.main() == 1
    captured = capsys.readouterr()
    assert captured.out == "" and "never became reachable" in captured.err
    assert "port 9" in captured.err                    # the last try's own error


def test_the_probe_exits_one_when_there_is_no_database(monkeypatch, capsys):
    """No DATABASE_URL and no cluster is no database to wait for: one line
    on stderr and exit 1 at once, which ends the container under set -e."""
    def nothing():
        raise psql.NoDatabaseError("nothing to point at")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(schema.psql, "default_dsn", nothing)
    assert schema.main() == 1
    captured = capsys.readouterr()
    assert captured.out == "" and "no database: nothing to point at" in captured.err


def test_a_migration_that_fails_is_named_and_the_files_before_it_stay_recorded():
    """Each file commits with its ledger row, the files before the ledger's
    own with it; one that fails is rolled back and named, so the ledger
    never lags the schema and a retry starts at the file that broke."""

    class Connection:
        """Commits what was executed since the last commit or rollback; the
        ledger exists once the migration that makes it has run."""

        def __init__(self):
            self.ledger, self.open, self.recorded = False, [], []

        def cursor(self):
            return contextlib.nullcontext(self)

        def execute(self, sql, params=None):
            if sql == "fails":
                raise psycopg.errors.DuplicateTable('relation "heroes" already exists')
            self.ledger = self.ledger or sql == "makes the ledger"
            if sql.startswith("INSERT INTO schema_migrations"):
                self.open.append(params[0])
            return self

        def fetchone(self):                     # to_regclass('schema_migrations')
            return ("schema_migrations" if self.ledger else None,)

        def commit(self):
            self.recorded += self.open
            self.open = []

        def rollback(self):
            self.open = []

    files = [schema.Migration(path="migrations/%s" % name, sql=sql) for name, sql in (
        ("001_a.sql", "runs"), ("002_b.sql", "makes the ledger"), ("003_c.sql", "runs"),
        ("004_d.sql", "fails"), ("005_e.sql", "runs"))]
    cx = Connection()
    with pytest.raises(schema.SchemaError, match=r'^004_d\.sql: relation "heroes" already exists$'):
        schema.apply(cx, files)
    assert cx.recorded == ["001_a.sql", "002_b.sql", "003_c.sql"] and cx.open == []
