"""One strategy: the record a playbook file becomes, its kind and form, and
the rules every file keeps, checked against the facts layer's metric
registry.

    STRATEGIES = CONSTRAINTS ∪ HEURISTICS ∪ ASSUMPTIONS

A strategy file - its frontmatter, its kind and the form read off its
fields (limit, heuristic, scored), a need, a draft, its params - is
docs/inference.md's "How a strategy file works".

Each field keeps one rule, which FIELDS names and checked_value applies: a
line of text or an expression is one line as the loader splits lines,
within its length cap; a choice is one of its choices; the weight is a
finite number within 0..10; a param is NAME: a finite number. A key
outside FIELDS (and `id`, the filename's) is refused. Every expression then
runs on its probes before any board does (Expr.probes): it must evaluate,
and a bonus or a penalty must come out a number (amount). The loader reads
every file through these checks, every writer (inference.tune) checks a
value by them before a file changes, and the door declares its strategy
arguments from FIELDS.
"""

import math
import re
from collections.abc import Iterable, Mapping
from typing import Literal, NamedTuple, TypedDict

from facts import compute
from inference.expr import Expr, ExprError, Section, Value, compile_expr
from inference.frontmatter import Frontmatter, Scalar

# a strategy's kind, as its frontmatter names it, its form, as its fields make
# it, and which end of a heuristic's metric is good
type Kind = Literal["constraint", "heuristic", "assumption"]
type Form = Literal["limit", "heuristic", "scored", "assumption", "draft"]
type Direction = Literal["maximize", "minimize"]
KINDS: tuple[Kind, ...] = ("constraint", "heuristic", "assumption")
# load() sorts by this index within a kind: a heuristic on a metric before one
# on an expression, and draft last for either kind
FORMS: tuple[Form, ...] = ("limit", "heuristic", "scored", "assumption", "draft")
WEIGHED: tuple[Form, ...] = ("heuristic", "scored")     # the forms a weight scales: a heuristic's
DIRECTIONS: tuple[Direction, ...] = ("maximize", "minimize")

# the namespaces one board settles for every candidate six
_BOARD_SECTIONS = ("enemy", "map", "world", "params")


def settled_by_board(names: Iterable[str]) -> bool:
    """Whether an expression over these names is decided once per board: each
    name is red's, the map's, the world's or a param. Strategy.need and the
    solver's gates both ask it."""
    return all(n.split(".", 1)[0] in _BOARD_SECTIONS for n in names)


WEIGHT_RANGE = (0.0, 10.0)
MAX_NAME = 120             # characters in a strategy's name and its category
MAX_TEXT = 500             # characters in any other line or expression
PARAM_RE = re.compile(r"[A-Z][A-Z0-9_]*\Z")

# how a field's value is checked: one line of text, one of a few choices, a
# number within WEIGHT_RANGE, an expression, or the params block
type FieldKind = Literal["line", "choice", "number", "expression", "params"]
# what one frontmatter line holds once checked, and what any field holds
type LineValue = str | float
type FieldValue = LineValue | dict[str, float]


class Field(NamedTuple):
    """One frontmatter field: how its value is checked, what it means (the
    door's schema says so), a choice's choices, and how many characters a
    line or an expression holds."""
    kind: FieldKind
    meaning: str
    choices: tuple[str, ...] = ()
    limit: int = MAX_TEXT


# every field a strategy file may set, in the order the door lists them
FIELDS: dict[str, Field] = {
    "name": Field("line", "what the strategy is called, one line", limit=MAX_NAME),
    "kind": Field("choice", "constraint, heuristic or assumption", KINDS),
    "category": Field(
        "line", "the group the catalog files it under (default general)", limit=MAX_NAME),
    "metric": Field("line", "heuristics: a numeric key from `metrics`"),
    "direction": Field("choice", "heuristics: which end of the metric is good", DIRECTIONS),
    "weight": Field("number", "heuristics: 0..10; 1-4 is the working range"),
    "when": Field("expression", "heuristics: a guard expression; optional"),
    "require": Field("expression", "constraints: the limit, an expression that always holds"),
    "bonus": Field(
        "expression", "heuristics: an expression added, times the weight, while `when` holds"),
    "penalty": Field(
        "expression", "heuristics: an expression or a number subtracted, times the weight,"
        " while `when` holds"),
    "params": Field("params", "NAME: number dials the expressions read as params.NAME"),
}
# what a constraint never carries: it is a limit that always holds, never weighted
NOT_A_LIMIT = ("when", "bonus", "penalty", "metric", "direction", "weight")
# the expression fields, in the order a file and the catalog list them, and
# the two whose value the score adds or subtracts
EXPRESSIONS = ("when", "require", "bonus", "penalty")
AMOUNTS = ("bonus", "penalty")
# the fields a writer sets one at a time; a dial is params.NAME
TUNABLE = tuple(field for field in FIELDS if field not in ("name", "params"))
FIELD_RULE = "field must be one of %s or params.NAME" % ", ".join(TUNABLE)


class CatalogError(ValueError):
    """A playbook the catalog refuses: the message names the file at fault,
    once the catalog knows it, and the rule it breaks."""


# --- the rule each field keeps ---------------------------------------------------

def finite_number(value: object) -> float | None:
    """An int, a float or the text of one - never a bool - as a finite
    float; None for anything else, inf and nan included."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = float(value)
    except (ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def amount(value: Value, source: str) -> float:
    """A bonus or penalty expression's value, as the score adds it: a
    number, a bool among them; anything else is the playbook's error, named
    by its `source`. The catalog runs every bonus and penalty through this
    on its probes at load, so a file that adds a name or a list is refused
    before any board reads it."""
    if isinstance(value, (int, float)):               # a bool is an int
        return float(value)
    raise ExprError("%r - a bonus or penalty is a number, got %r" % (source, value))


def field_text(value: LineValue) -> str:
    """A value as a frontmatter line writes it: a whole float without its
    point, anything else as str() gives it."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _line(field: str, value: object, limit: int) -> str:
    """A line or an expression: a str, or a finite number as its text. It
    holds no break that str.splitlines() - and so parse_frontmatter - splits
    on, a trailing one included, does not open a fence, and is at most limit
    characters."""
    text: str | None = None
    if isinstance(value, str):
        text = value
    elif isinstance(value, (int, float)) and finite_number(value) is not None:
        text = field_text(value)
    if (text is None or "".join(text.splitlines()) != text
            or text.lstrip().startswith("---") or len(text) > limit):
        raise CatalogError("%s is one line of text under %d characters" % (field, limit))
    return text


def _choice[C: str](field: str, value: object, choices: tuple[C, ...]) -> C:
    """One of the field's choices, as the choices spell it."""
    for choice in choices:
        if value == choice:
            return choice
    raise CatalogError("%s must be one of %s" % (field, "/".join(choices)))


def _number(field: str, value: object) -> float:
    """A finite number within WEIGHT_RANGE."""
    number = finite_number(value)
    if number is None:
        raise CatalogError("%s must be a number" % field)
    if not WEIGHT_RANGE[0] <= number <= WEIGHT_RANGE[1]:
        raise CatalogError("%s must be within %g..%g" % (field, *WEIGHT_RANGE))
    return number


def _param(name: str, value: object) -> float:
    """One dial: NAME in capitals, and a finite number. An int stays an int,
    so the file, the mirror and the docs read it as written."""
    if not PARAM_RE.match(name):
        raise CatalogError("a param is NAME: capitals, digits, underscores")
    number = finite_number(value)
    if number is None:
        raise CatalogError("a param must be a finite number")
    return value if isinstance(value, int) else number


def _params(value: object) -> dict[str, float]:
    """The params block: a mapping of dials."""
    if not isinstance(value, Mapping):
        raise CatalogError("params is a block of NAME: number")
    return {str(name): _param(str(name), number) for name, number in value.items()}


def checked_value(field: str, value: object) -> FieldValue:
    """The value a writer sets under field, by the rule its kind keeps in
    FIELDS - the rule the loader reads the file by - else a CatalogError with
    the bare rule. params.NAME is one dial."""
    if field.startswith("params."):
        return _param(field[len("params."):], value)
    spec = FIELDS.get(field)
    if spec is None:
        raise CatalogError(FIELD_RULE)
    if spec.kind == "choice":
        return _choice(field, value, spec.choices)
    if spec.kind == "number":
        return _number(field, value)
    if spec.kind == "params":
        return _params(value)
    return _line(field, value, spec.limit)


def _given(meta: Frontmatter, field: str) -> Scalar | dict[str, Scalar]:
    """What the frontmatter sets under field; None when it is unset - absent,
    null, blank, or the empty mapping a bare `key:` reads as."""
    value = meta.get(field)
    return None if value is None or value == "" or value == {} else value


def _text(meta: Frontmatter, field: str) -> str | None:
    """A line or an expression the frontmatter sets, checked; None when unset."""
    value = _given(meta, field)
    return None if value is None else _line(field, value, FIELDS[field].limit)


def _check_keys(meta: Frontmatter) -> None:
    """Every key the frontmatter sets is a field, or the id the filename
    holds. soft: is refused by name: a limit always holds, and a charge is a
    heuristic's penalty."""
    if "soft" in meta:
        raise CatalogError("soft: is refused - a limit always holds; charge a penalty from a"
                           " heuristic, when: not (<the rule>)")
    unknown = sorted(str(key) for key in meta if key not in FIELDS and key != "id")
    if unknown:
        raise CatalogError("%s is not a strategy field (the fields: %s)"
                           % (", ".join(unknown), ", ".join(FIELDS)))


# --- the strategy -----------------------------------------------------------------

class StrategyRecord(TypedDict):
    """A strategy as the tools and the board serve it."""
    id: str
    name: str
    kind: Kind
    form: Form
    pending: bool
    need: bool
    category: str
    direction: Direction | None
    metric: str | None
    weight: float
    when: str | None
    require: str | None
    bonus: str | None
    penalty: str | None
    params: dict[str, float]
    body: str


class Strategy:
    """One strategy file, parsed and checked: its fields, its expressions
    compiled, and the form they make it."""

    def __init__(self, strategy_id: str, meta: Frontmatter, body: str) -> None:
        self.id, self.body = strategy_id, body
        try:
            _check_keys(meta)
            self.name = _text(meta, "name") or strategy_id.replace("-", " ")
            self.kind: Kind = _choice("kind", meta.get("kind"), KINDS)
            self.category = _text(meta, "category") or "general"
            self.metric = _text(meta, "metric")
            direction = _given(meta, "direction")
            self.direction = None if direction is None else _choice(
                "direction", direction, DIRECTIONS)
            # an absent weight reads 1, a blank one 0
            self.weight = _number("weight", meta.get("weight", 1.0) or 0.0)
            self.when = compile_expr(_text(meta, "when"))
            self.require = compile_expr(_text(meta, "require"))
            self.bonus = compile_expr(_text(meta, "bonus"))
            self.penalty = compile_expr(_text(meta, "penalty"))
            params = _given(meta, "params")
            self.params = {} if params is None else _params(params)
        except (CatalogError, ExprError) as error:
            raise CatalogError("%s: %s" % (strategy_id, error)) from error
        self.params_section = Section(dict(self.params))
        self._check(meta)

    def _check(self, meta: Frontmatter) -> None:
        """Every rule a file must keep, in order, so its first error is the one
        reported."""
        known = compute.registry()
        self._check_heuristic(known)
        self._check_kind(meta)
        self._check_names(known)
        self._check_probes()

    def _labelled(self) -> list[tuple[str, Expr]]:
        """Every expression the file sets, with the field it sits under, in
        EXPRESSIONS' order."""
        held = {"when": self.when, "require": self.require, "bonus": self.bonus,
                "penalty": self.penalty}
        return [(field, expr) for field in EXPRESSIONS if (expr := held[field]) is not None]

    def _check_heuristic(self, known: Mapping[str, str]) -> None:
        if self.kind != "heuristic" or not (self.metric or self.direction):
            return
        if self.direction not in DIRECTIONS:
            raise CatalogError("%s: a heuristic needs direction maximize|minimize" % self.id)
        if not self.metric or self.metric not in known:
            raise CatalogError("%s: metric %r is not a registered fact key"
                               % (self.id, self.metric))
        if self.metric in compute.TEXT_METRICS:
            raise CatalogError("%s: metric %r is text, not a number" % (self.id, self.metric))

    def _check_kind(self, meta: Frontmatter) -> None:
        """What each kind may not carry: an assumption anything to score, a
        constraint anything but its limit, a heuristic a limit, or a metric
        and an expression at once."""
        if self.kind == "assumption" and (self.metric or self.expressions):
            raise CatalogError("%s: an assumption carries nothing to score" % self.id)
        if self.kind == "constraint":
            weighed = [f for f in NOT_A_LIMIT if _given(meta, f) is not None]
            if weighed:
                raise CatalogError(
                    "%s: a constraint is a limit that always holds (require:) and is never"
                    " weighted; %s belong to a heuristic" % (self.id, ", ".join(weighed)))
        if self.kind == "heuristic" and self.require is not None:
            raise CatalogError("%s: a heuristic weighs; require: is a constraint's limit"
                               % self.id)
        if self.kind == "heuristic" and self.metric and (
                self.bonus is not None or self.penalty is not None):
            raise CatalogError("%s: a heuristic weighs a metric or bonus/penalty, not both"
                               % self.id)

    def _check_names(self, known: Mapping[str, str]) -> None:
        """Every name an expression reads is a registered key or a declared param."""
        for _, expr in self._labelled():
            for name in expr.names:
                if name.startswith("params."):
                    if name[7:] not in self.params:
                        raise CatalogError("%s: %s is not declared under params:"
                                           % (self.id, name))
                elif name not in known:
                    raise CatalogError("%s: %r is not a registered fact key"
                                       % (self.id, name))

    def _check_probes(self) -> None:
        """Every expression runs before any board does: on each of its
        probes, the file's params among the numbers, it evaluates, and a
        bonus or a penalty comes out a number. A file that adds a name, or
        orders a name against a number, is refused here, not by the first
        board its guard holds on."""
        for field, expr in self._labelled():
            for probe in expr.probes(compute.TEXT_METRICS, self.params.values()):
                probe.scope["params"] = self.params_section
                try:
                    value = expr.evaluate(probe.scope)
                    if field in AMOUNTS:
                        amount(value, expr.source)
                except ExprError as error:
                    raise CatalogError("%s: %s %s (every number it reads at %s, every text %r)"
                                       % (self.id, field, error, field_text(probe.number),
                                          probe.text)) from error

    @property
    def form(self) -> Form:
        """A constraint's limit; a heuristic on a metric (heuristic) or on an
        expression (scored); assumption; or draft (name, kind and prose only -
        awaiting /strategy)."""
        if self.kind == "assumption":
            return "assumption"
        if self.kind == "constraint":
            return "limit" if self.require is not None else "draft"
        if self.metric:
            return "heuristic"
        if self.bonus is not None or self.penalty is not None:
            return "scored"
        return "draft"

    @property
    def weighs(self) -> bool:
        """Whether the strategy is a heuristic the solver weighs: on a metric or
        on an expression, never a draft."""
        return self.form in WEIGHED

    @property
    def pending(self) -> bool:
        """A draft: the /strategy skill has not inferred its frontmatter yet."""
        return self.form == "draft"

    @property
    def expressions(self) -> str:
        """Every expression the file sets, labelled: "when: ...; require: ..."."""
        return "; ".join("%s: %s" % (field, expr.source) for field, expr in self._labelled())

    @property
    def need(self) -> bool:
        """A heuristic guarded on the six's own state: the solver charges what it
        misses (weight x (norm - 1)) instead of paying what it has. A guard the
        board settles leaves it a reward."""
        return (self.form == "heuristic" and self.when is not None
                and not settled_by_board(self.when.names))

    def to_dict(self) -> StrategyRecord:
        """The record the tools and the board serve."""
        return {"id": self.id, "name": self.name, "kind": self.kind, "form": self.form,
                "pending": self.pending, "need": self.need,
                "category": self.category, "direction": self.direction,
                "metric": self.metric, "weight": self.weight,
                "when": self.when.source if self.when else None,
                "require": self.require.source if self.require else None,
                "bonus": self.bonus.source if self.bonus else None,
                "penalty": self.penalty.source if self.penalty else None,
                "params": self.params, "body": self.body}
