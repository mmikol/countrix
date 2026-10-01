"""A Result as it reads: unscored and why, the rendered breakdown, the
facts a pick and a contribution cite, and the queue a win rate names.
Every board is the synthetic World's: no database."""

from facts import board_facts
from facts.draft import Draft
from inference import catalog
from inference.base import OFF
from tests.verification.inference import BRIEF, FIXTURE_PLAYBOOK, evaluated


def test_a_playbook_that_scores_nothing_reads_unscored(synthetic_world):
    """With the default engine off, limits and prose alone tie every
    legal six at zero: the results carry no share of a best, say so, and the
    verdict is the one line."""
    from inference import engine
    world = synthetic_world
    reference = catalog.load(FIXTURE_PLAYBOOK)
    assert any(s.weighs for s in reference)
    limit_only = [h for h in reference if h.form == "limit"]
    assert limit_only and not any(s.weighs for s in limit_only)
    draft = Draft("Harbor Gate", ("Mortar", "Gale"), ("Balm", "Anvil"))
    b = engine.board(world, draft, catalog=limit_only, brief=engine.Brief(base=OFF, swaps=False))
    d = b.to_dict()
    for key in ("blue", "red"):                     # the optimal is the reference: 100, always
        assert d[key]["scoring"] is True and d[key]["normalized"] == 100
    for key in ("current", "red_current", "fill", "countered"):
        assert d[key]["scoring"] is False and d[key]["normalized"] is None
        assert all(a["normalized"] is None for a in d[key]["alternatives"])
    assert d["momentum"]["verdict"].startswith("unscored") and d["momentum"]["blue"] is None
    assert {badge["label"] for badge in d["momentum"]["badges"].values()} == {"unscored"}
    assert "(unscored)" in b.current.rendered() and "UNSCORED:" in b.current.rendered()
    scored = engine.board(world, draft, catalog=reference, brief=BRIEF).to_dict()
    assert scored["current"]["scoring"] is True
    assert scored["current"]["normalized"] is None   # two picks of six: no share to give
    assert 0 < scored["fill"]["normalized"] <= 100   # the filled six carries it
    assert scored["current"]["unscored"] is None


def test_the_default_engine_scores_a_playbook_that_scores_nothing(synthetic_world):
    """The same limits alone under the default engine: every seat scores and
    carries a share, no badge reads unscored, and only red's likely six, a
    likelihood nothing scores, says why it has none."""
    from inference import engine
    from inference.result import LIKELIHOOD
    reference = catalog.load(FIXTURE_PLAYBOOK)
    limit_only = [h for h in reference if h.form == "limit"]
    draft = Draft("Harbor Gate", ("Mortar", "Gale"), ("Balm", "Anvil"))
    d = engine.board(synthetic_world, draft, catalog=limit_only, brief=BRIEF).to_dict()
    for key in ("blue", "red", "current", "red_current", "fill", "countered"):
        assert d[key]["scoring"] is True and d[key]["unscored"] is None, key
    assert 0 < d["fill"]["normalized"] <= 100 and d["momentum"]["blue"] is not None
    assert "unscored" not in {badge["label"] for badge in d["momentum"]["badges"].values()}
    assert "unscored" not in d["momentum"]["verdict"]
    assert d["expected"]["unscored"] == LIKELIHOOD and d["expected"]["normalized"] is None


def test_the_rendered_breakdown_marks_a_need():
    """A need reads at or below zero by design, so the breakdown says which
    terms are needs; the flag rides to_dict() on each contribution."""
    from inference.result import Result
    r = Result(
        kind="evaluate", map_name=None, red=[], blue=[], locked=[], catalog=[], base=OFF,
        contributions=[
            {
                "id": "a-reward", "kind": "heuristic", "form": "heuristic",
                "applies": True, "weighted": 0.25, "metric": None, "need": False},
            {
                "id": "a-need", "kind": "heuristic", "form": "heuristic",
                "applies": True, "weighted": -0.11, "metric": None, "need": True}])
    assert "breakdown: a-reward +0.25 · a-need -0.11 (need)" in r.rendered()
    assert [c["need"] for c in r.to_dict()["contributions"]] == [False, True]


def test_a_metric_printed_inside_another_fact_cites_that_fact(synthetic_world):
    """team.range_max rides the range_median line and team.cleanse the invuln
    line; a rule on either cites that fact, not its guard's."""
    from inference.result import _cited_fact
    six = ["Anvil", "Quarry", "Needle", "Flint", "Balm", "Sorrel"]
    fs = board_facts.generate(synthetic_world,
                              Draft("Harbor Gate", ("Mortar",), tuple(six), side="attack"))
    for metric, line in (("team.range_max", "team.range_median"), ("team.melee", "team.hitscan"),
                         ("team.cleanse", "team.invuln"), ("team.dps_count", "team.dps_floor"),
                         ("matchup.exposure_share", "matchup.coverage_share")):
        fact = _cited_fact(fs, [metric, "team.style_top"])
        assert fact is not None and fact.key == line, metric


def test_a_mirror_pick_cites_its_own_facts_not_the_enemy_copy(synthetic_world):
    """Gale on both teams: our Gale's reasons come from our side of the
    board - never "answers Anvil" (our Anvil, whom red's Gale answers) and
    never "partner of Kite" (red's Kite)."""
    r = evaluated(synthetic_world, Draft(
        "Harbor Gate", ("Kite", "Gale"), ("Anvil", "Mortar", "Gale", "Rook", "Balm", "Sorrel")),
        catalog=catalog.load(FIXTURE_PLAYBOOK))
    ours = next(p for p in r.picks if p["hero"] == "Gale")
    partners = [part for part in ours["why"].split("; ") if part.startswith("partner of")]
    assert "answers Anvil" not in ours["why"] and not any("Kite" in part for part in partners)
    assert "partner of Sorrel" in ours["why"]           # our Sorrel, beside our Gale


def test_a_pick_and_the_plan_name_the_queue_the_rates_were_captured_in(
        synthetic_world, scratch_playbook):
    """The source publishes no Open Queue rates, so each win rate a pick
    cites and the plan's basis say which queue the rates come from: the
    synthetic World's are Role Queue's."""
    from inference import engine
    from inference.result import rates_queue
    b = engine.board(synthetic_world, Draft("Harbor Gate", ("Anvil",), side="attack"),
                     catalog=scratch_playbook, brief=BRIEF)
    assert rates_queue(b.blue.facts) == "Role Queue"
    assert b.plan.split("\n")[-1].startswith("Based on: the Role Queue rates and counters")
    rates = [
        part for r in (b.blue, b.red) for p in r.picks for part in p["why"].split("; ")
        if part.startswith("wins ")]
    assert rates and all(part.endswith(", Role Queue") for part in rates)
