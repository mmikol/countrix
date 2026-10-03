"""The board's server: its facts speak what the MCP tools serve. Its roster
is facts.roster's, tested in tests/verification/facts/test_roster.py, and
its board and catalog are ui/serve.py's handlers, tested in
tests/verification/ui/test_serve.py. No HTTP server is spun up - the handler is
thin routing; tests/verification/ui/test_board_server.py serves it."""

import pytest

from db import Refusal
from ui import board


@pytest.mark.invariant
def test_facts_endpoint_returns_the_board(db):
    data, code = board.api_facts(db, {"map": ["King's Row"], "red": ["Zarya", "Pharah"],
                                   "blue": ["Ana"]})
    assert code == 200 and data["count"] > 300
    keys = {f["key"] for f in data["facts"]}
    assert "team.coverage" in keys and "team.net_edges" in keys
    # UNDER-HEALED reads the supports' sustained healing, as the strategies do, not one cast
    data, code = board.api_facts(db, {"blue": ["Zenyatta", "Wuyang"], "red": ["Ana", "Moira"]})
    text = {(f["team"], f["key"]): f["text"] for f in data["facts"]}
    assert text["blue", "team.hps_supports"].endswith(" - UNDER-HEALED")
    assert "UNDER-HEALED" not in text["red", "team.hps_supports"]
    assert not any("UNDER-HEALED" in text[side, "team.heal_peak_supports"]
                   for side in ("blue", "red"))
    with pytest.raises(Refusal, match="Saitama"):      # the boundary answers it 400
        board.api_facts(db, {"red": ["Saitama"]})
    db.rollback()


@pytest.mark.invariant
def test_bans_ride_the_query_string(db):
    data, code = board.api_facts(db, {"map": ["King's Row"], "red": ["Zarya"],
                                      "bans": ["Widowmaker", "Sombra"]})
    assert code == 200 and data["bans"] == ["Widowmaker", "Sombra"]
    assert any(f["scope"] == "bans" for f in data["facts"])
    db.rollback()
