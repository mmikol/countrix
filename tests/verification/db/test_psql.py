"""Where the database is, db/psql/__init__.py: the embedded cluster as
pgserver starts it, and every way that start fails reported as the database
out of reach. pgserver is stubbed, so no cluster starts."""

import re
import subprocess

import pytest

from db import psql


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
