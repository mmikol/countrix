"""The recorded matches through the door: check_match on the synthetic World
with no database, then record_match, list_matches and delete_match against
a scratch database holding the same roster (tests/scratch.py), never the
built one. The synthetic roster has four tanks (Anvil, Kite, Mortar,
Quarry), twelve released heroes and Wisp, announced; Harbor Gate is
Hybrid, Ember Ruins Control, Salt Flats Push."""

import datetime

import psycopg
import pytest

from db import Refusal
from door.mcp import matches as door_matches
from door.mcp import tools
from door.mcp.schema import ToolReply
from facts.draft import Draft
from facts.matches import load_matches
from inference import catalog
from tests import scratch

BLUE = ["Anvil", "Kite", "Rook", "Needle", "Balm", "Myrrh"]
RED = ["Mortar", "Quarry", "Rook", "Gale", "Sorrel", "Tansy"]      # Rook plays for both
TODAY = datetime.date(2026, 9, 25)


def _checked(world, **board):
    return door_matches.check_match(world, Draft(**board))


# --- the checks, on the synthetic World -----------------------------------------

def test_a_played_map_is_checked_as_the_board_checks_a_board(synthetic_world):
    """The names resolve through World.resolve: any spelling, and the
    board's refusals - an unknown hero, an announced one, a hero twice on a
    team, a banned hero picked, an unknown map."""
    played = _checked(synthetic_world, map_name="harbor gate", side="attack",
                      blue=tuple(n.lower() for n in BLUE), red=tuple(RED), bans=("Flint",))
    assert played.map.name == "Harbor Gate"
    assert [h.name for h in played.blue] == BLUE and [h.name for h in played.bans] == ["Flint"]
    for board, said in (
            ({"blue": ("Goku", *BLUE[1:])}, "unknown heroes: Goku"),
            ({"blue": ("Wisp", *BLUE[1:])}, "announced, not yet playable: Wisp"),
            ({"blue": ("Anvil", *BLUE[:5])}, "blue picks the same hero twice: Anvil"),
            ({"bans": ("Balm",)}, "banned this match, cannot be picked: Balm"),
            ({"map_name": "Atlantis"}, "unknown map: Atlantis")):
        with pytest.raises(Refusal, match=said):
            _checked(synthetic_world, **{"map_name": "Salt Flats", "blue": tuple(BLUE),
                                         "red": tuple(RED), **board})


def test_a_played_map_names_its_map_and_both_sixes(synthetic_world):
    with pytest.raises(Refusal, match="a recorded match names its map"):
        _checked(synthetic_world, blue=tuple(BLUE), red=tuple(RED))
    with pytest.raises(Refusal, match="both sixes, and blue names 5"):
        _checked(synthetic_world, map_name="Salt Flats", blue=tuple(BLUE[:5]), red=tuple(RED))
    with pytest.raises(Refusal, match="both sixes, and red names 0"):
        _checked(synthetic_world, map_name="Salt Flats", blue=tuple(BLUE))
    with pytest.raises(Refusal, match="more than 6 red picks"):     # the Draft's own limit
        _checked(synthetic_world, map_name="Salt Flats", blue=tuple(BLUE),
                 red=(*RED, "Flint"))
    with pytest.raises(Refusal, match="more than 5 bans"):
        _checked(synthetic_world, map_name="Salt Flats", blue=tuple(BLUE), red=tuple(RED),
                 bans=("Flint", "Gale", "Needle", "Balm", "Myrrh", "Wisp"))


def test_a_team_of_three_tanks_is_refused_whatever_the_playbook_holds(synthetic_world):
    three = ("Anvil", "Kite", "Mortar", "Needle", "Balm", "Myrrh")
    with pytest.raises(Refusal, match="at most 2 tanks, and blue picks 3"):
        _checked(synthetic_world, map_name="Salt Flats", blue=three, red=tuple(RED))
    with pytest.raises(Refusal, match="at most 2 tanks, and red picks 3"):
        _checked(synthetic_world, map_name="Salt Flats", blue=tuple(BLUE),
                 red=("Mortar", "Quarry", "Kite", "Gale", "Sorrel", "Tansy"))


def test_a_sided_map_takes_blues_side_and_any_other_map_none(synthetic_world):
    teams = {"blue": tuple(BLUE), "red": tuple(RED)}
    with pytest.raises(Refusal, match="Harbor Gate has sides: say whether blue attacked"):
        _checked(synthetic_world, map_name="Harbor Gate", **teams)
    for unsided in ("Ember Ruins", "Salt Flats"):
        with pytest.raises(Refusal, match="%s has no sides: leave side empty" % unsided):
            _checked(synthetic_world, map_name=unsided, side="defense", **teams)
        assert _checked(synthetic_world, map_name=unsided, **teams).map.name == unsided
    assert _checked(synthetic_world, map_name="Harbor Gate", side="defense", **teams)
    with pytest.raises(Refusal, match="side must be attack or defense"):
        _checked(synthetic_world, map_name="Harbor Gate", side="both", **teams)


def test_the_day_played_is_a_day_that_has_come():
    assert door_matches.played_day(None, TODAY) == TODAY
    assert door_matches.played_day("", TODAY) == TODAY
    assert door_matches.played_day("2026-09-01", TODAY) == datetime.date(2026, 9, 1)
    # a caller a timezone ahead of the server may be on tomorrow already
    assert door_matches.played_day("2026-09-26", TODAY) == datetime.date(2026, 9, 26)
    with pytest.raises(Refusal, match="played_on 2026-09-27 has not come yet"):
        door_matches.played_day("2026-09-27", TODAY)
    with pytest.raises(Refusal, match="played_on is a day, YYYY-MM-DD, not 'last night'"):
        door_matches.played_day("last night", TODAY)


def test_a_note_is_one_line_and_short():
    assert door_matches.one_line("  held the\n first   point ") == "held the first point"
    assert door_matches.one_line("") == ""
    limit = door_matches.NOTE_LIMIT
    assert door_matches.one_line("x" * limit) == "x" * limit
    with pytest.raises(Refusal, match="%d characters at most" % limit):
        door_matches.one_line("x" * (limit + 1))


def test_the_record_tools_take_what_the_board_and_the_skill_send():
    schema = tools.REGISTRY.get("record_match").schema
    assert set(schema["properties"]) == {
        "map", "side", "result", "blue", "red", "bans", "played_on", "note"}
    assert set(schema["required"]) == {"map", "result", "blue", "red"}
    assert schema["properties"]["result"]["enum"] == ["win", "loss", "draw"]
    assert schema["properties"]["side"]["enum"] == ["attack", "defense", ""]
    assert tools.REGISTRY.get("delete_match").schema["required"] == ["match_id"]
    assert {spec.family for spec in tools.REGISTRY if spec.name.endswith("_match")
            or spec.name == "list_matches"} == {"door.mcp.matches"}


def test_a_call_the_schema_refuses_reaches_no_database():
    nowhere = tools.Context(dsn="postgresql://nobody@127.0.0.1:9/nowhere")
    board = {"map": "Harbor Gate", "blue": BLUE, "red": RED}
    with pytest.raises(Refusal, match="must be one of 'win', 'loss', 'draw'"):
        nowhere.call("record_match", result="won", **board)
    with pytest.raises(Refusal, match="missing"):
        nowhere.call("record_match", map="Harbor Gate", result="win", blue=BLUE)
    with pytest.raises(Refusal, match="played_on is a day"):
        nowhere.call("record_match", result="win", played_on="yesterday", **board)
    with pytest.raises(Refusal, match="limit is 1 or more"):
        nowhere.call("list_matches", limit=0)


# --- the tools, on a scratch database -------------------------------------------------

@pytest.fixture()
def ctx(scratch_dsn):
    """A context on the scratch database, its matches cleared."""
    with psycopg.connect(scratch_dsn) as cx:
        cx.execute("delete from matches")
    return tools.Context(dsn=scratch_dsn)


def _record(ctx, **overrides):
    board = {
        "map": "Harbor Gate", "side": "attack", "result": "win", "blue": BLUE, "red": RED,
        "bans": ["Flint"], **overrides}
    return ctx.call("record_match", **board)


@pytest.mark.invariant
def test_a_recorded_match_is_stored_as_the_roster_names_it(ctx, scratch_dsn):
    """Any spelling in, the roster's names out; the playbook in force
    stamped; the rows under the user source; the reply's first line what
    the board flashes."""
    text, data = _record(ctx, map="harbor gate", blue=[n.upper() for n in BLUE],
                         played_on="2026-09-24", note=" held\nthe gate ")
    assert text.splitlines()[0] == "recorded match %d: win on Harbor Gate" % data["match_id"]
    assert data == {
        "match_id": data["match_id"], "played_on": "2026-09-24", "map_name": "Harbor Gate",
        "side": "attack", "result": "win", "blue": BLUE, "red": RED, "bans": ["Flint"],
        "playbook_digest": catalog.playbook_digest(), "note": "held the gate"}
    with psycopg.connect(scratch_dsn) as cx:
        [match] = load_matches(cx)
        sources = {code for (code,) in cx.execute(
            "select distinct s.code from matches m join sources s using (source_id)"
            " union select distinct s.code from match_picks p join sources s using (source_id)")}
    assert match._replace(played_on=match.played_on.isoformat(), blue=list(match.blue),
                          red=list(match.red), bans=list(match.bans))._asdict() == data
    assert sources == {"user"}


@pytest.mark.invariant
def test_a_match_played_today_is_dated_today_and_an_unsided_map_holds_no_side(ctx):
    _text, data = _record(ctx, map="Ember Ruins", side="", result="draw", bans=[])
    assert data["played_on"] == datetime.date.today().isoformat()
    assert data["side"] == "" and data["bans"] == [] and data["result"] == "draw"


@pytest.mark.invariant
def test_a_refused_match_writes_nothing(ctx, scratch_dsn):
    for overrides, said in (({"side": ""}, "has sides"), ({"bans": ["Anvil"]}, "banned"),
                            ({"blue": BLUE[:5]}, "both sixes"),
                            ({"red": ["Mortar", "Quarry", "Kite", *RED[3:]]}, "tanks")):
        with pytest.raises(Refusal, match=said):
            _record(ctx, **overrides)
    with psycopg.connect(scratch_dsn) as cx:
        assert cx.execute("select count(*) from matches").fetchone()[0] == 0
        assert cx.execute("select count(*) from match_picks").fetchone()[0] == 0


@pytest.mark.invariant
def test_list_matches_is_newest_first_up_to_its_limit(ctx):
    assert ctx.call("list_matches") == ToolReply("no matches recorded",
                                                 {"matches": [], "total": 0})
    first = _record(ctx, played_on="2026-09-20").data["match_id"]
    second = _record(ctx, played_on="2026-09-22", result="loss").data["match_id"]
    late = _record(ctx, played_on="2026-09-21", map="Salt Flats", side="").data["match_id"]
    text, data = ctx.call("list_matches")
    assert [m["match_id"] for m in data["matches"]] == [second, late, first]
    assert data["total"] == 3 and text.startswith("3 of 3 recorded matches, newest first")
    assert "#%d  2026-09-22  Harbor Gate  attack  loss" % second in text
    assert "  bans  Flint" in text
    text, data = ctx.call("list_matches", limit=1)
    assert [m["match_id"] for m in data["matches"]] == [second] and data["total"] == 3


@pytest.mark.invariant
def test_delete_match_takes_a_match_and_its_picks(ctx, scratch_dsn):
    kept = _record(ctx).data["match_id"]
    wrong = _record(ctx, result="loss").data["match_id"]
    text, data = ctx.call("delete_match", match_id=wrong)
    assert text.splitlines()[0] == "deleted match %d" % wrong
    assert data["deleted"]["result"] == "loss"
    with psycopg.connect(scratch_dsn) as cx:
        assert [m.match_id for m in load_matches(cx)] == [kept]
        assert cx.execute("select count(*) from match_picks where match_id = %s",
                          (wrong,)).fetchone()[0] == 0
    with pytest.raises(Refusal, match="no recorded match %d" % wrong):
        ctx.call("delete_match", match_id=wrong)


@pytest.mark.invariant
def test_a_database_the_migrations_have_not_reached_refuses_a_record(dsn):
    with scratch.database(dsn) as bare:
        with pytest.raises(Refusal, match=r"no matches table yet \(migration 024\): run db_m"):
            _record(tools.Context(dsn=bare))
        assert tools.Context(dsn=bare).call("list_matches").data["total"] == 0
