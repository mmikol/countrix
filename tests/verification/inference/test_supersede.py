"""Latest wins: a superseded board stops in the middle of a search, a
refusal the doors answer as the caller's, and a board no newer one
replaced asks its check as it goes and runs to the end."""

import dataclasses

import pytest

from facts.draft import Draft
from tests.verification.inference import BRIEF

# red revealed and one blue pick locked on a sided map: every seat of the board solves
DRAFT = Draft("Harbor Gate", ("Anvil",), ("Balm",), side="attack")


def test_a_superseded_board_stops_in_the_middle_of_a_search(
        monkeypatch, synthetic_world, scratch_playbook):
    """Every CHECK_EVERY branches a search asks the board's check; once a
    newer board from the same client has taken the lane, the check raises
    Superseded there, and the board stops without finishing its seats. The
    synthetic boards are small, so the check is asked at every branch."""
    from db import Refusal
    from inference import engine, solver, supersede
    monkeypatch.setattr(solver, "CHECK_EVERY", 1)
    asked = []

    def superseded():
        asked.append(1)
        return len(asked) > 40
    walked = []
    real = solver.Solver._branch

    def branch(self, *args):
        walked.append(1)
        return real(self, *args)
    monkeypatch.setattr(solver.Solver, "_branch", branch)
    with pytest.raises(supersede.Superseded):
        engine.board(synthetic_world, DRAFT, catalog=scratch_playbook,
                     brief=dataclasses.replace(BRIEF, superseded=superseded))
    assert len(asked) == 41 and len(walked) < 45
    assert issubclass(supersede.Superseded, Refusal)


def test_a_board_no_newer_one_replaced_runs_to_the_end(
        monkeypatch, synthetic_world, scratch_playbook):
    """A board whose lane no newer request took asks its check as it goes -
    between its seats and every CHECK_EVERY branches - and is solved whole."""
    from inference import engine, solver
    monkeypatch.setattr(solver, "CHECK_EVERY", 16)
    asked = []

    def superseded():
        asked.append(1)
        return False
    b = engine.board(synthetic_world, DRAFT, catalog=scratch_playbook,
                     brief=dataclasses.replace(BRIEF, superseded=superseded))
    assert b.fill is not None and b.countered is not None and len(asked) > 10
