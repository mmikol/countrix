"""The study, /study: the proof that the search returns the best team its
objective allows, the audit of what the code fixes and what it reads from
the data, and the study's results - Countrix's teams beside the tools
people use, on the same boards - rendered on every call. The prose is
ui/static/study.html, the code's constants filled in from their modules as
the math page's are; the results are read from the file the benchmark
publishes, ui/static/study.json, in the countrix-study/1 schema (SCHEMA),
and ui/charts.py draws each chart, beside a table of its numbers.

The page computes no result: each number it shows of the study is the
file's. It reads the metrics by their ids, each a percentile among a
board's random sixes, a share of a yardstick or a satisfaction, so a raw
rate a file carried by mistake is never drawn. A file that is missing,
unreadable or of another schema leaves the proof and the audit standing
and says so where the results would be; a file that says it is a sample
(`"sample": true`) says so above everything. Every string read from the
file is escaped. ui/board.py serves the page; nothing here reads the
database.
"""

import json
import math
import os
import re
from collections.abc import Iterator, Mapping, Sequence
from typing import Any, NamedTuple

from facts.draft import MAX_TANKS, TEAM_SIZE
from inference import bounds, catalog, ranges, scale, scoring, solver, strategy
from inference.shapes import legal_shapes
from ui import charts, pages
from ui.charts import Stat
from ui.pages import esc

SCHEMA = "countrix-study/1"
RESULTS_PATH = os.path.join(pages.STATIC_DIR, "study.json")
RESULTS_NAME = "ui/static/study.json"
ARTICLE = "study.html"
# the commit the proof read the code at: its line references link that commit
PROOF_COMMIT = "4eaba4ace71615382a92197e1c0114c596acd0bf"
CODE_URL = "%s/blob/%s" % (pages.REPO_URL, PROOF_COMMIT)
# the roster the proof's count check was taken on, 2026-10-05: its tanks,
# damage and supports, multiplied out over the shapes in force
PROOF_ROSTER = (15, 24, 14)


class Family(NamedTuple):
    """An arm family: its id in the results file, its name in a legend, and
    the class that colours its marks (board.css)."""
    key: str
    name: str
    css: str


# the families in the order the charts list them; one the file names and
# this does not keeps the colour every family's mark starts from
FAMILIES = (
    Family("countrix", "Countrix", "f-countrix"),
    Family("counterwatch", "CounterWatch", "f-counterwatch"),
    Family("oracle", "the yardstick's best", "f-oracle"),
    Family("tier", "tier lists", "f-tier"),
    Family("counter_picker", "counter pickers", "f-counter"),
    Family("meta", "the most picked", "f-meta"),
    Family("random", "random sixes", "f-random"))
EMPHASIS = frozenset({"countrix", "counterwatch"})      # coloured on the scatter, the rest grey
# the groups of arms the main charts leave out: the sweeps have tables of
# their own, and an arm on another capture or another source's rates is
# read under whether the results hold up
APART = frozenset({"generalization", "sweep_mu", "sweep_rule"})
SHIPPED = "cx_full"                                       # the arm that is Countrix as shipped
# the arms whether the results hold up follows on every other set of boards,
# beside each arm of another capture or another source
KEY_ARMS = (SHIPPED, "cw_builder_matchup")
# where an arm reads a tool's numbers: its site, credited and linked
CREDITS = {
    "CounterWatch": "https://counterwatch.gg", "herostats.live": "https://herostats.live",
    "owherostats.com": "https://owherostats.com", "wiki": pages.WIKI_URL}

# the metrics the page reads, by the ids the benchmark writes: a percentile
# among a board's random two-two-two sixes, a share of a yardstick, or a
# satisfaction - never a raw rate
PROFILE = (
    ("pct_pop_bz", "popularity", "Blizzard"), ("pct_str_bz", "strength", "Blizzard"),
    ("pct_pop_cw", "popularity", "CounterWatch"), ("pct_str_cw", "strength", "CounterWatch"),
    ("pct_syn_wiki", "synergy", "wiki"), ("pct_syn_cw", "synergy", "CW duos"),
    ("pct_ctr_wiki", "counters", "wiki"), ("pct_ctr_cw_matchup", "counters", "CW matchups"),
    ("pct_ctr_cw_duel", "counters", "CW duels"))
YARDSTICK = ("y_matchup", "y_rating")          # CounterWatch's yardstick, its two readings
OWN_SCALE = ("cx_rel",)                         # Countrix's scale, anchored as the yardstick is
# the scatter's panels: strength on the meta against the team's edge - the
# mean of its synergy and counter percentiles - on each source's numbers
TEAM_PANELS = (
    ("On Blizzard's rates and the wiki", "pct_str_bz", "team_wiki"),
    ("On CounterWatch's 6v6 numbers", "pct_str_cw", "team_cw"))
RULES_KEPT = "sat_mean"
HEADLINE = (*YARDSTICK, *OWN_SCALE, "pct_str_bz", "team_wiki", RULES_KEPT)
LABELS = {
    "y_matchup": "CounterWatch's yardstick, matchups",
    "y_rating": "CounterWatch's yardstick, duels", "cx_rel": "Countrix's scale",
    "pct_str_bz": "strength, Blizzard", "pct_str_cw": "strength, CounterWatch",
    "team_wiki": "team edge, wiki", "team_cw": "team edge, CounterWatch",
    RULES_KEPT: "rules kept"}

# a score's parts as the stacked bars draw them: Countrix's three terms and
# its rules together, and CounterWatch's three parts in the colour of the
# term each answers to
RULES_PART = "rules"
COUNTRIX_PARTS = (("base.rates", charts.Part("win rates", "p1")),
                  ("base.synergy", charts.Part("synergy", "p2")),
                  ("base.counters", charts.Part("counters", "p3")),
                  (RULES_PART, charts.Part("the playbook's rules", "p4")))
YARDSTICK_PARTS = (("map", charts.Part("map advantage", "p1")),
                   ("composition", charts.Part("composition", "p2")),
                   ("counter", charts.Part("counters", "p3")))
SEARCH_STAGES = (("legal", "considered", "legal sixes"), ("nodes", "nodes", "branches walked"),
                 ("leaves", "leaves", "scored in full"))


# --- the results file ---------------------------------------------------------------------

class Study(NamedTuple):
    """The results file as the page reads it: its contents where it is the
    schema this page reads, else None and the line the page says instead."""
    results: dict[str, Any] | None
    note: str


def read_study(path: str = RESULTS_PATH) -> Study:
    """The results at `path`, or None and why: no file, a file that is not
    JSON or holds no object, or one of another schema."""
    shown = RESULTS_NAME if path == RESULTS_PATH else os.path.basename(path)
    if not os.path.isfile(path):
        return Study(None, "The study has not been run: there is no results file, %s." % shown)
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as error:
        return Study(None, "The results file, %s, cannot be read: %s." % (shown, error))
    if not isinstance(data, dict):
        return Study(None, "The results file, %s, holds no object." % shown)
    if data.get("schema") != SCHEMA:
        return Study(None, "The results file, %s, is of the schema %s; this page reads %s, so it"
                     " shows none of it." % (shown, plain(data.get("schema")) or "none", SCHEMA))
    return Study(data, "")


def get(data: Any, *path: str) -> Any:
    """The value at `path` through nested objects, or None where a step is
    missing or not an object."""
    for key in path:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def number(value: Any) -> float | None:
    """A finite number, or None: a bool, a string, NaN and infinity are none."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    out = float(value)
    return out if math.isfinite(out) else None


def plain(value: Any) -> str:
    """A JSON scalar as text: a string as it stands, a number as written,
    anything else nothing."""
    if isinstance(value, str):
        return value
    out = number(value)
    return "" if out is None else "%g" % out


def stat(value: Any) -> Stat | None:
    """An aggregate {mean, lo, hi} - or a bare number, a mean with no range
    - as a Stat; None where it holds no finite mean."""
    if not isinstance(value, dict):
        mean = number(value)
        return None if mean is None else Stat(mean, None, None)
    mean, lo, hi = number(value.get("mean")), number(value.get("lo")), number(value.get("hi"))
    if mean is None:
        return None
    return Stat(mean, lo, hi) if lo is not None and hi is not None else Stat(mean, None, None)


class Arm(NamedTuple):
    """One arm of the study as the results file lists it."""
    id: str
    label: str
    family: Family
    group: str
    sources: tuple[str, ...]
    model: str


def family(key: str) -> Family:
    """The family by its id; one this page does not know keeps its id as
    its name and no colour of its own."""
    return next((f for f in FAMILIES if f.key == key), Family(key, key.replace("_", " "), ""))


def _keyed(raw: Any) -> list[tuple[str, dict[str, Any]]]:
    """An object by id, or a list of objects with ids, as (id, object)
    pairs in the file's order."""
    pairs = list(raw.items()) if isinstance(raw, dict) else [
        (item.get("id"), item) for item in raw if isinstance(item, dict)
    ] if isinstance(raw, list) else []
    return [(key, item) for key, item in pairs if isinstance(key, str) and isinstance(item, dict)]


def arms(results: Mapping[str, Any]) -> list[Arm]:
    """The file's arms, in its order."""
    out = []
    for key, arm in _keyed(results.get("arms")):
        sources = arm.get("sources")
        out.append(Arm(
            id=key, label=plain(arm.get("label")) or key,
            family=family(plain(arm.get("family")) or "other"), group=plain(arm.get("group")),
            sources=tuple(plain(s) for s in sources) if isinstance(sources, list) else (),
            model=plain(arm.get("model"))))
    return out


class Metric(NamedTuple):
    """One metric as the results file describes it."""
    id: str
    label: str
    family: str
    source: str
    unit: str


def metrics(results: Mapping[str, Any]) -> dict[str, Metric]:
    """The file's metrics by id."""
    return {key: Metric(key, plain(m.get("label")) or LABELS.get(key, key),
                        plain(m.get("family")), plain(m.get("source")), plain(m.get("unit")))
            for key, m in _keyed(results.get("metrics"))}


def label(results: Mapping[str, Any], metric: str) -> str:
    """A metric's name: the file's, else the page's own, else its id."""
    known = metrics(results).get(metric)
    return known.label if known is not None else LABELS.get(metric, metric)


class Where(NamedTuple):
    """Where a chart reads the aggregates: a set of boards and a slice of it."""
    set: str
    slice: str


def primary(results: Mapping[str, Any]) -> Where | None:
    """The primary set - the one design.sets marks, else the first the
    aggregates hold - and its test-half slice, else all its boards, else
    its first."""
    aggregates = results.get("aggregates")
    if not isinstance(aggregates, dict):
        return None
    held = [name for name, value in aggregates.items() if isinstance(value, dict)]
    marked = [name for name, value in _keyed_sets(results) if value.get("primary") is True]
    name = next((n for n in marked if n in held), held[0] if held else None)
    if name is None:
        return None
    slices = [key for key, value in aggregates[name].items() if isinstance(value, dict)]
    chosen = next((s for s in ("test", "all") if s in slices), slices[0] if slices else None)
    return None if chosen is None else Where(name, chosen)


def _keyed_sets(results: Mapping[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    sets = get(results, "design", "sets")
    return [(name, value) for name, value in sets.items() if isinstance(value, dict)
            ] if isinstance(sets, dict) else []


def agg(results: Mapping[str, Any], where: Where, arm: str, metric: str) -> Stat | None:
    """An arm's aggregate of a metric where the chart reads, or None."""
    return stat(get(results, "aggregates", where.set, where.slice, arm, metric))


def shown_arms(results: Mapping[str, Any], where: Where) -> list[Arm]:
    """The arms the main charts show: every arm the slice holds but the
    sweeps and the other sets' arms, by family, then in the file's order."""
    held = get(results, "aggregates", where.set, where.slice)
    rank = {f.key: i for i, f in enumerate(FAMILIES)}
    listed = [
        a for a in arms(results) if a.group not in APART and isinstance(held, dict)
        and isinstance(held.get(a.id), dict)]
    return sorted(listed, key=lambda a: rank.get(a.family.key, len(rank)))


# --- numbers and tables as the page writes them --------------------------------------------

def fmt(value: float | None, places: int = 1) -> str:
    """A number to `places` decimals with a minus sign where it is below 0,
    a dash where there is none."""
    if value is None:
        return "-"
    text = "%.*f" % (places, value)
    if text.startswith("-") and float(text) == 0.0:
        text = text[1:]
    return "&minus;" + text[1:] if text.startswith("-") else text


def count(value: Any) -> str:
    """A count with thousands separators; a fraction to three places; a
    string escaped as it stands."""
    out = number(value)
    if out is None:
        return esc(plain(value)) or "-"
    return format(round(out), ",") if out == round(out) else fmt(out, 3)


def stat_html(s: Stat | None, places: int = 1) -> str:
    """A Stat as a table writes it: the mean, its range in brackets."""
    if s is None:
        return "-"
    if s.lo is None or s.hi is None:
        return fmt(s.mean, places)
    return "%s <span class='rng'>(%s to %s)</span>" % (
        fmt(s.mean, places), fmt(s.lo, places), fmt(s.hi, places))


def stat_words(s: Stat | None) -> str:
    """A Stat in a tooltip's plain text."""
    if s is None:
        return "none"
    if s.lo is None or s.hi is None:
        return "%.1f" % s.mean
    return "%.1f (%.1f to %.1f)" % (s.mean, s.lo, s.hi)


def table(head: Sequence[str], body: Sequence[Sequence[str]]) -> str:
    """A table in a box that scrolls sideways: the head escaped here, each
    cell as given, which its caller has escaped."""
    return ("<div class='wide'><table class='numbers'><tr>%s</tr>%s</table></div>" % (
        "".join("<th>%s</th>" % esc(h) for h in head),
        "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % c for c in row) for row in body)))


def figure(fid: str, title: str, caption: str, chart: str, numbers: str) -> str:
    """A chart in its figure: its title and caption, the chart, and its
    numbers in a table under a fold, the twin every chart keeps."""
    return ("<figure class='viz' id='%s'><figcaption><b>%s</b> %s</figcaption>%s"
            "<details class='numbers'><summary>the numbers</summary>%s</details></figure>"
            % (fid, esc(title), caption, chart, numbers))


def key(entries: Sequence[tuple[str, str, str]]) -> str:
    """A legend: each entry's mark - a dot, a hollow dot or a square - in
    its class's colour, then its name."""
    return "<div class='key'>%s</div>" % "".join(
        "<span class='%s'><i class='%s'></i>%s</span>" % (css, mark, esc(name))
        for css, mark, name in entries)


def missing(what: str) -> str:
    """The line in place of a block the results file holds nothing for."""
    return "<p class='legend'>The results file holds none of %s.</p>" % esc(what)


def where_words(where: Where) -> str:
    """The boards a chart reads, in words."""
    half = {"test": "maps held out of any tuning", "train": "maps the dials were tuned on",
            "all": "maps"}.get(where.slice, "%s slice" % where.slice)
    return "%s boards on the %s" % (esc(where.set), esc(half))


# --- the charts -------------------------------------------------------------------------------

def shares_figure(results: Mapping[str, Any], where: Where) -> str:
    """Where each six lands: on CounterWatch's yardstick, its two readings,
    and on Countrix's scale, each 0 at the average random six and 100 at
    its own best."""
    panels, every = [], []
    for names, heading in ((YARDSTICK, "On CounterWatch's yardstick"),
                           (OWN_SCALE, "On Countrix's scale")):
        rows = []
        for arm in shown_arms(results, where):
            values = tuple(agg(results, where, arm.id, n) for n in names)
            if any(v is not None for v in values):
                tip = "%s - %s" % (arm.label, "; ".join(
                    "%s %s" % (label(results, n), stat_words(v))
                    for n, v in zip(names, values, strict=True)))
                rows.append(charts.DotRow(arm.label, arm.family.key, arm.family.css, values, tip))
        if rows:
            panels.append(charts.dots(rows, heading))
            every += list(names)
    if not panels:
        return missing("the yardstick shares (%s)" % ", ".join((*YARDSTICK, *OWN_SCALE)))
    listed = shown_arms(results, where)
    numbers = table(["arm", *(label(results, n) for n in every)], [
        [esc(a.label), *(stat_html(agg(results, where, a.id, n)) for n in every)]
        for a in listed])
    families = list(dict.fromkeys(a.family for a in listed))
    caption = (
        "Each arm's mean over the %s, with the range it would fall in if the maps were drawn"
        " again. 0 is the average random two-two-two six, 100 the best six that scale knows."
        " %s%s" % (where_words(where), key([("fam %s" % f.css, "dot", f.name) for f in families]),
                   key([("fam", "dot", label(results, YARDSTICK[0])),
                        ("fam", "hollow", label(results, YARDSTICK[1]))])))
    return figure("shares", "Where each six lands", caption,
                  "<div class='panels'>%s</div>" % "".join(panels), numbers)


def parts_of(
        results: Mapping[str, Any], where: Where, arm: str, scale_id: str) -> dict[str, float]:
    """An arm's parts of one score: the file's parts where it holds them,
    else the aggregates' part.* or ypart_<reading>.* metrics."""
    held = get(results, "parts", where.set, where.slice, arm, scale_id)
    out: dict[str, float] = {}
    if isinstance(held, dict):
        for name, value in held.items():
            mean = stat(value)
            if mean is not None:
                out[str(name)] = mean.mean
        return out
    prefix = "part." if scale_id == "countrix" else "ypart_%s." % scale_id.split("_", 1)[-1]
    row = get(results, "aggregates", where.set, where.slice, arm)
    for name, value in row.items() if isinstance(row, dict) else ():
        mean = stat(value)
        if str(name).startswith(prefix) and mean is not None:
            out[str(name)[len(prefix):]] = mean.mean
    return out


def gathered(
        parts: Mapping[str, float], shown: Sequence[tuple[str, charts.Part]]
) -> tuple[float, ...]:
    """The parts in the bars' order, the rules part the sum of every term
    the named parts leave."""
    named = {name for name, _ in shown if name != RULES_PART}
    return tuple(sum(v for k, v in parts.items() if k not in named) if name == RULES_PART
                 else parts.get(name, 0.0) for name, _ in shown)


def parts_figure(results: Mapping[str, Any], where: Where) -> str:
    """What each six is made of: Countrix's score and CounterWatch's
    yardstick split into their parts, each part less its mean over the
    random sixes, so the parts sum to the six's place on that scale."""
    panels, tables = [], []
    for scale_id, shown, heading in (("countrix", COUNTRIX_PARTS, "On Countrix's scale"),
                                     ("cw_matchup", YARDSTICK_PARTS,
                                      "On CounterWatch's yardstick")):
        rows = []
        for arm in shown_arms(results, where):
            parts = parts_of(results, where, arm.id, scale_id)
            if parts and arm.family.key != "random":
                values = gathered(parts, shown)
                tip = "%s - %s; sum %.1f" % (arm.label, ", ".join(
                    "%s %.1f" % (p.label, v) for (_, p), v in zip(shown, values, strict=True)),
                    sum(values))
                rows.append(charts.BarRow(arm.label, arm.family.key, values, tip))
        if not rows:
            continue
        panels.append(charts.bars(rows, [p for _, p in shown], heading))
        tables.append("<p class='legend'>%s</p>%s" % (esc(heading), table(
            ["arm", *(p.label for _, p in shown), "sum"],
            [[esc(r.label), *(fmt(v) for v in r.values), fmt(sum(r.values))] for r in rows])))
    if not panels:
        return missing("the parts of each score (parts, or the part.* metrics)")
    legend = key([(p.css, "sq", "%s, or %s" % (p.label, q.label)) for (_, p), (_, q)
                  in zip(COUNTRIX_PARTS, YARDSTICK_PARTS, strict=False)]
                 + [(COUNTRIX_PARTS[-1][1].css, "sq", COUNTRIX_PARTS[-1][1].label)])
    caption = (
        "Each part less its mean over the random sixes, in points of its scale, on the %s: a"
        " gain stacks right of 0 and a loss left of it, and the tick is their sum, the six's"
        " place. A colour is the same kind of part on both scales - win rates and"
        " CounterWatch's map advantage, synergy and its composition, counters and its"
        " counters; only Countrix has rules. %s" % (where_words(where), legend))
    return figure("parts", "What each six is made of", caption,
                  "<div class='panels'>%s</div>" % "".join(panels), "".join(tables))


def scatter_figure(results: Mapping[str, Any], where: Where) -> str:
    """The meta against the team: how strong each six is on the meta, and
    how much synergy and how many answers it carries, on each source."""
    panels, tables = [], []
    for heading, x_metric, y_metric in TEAM_PANELS:
        points = []
        for arm in shown_arms(results, where):
            sx, sy = agg(results, where, arm.id, x_metric), agg(results, where, arm.id, y_metric)
            if sx is None or sy is None:
                continue
            css = arm.family.css if arm.family.key in EMPHASIS else "f-random"
            tip = "%s - strength %s, team edge %s" % (arm.label, stat_words(sx), stat_words(sy))
            points.append((arm, charts.Point(arm.label, css, sx, sy, tip, arm.id == SHIPPED)))
        if not points:
            continue
        # drawn grey first, then the two coloured families, Countrix as shipped last, on top:
        # its label is placed first
        points.sort(key=lambda p: (p[0].family.key in EMPHASIS, p[0].id == SHIPPED))
        panels.append(charts.scatter([p for _, p in points], heading,
                                     "strength on the meta, percentile", "team edge, percentile"))
        tables.append("<p class='legend'>%s</p>%s" % (esc(heading), table(
            ["arm", label(results, x_metric), label(results, y_metric)],
            [[esc(a.label), stat_html(p.x), stat_html(p.y)] for a, p in points])))
    if not panels:
        return missing("the strength and team-edge percentiles (%s)" % ", ".join(
            m for _, x_metric, y_metric in TEAM_PANELS for m in (x_metric, y_metric)))
    legend = key([("fam f-countrix", "dot", "Countrix"),
                  ("fam f-counterwatch", "dot", "CounterWatch"),
                  ("fam f-random", "dot", "every other arm")])
    caption = (
        "Across, the six's strength on the meta - its heroes' win rates - placed among the"
        " board's random sixes; up, its team edge, the mean of its synergy and its counters"
        " placed the same way. 50 is a random six on either axis, and a six up and to the right"
        " is strong on the meta and carries a team. On the %s. %s" % (where_words(where), legend))
    return figure("meta-and-team", "The meta against the team", caption,
                  "<div class='panels'>%s</div>" % "".join(panels), "".join(tables))


def rules_of(results: Mapping[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """The file's rules, by id, in its order."""
    held = results.get("rules")
    return [(rid, rule) for rid, rule in held.items()
            if isinstance(rule, dict)] if isinstance(held, dict) else []


def map_columns(results: Mapping[str, Any]) -> list[charts.HeatColumn]:
    """The design's maps as the heatmap's columns, by mode then name, a map
    of the held-out half marked."""
    maps = get(results, "design", "maps")
    listed = [
        (plain(m.get("mode")), plain(m.get("name")), plain(m.get("half")) == "test")
        for m in maps if isinstance(m, dict) and plain(m.get("name"))
    ] if isinstance(maps, list) else []
    return [charts.HeatColumn(name, mode, test) for mode, name, test in sorted(listed)]


def share(value: Any) -> str:
    """A {boards, share} as "N boards, P%"."""
    boards, part = number(get(value, "boards")), number(get(value, "share"))
    if part is None:
        return "-"
    return "%s, %s%%" % (count(boards) if boards is not None else "-", fmt(100 * part, 0))


def rules_figure(results: Mapping[str, Any]) -> str:
    """The rules: where each applies and where it changes Countrix's six,
    map by map; then a row a rule - how often it applies and moves the six,
    how well each six keeps it, and what leaving it out does."""
    rules, columns = rules_of(results), map_columns(results)
    if not rules:
        return missing("the rules (rules)")
    out = []
    if columns:
        rows = []
        for rid, rule in rules:
            name = plain(rule.get("name")) or rid
            cells, tips = [], []
            for column in columns:
                applies = number(get(rule, "by_map", column.name, "applies")) or 0.0
                moves = number(get(rule, "by_map", column.name, "moves")) or 0.0
                cells.append((applies, moves))
                tips.append("%s on %s - applies on %.0f%% of its boards; leaving it out changes"
                            " the six on %.0f%%" % (name, column.name, 100 * applies,
                                                   100 * moves))
            rows.append(charts.HeatRow(name, "/registry#%s" % rid, tuple(cells), tuple(tips)))
        caption = ("A row a heuristic and a column a map, grouped by mode; a bar under a map marks"
                   " the half held out of any tuning. A cell's blue is the share of the map's"
                   " boards where the rule applies to Countrix's six, its dot the share where"
                   " leaving the rule out changes the six. A rule's name opens its entry on the"
                   " registry. %s" % key([("", "sq cellkey", "applies"),
                                          ("", "movedkey", "moves the six"),
                                          ("", "testkey", "a held-out map")]))
        numbers = table(["rule", *(c.name for c in columns)], [
            [esc(row.label), *(fmt(100 * applies, 0) for applies, _ in row.cells)]
            for row in rows])
        out.append(figure("rules-by-map", "The rules, map by map", caption,
                          "<div class='wide'>%s</div>" % charts.heatmap(
                              rows, columns, "the rules, map by map"),
                          "<p class='legend'>the share of each map's boards where the rule"
                          " applies, in percent</p>" + numbers))
    kept_by = list(dict.fromkeys(a for _, r in rules for a in (
        r["satisfaction"] if isinstance(r.get("satisfaction"), dict) else {})))
    without = list(dict.fromkeys(m for _, r in rules for m in (
        r["without"] if isinstance(r.get("without"), dict) else {})))
    names = {a.id: a.label for a in arms(results)}
    head = ["rule", "form", "weight", "applies", "moves the six",
            *("kept by %s" % names.get(a, a) for a in kept_by),
            *("left out: %s" % label(results, m) for m in without)]
    body = []
    for rid, r in rules:
        body.append([
            "<a href='/registry#%s'>%s</a>" % (esc(rid), esc(plain(r.get("name")) or rid)),
            esc(plain(r.get("form"))), fmt(number(r.get("weight")), 2),
            share(r.get("applies")), share(r.get("moves")),
            *(fmt(number(get(r, "satisfaction", a)), 2) for a in kept_by),
            *(stat_html(stat(get(r, "without", m))) for m in without)])
    out.append(table(head, body))
    return "".join(out)


def quantiles(value: Any) -> dict[str, float]:
    """A {min, p10, median, p90, max}'s finite numbers."""
    return {name: q for name, q in ((n, number(v)) for n, v in value.items())
            if q is not None} if isinstance(value, dict) else {}


def search_figure(results: Mapping[str, Any]) -> str:
    """The search's work on the study's boards: each stage's quantiles from
    the file, and each board of its rows a faint dot."""
    search = get(results, "proof", "search")
    if not isinstance(search, dict):
        return missing("the search's counts (proof.search)")
    rows = results.get("rows")
    boards = [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
    stages = []
    for name, per_board, words in SEARCH_STAGES:
        q = quantiles(search.get(name))
        if "median" in q:
            each = tuple(v for v in (number(get(b, "search", per_board)) for b in boards)
                         if v is not None)
            stages.append(charts.Stage(words, q, each))
    if not stages:
        return missing("the search's counts (proof.search)")
    stages.append(charts.Stage("the answer", {"median": 1.0}, ()))
    numbers = table(["stage", "min", "p10", "median", "p90", "max"], [
        [esc(words), *(count(get(search, name, q)) for q in ("min", "p10", "median", "p90", "max"))]
        for name, words in (*((n, w) for n, _, w in SEARCH_STAGES), ("seconds", "seconds"))
        if isinstance(search.get(name), dict)])
    facts = []
    if number(search.get("refused")) is not None:
        facts.append(" Searches refused past their budget: %s." % count(search.get("refused")))
    if number(search.get("unique_optimum")) is not None:
        facts.append(" Boards whose optimum no other six ties: %s."
                     % count(search.get("unique_optimum")))
    caption = (
        "A log scale: each bar is the median board, its whisker the middle eight boards in ten,"
        " and each faint dot a board of the file's rows. Every six the search does not score"
        " sits in a branch whose bound proves it cannot place.%s" % "".join(facts))
    return figure("search", "What the search walks and scores", caption,
                  charts.funnel(stages, "One search, stage by stage"), numbers)


# --- the tables -------------------------------------------------------------------------------

def checks_table(results: Mapping[str, Any]) -> str:
    """Each claim the study checks, how, on how many cases, and how many
    broke it."""
    theorems = get(results, "proof", "theorems")
    rows = [t for t in theorems if isinstance(t, dict)] if isinstance(theorems, list) else []
    if not rows:
        return missing("the theorems' checks (proof.theorems)")
    return table(["", "the claim", "checked by", "boards", "cases", "violations"], [[
        esc(plain(t.get("id"))), esc(plain(t.get("statement"))),
        esc(plain(get(t, "checked", "method"))), count(get(t, "checked", "boards")),
        count(get(t, "checked", "cases")), count(get(t, "checked", "violations"))]
        for t in rows])


def brute_table(results: Mapping[str, Any]) -> str:
    """The brute force: each board, its legal sixes, whether the search's
    best sixes matched it bit for bit, its time and the commit."""
    runs = get(results, "proof", "brute_force")
    rows = [r for r in runs if isinstance(r, dict)] if isinstance(runs, list) else []
    if not rows:
        return missing("the brute force (proof.brute_force)")
    matched = {True: "yes", False: "no"}
    return table(["board", "legal sixes", "matched", "seconds", "commit"], [[
        esc(plain(r.get("board"))), count(r.get("legal")),
        matched[r["matched"]] if isinstance(r.get("matched"), bool) else "-",
        count(r.get("seconds")), esc(plain(r.get("commit")))] for r in rows])


def source_link(name: str) -> str:
    """A source an arm reads, linked where it is a tool's site."""
    url = CREDITS.get(name)
    if url is None:
        return esc(name)
    return "<a href='%s' target='_blank' rel='noopener'>%s</a>" % (esc(url), esc(name))


def design_tables(results: Mapping[str, Any]) -> str:
    """The method as the file records it: the sets of boards, the arms
    with their families, sources and models, and the metrics."""
    out = []
    sets = _keyed_sets(results)
    if sets:
        out.append("<p class='legend'>the sets of boards</p>" + table(
            ["set", "boards", "primary", "seed"], [[
                esc(name), count(s.get("boards")), "yes" if s.get("primary") is True else "",
                esc(plain(s.get("seed")))] for name, s in sets]))
    listed = arms(results)
    if listed:
        out.append("<p class='legend'>the arms</p>" + table(
            ["family", "arm", "reads", "its model"], [[
                esc(a.family.name), esc(a.label), ", ".join(source_link(s) for s in a.sources),
                esc(a.model)] for a in listed]))
    known = metrics(results)
    if known:
        out.append("<p class='legend'>the metrics</p>" + table(
            ["metric", "family", "source", "unit"],
            [[esc(m.label), esc(m.family), esc(m.source), esc(m.unit)] for m in known.values()]))
    return "".join(out) or missing("the design (design, arms, metrics)")


def profile_table(results: Mapping[str, Any], where: Where) -> str:
    """The answer in numbers: each arm's place among the random sixes on
    the meta - popularity and strength - and on the team - synergy and
    counters - on each source, blue above a random six's 50 and red below,
    and the share of the playbook's rules it keeps."""
    listed = shown_arms(results, where)
    present = [m for m in PROFILE if any(agg(results, where, a.id, m[0]) is not None
                                         for a in listed)]
    if not present:
        return missing("the percentiles (pct_*)")
    body = []
    for arm in listed:
        cells = []
        for metric, _, _ in present:
            s = agg(results, where, arm.id, metric)
            if s is None:
                cells.append("<td class='v'>-</td>")
                continue
            lean = max(-1.0, min(1.0, (s.mean - 50.0) / 50.0))
            colour = (57, 135, 229) if lean >= 0 else (230, 103, 103)
            cells.append("<td class='v' style='background:rgba(%d,%d,%d,%.2f)' title='%s'>%s</td>"
                         % (*colour, 0.7 * abs(lean), esc("%s: %s" % (
                             label(results, metric), stat_words(s))), fmt(s.mean, 0)))
        kept = agg(results, where, arm.id, RULES_KEPT)
        body.append("<tr><td>%s</td>%s<td class='v'>%s</td></tr>" % (
            esc(arm.label), "".join(cells), fmt(None if kept is None else kept.mean, 2)))
    head = "<tr><th>arm</th>%s<th>rules<br>kept</th></tr>" % "".join(
        "<th>%s<br>%s</th>" % (esc(kind), esc(source)) for _, kind, source in present)
    return ("<div class='wide'><table class='numbers profile'>%s%s</table></div>"
            "<p class='legend'>Each six's place among the board's random two-two-two sixes, in"
            " percent, averaged over the %s: 50 is a random six, 100 beats every one. Rules kept"
            " is the mean satisfaction of the playbook's heuristics, 0 to 1.</p>"
            % (head, "".join(body), where_words(where)))


def slider_table(results: Mapping[str, Any]) -> str:
    """The Meta slider: each setting's six, scored on the shipped
    objective - its engine part and its playbook part - with its yardstick
    shares and the rules it keeps; and how many steps broke the trade."""
    per_mu = get(results, "slider", "per_mu")
    rows = [r for r in per_mu if isinstance(r, dict)] if isinstance(per_mu, list) else []
    if not rows:
        return missing("the Meta slider's steps (slider.per_mu)")
    words = {
        "engine_part": "the engine's part", "playbook_part": "the playbook's part",
        "shape_222": "two of each role"}
    names = [n for n in ("engine_part", "playbook_part", "y_matchup", "y_rating", RULES_KEPT,
                         "pct_str_bz", "shape_222") if any(number(r.get(n)) is not None
                                                           for r in rows)]
    out = table(["meta", *(words.get(n) or label(results, n) for n in names)],
                [[fmt(number(r.get("mu")), 2), *(fmt(number(r.get(n)), 2) for n in names)]
                 for r in rows])
    broke = get(results, "slider", "violations")
    if number(broke) is not None:
        out += "<p class='legend'>%s steps checked; %s went against the trade.</p>" % (
            count(get(results, "slider", "steps")), count(broke))
    return out


def paired_table(results: Mapping[str, Any], where: Where) -> str:
    """Countrix as shipped against each arm, board by board on the same
    boards: the mean gap and its range, and its wins, ties and losses."""
    paired = results.get("paired")
    rows = [p for p in paired if isinstance(p, dict) and p.get("set") == where.set
            and p.get("slice") == where.slice] if isinstance(paired, list) else []
    if not rows:
        return missing("the board-by-board gaps (paired)")
    names = {a.id: a.label for a in arms(results)}
    return table(["against", "on", "the gap", "wins", "ties", "losses"], [[
        esc(names.get(plain(p.get("b")), plain(p.get("b")))),
        esc(label(results, plain(p.get("metric")))), stat_html(stat(p.get("gap"))),
        count(p.get("wins")), count(p.get("ties")), count(p.get("losses"))] for p in rows])


def holds_table(results: Mapping[str, Any], where: Where) -> str:
    """Whether the results hold up: on every other set and slice the file
    holds - the other half of the maps, the earlier boards, the bans, the
    older capture, CounterWatch's rates fed to the engine - the key arms'
    and each such run's headline numbers."""
    aggregates = results.get("aggregates")
    listed = {a.id: a for a in arms(results)}
    body = []
    for set_name, slices in aggregates.items() if isinstance(aggregates, dict) else ():
        for slice_name, held in slices.items() if isinstance(slices, dict) else ():
            if Where(set_name, slice_name) == where or not isinstance(held, dict):
                continue
            for arm_id, values in held.items():
                arm = listed.get(arm_id)
                followed = arm_id in KEY_ARMS or (arm is not None and arm.group == "generalization")
                stats = [stat(get(values, m)) for m in HEADLINE]
                if followed and any(s is not None for s in stats):
                    body.append(["%s, %s" % (esc(set_name), esc(slice_name)),
                                 esc(arm.label if arm is not None else arm_id),
                                 *(stat_html(s) for s in stats)])
    if not body:
        return missing("another set of boards")
    return table(["boards", "arm", *(label(results, m) for m in HEADLINE)], body)


def leaves(value: Any, prefix: str = "") -> Iterator[tuple[str, str]]:
    """A nested object's leaves as (dotted path, escaped text)."""
    if isinstance(value, dict):
        for name, inner in value.items():
            yield from leaves(inner, "%s.%s" % (prefix, name) if prefix else str(name))
    elif isinstance(value, list):
        yield prefix, esc(", ".join(plain(v) for v in value if plain(v)))
    elif isinstance(value, bool):
        yield prefix, "yes" if value else "no"
    else:
        yield prefix, esc(plain(value))


def provenance_table(results: Mapping[str, Any]) -> str:
    """Where the results come from - the commits, the data and its dates -
    and what the file says of the generalization runs and of the heroes
    each arm used, a row a field."""
    rows = [[esc(path), text] for name in ("provenance", "generalization", "usage")
            for path, text in leaves(results.get(name), name) if text]
    return table(["field", "value"], rows) if rows else missing("the provenance (provenance)")


# --- the page ---------------------------------------------------------------------------------

NONE_YET = ("<p class='legend'>Nothing yet: the study's results file is not in place - see the top"
            " of the page.</p>")
RESULT_BLOCKS = ("PROFILE", "CHECKS", "BRUTE", "SEARCH", "DESIGN", "SHARES", "PARTS", "SCATTER",
                 "RULES", "SLIDER", "PAIRED", "HOLDS", "PROVENANCE")


def status(study: Study) -> str:
    """What the page reads: why there are no results, or the file's
    vintage, under a sample's warning where the file is one."""
    results = study.results
    if results is None:
        return "<div class='warnbox'>%s</div>" % esc(study.note)
    named = (
        ("generated", ("generated",)), ("Countrix at", ("provenance", "countrix", "commit")),
        ("the benchmark at", ("provenance", "benchmark", "commit")))
    vintage = [
        "%s %s" % (words, esc(plain(get(results, *path)))) for words, path in named
        if plain(get(results, *path))]
    line = "<p class='legend'>The results: %s.</p>" % "; ".join(vintage) if vintage else ""
    if results.get("sample") is True:
        return ("<div class='warnbox'><b>A sample.</b> The numbers in this page's results were"
                " written to build the page, not measured: no board was solved for them. The"
                " study's own results file replaces them.</div>" + line)
    return line


def report(results: Mapping[str, Any] | None) -> str:
    """The report's link, where the file names its address - a web
    address, nothing else."""
    held = None if results is None else results.get("report")
    url = held if isinstance(held, str) else plain(get(held, "url"))
    title = plain(get(held, "title")) or "the report"
    if url and re.match(r"https?://", url):
        return ("<p>The report sets out these results with every figure, its method and how to"
                " run the study again: <a href='%s' target='_blank' rel='noopener'>%s</a>.</p>"
                % (esc(url), esc(title)))
    if results is None:
        return "<p class='legend'>The report follows the study's results; there are none yet.</p>"
    return ("<p class='legend'>The report renders this same results file; the file names no"
            " address for it yet.</p>")


def assumptions_table() -> str:
    """The playbook's assumptions, each linked to its registry entry, with
    the first sentence of its prose."""
    rows = []
    for s in catalog.load():
        if s.kind == "assumption":
            prose = " ".join(catalog.without_title(s.body).split())
            first = re.split(r"(?<=[.!?])\s", prose, maxsplit=1)[0] if prose else ""
            rows.append(["<a href='/registry#%s'>%s</a>" % (esc(s.id), esc(s.name)), esc(first)])
    return table(["assumption", "what it says"], rows) if rows else ""


def shapes_table() -> str:
    """The count check: the sixes of each shape the playbook in force
    allows, on the roster the proof was checked on, and their sum."""
    tanks, damage, supports = PROOF_ROSTER
    rows, total = [], 0
    for shape in legal_shapes(catalog.load()):
        sixes = (math.comb(tanks, shape.tanks) * math.comb(damage, shape.damage)
                 * math.comb(supports, shape.supports))
        total += sixes
        rows.append(["%d-%d-%d" % (shape.tanks, shape.damage, shape.supports),
                     format(sixes, ",")])
    rows.append(["<b>every legal six</b>", "<b>%s</b>" % format(total, ",")])
    return table(["shape: tanks-damage-supports", "sixes"], rows)


def constants() -> dict[str, str]:
    """The code's numbers the article quotes, from the modules that hold
    them, as text."""
    return {
        "CODE": CODE_URL, "REPO": pages.REPO_URL, "COMMIT": PROOF_COMMIT[:7],
        "TEAM_SIZE": str(TEAM_SIZE),
        "MAX_TANKS": str(MAX_TANKS), "NODE_BUDGET": format(solver.NODE_BUDGET, ","),
        "SCORE_BUDGET": format(solver.SCORE_BUDGET, ","), "RANK_CAP": str(solver.RANK_CAP),
        "TIE_BUDGET": format(solver.TIE_BUDGET, ","), "FOLD_COUNTS": str(bounds.FOLD_COUNTS),
        "MEMO_CAP": format(bounds.MEMO_CAP, ","), "SLACK": "%g" % ranges.SLACK,
        "SCORE_PLACES": str(scoring.SCORE_PLACES), "NEED_BUDGET": "%g" % scoring.NEED_BUDGET,
        "DRAW_BITS": str(8 * scoring.DRAW_BYTES),
        "REFERENCE_SIZE": format(scale.REFERENCE_SIZE, ","),
        "SCALE_POOL": str(scale.SCALE_POOL), "WEIGHT_MAX": "%g" % strategy.WEIGHT_RANGE[1],
        "TANKS": str(PROOF_ROSTER[0]), "DAMAGE": str(PROOF_ROSTER[1]),
        "SUPPORTS": str(PROOF_ROSTER[2])}


def blocks(study: Study) -> dict[str, str]:
    """Each block of the article: the ones the results fill, NONE_YET each
    where there are none, and the ones that need none."""
    results = study.results
    out = {
        "STATUS": status(study), "REPORT": report(results), "SHAPES": shapes_table(),
        "ASSUMPTIONS": assumptions_table()}
    where = None if results is None else primary(results)
    if results is None or where is None:
        out.update(dict.fromkeys(RESULT_BLOCKS, NONE_YET if results is None
                                 else missing("the aggregates (aggregates)")))
        return out
    out.update({
        "PROFILE": profile_table(results, where), "CHECKS": checks_table(results),
        "BRUTE": brute_table(results), "SEARCH": search_figure(results),
        "DESIGN": design_tables(results), "SHARES": shares_figure(results, where),
        "PARTS": parts_figure(results, where), "SCATTER": scatter_figure(results, where),
        "RULES": rules_figure(results), "SLIDER": slider_table(results),
        "PAIRED": paired_table(results, where), "HOLDS": holds_table(results, where),
        "PROVENANCE": provenance_table(results)})
    return out


def article(study: Study) -> str:
    """The study's article: ui/static/study.html with the code's constants
    and the blocks filled in. A literal percent in study.html is written %%."""
    with open(os.path.join(pages.STATIC_DIR, ARTICLE), encoding="utf-8") as handle:
        template = handle.read()
    return template % {**constants(), **blocks(study)}


def view_study(path: str = RESULTS_PATH) -> str:
    """The study page: its article in the page shell, the results file read
    on every call."""
    return pages.page("the study", article(read_study(path)))
