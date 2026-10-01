"""The strategies catalog: the playbook in force read from its folder,
each file parsed (inference.frontmatter) and checked (inference.strategy)
into a Strategy, the whole ordered, mirrored into the `strategies` table
under its own `sources` row (AUTHORED) and written into
docs/inference.md; the default engine's weights, which meta.md beside the
strategy files holds (read_meta); and what reads the playbook as a whole -
the weights one board overrides, the count per kind, the playbook's name
and digest.

    ---
    meta: 1
    rate: 1
    synergy: 0.26
    counter: 0.05
    swap: 10
    ---
    prose: what the weights do and why they are set so

meta.md sets the four weights, each a number within the weight range
(strategy.WEIGHT_RANGE), and the swap cost (base.SWAP), in share points
within base.SWAP_RANGE, and nothing else; every playbook folder holds one:
a board, an infer and the math page read it, and a folder without it is a
CatalogError. The swap cost is the one field a folder may leave out: it
reads the shipped meta.md's (read_meta), which must set it. It is no
strategy - the catalog never loads it as one, the digest leaves it out (a
fixture's stamp, inference.base.stamp, records the weights) and no
strategy may take its name, nor the swap cost's (RESERVED).
"""

import copy
import hashlib
import os
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import NamedTuple, NotRequired, TypedDict

import psycopg

from db import ROOT, Refusal, Source, embed
from db.psql import now, register_source
from facts import compute
from facts.team_facts import counted
from inference.base import DIALS, FIELDS, META, SWAP, SWAP_RANGE, BaseRecord, BaseWeights
from inference.frontmatter import FrontmatterError, parse_frontmatter
from inference.strategy import (
    FORMS,
    KINDS,
    WEIGHT_RANGE,
    CatalogError,
    Strategy,
    field_text,
    finite_number,
)

SHIPPED_DIR = os.path.join(ROOT, "inference", "strategies")
# The sources row of the one input a user writes: the strategies, mirrored
# here. Nothing is downloaded: the "url" is the playbook's folder. No other
# table may carry this source.
AUTHORED = Source(code="user", name="The user: the playbook", url="inference/strategies/")

# the id is the filename, so no id may name a path (docs/security.md)
ID_RE = re.compile(r"[a-z0-9][a-z0-9-]*\Z")


def strategies_dir() -> str:
    """The playbook in force: the shipped one, unless COUNTRIX_STRATEGIES
    names another folder - a path relative to the repo root or absolute. Read
    where it is needed rather than snapshotted at import, so the setting means
    what it says and no module can freeze it before another reads it."""
    chosen = os.environ.get("COUNTRIX_STRATEGIES", "").strip()
    return os.path.abspath(os.path.join(ROOT, chosen)) if chosen else SHIPPED_DIR


DOCS_PATH = os.path.join(ROOT, "docs", "inference.md")
META_FILE = META + ".md"            # the default engine's weights, beside the strategy files
# markdown that lives beside the files
NOT_STRATEGIES = ("README.md", "tuning-log.md", META_FILE)
# the ids no strategy may take: meta.md's name and the swap cost's, each a key
# of a board's weights beside the heuristics' ids
RESERVED = (META, SWAP)


def _read(directory: str, name: str) -> Strategy:
    """One strategy file, validated; any failure is a CatalogError naming the
    file."""
    sid = name[:-3]                       # the id IS the filename; nothing overrides it
    try:
        if not ID_RE.fullmatch(sid):
            raise CatalogError("%s: the filename must be lowercase-kebab" % name)
        if sid in RESERVED:
            raise CatalogError("%s: %s is %s's and no strategy's" % (name, sid, META_FILE))
        with open(os.path.join(directory, name), encoding="utf-8") as handle:
            parsed = parse_frontmatter(handle.read())
        if "id" in parsed.meta and str(parsed.meta["id"]) != sid:
            raise CatalogError("%s: id: is the filename; drop it" % name)
        return Strategy(sid, parsed.meta, body=parsed.body)
    except (CatalogError, FrontmatterError) as error:
        text = str(error)
        raise CatalogError(
            text if text.startswith((name, sid)) else "%s: %s" % (name, text)) from error
    except Exception as error:            # bytes that are not text, a directory, ...
        raise CatalogError("%s: %s: %s" % (name, type(error).__name__, error)) from error


def strategy_files(directory: str) -> list[str]:
    """The names of a playbook's strategy files, sorted: its .md files less
    the markdown that lives beside them. Everything that copies, reads or
    fingerprints a playbook takes its files from here."""
    if not os.path.isdir(directory):
        raise CatalogError("no strategies directory at %s" % directory)
    return sorted(name for name in os.listdir(directory)
                  if name.endswith(".md") and name not in NOT_STRATEGIES)


def load(directory: str | None = None) -> list[Strategy]:
    """Every strategy file, validated, ordered constraints (limits), then
    heuristics (on a metric, then scored), then assumptions; drafts sit last
    within their kind."""
    directory = directory or strategies_dir()
    out = [_read(directory, name) for name in strategy_files(directory)]
    if not out:
        raise CatalogError("no strategies in %s" % directory)
    out.sort(key=lambda s: (KINDS.index(s.kind), FORMS.index(s.form), s.category, s.id))
    return out


class Meta(NamedTuple):
    """meta.md, read: the default engine's weights, the swap cost - None
    where the file leaves it out and nothing has seeded it (parse_meta) -
    and the prose that says what they do and why."""
    weights: BaseWeights
    swap: float | None
    body: str


class MetaRecord(BaseRecord):
    """meta.md as the tools and the board serve it: the weights, the swap
    cost and the prose."""
    swap: float | None
    body: str


def meta_dial(field: str, value: object) -> float:
    """One of meta.md's fields: a weight a finite number within
    WEIGHT_RANGE, the swap cost one within SWAP_RANGE, else a CatalogError
    with the rule. The reader and the tune tool both check a value by it."""
    if field not in FIELDS:
        raise CatalogError("%s's fields are %s" % (META_FILE, ", ".join(FIELDS)))
    low, high = SWAP_RANGE if field == SWAP else WEIGHT_RANGE
    number = finite_number(value)
    if number is None or not low <= number <= high:
        raise CatalogError("%s is a number within %g..%g" % (field, low, high))
    return number


def parse_meta(text: str) -> Meta:
    """meta.md's text -> its weights, swap cost and prose: the four weights
    set, each by meta_dial, the swap cost where the file sets it, and no
    other key; else a CatalogError naming the file."""
    try:
        parsed = parse_frontmatter(text)
        unknown = sorted(str(key) for key in parsed.meta if key not in FIELDS)
        if unknown:
            raise CatalogError("%s is not a field (the fields: %s)"
                               % (", ".join(unknown), ", ".join(FIELDS)))
        missing = [field for field in DIALS if parsed.meta.get(field) is None]
        if missing:
            raise CatalogError("%s unset: it sets %s" % (", ".join(missing), ", ".join(DIALS)))
        dials = {field: meta_dial(field, parsed.meta[field]) for field in DIALS}
        swap = parsed.meta.get(SWAP)
        cost = None if swap is None else meta_dial(SWAP, swap)
    except (CatalogError, FrontmatterError) as error:
        raise CatalogError("%s: %s" % (META_FILE, error)) from error
    return Meta(weights=BaseWeights(**dials), swap=cost, body=parsed.body)


def _meta_file(directory: str) -> Meta:
    """The meta.md in `directory`, parsed; a folder without one is a
    CatalogError: the default engine has no weights there."""
    try:
        with open(os.path.join(directory, META_FILE), encoding="utf-8") as handle:
            text = handle.read()
    except FileNotFoundError as error:
        raise CatalogError("%s: missing - the playbook's folder holds the default engine's"
                           " weights there" % META_FILE) from error
    return parse_meta(text)


def read_meta(directory: str | None = None) -> Meta:
    """The playbook's meta.md - the playbook in force's unless `directory`
    names another - read and checked, its swap cost seeded from the shipped
    meta.md's where it sets none: a folder written before the dial existed
    reads the shipped cost. The shipped file without one is a CatalogError."""
    meta = _meta_file(directory or strategies_dir())
    if meta.swap is None:
        shipped = _meta_file(SHIPPED_DIR).swap
        if shipped is None:
            raise CatalogError("%s: %s unset - the shipped %s sets the swap cost"
                               % (META_FILE, SWAP, META_FILE))
        meta = meta._replace(swap=shipped)
    return meta


def engine_weights(directory: str | None = None) -> BaseWeights:
    """The default engine's weights in force: meta.md's (read_meta)."""
    return read_meta(directory).weights


def swap_cost(directory: str | None = None) -> float:
    """The swap cost in force, in share points: meta.md's, else the shipped
    meta.md's (read_meta)."""
    return read_meta(directory).swap or 0.0


def meta_record(meta: Meta) -> MetaRecord:
    """meta.md as the strategies tool and the board's playbook tab serve it."""
    return MetaRecord(**meta.weights.record(), swap=meta.swap, body=meta.body)


def meta_rendered(weights: BaseWeights, swap: float | None = None) -> str:
    """The weights as one line of text: the meta, and each dial under it,
    then the swap cost where one is given."""
    line = "meta %s x (rate %s, synergy %s, counter %s)" % tuple(
        field_text(getattr(weights, field)) for field in DIALS)
    return line if swap is None else "%s; swap cost %s" % (line, field_text(swap))


def parse_weights(items: Mapping[str, object] | Iterable[object] | None) -> dict[str, float]:
    """`id:value` strings (a query's repeated `weights` parameter) or a mapping
    -> {id: weight}, each clamped to the file's WEIGHT_RANGE, the swap cost
    to SWAP_RANGE. What a board's sliders send: a heuristic's id, META for
    the default engine's meta (BaseWeights.metered), or SWAP for the swap
    cost (engine.swap_in_force). An entry that is not id:value, or a value that
    is not a finite number (strategy.finite_number: nan and inf are not), is
    a Refusal, which the board and the board tool answer as the caller's
    error."""
    if isinstance(items, Mapping):
        pairs = [(str(sid), value) for sid, value in items.items()]
    else:
        pairs = [_weight_entry(item) for item in items or []]
    out = {}
    for sid, value in pairs:
        weight = finite_number(value)
        if weight is None:
            raise Refusal("weight %r for %r is not a number" % (value, sid))
        low, high = SWAP_RANGE if sid.strip() == SWAP else WEIGHT_RANGE
        out[sid.strip()] = min(high, max(low, weight))
    return out


def _weight_entry(item: object) -> tuple[str, object]:
    """One `id:value` string -> (id, value)."""
    sid, colon, value = str(item).partition(":")
    if not colon:
        raise Refusal("a weight is id:value, got %r" % item)
    return sid, value


def weighted(catalog: list[Strategy], weights: Mapping[str, float] | None) -> list[Strategy]:
    """The catalog with the heuristics named in `weights` carrying those
    weights instead of their files' - shallow copies, so the files and the
    loaded catalog stay as they are. Only a heuristic has a weight to set -
    on a metric or scored alike; a constraint has none, and an unknown id is
    ignored, META and SWAP among them: the meta is the engine's
    (BaseWeights.metered), the swap cost the swap search's."""
    if not weights:
        return catalog
    out = []
    for s in catalog:
        if s.kind == "heuristic" and s.id in weights and s.weight != weights[s.id]:
            s = copy.copy(s)
            s.weight = weights[s.id]
        out.append(s)
    return out


class KindCounts(TypedDict):
    """Strategies per kind, in KINDS order."""
    constraint: int
    heuristic: int
    assumption: int


def counts(catalog: Iterable[Strategy]) -> KindCounts:
    """Strategies per kind: {"constraint": n, "heuristic": n, "assumption": n}."""
    kinds = [s.kind for s in catalog]
    return KindCounts(constraint=kinds.count("constraint"), heuristic=kinds.count("heuristic"),
                      assumption=kinds.count("assumption"))


def playbook_name(directory: str | None = None) -> str:
    """How the database names a playbook: its folder, relative to the repo."""
    return os.path.relpath(directory or strategies_dir(), ROOT).replace(os.sep, "/")


def playbook_digest(directory: str | None = None) -> str:
    """The playbook's fingerprint: a sha256 over its strategy files in
    strategy_files order, each name and then its bytes. A fixture recorded
    under a playbook records this value, so a test can tell the playbook it
    was recorded under from the one in force. README.md and tuning-log.md
    never move it."""
    directory = directory or strategies_dir()
    digest = hashlib.sha256()
    for name in strategy_files(directory):
        digest.update(name.encode("utf-8") + b"\0")
        with open(os.path.join(directory, name), "rb") as handle:
            digest.update(handle.read() + b"\0")
    return digest.hexdigest()


class MirrorSummary(KindCounts):
    """What a mirror loaded: the strategies per kind, the total and the table
    it wrote; load_authored adds how many are drafts."""
    total: int
    tables: list[str]
    pending: NotRequired[int]


def mirror(cx: psycopg.Connection, catalog: Sequence[Strategy]) -> MirrorSummary:
    """Reload the strategies table from the files (whole truth), each row
    naming the playbook in force."""
    cursor = cx.cursor()
    source_id = register_source(cursor, AUTHORED, now())
    cursor.execute("DELETE FROM strategies")
    for s in catalog:
        cursor.execute(
            "INSERT INTO strategies (strategy_id, name, kind, category,"
            " direction, metric, weight, expression, params, body, playbook, source_id)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                s.id, s.name, s.kind, s.category, s.direction, s.metric,
                s.weight if s.weighs else None, s.expressions or None,
                _params_line(s) or None, s.body, playbook_name(), source_id))
    cx.commit()
    return MirrorSummary(**counts(catalog), total=len(catalog), tables=["strategies"])


def _params_line(s: Strategy) -> str:
    """A strategy's params as NAME=value, by name."""
    return ", ".join("%s=%s" % (name, s.params[name]) for name in sorted(s.params))


def catalog_rendered(catalog: Iterable[Strategy]) -> str:
    """The catalog as text, one line per strategy: kind, form, id, category and
    what it holds or weighs - the `strategies` tool's reply."""
    lines = []
    for s in catalog:
        head = "%-10s %-10s %-28s %-9s" % (s.kind, s.form, s.id, s.category)
        if s.form == "heuristic":
            head += " %s %s x%g%s" % (s.direction, s.metric, s.weight, " need" if s.need else "")
        elif s.form == "limit":
            head += " %s" % s.expressions
        elif s.form == "scored":
            head += " %s x%g" % (s.expressions, s.weight)
        elif s.form == "draft":
            head += " (draft: name, kind and prose only - /strategy infers the rest)"
        lines.append(head)
    return "\n".join(lines)


def _form_line(s: Strategy, reg: Mapping[str, str]) -> str:
    """The line under a strategy's heading in the docs: what it weighs, by form."""
    when = "; when `%s`" % s.when.source if s.when else ""
    if s.form == "heuristic":
        return "`%s %s` - %s. weight %g%s%s" % (
            s.direction, s.metric, reg.get(s.metric or "", ""), s.weight,
            ", a need" if s.need else "", when)
    if s.form == "limit":
        # a limit has require: and nothing else (Strategy._check_kind)
        return "`require %s` - always holds" % (s.require.source if s.require else "")
    if s.form == "draft":
        return "*draft* - name, kind and prose only; `/strategy` infers the rest"
    if s.form == "assumption":
        return "*assumption* - prose the solver takes as given and the session holds a comp to"
    return "weight %g; %s" % (s.weight, "; ".join(
        "%s `%s`" % (label, expr.source) for label, expr in (
            ("when", s.when), ("bonus", s.bonus), ("penalty", s.penalty))
        if expr is not None))


def _without_title(body: str) -> str:
    """The prose without its title line: the docs' heading names the strategy."""
    first, newline, rest = body.partition("\n")
    return rest.lstrip("\n") if first.startswith("#") and newline else body


def write_docs(catalog: Sequence[Strategy], path: str = DOCS_PATH) -> str | None:
    """The catalog and the vocabulary, generated into docs/inference.md
    between its <!-- generated:catalog --> markers - from the shipped
    playbook only: while another folder is in force the docs keep describing
    the shipped one, and this returns None."""
    if strategies_dir() != SHIPPED_DIR:
        return None
    meta = read_meta(SHIPPED_DIR)
    kinds = counts(catalog)
    forms = {f: sum(1 for s in catalog if s.form == f) for f in FORMS}
    reg = compute.registry()
    out = [
        "%s in `inference/strategies/`: %s (%s), %s (%d on a metric, %d scored) and %s%s."
        " Regenerated by `.venv/bin/python -m door.mcp call db_docs`."
        % (
            counted(len(catalog), "strategy file"), counted(kinds["constraint"], "constraint"),
            "a limit" if kinds["constraint"] == 1 else "limits",
            counted(kinds["heuristic"], "heuristic"), forms["heuristic"], forms["scored"],
            counted(kinds["assumption"], "assumption"),
            "; %d draft(s) awaiting /strategy" % forms["draft"] if forms["draft"] else ""),
        "", "#### The meta", "",
        "`%s`: %s - the default engine's weights, which the tune tool changes (id `%s`)"
        % (META_FILE, meta_rendered(meta.weights, meta.swap), META),
        "", _without_title(meta.body), ""]
    for kind in KINDS:
        items = [s for s in catalog if s.kind == kind]
        if not items:
            continue
        out += ["#### %ss" % kind.capitalize(), ""]
        for s in items:
            out.append("##### %s (`%s`, %s%s)" % (
                s.name, s.id, s.category, ", %s" % s.form if s.form != s.kind else ""))
            out += ["", _form_line(s, reg)]
            if s.params:
                out.append("params: " + _params_line(s))
            out += ["", _without_title(s.body), ""]
    out += ["#### The vocabulary", "",
            "Every key a strategy may reference, with its meaning. `enemy.*` are",
            "the `team.*` metrics computed for the red side.", "",
            "| key | meaning |", "| --- | --- |"]
    for key, description in reg.items():
        if key.startswith("enemy."):
            continue
        out.append("| `%s`%s | %s |" % (key, " (text)" if key in compute.TEXT_METRICS
                                        else "", description))
    embed(path, "catalog", "\n".join(out))
    return path
