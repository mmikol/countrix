"""Pull + clean + store: overwatch.fandom.com - hero synergies.

Every hero article's "Match-Ups and Team Synergy" section has, per other
hero, a Team Synergy cell of advice, in either markup matchup_tables.py
reads; a template rates the cell in <Hero>_synergy_rating.

A cell is written when it is not a placeholder: it has a rating, or advice
that is not "To be added" or empty. A written cell is a claim unless it is
rated below GOOD (SITUATIONAL, OK, WEAK, POOR, BAD) or MIRROR, or, unrated,
opens with "no notable synergy" or the like; a cell rated GOOD or better
with no advice written is a claim. A pair is stored once, lower hero_id
first. score 2 when both articles claim the pair, 1 when one does. note is
the first sentence of the advice, cut to a clause under 120 characters, or
NO_ADVICE where no claim writes any. synergy_cells keeps every written
cell, a claim or not, so the facts layer can tell a pair an article wrote
off from one neither article wrote (facts/tables.py reads the second at
the written pairs' mean). Both tables are reloaded wholesale.
"""

import re
from collections.abc import Mapping, Sequence
from typing import NamedTuple

import psycopg

from db import psql
from db.data import ArticlePullSummary, cache
from db.data.normalizer import hero_key, index, name_key
from db.data.wiki import WIKI, WikiError
from db.data.wiki.matchup_tables import (
    PLACEHOLDERS,
    SENTENCE_END_RE,
    Row,
    paragraphs,
    released_articles,
    section_rows,
)

# --- extract: markup -> Python ---------------------------------------------

NOTE_LIMIT = 120
# the note of a pair whose claims are ratings with no advice written
NO_ADVICE = "Rated GOOD or better, with no advice written"

# "STRONG SYNERGY advice", or "(6v6 Exclusive Pairing - Weak Synergy) advice".
RATING_RE = re.compile(r"^(?:\s|<[^>]+>|'{2,5})*(?:([A-Z ]*?)\s*SYNERGY\b"
                       r"|\((?:[^()]*? - )?(?i:([a-z ]*?)\s*synergy)\))(?:\s|'{2,5})*")
CLAUSE_END_RE = re.compile(r"[,;:]\s| - | \(")
# "With a friendly Sigma on your team, ..." - an opener, not the advice.
OPENER_RE = re.compile(r"(?:if|when|while|with|because|since|as|though|although|should|like"
                       r"|just like|unlike|in|for|due to|thanks to)\b[^,]*,\s+", re.I)

# A rated cell is a claim unless rated one of these; "tba" is no rating.
NOT_A_SYNERGY = {"situational", "ok", "weak", "very weak", "poor", "very poor",
                 "bad", "no", "mirror"}
UNRATED = {"", "tba", "tbd"}
# An unrated cell is a claim unless its first sentence says there is none.
NO_SYNERGY_RE = re.compile(
    r"\b(?:no|not|n't|poor|little|few)\b[^.]{0,40}\bsynerg"
    r"|\bstruggles?\b|\bsynergi[sz]ing\b[^.]*\bdifficult"
    r"|\bnot (?:the best|a good) (?:pair|match)|\bdon't really mix"
    r"|\bdo not share\b|\brarely interact|\b(?:low|weak\w*) (?:synerg|pairing)", re.I)


def split_rating(cell: str) -> tuple[str | None, str]:
    """'''STRONG SYNERGY''' advice -> ('strong', advice). No rating -> (None, cell)."""
    match = RATING_RE.match(cell)
    if not match:
        return None, cell
    rating = (match.group(1) or match.group(2) or "").strip().lower()
    return (None if rating in UNRATED else rating), cell[match.end():]


def plain(cell: str) -> str:
    """The first paragraph of a cell's advice as plain text."""
    return next(iter(paragraphs(cell)), "")


def first_sentence(text: str) -> str:
    """The first sentence, uncut, its closing punctuation dropped."""
    end = SENTENCE_END_RE.search(text)
    sentence = text[: end.start()] if end else text
    return sentence.strip().rstrip(".!?;:, ")


def clause(text: str) -> str:
    """The first sentence, cut to a clause under NOTE_LIMIT characters: a long
    sentence loses its opener, then everything past its last clause that fits."""
    sentence = first_sentence(text)
    if len(sentence) < NOTE_LIMIT:
        return sentence
    opener = OPENER_RE.match(sentence)
    if opener:
        sentence = sentence[opener.end()].upper() + sentence[opener.end() + 1:]
        if len(sentence) < NOTE_LIMIT:
            return sentence
    cuts = [m.start() for m in CLAUSE_END_RE.finditer(sentence) if 30 <= m.start() < NOTE_LIMIT]
    if cuts:
        return sentence[: cuts[-1]].rstrip(".;:, ")
    return sentence[:NOTE_LIMIT].rsplit(" ", 1)[0].rstrip(".;:, ")


class Cell(NamedTuple):
    """One written Team Synergy cell: the teammate it is about, its plain
    advice ('' for a rating alone) and whether it claims the pair."""
    hero: str
    advice: str
    claim: bool


def read_cells(text: str) -> list[Cell]:
    """Every written cell of one article's Team Synergy column: a
    placeholder with no rating is not written, and is left out."""
    cells = []
    for row in section_rows(text):
        rating, advice = split_rating(row.cell)
        advice = plain(advice)
        if name_key(advice) in PLACEHOLDERS:
            if rating is None:
                continue
            advice = ""             # a rating alone: written, with no advice
        claim = rating not in NOT_A_SYNERGY and not (
            rating is None and NO_SYNERGY_RE.search(first_sentence(advice)))
        cells.append(Cell(hero=row.hero, advice=advice, claim=claim))
    return cells


def claimed(cells: Sequence[Cell]) -> list[Row]:
    """[Row(teammate name, advice)] - the cells that claim their pair, a
    rating with no advice among them as ''."""
    return [Row(hero=c.hero, cell=c.advice) for c in cells if c.claim]


def parse_synergies(text: str) -> list[Row]:
    """[Row(teammate name, advice)] - the claims one article's synergy cells make."""
    return claimed(read_cells(text))


# {(low id, high id): (score, note)}
type Pairs = dict[tuple[int, int], tuple[int, str]]
# {(article's hero id, teammate's id)}: the written cells, each way
type Written = set[tuple[int, int]]


def pair_up(claims_by_hero: Mapping[str, Sequence[Row]],
            hero_ids: Mapping[str, int]) -> Pairs:
    """Claims per hero -> {(low id, high id): (score, note)}.

    claims_by_hero is {hero name: [Row(teammate name, advice)]}; hero_ids is
    {name_key: hero_id}. A teammate no released hero keys to is skipped:
    written_cells names it. The note comes from an article that writes
    advice, one whose first sentence fits uncut when there is one, else the
    first by hero name; NO_ADVICE where every claim is a rating alone.
    """
    stated: dict[tuple[int, int], dict[int, str]] = {}
    for hero in sorted(claims_by_hero):
        hero_id = hero_ids[name_key(hero)]
        for teammate, advice in claims_by_hero[hero]:
            other_id = hero_ids.get(hero_key(teammate))
            if other_id is not None and other_id != hero_id:
                pair = (min(hero_id, other_id), max(hero_id, other_id))
                stated.setdefault(pair, {}).setdefault(hero_id, advice)

    pairs: Pairs = {}
    for pair, advice_by_hero in stated.items():
        notes = [n for n in advice_by_hero.values() if n]
        uncut = [n for n in notes if clause(n) == first_sentence(n)]
        note = clause((uncut or notes)[0]) if notes else NO_ADVICE
        pairs[pair] = (len(advice_by_hero), note)
    return pairs


def written_cells(cells_by_hero: Mapping[str, Sequence[Cell]],
                  hero_ids: Mapping[str, int]) -> tuple[Written, list[str]]:
    """Cells per hero -> ({(article's hero id, teammate's id)}, unresolved
    names): every written cell about another released hero, a claim or not,
    and each teammate name no released hero keys to."""
    written: Written = set()
    unmatched: list[str] = []
    for hero in sorted(cells_by_hero):
        hero_id = hero_ids[name_key(hero)]
        for cell in cells_by_hero[hero]:
            other_id = hero_ids.get(hero_key(cell.hero))
            if other_id is None:
                unmatched.append("%s: %s" % (hero, cell.hero))
            elif other_id != hero_id:
                written.add((hero_id, other_id))
    return written, unmatched


# --- store ---------------------------------------------------------------------

class SynergiesSummary(ArticlePullSummary):
    synergies: int
    mutual: int
    articles: int
    cells: int
    unwritten_pairs: int
    unpaired: list[str]
    unmatched: list[str]
    unwritten: list[str]


def run(connection: psycopg.Connection, pull: cache.PullContext) -> SynergiesSummary:
    """Reload synergies and synergy_cells from the Team Synergy column of
    every released hero's article -> the pairs stored, the mutual ones, the
    cells written, the pairs neither article writes and the heroes left
    unpaired."""
    cursor = connection.cursor()
    released, articles = released_articles(cursor, pull)
    cells = {name: read_cells(text) for name, text in articles.found.items()}
    claims = {name: claimed(read) for name, read in cells.items()}
    if not any(claims.values()):
        raise WikiError("no hero article has a synergy claim")
    ids = index(released)
    pairs = pair_up(claims, ids)
    # every written cell's names, the claims' among them
    written, unmatched = written_cells(cells, ids)

    source_id = psql.register_source(cursor, WIKI, psql.now())
    cursor.execute("DELETE FROM synergies")
    for (hero_id, other_id), (score, note) in sorted(pairs.items()):
        cursor.execute(
            "INSERT INTO synergies (hero_id, other_id, score, note, source_id)"
            " VALUES (%s, %s, %s, %s, %s)",
            (hero_id, other_id, score, note, source_id))
    cursor.execute("DELETE FROM synergy_cells")
    for hero_id, other_id in sorted(written):
        cursor.execute(
            "INSERT INTO synergy_cells (hero_id, other_id, source_id) VALUES (%s, %s, %s)",
            (hero_id, other_id, source_id))
    connection.commit()

    paired = {hero_id for pair in pairs for hero_id in pair}
    unpaired = []
    for name, hero_id in released.items():
        if hero_id not in paired:
            reason = ("no article" if name not in claims else
                      "its claims name no released hero" if claims[name] else
                      "no advice in its article or about it in another")
            unpaired.append("%s: %s" % (name, reason))
    mutual = sum(1 for score, _ in pairs.values() if score == 2)
    possible = len(released) * (len(released) - 1) // 2
    unwritten_pairs = possible - len({frozenset(cell) for cell in written})
    writers = {hero_id for hero_id, _ in written}
    unwritten = [name for name, hero_id in released.items() if hero_id not in writers]
    pull.log(
        "  synergies  %d pairs (%d mutual) from %d articles; %d cells written, %d of %d"
        " pairs in neither article; %d heroes unpaired" % (
            len(pairs), mutual, sum(1 for c in claims.values() if c), len(written),
            unwritten_pairs, possible, len(unpaired)))
    return {"synergies": len(pairs), "mutual": mutual,
            "articles": sum(1 for c in claims.values() if c),
            "cells": len(written), "unwritten_pairs": unwritten_pairs,
            "unpaired": unpaired, "unmatched": unmatched, "unwritten": unwritten,
            "missing": articles.missing, "tables": ["synergies", "synergy_cells"]}
