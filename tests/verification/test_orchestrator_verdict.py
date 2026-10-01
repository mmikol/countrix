"""orchestrator.py's verdict on the stack: the three health replies read into
lines, by keys the servers declare, the data layer's state, a layer that
answers with an error, the one board the readiness probe solves, an image
older than the checkout, and the backup container as compose reports it.
The network and docker are stubbed out."""

import json

import orchestrator
from door.mcp import lifecycle
from ui import serve


def test_verdict_reads_the_three_health_replies():
    ok, lines = orchestrator.verdict({
        "data": {"status": "ok", "state": "current", "table_count": 42, "heroes": 53,
                 "pending_migrations": [], "newest_capture": "2026-09-13"},
        "inference": {"status": "ok", "strategies": 38, "heroes": 53},
        "ui": {"heroes": [{}] * 53, "maps": [{}] * 30},
        "board": {"seconds": 1.0, "picks": []}})
    assert ok and lines == ["data layer: 42 tables, 53 heroes, rates captured 2026-09-13",
                            "inference: 38 strategies, 53 heroes, a board in 1.0s",
                            "board: 53 heroes on the roster, 30 maps"]
    ok, lines = orchestrator.verdict({
        "data": {"status": "ok", "state": "current", "table_count": 36, "heroes": 54,
                 "announced": 1, "pending_migrations": [], "newest_capture": "2026-09-14"},
        "inference": {"status": "ok", "strategies": 38, "heroes": 54},
        "ui": {"heroes": [{}] * 54, "maps": [{}] * 30},
        "board": {"seconds": 1.0, "picks": []}})
    assert ok and any("54 heroes (1 announced, not yet playable)" in line for line in lines)
    ok, lines = orchestrator.verdict({"data": {"status": "ok", "state": "stale",
                                               "table_count": 42, "heroes": 53,
                                               "pending_migrations": ["099_future.sql"]},
                                      "inference": {"status": "ok", "strategies": 0},
                                      "ui": None, "board": None})
    assert not ok
    assert [line.split(" (")[0] for line in lines] == [
        "data layer: schema behind the migrations", "data layer: 42 tables, 53 heroes,"
        " rates captured never", "inference: no strategies visible", "board: not answering"]
    assert "(099_future.sql)" in lines[0] and "stale bind mount" in lines[2]


def test_the_verdict_waits_on_the_data_layers_state():
    """Ready is the state the data layer reports, db.psql.schema.state; an
    image older than the checkout reports none, and is not ready either."""
    served = {
        "inference": {"status": "ok", "strategies": 38, "heroes": 54},
        "ui": {"heroes": [{}] * 54, "maps": [{}] * 30},
        "board": {"seconds": 1.0, "picks": []}}
    for state, said in (("empty", "no heroes yet"), ("unfilled", "no heroes yet"),
                        (None, "predates this checkout")):
        data = {"status": "ok", "table_count": 36, "heroes": 0, "pending_migrations": []}
        if state:
            data["state"] = state
        ok, lines = orchestrator.verdict(dict(served, data=data))
        assert not ok and any(said in line for line in lines), state


def test_the_verdict_reads_only_keys_the_servers_declare():
    """The verdict reads each /health reply by key, and every key it reads is
    one the server's own shape declares - the door's lifecycle.DataHealth,
    the board's serve.Health - so a key renamed there fails here, not as a
    verdict that prints 0 tables or rates captured never."""
    assert {"status", "state", "pending_migrations", "table_count", "heroes", "announced",
            "newest_capture", "error"} <= set(lifecycle.DataHealth.__annotations__)
    assert {"status", "strategies", "pending", "heroes", "error"} <= set(
        serve.Health.__annotations__)


def test_health_urls_cover_every_served_layer():
    assert set(orchestrator.URLS) == {"data", "inference", "ui"}


def test_an_error_reply_reports_the_layers_own_message(monkeypatch):
    """A layer that answers with an error status is answering: get_json reads
    the body, and the verdict prints the layer's own words."""
    import io
    import urllib.error
    import urllib.request
    body = {}

    def failing(url, timeout=0):
        raise urllib.error.HTTPError(url, 500, "x", {}, io.BytesIO(body["raw"]))
    monkeypatch.setattr(urllib.request, "urlopen", failing)
    body["raw"] = json.dumps({"status": "degraded", "error": "no strategies in /x"}).encode()
    data = orchestrator.get_json("http://localhost:8020/health")
    assert data == {"status": "degraded", "error": "no strategies in /x"}
    body["raw"] = b"<html>a proxy's page</html>"
    assert orchestrator.get_json("http://localhost:8020/health") == {
        "status": "error", "error": "HTTP 500"}
    ok, lines = orchestrator.verdict({"data": data, "inference": None, "board": None,
                                      "ui": {"error": "TypeError: boom"}})
    assert not ok and "data layer: no strategies in /x" in lines
    assert "board: TypeError: boom" in lines


def test_readiness_solves_one_board_on_the_board(monkeypatch):
    """A six back from the probe means ready, anything else means not."""
    calls = []
    six = {"blue": {"blue": ["D.Va", "Winston", "Cassidy", "Genji", "Ana", "Brigitte"]}}
    monkeypatch.setattr(orchestrator, "get_json", lambda url, timeout=10: calls.append(url) or six)
    probe = orchestrator.probe()
    assert probe["picks"] == six["blue"]["blue"] and probe["seconds"] >= 0
    assert calls == [orchestrator.PROBE]
    monkeypatch.setattr(orchestrator, "get_json", lambda url, timeout=10: {"error": "died"})
    assert orchestrator.probe() is None
    inf = {"status": "ok", "strategies": 300, "heroes": 54}
    served = {
        "data": {"status": "ok", "state": "current", "table_count": 36, "heroes": 54},
        "inference": inf, "ui": {"heroes": [{}] * 54, "maps": [{}] * 30}}
    ok, lines = orchestrator.verdict(dict(served, board={"seconds": 2.4, "picks": six}))
    assert ok and any(line.endswith("a board in 2.4s") for line in lines)
    ok, lines = orchestrator.verdict(dict(served, board=None))
    assert not ok and any("a board did not solve" in line for line in lines)


def test_a_playbook_the_image_refuses_and_the_checkout_loads_names_the_old_image():
    """The board's container reads the bind-mounted playbook with the image's
    code: a file that code refuses while this checkout loads it means the
    image predates the checkout, and the verdict says `up` rebuilds it. A
    file the checkout refuses too is the file's fault, and a stale mount is
    the mount's: neither gets the line, and the mount gets its fix."""
    refused = {
        "status": "degraded", "heroes": 54,
        "error": "heal-rate: a heuristic weighs a metric; require/bonus/penalty belong to a"
                 " constraint"}
    served = {
        "data": {"status": "ok", "state": "current", "table_count": 36, "heroes": 54},
        "inference": refused, "ui": {"heroes": [{}] * 54, "maps": [{}] * 30}, "board": None}
    ok, lines = orchestrator.verdict(dict(served, playbook=None))
    assert not ok and lines[1] == "inference: " + refused["error"]
    assert "the image's code predates it - `orchestrator.py up` rebuilds the image" in lines[2]
    for host in ({"playbook": "heal-rate: bad"}, {}):
        ok, lines = orchestrator.verdict(dict(served, **host))
        assert not ok and not any("predates" in line for line in lines)
    stale = {"status": "degraded", "error": "no strategies in /app/inference/strategies"}
    ok, lines = orchestrator.verdict(dict(served, inference=stale, playbook=None))
    assert not any("predates" in line for line in lines)
    assert lines[2] == "inference: " + orchestrator.RECREATE     # the fix, printed


def test_the_verdict_warns_when_no_nightly_dump_is_being_taken():
    """The backup container not running, or unhealthy once its newest dump is
    26 hours old, is a warning line after the layers'; the board works
    without it, so the stack stays ready. Docker not answering says
    nothing."""
    served = {
        "data": {"status": "ok", "state": "current", "table_count": 36, "heroes": 54},
        "inference": {"status": "ok", "strategies": 38, "heroes": 54},
        "ui": {"heroes": [{}] * 54, "maps": [{}] * 30}, "board": {"seconds": 1.0, "picks": []}}
    for backup, said in (({"state": "running", "health": "healthy"}, None),
                         (None, None),
                         ({"state": "running", "health": "unhealthy"},
                          "backup: unhealthy - the newest dump in backups/ is over 26 hours old"),
                         ({"state": "exited", "health": ""},
                          "backup: exited - no nightly dump is being taken"),
                         ({"state": "", "health": ""},
                          "backup: no container - no nightly dump is being taken")):
        ok, lines = orchestrator.verdict(dict(served, backup=backup))
        assert ok and len(lines) == (3 if said is None else 4), backup
        assert said is None or lines[-1].startswith(said), backup


def test_the_backup_service_is_read_from_compose_in_either_format(monkeypatch):
    """`docker compose ps --format json` prints an object a line since 2.21
    and one array before it; either reads as the container's state and
    health, and docker failing or printing nothing JSON reads as None."""
    import subprocess
    printed = {}

    def ps(argv, **kw):
        assert argv[:3] == ["docker", "compose", "ps"] and argv[-1] == "backup"
        if printed.get("raise"):
            raise FileNotFoundError("docker")
        return subprocess.CompletedProcess(argv, printed.get("code", 0), printed["out"], "")
    monkeypatch.setattr(subprocess, "run", ps)
    row = {"Service": "backup", "State": "running", "Health": "unhealthy"}
    for out in (json.dumps(row) + "\n", json.dumps([row])):
        printed["out"] = out
        assert orchestrator.service("backup") == {"state": "running", "health": "unhealthy"}
    printed["out"] = ""
    assert orchestrator.service("backup") == {"state": "", "health": ""}
    printed["out"] = "not json"
    assert orchestrator.service("backup") is None
    printed.update(out="", code=1)
    assert orchestrator.service("backup") is None
    printed["raise"] = True
    assert orchestrator.service("backup") is None
