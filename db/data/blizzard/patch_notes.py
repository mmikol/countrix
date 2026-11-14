"""Pull + clean + store: overwatch.blizzard.com - the live patch notes.

One page a month, from FIRST_MONTH to the month of the pull, each holding
that month's patches newest first. A patch is dated by its anchor
(`patch-2026-10-06`) and titled "Overwatch Retail Patch Notes - <date>";
anything else on the page (a notice, a pagination link) is no patch. Under
a patch, its sections follow one another flat: "Hero Updates" opens the
balance changes, and the headings that sort its heroes (Tank, Damage,
Support, Hero Reworks) stay in it; any other heading - Stadium Updates, Bug
Fixes, Hero Hit Volumes, a mode's news - closes it, so a Stadium power, a
bug fix or a hitbox size is never read as a balance line. A hero's entry
holds lines on the hero itself, perks under a "<name> - Major Perk"
paragraph, and its abilities' lines; the developer comments are prose and
are left out.

The patches are stored as the wiki's Patches table names them ("October 6,
2026 Patch"), so a patch both sources know is one row; every balance line
goes to patch_notes, which facts/patch_notes.py reads to check that each
fix it lays over the wiki's kit cites a line Blizzard wrote. A "New Escort
Map - Grimsvotn" line in any section adds the map to the pool under its
mode: the rates page lists a map from the day it ships, and the wiki's pool
can lag it.
"""

import re
from datetime import date, datetime
from typing import NamedTuple

import psycopg
from bs4 import BeautifulSoup, Tag

from db import psql
from db.data import ArticlePullSummary, cache
from db.data.blizzard import BASE_URL, BLIZZARD, BlizzardError
from db.data.cache import cache_key, cached_get
from db.data.normalizer import hero_key, index, map_index, map_key, name_key

NOTES_URL = BASE_URL + "/news/patch-notes/live/%d/%02d/"
# The wiki's Patches table ends on its "August 14, 2026 Patch", and its hero
# articles lag the patches since: the notes are read from that month on.
FIRST_MONTH = (2026, 8)
# A few pages, read once a refresh: paced as the rates page is.
NOTES_POLICY = cache.RequestPolicy(attempts=3, backoff=2.0, delay=5.0)

PATCH_ANCHOR_RE = re.compile(r"^patch-(\d{4}-\d{2}-\d{2})$")
PATCH_TITLE_RE = re.compile(r"^Overwatch Retail Patch Notes\s*[–-]\s*(.+)$")
NEW_MAP_RE = re.compile(r"^New (\w+) Map\s*[–-]\s*(.+?)\s*$")
PERK_SUFFIX_RE = re.compile(r"\s*[–-]\s*(?:Major|Minor) Perk\s*$")
BALANCE = "Hero Updates"
# the headings that sort a balance section's heroes, and stay in it
SUBHEADS = ("Tank", "Damage", "Support", "Hero Reworks")


# --- extract: markup -> Python ---------------------------------------------

class NotedPatch(NamedTuple):
    """A patch the notes date, named as the wiki's Patches table names one."""
    name: str
    released: date


class NoteLine(NamedTuple):
    """A balance line under a hero: the patch, the hero and piece as the
    notes name them ('' for the hero itself), its place in the hero's entry,
    and its words."""
    patch: str
    hero: str
    piece: str
    position: int
    line: str


class NewMap(NamedTuple):
    """A map the notes add to the pool, and its mode."""
    patch: str
    mode: str
    name: str


class NotesPage(NamedTuple):
    """What one month's page says."""
    patches: list[NotedPatch]
    lines: list[NoteLine]
    maps: list[NewMap]


def months(first: tuple[int, int], today: date) -> list[tuple[int, int]]:
    """Every (year, month) from `first` to today's, in order."""
    year, month = first
    out = []
    while (year, month) <= (today.year, today.month):
        out.append((year, month))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return out


def patch_name(released: date) -> str:
    """A patch's name as the wiki's Patches table writes it: "October 6, 2026 Patch"."""
    return "%s %d, %d Patch" % (released.strftime("%B"), released.day, released.year)


def _text(node: Tag) -> str:
    """A node's words on one line, its spacing collapsed."""
    return " ".join(node.get_text(" ", strip=True).split())


def _hero_lines(entry: Tag, patch: str) -> list[NoteLine]:
    """One hero's balance lines: those on the hero itself, each perk's under
    its name, then each ability's, in page order."""
    name = entry.select_one(".PatchNotesHeroUpdate-name")
    if name is None:
        raise BlizzardError("patch notes: a hero entry with no name")
    hero = _text(name)
    said: list[tuple[str, str]] = []
    for general in entry.select(".PatchNotesHeroUpdate-generalUpdates"):
        piece = ""
        for child in general.children:
            if not isinstance(child, Tag):
                continue
            if child.name == "p":
                piece = PERK_SUFFIX_RE.sub("", _text(child))
            elif child.name == "ul":
                said.extend((piece, _text(li)) for li in child.select("li"))
    for ability in entry.select(".PatchNotesAbilityUpdate"):
        heading = ability.select_one(".PatchNotesAbilityUpdate-name")
        piece = _text(heading) if heading else ""
        said.extend((piece, _text(li)) for li in ability.select("li"))
    return [NoteLine(patch, hero, piece, position, line)
            for position, (piece, line) in enumerate(said, start=1) if line]


def parse_notes(html: str, month: tuple[int, int]) -> NotesPage:
    """One month's page -> its patches, their balance lines and the maps they
    add. A patch dated outside `month` is another page's and is left out.
    BlizzardError when the page holds no patch list at all."""
    soup = BeautifulSoup(html, "html.parser")
    if soup.select_one(".PatchNotes-list") is None:
        raise BlizzardError("patch notes %d-%02d: no patch list" % month)
    page = NotesPage([], [], [])
    for block in soup.select(".PatchNotes-patch"):
        anchor = block.select_one(".anchor")
        title = block.select_one(".PatchNotes-patchTitle")
        found = PATCH_ANCHOR_RE.match(str(anchor.get("id", ""))) if anchor else None
        if not (found and title and PATCH_TITLE_RE.match(_text(title))):
            continue                                    # a notice, not a patch
        released = datetime.strptime(found.group(1), "%Y-%m-%d").date()
        if (released.year, released.month) != month:
            continue
        name = patch_name(released)
        page.patches.append(NotedPatch(name, released))
        group = ""
        for section in block.select(".PatchNotes-section"):
            heading = section.select_one(".PatchNotes-sectionTitle")
            title_text = _text(heading) if heading else ""
            if title_text not in SUBHEADS:
                group = title_text
            for said in section.find_all(["strong", "li", "p"]):
                new_map = NEW_MAP_RE.match(_text(said))
                # a <p><strong> says it twice: one map once
                if new_map and group != "Stadium Updates" and new_map.group(2) not in {
                        m.name for m in page.maps}:
                    page.maps.append(NewMap(name, new_map.group(1), new_map.group(2)))
            if group == BALANCE:
                for entry in section.select(".PatchNotesHeroUpdate"):
                    page.lines.extend(_hero_lines(entry, name))
    return page


# --- store -------------------------------------------------------------------

class PatchNotesSummary(ArticlePullSummary):
    patches: int
    lines: int
    maps: list[str]
    unknown_heroes: list[str]
    unknown_modes: list[str]


def run(connection: psycopg.Connection, pull: cache.PullContext) -> PatchNotesSummary:
    """Upsert every patch the notes date, add the maps they ship, and reload
    patch_notes whole with every balance line under a hero on the roster ->
    the patches, lines and maps stored, the heroes and modes no row matches,
    and the month pages that would not fetch (missing)."""
    # the read's transaction ends before the fetches, so none stays open across them
    reader = connection.cursor()
    heroes = {hero_key(name): hero_id for name, hero_id in reader.execute(
        "SELECT name, hero_id FROM heroes").fetchall()}
    modes = index(dict(reader.execute("SELECT name, mode_id FROM game_modes").fetchall()))
    pooled = map_index(dict(reader.execute("SELECT name, map_id FROM maps").fetchall()))
    connection.commit()

    pages: list[NotesPage] = []
    missing: list[str] = []
    for month in months(FIRST_MONTH, psql.now().date()):
        url = NOTES_URL % month
        try:
            html = cached_get(pull, url, cache_key("patch_notes", *month), policy=NOTES_POLICY)
        except cache.FetchError as error:
            missing.append("%d-%02d: %s" % (*month, error))
            pull.log("  %d-%02d  %s" % (*month, error))
            continue
        page = parse_notes(html, month)
        pull.log("  %d-%02d  %d patches, %d hero lines" % (
            *month, len(page.patches), len(page.lines)))
        pages.append(page)

    cursor = connection.cursor()
    source_id = psql.register_source(cursor, BLIZZARD, psql.now())
    patch_ids: dict[str, int] = {}
    for patch in (p for page in pages for p in page.patches):
        cursor.execute(
            "INSERT INTO patches (name, released, source_id) VALUES (%s, %s, %s)"
            " ON CONFLICT (name) DO UPDATE SET released = EXCLUDED.released,"
            " source_id = EXCLUDED.source_id, cao = now() RETURNING patch_id",
            (*patch, source_id))
        patch_ids[patch.name] = psql.scalar(cursor)
    # a page that would not fetch keeps its lines out: the table is the pages read
    cursor.execute("DELETE FROM patch_notes")
    unknown_heroes: list[str] = []
    stored = 0
    for line in (n for page in pages for n in page.lines):
        hero_id = heroes.get(hero_key(line.hero))
        if hero_id is None:
            if line.hero not in unknown_heroes:
                unknown_heroes.append(line.hero)
            continue
        cursor.execute(
            "INSERT INTO patch_notes (patch_id, hero_id, piece, position, line, source_id)"
            " VALUES (%s, %s, %s, %s, %s, %s)",
            (patch_ids[line.patch], hero_id, line.piece, line.position, line.line, source_id))
        stored += 1
    added: list[str] = []
    unknown_modes: list[str] = []
    for new_map in (m for page in pages for m in page.maps):
        mode_id = modes.get(name_key(new_map.mode))
        if mode_id is None:
            unknown_modes.append("%s (%s)" % (new_map.name, new_map.mode))
            continue
        # a map the pool holds under any title, the wiki's included, keeps its
        # row; a new one is inserted, and never deleted: rates hang off maps
        map_id = pooled.get(map_key(new_map.name))
        if map_id is None:
            cursor.execute(
                "INSERT INTO maps (name, source_id) VALUES (%s, %s) RETURNING map_id",
                (new_map.name, source_id))
            map_id = pooled[map_key(new_map.name)] = psql.scalar(cursor)
        cursor.execute(
            "INSERT INTO map_modes (map_id, mode_id, source_id) VALUES (%s, %s, %s)"
            " ON CONFLICT DO NOTHING", (map_id, mode_id, source_id))
        added.append(new_map.name)
    connection.commit()
    pull.log("patch notes: %d patches, %d lines, maps %s" % (
        len(patch_ids), stored, ", ".join(added) or "-"))
    return {"patches": len(patch_ids), "lines": stored, "maps": added,
            "unknown_heroes": unknown_heroes, "unknown_modes": unknown_modes,
            "missing": missing,
            "tables": ["patches", "patch_notes", "maps", "map_modes"]}
