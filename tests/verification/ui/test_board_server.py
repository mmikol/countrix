"""The board over HTTP: the same handlers the unit tests call, served."""

import http.client
import json
import re
import threading
import urllib.error
import urllib.request
from urllib.parse import urlparse

import pytest

from db import web
from ui import board

NOWHERE = "postgresql://nobody@127.0.0.1:9/nowhere"


@pytest.fixture()
def served():
    server = web.LocalServer(("127.0.0.1", 0), board.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:%d" % server.server_address[1]
    server.shutdown()


def get(url, headers=None):
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, response.headers.get("Content-Type", ""), response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.headers.get("Content-Type", ""), error.read()


def test_the_board_writes_nothing(served):
    """The board answers GET alone: a POST is a 501 once the host guard lets
    it through, and a 403 from a foreign origin before that."""
    address = urlparse(served)
    for headers, status in (({}, 501), ({"Origin": "http://evil.example"}, 403)):
        connection = http.client.HTTPConnection(address.hostname, address.port, timeout=60)
        connection.request("POST", "/api/board", body=b"{}", headers={
            "Content-Type": "application/json", **headers})
        assert connection.getresponse().status == status, headers
        connection.close()


def test_the_board_listens_where_its_flags_say():
    args = board.command_line([])
    assert (args.host, args.port) == ("127.0.0.1", 8017)
    # the names it answers to beyond the local ones: none unless given
    assert args.allow_host == []
    args = board.command_line(["--host", "0.0.0.0", "--port", "9"])
    assert (args.host, args.port) == ("0.0.0.0", 9)
    assert board.command_line(["--allow-host", "x", "--allow-host", "y"]).allow_host == ["x", "y"]


def test_a_foreign_host_or_origin_is_refused_on_every_route(served, monkeypatch):
    """The guard runs before any route: a page rebound to the board's address
    sends its GETs under its own host name and no Origin, and a cross-site
    request carries a foreign Origin - both are 403, reads included."""
    monkeypatch.setattr(board.psql, "default_dsn", lambda: NOWHERE)
    for path in ("/", "/api/strategies"):
        assert get(served + path, {"Host": "evil.example"})[0] == 403, path
        assert get(served + path, {"Origin": "http://evil.example"})[0] == 403, path
        assert get(served + path, {"Host": "localhost:8017"})[0] == 200, path


def test_the_page_the_statics_the_math_and_the_strategies_need_no_database(
        served, monkeypatch, tmp_path):
    monkeypatch.setattr(board.psql, "default_dsn", lambda: NOWHERE)
    code, ctype, body = get(served + "/")
    assert code == 200 and "text/html" in ctype and b"Countrix" in body
    code, ctype, body = get(served + "/static/board.css")
    assert code == 200 and "text/css" in ctype and b".tile" in body
    code, ctype, body = get(served + "/static/bebas-neue.woff2")
    assert code == 200 and ctype == "font/woff2" and body.startswith(b"wOF2")
    assert get(served + "/static/nope.txt")[0] == 404
    assert get(served + "/static/OFL.txt")[0] == 404        # the licence ships, unserved
    code, _, body = get(served + "/math")
    assert code == 200 and b"The Counter Utility Matrix" in body
    code, _, body = get(served + "/api/strategies")
    assert code == 200 and json.loads(body)["strategies"]
    code, _, body = get(served + "/health")      # the engine's, for the container's healthcheck
    health = json.loads(body)
    assert code == 200 and health["status"] == "degraded" and health["strategies"]
    assert "heroes" not in health and health["error"]
    with monkeypatch.context() as broken:                 # a playbook that does not load
        broken.setenv("COUNTRIX_STRATEGIES", str(tmp_path))
        code, _, body = get(served + "/api/strategies")
        assert code == 500 and json.loads(body)["error"].startswith(
            "CatalogError: no strategies in")
        # the health stays 200 and says why, in the catalog's words, which
        # orchestrator.py prints
        code, _, body = get(served + "/health")
        health = json.loads(body)
        assert code == 200 and health["status"] == "degraded" and "strategies" not in health
        assert "no strategies in" in health["error"]
    assert get(served + "/nothing")[0] == 404
    # the database is not there. A JSON route answers JSON
    code, ctype, body = get(served + "/api/roster")
    error = json.loads(body)["error"]
    assert code == 500 and "application/json" in ctype and error
    assert "Traceback" not in error                       # the stack goes to stderr only
    code, ctype, body = get(served + "/api/nothing")
    assert code == 404 and "application/json" in ctype and json.loads(body)["error"]


def test_a_board_leaves_a_line_on_stderr_and_a_static_file_none(served, monkeypatch, capsys):
    """The solves are logged with their status and seconds, so the container's
    log says what the page asked and when; the page and its files are quiet
    unless they fail."""
    monkeypatch.setattr(board, "api_board", lambda query: ({}, 200))
    capsys.readouterr()
    assert get(served + "/static/board.css")[0] == 200 and get(served + "/")[0] == 200
    assert capsys.readouterr().err == ""
    assert get(served + "/api/board?map=Ilios")[0] == 200
    assert re.search(r'"GET /api/board\?map=Ilios HTTP/1.1" 200 \d+\.\d\ds$',
                     capsys.readouterr().err.rstrip())
    assert get(served + "/static/nope.js")[0] == 404
    assert '"GET /static/nope.js HTTP/1.1" 404' in capsys.readouterr().err


@pytest.mark.invariant
def test_the_json_endpoints_answer_over_http(served, monkeypatch, dsn):
    monkeypatch.setattr(board.psql, "default_dsn", lambda: dsn)
    code, _, body = get(served + "/api/roster")
    assert code == 200 and len(json.loads(body)["heroes"]) > 50
    code, _, body = get(served + "/api/facts?map=Ilios&blue=Ana")
    assert code == 200 and json.loads(body)["count"] > 0
    code, _, body = get(served + "/api/board?map=Ilios&blue=Ana&bans=Widowmaker")
    assert code == 200 and json.loads(body)["blue"]["blue"] and json.loads(body)["plan"]
    code, _, body = get(served + "/api/board?blue=Nobody")
    assert code == 400 and "error" in json.loads(body)
