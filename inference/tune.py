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
bonus, penalty (strategy.TUNABLE) and params.NAME. Every
value is checked by strategy.checked_value, the rule the loader reads a
file by, before any file is touched. Each of the three takes a reason and
writes in one order (_commit): the edited (or new) file is loaded through
the catalog before it is written, so a metric that does not exist or an
expression that does not parse is refused and nothing changes. Every
accepted change is one line in inference/strategies/tuning-log.md. The log
lives beside the files: the compose stack bind-mounts that directory, so a
change made through a container lands on the host and in git with the file
it changed.

    tune("meta", "synergy", 0.2, "the wiki's pairs should count for more")
    tune("meta", "body", prose, "the synergy clause names the imputed cells")

The id `meta` names meta.md, the default engine's weights beside the
strategy files: its fields are meta, rate, synergy and counter
(base.DIALS), each checked by catalog.meta_dial, and `body`, the prose the
playbook tab and the docs catalog show, rewritten whole; the file is read
back by catalog.parse_meta before it is written, then documented and
logged like any other change (_tune_meta). A playbook folder with no
meta.md is seeded from the shipped one's by its first such change, and the
log line says so. No strategy may take the name.
"""

import os
import re
import shutil
import tempfile
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import TypedDict

from db import Refusal
from inference import catalog as catalog_module
from inference.base import DIALS, META
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
META_PROSE = "body"        # meta.md's prose, as tune names it beside the dials
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
    """What complete() set: the form the strategy took and each field's text."""
    id: str
    form: Form
    set: dict[str, str]
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


def _set_param(lines: list[str], name: str, value: LineValue) -> str | None:
    """NAME set under params:, the block added when there is none -> the old value."""
    block = next((i for i, line in enumerate(lines) if line.strip() == "params:"), None)
    if block is None:
        block = _header_end(lines)
        lines.insert(block, "params:")
    i = block + 1
    while i < len(lines) and lines[i][:1] in (" ", "\t"):
        if lines[i].strip().split(":")[0] == name:
            old = lines[i].split(":", 1)[1].strip()
            lines[i] = "  %s: %s" % (name, field_text(value))
            return old
        i += 1
    lines.insert(i, "  %s: %s" % (name, field_text(value)))
    return None


def _set_scalar(lines: list[str], field: str, value: LineValue) -> str | None:
    """A flat field set in place, or added above params: -> the old value."""
    for i, line in enumerate(lines):
        if line[:1] not in (" ", "\t") and line.split(":")[0].strip() == field:
            old = line.split(":", 1)[1].strip()
            lines[i] = "%s: %s" % (field, field_text(value))
            return old
    at = next((i for i, line in enumerate(lines) if line.strip() == "params:"), _header_end(lines))
    lines.insert(at, "%s: %s" % (field, field_text(value)))
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
            handle.write("# Tuning log\n\nEvery change to a strategy's frontmatter,"
                         " newest last: when, what, why, and who.\n\n")
    with open(log_path, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ")


def _where(directory: str | None) -> tuple[str, str]:
    """The playbook in force and its log: (directory, log path)."""
    directory = directory or catalog_module.strategies_dir()
    return directory, os.path.join(directory, "tuning-log.md")


def _document(directory: str, loaded: list[Strategy]) -> None:
    """The catalog document follows the files, for the shipped playbook only."""
    if os.path.abspath(directory) == os.path.abspath(catalog_module.strategies_dir()):
        catalog_module.write_docs(loaded)


def _reason(reason: str, message: str) -> None:
    """Every change is logged with why: a blank reason is refused."""
    if not reason or not reason.strip():
        raise TuneError(message)


def _existing(directory: str, sid: str) -> str:
    """The path of the strategy file sid names, or a TuneError."""
    if not catalog_module.ID_RE.fullmatch(sid or ""):
        raise TuneError("no strategy %r" % sid)          # ids are kebab: no paths here
    path = os.path.join(directory, sid + ".md")
    if not os.path.exists(path):
        raise TuneError("no strategy %r" % sid)
    return path


def _commit(directory: str, sid: str, text: str,
            what: Callable[[Strategy], str], reason: str,
            by: str) -> tuple[Strategy, str]:
    """The one write order: the catalog loaded with the new text, the file
    written, the docs regenerated, one line logged -> (the strategy as loaded,
    the line). `what` words the change from the loaded strategy; it is a
    callable because a pair's text can hold an expression's %, which a
    %-template would misread. A file the catalog never reads, the markdown
    beside the playbook, is refused before anything is written. The reason
    and who asked are folded onto one line, as str.split() splits - every
    break str.splitlines() knows included - so neither opens a second log
    line; who asked is cut to MAX_BY characters, and a blank one is
    BY_SESSION."""
    loaded = _trial_load(directory, sid, text)
    strategy = next((s for s in loaded if s.id == sid), None)
    if strategy is None:
        raise TuneError("%s.md lives beside the playbook and is not a strategy" % sid)
    with open(os.path.join(directory, sid + ".md"), "w", encoding="utf-8") as handle:
        handle.write(text)
    _document(directory, loaded)
    return strategy, _logged(directory, sid, what(strategy), reason, by)


def _logged(directory: str, sid: str, what: str, reason: str, by: str) -> str:
    """One accepted change's line, appended to the log beside the playbook
    -> the line: the reason and who asked folded onto it (_commit)."""
    by = " ".join(by.split())[:MAX_BY] or BY_SESSION
    line = "- %s `%s` %s (%s) [%s]" % (_stamp(), sid, what, " ".join(reason.split()), by)
    _log(_where(directory)[1], line)
    return line


# --- the three changes -------------------------------------------------------------

def tune(
        strategy_id: str, field: str, value: object, reason: str, directory: str | None = None,
        by: str = BY_SESSION) -> Change:
    """Apply one change -> the field's old and new text and the log line.
    The id META changes one of meta.md's weights (_tune_meta)."""
    directory = _where(directory)[0]
    _reason(reason, "a tuning change needs a reason")
    if strategy_id == META:
        return _tune_meta(directory, field, value, reason, by)
    path = _existing(directory, strategy_id)
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
        try:
            with open(os.path.join(source, name), encoding="utf-8") as handle:
                return handle.read(), seeded
        except FileNotFoundError:
            continue
    raise TuneError("%s: missing - the playbook's folder holds the default engine's weights"
                    " there" % name)


def _meta_prose(text: str, value: object) -> tuple[str, str]:
    """meta.md's text with its prose rewritten whole -> (the new text, the
    old prose). The prose is text within MAX_PROSE characters; one that
    opens with no title keeps the file's."""
    if not isinstance(value, str) or not value.strip():
        raise TuneError("%s's %s is its prose, as text" % (catalog_module.META_FILE, META_PROSE))
    if len(value) > MAX_PROSE:
        raise TuneError("%s's prose is under %d characters"
                        % (catalog_module.META_FILE, MAX_PROSE))
    old = catalog_module.parse_meta(text).body         # the frontmatter is whole
    prose = value.strip("\n")
    if not prose.startswith("#"):
        title = next((line for line in old.splitlines() if line.startswith("#")), "# The meta")
        prose = "%s\n\n%s" % (title, prose)
    close = text.find("\n---", 3) + len("\n---")
    return text[:close] + "\n" + prose + "\n", old


def _tune_meta(directory: str, field: str, value: object, reason: str, by: str) -> Change:
    """One of meta.md's weights set, or its prose rewritten -> the change:
    a weight checked by the rule the reader keeps (catalog.meta_dial), the
    new text read back through catalog.parse_meta and the strategies loaded
    before anything is written, then the file written - seeded from the
    shipped playbook's where the folder has none (_meta_text) - the docs
    regenerated and one line logged, which names a rewritten prose and
    does not quote it."""
    path = os.path.join(directory, catalog_module.META_FILE)
    if field != META_PROSE and field not in DIALS:
        raise TuneError("%s's fields are %s" % (catalog_module.META_FILE,
                                                ", ".join((*DIALS, META_PROSE))))
    text, seeded = _meta_text(directory)
    old: str | None
    try:
        if field == META_PROSE:
            text, old = _meta_prose(text, value)
            new = catalog_module.parse_meta(text).body
            what = "%s: rewritten" % META_PROSE
        else:
            checked = catalog_module.meta_dial(field, value)
            text, old = _edited(text, lambda lines: _set_scalar(lines, field, checked))
            catalog_module.parse_meta(text)
            new = field_text(checked)
            what = "%s: %s -> %s" % (field, old or "unset", new)
        loaded = catalog_module.load(directory)
    except CatalogError as error:
        raise TuneError(str(error)) from error
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    _document(directory, loaded)
    line = _logged(directory, META, seeded + what, reason, by)
    return {"id": META, "field": field, "old": old, "new": new, "line": line}


def complete(
        strategy_id: str, fields: Mapping[str, object] | None, reason: str,
        directory: str | None = None, by: str = BY_SESSION) -> Completion:
    """Set several frontmatter fields at once - what /strategy infers for a
    draft - validated as a whole, logged as one line -> the form it took and
    each field's text."""
    directory = _where(directory)[0]
    _reason(reason, "an inferred strategy needs a reason")
    path = _existing(directory, strategy_id)
    pairs = [(f, _coerce(f, v)) for f, v in _flatten(fields)]
    if not pairs:
        raise TuneError("nothing to set")
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    for field, value in pairs:
        text, _ = edit_frontmatter(text, field, value)
    strategy, line = _commit(directory, strategy_id, text, lambda s: "inferred -> %s: %s" % (
        s.form, _pairs(pairs)), reason, by)
    return {"id": strategy_id, "form": strategy.form, "set": {f: field_text(v) for f, v in pairs},
            "line": line}


def sentence_count(body: str) -> int:
    """How many sentences the prose holds - the title line and code spans aside."""
    text = "\n".join(line for line in (body or "").splitlines() if not line.startswith("#"))
    text = re.sub(r"`[^`]*`", "code", text)                 # `require: a == 2.` is one token
    return len(_SENTENCE_END.findall(text.strip()))


def _check_new(sid: str, name: str, kind: str, body: str) -> None:
    """What a new strategy must be before any file exists: a kebab id, a known
    kind, a name and prose, the name one line by the rule every field keeps,
    the prose within its length and three sentences at most."""
    if not catalog_module.ID_RE.fullmatch(sid or ""):
        raise TuneError("id must be lowercase-kebab, got %r" % sid)
    if sid == META:
        raise TuneError("%s is %s, the default engine's weights, and no strategy: tune"
                        " changes them" % (META, catalog_module.META_FILE))
    _coerce("kind", kind)
    if not (name or "").strip() or not (body or "").strip():
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
    directory = _where(directory)[0]
    _reason(reason, "a new strategy needs a reason")
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


def log_tail(n: int = 20, log_path: str | None = None) -> list[str]:
    """The last n lines of the log beside the playbook in force; none for n
    below 1."""
    log_path = log_path or _where(None)[1]
    if not os.path.exists(log_path):
        return []
    with open(log_path, encoding="utf-8") as handle:
        lines = [line.rstrip("\n") for line in handle if line.startswith("- ")]
    return lines[-n:] if n > 0 else []
