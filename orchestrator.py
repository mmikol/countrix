"""The orchestrator: the Docker stack, from a shell or a Claude Code session.

    python orchestrator.py            up, when no verb is named
    python orchestrator.py up         build the image, start the containers, wait -
                                      the data container builds the database when
                                      it is empty and migrates it when it is
                                      stale - then the verdict
    python orchestrator.py status     what is running, how fresh the data is, the URLs
    python orchestrator.py down       stop everything (the database volume stays)

It imports the standard library, db's ROOT, db.web's JSON reader and the
catalog, to check the playbook before the stack starts; run it with
.venv/bin/python, since the catalog loads psycopg. Exit code 0 means
everything answered.
"""

import json
import os
import subprocess  # nosec B404  # docker compose, argv lists, never a shell
import sys
import time
from collections.abc import Callable
from typing import Any, NamedTuple, NotRequired, TypedDict

from db import ROOT, web
from inference import catalog
from inference.strategy import CatalogError

# the compose stack's ports on this host (compose.yaml)
DATA = "http://localhost:8020"
BOARD = "http://localhost:8017"
# the inference layer's health is the board's: the ui container runs the engine
URLS = {"data": DATA + "/health", "inference": BOARD + "/health", "ui": BOARD + "/api/roster"}
MCP_URL = DATA + "/mcp"
# the nightly dumps, bind-mounted into the backup service (compose.yaml)
BACKUPS = "backups"
BACKUP_SERVICE = "backup"
# one board solved on the board before the stack is called ready: only the
# container (its memory limit in compose.yaml, a read-only root) shows
# whether this playbook fits its memory and time
PROBE = BOARD + "/api/board?map=King%27s%20Row&red=Zarya&red=Pharah&side=attack"

MINUTE = 60                         # seconds
# the fix for a bind mount gone stale, which the verdict prints
RECREATE = "a stale bind mount - run `docker compose up -d --force-recreate`"


def sh(*args: str, timeout: float) -> None:
    """Run one command; a failure or an overrun past `timeout` seconds stops
    the run."""
    try:
        result = subprocess.run(  # nosec B603  # argv lists built here from literals, never a shell
            list(args), timeout=timeout)
    except subprocess.TimeoutExpired as error:
        raise SystemExit("error: %s did not finish within %d minutes"
                         % (" ".join(args), timeout // MINUTE)) from error
    if result.returncode:
        raise SystemExit("error: %s exited %d" % (" ".join(args), result.returncode))


def get_json(url: str, timeout: float = 10) -> dict[str, Any] | None:
    """The JSON object a URL is answered with, an error status's
    body included, or None when nothing answers with one. An error status
    whose body is not a JSON object reads as {"status": "error", "error":
    "HTTP <code>"}."""
    try:
        answer = web.read_json(url, timeout)
    except OSError:
        return None
    if isinstance(answer.body, dict):
        return answer.body
    if 200 <= answer.status < 300:
        return None
    return {"status": "error", "error": "HTTP %d" % answer.status}


def wait_for(url: str, seconds: float, what: str) -> dict[str, Any]:
    """The first JSON the URL answers, an error included, polled until
    `seconds` pass; then the run stops."""
    started = time.time()
    while time.time() - started < seconds:
        data = get_json(url)
        if data is not None:
            return data
        time.sleep(3)
    raise SystemExit("error: %s did not answer at %s within %ds" % (what, url, seconds))


class Probe(TypedDict):
    """One board solved on the board's engine: how long it took, and blue's
    six."""
    seconds: float
    picks: list[str]


class Verdict(NamedTuple):
    """Whether a layer, or the whole stack, is ready, and the lines that say so."""
    ok: bool
    lines: list[str]


class Service(TypedDict):
    """One compose service's container as `docker compose ps` reports it: its
    state (running, exited, restarting; empty with no container) and its
    health (healthy, unhealthy, starting; empty with no healthcheck)."""
    state: str
    health: str


class Health(TypedDict):
    """What each served layer answered, None where nothing did, and the probe:
    None when the board could not solve one or was never asked. The replies
    stay JSON off the wire; verdict reads them with .get. `backup` is the
    backup container, None where docker did not answer; `playbook` is why
    the host's playbook does not load, None when it loads - each left out
    where it was not asked."""
    data: dict[str, Any] | None
    inference: dict[str, Any] | None
    ui: dict[str, Any] | None
    board: Probe | None
    backup: NotRequired[Service | None]
    playbook: NotRequired[str | None]


def health() -> Health:
    """The three served layers' replies, a board probed when the inference
    layer answers, the backup container's state and the host's playbook
    check."""
    replies = {layer: get_json(url) for layer, url in URLS.items()}
    return Health(data=replies["data"], inference=replies["inference"], ui=replies["ui"],
                  board=probe() if replies["inference"] else None,
                  backup=service(BACKUP_SERVICE), playbook=playbook_problem())


def service(name: str) -> Service | None:
    """One compose service's container as `docker compose ps` reports it,
    None where docker does not answer. Compose prints a JSON object a line,
    or one JSON array before 2.21."""
    try:
        done = subprocess.run(  # nosec B603 B607  # a literal argv, docker found on PATH as sh() finds it
            ["docker", "compose", "ps", "--all", "--format", "json", name], cwd=ROOT,
            capture_output=True, text=True, timeout=MINUTE)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if done.returncode:
        return None
    text = done.stdout.strip()
    try:
        rows = json.loads(text) if text.startswith("[") else [
            json.loads(line) for line in text.splitlines() if line.strip()]
    except ValueError:
        return None
    row = next((r for r in rows if isinstance(r, dict)), {})
    return Service(state=str(row.get("State") or ""), health=str(row.get("Health") or ""))


def probe() -> Probe | None:
    """One board solved on the board -> {"seconds", "picks"}, or None when it
    did not answer with a six: unreachable, erroring, or a playbook whose
    limits seat no composition."""
    started = time.time()
    data = get_json(PROBE, timeout=2 * MINUTE)
    picks = (data or {}).get("blue", {}).get("blue") or []
    if len(picks) != 6:                            # a six, or the solve failed
        return None
    return Probe(seconds=round(time.time() - started, 1), picks=picks)


def _state_problem(data: dict[str, Any]) -> str | None:
    """Why the database is not ready, from the state the data layer's /health
    carries (db.psql.schema.state); None when it is current."""
    state = data.get("state")
    if state == "current":
        return None
    if state == "stale":
        return ("data layer: schema behind the migrations (%s)"
                % ", ".join(data.get("pending_migrations") or []))
    if state in ("empty", "unfilled"):
        return "data layer: the database holds no heroes yet"
    if state is None:
        return ("data layer: its /health carries no state - the image"
                " predates this checkout (`orchestrator.py up` rebuilds it)")
    return "data layer: the database is %s" % state


def data_verdict(data: dict[str, Any] | None) -> Verdict:
    """The data layer answers, its database is current, and what it holds."""
    if not data:
        return Verdict(False, ["data layer: not answering"])
    if data.get("status") != "ok":
        return Verdict(False, ["data layer: %s" % data.get("error", data.get("status"))])
    announced = data.get("announced")
    summary = "data layer: %d tables, %d heroes%s, rates captured %s" % (
        data.get("table_count", 0), data.get("heroes", 0),
        " (%d announced, not yet playable)" % announced if announced else "",
        data.get("newest_capture") or "never")
    problem = _state_problem(data)
    return Verdict(False, [problem, summary]) if problem else Verdict(True, [summary])


def inference_verdict(inf: dict[str, Any] | None, board: Probe | None,
                      loads_here: bool = False) -> Verdict:
    """The inference layer answers on the board, sees the playbook, and solves
    a board. A playbook the board's container refuses while this checkout
    loads it (`loads_here`) is read by older code: the image predates the
    checkout. A folder that reads empty there is a stale mount, and the
    verdict prints the fix."""
    if not inf:
        return Verdict(False, ["inference: not answering"])
    if inf.get("status") != "ok":
        lines = ["inference: %s" % inf.get("error", inf.get("status"))]
        if stale_mount(inf):
            lines.append("inference: %s" % RECREATE)
        elif loads_here and "strategies" not in inf:
            lines.append("inference: this checkout loads that playbook, so the image's code"
                         " predates it - `orchestrator.py up` rebuilds the image")
        return Verdict(False, lines)
    if not inf.get("strategies"):
        return Verdict(False, ["inference: no strategies visible (%s)" % RECREATE])
    pending = inf.get("pending")
    summary = "inference: %d strategies, %d heroes%s" % (
        inf["strategies"], inf.get("heroes", 0),
        " - %d draft(s) awaiting /strategy" % pending if pending else "")
    if board is None:
        return Verdict(False, [summary, "inference: a board did not solve - the engine"
                                        " fails under this playbook (`docker compose logs"
                                        " ui`)"])
    return Verdict(True, [summary + ", a board in %.1fs" % board["seconds"]])


def ui_verdict(ui: dict[str, Any] | None) -> Verdict:
    """The board answers with its roster."""
    if not ui:
        return Verdict(False, ["board: not answering"])
    if "heroes" not in ui:
        return Verdict(False, ["board: %s" % ui.get("error", "no roster in the reply")])
    return Verdict(True, ["board: %d heroes on the roster, %d maps"
                          % (len(ui["heroes"]), len(ui.get("maps", [])))])


def backup_lines(backup: Service | None) -> list[str]:
    """A warning when the nightly dump is not being taken: the backup
    container not running, or unhealthy - its newest dump over 26 hours old.
    Nothing where all is well or docker did not answer. The board works
    without it, so it never makes the stack not ready."""
    if backup is None:
        return []
    if backup["state"] != "running":
        return ["backup: %s - no nightly dump is being taken (`docker compose logs backup`)"
                % (backup["state"] or "no container")]
    if backup["health"] == "unhealthy":
        return ["backup: unhealthy - the newest dump in backups/ is over 26 hours old"
                " (`docker compose logs backup`)"]
    return []


def verdict(h: Health) -> Verdict:
    """The stack's verdict from the health map: ok when every layer is, and the
    data layer's lines, then the inference layer's, then the board's, then a
    warning on the nightly dump."""
    layers = (
        data_verdict(h["data"]),
        inference_verdict(h["inference"], h["board"],
                          loads_here="playbook" in h and h["playbook"] is None),
        ui_verdict(h["ui"]))
    return Verdict(all(layer.ok for layer in layers),
                   [line for layer in layers for line in layer.lines]
                   + backup_lines(h.get("backup")))


def dotenv() -> dict[str, str]:
    """KEY=VALUE lines of .env beside this file: what compose reads. No .env
    reads as none; one that cannot be read raises."""
    try:
        with open(os.path.join(ROOT, ".env"), encoding="utf-8") as handle:
            text = handle.read()
    except FileNotFoundError:
        return {}
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            out[key.strip()] = value.strip().strip("'\"")
    return out


def stale_mount(inf: dict[str, Any] | None) -> bool:
    """The playbook's folder reads as empty or missing inside the board's
    container - a bind mount gone stale - rather than a file in it that does
    not load, whose error the verdict prints as it is."""
    if not inf or inf.get("strategies"):
        return False
    error = str(inf.get("error", ""))
    return "no strategies in " in error or "no strategies directory at " in error


def playbook_problem() -> str | None:
    """Why the playbook the stack reads does not load, checked on the host
    under .env's COUNTRIX_STRATEGIES; None when it loads. The data container
    refuses a rebuild over such a playbook and restarts until it loads."""
    folder = os.environ.get("COUNTRIX_STRATEGIES") or dotenv().get("COUNTRIX_STRATEGIES") or ""
    folder = folder.strip()
    try:
        catalog.load(os.path.abspath(os.path.join(ROOT, folder)) if folder else None)
    except CatalogError as error:
        return str(error)
    return None


def up() -> int:
    """Check the playbook, build the image, make backups/, start the
    containers, wait for each container -> the verdict's exit code. Pending
    drafts stay pending: the verdict counts them for /strategy."""
    problem = playbook_problem()
    if problem:
        return report(False, ["playbook: %s - the stack would not start on it: the user"
                              " fixes or removes that file" % problem])
    print("building the image and starting the containers...")
    sh("docker", "compose", "build", "data", timeout=30 * MINUTE)
    # the backup service's bind mount, made here by the checkout's owner:
    # left to Docker, a Linux host makes it root's and the dump cannot write it
    os.makedirs(os.path.join(ROOT, BACKUPS), exist_ok=True)
    sh("docker", "compose", "up", "-d", "--remove-orphans", timeout=10 * MINUTE)
    print("waiting for the containers (a first build scrapes the sources: minutes)...")
    wait_for(URLS["data"], 30 * MINUTE, "the data layer")
    wait_for(URLS["ui"], 10 * MINUTE, "the board")
    return report(*verdict(health()))


def status() -> int:
    """The verdict, touching nothing."""
    return report(*verdict(health()))


def report(ok: bool, lines: list[str]) -> int:
    """Print the lines, then READY or NOT READY with the URLs -> the exit code."""
    for line in lines:
        print("  " + line)
    print(
        "%s - board %s, MCP over HTTP %s" % ("READY" if ok else "NOT READY", BOARD, MCP_URL))
    return 0 if ok else 1


def down() -> int:
    """Stop the containers; the database volume stays."""
    sh("docker", "compose", "down", timeout=5 * MINUTE)
    print("stopped; the database volume stays")
    return 0


def main(argv: list[str]) -> int:
    """Run one verb, `up` when none is named -> its exit code; 2, with the
    usage on stderr, for anything else."""
    verbs: dict[str, Callable[[], int]] = {"up": up, "status": status, "down": down}
    verb = argv[0] if argv else "up"
    if len(argv) > 1 or verb not in verbs:
        print(__doc__, file=sys.stderr)
        return 2
    return verbs[verb]()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
