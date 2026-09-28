"""Every hero is the right pick somewhere: the objective may make a hero rare, never
impossible, and the heroes the search seats nowhere are named. tests/fixtures/reach.json
records, per released hero, the board inference.reach.search seated it on (a tool:
`reach`), within the five bans a match has, beside the objective that seated it - the
playbook's digest and the default engine's stamp;
`.venv/bin/python -m tests.inference.record_reach` re-records it, and every released hero
is on file or named unseated.
Rates move daily and the two databases differ, so a few boards may tip; a hero that falls
off its board, or is on neither list, is searched for again, and none may be lost. The
search itself, and the recorder, run on the synthetic World."""

import json

import pytest

from db import Refusal
from facts.model import World
from facts.records import DerivedEdge
from inference import base, catalog, reach
from inference.solver import Infeasible
from tests.inference import FIXTURE_PLAYBOOK, in_force, recorded
from tests.inference import record_reach as recorder

# named, not waived - see the test
UNSEATED = {"Cassidy", "Domina", "Emre", "Freja", "Hazard", "Ramattra", "Shion", "Sierra",
            "Sojourn", "Venture", "Zarya"}


@pytest.mark.invariant
def test_every_hero_reach_finds_a_board_for_is_still_seated_and_none_is_newly_lost(world):
    # reach.json is recorded under the shipped playbook - its assumptions and the healing
    # floor - on top of the default engine; a board that no longer seats its hero is
    # searched for anew.
    fixture = recorded("reach")
    boards = fixture["boards"]
    released = {h.name for h in world.heroes.values() if h.released}
    on_file = {b["hero"] for b in boards}
    assert all(b["seated"] and len(b["banned"]) <= reach.MAX_BANS for b in boards)
    fell = [b["hero"] for b in boards if b["hero"] in released and not reach.seated(world, b)]
    # a stale fixture fails here, before the costly search for what it lost
    stale = (
        "" if (fixture["playbook"], fixture["base"]) == in_force()
        else " - recorded under a different objective")
    assert len(fell) <= len(boards) // 5, "the recorded boards have gone stale%s: %s" % (
        stale, fell)
    # Eleven heroes the recorder's search found no board for. That is not a proof none
    # exists - the search tries four maps and a few reds per hero, so a board it
    # never visits could seat any of them - but it is what the search establishes,
    # and they are named rather than waived: a twelfth fails here. The default engine
    # and the healing floor score the shipped playbook's boards, and on the boards the
    # search tries they value none of the eleven above its rivals for the seat, even
    # with five of them banned; the playbook's rules are what can answer it. They are
    # not searched again on every run - eleven searches are a quarter hour, more under
    # coverage - so one that comes to seat leaves UNSEATED when the recorder
    # re-records. The healing floor seated Illari and Lifeweaver and unseated Cassidy;
    # summed healing seated Kiriko and unseated Zarya.
    assert not UNSEATED - released, "not a released hero: %s" % ", ".join(UNSEATED - released)
    lost = [name for name in sorted((released - on_file - UNSEATED) | set(fell))
            if not reach.search(world, name)["seated"]]
    assert not lost, "no board seats: %s" % ", ".join(lost)


def test_the_reach_fixture_names_the_objective_it_was_recorded_under():
    """Needs no database, so the pull-request gate checks the stamp: the
    fixture names the playbook and the default engine that seated its heroes
    (recorded() fails a fixture that names neither) and holds one seated
    board per hero, none of them one the test names unseated."""
    fixture = recorded("reach")
    assert fixture["base"] is not None, "recorded with the default engine off"
    boards = fixture["boards"]
    assert not {b["hero"] for b in boards} & UNSEATED
    heroes = [b["hero"] for b in boards]
    assert len(set(heroes)) == len(heroes), "a hero is recorded twice"
    assert all(b["seated"] for b in boards), "an unseated board is on file"


def test_reach_refuses_a_hero_the_world_does_not_know():
    """A name the World does not hold is the caller's to fix: reach resolves
    its hero the way every board tool does, not a crash inside the search."""
    with pytest.raises(Refusal, match="unknown heroes: Nosuchhero"):
        reach.search(World(), "Nosuchhero")


def test_reach_without_a_map_pool_is_the_servers_fault(synthetic_world, monkeypatch):
    monkeypatch.setattr(reach, "maps", lambda world, hero: [])
    with pytest.raises(RuntimeError, match="no board") as caught:
        reach.search(synthetic_world, "Anvil")
    assert not isinstance(caught.value, Refusal)


def test_a_board_no_six_fits_is_a_miss_and_the_search_goes_on(synthetic_world, monkeypatch):
    """Harbor Gate, Anvil's best map, is made to allow no six: the search
    counts it a miss and goes on to the next map, where it used to end on
    the engine's refusal."""
    monkeypatch.setenv("COUNTRIX_STRATEGIES", FIXTURE_PLAYBOOK)
    monkeypatch.setattr(reach, "reds", lambda world, hero: [[]])
    infer = reach.engine.infer

    def fenced(world, draft, **kw):
        if draft.map_name == "Harbor Gate":
            raise Infeasible("no composition satisfies the limits on this board")
        return infer(world, draft, **kw)
    monkeypatch.setattr(reach.engine, "infer", fenced)
    anvil = synthetic_world.hero("Anvil")
    board = reach.search(synthetic_world, "Anvil")
    assert board["map"] in [m.name for m in reach.maps(synthetic_world, anvil)[1:]]


def test_a_hero_no_board_fits_is_infeasible_not_a_crash(synthetic_world, monkeypatch):
    """With no board the search tries allowing a six, reach refuses the hero
    as the playbook's to relax, and a recorded board that no longer fits has
    fallen: it seats no one."""
    monkeypatch.setenv("COUNTRIX_STRATEGIES", FIXTURE_PLAYBOOK)

    def fenced(world, draft, **kw):
        raise Infeasible("no composition satisfies the limits on this board")
    monkeypatch.setattr(reach.engine, "infer", fenced)
    with pytest.raises(Infeasible, match="no board the search tries seats Anvil") as caught:
        reach.search(synthetic_world, "Anvil")
    assert isinstance(caught.value, Refusal)
    recorded_board = {"hero": "Anvil", "seated": True, "map": "Harbor Gate", "side": "",
                      "red": [], "banned": [], "six": ["Anvil"], "gap": 0.0}
    assert reach.seated(synthetic_world, recorded_board) is False


def test_a_hero_its_best_map_favours_is_seated_there_with_no_ban(synthetic_world):
    """Anvil's map rates lift it most on Harbor Gate: the search tries that map
    first, finds Anvil in the optimal six against red's likely six, and the
    board it records seats Anvil again when it is solved afresh."""
    anvil = synthetic_world.hero("Anvil")
    assert reach.maps(synthetic_world, anvil)[0].name == "Harbor Gate"
    assert reach.reds(synthetic_world, anvil)[0] == []
    board = reach.search(synthetic_world, "Anvil")
    assert (board["seated"], board["banned"], board["map"], board["red"], board["gap"]) == (
        True, [], "Harbor Gate", [], 0.0)
    assert "Anvil" in board["six"] and reach.seated(synthetic_world, board)


def test_the_reds_read_the_counter_graph_the_engine_scores(synthetic_world):
    """A red is built on counters.weight, the graph the default engine
    scores, not the wiki's edges alone: Anvil's derived answers to Quarry
    and Flint rank after its wiki answer to Mortar and before the most
    picked heroes it does not answer, and Balm, with a derived answer to
    Anvil, drops behind them. On the wiki's edges alone the red was
    Mortar, Kite, Needle, Rook, Balm and Tansy."""
    w = synthetic_world
    ids = {h.name: h.id for h in w.heroes.values()}
    for winner, loser in (("Anvil", "Quarry"), ("Anvil", "Flint"), ("Balm", "Anvil")):
        w.derived[(ids[loser], ids[winner])] = DerivedEdge(
            winner=ids[winner], loser=ids[loser], score=0.8, net=0.5, fired=())
    assert reach.reds(w, w.hero("Anvil")) == [
        [], ["Mortar", "Quarry", "Flint", "Needle", "Tansy", "Myrrh"]]


# four of a six, none of them a tank
REST = ("Rook", "Needle", "Balm", "Tansy")


def _boards(monkeypatch, maps, top_of, held_score):
    """The search stubbed onto `maps`, red empty: each unlocked board's top
    six is top_of(its bans), scoring 3; with Anvil locked, the six holds
    Anvil as its one tank and scores held_score(its map). Returns the bans
    each unlocked board was solved under."""
    import types
    monkeypatch.setattr(reach, "maps", lambda world, hero: [world.map(n) for n in maps])
    monkeypatch.setattr(reach, "reds", lambda world, hero: [[]])
    seen = []

    def infer(world, draft, **kw):
        if draft.blue:
            return types.SimpleNamespace(blue=["Anvil", *REST, "Sorrel"],
                                         score=held_score(draft.map_name))
        seen.append(draft.bans)
        return types.SimpleNamespace(blue=top_of(draft.bans), score=3.0)
    monkeypatch.setattr(reach.engine, "infer", infer)
    return seen


def test_a_rival_banned_out_of_the_heros_seat_seats_it(synthetic_world, monkeypatch):
    """Harbor Gate's optimal six fields Mortar and Kite in Anvil's role, and
    the six that holds Anvil neither: the ban search bans the first, Mortar,
    and the board solved again seats Anvil. The board recorded is the first
    side tried."""
    def top_of(bans):
        return ["Anvil" if "Mortar" in bans else "Mortar", "Kite", *REST]
    seen = _boards(monkeypatch, ["Harbor Gate"], top_of, lambda map_name: 1.0)
    board = reach.search(synthetic_world, "Anvil")
    assert board == {"hero": "Anvil", "seated": True, "map": "Harbor Gate", "side": "attack",
                     "red": [], "banned": ["Mortar"], "six": top_of(("Mortar",)), "gap": 0.0}
    assert ("Mortar",) in seen


def test_a_rival_of_another_role_is_banned_out_of_the_heros_seat(synthetic_world, monkeypatch):
    """In Open Queue a seat is no role's: Harbor Gate's optimal six fields
    Gale and Kite where the six holding Anvil fields Anvil and Sorrel. The
    ban search bans Kite first, Anvil's own role, then Gale, a damage hero
    the search used to pass over, stopping with no tank left to ban, and
    the board solved again seats Anvil."""
    def top_of(bans):
        if "Gale" in bans:
            return ["Anvil", "Sorrel", *REST]
        return ["Gale", "Sorrel" if "Kite" in bans else "Kite", *REST]
    seen = _boards(monkeypatch, ["Harbor Gate"], top_of, lambda map_name: 1.0)
    board = reach.search(synthetic_world, "Anvil")
    assert (board["seated"], board["banned"]) == (True, ["Kite", "Gale"])
    assert seen[-3:] == [(), ("Kite",), ("Kite", "Gale")]


def test_a_ban_search_that_runs_out_returns_the_closest_board(synthetic_world, monkeypatch):
    """Every round seats a new rival in Anvil's role and never Anvil, so each
    board's ban search stops at the bans a match allows (two here): the
    search returns the board Anvil came closest on, unseated, unbanned and
    with no six, the gap the smallest it fell short by."""
    monkeypatch.setattr(reach, "MAX_BANS", 2)
    rivals = ("Kite", "Mortar", "Quarry")

    def top_of(bans):
        return [next(r for r in rivals if r not in bans), *REST, "Myrrh"]
    gaps = {"Harbor Gate": 1.0, "Ember Ruins": 2.5}
    seen = _boards(monkeypatch, list(gaps), top_of, gaps.__getitem__)
    board = reach.search(synthetic_world, "Anvil")
    assert board == {"hero": "Anvil", "seated": False, "map": "Ember Ruins", "side": "",
                     "red": [], "banned": [], "six": [], "gap": 0.5}
    assert ("Kite", "Mortar") in seen and max(len(bans) for bans in seen) == 2


class _Connected:
    """psycopg.connect's context manager, connected to nothing."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_the_recorder_writes_every_seated_hero_beside_the_objective_it_ran_under(
        synthetic_world, monkeypatch, tmp_path, capsys):
    """The recorder searches each released hero in name order, records the
    boards that seat one beside the playbook's digest and the default
    engine's stamp, and names the heroes no board seats with the gap each
    fell short by. The search is stubbed: its own tests are above."""
    searched = []

    def search(world, name):
        searched.append(name)
        if name == "Quarry":
            return {"hero": name, "seated": False, "map": "Salt Flats", "side": "", "red": [],
                    "banned": [], "six": [], "gap": 1.235}
        banned = ["Needle"] if name == "Rook" else []
        return {"hero": name, "seated": True, "map": "Harbor Gate", "side": "attack",
                "red": [], "banned": banned, "six": [name], "gap": 0.0}
    monkeypatch.setattr(recorder.psql, "default_dsn", lambda: "postgresql://nowhere")
    monkeypatch.setattr(recorder.psycopg, "connect", lambda dsn: _Connected())
    monkeypatch.setattr(recorder.tables, "load", lambda cx: synthetic_world)
    monkeypatch.setattr(recorder.reach, "search", search)
    monkeypatch.setattr(recorder.catalog, "playbook_digest", lambda: "ab" * 32)
    monkeypatch.setattr(recorder, "OUT", str(tmp_path / "reach.json"))
    assert recorder.main() == 0
    released = sorted(h.name for h in synthetic_world.heroes.values() if h.released)
    assert searched == released and "Wisp" not in searched
    with open(tmp_path / "reach.json", encoding="utf-8") as handle:
        written = json.load(handle)
    assert written["playbook"] == "ab" * 32
    assert written["base"] == base.stamp(catalog.engine_weights())
    assert [b["hero"] for b in written["boards"]] == [n for n in released if n != "Quarry"]
    assert capsys.readouterr().out == (
        "recorded 11 seated heroes under playbook abababababab and the default engine, 1 of"
        " them after bans, 0 on a six recorded for another; unseated: Quarry 1.235\n")


def test_the_recorder_checks_every_six_already_recorded_before_a_hero_is_unseated(
        synthetic_world, monkeypatch, tmp_path, capsys):
    """Quarry's and Myrrh's own searches find no board. Rook's board, found
    in this run, fields Quarry in its optimal six, and the fixture held a
    board for Flint that, solved afresh, fields Myrrh: each is recorded on
    that board. Wisp is announced, never searched. Only a hero no recorded
    six holds is named unseated - the recorder used to name all three."""
    missed = {"Quarry": 1.2, "Myrrh": 0.5, "Sorrel": 0.9}

    def search(world, name):
        if name in missed:
            return {"hero": name, "seated": False, "map": "Salt Flats", "side": "",
                    "red": [], "banned": [], "six": [], "gap": missed[name]}
        six = [name, "Quarry"] if name == "Rook" else [name]
        return {"hero": name, "seated": True, "map": "Harbor Gate", "side": name,
                "red": [], "banned": [], "six": six, "gap": 0.0}
    prior = {"hero": "Flint", "seated": True, "map": "Ember Ruins", "side": "",
        "red": ["Anvil"], "banned": [], "six": ["Flint"], "gap": 0.0}
    out = tmp_path / "reach.json"
    out.write_text(json.dumps({"playbook": "cd" * 32, "base": None, "boards": [prior]}))
    solved = []

    def six(world, board):
        solved.append(board["map"])
        return ["Flint", "Myrrh"]
    monkeypatch.setattr(recorder.psql, "default_dsn", lambda: "postgresql://nowhere")
    monkeypatch.setattr(recorder.psycopg, "connect", lambda dsn: _Connected())
    monkeypatch.setattr(recorder.tables, "load", lambda cx: synthetic_world)
    monkeypatch.setattr(recorder.reach, "search", search)
    monkeypatch.setattr(recorder.reach, "six", six)
    monkeypatch.setattr(recorder.catalog, "playbook_digest", lambda: "ab" * 32)
    monkeypatch.setattr(recorder, "OUT", str(out))
    assert recorder.main() == 0
    written = {b["hero"]: b for b in json.loads(out.read_text())["boards"]}
    assert (written["Quarry"]["map"], written["Quarry"]["side"]) == ("Harbor Gate", "Rook")
    assert written["Quarry"]["six"] == ["Rook", "Quarry"] and written["Quarry"]["seated"]
    assert (written["Myrrh"]["map"], written["Myrrh"]["six"]) == ("Ember Ruins", ["Flint", "Myrrh"])
    assert "Sorrel" not in written and solved == ["Ember Ruins"]
    assert capsys.readouterr().out.endswith(
        "0 of them after bans, 2 on a six recorded for another; unseated: Sorrel 0.900\n")
