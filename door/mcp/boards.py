"""The board a board tool takes: BOARD's six properties - map, red, blue,
bans, side, stage - and board_tool, the decorator that registers a tool over them
and hands its function the one Draft they name. The facts family's facts and
the solver family's infer and board are declared through it.
"""

import functools
from collections.abc import Callable

from door.mcp.registry import Context, tool
from door.mcp.schema import Properties, ToolReply
from facts.draft import SIDES, Draft, as_side

BOARD: Properties = {
    "map": {"type": "string", "description": "map name (any spelling)"},
    "red": {
        "type": "array", "items": {"type": "string"},
        "description": "the enemy team's revealed heroes"},
    "blue": {
        "type": "array", "items": {"type": "string"},
        "description": "your team's locked heroes"},
    "bans": {
        "type": "array", "items": {"type": "string"},
        "description": "the match's bans, at most five (each team's two and"
                       " the lobby's), more refused; all optional; neither"
                       " team can pick them"},
    "side": {
        "type": "string", "enum": [*SIDES, ""],
        "description": "blue's side on an Escort or Hybrid map (red gets"
                       " the other); ignored on Control, Push, Flashpoint"},
    "stage": {
        "type": "string",
        "description": "the stage in play, one the map lists (the roster's"
                       " stages): a Control or Flashpoint round, or an Escort"
                       " or Hybrid phase; its terrain and objective are what"
                       " the map.* metrics read. Empty or left out: the whole"
                       " map. A stage the map does not list is refused"},
}

# A board tool's function: its context, the Draft, then its own arguments.
type BoardFn = Callable[..., ToolReply]


def _names(value: object) -> tuple[str, ...]:
    """An array of names the schema admitted, as the tuple a Draft holds,
    its empty names dropped as facts.draft.parse_board drops them."""
    return tuple(str(v) for v in value if v) if isinstance(value, (list, tuple)) else ()


def _draft(arguments: dict[str, object]) -> Draft:
    """The board BOARD's six arguments name, taken out of the call's
    arguments: the lists as tuples, and what the call left out empty. Draft
    refuses a board past the lobby's limits, whichever door built it."""
    map_name = arguments.pop("map", None)
    return Draft(map_name=None if map_name is None else str(map_name),
                 red=_names(arguments.pop("red", ())),
                 blue=_names(arguments.pop("blue", ())),
                 bans=_names(arguments.pop("bans", ())),
                 side=as_side(str(arguments.pop("side", ""))),
                 stage=str(arguments.pop("stage", "")))


def _board_call(fn: BoardFn, ctx: Context, /, **arguments: object) -> ToolReply:
    """A board tool's call: its function handed the one Draft BOARD's
    arguments name, then the rest of them."""
    return fn(ctx, _draft(arguments), **arguments)


def board_tool(
        name: str, description: str,
        properties: Properties | None = None) -> Callable[[BoardFn], BoardFn]:
    """The decorator that registers a board tool: BOARD's six properties
    first, then its own, and the function called with the one Draft they name
    and the rest of the arguments. The call wears the function's name and
    module, which is its family; the function is returned as it is."""
    def decorate(fn: BoardFn) -> BoardFn:
        call = functools.update_wrapper(functools.partial(_board_call, fn), fn)
        tool(name, description, dict(BOARD, **(properties or {})))(call)
        return fn
    return decorate
