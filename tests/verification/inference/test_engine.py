"""board(): both seats on opposite sides, the weights it is given, the fight
odds, the shapes and the queue's tank limit, an empty catalog kept as the
caller's, a limit red's reveal already breaks and blue's picks may not, the
share read from the seat's floor and a mirror's even odds, the likely six, a
full six on control, every seat of a board on the synthetic World and on
the stage it names, the page's boards superseding one another, and the
healing floor on top of the default engine.
Every board is the synthetic World's but the last two, King's Row and
Samoa on the built database. test_board_gate holds the lobby's limits on every door."""

import os

import pytest

from db import Refusal
from facts import compute
from facts.draft import MAX_TANKS, Draft
from facts.records import MapRate
from facts.team import team_metrics
from inference import catalog, engine
from inference.base import OFF
from tests.verification.inference import (
    ASSUMPTIONS_ONLY,
    BRIEF,
    DEFAULT,
    FIXTURE_PLAYBOOK,
    heal_rate,
)


def test_board_solves_both_seats_on_opposite_sides_and_scores_the_current(synthetic_world):
    from inference import engine
    world = synthetic_world
    fix = catalog.load(FIXTURE_PLAYBOOK)        # the reference playbook has the side rules
    b = engine.board(world, Draft("Harbor Gate", ("Mortar", "Gale"), ("Balm",), side="attack"),
                     catalog=fix, brief=BRIEF)
    blue, red, cur = b.blue, b.red, b.current
    assert blue.seat == "blue" and blue.side == "attack" and blue.locked == []
    absolute = engine.infer(world, Draft("Harbor Gate", ("Mortar", "Gale"), (), side="attack"),
                            catalog=fix, base=DEFAULT)
    assert blue.blue == absolute.blue                     # blue's optimal ignores your picks
    assert red.seat == "red" and red.side == "defense" and len(red.blue) == 6
    # red's optimal: their best counter to ours
    assert red.locked == [] and red.red == ["Balm"]
    theirs = engine.infer(world, Draft("Harbor Gate", ("Balm",), (), side="defense"), catalog=fix,
                          base=DEFAULT)
    assert red.blue == theirs.blue
    assert cur.kind == "current" and cur.partial and cur.blue == ["Balm"]
    assert cur.contributions and cur.score is not None
    rc = b.red_current                                  # their comp as revealed, scored vs ours
    assert rc.seat == "red"
    assert set(rc.blue) == {"Mortar", "Gale"}
    assert rc.red == ["Balm"]
    assert rc.partial
    assert rc.to_dict()["normalized"] is None        # a partial team has no share
    assert b.countered is not None and b.countered.kind == "countered"
    fill = b.fill                                       # the empty slots, filled around Balm
    assert fill.kind == "fill"
    assert fill.locked == ["Balm"]
    assert len(fill.blue) == 6
    assert "Balm" in fill.blue
    assert [p["locked"] for p in fill.picks].count(True) == 1
    assert 0 < fill.to_dict()["normalized"] <= 100
    around = engine.infer(world, Draft("Harbor Gate", ("Mortar", "Gale"), ("Balm",),
                                       side="attack"), catalog=fix, base=DEFAULT)
    assert fill.blue == around.blue
    mo = b.momentum
    assert set(mo) >= {"blue", "red", "countered", "verdict", "partial"} and mo["partial"]
    # each seat is half-drafted, so its share is read through its fill - the best
    # six reachable from its picks - not off the picks alone; both current comps'
    # dicts report no share of their own.
    assert mo["blue"] == fill.to_dict()["normalized"]
    assert mo["red"] is not None
    assert cur.to_dict()["normalized"] is None and rc.to_dict()["normalized"] is None
    assert ("ahead by" in mo["verdict"] or mo["verdict"].startswith("even"))
    assert "best counter" in mo["verdict"]
    # prose: the ground, what to play, them, the family
    plan = b.plan
    assert plan.startswith("Harbor Gate is a Hybrid map: a capture point and then the payload path")
    assert "You are attacking: you have to break their hold" in plan
    assert "The map rewards %s" % world.map("Harbor Gate").style_top in plan
    assert "Their 2 picks so far (Mortar, Gale)" in plan and "answer" in plan
    assert "If you stray from the six, stay in its family. Tanks: " in plan
    assert "Above all: " in plan
    assert plan.endswith("Based on: the Role Queue rates and counters, the map, the side,"
                         " your 1 pick, red's 2 revealed picks.")
    d = b.to_dict()
    assert d["side"] == "attack" and d["red"]["seat"] == "red" and d["current"]["partial"]
    assert d["red_current"]["seat"] == "red"
    assert d["momentum"]["verdict"] == mo["verdict"]
    assert d["plan"] == plan
    assert d["fill"]["kind"] == "fill" and "the rest filled" in b.rendered()
    assert "current comp" in b.rendered() and "momentum:" in b.rendered()
    # the side constraints fire on the right seat
    ids = {c["id"] for c in blue.contributions if c.get("applies")}
    assert "attack-breaks-the-hold" in ids and "defense-holds-the-ground" not in ids
    ids = {c["id"] for c in red.contributions if c.get("applies")}
    assert "defense-holds-the-ground" in ids


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


def test_fight_odds_pit_the_two_shares_against_each_other(synthetic_world, harbor_gate_board):
    """Both seats scored: each side's odds are its share over the two shares'
    sum, the pair splits 100, and the verdict says so; one seat unscored or
    empty: no odds."""
    from inference import engine
    b = harbor_gate_board.to_dict()
    mo = b["momentum"]
    n, m = mo["blue"], mo["red"]
    assert isinstance(n, int) and isinstance(m, int) and n + m > 0
    blue_odds = round(100.0 * n / (n + m))
    assert mo["odds"] == {"blue": blue_odds, "red": 100 - blue_odds}
    assert "fight odds blue %d%%, red %d%%" % (blue_odds, 100 - blue_odds) in mo["verdict"]
    alone = engine.board(synthetic_world, Draft("Harbor Gate", ("Mortar", "Gale")),
                         catalog=catalog.load(FIXTURE_PLAYBOOK), brief=BRIEF).to_dict()
    assert alone["momentum"]["blue"] is None and alone["momentum"]["odds"] is None


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
    # red's likely six rides along - static: the map and the meta, not their reveal
    assert d["expected"]["kind"] == "expected" and "Mortar" not in d["expected"]["blue"]
    assert len(d["expected"]["picks"]) == 6 and all(p["why"] for p in d["expected"]["picks"])
    assert not any(p["locked"] for p in d["expected"]["picks"])


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
        sixes = [d[seat]["blue"] for seat in ("blue", "red", "fill", "expected") if d[seat]]
        assert len(sixes) == (4 if blue else 3)
        for six in sixes:
            assert sum(world.hero(n).role == "tank" for n in six) <= MAX_TANKS, (map_name, six)
        assert max(t for t, _, _ in d["shapes"]) == MAX_TANKS
    for blue in (["Anvil", "Kite", "Mortar"], ["Anvil", "Kite", "Mortar", "Balm"],
                 ["Anvil", "Kite", "Mortar", "Balm", "Tansy", "Needle"]):
        with pytest.raises(Refusal, match="the queue allows at most 2 tanks"):
            engine.board(world, Draft("Harbor Gate", (), tuple(blue)),
                         catalog=ASSUMPTIONS_ONLY, brief=BRIEF)


SUPPORTS = ("Balm", "Myrrh", "Sorrel", "Tansy")
NOT_ALLOWED = "not allowed: breaks At most three supports"


def _support_limit(directory):
    """A playbook of one limit, at most three supports, written in `directory`
    on a dial, as the shipped rule writes it."""
    with open(os.path.join(directory, "three-supports.md"), "w", encoding="utf-8") as handle:
        handle.write("---\nname: At most three supports\nkind: constraint\n"
                     "require: team.supports <= params.MAX_SUPPORTS\nparams:\n"
                     "    MAX_SUPPORTS: 3\n---\n# At most three supports\n\n"
                     "A six fields at most three supports.\n")
    return catalog.load(str(directory))


def test_red_may_reveal_what_a_limit_forbids(synthetic_world, tmp_path):
    """A limit binds the sixes the playbook builds and blue's own picks, not
    the other side's revealed ones: red past it still gets its optimal and
    its current comp, read off its picks with no fill, and is never ruled
    out. The limit reads a dial and is still a shape limit, so the shapes
    the board carries stop at three supports. A full red six past it is
    scored, ranked and shared, and says which limit it breaks; a draft
    beside the limit is named, not scored."""
    from inference import engine
    world, cat = synthetic_world, _support_limit(tmp_path)
    d = engine.board(world, Draft("Harbor Gate", SUPPORTS), catalog=cat, brief=BRIEF).to_dict()
    for seat in ("blue", "red"):
        assert sum(world.hero(n).role == "support" for n in d[seat]["blue"]) <= 3, seat
    assert sorted(d["red_current"]["blue"]) == sorted(SUPPORTS)
    assert d["red_current"]["unscored"] is None and d["red_current"]["score"] is not None
    assert d["momentum"]["badges"]["red"]["label"] != "not allowed"
    assert d["shapes"] and max(supports for _, _, supports in d["shapes"]) == 3
    (tmp_path / "a-draft.md").write_text(
        "---\nname: A draft\nkind: heuristic\n---\nprose\n", "utf-8")
    b = engine.board(world, Draft("Harbor Gate", ("Anvil", "Mortar", *SUPPORTS)),
                     catalog=catalog.load(str(tmp_path)), brief=BRIEF)
    red = b.red_current.to_dict()
    assert red["kind"] == "evaluate" and red["violations"] == ["three-supports"]
    assert (red["rank"] is not None or red["outranked"]) and red["normalized"] is not None
    assert red["pending"] == ["a-draft"]
    text = b.rendered()
    assert "  VIOLATES: three-supports" in text
    assert "  drafts not yet scored (run /strategy): a-draft" in text


def test_blue_picks_that_break_a_limit_are_not_allowed_and_the_board_still_renders(
        synthetic_world, tmp_path):
    """Constraints cut the space for blue's own picks too. Four supports under
    a three-support limit leave no six that keeps them: the fill is not
    solved, the board does not error, and blue's current comp is not
    allowed - no score, no share, no odds, the limit named in its reason and
    its badge, its breakdown the limit alone. Blue's optimal still renders.
    A full six that breaks it reads the same, ranked against nothing, and
    the plan describes the optimal. Three supports keep the limit and
    score."""
    from inference import engine
    world, cat = synthetic_world, _support_limit(tmp_path)
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
    assert mo["blue"] is None and mo["odds"] is None and mo["countered"] is None
    assert mo["badges"]["blue"] == {"label": "not allowed", "tip": NOT_ALLOWED}
    assert mo["verdict"].startswith("blue " + NOT_ALLOWED)
    assert "NOT ALLOWED: breaks At most three supports" in b.current.rendered()
    six = (*SUPPORTS, "Anvil", "Rook")
    b = engine.board(world, Draft("Harbor Gate", ("Mortar",), six), catalog=cat, brief=BRIEF)
    full = b.to_dict()
    assert full["current"]["kind"] == "evaluate" and full["current"]["unscored"] == NOT_ALLOWED
    assert full["current"]["score"] is None and full["current"]["alternatives"] == []
    assert full["momentum"]["blue"] is None and full["momentum"]["odds"] is None
    assert b.fill is None and b.countered is None
    assert "The six is the one you picked." not in b.plan
    kept = engine.board(world, Draft("Harbor Gate", ("Mortar",), SUPPORTS[:3]), catalog=cat,
                        brief=BRIEF)
    assert kept.current.barred is None and kept.fill is not None
    assert kept.momentum["blue"] is not None and kept.momentum["odds"] is not None


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
    against the brawl six, which scores above it, and read from zero it was 0
    / 100 and the odds 0 to 100. Read from the seat's floor - the lowest of
    its reference sixes - it holds a share above 0, the odds sit strictly
    between, and the optimal is still 100."""
    from inference import engine
    from inference.result import _pct
    b = engine.board(synthetic_world, Draft("Harbor Gate", BRAWL, DIVE), catalog=ASSUMPTIONS_ONLY,
                     brief=BRIEF)
    cur = b.current
    assert cur.score < 0 < b.red_current.score
    assert _pct(cur.score, cur.best, 0.0) == 0                         # the old zero anchor
    assert cur.floor is not None and cur.floor < cur.score < cur.best == b.blue.score
    assert cur.floor == b.blue.floor
    share = round(100.0 * (cur.score - cur.floor) / (cur.best - cur.floor))
    mo = b.momentum
    assert mo["blue"] == cur.share() == share and 0 < share < 100
    assert 0 < mo["odds"]["blue"] < 100 and mo["odds"]["blue"] + mo["odds"]["red"] == 100
    assert b.to_dict()["blue"]["normalized"] == 100


def test_a_mirror_reads_even(synthetic_world):
    """The same six on both sides of a map with no sides is the same board
    from either seat: the same optimal, the same floor, the same share, and
    even odds."""
    from inference import engine
    b = engine.board(synthetic_world, Draft("Ember Ruins", BRAWL, BRAWL), catalog=ASSUMPTIONS_ONLY,
                     brief=BRIEF)
    assert b.current.floor == b.red_current.floor and b.current.best == b.red_current.best
    assert b.momentum["blue"] == b.momentum["red"]
    assert b.momentum["odds"] == {"blue": 50, "red": 50}


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
    """With no red pick the board solves blue against red's likely six, so the
    opening suggestion is a counter to what the map and the meta say red
    fields; the first reveal replaces that with red's actual picks."""
    from inference import engine
    world = synthetic_world
    fix = catalog.load(FIXTURE_PLAYBOOK)
    m = world.map("Harbor Gate")
    likely = [p["hero"] for p in compute.expected_picks(world, m)]
    b = engine.board(world, Draft("Harbor Gate", (), ("Balm",)), catalog=fix, brief=BRIEF)
    assert b.blue.red == likely and b.current.red == likely and b.fill.red == likely
    assert b.expected.blue == likely and b.expected.kind == "expected"
    assert [p["hero"] for p in b.expected.picks] == likely
    assert "their likely starting comp" in b.rendered()
    revealed = engine.board(world, Draft("Harbor Gate", ("Mortar",), ("Balm",)), catalog=fix,
                            brief=BRIEF)
    assert revealed.blue.red == ["Mortar"] and revealed.current.red == ["Mortar"]
    assert revealed.expected.blue == likely                      # static


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
    assert b.side == "" and b.blue.side == "" and b.red.side == ""
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
    assert b.momentum["verdict"] == "no picks yet on either side"
    assert b.momentum["blue"] is None and b.momentum["red"] is None
    assert b.plan.startswith("No map yet, so this is the meta's best six")
    assert b.plan.endswith("Based on: the Role Queue rates and counters.")
    assert len(b.blue.blue) == 6                      # the meta's best six, before any map
    b = engine.board(world, Draft("Ember Ruins", (), (), ("Needle",)), catalog=fix, brief=BRIEF)
    assert b.plan.endswith("the map, 1 ban.") and b.plan.count("\n") >= 2
    assert b.plan.startswith("Ember Ruins is a Control map: one point in three arenas")
    assert "The map rewards %s" % world.map("Ember Ruins").style_top in b.plan


def test_a_board_on_the_synthetic_world_holds_every_seat(synthetic_world, scratch_playbook):
    """With red revealed and one blue pick locked, a board holds all seven
    seats, each what its kind says, with no database: blue's optimal, red's
    on the other side of a sided map, the two current comps, the fill around
    the lock and the countered case. Without a blue pick there is no fill and
    no countered case."""
    from inference import engine
    from inference.result import Momentum
    from inference.shapes import legal_shapes
    b = engine.board(synthetic_world, Draft("Harbor Gate", ("Anvil",), ("Balm",), side="attack"),
                     catalog=scratch_playbook, brief=BRIEF)
    assert b.blue.kind == "infer" and b.blue.side == "attack"
    assert b.red.seat == "red" and b.red.side == "defense"
    assert b.current.partial and b.current.blue == ["Balm"]
    assert b.fill.kind == "fill" and len(b.fill.picks) == 6 and "Balm" in b.fill.blue
    assert b.countered.kind == "countered" and b.countered.red == b.red.blue
    assert set(b.momentum) == set(Momentum.__annotations__)
    assert b.plan.split("\n")[-1].startswith("Based on: ")
    assert b.shapes == [list(s) for s in legal_shapes(scratch_playbook)]
    seats = (b.blue, b.red, b.current, b.red_current, b.fill, b.countered, b.expected)
    assert not any("facts" in r.to_dict() for r in seats)
    alone = engine.board(synthetic_world, Draft("Harbor Gate", ("Anvil",), side="attack"),
                         catalog=scratch_playbook, brief=BRIEF)
    assert alone.fill is None and alone.countered is None


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
    """A board on a stage solves every seat there - both optimals, both
    current comps, the fill, the countered case and the likely six - so the
    two sides fight on one ground: a rule the stage's terrain turns on
    applies to red's seat as to blue's, each six keeps the limit it turns
    on, and the rule cites the ground in play's fact. The whole map turns
    the rule off, and a stage the map does not list is refused."""
    from tests.verification.inference.test_solver import hazard_playbook
    world = synthetic_world
    (tmp_path / "hazard-ground.md").write_text(
        "---\nname: Hazards pay\nkind: heuristic\nweight: 0.5\n"
        "bonus: 1 if map.hazards >= 1.5 else 0\n---\nOn the ground in play.\n",
        encoding="utf-8")
    playbook = hazard_playbook(world, tmp_path)
    b = engine.board(world, Draft("Ember Ruins", ("Mortar",), ("Anvil",), stage="forge"),
                     catalog=playbook, brief=BRIEF)
    seats = (b.blue, b.red, b.current, b.red_current, b.fill, b.countered, b.expected)
    assert b.stage == "Forge" and {r.stage for r in seats} == {"Forge"}
    assert b.to_dict()["stage"] == b.to_dict()["blue"]["stage"] == "Forge"
    for r in (b.blue, b.red, b.fill, b.countered):
        terms = {c["id"]: c for c in r.contributions}
        assert terms["hazard-cc"]["applies"] and terms["hazard-cc"]["raw"] >= 1
        assert terms["hazard-ground"]["bonus"] == 1
        assert terms["hazard-ground"]["text"].startswith(
            "Ember Ruins - Forge is the ground in play: hazards 2.5")
    assert " on Ember Ruins - Forge vs " in b.blue.rendered()
    whole = engine.board(world, Draft("Ember Ruins", ("Mortar",), ("Anvil",)),
                         catalog=playbook, brief=BRIEF)
    assert whole.stage == "" and {r.stage for r in (whole.blue, whole.red)} == {""}
    for r in (whole.blue, whole.red):
        terms = {c["id"]: c for c in r.contributions}
        assert not terms["hazard-cc"]["applies"] and terms["hazard-ground"]["bonus"] == 0
        assert "text" not in terms["hazard-ground"]
    with pytest.raises(Refusal, match="its stages: Courtyard, Forge, Spire"):
        engine.board(world, Draft("Ember Ruins", stage="Well"), catalog=playbook, brief=BRIEF)
    with pytest.raises(Refusal, match="its stages: Courtyard, Forge, Spire"):
        engine.infer(world, Draft("Ember Ruins", stage="Well"), catalog=playbook, base=DEFAULT)
