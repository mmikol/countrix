"""Blue's swaps held to a full enumeration on the synthetic World: every
legal six scored by the plain objective less the swap cost for each pick
it drops, the search's answer that enumeration's best, element for
element, for a full, a half-drafted and a not-allowed reference, the
default engine on and off, the cost from 0 to its ceiling; the zero-gain
rule, the pairs and their places, one swap taken leaving the rest the
answer, the keep term never reaching a payload, the target's share its
evaluation's, and the cost in force. No database."""

import dataclasses
import json
import os
import shutil

import pytest

from facts.draft import Draft
from inference import catalog, engine, swaps
from inference.base import OFF, SWAP, SWAP_RANGE
from inference.result import Span
from inference.scoring import Candidate, quantized, rank_key
from tests.verification.inference import DEFAULT, FIXTURE_PLAYBOOK, evaluated
from tests.verification.inference.test_engine import SUPPORTS, _support_limit
from tests.verification.inference.test_solver import enumerated, legal_sixes, seated, verdicts

K = 6                       # the sixes the search's order is compared on
COSTS = (0.0, 5.0, 10.0, 25.0, SWAP_RANGE[1])      # share points of blue's span
BOARDS = {
    "full": Draft("Harbor Gate", ("Mortar", "Gale"),
                  ("Anvil", "Kite", "Rook", "Needle", "Balm", "Myrrh"), side="attack"),
    "partial": Draft("Ember Ruins", ("Anvil", "Needle"), ("Quarry", "Flint")),
    "not-allowed": Draft("Harbor Gate", ("Mortar",), (*SUPPORTS, "Anvil", "Rook")),
    "stuck": Draft("Salt Flats", ("Anvil",), SUPPORTS),
}


@pytest.fixture()
def limited(tmp_path):
    """The reference playbook with a limit of three supports beside its own,
    so four supports are not allowed."""
    for name in catalog.strategy_files(FIXTURE_PLAYBOOK):
        shutil.copy(os.path.join(FIXTURE_PLAYBOOK, name), tmp_path / name)
    return _support_limit(tmp_path)


def plain_seat(world, draft, playbook, base):
    """Blue's optimal's Solver on the board - blue's seat, nothing locked,
    against red's picks - its scale frozen, and its span."""
    solver = seated(world, dataclasses.replace(draft, blue=()), playbook, base)
    best = solver.solve(top=1).ranked[0]
    return solver, Span(best=best.score, floor=solver.floor)


def netted(plain, picks, raw):
    """Every legal six of the board scored by the plain objective less `raw`
    for each pick it drops, best first: the answer, found without the keep
    term or the search."""
    keep = {h.id for h in picks}
    banned = [plain.world.heroes[i] for i in plain.banned]
    out = []
    for six in legal_sixes(plain.world, plain.catalog, (), banned):
        cand = plain.score(plain.prepare(Candidate(six)), detail=False)
        if not cand.violations:
            out.append((cand.score - raw * len(keep - set(cand.key)), cand))
    return sorted(out, key=lambda pair: (-quantized(pair[0]), -pair[1].tiebreak,
                                         sorted(pair[1].names)))


@pytest.mark.parametrize("base", [OFF, DEFAULT], ids=["base-off", "base-on"])
@pytest.mark.parametrize("name", list(BOARDS))
def test_the_swap_search_is_the_enumerated_best_net(synthetic_world, limited, base, name):
    """For each cost, the search's sixes are the enumeration's under the
    keep term, element for element, and its best is the six that maximises
    the plain score less the cost for each pick dropped over every legal
    six. The board suggests a swap exactly where that six drops a pick and
    its net beats the six that keeps every pick - the picks at six, the
    fill around fewer - and, where no six keeps them, always; the swaps it
    names make that six."""
    draft = BOARDS[name]
    plain, span = plain_seat(synthetic_world, draft, limited, base)
    picks = synthetic_world.resolve(None, (), draft.blue).blue
    assert span.best > span.floor
    for cost in COSTS:
        raw = swaps.raw_cost(cost, span)
        solver = swaps.keeping(plain, picks, raw)
        got = solver.solve(top=K).ranked
        assert verdicts(got) == verdicts(enumerated(solver)[:K]), (name, cost)
        net, best = netted(plain, picks, raw)[0]
        assert got[0].key == best.key, (name, cost)
        assert abs(got[0].score - raw * len(picks) - net) < 1e-9
        board = engine.board(synthetic_world, draft, catalog=limited,
                             brief=engine.Brief(base=base, swap=cost))
        s = board.swaps
        assert s is not None and s["cost"] == cost and s["stage"] == ""
        drops = not {h.id for h in picks} <= set(best.key)
        keeper = (draft.blue if len(draft.blue) == 6 and board.current.barred is None
                  else board.fill.blue if board.fill is not None else None)
        if keeper is not None and drops:
            kept = solver.score(solver.prepare(Candidate(
                synthetic_world.resolve(None, (), keeper).blue)), detail=False)
            drops = quantized(got[0].score) > quantized(kept.score)
        if not drops:
            assert s["pairs"] == [] and s["verdict"].startswith("keep the picks"), (name, cost)
            continue
        if not s["pairs"]:              # the odds gate withheld it, and says so
            assert s["status"] == "withheld", (name, cost)
            assert s["verdict"].startswith("keep the picks: the best swaps"), (name, cost)
            continue
        assert s["status"] == "suggested" and sorted(s["six"]) == sorted(best.names), (name, cost)
        held = [p for p in draft.blue if p in s["six"]]
        assert set(held) | {p["in"] for p in s["pairs"]} <= set(s["six"])
        # the empty slots show the fill, as the rest of the board does
        filled = [p["hero"] for p in board.fill.picks if not p["locked"]] if board.fill else []
        assert [o["hero"] for o in s["open"]] == filled
        for pair in s["pairs"]:
            assert draft.blue[pair["at"]] == pair["out"] and pair["out"] not in s["six"]
            assert pair["why"] and pair["portrait"] == synthetic_world.hero(pair["in"]).portrait
        if board.current.barred is not None:
            assert s["before"] is None and "back to an allowed six" in s["verdict"]


def test_a_cost_of_zero_suggests_the_optimal_and_the_ceiling_keeps_the_picks(synthetic_world):
    """At cost 0 the swaps make blue's optimal six, 100 of it; at the
    ceiling, 50 share points a swap, no swap on these boards pays and the
    picks keep, the verdict naming the cost; a partial seat's empty slots
    then show its fill."""
    playbook = catalog.load(FIXTURE_PLAYBOOK)
    for draft in (BOARDS["full"], BOARDS["partial"]):
        free = engine.board(synthetic_world, draft, catalog=playbook,
                            brief=engine.Brief(base=DEFAULT, swap=0.0))
        assert sorted(free.swaps["six"]) == sorted(free.blue.blue)
        assert free.swaps["after"] == 100 and free.swaps["pairs"]
        assert free.swaps["status"] == "suggested"
        dear = engine.board(synthetic_world, draft, catalog=playbook,
                            brief=engine.Brief(base=DEFAULT, swap=SWAP_RANGE[1]))
        assert dear.swaps["pairs"] == [] and dear.swaps["after"] == dear.swaps["before"]
        assert dear.swaps["status"] == "keep"
        assert dear.swaps["verdict"] == "keep the picks: no swap gains its cost of 50 / 100"
        filled = [p["hero"] for p in dear.fill.picks if not p["locked"]] if dear.fill else []
        assert [o["hero"] for o in dear.swaps["open"]] == filled


def test_the_pairs_match_a_role_and_one_swap_taken_leaves_the_rest(synthetic_world):
    """Each pick dropped meets an incoming hero of its own role where the
    six has one, and carries its place among the picks as sent. The answer
    is joint: take one of its swaps and the board suggests the others, the
    same six."""
    playbook = catalog.load(FIXTURE_PLAYBOOK)
    draft = Draft("Salt Flats", ("Anvil", "Rook"),
                  ("Quarry", "Mortar", "Flint", "Gale", "Sorrel", "Tansy"))
    s = engine.board(synthetic_world, draft, catalog=playbook,
                     brief=engine.Brief(base=DEFAULT, swap=5.0)).swaps
    assert len(s["pairs"]) >= 2
    role = {h.name: h.role for h in synthetic_world.heroes.values()}
    for pair in s["pairs"]:
        assert draft.blue[pair["at"]] == pair["out"]
        assert role[pair["in"]] == role[pair["out"]]
    first, rest = s["pairs"][0], s["pairs"][1:]
    picks = list(draft.blue)
    picks[first["at"]] = first["in"]
    after = engine.board(synthetic_world, dataclasses.replace(draft, blue=tuple(picks)),
                         catalog=playbook, brief=engine.Brief(base=DEFAULT, swap=5.0)).swaps
    assert sorted(after["six"]) == sorted(s["six"])
    assert [(p["out"], p["in"], p["at"]) for p in after["pairs"]] == [
        (p["out"], p["in"], p["at"]) for p in rest]


def test_the_keep_term_is_never_a_term_of_a_payload_and_the_share_is_the_evaluations(
        synthetic_world):
    """The keep term ranks the search and nothing else: no payload, fact or
    rendered board names it, and the six the swaps make is scored as the
    board would evaluate it - its score and its share on blue's optimal
    exactly an evaluation's."""
    playbook = catalog.load(FIXTURE_PLAYBOOK)
    draft = BOARDS["full"]
    board = engine.board(synthetic_world, draft, catalog=playbook,
                         brief=engine.Brief(base=DEFAULT, swap=5.0))
    s = board.swaps
    assert s["pairs"]
    payload = json.dumps(board.to_dict(), ensure_ascii=False)
    assert "keep" not in {c["id"] for c in board.current.contributions}
    assert "swap.keep" not in payload and "swap.keep" not in board.rendered()
    assert "swaps: " + s["verdict"] in board.rendered()
    six = evaluated(synthetic_world, dataclasses.replace(draft, blue=tuple(s["six"])),
                    catalog=playbook)
    assert six.share() == s["after"]
    assert s["before"] == board.momentum["blue"] and s["odds"]["before"] == board.momentum["odds"]
    assert s["odds"]["after"] is not None


def test_a_board_without_blue_picks_or_asked_for_none_has_no_swaps(synthetic_world):
    """No blue picks, nothing to swap: the optimal already fills the slots.
    A brief that turns the swaps off leaves them out."""
    playbook = catalog.load(FIXTURE_PLAYBOOK)
    open_board = engine.board(synthetic_world, Draft("Harbor Gate", ("Mortar",)),
                              catalog=playbook, brief=engine.Brief(base=DEFAULT, swap=5.0))
    assert open_board.swaps is None and open_board.to_dict()["swaps"] is None
    off = engine.board(synthetic_world, BOARDS["full"], catalog=playbook,
                       brief=engine.Brief(base=DEFAULT, swap=5.0, swaps=False))
    assert off.swaps is None


def test_the_swap_cost_in_force_is_the_weights_then_the_brief_then_meta_md():
    """A board's weights' swap (the Swap cost slider) comes first, then the
    brief's own, then the playbook in force's meta.md."""
    assert engine.swap_in_force(engine.Brief(weights={SWAP: 3.0}, swap=7.0)) == 3.0
    assert engine.swap_in_force(engine.Brief(weights={"meta": 1.0}, swap=7.0)) == 7.0
    assert engine.swap_in_force(engine.Brief()) == catalog.swap_cost()


def test_the_raw_cost_is_share_points_of_the_span():
    """A share point is a hundredth of the optimal's lead over the floor; a
    seat with no lead is unscored and has no raw cost."""
    assert swaps.raw_cost(10.0, Span(best=3.0, floor=1.0)) == pytest.approx(0.2)
    assert swaps.raw_cost(10.0, Span(best=1.0, floor=1.0)) is None
    assert swaps.raw_cost(10.0, Span(best=1.0, floor=None)) is None


def test_the_search_ranks_a_kept_hero_first_with_the_engine_off(synthetic_world):
    """With the default engine off the keep term is the bound's own part
    alone: the search still reaches the enumeration's order, around locks,
    and a cost past every other term keeps the picks."""
    playbook = catalog.load(FIXTURE_PLAYBOOK)
    draft = Draft("Harbor Gate", ("Mortar", "Gale"), ("Kite",), side="attack")
    solver = seated(synthetic_world, draft, playbook, OFF)
    solver.freeze_bounds()
    picks = synthetic_world.resolve(None, (), ("Kite", "Rook", "Balm", "Myrrh")).blue
    from inference.solver import Solver
    m, red, locked, banned = synthetic_world.resolve(draft.map_name, draft.red, draft.blue, ())
    kept = Solver(synthetic_world, m, red=red, locked=locked, banned=banned, side=draft.side,
                  catalog=playbook, base=OFF, keep=frozenset(h.id for h in picks), swap=100.0)
    kept.adopt_scale(solver)
    got = kept.solve(top=K).ranked
    assert verdicts(got) == verdicts(sorted(enumerated(kept), key=rank_key)[:K])
    assert {h.id for h in picks} <= set(got[0].key)


def test_a_swap_that_does_not_raise_the_fight_odds_is_withheld(synthetic_world, monkeypatch):
    """The odds after are read off red solved again against the six the
    swaps make; a swap is suggested only where they rise, as the owner asked,
    and where they would not, the picks keep, the status says withheld and
    the verdict names the swaps it held back and the odds they would read."""
    playbook = catalog.load(FIXTURE_PLAYBOOK)
    draft = BOARDS["full"]
    brief = engine.Brief(base=DEFAULT, swap=5.0)
    offered = engine.board(synthetic_world, draft, catalog=playbook, brief=brief).swaps
    odds = offered["odds"]
    assert offered["pairs"] and odds["after"]["blue"] > odds["before"]["blue"]
    assert offered["status"] == "suggested"
    worse = {"odds": {"blue": 0, "red": 100}}
    monkeypatch.setattr(engine._Pass, "_against", lambda self, draft, six, blue: worse)
    held = engine.board(synthetic_world, draft, catalog=playbook, brief=brief).swaps
    assert held["pairs"] == [] and sorted(held["six"]) == sorted(draft.blue)
    assert held["status"] == "withheld"
    assert held["verdict"] == "keep the picks: the best swaps (%s) would not raise the fight odds" \
        " %d -> 0" % (", ".join("%s for %s" % (p["out"], p["in"]) for p in offered["pairs"]),
                      offered["odds"]["before"]["blue"])


def test_a_fill_out_of_budget_suggests_no_swap(synthetic_world, monkeypatch):
    """A half-drafted seat whose fill ran out of budget is no proof that no
    six keeps its picks: the swaps say they were not searched, and suggest
    nothing."""
    from inference.solver import Unbounded

    def spent(self, draft, **_):
        raise Unbounded("out of budget")
    monkeypatch.setattr(engine._Pass, "filled", spent)
    board = engine.board(synthetic_world, BOARDS["partial"], catalog=catalog.load(FIXTURE_PLAYBOOK),
                         brief=engine.Brief(base=DEFAULT, swap=5.0))
    assert board.swaps["status"] == "none" and board.swaps["pairs"] == []
    assert "not solved within the search's budget" in board.swaps["verdict"]
