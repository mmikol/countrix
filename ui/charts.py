"""Charts drawn on the server as inline SVG, for the study page
(ui/study.py): the pieces - a chart's frame, its text and lines, a linear
and a log scale on round ticks, a row's wrapped label, labels placed clear
of each other - and the five forms the study draws, each from plain rows
that know nothing of the results file: dots with their ranges, diverging
stacked bars, a scatter, a heatmap, and a funnel on a log scale.

A chart is coloured by class, never by a colour of its own: each mark
carries its row's class, and board.css colours the class, so the palette
changes in one place. Every mark carries a <title>, the browser's tooltip,
and every string drawn is escaped. A chart is PANEL wide and shrinks with
its box, never past it; the heatmap keeps its size in a box that scrolls
sideways.
"""

import math
import textwrap
from collections.abc import Callable, Iterator, Mapping, Sequence
from typing import NamedTuple

from ui.pages import esc

PANEL = 400          # a chart's width: two sit side by side on a wide screen, one on a phone
LABEL = 152          # the column a row's label is drawn in
ROW = 28             # a row's height
GAP = 8              # the room between two groups of rows
MINUS = "−"     # the minus sign a negative tick is written with


class Stat(NamedTuple):
    """A mean and its 95% range; the range None where there is none."""
    mean: float
    lo: float | None
    hi: float | None


# --- the pieces ---------------------------------------------------------------------------

def frame(width: float, height: float, body: str, label: str, keep: bool = False) -> str:
    """An SVG `width` x `height` named `label`, which shrinks with its box -
    or, `keep`, holds its size in a box that scrolls sideways."""
    return ("<svg class='chart%s' viewBox='0 0 %d %d' width='%d' height='%d' role='img'"
            " aria-label='%s'>%s</svg>" % (" keep" if keep else "", width, height, width,
                                           height, esc(label), body))


def text(x: float, y: float, words: str, cls: str, anchor: str = "start") -> str:
    """`words` at (x, y), escaped, in the class `cls`."""
    return "<text x='%.1f' y='%.1f' class='%s' text-anchor='%s'>%s</text>" % (
        x, y, cls, anchor, esc(words))


def line(x1: float, y1: float, x2: float, y2: float, cls: str) -> str:
    return "<line x1='%.1f' y1='%.1f' x2='%.1f' y2='%.1f' class='%s'/>" % (x1, y1, x2, y2, cls)


def cut(words: str, width: int) -> str:
    """`words` cut to `width` characters, an ellipsis ending a cut."""
    return words if len(words) <= width else words[:width - 1].rstrip() + "…"


def tick_text(value: float) -> str:
    """A tick's number: whole, with a minus sign."""
    rounded = round(value)
    return "%s%d" % (MINUS if rounded < 0 else "", abs(rounded))


def row_label(x: float, y: float, words: str, width: int = 24) -> str:
    """A row's label, right-aligned at x and centred on y, wrapped to two
    lines at most, the second cut where it runs over."""
    lines = textwrap.wrap(words, width) or [words]
    if len(lines) > 2:
        lines = [lines[0], cut(" ".join(lines[1:]), width)]
    if len(lines) == 1:
        return text(x, y + 4, lines[0], "lab", "end")
    return ("<text x='%.1f' y='%.1f' class='lab' text-anchor='end'><tspan x='%.1f'>%s</tspan>"
            "<tspan x='%.1f' dy='13'>%s</tspan></text>"
            % (x, y - 2.5, x, esc(lines[0]), x, esc(lines[1])))


def scale(lo: float, hi: float, start: float, end: float) -> Callable[[float], float]:
    """The linear map from lo..hi onto start..end."""
    span = (hi - lo) or 1.0
    return lambda v: start + (v - lo) / span * (end - start)


def domain(values: Sequence[float], low: float, high: float) -> tuple[float, float, float]:
    """A range that holds the finite values, `low` and `high`, on round
    ticks, eight at most -> (from, to, step)."""
    held = [v for v in values if math.isfinite(v)]
    lo, hi = min([low, *held]), max([high, *held])
    least = (hi - lo) / 7.0
    step = next((s for s in (10.0, 20.0, 25.0, 50.0, 100.0) if least <= s),
                10.0 ** math.ceil(math.log10(least)))
    return math.floor(lo / step) * step, math.ceil(hi / step) * step, step


def ticks(lo: float, hi: float, step: float) -> Iterator[float]:
    tick = lo
    while tick <= hi + 1e-9:
        yield tick
        tick += step


def grid(
        x: Callable[[float], float], span: tuple[float, float, float], top: float,
        bottom: float, refs: Sequence[float]) -> list[str]:
    """The vertical gridlines with their numbers on top, the reference
    lines at `refs` stronger."""
    out = []
    for tick in ticks(*span):
        out += [line(x(tick), top, x(tick), bottom, "ref" if tick in refs else "grid"),
                text(x(tick), top - 6, tick_text(tick), "tick", "middle")]
    return out


def stacked(groups: Sequence[str], top: float) -> tuple[list[float], float]:
    """Each row's centre, two groups apart by GAP -> (centres, bottom)."""
    centres, y, previous = [], top, None
    for group in groups:
        if previous is not None and group != previous:
            y += GAP
        centres.append(y + ROW / 2)
        y += ROW
        previous = group
    return centres, y


type Box = tuple[float, float, float, float]
# where a label may sit beside its point, in the order tried - right, left,
# above, below, then the corners - each as (dx, dy, anchor) from the point;
# no further out, where a label would read as another point's
PLACES = (
    (8.0, 4.0, "start"), (-8.0, 4.0, "end"), (0.0, -9.0, "middle"), (0.0, 17.0, "middle"),
    (6.0, -6.0, "start"), (-6.0, -6.0, "end"), (6.0, 14.0, "start"), (-6.0, 14.0, "end"))


def placed(
        labels: Sequence[tuple[float, float, str]], marks: Sequence[tuple[float, float]],
        box: Box) -> list[str]:
    """Each label beside its point where it fits - right, left, above,
    below - inside `box` and clear of every mark and every label placed
    before it, the first label first; one that fits nowhere is left to its
    mark's tooltip."""
    taken: list[Box] = [(px - 6.0, py - 6.0, px + 6.0, py + 6.0) for px, py in marks]
    out = []
    for px, py, words in labels:
        width = 5.8 * len(words)
        for dx, dy, anchor in PLACES:
            shift = width if anchor == "end" else width / 2 if anchor == "middle" else 0.0
            rect = (px + dx - shift, py + dy - 10.0, px + dx - shift + width, py + dy + 2.0)
            inside = (box[0] <= rect[0] and rect[2] <= box[2] and box[1] <= rect[1]
                      and rect[3] <= box[3])
            if inside and not any(rect[0] < t[2] and t[0] < rect[2] and rect[1] < t[3]
                                  and t[1] < rect[3] for t in taken):
                taken.append(rect)
                out.append(text(px + dx, py + dy, words, "plab", anchor))
                break
    return out


# --- dots with their ranges ------------------------------------------------------------------

class DotRow(NamedTuple):
    """A row of dots: its label, its group - two groups' rows sit apart -
    the class that colours it, its values, a Stat or None each, the first
    drawn filled and the second hollow, and its tooltip."""
    label: str
    group: str
    css: str
    values: tuple[Stat | None, ...]
    tip: str


def dots(rows: Sequence[DotRow], heading: str, refs: Sequence[float] = (0.0, 100.0)) -> str:
    """A row a line of dots on one scale, each dot with its range, and the
    reference lines at `refs`."""
    values = [
        v for r in rows for s in r.values if s is not None
        for v in (s.mean, s.lo, s.hi) if v is not None]
    span = domain(values, min(refs), max(refs))
    top = 38.0
    centres, bottom = stacked([r.group for r in rows], top)
    x = scale(span[0], span[1], LABEL, PANEL - 14)
    out = [text(0, 13, heading, "head"), *grid(x, span, top - 6, bottom, refs)]
    for row, cy in zip(rows, centres, strict=True):
        marks = []
        for i, s in enumerate(row.values):
            if s is None:
                continue
            dy = 0.0 if len(row.values) == 1 else (-4.0 if i == 0 else 4.0)
            if s.lo is not None and s.hi is not None:
                marks.append(line(x(s.lo), cy + dy, x(s.hi), cy + dy, "range"))
            marks.append("<circle cx='%.1f' cy='%.1f' r='4.5' class='%s'/>"
                         % (x(s.mean), cy + dy, "dot" if i == 0 else "hollow"))
        out += [row_label(LABEL - 8, cy, row.label),
                "<g class='fam %s'><title>%s</title>%s</g>" % (row.css, esc(row.tip),
                                                              "".join(marks))]
    return frame(PANEL, bottom + 10, "".join(out), heading)


# --- diverging stacked bars -------------------------------------------------------------------

class Part(NamedTuple):
    """One part of a stacked bar: its name and the class that colours it."""
    label: str
    css: str


class BarRow(NamedTuple):
    """A row's bar: its label, its group, a value a part and its tooltip."""
    label: str
    group: str
    values: tuple[float, ...]
    tip: str


def bars(rows: Sequence[BarRow], parts: Sequence[Part], heading: str) -> str:
    """A row a bar of parts from 0 - a gain stacked right, a loss left, a
    2 px gap between two segments - and a tick at their sum."""
    values = [s for r in rows for s in (sum(v for v in r.values if v > 0),
                                        sum(v for v in r.values if v < 0))]
    span = domain(values, 0.0, 100.0)
    top = 38.0
    centres, bottom = stacked([r.group for r in rows], top)
    x = scale(span[0], span[1], LABEL, PANEL - 14)
    out = [text(0, 13, heading, "head"), *grid(x, span, top - 6, bottom, (0.0, 100.0))]
    for row, cy in zip(rows, centres, strict=True):
        segments, up, down = [], 0.0, 0.0
        for part, value in zip(parts, row.values, strict=True):
            if value > 0:
                x0, x1, up = x(up), x(up + value), up + value
            elif value < 0:
                x0, x1, down = x(down + value), x(down), down + value
            else:
                continue
            width = x1 - x0 - 2.0
            if width > 0:
                segments.append("<rect x='%.1f' y='%.1f' width='%.1f' height='12' class='%s'/>"
                                % (x0 + (2.0 if value < 0 else 0.0), cy - 6, width, part.css))
        total = x(sum(row.values))
        out += [row_label(LABEL - 8, cy, row.label),
                "<g><title>%s</title>%s%s</g>" % (esc(row.tip), "".join(segments),
                                                  line(total, cy - 9, total, cy + 9, "total"))]
    return frame(PANEL, bottom + 10, "".join(out), heading)


# --- a scatter --------------------------------------------------------------------------------

class Point(NamedTuple):
    """A point: its label, the class that colours it, where it sits on
    each axis with its ranges, its tooltip, and whether it is the one the
    chart is about, drawn larger."""
    label: str
    css: str
    x: Stat
    y: Stat
    tip: str
    lead: bool = False


def scatter(points: Sequence[Point], heading: str, x_name: str, y_name: str) -> str:
    """Points on two 0 to 100 axes, the lines at 50 stronger, each point
    with its ranges across and up; the points drawn in the order given, the
    last on top, and labelled in the reverse order, the one on top first,
    where a label fits."""
    height = 340.0
    left, right, top, bottom = 46.0, PANEL - 12.0, 26.0, height - 46.0
    x, y = scale(0, 100, left, right), scale(0, 100, bottom, top)
    out = [text(0, 13, heading, "head")]
    for tick in (0.0, 25.0, 50.0, 75.0, 100.0):
        cls = "ref" if tick == 50.0 else "grid"
        out += [line(x(tick), top, x(tick), bottom, cls), line(left, y(tick), right, y(tick), cls),
                text(x(tick), bottom + 14, tick_text(tick), "tick", "middle"),
                text(left - 6, y(tick) + 4, tick_text(tick), "tick", "end")]
    out += [text((left + right) / 2, height - 8, x_name, "tick", "middle"),
            "<text x='12' y='%.1f' class='tick' text-anchor='middle'"
            " transform='rotate(-90 12 %.1f)'>%s</text>"
            % ((top + bottom) / 2, (top + bottom) / 2, esc(y_name))]
    for p in points:
        cx, cy = x(p.x.mean), y(p.y.mean)
        marks = []
        if p.x.lo is not None and p.x.hi is not None:
            marks.append(line(x(p.x.lo), cy, x(p.x.hi), cy, "range"))
        if p.y.lo is not None and p.y.hi is not None:
            marks.append(line(cx, y(p.y.lo), cx, y(p.y.hi), "range"))
        marks.append("<circle cx='%.1f' cy='%.1f' r='%d' class='dot'/>"
                     % (cx, cy, 7 if p.lead else 5))
        out.append("<g class='fam %s'><title>%s</title>%s</g>" % (p.css, esc(p.tip),
                                                                 "".join(marks)))
    centres = [(x(p.x.mean), y(p.y.mean)) for p in points]
    labels = [(cx, cy, cut(p.label, 26)) for (cx, cy), p in zip(centres, points, strict=True)]
    out += placed(labels[::-1], centres, (4.0, top - 8.0, PANEL - 2.0, bottom - 2.0))
    return frame(PANEL, height, "".join(out), heading)


# --- a heatmap --------------------------------------------------------------------------------

class HeatColumn(NamedTuple):
    """A column: its name, its group - a group's columns sit together under
    its name - and whether a bar under it marks it."""
    name: str
    group: str
    marked: bool


class HeatRow(NamedTuple):
    """A row: its label and the address it links - none where empty - and
    per column a share for the cell's fill and a share for its dot, with
    the cell's tooltip."""
    label: str
    href: str
    cells: tuple[tuple[float, float], ...]
    tips: tuple[str, ...]


def heatmap(rows: Sequence[HeatRow], columns: Sequence[HeatColumn], name: str) -> str:
    """A row a line of cells: each cell's fill as strong as its first share
    and a dot as large as its second, the columns grouped under their
    groups' names and their own names under the grid."""
    label, cell, step, apart, top = 236.0, 13.0, 15.0, 10.0, 32.0
    xs, x, previous = [], label, None
    for column in columns:
        if previous is not None and column.group != previous:
            x += apart
        xs.append(x)
        x += step
        previous = column.group
    floor = top + step * len(rows)
    out = []
    for group in dict.fromkeys(c.group for c in columns):
        at = [xx for xx, c in zip(xs, columns, strict=True) if c.group == group]
        out += [text((at[0] + at[-1] + cell) / 2, top - 14, group, "tick", "middle"),
                line(at[0], top - 9, at[-1] + cell, top - 9, "ref")]
    for i, row in enumerate(rows):
        y = top + i * step
        name = text(label - 8, y + cell - 3, cut(row.label, 38), "lab", "end")
        out.append("<a href='%s'>%s</a>" % (esc(row.href), name) if row.href else name)
        for xx, (fill, dot), tip in zip(xs, row.cells, row.tips, strict=True):
            marks = ["<rect x='%.1f' y='%.1f' width='%.0f' height='%.0f' class='cell0'/>"
                     % (xx, y, cell, cell)]
            if fill > 0:
                marks.append("<rect x='%.1f' y='%.1f' width='%.0f' height='%.0f' class='cell'"
                             " fill-opacity='%.2f'/>" % (xx, y, cell, cell,
                                                         min(1.0, 0.12 + 0.88 * fill)))
            if dot > 0:
                marks.append("<circle cx='%.1f' cy='%.1f' r='%.1f' class='moved'/>" % (
                    xx + cell / 2, y + cell / 2, 1.3 + 3.7 * math.sqrt(min(1.0, dot))))
            out.append("<g><title>%s</title>%s</g>" % (esc(tip), "".join(marks)))
    for xx, column in zip(xs, columns, strict=True):
        cx, cy = xx + cell / 2 + 3, floor + 12
        if column.marked:
            out.append("<rect x='%.1f' y='%.1f' width='%.0f' height='3' class='testmark'/>"
                       % (xx, floor + 1, cell))
        out.append("<text x='%.1f' y='%.1f' class='tick' text-anchor='end'"
                   " transform='rotate(-60 %.1f %.1f)'>%s</text>"
                   % (cx, cy, cx, cy, esc(cut(column.name, 20))))
    return frame(x + 8.0, floor + 128.0, "".join(out), name, keep=True)


# --- a funnel on a log scale ------------------------------------------------------------------

class Stage(NamedTuple):
    """A stage of the funnel: its label, its quantiles - the median the
    bar, p10 to p90 the whisker - and each board's value, a faint dot."""
    label: str
    quantiles: Mapping[str, float]
    each: tuple[float, ...]


POWERS = ("1", "10", "100", "1k", "10k", "100k", "1M", "10M", "100M", "1G")


def funnel(stages: Sequence[Stage], heading: str) -> str:
    """A bar a stage on a log scale from 1: the median, its whisker and each
    value a faint dot under it - one dot where values fall on one spot -
    the median written at the bar's end."""
    biggest = max(max([*s.quantiles.values(), *s.each, 1.0]) for s in stages)
    powers = max(1, math.ceil(math.log10(max(biggest, 10.0))))
    left, right, top = 118.0, PANEL - 64.0, 44.0
    x = scale(0, powers, left, right)

    def at(value: float) -> float:
        return x(math.log10(max(1.0, value)))
    bottom = top + 34.0 * len(stages)
    out = [text(0, 13, heading, "head")]
    for power in range(powers + 1):
        out += [line(x(power), top - 6, x(power), bottom, "grid"),
                text(x(power), top - 12, POWERS[power] if power < len(POWERS)
                     else "1e%d" % power, "tick", "middle")]
    for i, stage in enumerate(stages):
        cy = top + 34.0 * i + 15.0
        median = stage.quantiles.get("median", 1.0)
        out += [text(left - 8, cy + 4, stage.label, "lab", "end"),
                "<rect x='%.1f' y='%.1f' width='%.1f' height='14' class='bar'/>"
                % (left, cy - 7, max(1.0, at(median) - left))]
        out += ["<circle cx='%s' cy='%.1f' r='2.2' class='faint'/>" % (spot, cy + 12)
                for spot in dict.fromkeys("%.1f" % at(v) for v in stage.each)]
        if "p10" in stage.quantiles and "p90" in stage.quantiles:
            out.append(line(at(stage.quantiles["p10"]), cy, at(stage.quantiles["p90"]), cy,
                            "whisk"))
        end = max(at(median), at(stage.quantiles.get("p90", median)))
        out.append(text(end + 6, cy + 4, format(round(median), ","), "val"))
    return frame(PANEL, bottom + 8, "".join(out), heading)
