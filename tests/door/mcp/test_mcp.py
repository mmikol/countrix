"""The door speaks the protocol: the real server spawned over
stdio, and the server's dispatch - the schema check every call passes, a
refusal answered as the caller's error, a fault as the server's. None of it
needs a database (tools/list and metrics read nothing). This module holds
the tool set a session sees.
The HTTP door, the tools themselves, the registry and the entry point have
modules of their own (test_mcp_http, test_mcp_tools, test_mcp_registry,
test_mcp_entry)."""

import io
import json
import subprocess
import sys

import pytest

from db import ROOT, Refusal
from door.mcp import stdio, tools
from door.mcp.schema import Tool, tool_schema
from door.mcp.server import Server
from inference import tune


def _talk(messages):
    proc = subprocess.Popen([sys.executable, "-m", "door.mcp"], cwd=ROOT,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    out, err = proc.communicate("\n".join(json.dumps(m) for m in messages) + "\n",
                                timeout=60)
    assert proc.returncode == 0, err
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def test_initialize_then_list_tools_over_stdio():
    replies = _talk([
        {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "test", "version": "0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "ping"},
    ])
    assert replies[0]["id"] == 1
    assert replies[0]["result"]["protocolVersion"] == "2025-06-18"
    assert replies[0]["result"]["serverInfo"]["name"] == "countrix"
    names = {t["name"] for t in replies[1]["result"]["tools"]}
    assert {"pull_heroes", "pull_rates", "pull_seasons", "pull_synergies", "sync_all",
            "db_rebuild", "db_migrate", "query",
            "facts", "infer", "board", "strategies", "load_authored",
            "tune", "tuning_log", "metrics",
            "add_strategy", "infer_strategy", "db_docs"} <= names
    assert len(names) == len(tools.REGISTRY)      # every registered tool is served
    for t in replies[1]["result"]["tools"]:
        assert t["inputSchema"]["type"] == "object" and t["description"]
    assert replies[2] == {"jsonrpc": "2.0", "id": 3, "result": {}}


def test_tools_call_without_a_database_and_unknown_method():
    replies = _talk([
        {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "metrics", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 2, "method": "no/such/method"},
        {"jsonrpc": "2.0", "id": 3, "method": "resources/list"},
    ])
    assert "team.coverage_share" in replies[0]["result"]["content"][0]["text"]
    assert replies[0]["result"]["isError"] is False
    # the door serves tools alone: resources/list is a method it does not know
    assert [r["error"]["code"] for r in replies[1:]] == [-32601, -32601]


def test_bad_json_is_a_parse_error_not_a_crash():
    proc = subprocess.Popen([sys.executable, "-m", "door.mcp"], cwd=ROOT,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    out, err = proc.communicate("{not json\n" + json.dumps(
        {"jsonrpc": "2.0", "id": 9, "method": "ping"}) + "\n", timeout=60)
    assert proc.returncode == 0, err          # a server that died says why
    lines = [json.loads(line) for line in out.splitlines() if line.strip()]
    assert lines[0]["error"]["code"] == -32700
    assert lines[1]["id"] == 9


def test_a_batch_is_a_request_of_the_wrong_shape_and_runs_no_tool():
    """The protocol the door speaks has no batches: a JSON array on one line
    is answered with one INVALID_REQUEST, and no call in it runs."""
    ran = []
    server = Server([Tool("t", "d", tool_schema(), lambda **kw: ran.append(kw) or ("ok", {}))])
    out = io.StringIO()
    call = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "t", "arguments": {}}}
    stdio.serve(server, [json.dumps([call, call])], out)
    [answered] = [json.loads(line) for line in out.getvalue().splitlines()]
    assert answered["error"] == {"code": -32600, "message": "expected an object"}
    assert ran == []


def test_tool_refuses_unknown_and_missing_arguments():
    tool = Tool("t", "d", tool_schema({
        "a": {"type": "string"}, "n": {"type": "integer"}, "x": {"type": "number"},
        "names": {"type": "array", "items": {"type": "string"}},
        "side": {"type": "string", "enum": ["attack", "defense"]}, "any": {},
        "expr": {"type": ["string", "number"]}}, ["a"]),
        lambda **kw: ("ok", kw))
    with pytest.raises(Refusal, match="unknown argument"):
        tool({"a": "x", "b": 1})
    with pytest.raises(Refusal, match="missing"):
        tool({})
    assert tool({"a": "x"}) == ("ok", {"a": "x"})
    # a value is checked as well as a name: the type, an array's items, the enum
    for arguments, named, wanted in (
            ({"a": 5}, "'a'", "must be string"),
            ({"a": None}, "'a'", "must be string"),
            ({"a": "x", "n": True}, "'n'", "must be integer"),      # a bool is no integer
            ({"a": "x", "n": 1.5}, "'n'", "must be integer"),
            ({"a": "x", "x": False}, "'x'", "must be number"),
            ({"a": "x", "names": ["Ana", 3]}, "'names'", "must be array of string"),
            ({"a": "x", "side": "sideways"}, "'side'", "must be one of 'attack', 'defense'"),
            ({"a": "x", "expr": True}, "'expr'", "must be string or number")):
        with pytest.raises(Refusal) as refused:
            tool(arguments)
        assert str(refused.value) == "t: %s %s" % (named, wanted)
    passing = {"a": "x", "n": 2, "x": 2, "names": ("Ana",), "side": "attack", "any": None}
    assert tool(passing) == ("ok", passing)
    for either in (2, "x"):                       # a list of types admits any of them
        assert tool({"a": "x", "expr": either}) == ("ok", {"a": "x", "expr": either})


def test_server_reports_a_refused_tool_as_is_error():
    """Every Refusal is the caller's error: the door answers it isError - a
    TuneError as much as a Refusal raised plainly."""
    def refuse(**kw):
        raise Refusal("no")

    def refuse_a_tune(**kw):
        raise tune.TuneError("no strategy 'x'")
    empty = tool_schema()
    server = Server([Tool("t", "d", empty, refuse), Tool("tuned", "d", empty, refuse_a_tune)])
    for name, said in (("t", "no"), ("tuned", "no strategy 'x'")):
        reply = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                               "params": {"name": name, "arguments": {}}})
        assert reply["result"]["isError"] is True
        assert reply["result"]["content"][0]["text"] == said


def test_a_fault_inside_a_tool_is_internal_and_logged_not_a_bad_parameter():
    """INVALID_PARAMS is for what the request got wrong. A KeyError raised deep
    inside a tool is the server's own fault: it reads as INTERNAL and leaves a
    traceback in the log."""
    def crash(**kw):
        raise KeyError("a lookup inside the tool")
    logged = []
    server = Server([Tool("t", "d", tool_schema(), crash)], log=logged.append)
    call = lambda method, params: server.handle(                      # noqa: E731
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    fault = call("tools/call", {"name": "t", "arguments": {}})["error"]
    assert fault["code"] == -32603 and "KeyError" in fault["message"]
    assert logged and "Traceback" in logged[0]
    assert call("tools/call", {})["error"] == {
        "code": -32602, "message": "missing parameter 'name'"}
    assert call("tools/call", {"name": "nope"})["error"] == {
        "code": -32602, "message": "no tool named 'nope'"}
    assert call("tools/call", {"name": "t", "arguments": [1]})["error"] == {
        "code": -32602, "message": "arguments must be an object"}


def test_a_request_of_the_wrong_shape_is_the_callers_error_and_logs_nothing():
    """A method that is not a string, params that are not an object, a tool
    name that is not a string: each is the request's error, never a fault
    with a traceback in the log. A notification still gets no reply."""
    logged = []
    server = Server([], log=logged.append)

    def error(message):
        return server.handle(dict({"jsonrpc": "2.0", "id": 1}, **message))["error"]
    assert error({"method": 5}) == {"code": -32600, "message": "method must be a string"}
    assert error({"method": "tools/call", "params": [1]}) == {
        "code": -32602, "message": "params must be an object"}
    assert error({"method": "tools/call", "params": {"name": ["t"]}}) == {
        "code": -32602, "message": "no tool named ['t']"}
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized",
                          "params": [1]}) is None
    assert logged == []


def test_a_broken_playbook_is_a_server_fault_at_the_door(tmp_path, monkeypatch):
    """A playbook that does not load is the operator's to fix, not the caller's:
    a tool that reads it answers INTERNAL with the catalog's own message and
    logs the traceback."""
    empty = tmp_path / "playbook"
    empty.mkdir()
    monkeypatch.setenv("COUNTRIX_STRATEGIES", str(empty))
    logged = []
    server = Server(tools.REGISTRY.bind(tools.Context(dsn="postgresql://nowhere")),
                    log=logged.append)
    fault = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": "strategies", "arguments": {}}})["error"]
    assert fault["code"] == -32603
    assert fault["message"].startswith("CatalogError: no strategies in")
    assert logged and "Traceback" in logged[0]

