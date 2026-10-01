"""The door's entry point and in-process call: `python -m door.mcp list`,
`call` and `--http`, the data container's /health, and ctx.call - the
refresher's, the shell's and the board's path - validated like a call
through either door."""

import pytest

from db import Refusal, psql
from door.mcp import http, lifecycle, tools
from door.mcp.__main__ import _status, main


def test_the_entry_point_lists_tools_and_refuses_nonsense(capsys):
    """Usage is 2, a refused call 1 with the reason on stderr."""
    assert main(["list"]) == 0
    out = capsys.readouterr().out
    assert "db_status" in out and "infer" in out
    assert main(["bogus"]) == 2
    assert main(["call", "no_such_tool"]) == 1
    assert "error: no tool named 'no_such_tool'" in capsys.readouterr().err
    assert main(["call", "strategies", '{"bogus": 1}']) == 1
    assert "unknown argument(s) bogus" in capsys.readouterr().err
    assert main(["call", "metrics", "{not json"]) == 2
    assert main(["call", "metrics", "[1]"]) == 2
    assert "python -m door.mcp call" in capsys.readouterr().err


def test_the_http_mode_takes_the_flags_the_board_takes(monkeypatch, capsys):
    """--host, --port and a repeated --allow-host, as the board spells
    them; the old HOST:PORT positional is a usage error like a port that is
    not a number."""
    served = []
    monkeypatch.setattr(http, "serve", lambda server, host, port, status, allowed_hosts=(): (
        served.append((host, port, list(allowed_hosts)))))
    assert main(["--http"]) == 0
    assert main(["--http", "--host", "0.0.0.0", "--port", "9",
                 "--allow-host", "x", "--allow-host", "y"]) == 0
    assert served == [("127.0.0.1", 8020, []), ("0.0.0.0", 9, ["x", "y"])]
    for argv in (["--http", "--port", "x"], ["--http", "127.0.0.1:8020"]):
        with pytest.raises(SystemExit) as usage:
            main(argv)
        assert usage.value.code == 2
    assert "python -m door.mcp --http" in capsys.readouterr().err


@pytest.mark.invariant
def test_the_entry_point_calls_a_tool(capsys, dsn, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", dsn)
    assert main(["call", "db_status"]) == 0
    assert "tables" in capsys.readouterr().out


def test_health_is_degraded_when_the_database_is_out_of_reach_and_crashes_otherwise(
        monkeypatch):
    """The data container's /health answers degraded for every way the database
    can be out of reach, and nothing else: a bug in the read still surfaces."""
    status = _status(tools.Context(dsn="postgresql://nobody@127.0.0.1:9/nowhere"))
    reply = status()
    assert reply["status"] == "degraded" and reply["error"]

    def no_database():
        raise psql.NoDatabaseError("no DATABASE_URL and no embedded cluster")
    monkeypatch.setattr(psql, "default_dsn", no_database)
    reply = _status(tools.Context())()
    assert reply["status"] == "degraded" and "no embedded cluster" in reply["error"]

    def broken(ctx):
        raise RuntimeError("a bug in read_status")
    monkeypatch.setattr(lifecycle, "read_status", broken)
    with pytest.raises(RuntimeError, match="a bug"):
        status()


def test_health_carries_every_key_data_health_declares_but_the_error(monkeypatch):
    """An ok /health is read_status reshaped into DataHealth: the state
    compose's healthcheck waits on, and the counts orchestrator.py prints."""
    monkeypatch.setattr(lifecycle, "read_status", lambda ctx: lifecycle.DbStatus(
        dsn="postgresql://db/overwatch", state="current", table_count=33,
        counts={"heroes": 50, "announced": 1}, snapshots=[], newest_capture="2026-09-30",
        pending_migrations=[]))
    reply = _status(tools.Context(dsn="postgresql://nowhere"))()
    assert reply == {"status": "ok", "state": "current", "table_count": 33,
                     "pending_migrations": [], "heroes": 50, "announced": 1,
                     "newest_capture": "2026-09-30"}
    assert set(reply) == set(lifecycle.DataHealth.__annotations__) - {"error"}


def test_an_in_process_call_is_validated_against_the_tools_schema():
    """The shell, the refresher and the board call through the same wrapper
    as either door, so a call the schema refuses never reaches the tool."""
    ctx = tools.Context(dsn="postgresql://nowhere")
    with pytest.raises(Refusal, match="strategies: unknown argument"):
        ctx.call("strategies", bogus=1)
    with pytest.raises(Refusal, match="reach: 'hero' must be string"):
        ctx.call("reach", hero=5)


def test_a_tool_argument_named_name_reaches_the_tool():
    """ctx.call takes the tool's name positionally, so add_strategy's own `name`
    argument is not swallowed by the call - it raised TypeError once."""
    with pytest.raises(tools.NoSuchToolError, match="no tool named 'no_such_tool'"):
        tools.Context(dsn="postgresql://nobody@127.0.0.1:9/x").call(
            "no_such_tool", name="Players play optimally")
