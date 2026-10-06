"""The study, /study: the proof that the search returns the best team its
objective allows, the audit of what the code fixes and what it reads from
the data, and the study's results - Countrix's teams beside the tools
people use, on the same boards - rendered on every call. The prose is
ui/static/study.html, the code's constants filled in from their modules as
the math page's are; the results are read from the file the benchmark's
harness writes, in the countrix-study/1 schema (SCHEMA), once it is in
place at ui/static/study.json, and ui/charts.py draws each chart, beside a
table of its numbers.

The page computes no result: each number it shows of the study is the
file's. It reads the metrics by their ids, each a percentile among a
board's random sixes, a share of a yardstick or a satisfaction, so a raw
rate a file carried by mistake is never drawn, and it reads each part of
the file in the shape the harness writes it (tests/fixtures/study.json
keeps those shapes). A file that is missing, unreadable or of another
schema leaves the proof and the audit standing and says so where the
results would be; a file that says it is a sample (`"sample": true`), or
was measured under another playbook or other engine weights than the
board runs, says so above everything. The count check and the
assumptions are the shipped playbook's, the one the proof and the study
read. Every string read from the file is escaped. ui/board.py serves the
page; nothing here reads the database.
"""

import json
import math
import os
import re
from collections.abc import Iterator, Mapping, Sequence
from typing import Any, NamedTuple

from facts.draft import MAX_TANKS, TEAM_SIZE
from inference import base, bounds, catalog, ranges, scale, scoring, solver, strategy
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
# the families whose sixes are the meta - the most picked and the tier lists -
# that the heroes-shared table holds every other six against
META_FAMILIES = frozenset({"meta", "tier"})
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
OWN_KEPT = "own_satisfaction"               # a rule's own satisfaction, in its `without`
HEADLINE = (*YARDSTICK, *OWN_SCALE, "pct_str_bz", "team_wiki", RULES_KEPT)
PAIRED = (*YARDSTICK, *OWN_SCALE)           # the gaps the board-by-board table gives
# the Meta slider's columns: the engine's and the playbook's parts, then the
# aggregates each step's six holds
SLIDER = ("engine_part", "playbook_part", *YARDSTICK, RULES_KEPT, "pct_str_bz", "is_222")
LABELS = {
    "y_matchup": "CounterWatch's yardstick, matchups",
    "y_rating": "CounterWatch's yardstick, duels", "cx_rel": "Countrix's scale",
    "pct_str_bz": "strength, Blizzard", "pct_str_cw": "strength, CounterWatch",
    "team_wiki": "team edge, wiki", "team_cw": "team edge, CounterWatch",
    RULES_KEPT: "rules kept", OWN_KEPT: "the rule's own satisfaction",
    "is_222": "two of each role", "engine_part": "the engine's part",
    "playbook_part": "the playbook's part"}
FRACTION = "0-1"                            # the unit of a metric that runs from 0 to 1

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
SEARCH_STAGES = (("legal", "legal sixes"), ("nodes", "branches walked"),
                 ("leaves", "scored in full"))
SEARCH_SECONDS = ("seconds", "seconds, the whole solve")
# a row's search, as the file's legend.rows gives it: legal sixes, branches
# walked, sixes scored in full, seconds, sixes tied
ROW_SEARCH = ("legal", "nodes", "leaves", "seconds", "tied")
QUANTILES = ("min", "p10", "median", "p90", "max")


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
        return Study(None, "The study's results are not in place: there is no results file,"
                     " %s." % shown)
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


def places(results: Mapping[str, Any], metric: str, extra: int = 0) -> int:
    """The decimals a metric is written to: two for one that runs from 0
    to 1, a satisfaction or a share of boards, one for a percentile or a
    share of a scale; `extra` more for a small gap."""
    known = metrics(results).get(metric)
    fraction = metric == OWN_KEPT or (known is not None and known.unit == FRACTION)
    return (2 if fraction else 1) + extra


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


def seconds(value: Any) -> str:
    """A time in seconds: to a tenth from 1 s up, to a thousandth below."""
    out = number(value)
    return "-" if out is None else fmt(out, 1 if abs(out) >= 1 else 3)


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
    half = {"test": "test-half maps", "train": "train-half maps",
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
    """An arm's parts of one score, as the file's parts[set][slice][arm]
    holds them: each part's mean, by name; none where the file holds
    none."""
    held = get(results, "parts", where.set, where.slice, arm, scale_id)
    out: dict[str, float] = {}
    for name, value in held.items() if isinstance(held, dict) else ():
        mean = stat(value)
        if mean is not None:
            out[str(name)] = mean.mean
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
        return missing("the parts of each score (parts)")
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
        " is strong on both. On the %s. %s" % (where_words(where), legend))
    return figure("meta-and-team", "The meta against the team", caption,
                  "<div class='panels'>%s</div>" % "".join(panels), "".join(tables))


def agreement_table(results: Mapping[str, Any], where: Where) -> str:
    """How close each six comes to the meta, hero by hero: the heroes it
    has in common with each six of the meta - the most picked and the tier
    lists - on average over every board of the primary set, beside how many
    the meta's own sixes have in common. The file keys a pair "a|b"."""
    held = results.get("meta_agreement")
    pairs: dict[frozenset[str], float] = {}
    for name, value in held.items() if isinstance(held, dict) else ():
        ends, shared = frozenset(str(name).split("|")), number(value)
        if len(ends) == 2 and shared is not None:
            pairs[ends] = shared
    named = [a for a in arms(results) if any(a.id in pair for pair in pairs)]
    meta = [a for a in named if a.family.key in META_FAMILIES]
    if not meta:
        return missing("the heroes shared (meta_agreement)")
    rank = {f.key: i for i, f in enumerate(FAMILIES)}
    others = sorted((a for a in named if a.family.key not in META_FAMILIES),
                    key=lambda a: (a.id != SHIPPED, rank.get(a.family.key, len(rank))))
    out = table(["the meta's six", *(a.label for a in others)], [
        [esc(m.label), *(fmt(pairs.get(frozenset((m.id, a.id))), 1) for a in others)]
        for m in meta]) if others else ""
    among = sorted(v for pair, v in pairs.items() if pair <= {a.id for a in meta})
    if not out and not among:
        return missing("the heroes shared (meta_agreement)")
    alike = "" if not among else " The meta's own sixes have %s heroes in common." % (
        fmt(among[0], 1) if len(among) == 1 else "%s to %s" % (
            fmt(among[0], 1), fmt(among[-1], 1)))
    return out + ("<p class='legend'>Heroes shared, of six, averaged over every %s board, both"
                  " halves of the maps.%s</p>" % (esc(where.set), alike))


def rules_of(results: Mapping[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """The file's rules, by id, in its order."""
    held = results.get("rules")
    return [(rid, rule) for rid, rule in held.items()
            if isinstance(rule, dict)] if isinstance(held, dict) else []


def map_columns(results: Mapping[str, Any]) -> list[charts.HeatColumn]:
    """The design's maps as the heatmap's columns, by mode then name, a map
    of the test half marked."""
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


def entry(rid: str, name: str, linked: frozenset[str]) -> str:
    """A rule's name, linked to its registry entry where the playbook in
    force holds the rule - the registry lists that playbook's alone."""
    if rid not in linked:
        return esc(name)
    return "<a href='/registry#%s'>%s</a>" % (esc(rid), esc(name))


def rules_figure(results: Mapping[str, Any], linked: frozenset[str]) -> str:
    """The rules: where each applies and where it changes Countrix's six,
    map by map; then a row a rule - how often it applies and moves the six,
    how well each six keeps it, its mean satisfaction, and what leaving it
    out does, Countrix as shipped less the six without the rule."""
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
            rows.append(charts.HeatRow(name, "/registry#%s" % rid if rid in linked else "",
                                       tuple(cells), tuple(tips)))
        caption = ("A row a heuristic and a column a map, grouped by mode; a bar under a map marks"
                   " the test half. A cell's blue is the share of the map's boards where the rule"
                   " applies to Countrix's six, its dot the share where leaving the rule out"
                   " changes the six. A rule's name opens its entry on the registry where the"
                   " playbook in force holds it. %s" % key([
                       ("", "sq cellkey", "applies"), ("", "movedkey", "moves the six"),
                       ("", "testkey", "a test-half map")]))
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
            entry(rid, plain(r.get("name")) or rid, linked),
            esc(plain(r.get("form"))), fmt(number(r.get("weight")), 2),
            share(r.get("applies")), share(r.get("moves")),
            *(stat_html(stat(get(r, "satisfaction", a)), 2) for a in kept_by),
            *(stat_html(stat(get(r, "without", m)), places(results, m, 1)) for m in without)])
    out.append(table(head, body) + (
        "<p class='legend'>Kept by: each six's mean satisfaction of the rule, 0 to 1. Left out:"
        " Countrix as shipped less the six it picks with the rule's weight at 0, board by board,"
        " with its range; a gain the rule brings is above 0.</p>" if kept_by or without else ""))
    return "".join(out)


def quantiles(value: Any) -> dict[str, float]:
    """A {min, p10, median, p90, max}'s finite numbers."""
    return {name: q for name, q in ((n, number(v)) for n, v in value.items())
            if q is not None} if isinstance(value, dict) else {}


def row_search(row: Mapping[str, Any], name: str) -> float | None:
    """A board row's count of one stage of its search, read from the list
    the row holds in ROW_SEARCH's order."""
    held = row.get("search")
    at = ROW_SEARCH.index(name)
    return number(held[at]) if isinstance(held, list) and len(held) > at else None


def open_line(results: Mapping[str, Any]) -> str:
    """The open boards' search in a sentence - every map and side with
    nothing picked, revealed or banned: the branches it walked and the
    sixes it scored in full, least to most with the median, and the search's
    own time once the scale was set; nothing where the file holds none."""
    held = get(results, "proof", "open_summary")
    boards = number(get(held, "boards"))
    walked, scored, timed = (quantiles(get(held, name))
                             for name in ("nodes", "leaves", "search_seconds"))
    spread = ("min", "max", "median")
    if boards is None or not all(set(spread) <= set(q) for q in (walked, scored)):
        return ""
    timing = ", in %s to %s s of search once the scale was set" % (
        seconds(timed["min"]), seconds(timed["max"])) if {"min", "max"} <= set(timed) else ""
    return (" On the %s open boards - every map and side, nothing picked, revealed or banned -"
            " the search walked %s to %s branches (median %s) and scored %s to %s sixes in full"
            " (median %s)%s." % (count(boards), *(count(walked[q]) for q in spread),
                                 *(count(scored[q]) for q in spread), timing))


def search_figure(results: Mapping[str, Any], where: Where) -> str:
    """The search's work on the study's boards: each stage's quantiles from
    the file, and under each bar the boards of the file's rows on the
    primary set, a faint dot each."""
    search = get(results, "proof", "search")
    if not isinstance(search, dict):
        return missing("the search's counts (proof.search)")
    rows = results.get("rows")
    rows = rows if isinstance(rows, list) else []
    boards = [r for r in rows if isinstance(r, dict) and r.get("set") == where.set]
    stages = []
    for name, words in SEARCH_STAGES:
        q = quantiles(search.get(name))
        if "median" in q:
            each = tuple(v for v in (row_search(b, name) for b in boards) if v is not None)
            stages.append(charts.Stage(words, q, each))
    if not stages:
        return missing("the search's counts (proof.search)")
    stages.append(charts.Stage("the answer", {"median": 1.0}, ()))
    body = [[esc(words), *(count(get(search, name, q)) for q in QUANTILES)]
            for name, words in SEARCH_STAGES if isinstance(search.get(name), dict)]
    name, words = SEARCH_SECONDS
    if isinstance(search.get(name), dict):
        body.append([esc(words), *(seconds(get(search, name, q)) for q in QUANTILES)])
    facts = []
    solved = number(search.get("boards"))
    if solved is not None:
        facts.append(" Each count is one board's search, %s boards in all." % count(solved))
    refused = number(search.get("refused"))
    if refused is not None:
        every = number(search.get("solves"))
        facts.append(" Searches refused past their budget: %s%s." % (
            count(refused), "" if every is None else " of the study's %s" % count(every)))
    unique = number(search.get("unique_optimum"))
    if unique is not None:
        facts.append(" The optimum ties no other six on %s%% of the boards%s." % (
            fmt(100 * unique, 0), "" if solved is None else ", %s of %s" % (
                count(round(unique * solved)), count(solved))))
    facts.append(open_line(results))
    caption = (
        "A log scale: each bar is the median board, its whisker the middle eight boards in ten,"
        " and the faint dots under it the boards. Every six the search does not score sits in"
        " a branch whose bound proves it cannot place; the seconds are the whole solve, its"
        " scale and its facts included.%s" % "".join(facts))
    return figure("search", "What the search walks and scores", caption,
                  charts.funnel(stages, "One search, stage by stage"),
                  table(["stage", *QUANTILES], body))


# --- the tables -------------------------------------------------------------------------------

def violations(check: Mapping[str, Any]) -> str:
    """A check's violations: a count, or, where the file holds none for a
    claim that is measured rather than checked, the word."""
    if "violations" in check and check["violations"] is None:
        return "measured"
    return count(check.get("violations"))


def checks_table(results: Mapping[str, Any]) -> str:
    """Each claim the study checks, each way it checks it - a theorem's
    `checked` lists them - on how many boards and cases, and how many broke
    it; then what filling slot by slot costs, the claim that is measured."""
    theorems = get(results, "proof", "theorems")
    rows = [t for t in theorems if isinstance(t, dict)] if isinstance(theorems, list) else []
    if not rows:
        return missing("the theorems' checks (proof.theorems)")
    body = []
    for t in rows:
        held = t.get("checked")
        ways = [c for c in held if isinstance(c, dict)] if isinstance(held, list) else []
        for i, check in enumerate(ways or [{}]):
            skipped = number(check.get("skipped"))
            why = plain(check.get("skipped_why"))
            method = plain(check.get("method")) + (
                "; %s skipped: %s" % (format(round(skipped), ","), why) if skipped else "")
            body.append([
                esc(plain(t.get("id"))) if i == 0 else "",
                esc(plain(t.get("statement"))) if i == 0 else "", esc(method) or "-",
                count(check.get("boards")), count(check.get("cases")), violations(check)])
    return table(["", "the claim", "checked by", "boards", "cases", "violations"],
                 body) + greedy_line(results)


def greedy_line(results: Mapping[str, Any]) -> str:
    """The measured claim's numbers: how far short of the exact six a fill
    slot by slot lands on Countrix's own objective, and how often it lands
    on the same six."""
    greedy = get(results, "proof", "greedy", "countrix")
    mean, worst = number(get(greedy, "mean")), number(get(greedy, "gap", "max"))
    if mean is None:
        return ""
    same, boards = number(get(greedy, "same")), number(get(greedy, "boards"))
    return ("<p class='legend'>Filled slot by slot, Countrix's own objective lands %s %s short of"
            " the exact six on average%s%s.</p>" % (
                fmt(mean, 2), esc(plain(get(greedy, "unit")) or "points"),
                "" if worst is None else ", %s at worst" % fmt(worst, 2),
                "" if same is None or boards is None else ", and on the same six on %s of %s"
                " boards" % (count(same), count(boards))))


def commit_text(value: Any) -> str:
    """A commit as a table writes it: a hash shortened to seven, anything
    else escaped as it stands."""
    text = plain(value)
    return text[:7] if re.fullmatch(r"[0-9a-f]{7,40}", text) else esc(text) or "-"


def brute_table(results: Mapping[str, Any]) -> str:
    """The brute force: each board - its map and side - its legal sixes,
    whether the search's best sixes matched it bit for bit, the brute
    force's time against the search's, and the commit."""
    runs = get(results, "proof", "brute_force")
    rows = [r for r in runs if isinstance(r, dict)] if isinstance(runs, list) else []
    if not rows:
        return missing("the brute force (proof.brute_force)")
    matched = {True: "yes", False: "no"}
    body = []
    for r in rows:
        board = ", ".join(w for w in (plain(r.get("map")), plain(r.get("side"))) if w)
        body.append([
            esc(board or plain(r.get("board"))), count(r.get("legal")),
            matched[r["matched"]] if isinstance(r.get("matched"), bool) else "-",
            seconds(r.get("wall_seconds")), seconds(r.get("search_seconds")),
            commit_text(r.get("commit"))])
    return table(["board", "legal sixes", "matched", "brute force, seconds", "search, seconds",
                  "commit"], body)


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
    objective - its engine part and its playbook part, numbers - with its
    yardstick shares, the rules it keeps, its strength and its shape, each
    an aggregate with its range; and how many steps broke the trade."""
    per_mu = get(results, "slider", "per_mu")
    rows = [r for r in per_mu if isinstance(r, dict)] if isinstance(per_mu, list) else []
    if not rows:
        return missing("the Meta slider's steps (slider.per_mu)")
    names = [n for n in SLIDER if any(stat(r.get(n)) is not None for r in rows)]
    body = []
    for r in rows:
        mu = fmt(number(r.get("mu")), 2) + (", as shipped" if r.get("arm") == SHIPPED else "")
        body.append([mu, *(stat_html(stat(r.get(n)), places(results, n)) for n in names)])
    out = table(["meta", *(label(results, n) for n in names)], body)
    notes = []
    boards, scored_on = number(get(results, "slider", "boards")), plain(
        get(results, "slider", "scored_on"))
    if boards is not None:
        notes.append("Each setting's six over %s boards." % count(boards))
    if scored_on:
        notes.append("%s." % esc(scored_on[0].upper() + scored_on[1:]))
    broke = get(results, "slider", "violations")
    if number(broke) is not None:
        notes.append("%s steps checked; %s went against the trade." % (
            count(get(results, "slider", "steps")), count(broke)))
    return out + ("<p class='legend'>%s</p>" % " ".join(notes) if notes else "")


def paired_table(results: Mapping[str, Any], where: Where) -> str:
    """Countrix as shipped against each arm, board by board on the same
    boards, on each yardstick and on its own scale: the mean gap and its
    range, and how often it won, tied and lost. The file's other pairs -
    another capture's or another source's Countrix against its reference -
    are read under whether the results hold up, not here."""
    paired = results.get("paired")
    held = {(plain(p.get("b")), plain(p.get("metric"))): p for p in paired
            if isinstance(p, dict) and p.get("set") == where.set
            and p.get("slice") == where.slice and p.get("a") == SHIPPED
            } if isinstance(paired, list) else {}
    shown = [m for m in PAIRED if any(metric == m for _, metric in held)]
    if not shown:
        return missing("the board-by-board gaps (paired)")
    names = {a.id: a.label for a in arms(results)}
    against = list(dict.fromkeys([*(a.id for a in shown_arms(results, where)),
                                  *(b for b, _ in held)]))

    def cell(pair: Mapping[str, Any] | None) -> str:
        if pair is None:
            return "-"
        return "%s<br><span class='rng'>won %s, tied %s, lost %s</span>" % (
            stat_html(stat(pair.get("gap"))), count(pair.get("wins")), count(pair.get("ties")),
            count(pair.get("losses")))
    return table(["against", *(label(results, m) for m in shown)], [
        [esc(names.get(b, b)), *(cell(held.get((b, m))) for m in shown)]
        for b in against if any((b, m) in held for m in shown)])


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
                                 *(stat_html(s, places(results, m))
                                   for s, m in zip(stats, HEADLINE, strict=True))])
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

NONE_YET = "<p class='legend'>No results: the top of the page says why.</p>"
SAMPLE = (
    "<div class='warnbox'><b>A sample.</b> These results were written to build the page; no"
    " board was solved for them. The study's own results file replaces them.</div>")
DRIFTED = (
    "<div class='warnbox'><b>Not the board's objective.</b> %s The results below describe the"
    " objective the study measured.</div>")
RESULT_BLOCKS = ("PROFILE", "CHECKS", "BRUTE", "SEARCH", "DESIGN", "SHARES", "PARTS", "SCATTER",
                 "AGREEMENT", "RULES", "SLIDER", "PAIRED", "HOLDS", "PROVENANCE")


def drift(results: Mapping[str, Any]) -> list[str]:
    """What the board runs and the study did not measure, a line each: the
    playbook in force, where its digest does not open with the one the
    file records, and the default engine in force, where its stamp - the
    weights and the constants its terms count by - is not the file's.
    Nothing where the file records neither."""
    out = []
    measured = plain(get(results, "provenance", "countrix", "playbook_digest"))
    in_force = catalog.playbook_digest()
    if measured and not in_force.startswith(measured):
        out.append("The playbook in force, %s, is not the one the study measured: its digest"
                   " opens %s, the study's %s." % (
                       esc(catalog.playbook_name()), in_force[:12], esc(measured[:12])))
    recorded = get(results, "provenance", "countrix", "base_stamp")
    if isinstance(recorded, dict):
        stamp: Mapping[str, Any] = base.stamp(catalog.engine_weights()) or {}
        moved = ["%s %s, the study's %s" % (esc(name), esc(plain(stamp.get(name)) or "none"),
                                            esc(plain(recorded.get(name)) or "none"))
                 for name in dict.fromkeys([*recorded, *stamp])
                 if stamp.get(name) != recorded.get(name)]
        if moved:
            out.append("The default engine in force is not the one the study measured: %s."
                       % "; ".join(moved))
    return out


def status(study: Study) -> str:
    """What the page reads: why there are no results, or the file's
    vintage - under a sample's warning where the file is one, and a warning
    where the board runs another objective than the study measured."""
    results = study.results
    if results is None:
        return "<div class='warnbox'>%s</div>" % esc(study.note)
    named = (
        ("generated", ("generated",)), ("Countrix at", ("provenance", "countrix", "commit")),
        ("the benchmark at", ("provenance", "benchmark", "commit")))
    vintage = [
        "%s %s" % (words, commit_text(get(results, *path)) if path[-1] == "commit"
                   else esc(plain(get(results, *path))))
        for words, path in named if plain(get(results, *path))]
    out = "<p class='legend'>The results: %s.</p>" % "; ".join(vintage) if vintage else ""
    moved = drift(results)
    if moved:
        out = DRIFTED % " ".join(moved) + out
    if results.get("sample") is True:
        out = SAMPLE + out
    return out


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


def registry_ids() -> frozenset[str]:
    """The ids the registry holds: the playbook in force's."""
    return frozenset(s.id for s in catalog.load())


def assumptions_table(shipped: Sequence[strategy.Strategy], linked: frozenset[str]) -> str:
    """The shipped playbook's assumptions - the ones the proof and the study
    read - each with the first sentence of its prose and linked to its
    registry entry where the playbook in force holds it."""
    rows = []
    for s in shipped:
        if s.kind == "assumption":
            prose = " ".join(catalog.without_title(s.body).split())
            first = re.split(r"(?<=[.!?])\s", prose, maxsplit=1)[0] if prose else ""
            rows.append([entry(s.id, s.name, linked), esc(first)])
    return table(["assumption", "what it says"], rows) if rows else ""


def shapes_table(shipped: Sequence[strategy.Strategy]) -> str:
    """The count check: the sixes of each shape the shipped playbook
    allows, on the roster the proof was checked on, and their sum - the
    count the walk considered on every open board that day, whatever
    playbook the board runs now."""
    tanks, damage, supports = PROOF_ROSTER
    rows, total = [], 0
    for shape in legal_shapes(shipped):
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
    shipped, linked = catalog.load(catalog.SHIPPED_DIR), registry_ids()
    out = {
        "STATUS": status(study), "REPORT": report(results), "SHAPES": shapes_table(shipped),
        "ASSUMPTIONS": assumptions_table(shipped, linked)}
    where = None if results is None else primary(results)
    if results is None or where is None:
        out.update(dict.fromkeys(RESULT_BLOCKS, NONE_YET if results is None
                                 else missing("the aggregates (aggregates)")))
        return out
    out.update({
        "PROFILE": profile_table(results, where), "CHECKS": checks_table(results),
        "BRUTE": brute_table(results), "SEARCH": search_figure(results, where),
        "DESIGN": design_tables(results), "SHARES": shares_figure(results, where),
        "PARTS": parts_figure(results, where), "SCATTER": scatter_figure(results, where),
        "AGREEMENT": agreement_table(results, where),
        "RULES": rules_figure(results, linked), "SLIDER": slider_table(results),
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
