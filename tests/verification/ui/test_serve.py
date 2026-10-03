"""The board's routes over the engine, ui/serve.py, which run in the
board's process: they speak the results the engine returns, admit boards
one at a time, and report the catalog and the database's health. The
database out of reach, as /health reports it, is
tests/verification/db/test_psql.py's."""

import pytest

from db import Refusal
from facts import tables
from inference import catalog
from tests.verification.inference import FIXTURE_PLAYBOOK
from ui import serve


def test_the_strategies_handler_lists_the_playbook_in_force():
    data, code = serve.handle_strategies()
    assert code == 200 and len(data["strategies"]) == len(catalog.load())


@pytest.mark.invariant
def test_the_board_handler_serves_both_seats_and_the_current_comp(db):
    """What the page's board shows: blue's optimal, red's likely six on the
    other side around red's picks, the current comp partial until blue holds
    six and evaluated once it does, and no countered case."""
    for side, other in (("attack", "defense"), ("defense", "attack")):
        data, code = serve.handle_board(db, {
            "map": ["King's Row"], "red": ["Zarya"], "blue": ["Ana"], "side": [side]})
        assert code == 200 and data["side"] == side
        assert data["blue"]["kind"] == "infer" and len(data["blue"]["blue"]) == 6
        assert data["expected"]["seat"] == "red" and data["expected"]["side"] == other
        assert data["expected"]["locked"] == ["Zarya"] and len(data["expected"]["blue"]) == 6
        assert data["current"]["partial"] and data["current"]["blue"] == ["Ana"]
        assert data["blue"]["cited"] and all(p["evidence"] for p in data["blue"]["picks"])
        assert data["countered"] is None                   # the page never reads it
    data, code = serve.handle_board(db, {
        "blue": ["Reinhardt", "Zarya", "Widowmaker", "Bastion", "Ana", "Lúcio"]})
    current = data["current"]
    assert code == 200 and current["kind"] == "evaluate"
    if current["unscored"]:
        assert current["rank"] is None and not current["outranked"]
    else:                               # ranked among the legal sixes, or outside RANK_CAP
        assert (current["rank"] or 0) >= 1 or current["outranked"]
    with pytest.raises(Refusal, match="banned"):          # the boundary answers it 400
        serve.handle_board(db, {"red": ["Zarya"], "blue": ["Ana"], "bans": ["Ana"]})
    data, code = serve.handle_board(db, {
        "map": ["King's Row"], "stage": ["assault"], "red": ["Zarya"], "side": ["attack"]})
    assert code == 200 and data["stage"] == "Assault"
    assert data["blue"]["stage"] == data["expected"]["stage"] == "Assault"
    with pytest.raises(Refusal, match="King's Row has no stage 'Well'"):
        serve.handle_board(db, {"map": ["King's Row"], "stage": ["Well"]})
    db.rollback()


def test_a_refused_board_supersedes_nothing():
    """handle_board reads the whole query before it takes the client's lane,
    so a board its parse refuses - a junk weight, a seventh pick, a stage
    with no map - leaves the board still solving in that lane alone. No
    database is reached: each is refused before the World loads."""
    ticket = serve.LATEST.take("tab1")
    seven = ["Ana", "Ashe", "Baptiste", "Cassidy", "Genji", "Kiriko", "Mercy"]
    for refused in ({"weights": ["junk"]}, {"red": seven}, {"stage": ["Well"]}):
        with pytest.raises(Refusal):
            serve.handle_board(None, {**refused, "client": ["tab1"]})
    assert ticket() is False


def test_a_board_waits_for_room_and_holds_none_once_it_leaves():
    """Admission counts the boards in flight against its budget: two fit in
    a budget of two, a third waits until one leaves, and nothing stays held
    after a board ends - raising included. The board's handler admits
    serve.BOARDS_AT_ONCE."""
    import threading
    admission = serve.Admission(budget=2, wait=5)
    order, inside, leave = [], threading.Event(), threading.Event()

    def third():
        with admission.admitted(lambda: False):
            order.append("third in")
            inside.set()
            leave.wait(5)
    with admission.admitted(lambda: False):
        with admission.admitted(lambda: False):         # the second fits beside the first
            assert admission.held() == 2
            waiter = threading.Thread(target=third)
            waiter.start()
            assert not inside.wait(0.2)                 # no room while two are in flight
            order.append("second out")
        assert inside.wait(5) and order == ["second out", "third in"]
        assert admission.held() == 2
    assert admission.held() == 1
    with pytest.raises(ValueError), admission.admitted(lambda: False):  # room beside the third
        raise ValueError("the solve failed")
    assert admission.held() == 1
    leave.set()
    waiter.join(5)
    assert admission.held() == 0


def test_a_waiting_board_stops_when_superseded_or_turned_away():
    """A board still waiting for room is answered without solving: 400 once a
    newer board from its client supersedes it, 429 once the wait runs out -
    and handle_board says so before the World is read."""
    from inference import supersede
    admission = serve.Admission(budget=1, wait=0.05)
    with admission.admitted(lambda: False):
        with pytest.raises(supersede.Superseded), admission.admitted(lambda: True):
            pass
        with pytest.raises(serve.BusyError), admission.admitted(lambda: False):
            pass
    assert admission.held() == 0


def test_a_board_superseded_while_it_waits_is_not_admitted_when_room_comes():
    """The release that makes room wakes every waiter; one whose lane a newer
    board took meanwhile stops there instead of solving a stale board."""
    import threading

    from inference import supersede
    admission, lanes, caught = serve.Admission(budget=1, wait=5), supersede.Latest(), []
    stale = lanes.take("tab1")

    def waiter():
        try:
            with admission.admitted(stale):
                caught.append("admitted")
        except supersede.Superseded:
            caught.append("superseded")
    with admission.admitted(lambda: False):
        thread = threading.Thread(target=waiter)
        thread.start()
        thread.join(0.1)
        lanes.take("tab1")                       # the page moved on while it waited
    thread.join(5)
    assert caught == ["superseded"] and admission.held() == 0


def test_a_board_with_no_room_answers_429(monkeypatch):
    """No database is reached: the board is turned away before the World loads."""
    admission = serve.Admission(budget=1, wait=0)
    monkeypatch.setattr(serve, "ADMISSION", admission)
    with admission.admitted(lambda: False):
        data, code = serve.handle_board(None, {"map": ["Ilios"], "client": ["tab9"]})
    assert code == 429 and "busy" in data["error"]


@pytest.mark.invariant
def test_health_reports_the_catalog_and_the_database(monkeypatch, dsn):
    monkeypatch.setattr(serve.psql, "default_dsn", lambda: dsn)
    data, code = serve.handle_health()
    assert code == 200 and data["strategies"] == len(catalog.load())
    assert data["status"] == "ok" and data["heroes"] > 40


def test_a_slider_weight_rides_the_board_and_a_malformed_one_is_refused(
        synthetic_world, monkeypatch):
    """The playbook tab's weight reaches the solve through the query: under
    the reference playbook a heuristic is scored at the weight sent, not the
    file's, the Swap cost slider's swap:value is the cost blue's swaps are
    searched at, and a weight that is not id:value is the caller's error.
    The synthetic World stands in for the database."""
    monkeypatch.setattr(tables, "load", lambda cx: synthetic_world)
    monkeypatch.setenv("COUNTRIX_STRATEGIES", FIXTURE_PLAYBOOK)
    heuristic = next(s for s in catalog.load(FIXTURE_PLAYBOOK) if s.kind == "heuristic")
    data, code = serve.handle_board(None, {
        "map": ["Harbor Gate"], "red": ["Mortar"], "blue": ["Balm"],
        "weights": ["%s:3" % heuristic.id, "swap:0"]})
    assert code == 200 and heuristic.weight != 3
    assert data["blue"]["weights"][heuristic.id] == 3
    assert data["swaps"]["cost"] == 0 and sorted(data["swaps"]["six"]) == sorted(
        data["blue"]["blue"])
    with pytest.raises(Refusal, match="id:value"):
        serve.handle_board(None, {"map": ["Harbor Gate"], "weights": ["junk"]})
