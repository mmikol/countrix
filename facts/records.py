"""The typed records a Hero, a Map and the World keep and hand to other
modules: the facts engine, the metrics and the solver read them by field or
unpack them, and the shape each one has is declared here once."""

from typing import NamedTuple, TypedDict

# --- a hero's ------------------------------------------------------------

class Rates(NamedTuple):
    """A hero's win, pick and ban rate in one population, percent; a rate the
    capture does not publish is None."""
    win: float | None
    pick: float | None
    ban: float | None


class MapRate(NamedTuple):
    """A hero's win and pick rate on one map, percent."""
    win: float
    pick: float | None


class KitLine(NamedTuple):
    """One line of the wiki's 6v6 kit for a hero, as kit_6v6 stores it: the
    piece it changes, the stat it names and the figures it moves from and to
    (None where the line names none), and its words."""
    piece: str
    stat: str | None
    before: float | None
    after: float | None
    text: str


class KitChange(NamedTuple):
    """What the format in force did with one 6v6 figure: the piece (empty
    for the hero's pool), the stat, the figures, whether it moved a number
    the kit holds, and the wiki's words."""
    piece: str
    stat: str | None
    before: float | None
    after: float | None
    applied: bool
    text: str


class Fired(NamedTuple):
    """One mechanism of the counter matrix firing for a pair: its name, its
    strength in [0, 1], the words the board says it with ("hitscan against
    a flier") and the numbers that fired it."""
    mechanism: str
    strength: float
    phrase: str
    numbers: str


class Pairing(NamedTuple):
    """A winner against a loser in the counter matrix: its score, the fired
    strengths' sum capped at 1, and each mechanism that fired, strongest
    first."""
    score: float
    fired: tuple[Fired, ...]


class DerivedEdge(NamedTuple):
    """A counter edge the matrix derives on a pair the wiki leaves out: the
    winner answers the loser, by the winner's score against it, through the
    mechanisms that fired."""
    winner: int
    loser: int
    score: float
    fired: tuple[Fired, ...]


# --- a map's -------------------------------------------------------------

class StageTerrain(NamedTuple):
    """How often a stage's own text mentions one terrain feature, and the
    words of that text (0 where stored before the words were)."""
    per_thousand: float
    mentions: int
    words: int


# --- the World's ---------------------------------------------------------

class Synergy(NamedTuple):
    """A pair the wiki says plays well together: its score, 1 when one article
    claims the pair and 2 when both, and its note."""
    score: int | None
    note: str | None


class Snapshot(TypedDict):
    """One source's newest capture of rates, as the meta facts word it: the
    capture day, the patch it fell in, the queue and platform, and the
    regions its rows cover."""
    source: str
    captured: str
    patch: str | None
    released: str | None
    queue: str
    platform: str
    region: str | None


class Patch(NamedTuple):
    """A patch shipped since the rates were captured, and its release day."""
    name: str
    released: str


class KitListMiss(NamedTuple):
    """A name an authored kit list holds that no hero's ability or weapon
    config carries, and the lists that hold it: a piece the wiki renamed,
    which reads as an ordinary one until its lists take the new name."""
    name: str
    lists: tuple[str, ...]
