"""The strategy registry, held to the code it is rendered from: every
strategy of a playbook has an entry anchored by its id in the box of
entries the page hides, and a row in its kind's table under its kind's
heading, which links it; a scored rule's entry writes
its gate, bonus and penalty with its params filled in and defines every
metric they read; a heuristic on a metric names its metric and the
registry's meaning of it; every metric an entry reads says how its range
rule aggregates it over the six; a need and a reward are told apart as
Strategy.need tells them, and a need's budget is the score's; a rule an
entry names links its entry; the citation
record's last entry for an id is the entry's, an earlier one marked as the
earlier rule of that id; the page reads the playbook in force - a crafted
one's drafts counted apart, its gates worded whatever they read, a need at
weight 0 divided by nothing - and links only sections the math page holds;
the shipped scored rules keep the bound the page claims for them; and
every string from a file is escaped. No database, but for that bound on
the built roster."""

import itertools
import os
import re
import shutil

import pytest

from facts import compute
from facts.model import ROLES
from inference import base, bounds, catalog, intervals, ranges, scoring
from inference.expr import Expr
from inference.shapes import legal_shapes
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
    """One entry's card: from its anchor to the next card or the dialog."""
    start = page.index("id='%s'" % sid)
    ends = [i for i in (page.find("<div class='hcard", start), page.find("<dialog", start))
            if i > 0]
    return page[start:min(ends, default=len(page))]


def test_every_strategy_of_the_reference_playbook_has_an_entry_anchored_by_its_id():
    """One card a strategy, anchored by its id, in the catalog's order, all
    in the entries' box after the tables, which the page hides for the
    dialog to copy; and a row a strategy in its kind's table, under its
    kind's heading, the rule's name a link to its card. The weight and the
    gate are a heuristic's columns alone; a kind with no rule says so."""
    strategies = catalog.load(FIXTURE_PLAYBOOK)
    page = render(strategies)
    ids = re.findall(r"<div class='hcard \w+' id='([a-z0-9-]+)'>", page)
    assert ids == [s.id for s in strategies]
    box = page.index("<div id='%s' class='entries'><h2>The entries</h2>" % registry.ENTRIES)
    assert re.findall(r"<div class='hcard \w+' id='([a-z0-9-]+)'>", page[box:]) == ids
    assert page.index("<div class='hcard") > box
    # the tables, each under its kind's heading, before the box
    heads = [page.index("<h2 id='%s'>%s</h2>" % registry.GROUPS[kind]) for kind in catalog.KINDS]
    assert heads == sorted(heads) and heads[-1] < box
    for kind, start, end in zip(catalog.KINDS, heads, [*heads[1:], box], strict=True):
        table, these = page[start:end], [s.id for s in strategies if s.kind == kind]
        assert these, kind
        assert re.findall(r"<a href='#([a-z0-9-]+)'>", table) == these, kind
        assert re.findall(r"<th>([^<]+)</th>", table) == list(registry.COLUMNS[kind]), kind
        assert table.count("<tr>") == len(these) + 1, kind
        # in its own box that scrolls sideways, so a phone's page never does
        assert "<div class='wide'><table class='glance'>" in table, kind
    assert "weight" not in registry.COLUMNS["constraint"] + registry.COLUMNS["assumption"]
    alone = render([strategy("given", kind="assumption")])
    limits = alone[alone.index("id='the_limits'"):alone.index("id='the_heuristics'")]
    assert "None in this playbook." in limits and "<table" not in limits
    # the page's own anchors and the box's id hold an underscore, which no strategy id can
    for anchor in (registry.TOP, registry.ENTRIES, *(a for a, _ in registry.GROUPS.values())):
        assert not catalog.ID_RE.fullmatch(anchor), anchor


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
    # the table sits in a box that scrolls sideways, so a narrow card never cuts it off
    assert "<div class='wide'><table class='reads'>" in entry
    css = pages.static_file("board.css")[0].decode()
    assert ".math .wide { overflow-x:auto; }" in css


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
    # each other need on the guard links its entry; the entry's own id stays text
    assert "It costs 0 to 2.25" in escape and (
        "here solo-escape and <a href='#solo-control'>solo-control</a>") in escape
    assert "here <a href='#solo-escape'>solo-escape</a> and solo-control" in card(
        page, "solo-control")
    assert "the six decides it: it reads the six" in escape
    # a need's norm is read over the reference sixes that meet its gate, and with
    # no spread it reads 1, where a reward's reads 0.5 (scoring.normalised)
    flat = " ".join(escape.split())
    assert "sixes take where they meet the gate" in flat
    assert "or none of them meets the gate, the norm is 1 and the need costs nothing" in flat
    assert scoring.normalised(3.0, 3.0, None, False, need=True) == 1.0
    assert scoring.normalised(3.0, 3.0, None, False, need=False) == 0.5
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
    # the floor is the reference sample's alone; the top-hero sixes set the scale
    flat = " ".join(entry.split())
    assert ("the share's 0 is the lowest score among the reference sample's sixes alone - the"
            " top-hero sixes set the scale, not the floor") in flat


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
    # the id's last entry is the rule's; the one before it is folded away, marked as the
    # earlier rule of the id
    sources = entry[entry.index("<div class='lbl'>sources</div>"):]
    assert sources.index("<p>Edges, again (heuristic).</p>") < sources.index(
        "<summary>1 source</summary>") < sources.index("<details class='earlier'>")
    earlier = sources[sources.index("<details class='earlier'>"):]
    assert earlier.startswith("<details class='earlier'><summary>the earlier rule of this id")
    assert "Edges reward shoves" in earlier and earlier.count("<li>") == 3
    assert "Edges reward shoves" not in sources[:sources.index("<details class='earlier'>")]
    assert "holds no entry for it" in card(render([strategy("uncited", kind="assumption")]),
                                           "uncited")


def test_a_rule_whose_id_two_rules_have_held_cites_the_last_entry_of_the_record():
    """On inference/README.md itself: an id the playbook has held twice -
    poke-needs-reach, a rule of the emptied playbook and one of the reset of
    2026-10-03 - lists its entries the earlier first, and its card shows the
    last as its own and folds the earlier away, marked so. The emptied
    playbook's entries carry the six-board check; the reset's, its check over
    122 boards."""
    cited = registry.citations()
    shipped = catalog.load(catalog.SHIPPED_DIR)
    twice = {s.id: cited[s.id] for s in shipped if len(cited.get(s.id, ())) > 1}
    earlier, last = twice["poke-needs-reach"]
    assert "/6 boards" in earlier.note and "Researched 2026-10-03" in last.note
    page = render(shipped, cited, shipped=True)
    for sid, entries in twice.items():
        entry = card(page, sid)
        sources = entry[entry.index("<div class='lbl'>sources</div>"):]
        folded = sources.index("<details class='earlier'>")
        assert registry._marked(entries[-1].note) in sources[:folded], sid
        for older in entries[:-1]:
            assert registry._marked(older.note) not in sources[:folded], sid
            assert registry._marked(older.note) in sources[folded:], sid
    # an id cited once shows its one entry, with nothing folded away
    once = card(page, "heal-rate")
    assert registry._marked(cited["heal-rate"][0].note) in once
    assert "class='earlier'" not in once


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


def test_a_rule_an_entry_names_links_its_entry():
    """Where an entry's prose or its line in the record names another rule
    of the playbook in backticks, the name links that rule's entry, which the
    registry's script opens in the dialog; the entry's own id and an id the
    playbook does not hold stay code, and the reference playbook's prose
    links each rule it names."""
    rules = [
        strategy("first", kind="heuristic", weight=1, bonus="min(team.hitscan, 1)",
                 body="# First\n\nSee `second`, `first` and `gone`."),
        strategy("second", kind="assumption", body="# Second\n\nThe owner says so.")]
    entry = card(render(rules, {"first": [registry.Citation("Cites `second`.", ())]}), "first")
    assert ("See <a href='#second'><code>second</code></a>, <code>first</code> and"
            " <code>gone</code>.") in entry
    assert "<p>Cites <a href='#second'><code>second</code></a>.</p>" in entry
    page = render(catalog.load(FIXTURE_PLAYBOOK))
    linked = re.findall(r"<a href='#([a-z0-9-]+)'><code>", card(page, "open-queue-tanks"))
    assert linked == ["under-healed", "squish-limit"]
    assert all("id='%s'" % sid in page for sid in linked)


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
    assert registry.SHIPPED_SCORED_BOUND in registry.view_registry()


@pytest.fixture()
def crafted(tmp_path, monkeypatch):
    """A playbook folder of its own, in force through COUNTRIX_STRATEGIES: a
    limit and a constraint's draft, a reward whose gate reads only its
    params, a scored rule whose gate reads no name at all, and a need at
    weight 0 - beside the reference playbook's meta.md. -> the registry's
    page for it."""
    files = {
        "cap-supports": "kind: constraint\nrequire: team.supports <= params.MOST\n"
                        "params:\n    MOST: 3\n",
        "ban-the-carry": "kind: constraint\n",
        "switched-on": "kind: heuristic\nmetric: team.win_mean\ndirection: maximize\n"
                       "weight: 1\nwhen: params.ON >= 1\nparams:\n    ON: 1\n",
        "always-on": "kind: heuristic\nweight: 1\nwhen: 1 > 0\nbonus: min(team.dmg_amp, 1)\n",
        "idle-need": "kind: heuristic\nmetric: team.mobility_count\ndirection: maximize\n"
                     "weight: 0\nwhen: team.supports <= 1\n"}
    for sid, fields in files.items():
        (tmp_path / ("%s.md" % sid)).write_text(
            "---\nname: %s\n%s---\n# %s\n\nThe rule's prose.\n" % (sid, fields, sid), "utf-8")
    shutil.copy(os.path.join(FIXTURE_PLAYBOOK, catalog.META_FILE), tmp_path / catalog.META_FILE)
    monkeypatch.setenv("COUNTRIX_STRATEGIES", str(tmp_path))
    return registry.view_registry()


def test_a_draft_counts_as_a_draft_alone_never_as_a_limit(crafted):
    """One limit and one constraint's draft are one limit and one draft."""
    assert ("<p>The playbook holds 5 strategies: 1 limit; 3 heuristics - 1 reward, 1 need and"
            " 1 scored; and 0 assumptions; 1 draft awaiting /strategy.</p>") in crafted
    assert "<a href='#ban-the-carry'>ban-the-carry</a></td><td>draft</td>" in crafted


def test_a_gate_that_reads_no_metric_says_what_it_reads(crafted):
    """A gate on its params alone, or on no name at all, is settled by the
    board, and its words say what it reads - never an empty list."""
    switched, always = card(crafted, "switched-on"), card(crafted, "always-on")
    assert "as the gate reads only its params, so no six can change it" in switched
    assert "the board settles it once: it reads only its params" in switched
    assert "as the gate reads no metric and no param, so no six can change it" in always
    assert "the board settles it once: it reads no metric and no param" in always
    for entry in (switched, always):
        assert not re.search(r"reads (only )?[,.\n<]", entry)


def test_a_need_at_weight_0_is_scaled_by_1_and_costs_nothing(crafted):
    """need_scales scales a guard whose weights sum to 0 by 1, dividing by
    nothing; the card says so, and that the need costs nothing."""
    entry = card(crafted, "idle-need")
    assert scoring.need_scales(catalog.load()) == {"idle-need": 1.0}
    assert "s           = 1\n" in entry and "/ 0" not in entry
    assert "the weights on this guard sum to 0, so s scales nothing" in entry
    assert "At weight 0 it costs nothing." in entry
    glance = crafted[crafted.index("href='#idle-need'"):]
    assert glance[:glance.index("</tr>")].endswith("<td>need</td><td>0</td><td>0</td>"
                                                   "<td>the six</td>")


def test_every_shipped_scored_rule_keeps_its_bonus_and_its_penalty_within_0_to_1(
        synthetic_world):
    """The claim the registry and the math page's engine's weights make of
    the shipped playbook (registry.SHIPPED_SCORED_BOUND), held by brute
    force: on every six the shipped limits allow on the synthetic World -
    every shape they allow, from four heroes a role - with no map and on
    each of its maps, red unrevealed and two of its picks revealed, each
    shipped scored rule's bonus and penalty, read whether its gate holds or
    not, lie within 0 to 1."""
    shipped = catalog.load(catalog.SHIPPED_DIR)
    scored = [s for s in shipped if s.form == "scored"]
    roles = {
        role: [h for h in synthetic_world.heroes.values() if h.role == role and h.released]
        for role in ROLES}
    shapes = legal_shapes(shipped)
    sixes = [
        [*t, *d, *s] for shape in shapes
        for t in itertools.combinations(roles["tank"], shape.tanks)
        for d in itertools.combinations(roles["damage"], shape.damage)
        for s in itertools.combinations(roles["support"], shape.supports)]
    assert scored
    reds = [(), (synthetic_world.hero("Mortar"), synthetic_world.hero("Gale"))]
    read = set()
    for m in (None, *synthetic_world.maps_sorted()):
        for red in reds:
            objective = scoring.Objective(synthetic_world, m, red=red, side="defense",
                                          catalog=shipped, base=base.OFF)
            for heroes in sixes:
                cand = objective.prepare(scoring.Candidate(heroes))
                if cand.violations:
                    continue
                sc = cand.scope
                for r in scored:
                    sc["params"] = r.params_section
                    for expr in (r.bonus, r.penalty):
                        if expr is not None:
                            value = expr.evaluate(sc)
                            assert 0 <= value <= 1, (r.id, expr.source, value, cand.names)
                read.add(tuple(sum(h.role == role for h in cand.heroes) for role in ROLES))
    # every shape the shipped limits allow was read
    assert read == {tuple(shape) for shape in shapes}
    # the claim the test holds is the one both pages make, word for word
    assert registry.SHIPPED_SCORED_BOUND in registry.view_registry()
    assert registry.SHIPPED_SCORED_BOUND in " ".join(pages.view_math().split())


@pytest.mark.invariant
def test_the_shipped_scored_rules_keep_the_bound_on_the_built_roster(world):
    """The same claim on the built database's roster, too many sixes for a
    brute force: each shipped scored rule's bonus and penalty over every
    six of each shape the shipped limits allow, read off the range rules at
    the shape's root - which hold every completion (test_bounds) - lie
    within 0 to 1, give or take the rules' float slack."""
    shipped = catalog.load(catalog.SHIPPED_DIR)
    objective = scoring.Objective(world, None, red=(), catalog=shipped, base=base.OFF)
    space = ranges.Space(objective, (), bounds.roster(world, (), set()))
    static = bounds._board_values(objective)
    roots = [
        ranges.Branch((), tuple((r, 0, n) for r, n in enumerate(shape) if n))
        for shape in legal_shapes(shipped)]
    for r in (s for s in shipped if s.form == "scored"):
        for expr in (e for e in (r.bonus, r.penalty) if e is not None):
            steps = ranges.rule_order(space, [
                n for n in expr.names if n.split(".", 1)[0] in ("team", "matchup")])
            read = intervals.abstract(expr, r.params, static)
            for root in roots:
                value = read(ranges.evaluate(steps, root))
                assert isinstance(value, intervals.Iv), (r.id, root.open, value)
                assert value.lo >= -1e-9 and value.hi <= 1 + 1e-9, (r.id, root.open, value)


def test_the_page_links_only_anchors_it_or_the_math_page_holds():
    """The table of contents and each kind's table resolve on the page; each
    form's link and each derived metric's resolve on the math page."""
    page = render([*catalog.load(FIXTURE_PLAYBOOK), strategy(
        "heal-bar", kind="heuristic", weight=2, penalty="matchup.heal_shortfall")])
    for anchor in set(re.findall(r"href='#([^']+)'", page)):
        assert "id='%s'" % anchor in page, anchor
    math = pages.view_math()
    linked = set(re.findall(r"href='/math#([^']+)'", page))
    assert {"function", "chosen", "equation", "base-weights", "healing-floor"} <= linked
    for anchor in linked | {target for target, _ in registry.DERIVED.values()}:
        assert "id='%s'" % anchor in math, anchor
