"""The strategy registry, held to the code it is rendered from: every
strategy of a playbook has an entry anchored by its id, filed under its
kind and linked from the table at a glance; a scored rule's entry writes
its gate, bonus and penalty with its params filled in and defines every
metric they read; a heuristic on a metric names its metric and the
registry's meaning of it; every metric an entry reads says how its range
rule aggregates it over the six; a need and a reward are told apart as
Strategy.need tells them, and a need's budget is the score's; the citation
record's entries and sources are the entry's; the page reads the playbook
in force and links only sections the math page holds; and every string
from a file is escaped. No database."""

import re

import pytest

from facts import compute
from inference import catalog, ranges, scoring
from inference.expr import Expr
from inference.strategy import Strategy
from tests.verification.inference import DEFAULT, FIXTURE_PLAYBOOK
from ui import pages, registry


def strategy(sid, **fields):
    """A strategy built from its frontmatter fields, as the catalog builds one."""
    body = fields.pop("body", "# %s\n\nThe rule's prose." % sid)
    return Strategy(sid, {"name": sid.replace("-", " "), **fields}, body=body)


def render(strategies, record=None, shipped=False):
    """The registry's article for these strategies, at the reference
    playbook's engine weights."""
    return registry.article(strategies, record or {}, DEFAULT,
                            playbook="tests/fixtures/playbook", shipped=shipped)


def card(page, sid):
    """One entry's card: from its anchor to the next card or group."""
    start = page.index("id='%s'" % sid)
    ends = [i for i in (page.find("<div class='hcard", start), page.find("<h2", start)) if i > 0]
    return page[start:min(ends, default=len(page))]


def test_every_strategy_of_the_reference_playbook_has_an_entry_anchored_by_its_id():
    """One card a strategy, in the catalog's order, each under its kind's
    heading and a link from the table at a glance."""
    strategies = catalog.load(FIXTURE_PLAYBOOK)
    page = render(strategies)
    ids = re.findall(r"<div class='hcard \w+' id='([a-z0-9-]+)'>", page)
    assert ids == [s.id for s in strategies]
    glance = page[page.index("id='%s'" % registry.GLANCE):page.index("<div class='hcard")]
    assert re.findall(r"<a href='#([a-z0-9-]+)'>", glance) == ids
    groups = [page.index("id='%s'" % registry.GROUPS[kind][0]) for kind in catalog.KINDS]
    for s in strategies:
        at = page.index("id='%s'" % s.id)
        kind = catalog.KINDS.index(s.kind)
        assert groups[kind] < at and all(at < g for g in groups[kind + 1:]), s.id
    # the page's own anchors hold an underscore, which no strategy id can
    assert not any(catalog.ID_RE.fullmatch(anchor) for anchor, _ in registry.GROUPS.values())
    assert not catalog.ID_RE.fullmatch(registry.GLANCE)


def test_a_scored_rules_entry_writes_its_bonus_and_penalty_with_its_params_filled_in():
    rule = strategy(
        "edge-shoves", kind="heuristic", weight=1.5, when="map.hazards >= params.STANDOUT",
        bonus="min(max(team.shove_count - params.FLOOR, 0), params.CAP) / params.CAP",
        penalty="max(0, params.SAVES - team.team_saves) * 0.5",
        params={"STANDOUT": 0.5, "FLOOR": 2, "CAP": 3, "SAVES": 1})
    entry = card(render([rule]), "edge-shoves")
    assert "term(x)     = 1.5 &middot; ( bonus(x) &minus; penalty(x) )" in entry
    assert "gate        %s" % pages.esc("map.hazards >= 0.5") in entry
    assert "bonus(x)    = %s" % pages.esc("min(max(team.shove_count - 2, 0), 3) / 3") in entry
    assert "penalty(x)  = %s" % pages.esc("max(0, 1 - team.team_saves) * 0.5") in entry
    formula = entry[entry.index("<pre class='eq'>"):entry.index("</pre>")]
    assert "params." not in formula
    assert "params      STANDOUT = 0.5 &middot; FLOOR = 2 &middot; CAP = 3 &middot; SAVES = 1" in (
        formula)
    # every metric it reads, defined: the registry's meaning and how it aggregates
    known = compute.registry()
    for key in ("map.hazards", "team.shove_count", "team.team_saves"):
        assert "<code>%s</code>" % key in entry and pages.esc(known[key]) in entry, key
    for key in ("team.shove_count", "team.team_saves"):
        assert pages.esc(ranges.RULES[key].aggregate) in entry, key
    assert pages.esc(registry.SETTLED["map"]) in entry
    assert "the board settles it once: it reads only the ground in play" in entry
    assert "the bonus adds up to 1.5 times its largest value" in entry


def test_a_constant_bonus_or_penalty_moves_a_six_by_exactly_its_weight_times_it():
    rule = strategy("split-six", kind="heuristic", weight=0.5, when="team.style_share <= 0.5",
                    penalty="1")
    entry = card(render([rule]), "split-six")
    assert "there is no bonus, and the penalty takes exactly 0.5" in entry
    assert "bonus(x)    = 0, none set" in entry and "which the six decides" in entry
    assert "Unlike a need, a scored rule can pay or charge a six" in entry


def test_a_heuristic_on_a_metric_names_its_metric_and_its_registry_meaning():
    strategies = catalog.load(FIXTURE_PLAYBOOK)
    page, known = render(strategies), compute.registry()
    on_metrics = [s for s in strategies if s.form == "heuristic"]
    assert on_metrics
    for s in on_metrics:
        entry = card(page, s.id)
        assert "norm( %s(x) )" % s.metric in entry, s.id
        assert "<code>%s</code>, %s" % (s.metric, pages.esc(known[s.metric])) in entry, s.id
        assert pages.esc(ranges.RULES[s.metric].aggregate) in entry, s.id
        better = "minimize: less is better" if s.direction == "minimize" else (
            "maximize: more is better")
        assert better in entry, s.id


def test_a_need_and_a_reward_are_told_apart_as_the_code_tells_them():
    """A heuristic on a metric whose gate the six decides is a need, the
    rest rewards, as Strategy.need and the score read them; the needs on one
    guard share the budget at the scale the score gives them."""
    rules = [
        strategy("solo-escape", kind="heuristic", metric="team.mobility_count",
                 direction="maximize", weight=3, when="team.supports <= 1"),
        strategy("solo-control", kind="heuristic", metric="team.cc_count",
                 direction="maximize", weight=1, when="team.supports <= 1"),
        strategy("their-fliers", kind="heuristic", metric="team.hitscan",
                 direction="maximize", weight=2, when="enemy.light_flyers >= 1"),
        strategy("light-pool", kind="heuristic", metric="team.pool_total",
                 direction="minimize", weight=0.5)]
    page = render(rules)
    for s in rules:
        form = registry.shown_form(s)
        assert form == ("need" if s.need else "reward"), s.id
        assert "<p>A %s: a heuristic on a metric" % form in card(page, s.id)
        assert "<td>%s</td>" % form in page[page.index("href='#%s'" % s.id):]
    assert [s.id for s in rules if s.need] == ["solo-escape", "solo-control"]
    assert scoring.need_scales(rules) == {"solo-escape": 0.75, "solo-control": 0.75}
    escape = card(page, "solo-escape")
    assert "= min( 1, max( 2, 3 ) / 4 ) = 0.75" in escape
    assert "It costs 0 to 2.25" in escape and "here solo-escape and solo-control" in escape
    assert "the six decides it: it reads the six" in escape
    assert "&minus;0.75 to 0" in page and "&minus;2.25 to 0" in page
    fliers = card(page, "their-fliers")
    assert "so it adds 0 to 2" in fliers and "the board settles it once" in fliers
    assert "the gate read as true" in fliers
    light = card(page, "light-pool")
    assert "norm(v)     = 1 &minus; clamp(" in light and "It has no gate" in light


def test_a_limit_writes_its_require_with_its_params_and_weighs_nothing():
    rule = strategy("three-supports", kind="constraint", require="team.supports <= params.MAX",
                    params={"MAX": 3})
    entry = card(render([rule]), "three-supports")
    assert "legal(x)    only where  %s  holds on x" % pages.esc("team.supports <= 3") in entry
    assert "a six where it fails is removed before any score is read" in entry
    assert "weighs nothing" in entry and "drops the shapes that break it" in entry
    assert "weight" not in entry[:entry.index("what it does")]


def test_an_assumption_adds_nothing_to_a_score():
    rule = strategy("given", kind="assumption", body="# Given\n\nThe owner says so.")
    page = render([rule])
    entry = card(page, "given")
    assert "It adds nothing to a score" in entry and "The owner says so." in entry
    assert "<pre" not in entry and "/math#equation" in entry


def test_the_citation_record_gives_each_entry_its_lines_and_sources(tmp_path):
    record = tmp_path / "README.md"
    record.write_text(
        "# The record\n\n"
        "- `edge-shoves` - Edges reward shoves (heuristic). <b>Applies</b>.\n"
        "  - https://example.org/a?x=1&y='2'\n"
        "  - a book, page 3\n"
        "  - https://example.org/L%C3%BAcio\n"
        "- `other` - Other (heuristic).\n\n"
        "A paragraph between.\n"
        "- `edge-shoves` - Edges, again (heuristic).\n"
        "  - https://example.org/b\n", "utf-8")
    cited = registry.citations(str(record))
    assert cited == {
        "edge-shoves": [
            registry.Citation("Edges reward shoves (heuristic). <b>Applies</b>.",
                              ("https://example.org/a?x=1&y='2'", "a book, page 3",
                               "https://example.org/L%C3%BAcio")),
            registry.Citation("Edges, again (heuristic).", ("https://example.org/b",))],
        "other": [registry.Citation("Other (heuristic).", ())]}
    rule = strategy("edge-shoves", kind="heuristic", weight=1, bonus="min(team.shove_count, 1)")
    entry = card(render([rule], cited), "edge-shoves")
    assert "<b>Applies" not in entry and "&lt;b&gt;Applies&lt;/b&gt;" in entry
    assert "href='https://example.org/a?x=1&amp;y=&#x27;2&#x27;'" in entry
    assert "<li>a book, page 3</li>" in entry
    # a link reads as the address without its scheme or its escapes, and goes where it says
    assert "href='https://example.org/L%C3%BAcio' target='_blank' rel='noopener'>" + (
        "example.org/L\u00facio</a>") in entry
    assert "<summary>3 sources</summary>" in entry and "<summary>1 source</summary>" in entry
    assert "holds no entry for it" in card(render([strategy("uncited", kind="assumption")]),
                                           "uncited")


def test_the_parser_reads_every_entry_and_source_of_the_record():
    """inference/README.md parsed whole: each `- `id`` line is an entry, and
    each indented source under it is that entry's."""
    with open(registry.RECORD_PATH, encoding="utf-8") as handle:
        text = handle.read()
    cited = registry.citations()
    bullets = re.findall(r"^- `([a-z0-9-]+)`", text, re.M)
    assert sorted(bullets) == sorted(sid for sid, entries in cited.items() for _ in entries)
    assert len(re.findall(r"^  - ", text, re.M)) == sum(
        len(entry.sources) for entries in cited.values() for entry in entries)


@pytest.mark.parametrize(("source", "params", "written"), [
    ("team.supports <= params.MAX", {"MAX": 3}, "team.supports <= 3"),
    ("params.A * team.x + params.B", {"A": 0.5, "B": -2}, "0.5 * team.x + (-2)"),
    ("map.name == 'params.A' or team.x > params.A", {"A": 1.0}, "map.name == 'params.A' or"
                                                                " team.x > 1"),
])
def test_an_expression_is_written_with_its_params_filled_in(source, params, written):
    assert registry.filled(Expr(source), params) == written


def test_every_string_from_a_file_is_escaped():
    rule = strategy("markup", kind="heuristic", category="<i>cat</i>", weight=1,
                    name="<script>alert(1)</script>", bonus="min(team.hitscan, 1)",
                    body="# x\n\n<img src=x onerror=alert(1)> and `code`")
    page = render([rule], {"markup": [registry.Citation("<b>note</b>", ("javascript:alert(1)",))]})
    for raw in ("<script>", "<img", "<i>cat", "<b>note", "href='javascript"):
        assert raw not in page, raw
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page and "<code>code</code>" in page


def test_the_page_reads_the_playbook_in_force_and_its_meta(monkeypatch):
    """view_registry reads COUNTRIX_STRATEGIES on every call; the default
    engine's weights are that playbook's meta.md; the shipped scored rules'
    bound is claimed for the shipped playbook alone."""
    monkeypatch.setenv("COUNTRIX_STRATEGIES", FIXTURE_PLAYBOOK)
    page = registry.view_registry()
    assert all("id='%s'" % s.id in page for s in catalog.load(FIXTURE_PLAYBOOK))
    assert "<title>the strategy registry</title>" in page and "<code>%s</code>" % (
        catalog.playbook_name()) in page
    assert ("base(x) = 1 &middot; ( 1 &middot; rates(x) + 0.1 &middot; synergy(x) + 0.05"
            " &middot; counters(x) )") in page
    assert "Every shipped scored rule" not in page
    monkeypatch.delenv("COUNTRIX_STRATEGIES")
    assert "Every shipped scored rule keeps its bonus and its penalty within 0 to 1" in (
        registry.view_registry())


def test_the_page_links_only_anchors_it_or_the_math_page_holds():
    """The table of contents and the table at a glance resolve on the page;
    each form's link and each derived metric's resolve on the math page."""
    page = render([*catalog.load(FIXTURE_PLAYBOOK), strategy(
        "heal-bar", kind="heuristic", weight=2, penalty="matchup.heal_shortfall")])
    for anchor in set(re.findall(r"href='#([^']+)'", page)):
        assert "id='%s'" % anchor in page, anchor
    math = pages.view_math()
    linked = set(re.findall(r"href='/math#([^']+)'", page))
    assert {"function", "chosen", "equation", "base-weights", "healing-floor"} <= linked
    for anchor in linked | {target for target, _ in registry.DERIVED.values()}:
        assert "id='%s'" % anchor in math, anchor
