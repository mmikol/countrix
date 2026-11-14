"""The kit as Blizzard's patch notes leave it, facts/patch_notes.py: each
kind of fix laid over a hero built by hand, a fix that cites a line the
notes lack and one the wiki has caught up on left unlaid and said so, the
board's words for both; then on the built database, where every fix in
FIXES still lays and the figures it sets are pinned."""

import pytest

from facts import board_facts, patch_notes
from facts.draft import Draft
from facts.kit import KitPiece, Stat
from facts.model import Hero, World
from facts.patch_notes import (
    FIXES,
    Drop,
    Move,
    Pool,
    Remove,
    Restate,
    Rework,
    SixFrom,
    SixLine,
)
from facts.records import KitFix, KitLine, NoteLine

P = "October 6, 2026 Patch"


def _stat(code, value, text, condition="", unit_den=None, den_value=None):
    return Stat(code=code, value=value, unit_num="hp", unit_den=unit_den, den_value=den_value,
                condition=condition, text=text)


def _world():
    """Anvil: a hammer whose dps field is stale, a trick the notes removed, a
    bolt still carrying the rows of the ability it replaced, a shield whose
    6v6 line reads from its old 5v5 cooldown; and the notes that say so."""
    hammer = KitPiece("Hammer", "weapon")
    hammer.extra["weapon"] = "Hammer"
    hammer.stats["damage"].append(_stat("damage", 10.0, "10"))
    hammer.stats["dps"].append(_stat("dps", 100.0, "100 while firing", "80 overall w/ reload",
                                     "seconds", 1.0))
    hammer.stats["dps"].append(_stat("dps", None, "(charged): 77.7 while firing"))
    bolt = KitPiece("Bolt", "ability", keywords="cleansable::hacked")
    bolt.stats["duration"].append(_stat("duration", 1.0, "1 second", "ability disable"))
    shield = KitPiece("Shield", "ability")
    shield.stats["cooldown"].append(_stat("cooldown", 7.0, "7 seconds"))
    hero = Hero(
        id=1, name="Anvil", role="support", subrole="Tactician", health=200,
        abilities=[KitPiece("Old Trick", "ability"), bolt, shield], weapons=[hammer],
        six_pools={"health": 300},
        six_lines=[KitLine("Shield", "cooldown", 9.0, 11.0, "Cooldown increased from 9 to 11")],
        notes=[NoteLine(P, piece, line) for piece, line in (
            ("Hammer", "Damage reduced from 10 to 8."),
            ("Old Trick", "Removed."),
            ("", "Base health increased from 200 to 250."),
            ("", "Base health increased from 300 to 350. (6v6)"),
            ("Shield", "Cooldown reduced from 9 to 7 seconds. (5v5)"),
            ("Bolt", "Heals an ally for 40."),
            ("Bolt", "Cooldown is 6 seconds in 6v6."))])
    w = World()
    w.heroes[1] = hero
    return w


FIXED = (
    Move(hero="Anvil", patch=P, piece="Hammer", stat="damage", before=10, after=8,
        cites=("Damage reduced from 10 to 8.",)),
    Drop(hero="Anvil", patch=P, piece="Hammer", stat="dps", values=(100,),
        cites=("Damage reduced from 10 to 8.",)),
    Restate(hero="Anvil", patch=P, piece="Hammer", stat="dps", holding="77.7",
            row=_stat("dps", 64.0, "64 while firing", "", "seconds", 1.0),
            cites=("Damage reduced from 10 to 8.",)),
    Remove(hero="Anvil", patch=P, piece="Old Trick", cites=("Old Trick: Removed.",)),
    Pool(hero="Anvil", patch=P, stat="health", before=200, after=250,
        cites=("Base health increased from 200 to 250.",)),
    Pool(hero="Anvil", patch=P, stat="health", before=300, after=350, six=True,
        cites=("Base health increased from 300 to 350. (6v6)",)),
    SixFrom(hero="Anvil", patch=P, piece="Shield", stat="cooldown", before=9, after=7,
            cites=("Cooldown reduced from 9 to 7 seconds. (5v5)",)),
    Rework(hero="Anvil", patch=P, piece="Bolt", keywords="", cites=("Heals an ally for 40.",),
        rows=(_stat("heal", 40.0, "40", "instant"), _stat("cooldown", 5.0, "5 seconds"))),
    SixLine(hero="Anvil", patch=P, piece="Bolt", stat="cooldown", before=5, after=6,
            text="Cooldown is 6 seconds in 6v6", cites=("Cooldown is 6 seconds in 6v6.",)),
    # a line the notes do not hold, and a figure the kit no longer holds
    Move(hero="Anvil", patch=P, piece="Shield", stat="cooldown", before=9, after=8,
        cites=("Cooldown reduced from 9 to 8 seconds.",)),
    Move(hero="Anvil", patch=P, piece="Hammer", stat="damage", before=12, after=8,
        cites=("Damage reduced from 10 to 8.",)),
)


def test_each_fix_lays_the_notes_figure_over_the_wikis():
    w = _world()
    patch_notes.apply(w, FIXED)
    anvil = w.heroes[1]
    hammer = anvil.weapons[0]
    assert [(s.value, s.text) for s in hammer.stats["damage"]] == [(8.0, "8")]
    assert [s.value for s in hammer.stats["dps"]] == [64.0]       # dropped, then restated
    assert [k.name for k in anvil.abilities] == ["Bolt", "Shield"]
    assert anvil.health == 250 and anvil.six_pools == {"health": 350}
    assert anvil.six_lines[0].before == 7.0
    assert anvil.six_lines[1] == KitLine("Bolt", "cooldown", 5, 6, "Cooldown is 6 seconds in 6v6")
    bolt = anvil.abilities[0]
    assert {c: [s.value for s in rows] for c, rows in bolt.stats.items() if rows} == {
        "heal": [40.0], "cooldown": [5.0]}
    assert bolt.keywords == set() and bolt.atoms == set()        # hacked no longer
    assert [f.applied for f in anvil.kit_fixes] == [True] * 9 + [False, False]
    uncited, caught_up = anvil.kit_fixes[-2:]
    assert uncited.text == (
        "the October 6, 2026 Patch notes hold no line 'Cooldown reduced from 9 to 8 seconds.'")
    assert caught_up.text == "the wiki has caught up"
    assert [f.change for f in anvil.kit_fixes[:4]] == [
        "damage 10 -> 8", "the stale dps 100 dropped", "dps 64/s", "removed"]
    assert anvil.kit_fixes[7].change == "the notes' rows - heal 40 (instant)"


def test_a_rework_lays_fresh_rows_on_every_load_and_none_once_the_wiki_writes_the_heal():
    """A World is built per request and the load moves rows in place: two
    loads share no row. A piece with a heal row of its own is the wiki's."""
    first, second = _world(), _world()
    patch_notes.apply(first, FIXED)
    patch_notes.apply(second, FIXED)
    one, two = (w.heroes[1].abilities[0].stats["heal"][0] for w in (first, second))
    assert one is not two and one is not FIXED[7].rows[0]
    written = _world()
    written.heroes[1].abilities[1].stats["heal"].append(_stat("heal", 45.0, "45"))
    patch_notes.apply(written, FIXED)
    assert written.heroes[1].kit_fixes[7].applied is False


def test_the_board_words_what_the_notes_set_and_warns_of_a_fix_that_lays_nothing(
        synthetic_world):
    w = synthetic_world
    balm = w.hero("Balm")
    balm.kit_fixes = [
        KitFix("Hammer", "damage", 10, 8, P, True, "Damage reduced from 10 to 8.",
            "damage 10 -> 8"),
        KitFix("", "health", 200, 250, P, False, "the wiki has caught up", "health 200 -> 250")]
    facts = board_facts.generate(w, Draft("Harbor Gate", (), ("Balm",))).facts
    [laid] = [f for f in facts if f.key == "hero.patch_fixes"]
    assert laid.text == (
        "Balm from Blizzard's patch notes, where the wiki lags: Hammer: damage 10 -> 8"
        " (October 6, 2026 Patch)")
    [warning] = [f for f in facts if f.key == "meta.patch_fix_warning"]
    assert warning.warn and warning.text == (
        "WARNING: 1 patch fix(es) lay nothing - Balm health 200 -> 250 (the wiki has caught"
        " up) - the wiki has caught up, or the notes no longer hold the line: drop the fix"
        " from facts/patch_notes.py")


# --- the built database ------------------------------------------------------

def test_every_patch_fix_still_lays(world):
    """Each fix finds its cited lines among Blizzard's notes and the wiki's
    figure in the kit. One that lays nothing is a wiki that has caught up:
    drop it from FIXES, and from KIT_LAGS what it covered."""
    laid = [(h.name, f) for h in world.heroes.values() for f in h.kit_fixes]
    assert len(laid) == len(FIXES)
    stale = ["%s %s %s: %s" % (name, f.piece, f.change, f.text)
            for name, f in laid if not f.applied]
    assert not stale, stale


def test_the_notes_set_the_figures_the_wiki_lags_on(world):
    sombra, roadhog = world.hero("Sombra"), world.hero("Roadhog")
    assert sombra.cc_tools == ["EMP"]                     # Hotfix hacks no hero
    assert sombra.peak_heal == 65 and sombra.dps == pytest.approx(92.86, abs=0.005)
    assert "Virus" not in {k.name for k in sombra.abilities}
    assert roadhog.max_range == 35 and roadhog.dps == pytest.approx(197.86, abs=0.005)
    assert world.hero("Illari").dps == pytest.approx(80.33, abs=0.005)
    assert world.hero("Freja").dps == pytest.approx(97.06, abs=0.005)
    assert world.hero("Junker Queen").pool == 500                 # 6v6
    [repeater] = [k for k in world.hero("D.Mon").abilities if k.name == "Fusion Repeater"]
    assert repeater.plain_stat("damage") == 15 and repeater.plain_stat("cooldown") == 5
