"""Tuning a strategy: an edit to its frontmatter, validated, written back
and logged with its reason. The `tune`, `add_strategy` and `infer_strategy`
tools mirror it into the database.

    tune("coverage", "weight", 3.5, "the solver kept leaving Pharah unanswered")
    tune("under-healed", "params.HEAL_MARGIN", 0.8, "two-support lines felt thin")
    tune("squish-limit", "penalty", "max(0, team.squish_count - 3) * 1.0", "...")

    add("shut-off-heals", "Shut off a heavy heal line", "heuristic", prose,
        {
            "when": "enemy.heal_ratio >= params.HEAL_RATIO",
            "bonus": "min(team.antiheal, 1) * 1.5", "params": {"HEAL_RATIO": 1.0}},
        "user: one anti-heal pick against a heavy heal line")
    complete("a-draft", {"metric": "team.dps_floor", "direction": "maximize",
                         "weight": 2}, "inferred from the prose")

Fields: kind, category, metric, direction, weight, when, require,
bonus, penalty (strategy.TUNABLE), params.NAME, and body, the prose
rewritten whole. Each value is checked as the loader checks a file, and
the edited file is loaded through the catalog before it is written
(_commit), so a refused change writes nothing. Every accepted change is
one line in tuning-log.md beside the playbook in force, a folder the
compose stack bind-mounts, so a change made in a container lands on the
host.

    tune("meta", "synergy", 0.2, "the wiki's pairs should count for more")
    tune("meta", "swap", 15, "a swap costs a fight's ultimate charge")
    tune("meta", "body", prose, "the synergy clause names the imputed cells")

The id `meta` names meta.md, the default engine's weights (_tune_meta):
its dials and the swap cost (base.FIELDS) and its body. A playbook folder
with no meta.md is seeded from the shipped one's by its first such
change, and no strategy may take the name (catalog.RESERVED).
"""

import functools
import os
import re
import shutil
import tempfile
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import TypedDict

from db import Refusal, write_whole
from inference import catalog as catalog_module
from inference.base import FIELDS, META
from inference.frontmatter import FrontmatterError, parse_frontmatter
from inference.strategy import (
    FIELD_RULE,
    TUNABLE,
    CatalogError,
    Form,
    LineValue,
    Strategy,
    checked_value,
    field_text,
)

MAX_PROSE = 20000          # characters in a strategy's prose, or meta.md's
PROSE_FIELD = "body"       # the prose, a strategy's or meta.md's, as tune names it
MAX_SENTENCES = 3          # a strategy's prose is three sentences at most
MAX_BY = 40                # characters of who asked, in a log line
BY_SESSION = "claude-code-session"    # who asked, when the caller does not say
_SENTENCE_END = re.compile(r"[.!?](?:[\"')\]`]*)(?:\s|$)")

type Pairs = Sequence[tuple[str, LineValue]]


class TuneError(Refusal):
    """A change the catalog or the field refuses: nothing is written."""


class Change(TypedDict):
    """What tune() changed: one field, its old and new text, the log line."""
    id: str
    field: str
    old: str | None
    new: str
    line: str


class Completion(TypedDict):
    """What complete() set: the form the strategy took, each field's text,
    and the fields it removed."""
    id: str
    form: Form
    set: dict[str, str]
    unset: list[str]
    line: str


class Addition(TypedDict):
    """What add() stored: the new file's form and path."""
    id: str
    form: Form
    path: str
    line: str


def _pairs(pairs: Pairs) -> str:
    return ", ".join("%s=%s" % (field, field_text(value)) for field, value in pairs)


# --- the frontmatter edit -------------------------------------------------------

def _header_end(lines: list[str]) -> int:
    """Where a new header line goes: the end, before a trailing blank line."""
    return len(lines) - (1 if lines and not lines[-1].strip() else 0)


def _params_block(lines: list[str]) -> int | None:
    """The index of the params: line, or None where the header has none."""
    return next((i for i, line in enumerate(lines) if line.strip() == "params:"), None)


def _dials(lines: list[str], block: int) -> range:
    """The indices of the dials under the params: line at `block`: the
    indented lines that follow it."""
    end = block + 1
    while end < len(lines) and lines[end][:1] in (" ", "\t"):
        end += 1
    return range(block + 1, end)


def _dial_at(lines: list[str], block: int, name: str) -> int | None:
    """The index of dial NAME under the params: line at `block`, or None."""
    for i in _dials(lines, block):
        if lines[i].strip().split(":")[0] == name:
            return i
    return None


def _field_at(lines: list[str], field: str) -> int | None:
    """The index of a flat field's line, one not indented, or None."""
    for i, line in enumerate(lines):
        if line[:1] not in (" ", "\t") and line.split(":")[0].strip() == field:
            return i
    return None


def _set_param(lines: list[str], name: str, value: LineValue) -> str | None:
    """NAME set under params:, the block added when there is none -> the old value."""
    block = _params_block(lines)
    if block is None:
        block = _header_end(lines)
        lines.insert(block, "params:")
    line = "  %s: %s" % (name, field_text(value))
    at = _dial_at(lines, block, name)
    if at is not None:
        old = lines[at].split(":", 1)[1].strip()
        lines[at] = line
        return old
    lines.insert(_dials(lines, block).stop, line)
    return None


def _set_scalar(lines: list[str], field: str, value: LineValue) -> str | None:
    """A flat field set in place, or added above params: -> the old value."""
    line = "%s: %s" % (field, field_text(value))
    at = _field_at(lines, field)
    if at is not None:
        old = lines[at].split(":", 1)[1].strip()
        lines[at] = line
        return old
    block = _params_block(lines)
    lines.insert(_header_end(lines) if block is None else block, line)
    return None


def _edited(
        text: str, edit: Callable[[list[str]], str | None]) -> tuple[str, str | None]:
    """The file's text with its frontmatter's lines changed by `edit` ->
    (new text, the old value `edit` returns)."""
    if not text.startswith("---"):
        raise TuneError("no frontmatter")
    end = text.find("\n---", 3)
    if end < 0:                       # find() gives -1, which slices from the tail
        raise TuneError("unterminated frontmatter")
    header, rest = text[3:end], text[end:]
    lines = header.split("\n")
    old = edit(lines)
    return "---" + "\n".join(lines) + rest, old


def edit_frontmatter(text: str, field: str, value: LineValue) -> tuple[str, str | None]:
    """The file's text with one frontmatter field set -> (new text, old
    value). The value is one _coerce passed, so it is one line, and the
    field is a tunable one or a params.NAME dial."""
    if field.startswith("params."):
        return _edited(text, lambda lines: _set_param(lines, field[len("params."):], value))
    if field in TUNABLE:
        return _edited(text, lambda lines: _set_scalar(lines, field, value))
    raise TuneError(FIELD_RULE)


def _trial_load(directory: str, strategy_id: str, new_text: str) -> list[Strategy]:
    """Load a copy of the catalog with this one file replaced; raise on error."""
    tmp = tempfile.mkdtemp(prefix="tune-")
    try:
        for name in catalog_module.strategy_files(directory):
            shutil.copy(os.path.join(directory, name), os.path.join(tmp, name))
        with open(os.path.join(tmp, strategy_id + ".md"), "w", encoding="utf-8") as handle:
            handle.write(new_text)
        return catalog_module.load(tmp)
    except CatalogError as error:
        raise TuneError(str(error)) from error
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _unset(lines: list[str], field: str) -> str | None:
    """A flat field, or params.NAME, removed -> its old value, None where it
    was not set; a params block left empty goes with its last dial."""
    if field.startswith("params."):
        block = _params_block(lines)
        if block is None:
            return None
        at = _dial_at(lines, block, field[len("params."):])
        if at is None:
            return None
        old = lines.pop(at).split(":", 1)[1].strip()
        if not _dials(lines, block):
            lines.pop(block)
        return old
    at = _field_at(lines, field)
    return None if at is None else lines.pop(at).split(":", 1)[1].strip()


# --- the values a field accepts -------------------------------------------------

def _coerce(field: str, value: object) -> LineValue:
    """The value a field accepts, by the rule the loader keeps too
    (strategy.checked_value), or a TuneError. A writer sets one line at a
    time: the params block arrives as params.NAME dials (_flatten), and a
    bare params is refused as edit_frontmatter refuses it."""
    try:
        checked = checked_value(field, value)
    except CatalogError as error:
        raise TuneError(str(error)) from error
    if isinstance(checked, dict):
        raise TuneError(FIELD_RULE)
    return checked


def _flatten(fields: Mapping[str, object] | None) -> list[tuple[str, object]]:
    """{"params": {"A": 1}, "weight": 2} -> [("params.A", 1), ("weight", 2)]."""
    out: list[tuple[str, object]] = []
    for field, value in (fields or {}).items():
        if field != "params":
            out.append((field, value))
        elif isinstance(value, Mapping):
            out += [("params." + name, v) for name, v in value.items()]
        elif value:
            raise TuneError("params is a block of NAME: number")
    return out


# --- the write order --------------------------------------------------------------

def _log(log_path: str, line: str) -> None:
    if not os.path.exists(log_path):
        with open(log_path, "w", encoding="utf-8") as handle:
            handle.write("# Tuning log\n\nEvery change to the playbook - a strategy's frontmatter"
                         " or prose, a strategy added, meta.md - newest last: when, what, why,"
                         " and who.\n\n")
    with open(log_path, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ")


def _playbook_dir(directory: str | None) -> str:
    """The playbook in force: `directory`, else the folder the catalog
    reads (catalog.strategies_dir)."""
    return directory or catalog_module.strategies_dir()


def _log_path(directory: str | None) -> str:
    """The tuning log beside the playbook in force."""
    return os.path.join(_playbook_dir(directory), "tuning-log.md")


def _document(directory: str, loaded: list[Strategy]) -> None:
    """The catalog document follows the files, for the shipped playbook only."""
    if os.path.abspath(directory) == os.path.abspath(catalog_module.strategies_dir()):
        catalog_module.write_docs(loaded)


def _check_reason(reason: str, message: str) -> None:
    """Every change is logged with why: a blank reason is refused."""
    if not reason or not reason.strip():
        raise TuneError(message)


def _strategy_path(directory: str, sid: str) -> str:
    """The path of the strategy file sid names, or a TuneError."""
    if not catalog_module.ID_RE.fullmatch(sid):
        raise TuneError("no strategy %r" % sid)          # ids are kebab: no paths here
    path = os.path.join(directory, sid + ".md")
    if not os.path.exists(path):
        raise TuneError("no strategy %r" % sid)
    return path


def _commit(directory: str, sid: str, text: str,
            what: Callable[[Strategy], str], reason: str,
            by: str) -> tuple[Strategy, str]:
    """The one write order: the catalog loaded with the new text, the file
    written whole, the docs regenerated, one line logged (_append_log_line)
    -> (the strategy as loaded, the line). `what` words the change from the
    loaded strategy; it is a callable because a pair's text can hold an
    expression's %, which a %-template would misread. A file the catalog
    never reads, the markdown beside the playbook, is refused before
    anything is written."""
    loaded = _trial_load(directory, sid, text)
    strategy = next((s for s in loaded if s.id == sid), None)
    if strategy is None:
        raise TuneError("%s.md lives beside the playbook and is not a strategy" % sid)
    write_whole(os.path.join(directory, sid + ".md"), text)   # .part is no strategy file
    _document(directory, loaded)
    return strategy, _append_log_line(directory, sid, what(strategy), reason, by)


def _append_log_line(directory: str, sid: str, what: str, reason: str, by: str) -> str:
    """One accepted change's line, appended to the log beside the playbook
    -> the line. The reason and who asked are folded onto it, as str.split()
    splits - every break str.splitlines() knows included - so neither opens
    a second log line; who asked is cut to MAX_BY characters, and a blank
    one is BY_SESSION."""
    by = " ".join(by.split())[:MAX_BY] or BY_SESSION
    line = "- %s `%s` %s (%s) [%s]" % (_stamp(), sid, what, " ".join(reason.split()), by)
    _log(_log_path(directory), line)
    return line


# --- the three changes -------------------------------------------------------------

def tune(
        strategy_id: str, field: str, value: object, reason: str, *,
        directory: str | None = None, by: str = BY_SESSION) -> Change:
    """Apply one change -> the field's old and new text and the log line.
    The id META changes one of meta.md's fields - a weight or the swap
    cost - or its prose (_tune_meta)."""
    directory = _playbook_dir(directory)
    _check_reason(reason, "a tuning change needs a reason")
    if strategy_id == META:
        return _tune_meta(directory, field, value, reason, by)
    path = _strategy_path(directory, strategy_id)
    if field == PROSE_FIELD:
        with open(path, encoding="utf-8") as handle:
            rewritten, prose = _strategy_prose(strategy_id, handle.read(), value)
        strategy, line = _commit(directory, strategy_id, rewritten,
                                 lambda _: "%s: rewritten" % PROSE_FIELD, reason, by)
        return {"id": strategy_id, "field": field, "old": prose, "new": strategy.body,
                "line": line}
    checked = _coerce(field, value)
    new = field_text(checked)
    with open(path, encoding="utf-8") as handle:
        text, old = edit_frontmatter(handle.read(), field, checked)
    _, line = _commit(directory, strategy_id, text, lambda _: "%s: %s -> %s" % (
        field, old if old is not None else "unset", new), reason, by)
    return {"id": strategy_id, "field": field, "old": old, "new": new, "line": line}


def _meta_text(directory: str) -> tuple[str, str]:
    """meta.md's text in `directory` -> (the text, what the log line says
    of where it came from): the folder's own, or, where it has none, the
    shipped playbook's, which seeds it. The shipped folder without one is
    a TuneError: nothing is left to seed from."""
    name = catalog_module.META_FILE
    sources = [(directory, "")]
    if os.path.abspath(directory) != os.path.abspath(catalog_module.SHIPPED_DIR):
        sources.append((catalog_module.SHIPPED_DIR, "seeded from the shipped %s; " % name))
    for source, seeded in sources:
        path = os.path.join(source, name)
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as handle:
                return handle.read(), seeded
    raise TuneError("%s: missing - the playbook's folder holds the default engine's weights"
                    " there" % name)


def _prose(text: str, value: object, owner: str, old: str, title: str) -> str:
    """A file's text with its prose, `old`, rewritten whole as `value`: text
    within MAX_PROSE characters, which keeps the file's title - else
    `title` - where it opens with none. `owner` names the file in a
    refusal."""
    if not isinstance(value, str) or not value.strip():
        raise TuneError("%s's %s is its prose, as text" % (owner, PROSE_FIELD))
    if len(value) > MAX_PROSE:
        raise TuneError("%s's prose is under %d characters" % (owner, MAX_PROSE))
    prose = value.strip("\n")
    if not prose.startswith("#"):
        title = next((line for line in old.splitlines() if line.startswith("#")), title)
        prose = "%s\n\n%s" % (title, prose)
    close = text.find("\n---", 3) + len("\n---")
    return text[:close] + "\n" + prose + "\n"


def _meta_prose(text: str, value: object) -> tuple[str, str]:
    """meta.md's text with its prose rewritten whole -> (the new text, the
    old prose)."""
    old = catalog_module.parse_meta(text).body         # the frontmatter is whole
    return _prose(text, value, catalog_module.META_FILE, old, "# The meta"), old


def _strategy_prose(sid: str, text: str, value: object) -> tuple[str, str]:
    """A strategy's text with its prose rewritten whole -> (the new text,
    the old prose): three sentences at most, as a new strategy's are
    (_check_new), under the file's own title where the prose opens with
    none."""
    try:
        old = parse_frontmatter(text).body
    except FrontmatterError as error:
        raise TuneError(str(error)) from error
    if isinstance(value, str) and sentence_count(value) > MAX_SENTENCES:
        raise TuneError("a strategy's prose is at most %d sentences; this has %d"
                        % (MAX_SENTENCES, sentence_count(value)))
    return _prose(text, value, "%s.md" % sid, old, "# %s" % sid), old


def _tune_meta(directory: str, field: str, value: object, reason: str, by: str) -> Change:
    """One of meta.md's fields set - a weight or the swap cost - or its
    prose rewritten -> the change: a field checked by the rule the reader
    keeps (catalog.meta_dial), the new text read back through
    catalog.parse_meta and the strategies loaded before anything is
    written, then the file written - seeded from the shipped playbook's
    where the folder has none (_meta_text) - the docs regenerated and one
    line logged, which names a rewritten prose and does not quote it."""
    path = os.path.join(directory, catalog_module.META_FILE)
    if field != PROSE_FIELD and field not in FIELDS:
        raise TuneError("%s's fields are %s" % (catalog_module.META_FILE,
                                                ", ".join((*FIELDS, PROSE_FIELD))))
    text, seeded = _meta_text(directory)
    old: str | None
    try:
        if field == PROSE_FIELD:
            text, old = _meta_prose(text, value)
            new = catalog_module.parse_meta(text).body
            what = "%s: rewritten" % PROSE_FIELD
        else:
            checked = catalog_module.meta_dial(field, value)
            text, old = _edited(text, lambda lines: _set_scalar(lines, field, checked))
            catalog_module.parse_meta(text)
            new = field_text(checked)
            what = "%s: %s -> %s" % (field, old or "unset", new)
        loaded = catalog_module.load(directory)
    except CatalogError as error:
        raise TuneError(str(error)) from error
    write_whole(path, text)
    _document(directory, loaded)
    line = _append_log_line(directory, META, seeded + what, reason, by)
    return {"id": META, "field": field, "old": old, "new": new, "line": line}


def complete(
        strategy_id: str, fields: Mapping[str, object] | None, reason: str, *,
        directory: str | None = None, by: str = BY_SESSION,
        unset: Sequence[str] = ()) -> Completion:
    """Set several frontmatter fields at once - what /strategy infers for a
    draft - and remove those `unset` names, a field or params.NAME, validated
    as a whole and logged as one line -> the form it took, each field's text
    and what went. A heuristic moving from a metric to a bonus or penalty
    drops its metric and direction in the same write, so no half-moved file
    is ever read; its name and kind stay."""
    directory = _playbook_dir(directory)
    _check_reason(reason, "an inferred strategy needs a reason")
    path = _strategy_path(directory, strategy_id)
    pairs = [(f, _coerce(f, v)) for f, v in _flatten(fields)]
    gone = list(dict.fromkeys(unset))
    removable = [f for f in TUNABLE if f not in ("kind", "category")]
    for field in gone:
        if not (field.startswith("params.") or field in removable):
            raise TuneError("%s cannot be unset: one of %s, or params.NAME"
                            % (field, ", ".join(removable)))
    if not pairs and not gone:
        raise TuneError("nothing to set")
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    for field, value in pairs:
        text, _ = edit_frontmatter(text, field, value)
    for field in gone:
        text, _ = _edited(text, functools.partial(_unset, field=field))
    said = _pairs(pairs) + ("; unset %s" % ", ".join(gone) if gone else "")
    strategy, line = _commit(directory, strategy_id, text, lambda s: "inferred -> %s: %s" % (
        s.form, said), reason, by)
    return {"id": strategy_id, "form": strategy.form, "set": {f: field_text(v) for f, v in pairs},
            "unset": gone, "line": line}


def sentence_count(body: str) -> int:
    """How many sentences the prose holds - the title line and code spans aside."""
    text = "\n".join(line for line in body.splitlines() if not line.startswith("#"))
    text = re.sub(r"`[^`]*`", "code", text)                 # `require: a == 2.` is one token
    return len(_SENTENCE_END.findall(text.strip()))


def _check_new(sid: str, name: str, kind: str, body: str) -> None:
    """What a new strategy must be before any file exists: a kebab id, a known
    kind, a name and prose, the name one line by the rule every field keeps,
    the prose within its length and three sentences at most."""
    if not catalog_module.ID_RE.fullmatch(sid):
        raise TuneError("id must be lowercase-kebab, got %r" % sid)
    if sid in catalog_module.RESERVED:
        raise TuneError("%s is %s's, the default engine's weights and the swap cost, and no"
                        " strategy's: tune changes them" % (sid, catalog_module.META_FILE))
    _coerce("kind", kind)
    if not name.strip() or not body.strip():
        raise TuneError("a strategy needs a name and its prose")
    _coerce("name", name)
    if len(body) > MAX_PROSE:
        raise TuneError("a strategy's prose is under %d characters" % MAX_PROSE)
    count = sentence_count(body)
    if count > MAX_SENTENCES:
        raise TuneError("a strategy's prose is at most %d sentences; this has %d"
                        % (MAX_SENTENCES, count))


def add(strategy_id: str, name: str, kind: str, body: str, fields: Mapping[str, object] | None,
        reason: str, *, directory: str | None = None,
        by: str = BY_SESSION) -> Addition:
    """A new strategy file from its name, kind, prose and (inferred) fields,
    validated through the catalog before it exists and logged with its reason
    -> its form, path and log line. The file opens in category general; a
    category among the fields sets it in place, like any other field."""
    directory = _playbook_dir(directory)
    _check_reason(reason, "a new strategy needs a reason")
    _check_new(strategy_id, name, kind, body)
    path = os.path.join(directory, strategy_id + ".md")
    if os.path.exists(path):
        raise TuneError("%r exists; tune or infer_strategy changes it, deleting it is manual"
                        % strategy_id)
    pairs = [(f, _coerce(f, v)) for f, v in _flatten(fields)]
    body = body.strip("\n")
    if not body.startswith("#"):
        body = "# %s\n\n%s" % (name.strip(), body)
    text = "---\nname: %s\nkind: %s\ncategory: general\n---\n%s\n" % (name.strip(), kind, body)
    for field, value in pairs:
        text, _ = edit_frontmatter(text, field, value)
    strategy, line = _commit(directory, strategy_id, text, lambda s: "added as %s/%s%s" % (
        kind, s.form, ": " + _pairs(pairs) if pairs else ""), reason, by)
    return {"id": strategy_id, "form": strategy.form, "path": path, "line": line}


def log_tail(n: int = 20, directory: str | None = None) -> list[str]:
    """The last n lines of the log beside `directory`, else beside the
    playbook in force, located as the writers locate it; none for n below
    1."""
    log_path = _log_path(directory)
    if not os.path.exists(log_path):
        return []
    with open(log_path, encoding="utf-8") as handle:
        lines = [line.rstrip("\n") for line in handle if line.startswith("- ")]
    return lines[-n:] if n > 0 else []
