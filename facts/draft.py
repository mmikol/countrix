"""The board's vocabulary: a lobby's limits and the refusal of a team past
them, the sides of a sided map, and the Draft - the board at one stage of
the pick-and-ban draft, which refuses a board no lobby holds - with
parse_board, the one reader of a board off the wire, which the board's
facts and its solves (serve.handle_board) share, and the format the kit is
read in, KIT_FORMAT. A playbook draft - a strategy
awaiting its frontmatter - is another thing. A leaf: it imports only the
model and db's Refusal, so every other module in the package can take
these names from it.
"""

from collections.abc import Iterable, Mapping, Sequence, Sized
from dataclasses import dataclass
from typing import Literal

from db import Refusal
from facts.model import Hero, Map

TEAM_SIZE = 6             # 6v6 Open Queue
MAX_TANKS = 2             # the queue's own limit, whatever the playbook holds
MAX_BANS = 5              # each team's two and the lobby's
SIDED_MODES = ("Escort", "Hybrid")   # modes with an attacking and a defending side
SIDES = ("attack", "defense")
# the two seats: blue is the owner's, red the other side's
type Seat = Literal["blue", "red"]
EXPECTED_SHAPE = {"tank": 2, "damage": 2, "support": 2}   # what a lobby fields: two of each
# The format the kit is read in. The shipped playbook's open-queue-ranked
# assumption makes 6v6 Open Queue the target, so the load lays the wiki's 6v6
# figures over the 5v5 ones the kit tables hold (facts.kit_format)
KIT_FORMAT = "6v6"


def check_team_size(picks: Sized, seat: str) -> None:
    """Refuse a team of more picks than a lobby seats."""
    if len(picks) > TEAM_SIZE:
        raise Refusal("more than %d %s picks" % (TEAM_SIZE, seat))


def check_tanks(heroes: Iterable[Hero], seat: str) -> None:
    """Refuse a team the queue would not seat: more than MAX_TANKS tanks. The
    limit is the game's, so it binds whatever the playbook holds."""
    tanks = sum(1 for h in heroes if h.role == "tank")
    if tanks > MAX_TANKS:
        raise Refusal("the queue allows at most %d tanks, and %s picks %d"
                      % (MAX_TANKS, seat, tanks))


@dataclass(frozen=True)
class Draft:
    """The board at one stage of the pick-and-ban draft. It refuses a board
    no lobby holds - a team past TEAM_SIZE picks, bans past MAX_BANS, a side
    that is not one - when it is built, dataclasses.replace included, so
    every door that builds one refuses the same boards."""
    map_name: str | None = None
    red: tuple[str, ...] = ()
    blue: tuple[str, ...] = ()
    bans: tuple[str, ...] = ()
    side: str = ""

    def __post_init__(self) -> None:
        check_team_size(self.red, "red")
        check_team_size(self.blue, "blue")
        if len(self.bans) > MAX_BANS:
            raise Refusal("more than %d bans" % MAX_BANS)
        if self.side not in ("", *SIDES):
            raise Refusal("side must be attack or defense, got %r" % self.side)


# --- the board off the wire -----------------------------------------------------
#
# The board's two routes that read one - /api/facts in ui/board.py and
# /api/board through inference/serve.py - read it off a query string with
# parse_board. The limits belong to Draft, so these routes and the MCP board
# tools (door/mcp/boards.py) refuse the same boards. A Draft holds tuples: a
# list in a field makes an equal-looking Draft compare unequal.

# A parsed query string, as both routes hand it to parse_board
type Query = Mapping[str, Sequence[str]]


def parse_board(query: Query) -> Draft:
    """The board a parsed query names, its empty values dropped. Draft
    refuses any board no lobby holds, and nothing is cut: a cut would answer
    a board the caller did not send."""
    maps, sides = query.get("map"), query.get("side")
    return Draft(map_name=(maps[0] or None) if maps else None,
                 red=tuple(x for x in query.get("red", ()) if x),
                 blue=tuple(x for x in query.get("blue", ()) if x),
                 bans=tuple(x for x in query.get("bans", ()) if x),
                 side=sides[0] if sides else "")


def is_sided(m: Map | None) -> bool:
    """Whether the map has an attacking and a defending side."""
    return m is not None and (m.mode or "") in SIDED_MODES


def board_side(m: Map | None, side: str) -> str:
    """The side a board keeps: the draft's side where the map has sides, none
    on any other map."""
    return side if is_sided(m) else ""


def opposite(side: str) -> str:
    """The other seat's side; no side stays none."""
    return {"attack": "defense", "defense": "attack"}.get(side, "")
