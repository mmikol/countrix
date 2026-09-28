"""The board's server: its roster and facts speak what the MCP tools serve.
Its board and catalog are inference/serve.py's handlers, tested in
tests/inference/test_serve.py. No HTTP server is spun up - the handler is
thin routing; tests/ui/test_board_server.py serves it."""

import pytest

from db import Refusal
from ui import board


@pytest.mark.invariant
def test_roster_endpoint_carries_portraits_and_maps(db):
    data, code = board.api_roster(db)
    assert code == 200
    assert {h["role"] for h in data["heroes"]} == {"tank", "damage", "support"}
    assert all(h["status"] in ("released", "announced") for h in data["heroes"])
    assert all(h["portrait"] for h in data["heroes"] if h["status"] == "released")
    assert all(h["pool"] > 0 for h in data["heroes"])     # the door's roster, pool and all
    assert any(m["name"] == "King's Row" for m in data["maps"])
    for h in data["heroes"]:                          # an announced hero rides in its role, dated
        if h["status"] == "announced":
            assert h["role"] in ("tank", "damage", "support") and "release_date" in h
    db.rollback()


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
    data, _ = board.api_roster(db)
    assert any(m["name"] == "King's Row" and m["sided"] for m in data["maps"])
    assert any(m["name"] == "Ilios" and not m["sided"] for m in data["maps"])
    db.rollback()
