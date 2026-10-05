"""The study page, /study: ui/study.py's reading of the results file and
ui/charts.py's charts - on tests/fixtures/study.json, the study's results
file of 2026-10-05 trimmed, every part in the shape the benchmark's
harness writes it; on the file the page reads, ui/static/study.json,
once it is in place; and on files written here. Every chart is drawn
beside a table of its numbers, every part of a harness file fills its
block, every string the file holds is escaped, the schema is checked, a
file missing, unreadable or of another schema leaves the proof standing
and says why, a playbook or an engine the study did not measure is said,
the numbers drawn are the file's, the count check and the assumptions
are the shipped playbook's, the code's constants are the code's, and the
proof's code links name lines that exist at its commit. No server and no
database."""

import html
import json
import os
import re
import subprocess

import pytest

from db import ROOT
from inference import base, bounds, catalog, scoring, solver
from tests.verification.inference import FIXTURE_PLAYBOOK, FIXTURES
from ui import charts, study
from ui.pages import esc

FIXTURE = os.path.join(FIXTURES, "study.json")
FIGURES = ("shares", "parts", "meta-and-team", "rules-by-map", "search")
EVIL = "<script>alert(1)</script>'\""
IN_PLACE = pytest.param(study.RESULTS_PATH, id="in-place", marks=pytest.mark.skipif(
    not os.path.isfile(study.RESULTS_PATH), reason="no results file in place yet: %s"
    % study.RESULTS_NAME))


def sample():
    with open(FIXTURE, encoding="utf-8") as handle:
        return json.load(handle)


def written(tmp_path, data):
    path = tmp_path / "study.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def figure(page, fid):
    start = page.index("<figure class='viz' id='%s'>" % fid)
    return page[start:page.index("</figure>", start)]


def words(fragment):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def cells(page, head):
    """The rows of the table whose head holds `head`, each a list of its
    cells' text."""
    at = page.index("<th>%s</th>" % head)
    start, end = page.rindex("<table", 0, at), page.index("</table>", at)
    rows = re.findall(r"<tr>(.*?)</tr>", page[start:end])[1:]
    return [[words(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row)] for row in rows]


def flat(page):
    return " ".join(page.split())


def labels(data):
    return {m["id"]: m["label"] for m in data["metrics"]}


def test_the_fixture_holds_the_schema_and_the_shapes_the_harness_writes():
    """The fixture is the harness's own file, trimmed: its arms and metrics
    lists with ids, each theorem's checks a list of method rows, a rule's
    satisfaction by arm and the slider's aggregates as {mean, ...}, a
    board row's search a list in the legend's order, the share of boards
    with one optimum, and the brute force's wall time - the shapes the page
    reads."""
    data = sample()
    assert data["schema"] == study.SCHEMA == "countrix-study/1" and "sample" not in data
    assert all("id" in arm for arm in data["arms"]) and all("id" in m for m in data["metrics"])
    theorems = data["proof"]["theorems"]
    assert all(isinstance(t["checked"], list) and t["checked"] for t in theorems)
    for rule in data["rules"].values():
        assert all(set(s) == {"mean", "n"} for s in rule["satisfaction"].values())
    assert all(isinstance(step["y_matchup"], dict) for step in data["slider"]["per_mu"])
    assert "search is [legal sixes, branches walked, sixes scored in full, seconds, sixes tied]" \
        in data["legend"]["rows"]
    assert all(len(row["search"]) == len(study.ROW_SEARCH) for row in data["rows"])
    assert 0.0 <= data["proof"]["search"]["unique_optimum"] <= 1.0
    assert "wall_seconds" in data["proof"]["brute_force"][0]


@pytest.mark.parametrize("path", [FIXTURE, IN_PLACE])
def test_every_part_of_a_harness_file_fills_its_block(path):
    """A file in the harness's shapes leaves no block empty and no cell of
    the evidence, the rules or the slider blank: every check with its
    method and counts, the brute force with its times, every rule kept by
    every six it was measured on, every slider step on the yardsticks, the
    search's share of boards with one optimum and its boards' dots - run
    on the file in place too, before it ships."""
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    page = study.view_study(path)
    assert "holds none of" not in page and study.NONE_YET not in page
    for fid in FIGURES:
        assert "<svg class='chart" in figure(page, fid), fid
    checks = cells(page, "the claim")
    assert len(checks) == sum(len(t["checked"]) for t in data["proof"]["theorems"])
    assert all(row[2] and "-" not in row[3:] for row in checks), checks
    assert "Filled slot by slot, Countrix's own objective lands" in page
    assert all("-" not in row for row in cells(page, "legal sixes"))
    rules = cells(page, "moves the six")
    assert len(rules) == len(data["rules"]) and all("-" not in row for row in rules)
    slider = cells(page, "the engine&#x27;s part")
    assert len(slider) == len(data["slider"]["per_mu"]) and all("-" not in r for r in slider)
    steps = page[page.index("id='slider'"):page.index("id='gaps'")]
    for metric in study.YARDSTICK:
        assert "<th>%s</th>" % esc(labels(data)[metric]) in steps, metric
    search = figure(page, "search")
    assert "The optimum ties no other six on" in search and "class='faint'" in search
    shipped = next(a["label"] for a in data["arms"] if a["id"] == study.SHIPPED)
    assert [row for row in cells(page, "against") if row[0] == shipped] == []


def test_every_chart_is_drawn_beside_a_table_of_its_numbers():
    """Each of the five charts is an inline SVG with its accessible name,
    and its numbers sit under its fold in a table, the twin a reader without
    the chart reads; the answer in numbers, the checks, the brute force,
    the rules, the slider, the board-by-board gaps and the other sets are
    tables of their own."""
    page = study.view_study(FIXTURE)
    for fid in FIGURES:
        fig = figure(page, fid)
        assert "<svg class='chart" in fig and "role='img' aria-label='" in fig, fid
        numbers = fig[fig.index("<summary>the numbers</summary>"):]
        assert "<table class='numbers'>" in numbers, fid
    assert "<table class='numbers profile'>" in page
    for head in ("<th>the claim</th>", "<th>legal sixes</th>", "<th>moves the six</th>",
                 "<th>the engine&#x27;s part</th>", "<th>against</th>", "<th>boards</th>"):
        assert head in page, head
    assert "<script" not in page


def test_a_sample_says_so_above_everything_and_a_measured_file_does_not(tmp_path):
    data = sample()
    data["sample"] = True
    page = study.view_study(written(tmp_path, data))
    assert page.index("<b>A sample.</b>") < page.index("<figure")
    del data["sample"]
    measured = study.view_study(written(tmp_path, data))
    assert "A sample." not in measured
    assert "The results: generated %s; Countrix at %s;" % (
        data["generated"], data["provenance"]["countrix"]["commit"][:7]) in measured


def test_without_a_results_file_the_proof_stands_and_the_results_are_not_in_place(
        tmp_path, monkeypatch):
    """No file: the proof, its count check, the assumptions and the audit
    stand, and every block the results fill says there is nothing yet, under
    the line that the study's results are not in place."""
    monkeypatch.delenv("COUNTRIX_STRATEGIES", raising=False)
    page = study.view_study(str(tmp_path / "none.json"))
    assert ("<div class='warnbox'>The study&#x27;s results are not in place: there is no results"
            " file, none.json.</div>") in page
    assert "<svg" not in page and "<figure" not in page
    assert page.count(study.NONE_YET) == len(study.RESULT_BLOCKS)
    for kept in ("<h3 id='the-theorem'>", "<b>Lemma 1.</b>", "<h2 id='hard-coded'>",
                 "href='/registry#players-play-optimally'"):
        assert kept in page, kept
    # the count check: the shipped playbook's shapes on the proof's roster, the
    # 13,030,920 legal sixes the walk considered on every open board that day
    assert "<b>13,030,920</b>" in page
    assert "The report follows the study's results; there are none yet." in page


def test_the_count_check_and_the_assumptions_are_the_shipped_playbooks_whatever_is_in_force(
        monkeypatch):
    """The proof's count check and the assumptions the study is relative to
    are the shipped playbook's under any playbook in force; an assumption
    links its registry entry only where the registry - the playbook in
    force's - holds it."""
    shipped = [s for s in catalog.load(catalog.SHIPPED_DIR) if s.kind == "assumption"]
    reference = {s.id for s in catalog.load(FIXTURE_PLAYBOOK)}
    monkeypatch.setenv("COUNTRIX_STRATEGIES", FIXTURE_PLAYBOOK)
    page = study.view_study("/nowhere/study.json")
    assert "<b>13,030,920</b>" in page
    for s in shipped:
        assert esc(s.name) in page, s.id
        assert ("href='/registry#%s'" % s.id in page) == (s.id in reference), s.id
    for rid in reference - {s.id for s in catalog.load(catalog.SHIPPED_DIR)}:
        assert "href='/registry#%s'" % rid not in page, rid


def test_a_playbook_or_an_engine_the_study_did_not_measure_is_said_above_the_results(
        tmp_path, monkeypatch):
    """The board's playbook and default engine are compared with the ones
    the file records: where both match nothing is said, and where either
    differs a warning above the results names it, the digests' openings
    and each field of the engine's stamp that moved."""
    monkeypatch.delenv("COUNTRIX_STRATEGIES", raising=False)
    stamp = base.stamp(catalog.engine_weights())
    data = sample()
    measured = data["provenance"]["countrix"]
    measured.update(playbook_digest=catalog.playbook_digest()[:12], base_stamp=dict(stamp))
    assert "Not the board's objective" not in study.view_study(written(tmp_path, data))
    measured.update(playbook_digest="0" * 12, base_stamp={**stamp, "synergy": 0.5})
    page = study.view_study(written(tmp_path, data))
    warned = page.index("<b>Not the board's objective.</b>")
    assert warned < page.index("<table class='numbers profile'>")
    assert ("The playbook in force, inference/strategies, is not the one the study measured: its"
            " digest opens %s, the study's 000000000000." % catalog.playbook_digest()[:12]
            ) in page
    assert "synergy %s, the study's 0.5." % study.plain(stamp["synergy"]) in page
    monkeypatch.setenv("COUNTRIX_STRATEGIES", FIXTURE_PLAYBOOK)
    measured.update(playbook_digest=catalog.playbook_digest(catalog.SHIPPED_DIR),
                    base_stamp={**stamp, "counter": 0.999})
    page = study.view_study(written(tmp_path, data))
    assert "The playbook in force, tests/fixtures/playbook, is not the one" in page
    assert "counter %s, the study's 0.999" % study.plain(catalog.engine_weights().counter) \
        in page


def test_a_file_of_another_schema_or_none_shows_none_of_it(tmp_path):
    data = sample()
    data["schema"] = "countrix-study/2"
    page = study.view_study(written(tmp_path, data))
    assert ("is of the schema countrix-study/2; this page reads countrix-study/1, so it shows"
            " none of it.") in page
    assert "<svg" not in page
    del data["schema"]
    assert "is of the schema none;" in study.view_study(written(tmp_path, data))


def test_a_file_that_is_not_json_or_holds_no_object_is_said_and_shows_nothing(tmp_path):
    path = tmp_path / "study.json"
    path.write_text("{not json", encoding="utf-8")
    page = study.view_study(str(path))
    assert "The results file, study.json, cannot be read:" in page and "<svg" not in page
    path.write_text("[1, 2]", encoding="utf-8")
    assert "The results file, study.json, holds no object." in study.view_study(str(path))


def test_every_string_the_file_holds_reaches_the_page_escaped(tmp_path):
    """Labels, models, sources, names, ids, words and the provenance from
    the file are text, whatever they hold; a number written as a string is
    never drawn as a number; and the report's link takes a web address,
    never a script's."""
    data = sample()
    for arm in data["arms"]:
        arm.update(label=EVIL + arm["label"], model=EVIL, sources=[EVIL])
    for metric in data["metrics"]:
        metric["label"] = EVIL
    for rule in data["rules"].values():
        rule["name"] = EVIL
    data["rules"][EVIL] = dict(next(iter(data["rules"].values())))
    data["design"]["maps"][0]["name"] = EVIL
    data["design"]["sets"]["fresh"]["seed"] = EVIL
    theorem = data["proof"]["theorems"][0]
    theorem["statement"] = EVIL
    theorem["checked"][0].update(method=EVIL, skipped=1, skipped_why=EVIL)
    data["proof"]["brute_force"][0].update(map=EVIL, side=EVIL, commit=EVIL)
    data["proof"]["greedy"]["countrix"]["unit"] = EVIL
    data["slider"]["scored_on"] = EVIL
    data["provenance"]["countrix"]["commit"] = EVIL
    data["generated"] = EVIL
    data["report"] = {"url": "javascript:alert(1)", "title": EVIL}
    data["aggregates"]["fresh"]["test"]["cx_full"]["y_matchup"] = {
        "mean": "<b>9</b>", "lo": 1, "hi": 2}
    page = study.view_study(written(tmp_path, data))
    assert "<script" not in page and "alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;&#x27;&quot;" in page
    assert "javascript:" not in page and "<b>9</b>" not in page


def test_the_numbers_drawn_are_the_files(tmp_path):
    """A mean and its range the file holds are the ones the chart's tooltip
    and its table show, a percentile the one the answer's cell shows, and a
    count the one the brute force's table shows, thousands separated."""
    data = sample()
    shipped = data["aggregates"]["fresh"]["test"]["cx_full"]
    shipped["y_matchup"] = {"mean": 37.3, "lo": 30.0, "hi": 44.5, "n": 180}
    shipped["pct_str_bz"] = {"mean": 88.4, "lo": 80.0, "hi": 93.0, "n": 180}
    data["proof"]["brute_force"][0]["legal"] = 12345678
    page = study.view_study(written(tmp_path, data))
    shares = figure(page, "shares")
    assert "Countrix as shipped - %s 37.3 (30.0 to 44.5)" % esc(labels(data)["y_matchup"]) \
        in shares
    assert "37.3 <span class='rng'>(30.0 to 44.5)</span>" in shares
    assert "title='%s: 88.4 (80.0 to 93.0)'>88</td>" % esc(labels(data)["pct_str_bz"]) in page
    assert "<td>12,345,678</td>" in page


def test_each_part_is_read_in_the_shape_the_harness_writes(tmp_path):
    """A theorem's checks are a row each, the first under its claim, a
    skip said beside its method; a rule's satisfaction and a slider step's
    aggregates are read as {mean, ...}; the share of boards with one
    optimum is a share of the search's boards; the brute force's time is
    its wall time; and the funnel's dots are the primary set's rows,
    each read in the legend's order."""
    data = sample()
    first = {"method": "way one", "boards": 3, "cases": 4567, "violations": 0}
    second = dict(first, method="way two", boards=5, cases=6, skipped=2, skipped_why="a reason")
    data["proof"]["theorems"][0]["checked"] = [first, second]
    rid, rule = next(iter(data["rules"].items()))
    rule["satisfaction"][study.SHIPPED] = {"mean": 0.613, "n": 360}
    data["slider"]["per_mu"][0]["y_matchup"] = {"mean": 12.3, "lo": 10.1, "hi": 14.5, "n": 360}
    data["proof"]["search"].update(unique_optimum=0.5, boards=360)
    data["proof"]["brute_force"][0]["wall_seconds"] = 98.7
    page = study.view_study(written(tmp_path, data))
    checks = cells(page, "the claim")
    assert checks[0][0] == "T1" and checks[0][2:] == ["way one", "3", "4,567", "0"]
    assert checks[1][:2] == ["", ""] and checks[1][2:] == [
        "way two; 2 skipped: a reason", "5", "6", "0"]
    kept = cells(page, "moves the six")[0]
    assert kept[5 + list(rule["satisfaction"]).index(study.SHIPPED)] == "0.61", rid
    assert "12.3 <span class='rng'>(10.1 to 14.5)</span>" in page[page.index("id='slider'"):]
    assert "on 50% of the boards, 180 of 360." in figure(page, "search")
    assert cells(page, "legal sixes")[0][3] == "98.7"
    search = figure(page, "search")
    dots = search.count("class='faint'")
    assert dots > 0
    for row in data["rows"]:
        if row["set"] == "fresh":
            row["search"] = []
    assert "class='faint'" not in figure(study.view_study(written(tmp_path, data)), "search")


def test_the_board_by_board_table_holds_countrix_as_shipped_alone(tmp_path):
    """Board by board is Countrix as shipped against each arm on the
    primary slice: a pair of another capture's or another source's Countrix,
    or of another slice, is left out, whatever it holds."""
    data = sample()
    for pair in data["paired"]:
        if pair["a"] != study.SHIPPED or pair["slice"] != "test":
            pair["gap"] = {"mean": 77.7, "lo": 76.6, "hi": 78.8}
    rows = cells(study.view_study(written(tmp_path, data)), "against")
    against = {p["b"] for p in data["paired"] if (p["a"], p["slice"]) == (study.SHIPPED, "test")}
    assert len(rows) == len(against)
    assert not any("77.7" in cell for row in rows for cell in row)


def test_a_raw_rate_the_file_carried_by_mistake_is_never_drawn(tmp_path):
    """The page reads its metrics by their ids - a percentile, a share or a
    satisfaction each - so a raw win rate a file carried under another id
    is never drawn."""
    before = study.view_study(written(tmp_path, sample()))
    data = sample()
    data["aggregates"]["fresh"]["test"]["cx_full"]["str_bz"] = {
        "mean": 77.777, "lo": 70.0, "hi": 80.0, "n": 180}
    after = study.view_study(written(tmp_path, data))
    assert after.count("77.8") == before.count("77.8")


@pytest.mark.parametrize(("module", "name", "phrase"), [
    (solver, "NODE_BUDGET", "within its budget - %s branches"),
    (solver, "SCORE_BUDGET", "or %s sixes scored in full ("),
    (solver, "RANK_CAP", "exactly up to %s;"),
    (solver, "TIE_BUDGET", "within %s sixes scored and reads"),
    (bounds, "FOLD_COUNTS", "It reads %s counts at most"),
    (bounds, "MEMO_CAP", "clearing the memo at %s entries"),
    (scoring, "SCORE_PLACES", "agree to %s decimal places"),
])
def test_the_study_quotes_each_constant_from_the_code(monkeypatch, module, name, phrase):
    monkeypatch.setattr(module, name, 37)
    assert phrase % "37" in flat(study.view_study("/nowhere/study.json"))


def test_the_proofs_code_links_name_lines_that_exist_at_its_commit():
    """Every code link opens a file's lines at the commit the proof read,
    its text the file and the lines it opens; each file is there at that
    commit, and long enough. CI's checkout is shallow and may not hold the
    commit, and then only the links' form is held."""
    page = study.view_study("/nowhere/study.json")
    links = re.findall(r"<a href='%s/([\w/]+\.py)#L(\d+)-L(\d+)'>([\w.]+):(\d+)-(\d+)</a>"
                       % re.escape(study.CODE_URL), page)
    assert len(links) >= 30
    for path, start, end, shown, first, last in links:
        assert path.endswith("/" + shown) and (start, end) == (first, last), path
        assert int(start) <= int(end), path
    probe = subprocess.run(["git", "cat-file", "-e", study.PROOF_COMMIT], cwd=ROOT,
                           capture_output=True, check=False)
    if probe.returncode:
        pytest.skip("the proof's commit is not in this clone")
    for path, _, end, *_ in links:
        text = subprocess.run(["git", "show", "%s:%s" % (study.PROOF_COMMIT, path)], cwd=ROOT,
                              capture_output=True, text=True, check=True).stdout
        assert int(end) <= len(text.splitlines()), path


def test_the_report_is_linked_only_at_a_web_address():
    linked = study.report({"report": {"url": "https://example.org/report", "title": "R"}})
    assert "<a href='https://example.org/report' target='_blank' rel='noopener'>R</a>" in linked
    assert "<a " not in study.report({"report": "javascript:alert(1)"})
    assert "names no address for it yet" in study.report({})
    assert "there are none yet" in study.report(None)


def test_a_chart_places_its_values_on_a_round_scale_that_holds_them():
    """The domain holds every finite value and the reference lines on round
    ticks, never more than eight, and never fails; a value sits where the
    scale puts it."""
    assert charts.domain([-17.5, 96.0], 0.0, 100.0) == (-20.0, 100.0, 20.0)
    assert charts.domain([float("inf"), 5.0], 0.0, 100.0) == (0.0, 100.0, 20.0)
    lo, hi, step = charts.domain([1e9], 0.0, 100.0)
    assert (hi - lo) / step <= 8 and hi >= 1e9
    row = charts.DotRow("a six", "g", "f-countrix", (charts.Stat(40.0, 30.0, 50.0), None), "a tip")
    drawn = charts.dots([row], "a heading")
    x = charts.scale(0.0, 100.0, charts.LABEL, charts.PANEL - 14)
    assert "<circle cx='%.1f'" % x(40.0) in drawn and "<title>a tip</title>" in drawn
    assert "<line x1='%.1f'" % x(30.0) in drawn and "x2='%.1f'" % x(50.0) in drawn


def test_a_label_is_placed_beside_its_point_only_where_it_fits():
    box = (0.0, 0.0, 400.0, 300.0)
    apart = charts.placed(
        [(50.0, 50.0, "one"), (300.0, 250.0, "two")], [(50.0, 50.0), (300.0, 250.0)], box)
    assert len(apart) == 2 and ">one<" in apart[0] and ">two<" in apart[1]
    too_long = [(5.0, 5.0, "a label too long for its box")]
    assert charts.placed(too_long, [(5.0, 5.0)], (0.0, 0.0, 20.0, 20.0)) == []


def test_the_funnel_writes_each_stages_median_and_a_dot_a_spot():
    stages = [
        charts.Stage("legal sixes", {"median": 13030920.0}, (13030920.0,) * 360),
        charts.Stage("scored in full", {"median": 10.0}, (9.0, 10.0, 10.0, 11.0)),
        charts.Stage("the answer", {"median": 1.0}, ())]
    drawn = charts.funnel(stages, "the search")
    assert ">13,030,920</text>" in drawn and ">1</text>" in drawn and ">10M</text>" in drawn
    assert drawn.count("class='faint'") == 1 + 3


def test_a_heatmap_row_links_only_an_address_it_has():
    row = charts.HeatRow("a rule", "", ((0.5, 0.1),), ("a tip",))
    linked = row._replace(href="/registry#a-rule")
    column = [charts.HeatColumn("a map", "a mode", False)]
    assert "<a " not in charts.heatmap([row], column, "rules")
    assert "<a href='/registry#a-rule'>" in charts.heatmap([linked], column, "rules")
