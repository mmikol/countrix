"""The playbook through the door: the metric vocabulary a strategy may
reference, the catalog and the default engine's weights, the tools that
write a strategy file or meta.md - tune, add_strategy, infer_strategy - and
the tuning log.

Every write opens the database before it changes anything, so a database
out of reach fails the call with every file as it was. The write then
validates through the catalog, rewrites the docs catalog for the shipped
playbook and logs a reasoned line (inference.tune does all three), and
reloads the strategies table from the files on that connection
(_remirror): the database half of the write, and the one step this module
adds. The frontmatter fields the writes take are declared from
inference.strategy.FIELDS, the rule that checks them, so the door admits
what a file may hold.
"""

import os

import psycopg

from db import ROOT, Refusal
from door.mcp.registry import Context, tool
from door.mcp.schema import Properties, Property, ToolReply
from facts import compute
from inference import base, catalog, tune
from inference.base import META, SWAP_RANGE
from inference.strategy import FIELDS, TUNABLE, WEIGHT_RANGE, Field, FieldKind


@tool(
    "metrics", "The vocabulary a strategy may reference: every metric key with its"
    " meaning - team.*, enemy.* (the same for the red side), matchup.*, map.*,"
    " world.* - and which are text. What /strategy reads to infer a heuristic's"
    " metric or expression, or a constraint's limit, from prose.")
def metrics(ctx: Context) -> ToolReply:
    reg = compute.registry()
    numeric = {k: v for k, v in reg.items() if k not in compute.TEXT_METRICS}
    lines = [
        "%-32s %s%s" % (k, v, "  (text)" if k in compute.TEXT_METRICS else "")
        for k, v in reg.items() if not k.startswith("enemy.")]
    return ToolReply("\n".join(lines), {"metrics": reg, "numeric": sorted(numeric),
                                        "text": sorted(compute.TEXT_METRICS)})


@tool(
    "strategies", "The inference layer's catalog - STRATEGIES = CONSTRAINTS ∪ HEURISTICS"
    " ∪ ASSUMPTIONS: every markdown strategy with its kind (constraint, heuristic or"
    " assumption), its form (a constraint's limit; a heuristic on a metric, or scored on"
    " bonus/penalty; draft), metric, direction, weight and expressions - and, first,"
    " meta.md: the default engine's weights, the meta that scales it and its rate,"
    " synergy and counter dials, and the swap cost.")
def strategies(ctx: Context) -> ToolReply:
    cat = catalog.load()
    meta = catalog.read_meta()
    pending = [s.id for s in cat if s.pending]
    text = "%-10s %-10s %-28s %s\n%s" % (
        "engine", "meta", META, catalog.meta_rendered(meta.weights, meta.swap),
        catalog.catalog_rendered(cat))
    if catalog.strategies_dir() != catalog.SHIPPED_DIR:
        text = "playbook in force: %s (the shipped one is %s)\n\n%s" % (
            os.path.relpath(catalog.strategies_dir(), ROOT),
            os.path.relpath(catalog.SHIPPED_DIR, ROOT), text)
    if pending:
        text += "\n\n%d draft(s) awaiting /strategy: %s" % (len(pending), ", ".join(pending))
    return ToolReply(text, {"strategies": [s.to_dict() for s in cat],
                            "meta": catalog.meta_record(meta), "pending": pending})


# the JSON schema type the door declares for each kind of frontmatter field:
# an expression may be a bare number, as a flat penalty is
KIND_TYPES: dict[FieldKind, str | list[str]] = {
    "line": "string", "choice": "string", "number": "number",
    "expression": ["string", "number"], "params": "object"}


def _property(field: Field) -> Property:
    """A frontmatter field as the door declares it, from the rule that checks
    it (strategy.FIELDS): its kind's JSON type, a choice's enum and its
    meaning."""
    prop = Property(type=KIND_TYPES[field.kind], description=field.meaning)
    if field.choices:
        prop["enum"] = list(field.choices)
    return prop


# the fields add_strategy and infer_strategy take beside a strategy's name and kind
STRATEGY_FIELDS: Properties = {
    name: _property(field) for name, field in FIELDS.items() if name not in ("name", "kind")}


# who asked, for the log line: the three writers take it alike, so a
# caller names itself whichever it calls
BY: Properties = {
    "by": {"type": "string", "description": "who asked, for the log line (default %s)"
                                           % tune.BY_SESSION}}


def _remirror(cx: psycopg.Connection) -> None:
    """A playbook write's database half: the strategies table reloaded from
    the files the write changed, on the connection its tool opened before
    the write."""
    catalog.mirror(cx, catalog.load())


@tool(
    "tune", "Change one strategy's frontmatter - its weight, a params dial, or"
    " a when/require/bonus/penalty expression - or its prose, body, rewritten"
    " whole within three sentences under its title - or, with id meta, meta.md: one"
    " of the default engine's weights - meta, which scales the whole engine"
    " (0 turns it off), or its rate, synergy or counter dial - or the swap"
    " cost, swap, in share points of blue's span: what a swap of one of blue's"
    " picks must gain before the board suggests it - or its prose,"
    " body, rewritten whole. A playbook folder with no meta.md is seeded from"
    " the shipped one's. Validated through the catalog before it is written,"
    " the strategies re-mirrored into the database (meta.md's weights live in"
    " the file alone), and logged with the reason in the tuning-log.md beside"
    " the playbook.",
    {
        "id": {
            "type": "string",
            "description": "the strategy's id (its filename), or %s for meta.md" % META},
        "field": {
            "type": "string",
            "description": "%s; for id %s: %s" % (
                " | ".join((*TUNABLE, "params.NAME", tune.META_PROSE)), META,
                " | ".join((*base.FIELDS, tune.META_PROSE)))},
        "value": {"description": "the new value: a number, a word (kind, category, metric,"
                                 " direction) or an expression; meta.md's weights are"
                                 " numbers within %g..%g, its swap cost one within"
                                 " %g..%g, its body the prose in markdown"
                                 % (*WEIGHT_RANGE, *SWAP_RANGE)},
        "reason": {"type": "string", "description": "why, in a sentence"},
        **BY},
    ["id", "field", "value", "reason"])
def tune_tool(      # _tool: inference.tune holds the bare name
        ctx: Context, id: str, field: str, value: object, reason: str,
        by: str = tune.BY_SESSION) -> ToolReply:
    with ctx.connect() as cx:
        change = tune.tune(id, field, value, reason, by=by)
        _remirror(cx)
    return ToolReply("tuned %s: %s %s -> %s\n%s" % (
        change["id"], change["field"], change["old"], change["new"], change["line"]), change)


@tool(
    "add_strategy", "Store a new strategy in inference/strategies/ from its name,"
    " kind and prose plus the frontmatter /strategy inferred - a constraint's"
    " require, a limit that always holds and is never weighted; a heuristic's"
    " metric/direction/weight, or its when/bonus/penalty and weight; params for"
    " either. An assumption is prose and needs nothing. The prose is three"
    " sentences at most. Validated through the"
    " catalog before the file exists, mirrored into the database, logged."
    " Left with nothing inferred it lands as a draft the solver ignores.",
    {
        "id": {"type": "string", "description": "lowercase-kebab, becomes the filename"},
        "name": _property(FIELDS["name"]),
        "kind": _property(FIELDS["kind"]),
        "body": {"type": "string", "description": "the prose: what it means and why"},
        "reason": {"type": "string", "description": "why it was added, in a sentence"},
        **BY, **STRATEGY_FIELDS},
    ["id", "name", "kind", "body", "reason"])
def add_strategy(
        ctx: Context, id: str, name: str, kind: str, body: str, reason: str,
        by: str = tune.BY_SESSION, **fields: object) -> ToolReply:
    with ctx.connect() as cx:
        added = tune.add(id, name, kind, body, fields, reason, by=by)
        _remirror(cx)
    note = ("\nstored as a DRAFT: the solver ignores it until /strategy infers its frontmatter"
            if added["form"] == "draft" else "")
    return ToolReply("added %s as %s/%s -> %s\n%s%s" % (
        id, kind, added["form"], os.path.relpath(added["path"], ROOT), added["line"], note),
        added)


@tool(
    "infer_strategy", "Complete a draft (or rewrite a strategy's scoring): set several"
    " frontmatter fields at once - a constraint's require; a heuristic's"
    " metric/direction/weight or when/bonus/penalty/weight; params - and remove the"
    " ones `unset` names, validated as a whole, mirrored, logged as one line.",
    {
        "id": {"type": "string"},
        "reason": {"type": "string", "description": "how the fields follow from the prose"},
        "unset": {"type": "array", "items": {"type": "string"},
                  "description": "fields to remove, or params.NAME: a heuristic moving from a"
                                 " metric to a bonus or penalty drops metric and direction"},
        **BY, **STRATEGY_FIELDS},
    ["id", "reason"])
def infer_strategy(
        ctx: Context, id: str, reason: str, by: str = tune.BY_SESSION,
        unset: list[str] | None = None, **fields: object) -> ToolReply:
    with ctx.connect() as cx:
        done = tune.complete(id, fields, reason, by=by, unset=unset or ())
        _remirror(cx)
    return ToolReply("%s is now %s: %s\n%s" % (id, done["form"], ", ".join(
        "%s=%s" % kv for kv in done["set"].items()), done["line"]), done)


@tool(
    "tuning_log", "The record of every change to the playbook's frontmatter -"
    " the strategies' and meta.md's - newest last.",
    {"lines": {"type": "integer", "description": "how many, 1 or more (default 20)"}})
def tuning_log(ctx: Context, lines: int = 20) -> ToolReply:
    if lines < 1:
        raise Refusal("lines is 1 or more")
    tail = tune.log_tail(lines)
    return ToolReply("\n".join(tail) or "no tuning yet", {"lines": tail})

