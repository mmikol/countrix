"""The study page, /study: ui/study.py's reading of the results file and
ui/charts.py's charts - on the sample the repository ships, the file the
page reads (ui/static/study.json), and on files written here. Every chart
is drawn beside a table of its numbers, every string the file holds is
escaped, the schema is checked, a file missing, unreadable or of another
schema leaves the proof standing and says why, the numbers drawn are the
file's, the code's constants are the code's, and the proof's code links
name lines that exist at its commit. No server and no database."""

import json
import re
import subprocess

import pytest

from db import ROOT
from inference import bounds, scoring, solver
from ui import charts, study

FIGURES = ("shares", "parts", "meta-and-team", "rules-by-map", "search")
EVIL = "<script>alert(1)</script>'\""


def sample():
    with open(study.RESULTS_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def written(tmp_path, data):
    path = tmp_path / "study.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def figure(page, fid):
    start = page.index("<figure class='viz' id='%s'>" % fid)
    return page[start:page.index("</figure>", start)]


def flat(page):
    return " ".join(page.split())


def test_the_results_file_the_page_reads_is_the_schema_it_reads():
    assert sample()["schema"] == study.SCHEMA == "countrix-study/1"
    read = study.read_study()
    assert read.results is not None and read.note == ""


def test_the_sample_draws_every_chart_beside_a_table_of_its_numbers():
    """Each of the five charts is an inline SVG with its accessible name,
    and its numbers sit under its fold in a table, the twin a reader without
    the chart reads; the answer in numbers, the checks, the brute force,
    the rules, the slider, the board-by-board gaps and the other sets are
    tables of their own."""
    page = study.view_study()
    for fid in FIGURES:
        fig = figure(page, fid)
        assert "<svg class='chart" in fig and "role='img' aria-label='" in fig, fid
        numbers = fig[fig.index("<summary>the numbers</summary>"):]
        assert "<table class='numbers'>" in numbers, fid
    assert "<table class='numbers profile'>" in page
    for head in ("<th>the claim</th>", "<th>legal sixes</th>", "<th>moves the six</th>",
                 "<th>the engine&#x27;s part</th>", "<th>the gap</th>", "<th>boards</th>"):
        assert head in page, head
    assert "<script" not in page


def test_a_sample_says_so_above_everything_and_a_measured_file_does_not(tmp_path):
    page = study.view_study()
    assert page.index("<b>A sample.</b>") < page.index("<figure")
    data = sample()
    del data["sample"]
    measured = study.view_study(written(tmp_path, data))
    assert "A sample." not in measured
    assert "The results: generated %s; Countrix at %s" % (
        data["generated"], data["provenance"]["countrix"]["commit"]) in measured


def test_without_a_results_file_the_proof_stands_and_the_study_has_not_been_run(
        tmp_path, monkeypatch):
    """No file: the proof, its count check, the assumptions and the audit
    stand, and every block the results fill says there is nothing yet, under
    the line that the study has not been run."""
    monkeypatch.delenv("COUNTRIX_STRATEGIES", raising=False)
    page = study.view_study(str(tmp_path / "none.json"))
    assert ("<div class='warnbox'>The study has not been run: there is no results file,"
            " none.json.</div>") in page
    assert "<svg" not in page and "<figure" not in page
    assert page.count(study.NONE_YET) == len(study.RESULT_BLOCKS)
    for kept in ("<h3 id='the-theorem'>", "<b>Lemma 1.</b>", "<h2 id='hard-coded'>",
                 "href='/registry#players-play-optimally'"):
        assert kept in page, kept
    # the count check: the shipped playbook's shapes on the proof's roster, the
    # 13,030,920 legal sixes the walk considered on every open board that day
    assert "<b>13,030,920</b>" in page
    assert "The report follows the study's results; there are none yet." in page


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
    for arm in data["arms"].values():
        arm.update(label=EVIL + arm["label"], model=EVIL, sources=[EVIL])
    for metric in data["metrics"]:
        metric["label"] = EVIL
    for rule in data["rules"].values():
        rule["name"] = EVIL
    data["rules"][EVIL] = dict(next(iter(data["rules"].values())))
    data["design"]["maps"][0]["name"] = EVIL
    data["design"]["sets"]["fresh"]["seed"] = EVIL
    data["proof"]["theorems"][0]["statement"] = EVIL
    data["proof"]["brute_force"][0]["board"] = EVIL
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
    assert "Countrix as shipped - CounterWatch&#x27;s yardstick, matchups 37.3 (30.0 to 44.5)" \
        in shares
    assert "37.3 <span class='rng'>(30.0 to 44.5)</span>" in shares
    assert "title='strength, Blizzard: 88.4 (80.0 to 93.0)'>88</td>" in page
    assert "<td>12,345,678</td>" in page


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


def test_the_funnel_writes_each_stages_median():
    stages = [
        charts.Stage("legal sixes", {"median": 13030920.0}, (13030920.0,)),
        charts.Stage("the answer", {"median": 1.0}, ())]
    drawn = charts.funnel(stages, "the search")
    assert ">13,030,920</text>" in drawn and ">1</text>" in drawn and ">10M</text>" in drawn
