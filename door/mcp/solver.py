"""The inference layer through the door: the solver's infer, reach and
board. infer and board are board tools (boards.board_tool); reach takes a
hero. Each call loads a World from the database the context points at, and
none of these tools writes.
"""

from collections.abc import Mapping

from door.mcp.boards import board_tool
from door.mcp.registry import Context, tool
from door.mcp.schema import Property, ToolReply
from facts import tables
from facts.draft import Draft
from inference import catalog, engine, reach

# the search's one knob as the tools describe it; clamp_top holds its rule
TOP: Property = {
    "type": "integer",
    "description": "alternatives to return, 1 to %d (default %d): the next best sixes"
                   " of the whole legal space, in order"
                   % (engine.TOP_CEILING, engine.TOP_DEFAULT)}


@board_tool(
    "infer", "The INFERENCE LAYER: the optimal six for this board under"
    " the default engine (win rates, synergies, counters) and, on top, the"
    " markdown strategies in the playbook in force (inference/strategies/"
    " unless COUNTRIX_STRATEGIES names another folder), players assumed to"
    " play optimally. Locked blue picks are kept; the rest is"
    " searched exactly - every legal six of the released, unbanned roster,"
    " by branch and bound - and picks no six completes within the playbook's"
    " limits are refused as not allowed, the limits named. Returns the comp,"
    " per-pick reasons with fact citations, the score breakdown per engine"
    " term and strategy, and alternatives.",
    {"top": TOP})
def infer(ctx: Context, draft: Draft, top: int | None = None) -> ToolReply:
    with ctx.connect() as cx:
        world = tables.load(cx)
    result = engine.infer(world, draft, top=engine.clamp_top(top))
    return ToolReply(result.rendered(), result.to_dict())


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
    " each other), the swaps from blue's picks that pay for the swap cost - one"
    " joint answer, the best six reachable from the picks when each pick"
    " dropped costs that many share points, with blue's share and the fight"
    " odds before and after - the game plan in prose and, on a map with stages,"
    " the plan stage by stage, the shapes the queue and the playbook's limits"
    " allow, and red's likely six"
    " from the data alone (a two-two-two from the map's pick rates and the"
    " wiki's synergies, past the bans; static for the board, no strategy read).",
    {
        "weights": {"type": "object",
                    "description": "{heuristic id: 0..10} - weights to score this"
                                   " board under instead of the files' (the playbook"
                                   " tab's sliders), meta: 0..10 in place of"
                                   " meta.md's meta, which scales the default engine"
                                   " (the Meta slider), and swap: 0..50 in place of"
                                   " meta.md's swap cost, in share points of blue's"
                                   " span; the files are untouched. A value outside"
                                   " its range is clamped into it, and any other id"
                                   " that names no heuristic of the playbook in force"
                                   " is ignored (the reply's weights list those in"
                                   " force)"}})
def board(
        ctx: Context, draft: Draft, weights: Mapping[str, object] | None = None) -> ToolReply:
    with ctx.connect() as cx:
        world = tables.load(cx)
    brief = engine.Brief(weights=catalog.parse_weights(weights))
    b = engine.board(world, draft, brief=brief)
    return ToolReply(b.rendered(), b.to_dict())
