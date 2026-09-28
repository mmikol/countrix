"""One gate for every door: the same over-limit board sent through the page's
facts endpoint and its board handler, the three MCP board tools and the
engine's two entry points is refused with the same message on each, and
locked picks the playbook's limits rule out are refused by every infer.
The page's board route is not listed: it opens a connection and hands the
query to serve.handle_board, which is a door here. The synthetic World
stands in for the database and the reference playbook for the live one,
and every board solves in this process."""

import contextlib
import os
import shutil

import pytest

from db import Refusal
from door.mcp import tools
from facts import tables
from facts.draft import Draft
from inference import catalog, engine, serve
from tests.inference import FIXTURE_PLAYBOOK
from ui import board as page

SEVEN = ("Balm", "Myrrh", "Sorrel", "Tansy", "Rook", "Needle", "Flint")

# every door that reads a board; the ones that solve apply the queue's tank rule too
FACTS_DOORS = ("page api_facts", "mcp facts")
SOLVING_DOORS = (
    "page handle_board",
    "mcp infer", "mcp board",
    "engine infer", "engine board")
DOORS = (*FACTS_DOORS, *SOLVING_DOORS)

OVER_LIMIT = [
    pytest.param({"red": SEVEN, "blue": ("Anvil",)}, "more than 6 red picks", id="seven-red"),
    pytest.param({"blue": SEVEN}, "more than 6 blue picks", id="seven-blue"),
    pytest.param({"blue": ("Anvil",), "bans": SEVEN[:6]}, "more than 5 bans", id="six-bans"),
]


class Offline(tools.Context):
    """The door's context, every tool family registered, over no database:
    tables.load is stubbed."""

    def connect(self, boot=False):
        return contextlib.nullcontext("cx")


@pytest.fixture()
def doors(synthetic_world, monkeypatch):
    """Each door by name, as a call that takes a board: red, blue and bans as
    tuples, one dict for Draft(**board), ctx.call(name, **board) and the
    page's parsed query."""
    monkeypatch.setattr(tables, "load", lambda cx: synthetic_world)
    monkeypatch.setenv("COUNTRIX_STRATEGIES", FIXTURE_PLAYBOOK)
    ctx = Offline(dsn="postgresql://nowhere")

    def query(board):
        return {key: list(value) for key, value in board.items()}

    def tool(name):
        return lambda board: ctx.call(name, **board)

    def solved(entry):
        return lambda board: entry(synthetic_world, Draft(**board), catalog=[])

    return {
        "page api_facts": lambda board: page.api_facts(None, query(board)),
        "page handle_board": lambda board: serve.handle_board(None, query(board)),
        "mcp facts": tool("facts"),
        "mcp infer": tool("infer"),
        "mcp board": tool("board"),
        "engine infer": solved(engine.infer),
        "engine board": solved(engine.board),
    }


@pytest.mark.parametrize("door", DOORS)
@pytest.mark.parametrize(("board", "message"), OVER_LIMIT)
def test_every_door_refuses_a_board_no_lobby_holds(doors, door, board, message):
    """A seventh pick on either team and a sixth ban: the Draft every door
    builds refuses the board, so no door cuts it or solves it."""
    with pytest.raises(Refusal, match=message):
        doors[door](board)


@pytest.mark.parametrize("door", SOLVING_DOORS)
def test_every_door_that_solves_refuses_a_third_red_tank(doors, door):
    """Three red tanks against one blue pick is refused as the queue's by
    infer and board alike; test_engine holds a third blue tank. The facts
    doors are left out: a board's facts state what it holds and apply no
    tank rule."""
    with pytest.raises(Refusal, match="the queue allows at most 2 tanks, and red picks 3"):
        doors[door]({"red": ("Anvil", "Kite", "Mortar"), "blue": ("Balm",)})


def test_every_infer_refuses_locked_picks_its_limits_rule_out(
        doors, synthetic_world, monkeypatch, tmp_path):
    """A full blue six that breaks one of the playbook's limits is not
    allowed: every infer that is handed it as locked picks, under the
    playbook in force, refuses them with the rule's name, in the words the
    board's current comp reads."""
    (tmp_path / "three-supports.md").write_text(
        "---\nname: At most three supports\nkind: constraint\nrequire: team.supports <= 3\n"
        "---\n# At most three supports\n\nA six fields at most three supports.\n",
        encoding="utf-8")
    shutil.copy(os.path.join(FIXTURE_PLAYBOOK, catalog.META_FILE), tmp_path)
    monkeypatch.setenv("COUNTRIX_STRATEGIES", str(tmp_path))
    board = {"red": ("Mortar",), "blue": ("Balm", "Myrrh", "Sorrel", "Tansy", "Anvil", "Rook")}
    # the engine's own door under the playbook in force: the fixture's passes catalog=[]
    in_force = {"engine infer": lambda board: engine.infer(synthetic_world, Draft(**board))}
    for door in ("mcp infer", "engine infer"):
        with pytest.raises(Refusal, match=r"^not allowed: breaks At most three supports$"):
            in_force.get(door, doors[door])(board)
