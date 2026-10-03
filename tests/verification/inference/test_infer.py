"""infer() and a full six scored alone: locked picks and the queue's shape,
an answer to a flier, a board no six satisfies, bans, one scale per board,
an announced hero, the fill that keeps a lock, a seat's search timed from
where it began, and no rank in an unscored field. A full six's rank is
test_solver's. Every board is the synthetic World's: no database."""

import os

import pytest

from db import Refusal
from facts import board_facts
from facts.draft import Draft
from inference import catalog
from inference.base import OFF
from tests.verification.inference import (
    ASSUMPTIONS_ONLY,
    BRIEF,
    DEFAULT,
    FIXTURE_PLAYBOOK,
    evaluated,
)


def test_infer_keeps_locked_picks_and_the_open_queue_shape(synthetic_world):
    from inference import engine
    world = synthetic_world
    r = engine.infer(world, Draft("Harbor Gate", ("Mortar", "Gale"), ("Balm",)),
                     catalog=catalog.load(FIXTURE_PLAYBOOK), base=DEFAULT)
    assert len(r.blue) == 6 and "Balm" in r.blue
    roles = [world.hero(n).role for n in r.blue]
    assert roles.count("tank") <= 2
    assert r.considered > 100 and r.score > 0
    assert any(p["hero"] == "Balm" and p["locked"] for p in r.picks)
    # every pick cites facts the board for (map, red, the five) shows
    assert r.facts.draft.blue == tuple(r.blue)
    ids = {f.id for f in r.facts.facts}
    for p in r.picks:
        assert p["evidence"] and set(p["evidence"]) <= ids
    # coverage of both enemies is worth 3 points, and the optimum takes them:
    # Anvil answers Mortar, Needle or Flint answers Gale
    cov = next(c for c in r.contributions if c["id"] == "coverage")
    assert cov["raw"] == 1.0 and cov.get("fact")


def test_infer_honours_a_hitscan_answer_to_a_flier(synthetic_world):
    from inference import engine
    world = synthetic_world
    r = engine.infer(world, Draft("Harbor Gate", ("Gale", "Balm")),
                     catalog=catalog.load(FIXTURE_PLAYBOOK), base=DEFAULT)
    assert any(world.hero(n).hitscan for n in r.blue)
    anti = next(c for c in r.contributions if c["id"] == "anti-air")
    assert not anti["applies"] and anti["weighted"] == 0.0      # answered: nothing to charge


def test_a_board_no_six_satisfies_is_refused_by_infer_and_the_board_alike(
        synthetic_world, tmp_path):
    """A limit no six can meet leaves no legal shape, so the field is empty:
    infer refuses the board, and the board refuses the full six it is
    given - instead of ranking it first among nothing."""
    from inference import engine
    world = synthetic_world
    (tmp_path / "seven-tanks.md").write_text(
        "---\nname: seven tanks\nkind: constraint\nrequire: team.tanks == 7\n---\nx\n", "utf-8")
    scratch = catalog.load(str(tmp_path))
    with pytest.raises(Refusal, match="relax a constraint"):
        engine.infer(world, Draft("Harbor Gate", ("Mortar",)), catalog=scratch, base=DEFAULT)
    with pytest.raises(Refusal, match="relax a constraint"):
        engine.board(world, Draft("Harbor Gate", ("Mortar",),
                                  ("Anvil", "Kite", "Rook", "Needle", "Balm", "Tansy")),
                     catalog=scratch, brief=BRIEF)


def test_infer_never_drafts_a_banned_hero(synthetic_world):
    from inference import engine
    world = synthetic_world
    fix = catalog.load(FIXTURE_PLAYBOOK)
    r = engine.infer(world, Draft("Harbor Gate", ("Mortar", "Gale"), ("Balm",),
                                  ("Needle", "Rook", "Anvil")), catalog=fix, base=DEFAULT)
    assert not {"Needle", "Rook", "Anvil"} & set(r.blue)
    assert r.bans == ["Needle", "Rook", "Anvil"] and "banned" in r.rendered()
    assert r.facts.draft.bans == tuple(r.bans)
    with pytest.raises(Refusal, match="banned this match"):
        engine.infer(world, Draft(None, ("Mortar",), ("Balm",), ("Mortar",)), catalog=fix,
                     base=DEFAULT)


def test_scores_share_one_scale_per_board(synthetic_world):
    # infer, a full six scored alone and the current comp normalise against
    # the same seeded reference sample, so the same six scores the same everywhere
    from inference import engine
    world = synthetic_world
    fix = catalog.load(FIXTURE_PLAYBOOK)       # a rich playbook: alternatives fall below the best
    red = ("Mortar", "Gale")
    # no lock: a full six is ranked against the whole unlocked field, and the best six
    # that keeps a locked pick need not be the best of that field
    r = engine.infer(world, Draft("Harbor Gate", red), catalog=fix, base=DEFAULT)
    e = evaluated(world, Draft("Harbor Gate", red, tuple(r.blue)), catalog=fix)
    assert abs(r.score - e.score) < 1e-9 and e.rank == 1
    held = engine.infer(world, Draft("Harbor Gate", red, ("Balm",)), catalog=fix, base=DEFAULT)
    again = evaluated(world, Draft("Harbor Gate", red, tuple(held.blue)), catalog=fix)
    assert "Balm" in held.blue and abs(held.score - again.score) < 1e-9
    assert r.to_dict()["normalized"] == 100 and e.to_dict()["normalized"] == 100
    assert all(0 <= a["normalized"] <= 100 for a in r.alternatives)
    assert r.alternatives[0]["score"] < r.score        # below the optimum, if only by a hair
    assert r.alternatives[0]["normalized"] <= 100
    b = engine.board(world, Draft("Harbor Gate", red, tuple(r.blue)), catalog=fix, brief=BRIEF)
    assert abs(b.current.score - r.score) < 1e-9 and b.blue.blue == r.blue
    assert b.current.to_dict()["normalized"] == 100


def test_an_announced_hero_is_described_but_never_picked(synthetic_world):
    from inference import engine
    world = synthetic_world
    early = [h for h in world.heroes.values() if not h.released]
    assert [h.name for h in early] == ["Wisp"]
    h = early[0]
    fix = catalog.load(FIXTURE_PLAYBOOK)
    fs = board_facts.generate(world, Draft(blue=(h.name,)))       # the facts may describe it
    assert fs.find("hero.announced", h.name)
    with pytest.raises(Refusal, match="announced, not yet playable"):
        engine.infer(world, Draft(blue=(h.name,)), catalog=fix, base=DEFAULT)      # a pick may not
    with pytest.raises(Refusal, match="announced"):
        engine.board(world, Draft(red=(h.name,)), catalog=fix, brief=BRIEF)
    r = engine.infer(world, Draft(), catalog=fix, base=DEFAULT)
    assert h.name not in r.blue and all(a["blue"] for a in r.alternatives)
    assert not any(h.name in a["blue"] for a in r.alternatives)   # nor does the field hold it
    # and under a playbook that ties most sixes, where the tie-break decides: an
    # announced hero once reached the alternatives that way
    limit_only = [s for s in fix if s.form == "limit"]
    r = engine.infer(world, Draft(), catalog=limit_only, base=DEFAULT)
    assert h.name not in r.blue and not any(h.name in a["blue"] for a in r.alternatives)


@pytest.mark.parametrize("base", [OFF, DEFAULT], ids=["base-off", "base-on"])
def test_the_fill_is_the_optimal_whenever_the_optimal_holds_every_lock(synthetic_world, base):
    """Locking a hero of the optimal six leaves the optimal six the best one
    that keeps the lock, so the fill must find it again. With the default
    engine off, under a playbook that scores nothing every six scores zero
    and only the tie-break tells them apart; with it on, the same playbook
    scores by the engine."""
    from inference import engine
    world = synthetic_world
    assert not any(s.weighs for s in ASSUMPTIONS_ONLY)
    for map_name in ("Harbor Gate", "Ember Ruins"):
        best = engine.infer(world, Draft(map_name), catalog=ASSUMPTIONS_ONLY, base=base)
        for hero in best.blue:
            fill = engine.infer(world, Draft(map_name, blue=(hero,)), catalog=ASSUMPTIONS_ONLY,
                                base=base)
            assert fill.blue == best.blue, (map_name, hero, fill.blue)


def test_a_seat_is_timed_from_when_its_search_began(
        monkeypatch, synthetic_world, scratch_playbook):
    """A seat's seconds run from when its search began, the scale and the
    walk included: a search that takes a while reads it."""
    import time

    from inference import engine
    from inference.solver import Solver
    draft = Draft("Harbor Gate", ("Anvil",), side="attack")
    solve = Solver.solve

    def slow(solver, top=5):
        time.sleep(0.3)
        return solve(solver, top)
    monkeypatch.setattr(Solver, "solve", slow)
    seat = engine._optimal(synthetic_world, draft, catalog=scratch_playbook, base=DEFAULT,
                           top=1, seat="blue", kind="infer")
    assert 0.3 <= seat.result.seconds < 5 and seat.result.to_dict()["seconds"] >= 0.3


def test_a_six_in_a_field_that_scores_nothing_has_no_rank(
        synthetic_world, scratch_playbook, tmp_path):
    """A full six's rank counts the sixes that score strictly higher, and
    where nothing scores - the default engine off, a playbook of limits
    alone - every six ties at zero, so every six ranked first. An unscored
    six now carries no rank; a scored one keeps its place, and the default
    engine alone scores the limits' field."""
    import shutil

    six = ("Anvil", "Kite", "Rook", "Needle", "Balm", "Tansy")
    limit_only = tmp_path / "limit-only"            # the scratch playbook is tmp_path's own
    limit_only.mkdir()
    shutil.copy(os.path.join(FIXTURE_PLAYBOOK, "open-queue-tanks.md"), limit_only)
    board = Draft("Harbor Gate", (), six, side="attack")
    unscored = evaluated(synthetic_world, board, catalog=catalog.load(str(limit_only)),
                         base=OFF)
    assert unscored.unscored() is not None
    assert unscored.rank is None and unscored.to_dict()["rank"] is None
    assert "(rank " not in unscored.rendered() and "UNSCORED" in unscored.rendered()
    for scored in (evaluated(synthetic_world, board, catalog=scratch_playbook, base=OFF),
                   evaluated(synthetic_world, board, catalog=catalog.load(str(limit_only)))):
        assert scored.unscored() is None and scored.rank >= 1
        assert "(rank %d among the legal sixes)" % scored.rank in scored.rendered()
