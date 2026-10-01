"""The door over Streamable HTTP, the data-layer container's: the real
server spawned on a free port, and an in-process HttpServer for the guards -
the origin check, the bearer token, the JSON label, the body cap, the rate
limit per client address, and /health's 500 for a status that raises - and
for the one message it handles at a time and the line each tool call logs."""

import http.client
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

import pytest

from db import ROOT
from door.mcp import tools
from door.mcp.http import HttpServer
from door.mcp.server import Server


@pytest.fixture(scope="module", autouse=True)
def no_ambient_token():
    """A door given no token reads COUNTRIX_MCP_TOKEN, which a shell may
    export for .mcp.json: cleared for the module, so the spawned door and
    every HttpServer(token=None) here ask for none. An autouse fixture is
    set up before http_server, which shares its scope."""
    with pytest.MonkeyPatch.context() as patch:
        patch.delenv("COUNTRIX_MCP_TOKEN", raising=False)
        yield


@pytest.fixture(scope="module")
def http_server(tmp_path_factory):
    """The server over HTTP on a free port, once it answers /health. A child
    that exits first, or never answers, fails the fixture with its own
    stderr, which goes to a file: a pipe nobody reads fills and blocks it."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    base = "http://127.0.0.1:%d" % port
    log = tmp_path_factory.mktemp("mcp_http") / "stderr.log"
    with log.open("wb") as err:
        proc = subprocess.Popen(
            [sys.executable, "-m", "door.mcp", "--http", "--port", str(port)],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=err,
            env=dict(os.environ, DATABASE_URL="postgresql://127.0.0.1:1/none"))
        try:
            # DATABASE_URL points nowhere: /health answers degraded at once and starts no cluster
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    pytest.fail("the mcp http server exited with %d before answering /health:\n%s"
                                % (proc.returncode,
                                   log.read_text(encoding="utf-8", errors="replace")))
                try:
                    with urllib.request.urlopen(base + "/health", timeout=2):
                        break
                except OSError:
                    time.sleep(0.2)
            else:
                pytest.fail("the mcp http server did not answer /health within 30 s:\n%s"
                            % log.read_text(encoding="utf-8", errors="replace"))
            yield base
        finally:
            proc.terminate()
            proc.wait(timeout=10)


def _post(base, payload, headers=None):
    request = urllib.request.Request(
        base + "/mcp", data=json.dumps(payload).encode("utf-8"),
        headers=dict({"Content-Type": "application/json",
                      "Accept": "application/json, text/event-stream"}, **(headers or {})))
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
            return response.status, json.loads(body) if body else None
    except urllib.error.HTTPError as error:
        body = error.read()
        return error.code, json.loads(body) if body else None


def test_http_transport_initializes_lists_and_calls(http_server):
    status, reply = _post(http_server, {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                   "clientInfo": {"name": "test", "version": "0"}}})
    assert status == 200 and reply["result"]["serverInfo"]["name"] == "countrix"
    status, reply = _post(http_server, {"jsonrpc": "2.0",
                                        "method": "notifications/initialized"})
    assert status == 202 and reply is None
    status, reply = _post(http_server, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert status == 200 and any(t["name"] == "infer" for t in reply["result"]["tools"])
    status, reply = _post(http_server, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                        "params": {"name": "metrics", "arguments": {}}})
    assert status == 200 and "team.coverage_share" in reply["result"]["content"][0]["text"]


def test_http_transport_guards_get_origin_and_health(http_server):
    with pytest.raises(urllib.error.HTTPError) as blocked:
        urllib.request.urlopen(http_server + "/mcp", timeout=10)
    assert blocked.value.code == 405
    status, _ = _post(http_server, {"jsonrpc": "2.0", "id": 9, "method": "ping"},
                      {"Origin": "https://evil.example"})
    assert status == 403
    health = json.load(urllib.request.urlopen(http_server + "/health", timeout=10))
    assert health["status"] == "degraded" and health["error"]
    # a rebound page sends no Origin on a GET, but it names its own host
    with pytest.raises(urllib.error.HTTPError) as foreign:
        urllib.request.urlopen(urllib.request.Request(
            http_server + "/health", headers={"Host": "evil.example"}), timeout=10)
    assert foreign.value.code == 403


def _http_server(token=None, rate_limit=120, status=lambda: {"status": "ok"}):
    ctx = tools.Context(dsn="postgresql://nowhere")
    mcp = Server(tools.REGISTRY.bind(ctx))
    httpd = HttpServer(("127.0.0.1", 0), mcp, status, token=token,
                       rate_limit=rate_limit)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, "http://127.0.0.1:%d" % httpd.server_address[1]


def _knock(url, body, headers=None):
    data = body if isinstance(body, bytes) else json.dumps(body).encode()
    request = urllib.request.Request(url + "/mcp", data=data, headers=dict(
        {"Content-Type": "application/json"}, **(headers or {})))
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"null")


def test_the_door_requires_its_token_when_one_is_set():
    httpd, url = _http_server(token="s3cret")
    call = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "metrics", "arguments": {}}}
    assert _knock(url, call)[0] == 401
    assert _knock(url, call, {"Authorization": "Bearer wrong"})[0] == 401
    code, reply = _knock(url, call, {"Authorization": "Bearer s3cret"})
    assert code == 200 and reply["result"]["isError"] is False
    httpd.shutdown()


def test_each_tool_call_leaves_a_line_naming_the_tool_and_the_client(capsys):
    """A tool call over HTTP is logged on stderr before it runs - the
    client's address, the time and the tool's name - so a rebuild through
    the door leaves a record; a ping, no tool call, leaves none."""
    httpd, url = _http_server()
    assert _knock(url, {"jsonrpc": "2.0", "id": 1, "method": "ping"})[0] == 200
    call = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "metrics", "arguments": {}}}
    assert _knock(url, call)[0] == 200
    httpd.shutdown()
    [line] = capsys.readouterr().err.splitlines()
    assert line.startswith("127.0.0.1 - - [") and line.endswith("] tools/call 'metrics'")


def test_the_door_refuses_huge_bodies_and_rate_limits_a_client():
    httpd, url = _http_server(rate_limit=3)
    call = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "metrics", "arguments": {}}}
    assert _knock(url, b"x" * ((1 << 20) + 1))[0] == 413
    assert [_knock(url, call)[0] for _ in range(4)] == [200, 200, 200, 429]
    # a batch is no message the door answers: one INVALID_REQUEST, no call run
    assert _knock(url, [call, call]) == (200, {
        "jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "expected an object"}})
    httpd.shutdown()


def test_a_missing_content_length_is_refused_as_required():
    """A POST with no Content-Length, or one that is not a number, is told so
    - not answered as bad JSON after reading an empty body. urllib always sets
    the header, so the requests are built by hand."""
    httpd, url = _http_server()
    address = urlparse(url)
    for length in (None, "abc"):
        connection = http.client.HTTPConnection(address.hostname, address.port, timeout=10)
        connection.putrequest("POST", "/mcp")
        connection.putheader("Content-Type", "application/json")
        if length is not None:
            connection.putheader("Content-Length", length)
        connection.endheaders()
        response = connection.getresponse()
        assert response.status == 400
        assert "Content-Length" in json.loads(response.read())["error"]
        connection.close()
    httpd.shutdown()


def test_a_post_that_does_not_claim_json_is_refused():
    """A body not labelled application/json is 415 before it is read: the
    door reads nothing but JSON-RPC."""
    httpd, url = _http_server()
    assert _knock(url, {"jsonrpc": "2.0", "id": 1, "method": "ping"},
                  {"Content-Type": "text/plain"}) == (415, {"error": "a JSON body is required"})
    httpd.shutdown()


def test_the_door_handles_one_message_at_a_time():
    """Each request runs on a thread of its own, but the messages are handled
    one after another, as over stdio: two playbook writes at once would lose
    one edit."""
    httpd, url = _http_server()
    events = []
    handle = httpd.mcp.handle

    def slow(message):
        events.append("in")
        time.sleep(0.1)
        events.append("out")
        return handle(message)
    httpd.mcp.handle = slow
    message = {"jsonrpc": "2.0", "method": "ping"}
    pings = [threading.Thread(target=_knock, args=(url, dict(message, id=n))) for n in range(3)]
    for ping in pings:
        ping.start()
    for ping in pings:
        ping.join()
    assert events == ["in", "out"] * 3
    httpd.shutdown()


def test_health_answers_a_status_that_raises_with_a_500_that_names_it():
    """/health is a request boundary like every other route: a bug in the
    status read is a 500 with its type and message, not a dropped connection."""
    def broken():
        raise RuntimeError("a bug in read_status")
    httpd, url = _http_server(status=broken)
    with pytest.raises(urllib.error.HTTPError) as failed:
        urllib.request.urlopen(url + "/health", timeout=10)
    assert failed.value.code == 500
    assert json.loads(failed.value.read()) == {"error": "RuntimeError: a bug in read_status"}
    httpd.shutdown()
