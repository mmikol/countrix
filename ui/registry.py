"""The strategy registry, /registry: the math of every rule in the
playbook in force, one entry per strategy, rendered on every call from the
code the solver runs - the catalog (inference.catalog), the metric
registry and its descriptions (facts.compute.registry), the range rules,
which say how each metric aggregates over the six (inference.ranges), the
needs' budget (inference.scoring.need_scales) and the citation record
(inference/README.md) - so the page cannot drift from the code.

An entry says in plain words what its rule does - its form as the code
reads it, its weight and the most it moves a six, its gate and who settles
it - then writes its formula with its own numbers, its params filled in,
each metric it reads, its prose and its sources. The math page
(ui/static/math.html) gives the general forms, and each entry links its
form there. ui/board.py serves it; nothing here reads the database, and
every string read from a file is escaped.
"""

import io
import os
import re
import textwrap
import tokenize
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, NamedTuple
from urllib.parse import unquote

from db import ROOT
from facts import compute
from facts.team_facts import counted
from inference import catalog, ranges, scoring
from inference.base import BaseWeights
from inference.expr import Expr
from inference.shapes import is_shape_limit
from inference.strategy import KINDS, Form, Kind, Strategy, field_text, settled_by_board
from ui import pages
from ui.pages import esc

RECORD_PATH = os.path.join(ROOT, "inference", "README.md")
# a strategy's line in the record, a source listed under it, and a source
# the page links: a web address and nothing else
ENTRY_RE = re.compile(r"- `([a-z0-9][a-z0-9-]*)` - (.*)")
SOURCE_RE = re.compile(r"  - (.+)")
LINKABLE_RE = re.compile(r"https?://\S+")

# the page's own anchors hold an underscore, which no strategy id does
# (catalog.ID_RE), so an entry's anchor, its strategy's id, never meets one
TOP, GLANCE = "the_registry", "at_a_glance"
GROUPS: dict[Kind, tuple[str, str]] = {
    "constraint": ("the_limits", "Limits"),
    "heuristic": ("the_heuristics", "Heuristics"),
    "assumption": ("the_assumptions", "Assumptions")}

# a strategy's form as this page names it: a heuristic on a metric is a
# reward or a need, by who settles its gate (Strategy.need)
type Shown = Literal["limit", "reward", "need", "scored", "assumption", "draft"]
SHOWN: dict[Form, Shown] = {"limit": "limit", "heuristic": "reward", "scored": "scored",
                            "assumption": "assumption", "draft": "draft"}
# who settles a strategy's gate: none it has, the board, or the six
type Settler = Literal["none", "board", "six"]

# what each section an expression reads is, in words, in the order they are named
SECTIONS = {"team": "the six", "matchup": "the six against red's revealed picks",
            "enemy": "red's revealed picks", "map": "the ground in play",
            "world": "the released roster's benchmarks"}
# how a metric of a section the board settles reads over the six: one value for all
SETTLED = {
    "enemy": "red's revealed picks', the same for every six",
    "map": "the board's ground in play, the same for every six",
    "world": "the released roster's, the same for every six"}
# the math page's sections that derive a metric, by the metric's name in its section
DERIVED = {
    "heal_need": ("healing-floor", "the healing bar"),
    "heal_shortfall": ("healing-floor", "the healing bar"),
    **dict.fromkeys(("hps_floor", "hps_supports", "hps_per_support", "hps_ratio", "hps_bench"),
                    ("sustained-healing", "sustained healing"))}
# where the math page gives each form in general
FORM_LINKS: dict[Shown, str] = {
    "limit": "<a href='/math#chosen'>how a six is chosen</a>, step 2",
    "reward": "<a href='/math#function'>the function</a>, its rewards",
    "need": "<a href='/math#function'>the function</a>, its needs and their budget",
    "scored": "<a href='/math#function'>the function</a>, its scored terms",
    "assumption": "<a href='/math#equation'>the equation</a>, where an ASSUMPTION adds nothing",
    "draft": "<a href='/math#equation'>the equation</a>, which a draft is not yet in"}
# where the math page gives the most each form moves a six and sets it beside
# the default engine's terms: its paragraph on the engine's weights
BOUND_LINK = (
    "the most each form moves a six, beside the default engine's terms:"
    " <a href='/math#base-weights'>the engine's weights</a>")
# what the registry and the math page's engine's weights both say of the shipped
# playbook's scored rules; test_registry holds it on every six the shipped limits
# allow, by brute force on the synthetic World and by the range rules on the built roster
SHIPPED_SCORED_BOUND = (
    "Every shipped scored rule keeps its bonus and its penalty within 0 to 1 inside the"
    " shipped limits, so it too moves a six by its weight at most.")
# a formula block's columns: the label, then what it is, wrapped to fit the card
LABEL_WIDTH, FORMULA_WIDTH = 12, 88


# --- the citation record ---------------------------------------------------------

class Citation(NamedTuple):
    """One entry of the citation record: the line that cites a strategy, its
    id aside, and the sources listed under it."""
    note: str
    sources: tuple[str, ...]


def citations(path: str = RECORD_PATH) -> dict[str, list[Citation]]:
    """The citation record by strategy id: each ``- `id` - note`` line and
    the sources indented under it, in the record's order. An id two rules
    have held in turn has an entry for each, the earlier first, as the
    record's preamble says: the last is the rule the id names now."""
    with open(path, encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    out: dict[str, list[Citation]] = {}
    current: tuple[str, str, list[str]] | None = None
    for line in [*lines, ""]:
        source = SOURCE_RE.fullmatch(line)
        if current is not None and source:
            current[2].append(source.group(1).strip())
            continue
        if current is not None:
            out.setdefault(current[0], []).append(Citation(current[1], tuple(current[2])))
            current = None
        entry = ENTRY_RE.fullmatch(line)
        if entry:
            current = (entry.group(1), entry.group(2).strip(), [])
    return out


# --- a rule as the code reads it -------------------------------------------------

def shown_form(s: Strategy) -> Shown:
    """The form this page names: a limit, a reward, a need, a scored
    heuristic, an assumption or a draft - a heuristic on a metric a need
    where Strategy.need says so, as the score charges it, else a reward."""
    return "need" if s.need else SHOWN[s.form]


def settler(s: Strategy) -> Settler:
    """Who settles the strategy's `when`: none where it has none; the board
    where it reads only the board's sections and its params, as the
    solver's gates read it (strategy.settled_by_board); else the six."""
    if s.when is None:
        return "none"
    return "board" if settled_by_board(s.when.names) else "six"


def filled(expr: Expr, params: Mapping[str, float]) -> str:
    """An expression's source with each params.NAME it reads written as the
    dial's value - a negative one in brackets - and the rest as written."""
    source, out, last = expr.source, [], 0
    tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    for i in range(len(tokens) - 2):
        name, dot, dial = tokens[i], tokens[i + 1], tokens[i + 2]
        if (name.type == tokenize.NAME and name.string == "params" and dot.string == "."
                and dial.string in params):
            value = params[dial.string]
            out += [source[last:name.start[1]], ("(%s)" if value < 0 else "%s") % field_text(value)]
            last = dial.end[1]
    return "".join(out) + source[last:]


class Read(NamedTuple):
    """A metric a strategy reads, and the parts of the strategy that read it."""
    key: str
    parts: tuple[str, ...]


def reads(s: Strategy) -> list[Read]:
    """Every metric the strategy reads, its params aside: its metric, then
    the names of its gate, its limit, its bonus and its penalty, each once,
    with the parts that read it."""
    parts: dict[str, list[str]] = {}
    if s.metric:
        parts[s.metric] = ["the metric"]
    for label, expr in (("the gate", s.when), ("the limit", s.require),
                        ("the bonus", s.bonus), ("the penalty", s.penalty)):
        for name in expr.names if expr is not None else ():
            if not name.startswith("params."):
                parts.setdefault(name, []).append(label)
    return [Read(key, tuple(labels)) for key, labels in parts.items()]


def over_the_six(key: str) -> str:
    """How a metric aggregates over the six: its range rule's words
    (ranges.Spec.aggregate) for the six's own metrics, else the board's one
    value."""
    rule = ranges.RULES.get(key)
    if rule is not None:
        return rule.aggregate
    return SETTLED.get(key.split(".", 1)[0], "no range rule")


# --- words and numbers -----------------------------------------------------------

def _num(value: float) -> str:
    """A number as the page writes it: %g."""
    return "%g" % value


def _and(items: Sequence[str]) -> str:
    """Words joined as a list: a, b and c."""
    return " and ".join(items) if len(items) < 3 else "%s and %s" % (
        ", ".join(items[:-1]), items[-1])


def _gate_reads(expr: Expr) -> str:
    """What a gate reads, in words: the sections it names, its params aside,
    "only" those where the board settles it; where it names no section, only
    its params, or no metric and no param at all."""
    read = {name.split(".", 1)[0] for name in expr.names}
    named = [words for section, words in SECTIONS.items() if section in read]
    if not named:
        return "only its params" if "params" in read else "no metric and no param"
    return ("only %s" if settled_by_board(expr.names) else "%s") % _and(named)


def _code(expr: Expr, params: Mapping[str, float]) -> str:
    """An expression, its params filled in, as inline code."""
    return "<code>%s</code>" % esc(filled(expr, params))


def _marked(text: str) -> str:
    """Text from a file escaped, its backticked spans as code."""
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", esc(text))


def _constant(expr: Expr | None) -> float | None:
    """An expression's value where its source is one number, else None."""
    if expr is None:
        return 0.0
    try:
        return float(expr.source)
    except ValueError:
        return None


# --- one entry ---------------------------------------------------------------------

@dataclass(frozen=True)
class Needs:
    """Each need's guard-mates - the needs that share its guard, in catalog
    order - and its scale (scoring.need_scales), by id."""
    groups: dict[str, list[Strategy]]
    scales: dict[str, float]


def needs(strategies: Sequence[Strategy]) -> Needs:
    """Every need's guard-mates and scale, as the score reads them."""
    by_guard: dict[scoring.Guard, list[Strategy]] = {}
    for s in strategies:
        guard = scoring.need_guard(s)
        if guard is not None:
            by_guard.setdefault(guard, []).append(s)
    groups = {s.id: mates for mates in by_guard.values() for s in mates}
    return Needs(groups=groups, scales=scoring.need_scales(strategies))


def _gate_words(s: Strategy) -> str:
    """Its gate in plain words: none, or the expression and who settles it."""
    if s.when is None:
        return "It has no gate: it counts on every board."
    if settler(s) == "board":
        return ("It counts only on a board where its gate holds, %s. The board settles that"
                " once, as the gate reads %s, so no six can change it."
                % (_code(s.when, s.params), _gate_reads(s.when)))
    return ("It counts only on a six that meets its gate, %s, which the six decides, as the"
            " gate reads %s." % (_code(s.when, s.params), _gate_reads(s.when)))


def _metric_words(s: Strategy) -> str:
    """A heuristic's metric and what it is, in the registry's words."""
    key = s.metric or ""
    return "<code>%s</code>, %s" % (esc(key), esc(compute.registry().get(key, "")))


def _budget_words(s: Strategy, book: Needs) -> str:
    """How the needs' shared budget scales this need: s, its share of it."""
    mates = book.groups.get(s.id, [s])
    if len(mates) == 1:
        return "its weight, as s is 1: it is the only need on its guard"
    scale, names = _num(book.scales.get(s.id, 1.0)), _and([esc(m.id) for m in mates])
    return ("its weight times s = %s: the needs on one guard - here %s - cost %s at most"
            " together, or their largest weight where that is more"
            % (scale, names, _num(scoring.NEED_BUDGET)))


def _scored_bound(s: Strategy) -> str:
    """The most a scored rule moves a six where it counts, in words."""
    w = s.weight
    bonus, penalty = _constant(s.bonus), _constant(s.penalty)
    parts = []
    if s.bonus is None:
        parts.append("there is no bonus")
    elif bonus is not None:
        parts.append("the bonus adds exactly %s" % _num(w * bonus))
    else:
        parts.append("the bonus adds up to %s times its largest value" % _num(w))
    if s.penalty is None:
        parts.append("there is no penalty")
    elif penalty is not None:
        parts.append("the penalty takes exactly %s" % _num(w * penalty))
    else:
        parts.append("the penalty takes up to %s times its largest value" % _num(w))
    return ("Where it counts it moves a six by %s times its bonus less its penalty: %s."
            % (_num(w), ", and ".join(parts)))


def _words(s: Strategy, book: Needs) -> str:
    """What the rule does, in plain words: its form, its weight and the most
    it moves a six, and its gate."""
    form, w = shown_form(s), _num(s.weight)
    better = "less" if s.direction == "minimize" else "more"
    if form == "limit":
        text = ("A limit: every six must keep it. A six that breaks it is removed before any"
                " score is read - it is never chosen, and blue's picks that break it read not"
                " allowed - so it weighs nothing and adds nothing to a score. It reaches the"
                " scores only through the scale, which reads only sixes the limits allow: each"
                " heuristic on a metric is read against the board's reference sample and"
                " top-hero sixes, and the share's 0 is the lowest score among the reference"
                " sample's sixes alone - the top-hero sixes set the scale, not the floor.")
        if is_shape_limit(s):
            text += (" It reads only the six's shape, so the search drops the shapes that break"
                     " it before it seats a hero.")
        return "<p>%s</p>" % text
    if form == "reward":
        return ("<p>A reward: a heuristic on a metric, %s. It adds its weight times the six's"
                " norm on that metric - the metric placed on 0 to 1 between the lowest and the"
                " highest values the board's reference sample and top-hero sixes take, %s being"
                " better - so it adds 0 to %s, at most its weight. %s</p>"
                % (_metric_words(s), better, w, _gate_words(s)))
    if form == "need" and s.when is not None:
        most = book.scales.get(s.id, 1.0) * s.weight
        cost = ("It costs 0 to %s, %s." % (_num(most), _budget_words(s, book)) if most
                else "At weight 0 it costs nothing.")
        return ("<p>A need: a heuristic on a metric, %s. Its gate, %s, reads %s, so it counts"
                " only on a six that meets the gate, and there it charges what the six misses:"
                " s times its weight times (1 &minus; norm), s its share of its guard's budget"
                " - nothing at norm 1 and all of s times its weight at norm 0. The norm places"
                " the metric on 0 to 1 between the lowest and the highest values the board's"
                " reference sample and top-hero sixes take where they meet the gate, %s being"
                " better; where those sixes hold one value, or none of them meets the gate, the"
                " norm is 1 and the need costs nothing. A six that misses the gate pays nothing,"
                " so meeting the gate never pays. %s</p>"
                % (_metric_words(s), _code(s.when, s.params), _gate_reads(s.when), better, cost))
    if form == "scored":
        six = ""
        if settler(s) == "six":
            six = (" Unlike a need, a scored rule can pay or charge a six for meeting a gate"
                   " it decides.")
        return ("<p>A scored heuristic: it adds its weight times its bonus less its penalty,"
                " each an expression read on the six. %s%s %s</p>"
                % (_gate_words(s), six, _scored_bound(s)))
    if form == "assumption":
        return ("<p>An assumption: prose the solver takes as given and the playbook tab shows."
                " It adds nothing to a score - no term, no weight, no gate - and limits"
                " nothing.</p>")
    return ("<p>A draft: a name, a kind and prose only, which the /strategy skill turns into a"
            " rule. Until then it scores nothing and limits nothing.</p>")


def _line(label: str, html: str) -> str:
    """A formula row: the label in its column, then `html` as it stands."""
    return "%-*s%s" % (LABEL_WIDTH, label, html)


def _note(text: str, label: str = "") -> list[str]:
    """Plain text in a formula block, escaped and wrapped under the label's
    column."""
    lines = textwrap.wrap(text, FORMULA_WIDTH - LABEL_WIDTH, break_long_words=False,
                          break_on_hyphens=False)
    return [_line(label if i == 0 else "", esc(line)) for i, line in enumerate(lines)]


def _gate_lines(s: Strategy) -> list[str]:
    """The formula's gate: the expression, its params filled in, and who
    settles it."""
    if s.when is None:
        return []
    if settler(s) == "board":
        who = "the board settles it once: it reads %s" % _gate_reads(s.when)
    else:
        who = "the six decides it: it reads %s" % _gate_reads(s.when)
    return [_line("gate", esc(filled(s.when, s.params))), *_note(who)]


def _norm_lines(s: Strategy, need: bool) -> list[str]:
    """The norm a heuristic on a metric reads, and its scale's two ends."""
    clamp = "clamp( (v &minus; min_ref) / (max_ref &minus; min_ref), 0, 1 )"
    if s.direction == "minimize":
        lines = [_line("norm(v)", "= 1 &minus; %s" % clamp), *_note("minimize: less is better")]
    else:
        lines = [_line("norm(v)", "= %s" % clamp), *_note("maximize: more is better")]
    sixes = "the board's reference sample and top-hero sixes"
    if need:
        return [*lines, *_note("the lowest %s over %s that meet the gate" % (s.metric, sixes),
                               "min_ref"),
                *_note("the highest over them; where the two meet, or no six meets the gate,"
                       " the need costs nothing", "max_ref")]
    if s.when is not None:
        sixes += ", the gate read as true"
    return [*lines, *_note("the lowest %s over %s" % (s.metric, sixes), "min_ref"),
            *_note("the highest over them; where the two meet, or no six is read, norm is 0.5",
                   "max_ref")]


def _scale_lines(s: Strategy, book: Needs) -> list[str]:
    """A need's s, its share of its guard's budget, as scoring.need_scales
    reads it: 1 where the weights on the guard sum to 0, which it does not
    divide by."""
    weights = [m.weight for m in book.groups.get(s.id, [s])]
    if not sum(weights):
        return [_line("s", "= 1"), *_note("the weights on this guard sum to 0, so s scales"
                                          " nothing")]
    budget, largest, total = (_num(scoring.NEED_BUDGET), _num(max(weights)),
                              _num(sum(weights)))
    return [_line("s", "= min( 1, max( %s, %s ) / %s ) = %s"
                  % (budget, largest, total, _num(book.scales.get(s.id, 1.0)))),
            *_note("%s: the needs' budget; %s: the largest weight on this guard; %s: the"
                   " weights on it summed" % (budget, largest, total))]


def _formula(s: Strategy, book: Needs) -> str:
    """The rule in the math page's notation, its own numbers and params
    filled in: the lines of its formula block, empty for an assumption or a
    draft."""
    form, w = shown_form(s), _num(s.weight)
    lines: list[str] = []
    where = _note("where the gate holds; else 0" if s.when is not None else "on every six")
    if form == "limit" and s.require is not None:
        limit = esc(filled(s.require, s.params))
        lines += [_line("legal(x)", "only where  %s  holds on x" % limit),
                  *_note("a six where it fails is removed before any score is read")]
    elif form == "reward":
        lines += [_line("term(x)", "= %s &middot; norm( %s(x) )" % (w, esc(s.metric or ""))),
                  *where, *_gate_lines(s), *_norm_lines(s, need=False)]
    elif form == "need":
        lines += [_line("term(x)", "= s &middot; %s &middot; ( norm( %s(x) ) &minus; 1 )"
                        % (w, esc(s.metric or ""))),
                  *_note("on a six that meets the gate; else 0"), *_gate_lines(s),
                  *_scale_lines(s, book), *_norm_lines(s, need=True)]
    elif form == "scored":
        lines += [_line("term(x)", "= %s &middot; ( bonus(x) &minus; penalty(x) )" % w), *where,
                  *_gate_lines(s)]
        for label, expr in (("bonus(x)", s.bonus), ("penalty(x)", s.penalty)):
            lines.append(_line(label, "= %s" % (esc(filled(expr, s.params)) if expr is not None
                                               else "0, none set")))
    if lines and s.params:
        lines.append(_line("params", " &middot; ".join(
            "%s = %s" % (esc(name), esc(field_text(value))) for name, value in s.params.items())))
    return "\n".join(lines)


def _reads_table(s: Strategy) -> str:
    """Each metric the rule reads: its key and the parts that read it, its
    meaning in the registry, and how it aggregates over the six."""
    known = compute.registry()
    rows = []
    for key, parts in reads(s):
        derived = DERIVED.get(key.split(".", 1)[-1])
        meaning = esc(known.get(key, ""))
        if derived is not None:
            meaning += " (the math page: <a href='/math#%s'>%s</a>)" % derived
        rows.append("<tr><td><code>%s</code><div class='legend'>%s</div></td><td>%s</td>"
                    "<td>%s</td></tr>" % (esc(key), esc(_and(parts)), meaning,
                                          esc(over_the_six(key))))
    if not rows:
        return ""
    # in a box that scrolls sideways: a metric's key keeps one line, and a card
    # narrower than the table scrolls it rather than cutting it off
    return ("<div class='lbl'>what it reads</div><div class='wide'><table class='reads'><tr>"
            "<th>metric</th><th>what it is</th><th>over the six</th></tr>%s</table></div>"
            % "".join(rows))


def _prose(s: Strategy) -> str:
    """The rule's prose, less its title line, a paragraph each."""
    body = catalog.without_title(s.body).strip()
    paragraphs = [" ".join(p.split()) for p in re.split(r"\n\s*\n", body) if p.strip()]
    if not paragraphs:
        return ""
    return "<div class='lbl'>in the playbook's words</div>%s" % "".join(
        "<p>%s</p>" % _marked(p) for p in paragraphs)


def _link(source: str) -> str:
    """A source as a link where it is a web address, shown without its
    scheme and its escapes, else as text."""
    if LINKABLE_RE.fullmatch(source):
        shown = unquote(re.sub(r"^https?://(www\.)?", "", source))
        return "<a href='%s' target='_blank' rel='noopener'>%s</a>" % (esc(source), esc(shown))
    return esc(source)


def _listed(entry: Citation) -> str:
    """An entry's sources as a list, each a link where it is a web address."""
    return "<ul class='sources'>%s</ul>" % "".join(
        "<li>%s</li>" % _link(source) for source in entry.sources)


def _sources(s: Strategy, record: Mapping[str, Sequence[Citation]]) -> str:
    """The rule's entry in the citation record, its line with its sources
    folded under it. An id two rules have held in turn has an entry for
    each, the earlier first (citations): the last is this rule's, and each
    before it is folded away under a label that names it the earlier rule
    of this id."""
    entries = record.get(s.id, ())
    if not entries:
        return ("<div class='lbl'>sources</div><p>The citation record,"
                " <code>inference/README.md</code>, holds no entry for it.</p>")
    *earlier, current = entries
    out = ["<div class='lbl'>sources</div><p>%s</p>" % _marked(current.note)]
    if current.sources:
        out.append("<details><summary>%s</summary>%s</details>" % (
            counted(len(current.sources), "source"), _listed(current)))
    for entry in earlier:
        out.append("<details class='earlier'><summary>the earlier rule of this id, which the"
                   " playbook no longer holds</summary><p>%s</p>%s</details>"
                   % (_marked(entry.note), _listed(entry) if entry.sources else ""))
    return "".join(out)


def entry(s: Strategy, book: Needs, record: Mapping[str, Sequence[Citation]]) -> str:
    """One strategy's card, anchored by its id: its name, id, kind and form,
    then what it does in plain words, its formula, what it reads, its prose
    and its sources."""
    form = shown_form(s)
    head = [esc(s.id), esc(s.category), form]
    if s.weighs:
        head.append("weight %s" % _num(s.weight))
    formula = _formula(s, book)
    if formula:
        formula = "<div class='lbl'>the formula</div><pre class='eq'>%s</pre>" % formula
    bound = "; %s" % BOUND_LINK if s.weighs else ""
    parts = (
        s.kind, esc(s.id), s.kind, s.kind, esc(s.name), " &middot; ".join(head),
        _words(s, book), formula, _reads_table(s), FORM_LINKS[form], bound, _prose(s),
        _sources(s, record))
    return ("<div class='hcard %s' id='%s'><span class='kind %s'>%s</span><b>%s</b>"
            "<div class='meta'>%s</div><div class='lbl'>what it does</div>%s%s%s"
            "<p class='legend'>The general form: %s%s.</p>%s%s</div>" % parts)


# --- the page ----------------------------------------------------------------------

def _moves(s: Strategy, book: Needs) -> str:
    """The most the rule moves a six, as the table at a glance says it."""
    form, w = shown_form(s), _num(s.weight)
    if form == "limit":
        return "removes the sixes that break it"
    if form == "reward":
        return "0 to %s" % w
    if form == "need":
        most = book.scales.get(s.id, 1.0) * s.weight
        return "&minus;%s to 0" % _num(most) if most else "0"
    if form == "scored":
        return "%s &middot; (bonus &minus; penalty)" % w
    return "nothing"


def _glance(strategies: Sequence[Strategy], book: Needs) -> str:
    """Every rule in a row: its form, its weight, the most it moves a six and
    who settles its gate, each linked to its entry."""
    rows = []
    for s in strategies:
        gate = {"none": "none", "board": "the board", "six": "the six"}[settler(s)]
        rows.append("<tr><td><a href='#%s'>%s</a></td><td>%s</td><td>%s</td><td>%s</td>"
                    "<td>%s</td></tr>" % (esc(s.id), esc(s.name), shown_form(s),
                                          _num(s.weight) if s.weighs else "-", _moves(s, book),
                                          gate if s.kind == "heuristic" else "-"))
    return ("<div class='wide'><table class='glance'><tr><th>rule</th><th>form</th>"
            "<th>weight</th><th>moves a six by</th><th>gate settled by</th></tr>%s</table></div>"
            % "".join(rows))


def _tally(strategies: Sequence[Strategy]) -> str:
    """What the playbook holds, by form, in a sentence: a draft of any kind
    counts as a draft alone, never as a limit or a heuristic."""
    forms = Counter(shown_form(s) for s in strategies)
    heuristics = "%s - %s, %s and %d scored" % (
        counted(forms["reward"] + forms["need"] + forms["scored"], "heuristic"),
        counted(forms["reward"], "reward"), counted(forms["need"], "need"), forms["scored"])
    return "%d %s: %s; %s; and %s%s" % (
        len(strategies), "strategy" if len(strategies) == 1 else "strategies",
        counted(forms["limit"], "limit"), heuristics, counted(forms["assumption"], "assumption"),
        "; %s awaiting /strategy" % counted(forms["draft"], "draft") if forms["draft"] else "")


def article(strategies: Sequence[Strategy], record: Mapping[str, Sequence[Citation]],
            weights: BaseWeights, *, playbook: str, shipped: bool) -> str:
    """The registry's article: what it is, the default engine under the
    rules, every rule at a glance, then an entry per rule grouped by kind.
    `shipped` says the playbook is the shipped one, of whose scored rules
    the page says SHIPPED_SCORED_BOUND, as the math page does."""
    book = needs(strategies)
    base = ("base(x) = %s &middot; ( %s &middot; rates(x) + %s &middot; synergy(x) + %s &middot;"
            " counters(x) )" % tuple(_num(getattr(weights, f)) for f in
                                      ("meta", "rate", "synergy", "counter")))
    out = [
        "<article class='math'><nav class='toc'><a href='#%s'>the registry</a>"
        "<a href='#%s'>at a glance</a>%s</nav>" % (TOP, GLANCE, "".join(
            "<a href='#%s'>%s</a>" % (anchor, title.lower())
            for anchor, title in GROUPS.values())),
        "<h2 id='%s'>The strategy registry</h2>" % TOP,
        "<p>Every rule of the playbook in force, <code>%s</code>, as the solver reads it: what"
        " it does in plain words, then its formula with its own numbers filled in, each metric"
        " it reads, its prose and its sources. The page is rendered from the code on every"
        " load - the catalog, the metric registry, the range rules and the citation record -"
        " so it says what the solver runs. <a href='/math'>The math page</a> gives the"
        " general forms, and each entry links its form there.</p>" % esc(playbook),
        "<p>Every six is scored first by <a href='/math#default-engine'>the default"
        " engine</a> at <code>meta.md</code>'s weights; the playbook's terms sit on top, and"
        " the limits decide which sixes are read at all:</p>",
        "<pre class='eq'>score(x) = base(x)\n"
        "         + &Sigma; rewards h   w_h &middot; norm_h( metric_h(x) )\n"
        "         + &Sigma; needs n     s_n &middot; w_n &middot; ( norm_n( metric_n(x) )"
        " &minus; 1 )\n"
        "         + &Sigma; scored r    w_r &middot; ( bonus_r(x) &minus; penalty_r(x) )\n"
        "           for a six x every limit allows; a term whose gate fails adds 0, and an"
        " assumption adds nothing\n%s</pre>" % base,
        "<p>The playbook holds %s.</p>" % _tally(strategies),
        "<h2 id='%s'>At a glance</h2>" % GLANCE, _glance(strategies, book)]
    intros: dict[Kind, str] = {
        "constraint": "A limit cuts the space: every six must keep it, and it weighs nothing"
                      " (<a href='/math#chosen'>how a six is chosen</a>).",
        "heuristic": "A heuristic weighs the sixes the limits leave. On a metric it is a"
                     " reward where it has no gate or the board settles it, and a need where"
                     " the six decides it; otherwise it is scored, its weight times its bonus"
                     " less its penalty (<a href='/math#function'>the function</a>). A heuristic"
                     " on a metric moves a six by its weight at most; a scored one by its weight"
                     " times its bonus less its penalty (%s). Each weight here is its file's;"
                     " a slider on the playbook tab sets another for a session.%s" % (
                         BOUND_LINK, " " + SHIPPED_SCORED_BOUND if shipped else ""),
        "assumption": "An assumption is prose the solver takes as given; it adds nothing to a"
                      " score (<a href='/math#equation'>the equation</a>)."}
    for kind in KINDS:
        anchor, title = GROUPS[kind]
        these = [s for s in strategies if s.kind == kind]
        out.append("<h2 id='%s'>%s</h2><p>%s</p>" % (anchor, title, intros[kind]))
        out += [entry(s, book, record) for s in these] or [
            "<p class='legend'>None in this playbook.</p>"]
    out.append("</article>")
    return "\n".join(out)


def view_registry() -> str:
    """The registry page: the playbook in force, read on every call with
    its meta.md and the citation record, in the page shell."""
    folder = catalog.strategies_dir()
    return pages.page("the strategy registry", article(
        catalog.load(folder), citations(), catalog.engine_weights(folder),
        playbook=catalog.playbook_name(), shipped=folder == catalog.SHIPPED_DIR))
