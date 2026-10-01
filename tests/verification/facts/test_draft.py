"""The Draft from facts/draft.py refuses a board no lobby holds wherever it
is built - by a door's parse_board, by the MCP tools' _draft, by the engine's
dataclasses.replace - and board_stage, the stage a board is played on, as
its map spells it. No database."""

import dataclasses

import pytest

from db import Refusal
from facts.draft import MAX_BANS, TEAM_SIZE, Draft, board_stage, parse_board

SEVEN = ("Ana", "Kiriko", "Lúcio", "Tracer", "Genji", "Sojourn", "Ashe")


def test_a_draft_refuses_a_team_of_seven_and_a_sixth_ban():
    """Seven picks on a team, or six bans, is no board a lobby holds, and
    cutting either would answer a board the caller did not send: the Draft
    refuses both, whether a door builds it or parses it off the wire."""
    for team in ("red", "blue"):
        with pytest.raises(Refusal, match="more than 6 %s picks" % team):
            Draft(**{team: SEVEN})
        with pytest.raises(Refusal, match="more than 6 %s picks" % team):
            parse_board({team: list(SEVEN)})
    with pytest.raises(Refusal, match="more than 5 bans"):
        Draft(bans=SEVEN[:6])
    with pytest.raises(Refusal, match="more than 5 bans"):
        parse_board({"bans": list(SEVEN[:6])})
    draft = parse_board({"blue": list(SEVEN[:TEAM_SIZE]), "bans": list(SEVEN[:MAX_BANS])})
    assert len(draft.blue) == TEAM_SIZE and len(draft.bans) == MAX_BANS


def test_a_draft_refuses_a_side_that_is_not_one():
    with pytest.raises(Refusal, match="side must be attack or defense, got 'left'"):
        Draft("Harbor Gate", side="left")
    with pytest.raises(Refusal, match="side must be"):
        parse_board({"map": ["Harbor Gate"], "side": ["left"]})
    assert Draft("Harbor Gate", side="attack").side == "attack"


def test_a_replaced_draft_is_checked_again():
    """dataclasses.replace runs the check again, where NamedTuple._replace
    never did, so the engine cannot derive a board past the limits."""
    with pytest.raises(Refusal, match="more than 5 bans"):
        dataclasses.replace(Draft(), bans=SEVEN[:6])
    with pytest.raises(Refusal, match="more than 6 red picks"):
        dataclasses.replace(Draft("Harbor Gate"), red=SEVEN)


def test_parse_board_drops_empty_values():
    draft = parse_board({"map": [""], "red": ["", "Ana"], "blue": [""], "bans": ["", "Ashe"],
                         "side": [""], "stage": [""]})
    assert draft == Draft(None, ("Ana",), (), ("Ashe",), "", "")


def test_parse_board_reads_the_stage_and_a_stage_needs_a_map():
    """The stage rides the `stage` key, its first value; a stage with no map
    names no ground, and the Draft refuses it wherever it is built."""
    draft = parse_board({"map": ["Ember Ruins"], "stage": ["forge", "Spire"]})
    assert (draft.map_name, draft.stage) == ("Ember Ruins", "forge")
    for build in (lambda: Draft(stage="Forge"), lambda: parse_board({"stage": ["Forge"]}),
                  lambda: dataclasses.replace(Draft("Ember Ruins", stage="Forge"), map_name=None)):
        with pytest.raises(Refusal, match="name the map for stage 'Forge'"):
            build()


def test_a_board_is_played_on_a_stage_its_map_lists(synthetic_world):
    """board_stage answers the stage as the map spells it, whatever the
    spelling sent, and none for none; a stage the map does not list is
    refused naming the map's stages, and any stage on a map that lists none."""
    w = synthetic_world
    ember, salt = w.map("Ember Ruins"), w.map("Salt Flats")
    assert board_stage(ember, "forge") == "Forge" and board_stage(ember, "") == ""
    assert board_stage(None, "") == ""
    with pytest.raises(Refusal, match="Ember Ruins has no stage 'Well'; its stages:"
                                      " Courtyard, Forge, Spire"):
        board_stage(ember, "Well")
    with pytest.raises(Refusal, match="Salt Flats lists no stages"):
        board_stage(salt, "Forge")
    with pytest.raises(Refusal, match="name the map"):
        board_stage(None, "Forge")
