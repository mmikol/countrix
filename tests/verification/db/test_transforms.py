"""Unit tests: the pure functions the pulls lean on - the measurement, name
and map readers - and the doc writers, embed, table_prose and the prose a
later migration's comment gives a table. No database, no network - every
lesson here was paid for once already."""

import pytest

from db import embed
from db.data.normalizer import hero_key, name_key, slug
from db.data.wiki import WikiError
from db.data.wiki.kits.measurements import parse_measurements
from db.data.wiki.maps import parse_phases, parse_stages, parse_stretches, stages_of
from db.psql import schema
from db.psql.schema import table_prose
from tests.verification.db import HYBRID_PAGE

# --- measurements: value / numerator / denominator / window ------------

# a stat's text, its unit, and every measurement read from it: (value,
# numerator, denominator, window, condition, text)
MEASUREMENTS = [
    pytest.param("125 m/s", None, [(125, "meters", "seconds", 1, None, "125 m/s")],
                 id="a-rate-splits-into-numerator-and-denominator"),
    pytest.param("14 seconds", None, [(14, "seconds", None, None, None, "14 seconds")],
                 id="a-plain-quantity-has-no-denominator"),
    # 75 over 0.59s is a published total, not 127/s: normalised, it reads as a rate
    pytest.param("75 over 0.59 seconds", "hp",
                 [(75, "hp", "seconds", 0.59, None, "75 over 0.59 seconds")],
                 id="a-window-that-is-not-one-second-is-kept"),
    # falloff is written high -> low: magnitude, not position, decides min and max
    pytest.param("30 - 10 meters", None,
                 [(10, "meters", None, None, "min", "30 - 10 meters"),
                  (30, "meters", None, None, "max", "30 - 10 meters")],
                 id="a-range-is-ordered-by-magnitude"),
    # the value before the perk and with it: dropping either stores the wrong claim
    pytest.param("5 -> 7 meters", None,
                 [(5, None, None, None, "before perk", "5"),
                  (7, "meters", None, None, "with perk", "7 meters")],
                 id="a-perk-transition-keeps-both-sides"),
    pytest.param("✓", None, [(1, None, None, None, None, "✓")], id="a-tick-is-one"),
    pytest.param("✕", None, [(0, None, None, None, None, "✕")], id="a-cross-is-zero"),
    # Venom Mine's health is 1: one hp, not a yes
    pytest.param("1", "hp", [(1, "hp", None, None, None, "1")],
                 id="a-bare-one-is-a-number-in-the-stats-unit"),
    pytest.param("0 -> 50", "hp",
                 [(0, "hp", None, None, "before perk", "0"),
                  (50, "hp", None, None, "with perk", "50")],
                 id="a-bare-zero-is-a-number-in-the-stats-unit"),
    pytest.param("1", None, [(1, None, None, None, None, "1")], id="a-flag-takes-no-unit"),
    pytest.param("Projectile", None, [(None, None, None, None, None, "Projectile")],
                 id="text-keeps-its-row-with-no-value"),
    pytest.param("Expression error: unexpected <", None,
                 [(None, None, None, None, None, "Expression error: unexpected <")],
                 id="a-broken-template-is-no-number"),
    # no unit holds a slash
    pytest.param("1.25 shots/s", None, [(1.25, "shots", "seconds", 1, None, "1.25 shots/s")],
                 id="shots-a-second"),
    pytest.param("3 rounds/s", None, [(3, "rounds", "seconds", 1, None, "3 rounds/s")],
                 id="rounds-a-second"),
    # Symmetra's turret slow, written with U+2212, stored a NULL once
    pytest.param("\u221215% per turret", "percent",
                 [(-15, "percent", None, None, None, "-15% per turret")],
                 id="a-unicode-minus-reads-as-a-minus"),
    # Death Blossom's "185/s" stored as a flat 185 hp once
    pytest.param("185/s per enemy", "hp", [(185, "hp", "seconds", 1, None, "185/s per enemy")],
                 id="a-bare-per-second-is-a-rate-of-the-stats-own-unit"),
]


@pytest.mark.parametrize(("text", "unit", "expected"), MEASUREMENTS)
def test_a_stats_text_reads_as_its_measurements(text, unit, expected):
    assert [tuple(m) for m in parse_measurements(text, default_unit=unit)] == expected

# --- name matching across sources ---------------------------------------

def test_name_key_reconciles_source_spellings():
    # a fold that strips the accent to a space turns Lucio into "Lu io" -
    # NFKD + drop combining marks is the one that works
    assert name_key("Lúcio") == name_key("Lucio")
    assert name_key("D.Va") == name_key("DVa")
    assert name_key("Soldier: 76") == name_key("soldier-76")
    assert name_key("King's Row") == name_key("Kings Row")


@pytest.mark.parametrize(("name", "expected"), [
    ("Lúcio", "lucio"), ("D.Va", "dva"), ("D.Mon", "dmon"), ("Soldier: 76", "soldier-76"),
    ("Torbjörn", "torbjorn"), ("Jetpack Cat", "jetpack-cat"), ("Wrecking Ball", "wrecking-ball")])
def test_a_slug_is_the_name_as_blizzards_links_write_it(name, expected):
    # an announced hero's row upserts on its slug; one that differs from the
    # slug Blizzard later lists misses ON CONFLICT and collides on the name
    assert slug(name) == expected


def test_a_renamed_hero_keys_as_its_current_name():
    assert hero_key("McCree") == name_key("Cassidy")
    assert hero_key("D.Va") == "dva"


# --- map stages out of article wikitext ----------------------------------

FIXTURE = """
==Background==
lore
==Gameplay==
Each turn is played on one of the sections:
[[File:x.png|thumb|caption]]
* Downtown
** Downtown is a description sentence. It must not load as a stage.
* Sanctuary
*[[MEKA Base]]
=== Stadium ===
* Stadium Map That Must Not Leak
==Strategy==
* not a stage either
"""


def test_stages_are_top_level_gameplay_bullets_only():
    assert parse_stages(FIXTURE) == ["Downtown", "Sanctuary", "MEKA Base"]


def test_prose_only_maps_have_no_stages():
    assert parse_stages("==Gameplay==\nA payload route in prose.\n") == []


def test_fewer_than_two_bullets_is_not_a_stage_list():
    assert parse_stages("==Gameplay==\n* Lone bullet\n") == []


# --- an Escort map's stretches, a Hybrid map's phases ---------------------------

ESCORT_NAMED = """
==Background==
=== The Old Quarter ===
lore
== Gameplay ==
[[File:Harbour View.webp|thumb|Harbour View]]
Harbour is an [[Escort]] map which takes place in three main locations: The
City Streets, a [[Rum|Distillery]], and the Sea Fort.

=== City Streets ===
A long open street.

===<u>Distillery</u>===
An enclosed building.

=== The Sea Fort ===
A straight with minimal cover.

===Ferry Rides===
Ferries cross the water.

== Strategy ==
=== Heroes ===
"""

ESCORT_UNNAMED = """
==Gameplay==
The payload starts at the docks, passes the market and ends in the [[hangar]].

==Strategy==
=== Attack ===
Take the high ground.
"""


def test_stretches_are_the_gameplay_subsections_the_opening_names():
    # a leading article aside; Ferry Rides is a subsection, not a stretch
    assert parse_stretches(ESCORT_NAMED) == ["City Streets", "Distillery", "The Sea Fort"]


def test_an_escort_article_that_names_no_stretch_stores_none():
    assert parse_stretches(ESCORT_UNNAMED) == []
    assert stages_of("escort", ESCORT_UNNAMED, ["Assault", "Escort"]) == []
    # subsections its opening does not list are not stretches
    assert parse_stretches("==Gameplay==\nA route.\n=== Docks ===\n=== Market ===\n") == []
    assert parse_stretches("==Background==\nlore\n") == []


def test_the_hybrid_article_names_the_two_phases_in_play_order():
    # a piped link gives its label
    assert parse_phases(HYBRID_PAGE) == ["Assault", "Escort"]
    assert parse_phases("a combination of [[Assault]] and [[Escort]].") == ["Assault", "Escort"]
    with pytest.raises(WikiError):
        parse_phases("Hybrid is a [[game mode]].")


def test_a_maps_stages_follow_its_mode():
    phases = ["Assault", "Escort"]
    assert stages_of("control", FIXTURE, phases) == ["Downtown", "Sanctuary", "MEKA Base"]
    assert stages_of("flashpoint", FIXTURE, phases) == ["Downtown", "Sanctuary", "MEKA Base"]
    assert stages_of("escort", ESCORT_NAMED, phases) == [
        "City Streets", "Distillery", "The Sea Fort"]
    # every Hybrid map plays the two phases, whatever its article lists
    assert stages_of("hybrid", ESCORT_NAMED, phases) == phases
    assert stages_of("hybrid", "", phases) == phases
    # a Push map stays whole
    assert stages_of("push", FIXTURE, phases) == []
    assert stages_of("push", ESCORT_NAMED, phases) == []


# --- the doc writers: a table's prose, a generated section ----------------------

def test_a_tables_prose_is_the_comment_block_directly_above_it():
    text = "\n".join([
        "-- THE FILE: a header that is no table's.",
        "BEGIN;",
        "",
        "-- One row per hero.",
        "--",
        "-- The roster, from Blizzard.",
        "CREATE TABLE heroes (",
        "    hero_id serial PRIMARY KEY",
        ");",
        "",
        "-- Not this one: a blank line follows it.",
        "",
        "CREATE TABLE maps (map_id serial PRIMARY KEY);",
        "-- Nor this one:",
        "    -- an indented line ends the block.",
        "CREATE TABLE modes (mode_id serial PRIMARY KEY);",
        "-- Two lines,",
        "-- one sentence.",
        "CREATE TABLE stages (stage_id serial PRIMARY KEY);",
        "COMMIT;",
    ])
    assert table_prose(text) == {
        "heroes": "One row per hero. The roster, from Blizzard.",   # the bare -- is dropped
        "maps": "", "modes": "",
        "stages": "Two lines, one sentence.",
    }


def test_a_later_comment_replaces_a_tables_prose_and_leaves_its_domain(monkeypatch):
    """A COMMENT ON TABLE in a later migration replaces the prose the table's
    own migration wrote above it, '' read as one quote; the data dictionary
    still files the table under the migration that created it."""
    monkeypatch.setattr(schema, "read_migrations", lambda: [
        schema.Migration(path="001_a.sql", sql="-- The first words.\nCREATE TABLE things (\n"
                                               "    thing_id serial PRIMARY KEY\n);\n"),
        schema.Migration(path="002_b.sql", sql="COMMENT ON TABLE things IS\n"
                                               "    'The wiki''s words.';\n")])
    assert schema._migration_tables() == {
        "things": schema.TableOrigin(migration="001_a.sql", prose="The wiki's words.")}


def test_embed_replaces_only_the_marked_section(tmp_path):
    path = tmp_path / "doc.md"
    path.write_text("# T\n\nkeep\n\n<!-- generated:x -->\nold\n<!-- /generated:x -->"
                    "\n\nalso keep\n")
    embed(str(path), "x", "new\nlines")
    assert path.read_text() == ("# T\n\nkeep\n\n<!-- generated:x -->\nnew\nlines\n"
                                "<!-- /generated:x -->\n\nalso keep\n")
    with pytest.raises(ValueError, match="no y markers"):
        embed(str(path), "y", "z")
