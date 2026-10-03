"""board(): blue's seat solved and red's likely six read, never solved; the
weights it is given, the shapes and the queue's tank limit, an empty catalog
kept as the caller's, a limit red's reveal already breaks and blue's picks
may not, the share read from the seat's floor, the likely six, a full six on
control, every seat of a board on the stage it names, the page's boards
superseding one another, and the healing floor on top of the default
engine.
Every board is the synthetic World's but the last two, King's Row and
Samoa on the built database. test_board_gate holds the lobby's limits on every door."""

import pytest

from db import Refusal
from facts import compute
from facts.draft import MAX_TANKS, Draft
from facts.records import MapRate
from facts.team import team_metrics
from inference import catalog, engine
from inference.base import OFF
from inference.result import Momentum
from tests.verification.inference import (
    ASSUMPTIONS_ONLY,
    BRIEF,
    DEFAULT,
    FIXTURE_PLAYBOOK,
    SUPPORTS,
    hazard_playbook,
    heal_rate,
    support_limit,
)


def test_board_solves_blues_seat_and_reads_reds_likely_six(synthetic_world):
    """Blue's seat is solved and scored; red's is never optimized. Red reads as
    its likely six around its revealed picks, on the other side, with each
    pick's pull and no strategy read. The countered case alone solves red's
    best counter, as a what-if for blue."""
    from inference import engine
    world = synthetic_world
    fix = catalog.load(FIXTURE_PLAYBOOK)        # the reference playbook has the side rules
    b = engine.board(world, Draft("Harbor Gate", ("Mortar", "Gale"), ("Balm",), side="attack"),
                     catalog=fix, brief=BRIEF)
    blue, cur, likely = b.blue, b.current, b.expected
    assert blue.seat == "blue" and blue.kind == "infer" and blue.side == "attack"
    assert blue.locked == []
    absolute = engine.infer(world, Draft("Harbor Gate", ("Mortar", "Gale"), (), side="attack"),
                            catalog=fix, base=DEFAULT)
    assert blue.blue == absolute.blue                     # blue's optimal ignores your picks
    assert likely.seat == "red" and likely.side == "defense" and len(likely.blue) == 6
    assert likely.locked == ["Mortar", "Gale"] and likely.red == ["Balm"]
    assert {"Mortar", "Gale"} <= set(likely.blue) and likely.contributions == []
    assert all(p["pull"] >= 0 for p in likely.picks)
    assert cur.kind == "current" and cur.partial and cur.blue == ["Balm"]
    assert cur.contributions and cur.score is not None
    assert b.countered is not None and b.countered.kind == "countered"
    theirs = engine.infer(world, Draft("Harbor Gate", ("Balm",), (), side="defense"), catalog=fix,
                          base=DEFAULT)
    assert b.countered.red == theirs.blue               # blue against red's best counter
    fill = b.fill                                       # the empty slots, filled around Balm
    assert fill.kind == "fill"
    assert fill.locked == ["Balm"]
    assert len(fill.blue) == len(fill.picks) == 6
    assert "Balm" in fill.blue
    assert [p["locked"] for p in fill.picks].count(True) == 1
    assert 0 < fill.to_dict()["normalized"] <= 100
    around = engine.infer(world, Draft("Harbor Gate", ("Mortar", "Gale"), ("Balm",),
                                       side="attack"), catalog=fix, base=DEFAULT)
    assert fill.blue == around.blue
    mo = b.momentum
    assert set(mo) == set(Momentum.__annotations__) and mo["partial"]
    # blue is half-drafted, so its share is read through its fill - the best six
    # reachable from its picks - not off the picks alone; the current comp's dict
    # reports no share of its own. Red's badge is its likely six's pull
    assert mo["blue"] == fill.to_dict()["normalized"]
    assert cur.to_dict()["normalized"] is None
    assert mo["verdict"].startswith("blue %d / 100 of its optimal" % mo["blue"])
    assert "best counter" in mo["verdict"]
    pull = sum(p["pull"] for p in likely.picks)
    assert mo["badges"]["red"]["label"] == "%.0f pull" % pull
    # prose: the ground, what to play, them, the family
    plan = b.plan
    assert plan.startswith("Harbor Gate is a Hybrid map: a capture point and then the payload path")
    assert "You are attacking: you have to break their hold" in plan
    assert "Their 2 picks so far (Mortar, Gale)" in plan and "answer" in plan
    assert "If you stray from the six, stay in its family. Tanks: " in plan
    assert "Above all: " in plan
    assert plan.endswith("Based on: the Role Queue rates and counters, the map, the side,"
                         " your 1 pick, red's 2 revealed picks.")
    d = b.to_dict()
    assert d["side"] == "attack" and d["expected"]["seat"] == "red" and d["current"]["partial"]
    assert d["momentum"]["verdict"] == mo["verdict"]
    assert d["plan"] == plan
    assert d["fill"]["kind"] == "fill" and "the rest filled" in b.rendered()
    assert "current comp" in b.rendered() and "momentum:" in b.rendered()
    seats = (blue, cur, fill, b.countered, b.expected)
    assert not any("facts" in r.to_dict() for r in seats)      # no seat carries the facts
    # blue's side rule fires, and the other side's does not
    ids = {c["id"] for c in blue.contributions if c.get("applies")}
    assert "attack-breaks-the-hold" in ids and "defense-holds-the-ground" not in ids


def test_the_board_scores_under_the_weights_it_is_given(synthetic_world, harbor_gate_board):
    """A weight set on the board changes the score, every result says the
    weights it was scored under, and the file is untouched."""
    from inference import engine
    plain = harbor_gate_board
    fix = catalog.load(FIXTURE_PLAYBOOK)
    # a heuristic that actually moves this comp's score (one at the reference floor would not)
    moving = next(c["id"] for c in plain.current.contributions
                  if c["kind"] == "heuristic" and c.get("weighted"))
    heuristic = next(h for h in fix if h.id == moving)
    weights = {heuristic.id: 10.0 if heuristic.weight < 10 else 0.5}
    tilted = engine.board(synthetic_world,
                          Draft("Harbor Gate", ("Mortar", "Gale"), ("Balm", "Anvil")),
                          catalog=fix,
                          brief=engine.Brief(weights=weights, base=DEFAULT, search_swaps=False))
    assert tilted.current.to_dict()["weights"][heuristic.id] == weights[heuristic.id]
    assert plain.current.to_dict()["weights"][heuristic.id] == heuristic.weight
    assert tilted.current.score != plain.current.score
    assert next(h for h in catalog.load(FIXTURE_PLAYBOOK)
                if h.id == heuristic.id).weight == heuristic.weight


def test_legal_shapes_follow_the_playbook_and_the_board_carries_them(synthetic_world):
    """The roster enforces what the shape limits allow: the two-tank limit
    means no triple the solver would search seats a third tank, and the
    board says so in a form the script can read."""
    from inference import engine
    from inference.shapes import Shape, legal_shapes
    cat = catalog.load(FIXTURE_PLAYBOOK)
    shapes = legal_shapes(cat)
    assert shapes and all(t + d + s == 6 for t, d, s in shapes)
    assert (2, 2, 2) in shapes and all(t <= 2 for t, _, _ in shapes)
    assert (3, 2, 1) not in shapes
    seated = legal_shapes(cat, Shape(tanks=2, damage=3, supports=0))
    assert seated and all(t == 2 and d >= 3 for t, d, _ in seated)
    b = engine.board(synthetic_world, Draft("Harbor Gate", ("Mortar",), ("Balm",)), catalog=cat,
                     brief=BRIEF)
    assert b.shapes == [list(s) for s in shapes]
    d = b.to_dict()
    assert d["shapes"] == b.shapes
    # red's likely six rides along, around red's revealed pick
    assert d["expected"]["kind"] == "expected" and d["expected"]["locked"] == ["Mortar"]
    assert len(d["expected"]["picks"]) == 6 and all(p["why"] for p in d["expected"]["picks"])
    assert [p["hero"] for p in d["expected"]["picks"] if p["locked"]] == ["Mortar"]


def test_the_queue_caps_tanks_at_two_whatever_the_playbook_holds(synthetic_world):
    """A playbook of assumptions alone writes no shape limit and scores
    nothing, so every six ties and the map's win rates rank the pools - tanks, once every tank
    here wins ten points more. The queue's own limit binds all the same: no
    six the board shows fields a third tank, the shapes the roster enforces
    stop at two, and a third tank is refused as the queue's."""
    from inference import engine
    world = synthetic_world
    for h in world.heroes.values():
        if h.role == "tank":
            h.win += 10
            h.map_rates = {mid: MapRate(r.win + 10, r.pick) for mid, r in h.map_rates.items()}
    assert not any(h.form == "limit" for h in ASSUMPTIONS_ONLY)      # the cap is the engine's
    for map_name, blue in (("Harbor Gate", []), ("Ember Ruins", []),
                           ("Harbor Gate", ["Anvil", "Kite"])):
        d = engine.board(world, Draft(map_name, (), tuple(blue)),
                         catalog=ASSUMPTIONS_ONLY, brief=BRIEF).to_dict()
        sixes = [d[seat]["blue"] for seat in ("blue", "fill", "expected") if d[seat]]
        assert len(sixes) == (3 if blue else 2)
        for six in sixes:
            assert sum(world.hero(n).role == "tank" for n in six) <= MAX_TANKS, (map_name, six)
        assert max(t for t, _, _ in d["shapes"]) == MAX_TANKS
    for blue in (["Anvil", "Kite", "Mortar"], ["Anvil", "Kite", "Mortar", "Balm"],
                 ["Anvil", "Kite", "Mortar", "Balm", "Tansy", "Needle"]):
        with pytest.raises(Refusal, match="the queue allows at most 2 tanks"):
            engine.board(world, Draft("Harbor Gate", (), tuple(blue)),
                         catalog=ASSUMPTIONS_ONLY, brief=BRIEF)


NOT_ALLOWED = "not allowed: breaks At most three supports"


def test_red_may_reveal_what_a_limit_forbids(synthetic_world, tmp_path):
    """A limit binds the sixes the playbook builds and blue's own picks, never
    red's: red is never optimized or scored, so picks past a limit are its
    likely six's as they stand, and its badge is their pull. The limit reads
    a dial and is still a shape limit, so the shapes the board carries stop
    at three supports. A draft beside the limit is named, not scored."""
    from inference import engine
    world, cat = synthetic_world, support_limit(tmp_path)
    d = engine.board(world, Draft("Harbor Gate", SUPPORTS), catalog=cat, brief=BRIEF).to_dict()
    assert sum(world.hero(n).role == "support" for n in d["blue"]["blue"]) <= 3
    assert d["expected"]["locked"] == list(SUPPORTS) and set(SUPPORTS) <= set(d["expected"]["blue"])
    assert d["momentum"]["badges"]["red"]["label"].endswith(" pull")
    assert d["shapes"] and max(supports for _, _, supports in d["shapes"]) == 3
    (tmp_path / "a-draft.md").write_text(
        "---\nname: A draft\nkind: heuristic\n---\nprose\n", "utf-8")
    six = ("Anvil", "Mortar", *SUPPORTS)
    b = engine.board(world, Draft("Harbor Gate", six), catalog=catalog.load(str(tmp_path)),
                     brief=BRIEF)
    assert b.expected.blue == list(six) and b.expected.locked == list(six)
    assert b.blue.to_dict()["pending"] == ["a-draft"]
    assert "  drafts not yet scored (run /strategy): a-draft" in b.rendered()


def test_blue_picks_that_break_a_limit_are_not_allowed_and_the_board_still_renders(
        synthetic_world, tmp_path):
    """Constraints cut the space for blue's own picks too. Four supports under
    a three-support limit leave no six that keeps them: the fill is not
    solved, the board does not error, and blue's current comp is not
    allowed - no score, no share, the limit named in its reason and its
    badge, its breakdown the limit alone. Blue's optimal still renders.
    A full six that breaks it reads the same, ranked against nothing, and
    the plan describes the optimal. Three supports keep the limit and
    score."""
    from inference import engine
    world, cat = synthetic_world, support_limit(tmp_path)
    b = engine.board(world, Draft("Harbor Gate", (), SUPPORTS), catalog=cat, brief=BRIEF)
    d = b.to_dict()
    cur = d["current"]
    assert cur["unscored"] == NOT_ALLOWED and cur["scoring"] is False and cur["partial"]
    assert cur["score"] is None and cur["normalized"] is None and cur["rank"] is None
    assert [(c["id"], c["ok"]) for c in cur["contributions"]] == [("three-supports", False)]
    assert d["fill"] is None and d["countered"] is None
    assert len(d["blue"]["blue"]) == 6 and d["blue"]["normalized"] == 100
    assert sum(world.hero(n).role == "support" for n in d["blue"]["blue"]) <= 3
    mo = d["momentum"]
    assert mo["blue"] is None and mo["countered"] is None
    assert mo["badges"]["blue"] == {"label": "not allowed", "tip": NOT_ALLOWED}
    assert mo["verdict"].startswith("blue " + NOT_ALLOWED)
    assert "NOT ALLOWED: breaks At most three supports" in b.current.rendered()
    six = (*SUPPORTS, "Anvil", "Rook")
    b = engine.board(world, Draft("Harbor Gate", ("Mortar",), six), catalog=cat, brief=BRIEF)
    full = b.to_dict()
    assert full["current"]["kind"] == "evaluate" and full["current"]["unscored"] == NOT_ALLOWED
    assert full["current"]["score"] is None and full["current"]["alternatives"] == []
    assert full["momentum"]["blue"] is None
    assert b.fill is None and b.countered is None
    assert "The six is the one you picked." not in b.plan
    kept = engine.board(world, Draft("Harbor Gate", ("Mortar",), SUPPORTS[:3]), catalog=cat,
                        brief=BRIEF)
    assert kept.current.barred is None and kept.fill is not None
    assert kept.momentum["blue"] is not None


def test_a_half_drafted_seat_may_break_a_limit_its_picks_to_come_can_mend(
        synthetic_world, tmp_path):
    """Under Role Queue's two-two-two a single tank breaks the limit as it
    stands, and the picks to come can mend it: the fill is solved and the
    comp is allowed, its breach listed as one to mend."""
    from inference import engine
    (tmp_path / "role-queue.md").write_text(
        "---\nname: Role queue\nkind: constraint\nrequire: team.tanks == 2 and team.damage == 2"
        " and team.supports == 2\n---\nx\n", encoding="utf-8")
    b = engine.board(synthetic_world, Draft("Harbor Gate", ("Mortar",), ("Anvil",)),
                     catalog=catalog.load(str(tmp_path)), brief=BRIEF)
    assert b.current.barred is None and b.current.violations == ["role-queue"]
    assert b.fill is not None and b.momentum["blue"] is not None


def test_picks_are_ruled_out_exactly_when_no_six_on_the_roster_completes_them(
        synthetic_world, tmp_path):
    """The fill searches every six on the roster that keeps the picks, so an
    empty answer is a proof. Under a limit on the kit - a light flier
    fielded, and Gale the only one - picks whose one completion seats Gale
    are allowed and filled with her, their breach listed as one to mend.
    Capped at two damage, the open slot is a support's, no six completes
    them, and they are not allowed, the limit they break named - by the
    board and by infer alike."""
    from inference import engine
    (tmp_path / "air.md").write_text(
        "---\nname: A light flier\nkind: constraint\nrequire: team.light_flyers >= 1\n---\nx\n",
        "utf-8")
    picks = Draft("Harbor Gate", ("Kite",), ("Anvil", "Mortar", "Rook", "Needle", "Balm"))
    b = engine.board(synthetic_world, picks, catalog=catalog.load(str(tmp_path)), brief=BRIEF)
    assert b.fill is not None and "Gale" in b.fill.blue and b.current.barred is None
    assert b.current.violations == ["air"] and b.momentum["blue"] is not None
    (tmp_path / "two-damage.md").write_text(
        "---\nname: Two damage\nkind: constraint\nrequire: team.damage <= 2\n---\nx\n", "utf-8")
    capped = catalog.load(str(tmp_path))
    b = engine.board(synthetic_world, picks, catalog=capped, brief=BRIEF)
    assert b.fill is None and b.current.barred == "not allowed: breaks A light flier"
    assert "Gale" in b.blue.blue
    with pytest.raises(Refusal, match=r"^not allowed: breaks A light flier$"):
        engine.infer(synthetic_world, picks, catalog=capped, base=DEFAULT)


BRAWL = ("Anvil", "Mortar", "Rook", "Needle", "Balm", "Myrrh")
DIVE = ("Kite", "Quarry", "Gale", "Flint", "Sorrel", "Tansy")


def test_a_share_is_read_from_the_seats_floor_so_a_six_below_zero_still_holds_one(
        synthetic_world):
    """Scores are signed: the default engine counts each pick's edge over 50.
    On Harbor Gate under the engine alone the dive six scores below zero
    against the brawl six, and read from zero it was 0 / 100. Read from the
    seat's floor - the lowest of its reference sixes - it holds a share
    above 0, and the optimal is still 100."""
    from inference import engine
    from inference.result import _pct
    b = engine.board(synthetic_world, Draft("Harbor Gate", BRAWL, DIVE), catalog=ASSUMPTIONS_ONLY,
                     brief=BRIEF)
    cur = b.current
    assert cur.score < 0
    assert _pct(cur.score, cur.best, 0.0) == 0                         # the old zero anchor
    assert cur.floor is not None and cur.floor < cur.score < cur.best == b.blue.score
    assert cur.floor == b.blue.floor
    share = round(100.0 * (cur.score - cur.floor) / (cur.best - cur.floor))
    mo = b.momentum
    assert mo["blue"] == cur.share() == share and 0 < share < 100
    assert b.to_dict()["blue"]["normalized"] == 100


def test_an_empty_catalog_is_the_callers_and_loads_no_playbook(synthetic_world, monkeypatch):
    """Only a catalog left out is the playbook in force: [] is the caller's
    own, and scores nothing."""
    from inference import engine

    def load(directory=None):
        raise AssertionError("the playbook was loaded")
    monkeypatch.setattr(engine.catalog_module, "load", load)
    result = engine.infer(synthetic_world, Draft("Harbor Gate"), catalog=[], top=1, base=DEFAULT)
    assert len(result.blue) == 6 and result.catalog == []
    b = engine.board(synthetic_world, Draft("Harbor Gate"), catalog=[], brief=BRIEF)
    assert len(b.blue.blue) == 6 and b.blue.catalog == []


def test_blue_counters_the_likely_six_until_red_reveals_a_pick(synthetic_world):
    """With no red pick, blue's seat reads red's likely six through the
    default engine's counter term alone, as infer does: red is its revealed
    picks, none, so the opening suggestion is infer's own six, and every
    other term - the healing floor among them - reads an empty red. The
    first reveal replaces the likely six with red's actual picks, and red's
    likely six fills in around them."""
    from inference import base, engine
    world = synthetic_world
    fix = catalog.load(FIXTURE_PLAYBOOK)
    m = world.map("Harbor Gate")
    likely = [p["hero"] for p in compute.expected_picks(world, m)]
    b = engine.board(world, Draft("Harbor Gate", (), ("Balm",)), catalog=fix, brief=BRIEF)
    assert b.blue.red == [] and b.current.red == [] and b.fill.red == []
    for seat in (b.blue, b.current, b.fill):
        [c] = [c for c in seat.contributions if c["id"] == base.COUNTERS]
        assert c["likely"] and c["against"] == likely, seat.kind
    infer = engine.infer(world, Draft("Harbor Gate"), catalog=fix, base=DEFAULT)
    assert b.blue.blue == infer.blue and abs(b.blue.score - infer.score) < 1e-9
    assert b.expected.blue == likely and b.expected.kind == "expected"
    assert [p["hero"] for p in b.expected.picks] == likely
    assert "their likely starting comp" in b.rendered()
    revealed = engine.board(world, Draft("Harbor Gate", ("Mortar",), ("Balm",)), catalog=fix,
                            brief=BRIEF)
    assert revealed.blue.red == ["Mortar"] and revealed.current.red == ["Mortar"]
    around = [p["hero"] for p in compute.expected_picks(world, m, revealed=[world.hero("Mortar")])]
    assert revealed.expected.blue == around and revealed.expected.locked == ["Mortar"]


def test_board_ranks_a_full_six_and_ignores_sides_on_control(synthetic_world):
    """A full six on a control map is ranked among every legal six - the
    optimal's third alternative is fourth - and the side a caller names
    is dropped: control has none. A weak six ranks outside RANK_CAP."""
    from inference import engine
    world = synthetic_world
    fix = catalog.load(FIXTURE_PLAYBOOK)
    first = engine.board(world, Draft("Ember Ruins", ("Gale",)), catalog=fix, brief=BRIEF)
    six = first.blue.alternatives[2]["blue"]
    b = engine.board(world, Draft("Ember Ruins", ("Gale",), tuple(six), side="attack"),
                     catalog=fix, brief=BRIEF)
    assert b.side == "" and b.blue.side == "" and b.expected.side == ""
    assert b.current.kind == "evaluate" and b.current.rank == 4 and not b.current.outranked
    assert "(rank 4 among the legal sixes)" in b.current.rendered()
    assert set(b.current.blue) == set(six)
    weak = ("Anvil", "Mortar", "Rook", "Needle", "Balm", "Tansy")
    outside = engine.board(world, Draft("Ember Ruins", ("Gale",), weak), catalog=fix,
                           brief=BRIEF).current
    assert outside.rank is None and outside.outranked and outside.to_dict()["outranked"]
    assert "(outside the top 100 of the legal sixes)" in outside.rendered()
    assert b.blue.locked == [] and b.blue.to_dict()["normalized"] == 100
    assert 0 <= b.current.to_dict()["normalized"] <= 100      # against the absolute optimal
    b = engine.board(world, Draft(), catalog=fix, brief=BRIEF)
    assert not b.current.blue and b.current.partial
    # nothing locked: the optimal is the fill
    assert b.countered is None and b.fill is None
    assert b.momentum["verdict"].startswith("no blue picks yet: the suggested six is blue's")
    assert b.momentum["blue"] is None
    assert b.plan.startswith("No map yet, so this is the meta's best six")
    assert b.plan.endswith("Based on: the Role Queue rates and counters.")
    assert len(b.blue.blue) == 6                      # the meta's best six, before any map
    b = engine.board(world, Draft("Ember Ruins", (), (), ("Needle",)), catalog=fix, brief=BRIEF)
    assert b.plan.endswith("the map, 1 ban.") and b.plan.count("\n") >= 2
    assert b.plan.startswith("Ember Ruins is a Control map: one point in three arenas")


def test_a_newer_board_from_the_same_client_supersedes_the_older_one(
        synthetic_world, scratch_playbook):
    """The page's boards take a ticket per client: a newer ticket supersedes
    the older one under the same name only, and a board whose ticket is
    superseded stops before its first search, in this process too."""
    from inference import engine, supersede
    latest = supersede.Latest()
    first, elsewhere = latest.take("tab-1"), latest.take("tab-2")
    assert not first() and not elsewhere()
    second = latest.take("tab-1")
    assert first() and not second() and not elsewhere()
    with pytest.raises(supersede.Superseded):
        engine.board(synthetic_world, Draft("Harbor Gate", ("Anvil",), ("Balm",)),
                     catalog=scratch_playbook, brief=engine.Brief(superseded=first, base=DEFAULT,
                                                        search_swaps=False))


def _shortfall(world, result):
    """matchup.heal_shortfall of a result's six against its red, as scored."""
    six = [world.hero(n) for n in result.blue]
    red = [world.hero(n) for n in result.red]
    return compute.matchup_metrics(world, team_metrics(world, six, None, red),
                                   team_metrics(world, red, None, ()))["heal_shortfall"]


def test_the_healing_floor_scores_on_top_of_the_engine_and_off_leaves_it_alone(
        synthetic_world, tmp_path):
    """The floor is a playbook term, not the engine's: under DEFAULT it sits
    on the three base terms, and under OFF it scores alone, the base terms
    gone and the rule's charge the whole score. Its bar cites the board's
    healing-floor fact. With the rule the optimal clears the floor; the
    engine alone does not see it, and OFF with the assumptions alone scores
    nothing."""
    from inference import engine
    w = synthetic_world
    heal = heal_rate(str(tmp_path))
    draft = Draft("Harbor Gate", side="attack")
    plain = engine.infer(w, draft, catalog=ASSUMPTIONS_ONLY, base=DEFAULT)
    floored = engine.infer(w, draft, catalog=heal, base=DEFAULT)
    terms = {c["id"]: c for c in floored.contributions}
    assert set(terms) == {"base.rates", "base.synergy", "base.counters", "heal-rate"}
    rule = terms["heal-rate"]
    assert rule["form"] == "scored" and rule["weighted"] == -2.0 * _shortfall(w, floored)
    assert rule["text"].startswith("healing floor: blue heals ")
    # the engine alone fields Kite and Anvil, Balm and Tansy: 115 a second on
    # 2325 against a need of 134.3; the floor trades Kite and Tansy for Mortar
    # and Myrrh and clears it
    assert _shortfall(w, plain) > 0.1 and _shortfall(w, floored) == 0.0
    alone = engine.infer(w, draft, catalog=heal, base=OFF)
    assert [c["id"] for c in alone.contributions] == ["heal-rate"]
    assert alone.score == -2.0 * _shortfall(w, alone) == 0.0
    assert any(s.weighs for s in heal) and not any(s.weighs for s in ASSUMPTIONS_ONLY)
    assert DEFAULT.on and not OFF.on


@pytest.mark.invariant
def test_the_healing_floor_takes_kings_row_off_one_support(world, tmp_path):
    """King's Row attack, red empty: the default engine alone fields one
    support, Zenyatta on D.Mon, Reinhardt, Genji, Hanzo and Widowmaker,
    0.76 under the floor - D.Mon in Vendetta's seat since a synergy pair no
    article writes reads the written pairs' mean. The shipped floor
    (HEAL_RATE, written to a folder of its own) seats a second support,
    Juno, and leaves the six under 0.15."""
    from inference import engine
    draft = Draft("King's Row", side="attack")
    plain = engine.infer(world, draft, catalog=ASSUMPTIONS_ONLY, base=DEFAULT)
    floored = engine.infer(world, draft, catalog=heal_rate(str(tmp_path)), base=DEFAULT)

    def supports(result):
        return sum(1 for n in result.blue if world.hero(n).role == "support")

    assert supports(plain) == 1 and _shortfall(world, plain) > 0.5
    assert supports(floored) >= 2 and _shortfall(world, floored) < 0.15


@pytest.mark.invariant
def test_the_search_proves_real_boards_scoring_few_sixes_in_full(world):
    """On the built database the bound is tight enough that the exact search
    proves a seat's best sixes out of 17 million legal ones while scoring
    a few dozen in full - Samoa against five revealed picks, and King's
    Row with nothing revealed - and the whole space is what it covered. The
    ceilings are two orders of magnitude over what the boards take, so a
    data refresh moves the counts and not the verdict; a bound gone slack
    fails it."""
    from inference import catalog as catalog_module
    from inference.solver import Solver
    for map_name, red, side in (
            ("Samoa", ("D.Va", "Roadhog", "Sombra", "Lúcio", "Brigitte"), ""),
            ("King's Row", (), "attack")):
        m, red_h, _, _ = world.resolve(map_name, red, (), ())
        solver = Solver(world, m, red=red_h, locked=[], side=side,
                        catalog=catalog_module.load(), base=catalog_module.engine_weights())
        solved = solver.solve(top=6)
        released = sum(1 for h in world.heroes.values() if h.released)
        assert len(solved.ranked) == 6 and solver.considered > released ** 3
        assert solver.leaves < 2_000 and solver.nodes < 100_000, (map_name, solver.leaves)



def test_every_seat_of_a_board_plays_the_stage_it_names(synthetic_world, tmp_path):
    """A board on a stage solves every result there - blue's optimal and
    current comp, the fill, the countered case and red's likely six - so the
    two sides fight on one ground: a rule the stage's terrain turns on
    applies to blue's sixes and to the countered case's, each six keeps the
    limit it turns on, and the rule cites the ground in play's fact. The whole map turns
    the rule off, and a stage the map does not list is refused."""
    world = synthetic_world
    (tmp_path / "hazard-ground.md").write_text(
        "---\nname: Hazards pay\nkind: heuristic\nweight: 0.5\n"
        "bonus: 1 if map.hazards >= 1.5 else 0\n---\nOn the ground in play.\n",
        encoding="utf-8")
    playbook = hazard_playbook(world, tmp_path)
    b = engine.board(world, Draft("Ember Ruins", ("Mortar",), ("Anvil",), stage="forge"),
                     catalog=playbook, brief=BRIEF)
    seats = (b.blue, b.current, b.fill, b.countered, b.expected)
    assert b.stage == "Forge" and {r.stage for r in seats} == {"Forge"}
    assert b.to_dict()["stage"] == b.to_dict()["blue"]["stage"] == "Forge"
    for r in (b.blue, b.fill, b.countered):
        terms = {c["id"]: c for c in r.contributions}
        assert terms["hazard-cc"]["applies"] and terms["hazard-cc"]["raw"] >= 1
        assert terms["hazard-ground"]["bonus"] == 1
        assert terms["hazard-ground"]["text"].startswith(
            "Ember Ruins - Forge is the ground in play: hazards 2.5")
    assert " on Ember Ruins - Forge vs " in b.blue.rendered()
    whole = engine.board(world, Draft("Ember Ruins", ("Mortar",), ("Anvil",)),
                         catalog=playbook, brief=BRIEF)
    assert whole.stage == "" and {r.stage for r in (whole.blue, whole.expected)} == {""}
    for r in (whole.blue, whole.fill):
        terms = {c["id"]: c for c in r.contributions}
        assert not terms["hazard-cc"]["applies"] and terms["hazard-ground"]["bonus"] == 0
        assert "text" not in terms["hazard-ground"]
    with pytest.raises(Refusal, match="its stages: Courtyard, Forge, Spire"):
        engine.board(world, Draft("Ember Ruins", stage="Well"), catalog=playbook, brief=BRIEF)
    with pytest.raises(Refusal, match="its stages: Courtyard, Forge, Spire"):
        engine.infer(world, Draft("Ember Ruins", stage="Well"), catalog=playbook, base=DEFAULT)
