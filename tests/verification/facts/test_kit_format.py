"""The kit in the format in force, facts/kit_format.py: the wiki's 6v6
figures laid over the 5v5 rows on a hero built by hand, a row that holds
the figure twice and a stale line left alone and said so; then on the built
database, which the load reads in 6v6, each change naming the 5v5 figure
it moved."""

import pytest

from facts import board_facts, kit_format, tables
from facts.draft import KIT_FORMAT, Draft
from facts.kit import KitPiece, Stat
from facts.model import Hero, World
from facts.records import KitLine


def _stat(code, value, text):
    return Stat(code=code, value=value, unit_num=None, unit_den=None, den_value=None,
                condition=None, text=text)


def _hero():
    """Anvil: a 5v5 kit of three pieces, the 6v6 kit its article states."""
    barrier = KitPiece("Barrier Field", "ability")
    barrier.stats["barrier_health"].append(_stat("barrier_health", 1500.0, "1500"))
    barrier.stats["cooldown"].append(_stat("cooldown", 5.0, "5 seconds"))
    shield = KitPiece("Adaptive Shield", "ability")
    shield.stats["overhealth"].append(_stat("overhealth", 100.0, "100 base + 100 per enemy"))
    hammer = KitPiece("Rocket Hammer", "weapon")
    hammer.extra["weapon"] = "Rocket Hammer"
    hammer.stats["spread"].append(_stat("spread", 3.0, "3 degrees"))
    return Hero(
        id=1, name="Anvil", role="tank", subrole="Stalwart", health=250, armor=300,
        abilities=[barrier, shield], weapons=[hammer], six_pools={"health": 325},
        six_lines=[
            KitLine("Barrier Field", "barrier_health", 1500.0, 1800.0,
                    "Shield health increased from 1500 to 1800"),
            KitLine("Barrier Field", "cooldown", 7.0, 8.0, "Cooldown increased from 7 to 8"),
            KitLine("Adaptive Shield", "overhealth", 100.0, 50.0,
                    "Overhealth gained per target reduced from 100 to 50"),
            KitLine("Rocket Hammer", "spread", 3.0, 4.0, "Spread increased from 3 to 4"),
            KitLine("Rocket Hammer", None, None, None, "No longer staggers")])


def _world(hero):
    w = World()
    w.heroes[hero.id] = hero
    return w


def test_the_6v6_kit_moves_the_pool_and_every_row_it_names_once():
    """The health pool is 6v6's; the barrier's health and the weapon's spread
    move. The cooldown line's 7 is not the 5 the kit holds, so the line is
    stale and the row stays; "100 base + 100 per enemy" holds 100 twice, so
    a line about the per-enemy part moves nothing; a line with no figure
    moves nothing. Each is kept, applied or not."""
    hero = _hero()
    w = _world(hero)
    kit_format.apply(w)
    barrier, shield = hero.abilities
    assert (hero.health, hero.armor) == (325, 300)
    assert barrier.max_stat("barrier_health") == 1800.0
    assert barrier.max_stat("cooldown") == 5.0
    assert shield.max_stat("overhealth") == 100.0
    assert hero.weapons[0].max_stat("spread") == 4.0
    assert [(c.piece, c.stat, c.applied) for c in hero.kit_changes] == [
        ("", "health", True), ("Barrier Field", "barrier_health", True),
        ("Barrier Field", "cooldown", False), ("Adaptive Shield", "overhealth", False),
        ("Rocket Hammer", "spread", True), ("Rocket Hammer", None, False)]


def test_the_kit_is_read_in_6v6():
    """The shipped playbook's open-queue-ranked assumption: the format is one
    constant, 6v6."""
    assert KIT_FORMAT == "6v6"


@pytest.mark.invariant
def test_the_built_world_reads_the_6v6_kit(db):
    """Reinhardt's barrier holds 1800 in 6v6, his pool is 6v6's, and a board
    names what 6v6 moved in his kit from the 1500, 250 and 300 stored."""
    world = tables.load(db)
    db.rollback()
    rein = world.hero("Reinhardt")
    assert rein.barrier_hp == 1800.0 and (rein.health, rein.armor) == (325, 225)
    moved = [c for h in world.heroes.values() for c in h.kit_changes if c.applied]
    assert len(moved) >= 50
    fs = board_facts.generate(world, Draft(map_name="King's Row", red=("Reinhardt",)))
    (fact,) = fs.find("hero.kit_format")
    assert fact.text.startswith("Reinhardt in 6v6: health 250 -> 325, armor 300 -> 225,")
    assert "Barrier Field barrier health 1500 -> 1800" in fact.text


@pytest.mark.invariant
def test_a_tank_whose_article_writes_no_6v6_pool_keeps_its_5v5_one(db):
    """Twelve of the fifteen released tanks' articles write a 6v6 pool.
    Hazard's and D.Mon's write none and Sigma's leaves shield6v6 blank: the
    wiki is what is missing, not the parser, so their
    5v5 pools stand - Hazard's 275 health and 225 armor, 500 - and no pool
    change is named for them. A pool the wiki comes to write fails here."""
    world = tables.load(db)
    db.rollback()
    tanks = [h for h in world.heroes.values() if h.released and h.role == "tank"]
    assert sorted(h.name for h in tanks if not h.six_pools) == ["D.Mon", "Hazard", "Sigma"]
    assert len(tanks) == 15
    hazard = world.hero("Hazard")
    assert (hazard.health, hazard.armor, hazard.pool) == (275, 225, 500)
    assert not [c for c in hazard.kit_changes if c.stat in ("health", "shield", "armor")]
