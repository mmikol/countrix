"""Unit tests: Blizzard's live patch notes read into patches, balance lines
and the maps a patch ships, and the pull over them. No database, no network:
the pages are inline HTML in the site's markup."""

import datetime

import pytest

from db.data import cache
from db.data.blizzard import BlizzardError, patch_notes
from db.data.blizzard.patch_notes import (
    NewMap,
    NotedPatch,
    NoteLine,
    months,
    parse_notes,
    patch_name,
)
from tests.verification.db.recording import RecordingConnection


def _section(title, body=""):
    return ('<div class="PatchNotes-section"><h4 class="PatchNotes-sectionTitle">%s</h4>%s</div>'
            % (title, body))


def _hero(name, general="", abilities=()):
    return (
        '<div class="PatchNotesHeroUpdate"><div class="PatchNotesHeroUpdate-header">'
        '<h5 class="PatchNotesHeroUpdate-name">%s</h5></div>'
        '<div class="PatchNotesHeroUpdate-body">'
        '<div class="PatchNotes-dev PatchNotesHeroUpdate-dev"><p>Developer Comments: why.</p></div>'
        '%s<div class="PatchNotesHeroUpdate-abilitiesList">%s</div></div></div>' % (
            name,
            ('<div class="PatchNotesHeroUpdate-generalUpdates">%s</div>' % general
            if general else ""),
            "".join(
                '<div class="PatchNotesAbilityUpdate"><div class="PatchNotesAbilityUpdate-text">'
                '<div class="PatchNotesAbilityUpdate-name">%s</div>'
                '<div class="PatchNotesAbilityUpdate-detailList"><ul>%s</ul></div></div></div>'
                % (piece, "".join("<li>%s</li>" % line for line in lines))
                for piece, lines in abilities)))


def _patch(day, title, *sections):
    return ('<div class="PatchNotes-patch PatchNotes-live"><div class="anchor" id="patch-%s"></div>'
            '<h3 class="PatchNotes-patchTitle">%s</h3>%s</div>' % (day, title, "".join(sections)))


def _page(*patches):
    return ('<html><body><div class="PatchNotes-list"><div class="PatchNotes-body">%s</div></div>'
            '</body></html>' % "".join(patches))


OCTOBER = _page(
    _patch(
        "2026-10-13", "Overwatch Retail Patch Notes – October 13, 2026",
        _section("Hotfix Update"),
        _section("Hero Updates", _hero("Sombra", abilities=[
            ("Cyberspace", ["Explosion damage reduced from 40 to 20."])]))),
    _patch(
        "2026-10-06", "Overwatch Retail Patch Notes – October 6, 2026",
        _section("Core Game Updates",
                 '<div class="PatchNotesGeneralUpdate-description">'
                 "<p><strong>New Escort Map – Grímsvötn</strong></p></div>"),
        _section("Hero Updates"),
        _section("Hero Reworks", _hero(
            "Sombra",
            general="<ul><li>Moved from Damage to Support role.</li></ul>"
                    "<p>Life Hack - Minor Perk</p><ul><li>New Minor Perk.</li></ul>",
            abilities=[("Virus", ["Removed."]), ("Hotfix", ["Has 2 charges."])])),
        _section("Tank", _hero("wrecking Ball", abilities=[("Grappling Claw", ["Faster."])])),
        _section("Hero Hit Volumes", _hero("Sombra", general="<ul><li>Head bigger.</li></ul>")),
        _section("Stadium Updates"),
        _section("Damage", _hero("Sombra", abilities=[("Power", ["Damage increased to 60."])])),
        _section("Bug Fixes", _hero("Sombra", general="<ul><li>Fixed a bug.</li></ul>"))),
    # a notice is no patch, and a patch dated in another month is that page's
    _patch("2026-10-02", "Update on Unauthorized Peripheral Usage"),
    _patch("2026-09-22", "Overwatch Retail Patch Notes – September 22, 2026",
        _section("Hero Updates", _hero("Sombra", abilities=[("Hack", ["Gone."])]))))


def test_a_page_gives_its_months_patches_their_balance_lines_and_the_maps_they_ship():
    """Hero Updates and the headings that sort it (Hero Reworks, Tank) are
    read; Hit Volumes, Stadium and Bug Fixes close it. A perk's lines sit
    under its name, its tier dropped; the developer comment is no line; the
    new map, said in a strong inside a paragraph, is one map."""
    page = parse_notes(OCTOBER, (2026, 10))
    assert page.patches == [
        NotedPatch("October 13, 2026 Patch", datetime.date(2026, 10, 13)),
        NotedPatch("October 6, 2026 Patch", datetime.date(2026, 10, 6))]
    assert page.lines == [
        NoteLine("October 13, 2026 Patch", "Sombra", "Cyberspace", 1,
                 "Explosion damage reduced from 40 to 20."),
        NoteLine("October 6, 2026 Patch", "Sombra", "", 1, "Moved from Damage to Support role."),
        NoteLine("October 6, 2026 Patch", "Sombra", "Life Hack", 2, "New Minor Perk."),
        NoteLine("October 6, 2026 Patch", "Sombra", "Virus", 3, "Removed."),
        NoteLine("October 6, 2026 Patch", "Sombra", "Hotfix", 4, "Has 2 charges."),
        NoteLine("October 6, 2026 Patch", "wrecking Ball", "Grappling Claw", 1, "Faster.")]
    assert page.maps == [NewMap("October 6, 2026 Patch", "Escort", "Grímsvötn")]


def test_a_page_with_no_patch_list_is_refused():
    with pytest.raises(BlizzardError, match="patch notes 2026-11: no patch list"):
        parse_notes("<html><body><main></main></body></html>", (2026, 11))


def test_the_months_run_from_the_first_to_today_and_a_patch_is_named_as_the_wiki_names_one():
    assert months((2026, 11), datetime.date(2027, 2, 3)) == [
        (2026, 11), (2026, 12), (2027, 1), (2027, 2)]
    assert months((2026, 8), datetime.date(2026, 7, 31)) == []
    assert patch_name(datetime.date(2026, 10, 6)) == "October 6, 2026 Patch"


def test_the_pull_stores_every_patch_and_line_pools_a_new_map_once_and_names_the_rest(
        monkeypatch):
    """October's page stores its patches and lines; November's will not
    fetch and is one missing line. A hero no row names is listed, not
    stored. Grimsvotn is pooled under its mode; a map the pool holds under
    the wiki's Watchpoint title keeps its row."""
    november = _page(_patch(
        "2026-11-03", "Overwatch Retail Patch Notes – November 3, 2026",
        _section("Map Updates", "<ul><li>New Escort Map - Gibraltar</li></ul>"),
        _section("Hero Updates", _hero("Nobody", general="<ul><li>New.</li></ul>"))))

    def pages(pull, url, key, **kwargs):
        if key == "patch_notes_2026_12":
            raise cache.FetchError("%s failed after 3 attempts: gone" % url)
        return OCTOBER if key == "patch_notes_2026_10" else november
    monkeypatch.setattr(patch_notes, "cached_get", pages)
    monkeypatch.setattr(patch_notes, "months", lambda first, today: [
        (2026, 10), (2026, 11), (2026, 12)])
    connection = RecordingConnection([
        ("SELECT name, hero_id FROM heroes", [("Sombra", 7), ("Wrecking Ball", 9)]),
        ("SELECT name, mode_id FROM game_modes", [("Escort", 2)]),
        ("SELECT name, map_id FROM maps", [("Watchpoint: Gibraltar", 3)])])
    summary = patch_notes.run(connection, cache.PullContext("cache", log=lambda line: None))
    reader, cursor = connection.cursors
    assert [text for text, _ in reader.statements] == [
        "SELECT name, hero_id FROM heroes", "SELECT name, mode_id FROM game_modes",
        "SELECT name, map_id FROM maps"]
    assert connection.commits == 2            # the read's, before the fetches; the store's
    assert [params[:2] for params in cursor.written("INSERT INTO patches")] == [
        ("October 13, 2026 Patch", datetime.date(2026, 10, 13)),
        ("October 6, 2026 Patch", datetime.date(2026, 10, 6)),
        ("November 3, 2026 Patch", datetime.date(2026, 11, 3))]
    assert cursor.written("DELETE FROM patch_notes") == [()]
    stored = cursor.written("INSERT INTO patch_notes")
    assert [(hero, piece, line) for _, hero, piece, _, line, _ in stored] == [
        (7, "Cyberspace", "Explosion damage reduced from 40 to 20."),
        (7, "", "Moved from Damage to Support role."),
        (7, "Life Hack", "New Minor Perk."),
        (7, "Virus", "Removed."),
        (7, "Hotfix", "Has 2 charges."),
        (9, "Grappling Claw", "Faster.")]
    assert cursor.written("INSERT INTO maps") == [("Grímsvötn", 1)]
    map_modes = cursor.written("INSERT INTO map_modes")
    assert [(mode, map_id) for map_id, mode, _ in map_modes][1] == (2, 3)
    assert summary["maps"] == ["Grímsvötn", "Gibraltar"]
    assert summary["unknown_heroes"] == ["Nobody"] and summary["unknown_modes"] == []
    assert summary["patches"] == 3 and summary["lines"] == 6
    [missing] = summary["missing"]
    assert missing.startswith("2026-12: ") and "gone" in missing
