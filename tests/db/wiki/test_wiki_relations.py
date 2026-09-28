"""The synergies read off wiki articles. The parser on inline wikitext;
then the run() over the wiki page cache inside a transaction that is rolled
back, skipped without the cache or the database."""

import os

import pytest

from db import CACHE_DIRS
from db.data.cache import PullContext
from db.data.normalizer import name_key
from db.data.wiki import synergies

needs_cache = pytest.mark.skipif(
    not os.path.isdir(CACHE_DIRS["wiki"]), reason="the wiki page cache is not on this machine")


# --- synergies: markup -> claims ---------------------------------------------

WIKITABLE = """
==Abilities==
{|
! |Team Synergy
|-
|[[Genji]]
|x
|Not in the synergy section.
|}

==Match-Ups and Team Synergy==
<!-- [[Hanzo]] in a comment -->
===Tank===
{| class="wikitable mw-collapsible mw-collapsed"
|-
! style="width:75px" |Hero
! |Match-Up
! |Team Synergy</small>
|-
|<center>[[File:icon-dva.png|75px|link=D.Va]]<br />[[D.Va]]</center>
|<small>Her Defense Matrix eats your [[Biotic Grenade]].</small>
|<small>(To be added)</small>
|-
|<center>[[File:Icon-Ramattra.png|75x75px]]<br />[[Ramattra]]</center>
|<small>Keep your distance.</small>
|<small>The combined power of {{Al|Nano Boost}} and [[Annihilation]] is incredible.
Synchronize your attacks.</small>
|-
|<center>[[File:icon-sigma.png|75px|link=Sigma]]<br />[[Sigma]]</center>
|<small>(To be added)</small>
|<small>There are no notable synergies between these heroes.</small> |}

===Damage===
{| class="listtable"
|-
! style="width:80px" |'''Hero'''
! style="width:70%" |'''Match-Up'''
! style="width:30%" |'''Team Synergy'''
|-
!<center>[[Image:icon-genji.png|80px|link=Genji]]<br />[[Genji]]</center>
|'''HIGH RISK'''
<small>He deflects your darts.</small>

|'''TBA SYNERGY'''
<small>Nano-Boost and Dragonblade is popular for a reason.<ref>a [[Tracer]] guide</ref></small>

|-
!<center>[[Image:icon-mei.png|80px|link=Mei]]<br />[[Mei]]</center>
|'''LOW RISK'''
<small></small>

|'''TBA SYNERGY'''
<small></small>

|-
!<center>[[Image:icon-echo.png|80px|link=Echo]]<br />[[Echo]]</center>
|
|'''BAD SYNERGY'''
<small>She flies out of your sight.</small>
|-
|<center>[[Mauga]]</center>
|
|<small>(6v6 Exclusive Pairing - Weak Synergy) Frankly, this is not a good pairing.</small>
|-
|<center>[[Orisa]]</center>
|
|<small>(6v6 Exclusive Pairing - Exceptional Synergy) A match made in heaven.</small>
|}

==Story==
[[Widowmaker]] shot her.
"""

TEMPLATE = """
== Match-Ups and Team Synergy ==
=== Support ===
{{MatchupTable/Support
| Ana_rating = STRONG MATCHUP
| Ana_synergy_rating = STRONG SYNERGY
| Ana_matchup = Dive her.
| Ana_synergy = Ana and Anran have strong synergy, though it requires
coordination.<br><br>A {{al|Nano Boost}} helps.

| Baptiste_synergy_rating = SITUATIONAL SYNERGY
| Baptiste_synergy = Baptiste and Anran do not share ideal positioning.

| JetpackCat_synergy_rating = GOOD SYNERGY
| JetpackCat_synergy = {{al|Lifeline}} [[File:x.png|20px]] tows her behind the enemy.

| Lucio_synergy_rating = MIRROR SYNERGY
| Lucio_synergy =

| Mercy_synergy_rating =
| Mercy_synergy =
}}
"""


def test_a_wikitable_row_is_a_claim_when_its_synergy_cell_holds_advice():
    assert synergies.parse_synergies(WIKITABLE) == [
        ("Ramattra", "The combined power of Nano Boost and Annihilation is incredible."
                     " Synchronize your attacks."),
        ("Genji", "Nano-Boost and Dragonblade is popular for a reason."),
        ("Orisa", "A match made in heaven."),
    ]


def test_a_matchup_template_is_read_by_its_synergy_parameters_and_rating():
    claims = synergies.parse_synergies(TEMPLATE)
    assert claims == [
        ("ana", "Ana and Anran have strong synergy, though it requires coordination."),
        ("jetpackcat", "Lifeline tows her behind the enemy."),
    ]
    assert (claims[1].hero, claims[1].cell) == ("jetpackcat", "Lifeline tows her behind the enemy.")


def test_an_article_without_the_section_claims_nothing():
    assert synergies.parse_synergies("==Abilities==\n[[Genji]] is fast.") == []


@pytest.mark.parametrize("cell, rating, advice", [
    ("'''STRONG SYNERGY''' Dive together.", "strong", "Dive together."),
    ("'''TBA SYNERGY'''\n<small>Dive together.</small>", None, "<small>Dive together.</small>"),
    ("(6v6 Exclusive Pairing - Ok Synergy) Both fold to poke.", "ok", "Both fold to poke."),
    (
        "<small>Good synergy with his shield.</small>", None,
        "<small>Good synergy with his shield.</small>"),
])
def test_a_rating_is_split_off_the_advice(cell, rating, advice):
    assert synergies.split_rating(cell) == (rating, advice)


def test_a_note_is_the_first_sentence_cut_to_a_clause_under_the_limit():
    clause = synergies.clause
    assert clause("Nano D.Va. She dives. Then more.") == "Nano D.Va"
    assert clause("You'll end up boosting B.O.B. as his damage wipes teams. More.") == (
        "You'll end up boosting B.O.B. as his damage wipes teams")
    long = ("Enemies snagged by a friendly Roadhog's Chain Hook will usually be reduced to"
            " very low health, which makes them the easiest of targets for a Swift Strike"
            " reset.")
    assert clause(long) == ("Enemies snagged by a friendly Roadhog's Chain Hook will"
                            " usually be reduced to very low health")
    unbroken = "word " * 40
    assert len(clause(unbroken)) < synergies.NOTE_LIMIT and clause(unbroken).endswith("word")


def test_the_first_sentence_is_read_uncut_whatever_its_length():
    first = synergies.first_sentence
    assert first("Nano D.Va. She dives. Then more.") == "Nano D.Va"
    long = "With a friendly Sigma on your team, " + "you hold the line, " * 10 + "and win. More."
    assert first(long) == long[: -len(". More.")]
    assert first("  No sentence end;  ") == "No sentence end"


def test_pairs_are_stored_once_and_scored_by_how_many_articles_claim_them():
    ids = {"ana": 1, "genji": 2, "dva": 3, "cassidy": 4}
    pairs, unmatched = synergies.pair_up({
        "Ana": [("Genji", "Nano-Blade."), ("Ana", "Two of you."), ("Sym", "Teleport.")],
        "Genji": [("ana", "Ask for Nano Boost before you draw the blade.")],
        "D.Va": [("McCree", "Matrix his Deadeye.")],
        "Cassidy": [],
    }, ids)
    assert pairs == {(1, 2): (2, "Nano-Blade"), (3, 4): (1, "Matrix his Deadeye")}
    assert unmatched == ["Ana: Sym"]


# --- the page cache -> the tables ----------------------------------------------

@needs_cache
@pytest.mark.invariant
def test_synergies_pull_from_the_cache(sandbox):
    data = synergies.run(sandbox, PullContext(CACHE_DIRS["wiki"], log=lambda _: None))
    rows = sandbox.execute(
        "select s.hero_id, s.other_id, s.score, s.note, src.code"
        " from synergies s join sources src using (source_id)").fetchall()
    assert data["tables"] == ["synergies"] and data["synergies"] == len(rows) > 100
    assert data["mutual"] == sum(1 for row in rows if row[2] == 2) > 0
    assert data["unmatched"] == [] and data["missing"] == []

    pairs = [frozenset(row[:2]) for row in rows]
    assert len(set(pairs)) == len(pairs) and all(len(pair) == 2 for pair in pairs)
    assert {row[2] for row in rows} == {1, 2}
    assert {row[4] for row in rows} == {"wiki"}
    for _hero, _other, _score, note, _source in rows:
        assert 10 <= len(note) < synergies.NOTE_LIMIT, note
        assert not any(mark in note for mark in ("[[", "{{", "<", "'''", "\n")), note

    released = dict(sandbox.execute(
        "select hero_id, name from heroes where status = 'released'").fetchall())
    paired = {hero_id for pair in pairs for hero_id in pair}
    assert paired <= set(released)
    unpaired = {line.split(": ", 1)[0]: line.split(": ", 1)[1] for line in data["unpaired"]}
    assert set(unpaired) == {name for hero_id, name in released.items()
                             if hero_id not in paired}
    assert all(unpaired.values())


@needs_cache
@pytest.mark.invariant
def test_the_wiki_states_the_well_known_pairs(sandbox):
    synergies.run(sandbox, PullContext(CACHE_DIRS["wiki"], log=lambda _: None))
    stated = {frozenset((name_key(a), name_key(b))): score for a, b, score in sandbox.execute(
        "select h.name, o.name, s.score from synergies s"
        " join heroes h on h.hero_id = s.hero_id join heroes o on o.hero_id = s.other_id")}
    assert stated[frozenset(("ana", "genji"))] == 2            # both articles say Nano-Blade
    assert frozenset(("pharah", "mercy")) in stated
    assert frozenset(("zarya", "hanzo")) in stated
    assert frozenset(("brigitte", "hanzo")) not in stated      # "no notable team synergy"
    assert frozenset(("anran", "baptiste")) not in stated       # rated SITUATIONAL
