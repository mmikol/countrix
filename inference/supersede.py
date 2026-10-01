"""Latest wins: a board a newer request from the same client replaced stops
at its next check instead of holding the solver.

Latest hands a server one ticket per request and client. Each board's
Watch holds its ticket; every search the board runs asks it every
CHECK_EVERY branches (inference.solver), and between searches, and once
the ticket is superseded the check raises Superseded.
"""

import threading
from collections.abc import Callable

from db import Refusal


class Superseded(Refusal):
    """A board a newer request from the same client replaced before it was
    solved. It is answered as the caller's, a 400 with no traceback: the
    caller has already asked for the board it wants."""


# what a superseded board says, wherever it stops
MESSAGE = "a newer board from the same client superseded this one"


class Latest:
    """Latest wins, per client: each board request takes a ticket under its
    client's name, and a ticket is superseded as soon as a newer one is taken
    under the same name. A server hands the ticket to board() as
    Brief.superseded, so a board the page has already moved past stops at
    its next check instead of holding the solver."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._newest: dict[str, int] = {}

    def take(self, client: str) -> Callable[[], bool]:
        """A new ticket for `client`: a check that turns true once another
        is taken under the same name."""
        with self._lock:
            mine = self._newest.get(client, 0) + 1
            self._newest[client] = mine

        def superseded() -> bool:
            with self._lock:
                return self._newest[client] != mine
        return superseded


class Watch:
    """One board's check against being superseded. Every search the board
    runs calls check() as it goes: once a newer request has replaced the
    board, the check raises Superseded and the board stops."""

    def __init__(self, superseded: Callable[[], bool] | None = None) -> None:
        self.superseded = superseded

    def check(self) -> None:
        """Raise Superseded once a newer request has replaced this board."""
        if self.superseded is not None and self.superseded():
            raise Superseded(MESSAGE)
