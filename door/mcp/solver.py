"""The inference layer through the door: the solver's infer, reach and
board. infer and board are board tools (boards.board_tool); reach takes a
hero. Each call loads a World from the database the context points at, and
none of these tools writes.
"""

from collections.abc import Mapping
from typing import TypedDict

from door.mcp.boards import board_tool
from door.mcp.registry import Context, tool
from door.mcp.schema import Property, ToolReply
from facts import tables
from facts.draft import Draft
from inference import catalog, engine, reach
from inference.result import Result

COMPACT_TERMS = 15        # the heaviest terms a compact reply carries

# the search's one knob as the tools describe it; clamp_top holds its rule
TOP: Property = {
    "type": "integer",
    "description": "alternatives to return, 1 to %d (default %d): the next best sixes"
                   " of the whole legal space, in order"
                   % (engine.TOP_CEILING, engine.TOP_DEFAULT)}


class WeightedTerm(TypedDict):
    """One scoring term of a compact reply: its strategy and its weighted part
    of the score."""
    id: str
    weighted: float


class CompactInfer(TypedDict):
    """A compact infer reply's payload: the board and the six with its score;
    how many scoring terms the full reply's contributions carry (terms), how
    many of them do not apply here (idle), the applying heuristics whose
    metric does not vary on this board (silent), and the heaviest terms."""
    map: str | None
    side: str
    red: list[str]
    blue: list[str]
    score: float
    terms: int
    idle: int
    silent: list[str]
    largest: list[WeightedTerm]


@board_tool(
    "infer", "The INFERENCE LAYER: the optimal six for this board under"
    " the default engine (win rates, synergies, counters) and the"
    " markdown strategies in inference/strategies/ on top (players assumed"
    " to play optimally). Locked blue picks are kept; the rest is"
    " searched exactly - every legal six of the released, unbanned roster,"
    " by branch and bound - and picks no six completes within the playbook's"
    " limits are refused as not allowed, the limits named. Returns the comp,"
    " per-pick reasons with fact citations, the score breakdown per engine"
    " term and strategy, and alternatives.",
    {
        "top": TOP,
        "compact": {"type": "boolean",
                    "description": "true: a reply small enough to carry under a"
                                   " playbook of hundreds. The structured payload"
                                   " then has its own keys: map, side, red, blue,"
                                   " score, terms (how many scoring terms the full"
                                   " reply carries), idle, silent (applying,"
                                   " metric not varying on this board) and largest"
                                   " (the %d heaviest terms, each an id and its"
                                   " weighted value)" % COMPACT_TERMS}})
def infer(
        ctx: Context, draft: Draft, top: int | None = None, compact: bool = False) -> ToolReply:
    with ctx.connect() as cx:
        world = tables.load(cx)
    result = engine.infer(world, draft, top=engine.clamp_top(top))
    if compact:
        return ToolReply(*_compact(result))
    return ToolReply(result.rendered(), result.to_dict())


def _compact(result: Result) -> tuple[str, CompactInfer]:
    """A result small enough for a tool reply under a playbook of hundreds:
    the comp, the heuristics that apply but whose metric does not vary on this
    board, and the largest terms."""
    terms = result.contributions
    silent = sorted(c["id"] for c in terms if c.get("spread") is False)   # applying heuristics
    idle = sum(1 for c in terms if not c["applies"])
    largest = sorted((c for c in terms if c["weighted"]),
                     key=lambda c: (-abs(c["weighted"]), c["id"]))[:COMPACT_TERMS]
    payload = CompactInfer(
        map=result.map_name, side=result.side, red=list(result.red), blue=list(result.blue),
        score=round(result.score, 3), terms=len(terms), idle=idle, silent=silent,
        largest=[WeightedTerm(id=c["id"], weighted=round(c["weighted"], 4)) for c in largest])
    lines = result.rendered().split("\n")[:2]
    lines.append("  %d terms, %d not applying here" % (len(terms), idle))
    lines.append("  silent (applies, metric does not vary here): %s"
                 % (", ".join(silent) or "none"))
    lines += ["  %+.2f  %s" % (c["weighted"], c["id"]) for c in largest]
    return "\n".join(lines), payload


@tool(
    "reach", "Can the playbook ever pick this hero? A board that suits it - any map,"
    " its best first, a red it answers, the match's bans spent on the rivals holding its seat - on"
    " which it is in the optimal six; with none, the closest it came. A hero that"
    " cannot be reached is one the facts or the strategies cannot see.",
    {"hero": {"type": "string", "description": "a released hero (any spelling)"}},
    ["hero"])
def reach_tool(ctx: Context, hero: str) -> ToolReply:   # _tool: inference.reach holds the bare name
    with ctx.connect() as cx:
        world = tables.load(cx)
    found = reach.search(world, hero)
    where = "%s%s against %s" % (found["map"], " " + found["side"] if found["side"] else "",
                                 ", ".join(found["red"]) or "the likely six")
    if not found["seated"]:
        return ToolReply("%s is never the optimal pick, even with every ban; closest on %s,"
                         " %.2f behind" % (found["hero"], where, found["gap"]), found)
    return ToolReply("%s is optimal on %s%s: %s" % (
        found["hero"], where,
        ", with %s banned" % ", ".join(found["banned"]) if found["banned"] else "",
        ", ".join(found["six"])), found)


@board_tool(
    "board", "The whole board at any step of the draft (no map, a map, a side,"
    " the stage in play, bans, red's picks as they reveal), every seat solved on"
    " that stage: blue's optimal six as the best counter"
    " to red's selection - to their likely six until they reveal a pick"
    " (blue's own picks never constrain it), red's best"
    " counter to yours, both current comps scored on those scales, your picks"
    " against red's best counter, your locked picks with the empty slots filled,"
    " the fight odds (each seat's share of its own optimal, and the two against"
    " each other), the game plan in prose, the shapes the queue and the"
    " playbook's limits allow, and red's likely six"
    " from the data alone (a two-two-two from the map's pick rates and the"
    " wiki's synergies, past the bans; static for the board, no strategy read).",
    {
        "weights": {"type": "object",
                    "description": "{heuristic id: 0..10} - weights to score this"
                                   " board under instead of the files' (the playbook"
                                   " tab's sliders), and meta: 0..10 in place of"
                                   " meta.md's meta, which scales the default engine"
                                   " (the Meta slider); the files are untouched"}})
def board(
        ctx: Context, draft: Draft, weights: Mapping[str, object] | None = None) -> ToolReply:
    with ctx.connect() as cx:
        world = tables.load(cx)
    brief = engine.Brief(weights=catalog.parse_weights(weights or {}))
    b = engine.board(world, draft, brief=brief)
    return ToolReply(b.rendered(), b.to_dict())
