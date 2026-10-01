"""The board's routes over the engine, which ui/board.py answers in its own
process: handle_board, both seats and the current comp; handle_strategies,
the catalog and the default engine's weights; and handle_health, the
catalog's size and the database's state. ADMISSION holds the boards in
flight to BOARDS_AT_ONCE, and LATEST keeps a lane per client, where a newer
board from the client supersedes one still solving. A handler that raises
is answered at the board's request boundary, by db.web.failure.
"""

import contextlib
import threading
import time
from collections.abc import Callable, Iterator
from typing import NotRequired, TypedDict

import psycopg

from db import psql, web
from facts import tables
from facts.draft import Query, parse_board
from inference import catalog as catalog_module
from inference import engine, supersede
from inference.strategy import CatalogError

ADMIT_WAIT = 60.0           # seconds a board waits for room before it is turned away
ADMIT_POLL = 0.5            # seconds between a waiting board's looks at its lane
# boards solving at once in the board's process. A search holds its top K
# sixes, not a field, so memory sets no limit; the work is pure Python under
# one interpreter lock, so a second board would only halve the speed of both
BOARDS_AT_ONCE = 1


class BusyError(Exception):
    """No room for a board within the wait: the caller may ask again."""


class Admission:
    """The boards solving in one process, at most `budget` at once: the
    board's handler admits BOARDS_AT_ONCE. A board waits while `budget`
    boards are in flight. A waiting board a newer one from its client
    supersedes stops waiting; one still waiting after `wait` seconds raises
    BusyError."""

    def __init__(self, budget: int = BOARDS_AT_ONCE, wait: float = ADMIT_WAIT) -> None:
        self.budget = budget
        self.wait = wait
        self._room = threading.Condition()
        self._held = 0

    def held(self) -> int:
        """The boards in flight."""
        with self._room:
            return self._held

    def _take(self, superseded: Callable[[], bool]) -> None:
        deadline = time.monotonic() + self.wait
        with self._room:
            while self._held >= self.budget:
                if superseded():
                    raise supersede.Superseded(supersede.MESSAGE)
                left = deadline - time.monotonic()
                if left <= 0:
                    raise BusyError("the solver is busy with other boards; ask again")
                self._room.wait(min(left, ADMIT_POLL))
            if superseded():             # room came, but a newer board took the lane first
                raise supersede.Superseded(supersede.MESSAGE)
            self._held += 1

    @contextlib.contextmanager
    def admitted(self, superseded: Callable[[], bool]) -> Iterator[None]:
        """Hold one board's place while the block runs; raise BusyError or
        Superseded, holding nothing, when no place comes."""
        self._take(superseded)
        try:
            yield
        finally:
            with self._room:
                self._held -= 1
                self._room.notify_all()


# the boards in flight in the board's process
ADMISSION = Admission()
# the page's boards, one lane per client
LATEST = supersede.Latest()


class Health(TypedDict):
    """What /health answers: ok or degraded; the strategy counts where the
    playbook and its meta.md load; the heroes where the database answers;
    and the error, naming each thing out of reach, where either does not."""
    status: web.HealthStatus
    strategies: NotRequired[int]
    pending: NotRequired[int]
    heroes: NotRequired[int]
    error: NotRequired[str]


def _first(query: Query, key: str) -> str | None:
    """A parameter's first value, or None when the query leaves it out."""
    values = query.get(key)
    return values[0] if values else None


def handle_board(cx: psycopg.Connection, query: Query) -> web.Reply:
    """Both seats and the current comp - what the board's two displays show -
    under the playbook tab's weights, its Meta slider's (meta:value) among
    them. The page never reads the countered case, so it is not solved
    here; a newer board from the same `client` (one lane when none is
    named) supersedes this one, which then answers 400, and a board
    ADMISSION finds no room for answers 429. The whole query is read before
    the lane is taken, so a malformed one supersedes nothing."""
    draft = parse_board(query)
    weights = catalog_module.parse_weights(query.get("weights", []))
    superseded = LATEST.take(_first(query, "client") or "")
    try:
        with ADMISSION.admitted(superseded):
            world = tables.load(cx)
            brief = engine.Brief(weights=weights, solve_countered=False, superseded=superseded)
            return web.Reply(engine.board(world, draft, brief=brief).to_dict(), 200)
    except BusyError as busy:
        return web.Reply({"error": str(busy)}, 429)


def handle_strategies() -> web.Reply:
    """The catalog, and meta.md - the default engine's weights and prose,
    what the playbook tab's Meta card shows. A playbook that does not load
    is the server's fault: the CatalogError reaches the request boundary, a
    500."""
    return web.Reply({"strategies": [s.to_dict() for s in catalog_module.load()],
                      "meta": catalog_module.meta_record(catalog_module.read_meta()),
                      "playbook": catalog_module.playbook_name()}, 200)


def handle_health() -> web.Reply:
    """The catalog's size and the database's state, always 200: a playbook
    that does not load leaves the strategy counts out, and it or a database
    out of reach makes the status degraded, the error naming each - what
    orchestrator.py prints while it waits."""
    out: Health = {"status": "ok"}
    errors: list[str] = []
    try:
        cat = catalog_module.load()
        catalog_module.read_meta()
    except CatalogError as error:
        errors.append(str(error))
    else:
        out["strategies"], out["pending"] = len(cat), sum(1 for s in cat if s.pending)
    # psql.UNREACHABLE: a database out of reach is degraded, never a 500
    try:
        with psycopg.connect(psql.default_dsn()) as cx:
            out["heroes"] = psql.scalar(cx.execute("select count(*) from heroes"))
    except psql.UNREACHABLE as error:
        errors.append(str(error))
    if errors:
        out["status"], out["error"] = "degraded", "; ".join(errors)
    return web.Reply(out, 200)
