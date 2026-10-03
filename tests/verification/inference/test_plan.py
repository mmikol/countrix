"""The board in prose: the verdict read off blue's current comp, through its
fill while half-drafted, the badge above each picker, and the game plan -
the six the comps tab shows, the style, the terrain and the stages it names,
and nothing the board contradicts. Every board is the synthetic World's: no
database."""

import copy

from facts import board_facts
from facts.draft import Draft
from facts.team import team_metrics
from inference import base, catalog
from inference.base import OFF
from inference.expr import Expr
from inference.result import Pick, Result
from tests.verification.inference import BRIEF, FIXTURE_PLAYBOOK

FIX = catalog.load(FIXTURE_PLAYBOOK)


def comp(blue, score, best, partial=False, seat="blue"):
    """A seat's current comp of `blue` under the reference playbook, scoring
    `score` on a scale whose 100 is `best`."""
    return Result(kind="current", map_name=None, red=[], blue=blue, locked=blue,
                  catalog=FIX, base=OFF, score=score, best=best, partial=partial, seat=seat)


def likely(*pulls, revealed=0):
    """Red's likely six of heroes r0, r1.. with these pulls, the first
    `revealed` of them red's picks."""
    picks = [
        Pick(hero="r%d" % i, role="tank", locked=i < revealed, why="", evidence=[], pull=p)
        for i, p in enumerate(pulls)]
    return Result(kind="expected", map_name=None, red=[], blue=[p["hero"] for p in picks],
                  locked=[p["hero"] for p in picks if p["locked"]], catalog=FIX, base=OFF,
                  seat="red", picks=picks)


SIX = likely(12, 7.5, 7, 12, 7, 8)          # 53.5 pull


def test_the_verdict_reads_blues_standing():
    """Blue's share of its optimal, through its fill while half-drafted; red
    is never a share."""
    from inference import plan
    seated = plan.momentum(plan.Seats(comp(["a"] * 6, 8, 10), SIX))
    assert seated["verdict"] == "blue 80 / 100 of its optimal" and seated["blue"] == 80
    assert set(seated) == {"blue", "partial", "verdict", "badges"}
    half = plan.momentum(plan.Seats(comp(["a"], 2, 10, partial=True), SIX,
                                    fill=comp(["a"] * 6, 7, 10)))
    assert half["verdict"] == "blue 70 / 100 of its optimal (the best six from its picks)"
    assert half["partial"]
    none = plan.momentum(plan.Seats(comp([], 0, 10), SIX))
    assert none["verdict"].startswith("no blue picks yet") and none["blue"] is None


def test_the_badge_is_worded_on_the_server():
    """Blue's badge is the engine's: "unscored", with the reason, whenever its
    comp cannot be a share of anything - picks or not, never 100 / 100;
    before any pick the suggested six's 100; else the picks' share of the
    optimal, a half-drafted seat's through the best six its picks reach where
    that fill was solved and off the picks themselves where it was not, and
    the tip says which. Red's is its likely six's pull, which nothing scores,
    so it reads the same whatever blue's board can or cannot score."""
    from inference import plan
    waiting = plan.momentum(plan.Seats(comp(["a"], 0, 0), SIX))
    assert waiting["badges"]["blue"] == {
        "label": "unscored",
        "tip": ("unscored on this board - the optimal six scores 0.00, not above the floor of"
                " 0.00, so no comp is a share of it")}
    assert waiting["badges"]["red"] == {
        "label": "54 pull",
        "tip": ("their likely six: 53.5 pull - each hero's pick rate here, plus 2 for each"
                " synergy partner on the six")}
    held = plan.momentum(plan.Seats(comp([], 0, 10), likely(12, 7.5, 7, 12, 7, 8, revealed=2)))
    assert held["badges"]["red"]["tip"].startswith(
        "their picks and the likeliest heroes for the rest: 53.5 pull")
    assert held["badges"]["blue"] == {
        "label": "100 / 100",
        "tip": "no blue picks yet: the suggested six is this seat's optimal, 100"}
    half = plan.momentum(plan.Seats(comp(["a"], 2, 10, partial=True), SIX,
                                    fill=comp(["a"] * 6, 8, 10)))
    assert half["badges"]["blue"] == {
        "label": "80 / 100",
        "tip": "the best six from your picks reaches 80% of the best six for this board"}
    assert half["badges"]["blue"]["label"] == "%d / 100" % half["blue"]
    # no fill solved (a search past its budget): the share is the picks' own, and the tip says so
    alone = plan.momentum(plan.Seats(comp(["a"], 3, 10, partial=True), SIX))
    assert alone["badges"]["blue"]["tip"] == "your picks reach 30% of the best six for this board"
    full = plan.momentum(plan.Seats(comp(["a"] * 6, 9, 10), SIX))
    assert full["badges"]["blue"]["tip"] == "your picks reach 90% of the best six for this board"


def test_blue_is_read_through_its_fill_while_half_drafted(synthetic_world, scratch_playbook):
    """Blue's share is its fill's while it is half-drafted - the picks alone
    would sum over a smaller team and read low."""
    from inference import engine
    b = engine.board(synthetic_world, Draft("Ember Ruins", ("Anvil",), ("Anvil",)),
                     catalog=scratch_playbook, brief=BRIEF)
    assert b.current.partial
    assert b.momentum["blue"] == b.fill.to_dict()["normalized"]
    assert b.momentum["verdict"] == (
        "blue %d / 100 of its optimal (the best six from its picks)" % b.momentum["blue"])


def test_the_plan_names_every_maps_derived_style(synthetic_world, harbor_gate_board):
    """Every map's plan names the style its rates reward. One board is solved
    through the public path; the other maps' plans are composed from that
    board's optimal."""
    from inference import plan
    world = synthetic_world
    blue_r = harbor_gate_board.blue
    for m in world.maps.values():
        assert m.style_top, m.name
        said = (harbor_gate_board.plan if m.name == "Harbor Gate"
                else plan.plan(world, m, "", [], [], blue_r))
        assert "The map rewards %s" % m.style_top in said, m.name
    assert plan._and(["A"]) == "A" and plan._and(["A", "B", "C"]) == "A, B and C"


def test_a_style_the_plan_has_no_words_for_still_reads_as_advice(synthetic_world):
    """A style the wiki adds past dive, brawl and poke reads as plain advice,
    not a KeyError that fails the board."""
    from inference import plan
    m = copy.copy(synthetic_world.map("Harbor Gate"))
    m.styles = {"flank": 1.0}
    assert plan._style_read(m, "", []) == "The map rewards flank: play to its picks."


def test_the_plan_names_the_terrain_the_facts_hold_and_no_other(
        synthetic_world, harbor_gate_board):
    """The map sentence names the map.terrain facts above the ordinary map, largest
    first; a board whose facts hold none for the map names none."""
    from facts import model
    from inference import plan
    world = synthetic_world
    blue_r = harbor_gate_board.blue
    above = [
        f.value["feature"] for f in blue_r.facts.find("map.terrain", "Harbor Gate")
        if f.value["z"] > 0][:plan.TERRAIN_NAMED]
    assert above and above[0] == "chokes"
    assert set(plan.TERRAIN_GROUND) == set(model.TERRAIN_FEATURES)
    sentence = "The wiki's article stresses %s." % plan._and(
        plan.TERRAIN_GROUND[f] for f in above)
    assert sentence in harbor_gate_board.plan.split("\n")[0]
    # these facts are Harbor Gate's: another map's plan reads none of them
    assert "stresses" not in plan.plan(world, world.map("Ember Ruins"), "", [], [], blue_r)


def test_the_plan_names_the_stages_the_facts_hold_and_no_other(
        synthetic_world, harbor_gate_board):
    """One sentence names the stages with a map.stage_terrain fact, in play order,
    STAGES_NAMED at most, each by the features its fact holds; no fact, no sentence."""
    import copy

    from inference import plan
    world = synthetic_world
    blue_r = harbor_gate_board.blue

    def first_line(name):
        r = copy.copy(blue_r)
        r.facts = board_facts.generate(world, Draft(name))
        return plan.plan(world, world.map(name), "", [], [], r).split("\n")[0]
    # Forge's text stresses its hazards; Spire's falls a mention short and
    # Courtyard has no text of its own
    held = board_facts.generate(world, Draft("Ember Ruins")).find(
        "map.stage_terrain", "Ember Ruins")
    assert [f.value["stage"] for f in held] == ["Forge"]
    assert "Forge has the environmental hazards." in first_line("Ember Ruins")
    assert "Spire" not in first_line("Ember Ruins")
    assert "Courtyard" not in first_line("Ember Ruins")
    # no stage fact: Harbor Gate has stages and no text of theirs, Salt Flats no stages
    for name in ("Harbor Gate", "Salt Flats"):
        assert not board_facts.generate(world, Draft(name)).find("map.stage_terrain")
        assert " has the " not in first_line(name), name
        assert not any(stage in first_line(name) for stage in world.map(name).stages), name
    # three stages at most: the largest, told in play order. Salt Flats is given
    # five stages here, as a Flashpoint map holds, and a fact for four of them
    salt = world.map("Salt Flats")
    salt.mode, salt.stages = "Flashpoint", ["Dock", "Market", "Mill", "Pier", "Quay"]
    r = copy.copy(blue_r)
    r.facts = board_facts.generate(world, Draft("Salt Flats"))
    assert not r.facts.find("map.stage_terrain")
    for stage, z in zip(salt.stages[:4], (1.0, 4.0, 3.0, 2.0), strict=True):
        r.facts.add("map", "Salt Flats", "map.stage_terrain", stage, source="stage_terrain",
                    value={"stage": stage, "features": [{"feature": "cover", "z": z}]})
    assert plan.STAGES_NAMED == 3 and "%s has the cover; %s the cover; %s the cover." % tuple(
        salt.stages[1:4]) in plan.plan(world, salt, "", [], [], r)
    assert salt.stages[0] not in plan.plan(world, salt, "", [], [], r)


def test_the_plan_says_nothing_the_board_contradicts(synthetic_world):
    """A mirror is told as one, a six solved before red reveals a pick names the
    likely six its counter term read and counters, blue's own six only names
    it, "Above all" leaves out the shape every six pays and a rule named for
    another style, and the family follows the style tags."""
    from types import SimpleNamespace as Ns

    from inference import plan
    from inference.result import Result
    from inference.scoring import Contribution
    world = synthetic_world
    m = copy.copy(world.map("Harbor Gate"))
    m.styles = {"brawl": 1.0, "dive": -0.5, "poke": 0.0}     # a brawl map
    rules = [
        Ns(
            id="two-supports-hold", name="Two supports hold a six", kind="heuristic",
            form="scored", category="shape", when=None, pending=False),
        Ns(
            id="dive-the-pocket", name="Dive the pocket", kind="heuristic", form="scored",
            category="matchup", when=Expr("enemy.dmg_amp >= 2"), pending=False),
        Ns(
            id="brawl-maps", name="Brawl maps reward durability", kind="heuristic",
            form="heuristic", category="map", when=Expr("map.style_top == 'brawl'"),
            pending=False),
        Ns(
            id="poke-needs-reach", name="Poke needs reach", kind="heuristic",
            form="heuristic", category="shape", when=Expr("team.style_lean == 'poke'"),
            pending=False),
        Ns(
            id="unmet", name="An unmet need", kind="heuristic", form="heuristic",
            category="general", when=None, pending=False)]
    terms: list[Contribution] = [
        {
            "id": r.id, "kind": r.kind, "form": r.form, "applies": True, "weighted": 2.0,
            "metric": None}
        for r in rules[:4]]
    terms.append({"id": "unmet", "kind": "heuristic", "form": "heuristic", "applies": True,
                  "weighted": -0.5, "metric": None, "need": True})
    # the default engine's counter term, as it reads red's likely six before a reveal
    terms.append({"id": base.COUNTERS, "kind": "base", "form": "base", "applies": True,
                  "weighted": 0.0, "metric": None, "against": ["Anvil", "Mortar"],
                  "likely": True})
    red_h = [world.hero("Anvil"), world.hero("Mortar")]
    theirs = team_metrics(world, red_h, m, [])
    red_lean = theirs["style_lean"] or theirs["style_top"]
    assert red_lean == "brawl"
    # a real Result, not a stand-in: _plan reads .facts, which Result defines
    six = Result(kind="infer", map_name=m.name, red=["Anvil", "Mortar"], blue=[],
                 locked=[], catalog=rules, base=OFF, playstyle="brawl", contributions=terms)
    said = plan.plan(world, m, "", [], red_h, six)                     # a mirror
    assert "(Anvil, Mortar) lean brawl too: %s." % plan.SAME_LEAN["brawl"] in said
    assert plan.THEIR_LEAN["brawl"] not in said
    assert "Above all: brawl maps reward durability." in said
    six.playstyle = "poke"
    said = plan.plan(world, m, "", [], red_h, six)
    assert "lean brawl: %s." % plan.THEIR_LEAN["brawl"] in said
    assert "but against this red the six leans poke" in said
    assert "Above all: brawl maps reward durability; poke needs reach." in said
    said = plan.plan(world, m, "", [], [], six)                        # red revealed nothing
    assert "this red" not in said and "but the six leans poke" in said
    assert "No red pick yet: the six counters their likely six (Anvil, Mortar)." in said
    six.kind = "evaluate"                                              # blue's own six
    said = plan.plan(world, m, "", [], [], six)
    assert "No red pick yet: their likely six is Anvil and Mortar." in said
    tanks = plan._family(world, m, "brawl", "tank", ["Mortar"])
    tagged = [
        h for h in world.heroes.values()
        if h.role == "tank" and "brawl" in h.styles and h.released and h.name != "Mortar"]
    assert set(tanks) <= {h.name for h in tagged} and "Anvil" in tanks
    assert len(tanks) == min(plan.FAMILY_SIZE, len(tagged))
    assert "Mortar" not in tanks and "Quarry" not in tanks           # banned; not tagged brawl
    # fewest tags first, then the best win rate here: Flint carries dive and poke
    # and wins more here than Gale, and still comes after it
    divers = plan._family(world, m, "dive", "damage", [])
    keys = [(len(world.hero(n).styles), -(world.hero(n).map_win(m.id) or world.hero(n).win or 0.0))
            for n in divers]
    assert keys == sorted(keys) and divers == ["Gale", "Flint"]
    assert world.hero("Flint").map_win(m.id) > world.hero("Gale").map_win(m.id)
    alone = [
        h for h in world.heroes.values()
        if h.role == "damage" and h.released and h.styles == {"dive"}]
    assert [world.hero(n) for n in divers[:len(alone)]] == sorted(
        alone, key=lambda h: -(h.map_win(m.id) or h.win or 0.0))[:plan.FAMILY_SIZE]
    assert "Tanks: %s." % ", ".join(plan._family(world, m, "poke", "tank", [])) in said


def test_the_plan_describes_the_six_the_comps_tab_shows(synthetic_world, scratch_playbook):
    """The comps tab shows blue's optimal before any blue pick, the fill
    around one to five and the picks themselves at six, and the plan
    describes that six: it names the picks the six keeps, reads the fill's
    lean where the optimal leans elsewhere, and counts the picks in what it
    rests on. It used to read the optimal, which blue's picks never touch."""
    from inference import engine

    def board(red, blue):
        return engine.board(synthetic_world, Draft("Harbor Gate", red, blue, side="attack"),
                            catalog=scratch_playbook,
                            brief=engine.Brief(base=OFF, search_swaps=False))
    none = board(("Anvil",), ())
    assert "your pick" not in none.plan and "The six keeps" not in none.plan
    one = board(("Anvil",), ("Balm",))
    assert one.fill.playstyle != one.blue.playstyle             # the two sixes lean apart
    assert "The six keeps your pick (Balm) and fills the rest." in one.plan
    assert "the six leans %s" % one.fill.playstyle in one.plan
    assert one.plan.endswith("your 1 pick, red's 1 revealed pick.")
    full = board((), tuple(one.fill.blue))
    assert "The six is the one you picked." in full.plan and "your 6 picks" in full.plan
    # the default engine off, no term reads red's likely six: the plan names none
    assert "the six counters" not in full.plan and "likely six" not in full.plan
