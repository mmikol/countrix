"""The search's bounds: the most any six a branch of the search can still
reach scores, read off the picks made so far and the candidates each open
role has left. The walk (inference.solver) drops a branch whose bound cannot
enter the top K, so a bound that ever read below a six it covers would lose
that six without a word: every rule here is sound by construction, and
tests/inference/test_bounds.py holds each to it on random branches.

    Iv, Exact, Seq, Top   what a value can be over a branch: every number
                          lo..hi (a bool is 0 or 1), one value known exactly
                          (a name, a list), a display of values, or anything -
                          a list at most `size` long where that is known
    abstract              an expression read over those values, one rule for
                          each node type and operator the whitelist admits
                          (inference.expr): an operator takes the ends of its
                          operands' intervals, a comparison is true, false or
                          either, and `and`, `or` and `if` join the outcomes
                          they can take
    RULES                 each team.* and matchup.* key's range over a branch's
                          completions, by the aggregate it is: a sum over the
                          picks, a mean or median of the known values, a max or
                          a min, a product, a sum over pairs, the enemies
                          answered, the distinct subroles, the claimed synergy
                          graph's isolated picks and largest group, or fixed by
                          the shape
    Space                 one search's heroes - the locked picks, then each
                          role's candidates in walk order - by dense index, and
                          the suffix tables the rules read
    Bound                 the objective over a branch, summed in the order the
                          score sums it: the default engine's terms jointly -
                          each open pick's own part, its pairs with the picks
                          made, and half its best pairs among the rest - with
                          the swap search's keep term in each pick's own part,
                          then each heuristic and each scored term apart

Floating point: a metric the bound sums in another order than the metric
itself carries a slack, SLACK times the magnitude of its addends, outward on
both ends; one whose values are whole numbers is exact and carries none, so
a threshold on a count reads exactly. Every other step is a monotone float
operation taken at the right end of an interval, and the terms add up in
the score's own order, so a six's computed score never exceeds its branch's
computed bound.
"""

import ast
import math
import operator
from collections.abc import Callable, Mapping, Sequence
from typing import NamedTuple

from facts import compute
from facts.draft import EXPECTED_SHAPE, TEAM_SIZE
from facts.model import ROLES, SQUISHY_POOL, Hero, World
from facts.team import (
    FLIER_REACH,
    RANK_SENSITIVE,
    SPECIALIST_DELTA,
    number,
    pair_score,
    shape_flags,
)
from inference.expr import Expr
from inference.scoring import Norm, Objective, normalised
from inference.shapes import is_shape_limit

INF = math.inf
SLACK = 1e-12              # a float computation's slack per unit of its addends' magnitude


class Iv(NamedTuple):
    """Every number a value can take over a branch, lo..hi. A bool is 0 or
    1, as Python adds it."""
    lo: float
    hi: float


class Exact(NamedTuple):
    """One value that is not a number, the same on every completion: a
    name, a list, a tally, None."""
    value: object


class Seq(NamedTuple):
    """A list or tuple display, element by element."""
    items: tuple["Abstract", ...]


class Top(NamedTuple):
    """Any value; a list at most `size` long where the rule knows it is one."""
    size: float = INF


type Abstract = Iv | Exact | Seq | Top
type Env = dict[str, Abstract]              # a branch's team.* and matchup.* values
type Evaluator = Callable[[Env], Abstract]

FALSE, TRUE, MAYBE = Iv(0.0, 0.0), Iv(1.0, 1.0), Iv(0.0, 1.0)
WHOLE = Iv(-INF, INF)
ANY = Top()


def lift(value: object) -> Abstract:
    """A known value: a number, a bool among them, as a point; anything else
    exactly."""
    if isinstance(value, int | float):
        v = float(value)
        return Iv(v, v) if v == v else WHOLE
    return Exact(value)


def _iv(lo: float, hi: float) -> Iv:
    """An interval, a NaN end read as unbounded that way."""
    return Iv(-INF if lo != lo else lo, INF if hi != hi else hi)


def truth(a: Abstract) -> bool | None:
    """Whether a value is truthy on every completion (True), on none (False),
    or on some (None)."""
    if isinstance(a, Iv):
        if a.lo > 0 or a.hi < 0:
            return True
        if a.lo == 0 and a.hi == 0:
            return False
        return None
    if isinstance(a, Exact):
        return bool(a.value)
    if isinstance(a, Seq):
        return bool(a.items)
    return None


def boolean(t: bool | None) -> Iv:
    """A three-valued truth as a value: 0, 1, or either."""
    return MAYBE if t is None else TRUE if t else FALSE


def join(a: Abstract, b: Abstract) -> Abstract:
    """What either of two values can be."""
    if isinstance(a, Iv) and isinstance(b, Iv):
        return Iv(min(a.lo, b.lo), max(a.hi, b.hi))
    return a if a == b else ANY


# --- the operators ------------------------------------------------------------

def _exactly(op: Callable[[object, object], object], a: Abstract, b: Abstract) -> Abstract:
    """An operator on two exact values, as Python applies it; anything else
    it can be applied to is anything."""
    if isinstance(a, Exact) and isinstance(b, Exact):
        try:
            return lift(op(a.value, b.value))
        except Exception:  # noqa: BLE001  # the score raises the same on the six itself
            return ANY
    return ANY


def _add(a: Abstract, b: Abstract) -> Abstract:
    if isinstance(a, Iv) and isinstance(b, Iv):
        return _iv(a.lo + b.lo, a.hi + b.hi)
    return _exactly(operator.add, a, b)


def _sub(a: Abstract, b: Abstract) -> Abstract:
    if isinstance(a, Iv) and isinstance(b, Iv):
        return _iv(a.lo - b.hi, a.hi - b.lo)
    return ANY


def _corners(values: Sequence[float]) -> Iv:
    """The hull of an operator's values at its operands' ends; 0 x inf reads
    0, since an infinite end is a limit no value reaches."""
    finite = [0.0 if v != v else v for v in values]
    return Iv(min(finite), max(finite))


def _mul(a: Abstract, b: Abstract) -> Abstract:
    if isinstance(a, Iv) and isinstance(b, Iv):
        return _corners((a.lo * b.lo, a.lo * b.hi, a.hi * b.lo, a.hi * b.hi))
    return _exactly(operator.mul, a, b)


def _div(a: Abstract, b: Abstract) -> Abstract:
    """A division reads 0 at a zero divisor (inference.expr's _div)."""
    if not (isinstance(a, Iv) and isinstance(b, Iv)):
        return ANY
    if b.lo == 0 and b.hi == 0:
        return FALSE
    if b.lo > 0 or b.hi < 0:
        corners = (a.lo / b.lo, a.lo / b.hi, a.hi / b.lo, a.hi / b.hi)
        return WHOLE if any(c != c for c in corners) else Iv(min(corners), max(corners))
    return FALSE if a.lo == 0 and a.hi == 0 else WHOLE


def _floor(v: float) -> float:
    return float(math.floor(v)) if math.isfinite(v) else v


def _floordiv(a: Abstract, b: Abstract) -> Abstract:
    """A floor division: the quotient's hull floored, its low end one lower
    for a quotient that rounded up across a whole number."""
    q = _div(a, b)
    if not isinstance(q, Iv) or q == FALSE:
        return q
    return Iv(_floor(q.lo) - 1.0, _floor(q.hi))


def _mod(a: Abstract, b: Abstract) -> Abstract:
    """A remainder takes its divisor's sign and is smaller than it; 0 at a
    zero divisor."""
    if not (isinstance(a, Iv) and isinstance(b, Iv)):
        return ANY
    if b.lo == 0 and b.hi == 0:
        return FALSE
    if b.lo > 0:
        return Iv(0.0, b.hi)
    if b.hi < 0:
        return Iv(b.lo, 0.0)
    return Iv(min(b.lo, 0.0), max(b.hi, 0.0))


def _pow(a: Abstract, exponent: float) -> Abstract:
    """A power by the small constant exponent the whitelist allows."""
    if not isinstance(a, Iv):
        return ANY
    if exponent == 0:
        return TRUE
    try:
        if exponent == int(exponent):
            k = int(exponent)
            ends = [a.lo ** k, a.hi ** k]
            if k % 2 == 0 and a.lo < 0 < a.hi:
                ends.append(0.0)
            return _iv(min(ends), max(ends))
        if a.lo >= 0:
            return _iv(a.lo ** exponent, a.hi ** exponent)
    except OverflowError:
        return WHOLE
    return ANY


_BINARY: dict[type[ast.operator], Callable[[Abstract, Abstract], Abstract]] = {
    ast.Add: _add, ast.Sub: _sub, ast.Mult: _mul, ast.Div: _div,
    ast.FloorDiv: _floordiv, ast.Mod: _mod}


def _negate(a: Abstract) -> Abstract:
    return Iv(-a.hi, -a.lo) if isinstance(a, Iv) else ANY


def _positive(a: Abstract) -> Abstract:
    return a if isinstance(a, Iv) else ANY


def _not(a: Abstract) -> Abstract:
    t = truth(a)
    return boolean(None if t is None else not t)


_UNARY: dict[type[ast.unaryop], Callable[[Abstract], Abstract]] = {
    ast.USub: _negate, ast.UAdd: _positive, ast.Not: _not}


# --- the comparisons ------------------------------------------------------------

def _order(op: type[ast.cmpop], a: Iv, b: Iv) -> bool | None:
    """<, <=, > and >= between two intervals."""
    if op is ast.Gt:
        return _order(ast.Lt, b, a)
    if op is ast.GtE:
        return _order(ast.LtE, b, a)
    if op is ast.Lt:
        return True if a.hi < b.lo else False if a.lo >= b.hi else None
    return True if a.hi <= b.lo else False if a.lo > b.hi else None


def _equal(a: Abstract, b: Abstract) -> bool | None:
    """==, three-valued: a number never equals a name or a list."""
    if isinstance(a, Iv) and isinstance(b, Iv):
        if a.lo == a.hi == b.lo == b.hi:
            return True
        return False if a.hi < b.lo or b.hi < a.lo else None
    if isinstance(a, Exact) and isinstance(b, Exact):
        return bool(a.value == b.value)
    if isinstance(a, Iv | Exact) and isinstance(b, Iv | Exact):
        return False                       # one is a number and the other is not
    return None


def _member(a: Abstract, b: Abstract) -> bool | None:
    """`in`, three-valued."""
    if isinstance(b, Seq):
        found = [_equal(a, item) for item in b.items]
        return True if True in found else False if all(f is False for f in found) else None
    if isinstance(b, Exact):
        if isinstance(a, Exact) or (isinstance(a, Iv) and a.lo == a.hi):
            value = a.value if isinstance(a, Exact) else a.lo
            container = b.value
            if not isinstance(container, list | tuple | dict | str | set | frozenset):
                return None
            try:
                return value in container
            except TypeError:
                return None
        if isinstance(a, Iv) and isinstance(b.value, list | tuple | dict | str):
            items = b.value.keys() if isinstance(b.value, dict) else b.value
            return None if any(isinstance(x, int | float) for x in items) else False
    return None


def compare(op: type[ast.cmpop], a: Abstract, b: Abstract) -> bool | None:
    """One comparison between two values, three-valued."""
    if op is ast.Eq:
        return _equal(a, b)
    if op is ast.NotEq:
        eq = _equal(a, b)
        return None if eq is None else not eq
    if op is ast.In:
        return _member(a, b)
    if op is ast.NotIn:
        inside = _member(a, b)
        return None if inside is None else not inside
    if isinstance(a, Iv) and isinstance(b, Iv):
        return _order(op, a, b)
    if isinstance(a, Exact) and isinstance(b, Exact):
        try:
            return bool(_ORDERS[op](a.value, b.value))
        except TypeError:
            return None
    return None


_ORDERS: dict[type[ast.cmpop], Callable[..., object]] = {
    ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge}
# the comparisons abstract() reads, one per operator the whitelist admits
COMPARISONS = (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn)


# --- the calls ------------------------------------------------------------------

def _elements(args: Sequence[Abstract]) -> list[Abstract] | None:
    """min's and max's operands: its arguments, or the one iterable it is
    given; None where that iterable is unknown."""
    if len(args) != 1:
        return list(args)
    only = args[0]
    if isinstance(only, Seq):
        return list(only.items)
    if isinstance(only, Exact) and isinstance(only.value, list | tuple):
        return [lift(v) for v in only.value]
    return None


def _extreme(args: Sequence[Abstract], lowest: bool) -> Abstract:
    """min() or max() of intervals: the least (or most) of each end."""
    items = _elements(args)
    if not items:
        return ANY
    if all(isinstance(x, Iv) for x in items):
        ivs = [x for x in items if isinstance(x, Iv)]
        pick = min if lowest else max
        return Iv(pick(x.lo for x in ivs), pick(x.hi for x in ivs))
    if all(isinstance(x, Exact) for x in items):
        try:
            values = [x.value for x in items if isinstance(x, Exact)]
            return lift(min(values) if lowest else max(values))  # type: ignore[type-var]
        except TypeError:
            return ANY
    return ANY


def _abs(a: Abstract) -> Abstract:
    if not isinstance(a, Iv):
        return ANY
    if a.lo >= 0:
        return a
    if a.hi <= 0:
        return Iv(-a.hi, -a.lo)
    return Iv(0.0, max(-a.lo, a.hi))


def _monotone(f: Callable[[float], float], a: Abstract) -> Abstract:
    """A non-decreasing function of a number at an interval's two ends, an
    infinite end kept."""
    if not isinstance(a, Iv):
        return ANY
    try:
        return Iv(f(a.lo) if math.isfinite(a.lo) else a.lo,
                  f(a.hi) if math.isfinite(a.hi) else a.hi)
    except (OverflowError, ValueError):
        return WHOLE


def _call(name: str, args: Sequence[Abstract]) -> Abstract:
    """One of the helpers inference.expr serves: exactly where every
    argument is exact, else by its own rule."""
    if args and all(isinstance(a, Exact) for a in args):
        try:
            return lift(_HELPERS[name](*(a.value for a in args if isinstance(a, Exact))))
        except Exception:  # noqa: BLE001  # the score raises the same on the six itself
            return ANY
    if name in ("min", "max"):
        return _extreme(args, name == "min")
    if name == "abs" and len(args) == 1:
        return _abs(args[0])
    if name == "round" and len(args) in (1, 2):
        places = args[1] if len(args) == 2 else None
        if places is None:
            return _monotone(lambda v: float(round(v)), args[0])
        if isinstance(places, Iv) and places.lo == places.hi:
            n = int(places.lo)
            return _monotone(lambda v: round(v, n), args[0])
        return ANY
    if name in ("int", "float") and len(args) == 1:
        return _monotone(float if name == "float" else lambda v: float(int(v)), args[0])
    if name == "bool" and len(args) == 1:
        return boolean(truth(args[0]))
    if name == "len" and len(args) == 1:
        return _length(args[0])
    return ANY


def _length(a: Abstract) -> Abstract:
    if isinstance(a, Seq):
        return Iv(float(len(a.items)), float(len(a.items)))
    if isinstance(a, Top):
        return Iv(0.0, a.size)
    return ANY


_HELPERS: dict[str, Callable[..., object]] = {
    "min": min, "max": max, "abs": abs, "round": round, "len": len, "int": int,
    "float": float, "bool": bool}


# --- an expression, compiled over abstract values -------------------------------

def _and(parts: Sequence[Evaluator]) -> Evaluator:
    """`a and b ...`: the first falsy operand, else the last, joined over the
    paths a branch can take."""
    def run(env: Env) -> Abstract:
        seen: Abstract | None = None
        for part in parts[:-1]:
            value = part(env)
            t = truth(value)
            falsy = FALSE if isinstance(value, Iv) else value
            if t is False:
                return falsy if seen is None else join(seen, falsy)
            if t is None:
                seen = falsy if seen is None else join(seen, falsy)
        last = parts[-1](env)
        return last if seen is None else join(seen, last)
    return run


def _or(parts: Sequence[Evaluator]) -> Evaluator:
    """`a or b ...`: the first truthy operand, else the last, joined over the
    paths a branch can take."""
    def run(env: Env) -> Abstract:
        seen: Abstract | None = None
        for part in parts[:-1]:
            value = part(env)
            t = truth(value)
            if t is True:
                return value if seen is None else join(seen, value)
            if t is None:
                seen = value if seen is None else join(seen, value)
        last = parts[-1](env)
        return last if seen is None else join(seen, last)
    return run


class _Compiler:
    """An expression's tree as a closure over a branch's values: the board's
    own names - the enemy, the map, the world, the strategy's params - bound
    as constants, a six's read from the branch's Env."""

    def __init__(self, params: Mapping[str, float], static: Mapping[str, Abstract]) -> None:
        self.params, self.static = params, static

    def compile(self, node: ast.AST) -> Evaluator:
        rule = NODES.get(type(node))
        if rule is None:
            raise ValueError("no interval rule for %s" % type(node).__name__)
        return rule(self, node)

    def constant(self, node: ast.Constant) -> Evaluator:
        value = lift(node.value)
        return lambda env: value

    def name(self, node: ast.expr) -> Evaluator:
        dotted = Expr._dotted(node)
        if dotted is None or "." not in dotted:
            return lambda env: ANY                # a namespace read whole
        section, key = dotted.split(".", 1)
        if section == "params":
            value = lift(self.params.get(key, 0))
            return lambda env: value
        if dotted in self.static or section in ("enemy", "map", "world"):
            fixed = self.static.get(dotted, FALSE)     # a key a namespace lacks reads 0
            return lambda env: fixed
        return lambda env: env.get(dotted, FALSE)

    def boolop(self, node: ast.BoolOp) -> Evaluator:
        parts = [self.compile(v) for v in node.values]
        return _and(parts) if isinstance(node.op, ast.And) else _or(parts)

    def binop(self, node: ast.BinOp) -> Evaluator:
        left = self.compile(node.left)
        if isinstance(node.op, ast.Pow):
            exponent = node.right.value if isinstance(node.right, ast.Constant) else None
            if not isinstance(exponent, int | float):
                return lambda env: ANY
            power = float(exponent)
            return lambda env: _pow(left(env), power)
        right = self.compile(node.right)
        op = _BINARY[type(node.op)]
        return lambda env: op(left(env), right(env))

    def unaryop(self, node: ast.UnaryOp) -> Evaluator:
        operand, op = self.compile(node.operand), _UNARY[type(node.op)]
        return lambda env: op(operand(env))

    def compare(self, node: ast.Compare) -> Evaluator:
        """A chain `a < b <= c` holds where each link does."""
        values = [self.compile(v) for v in (node.left, *node.comparators)]
        ops = [type(op) for op in node.ops]

        def run(env: Env) -> Abstract:
            got = [v(env) for v in values]
            verdict: bool | None = True
            for i, op in enumerate(ops):
                link = compare(op, got[i], got[i + 1])
                if link is False:
                    return FALSE
                if link is None:
                    verdict = None
            return boolean(verdict)
        return run

    def ifexp(self, node: ast.IfExp) -> Evaluator:
        test, body, orelse = (self.compile(n) for n in (node.test, node.body, node.orelse))

        def run(env: Env) -> Abstract:
            t = truth(test(env))
            if t is True:
                return body(env)
            if t is False:
                return orelse(env)
            return join(body(env), orelse(env))
        return run

    def call(self, node: ast.Call) -> Evaluator:
        name = node.func.id if isinstance(node.func, ast.Name) else ""
        args = [self.compile(a) for a in node.args]
        return lambda env: _call(name, [a(env) for a in args])

    def sequence(self, node: ast.List | ast.Tuple) -> Evaluator:
        items = [self.compile(e) for e in node.elts]
        return lambda env: Seq(tuple(item(env) for item in items))


# each node type the whitelist admits (inference.expr's _RULES), and its rule
NODES: dict[type[ast.AST], Callable[..., Evaluator]] = {
    ast.Constant: _Compiler.constant, ast.BoolOp: _Compiler.boolop,
    ast.BinOp: _Compiler.binop, ast.UnaryOp: _Compiler.unaryop,
    ast.Compare: _Compiler.compare, ast.IfExp: _Compiler.ifexp, ast.Call: _Compiler.call,
    ast.List: _Compiler.sequence, ast.Tuple: _Compiler.sequence,
    ast.Attribute: _Compiler.name, ast.Name: _Compiler.name}
# the operators abstract() reads - the pow is binop's own - which must be the
# whitelist's (inference.expr: BINARY, UNARY, COMPARE); test_bounds holds it
OPERATORS = {*_BINARY, ast.Pow, *_UNARY, *COMPARISONS}


def abstract(
        expr: Expr, params: Mapping[str, float], static: Mapping[str, Abstract]) -> Evaluator:
    """An expression's value over a branch, from its source's tree (the Expr
    keeps only its code object): the board's names fixed, the six's read
    from the branch's Env."""
    return _Compiler(params, static).compile(ast.parse(expr.source, mode="eval").body)


# --- the space ------------------------------------------------------------------

class Branch(NamedTuple):
    """A node of the walk: the picks so far, locked ones included, by dense
    index, and each role still open as (role, first candidate, picks left)."""
    picks: tuple[int, ...]
    open: tuple[tuple[int, int, int], ...]


# per role, per start: a value over the candidates from there on
type Suffix[T] = list[list[T]]


def _prefix(values: Sequence[float]) -> list[float]:
    """Running sums, from the empty one: [0, v0, v0 + v1, ...]."""
    out = [0.0]
    for v in values:
        out.append(out[-1] + v)
    return out


class Space:
    """One search's heroes by dense index - the locked picks, then each role's
    candidates: released, unbanned and not locked - and, once order() has put
    each role in walk order, the suffix tables the rules read."""

    def __init__(self, objective: Objective, locked: Sequence[Hero],
                 candidates: Sequence[Sequence[Hero]]) -> None:
        self.objective = objective
        self.world, self.m, self.red = objective.world, objective.m, objective.red
        self.heroes: list[Hero] = [*locked]
        self.roles: list[list[int]] = []
        for role in candidates:
            self.roles.append(list(range(len(self.heroes), len(self.heroes) + len(role))))
            self.heroes.extend(role)
        self.locked = list(range(len(locked)))
        self.role_of = [ROLES.index(h.role) for h in self.heroes]
        self.map_style = self.m.style_top if self.m is not None else None
        self._pairs: list[list[float]] | None = None

    @property
    def candidates(self) -> list[int]:
        """Every hero an open slot can take, by dense index."""
        return [i for role in self.roles for i in role]

    def order(self, potential: Sequence[float], draws: Sequence[float]) -> None:
        """Each role's candidates in walk order: the highest potential first,
        then the highest tie-break draw, then by hero id. The order speeds
        the search - on a plateau the draws lead it to the six the tie-break
        keeps - and moves no answer."""
        for role in self.roles:
            role.sort(key=lambda i: (-potential[i], -draws[i], self.heroes[i].id))

    def pairs(self) -> list[list[float]]:
        """Every pair's synergy score (facts.team.pair_score), by dense index."""
        if self._pairs is None:
            ids = [h.id for h in self.heroes]
            self._pairs = [[0.0 if a == b else float(pair_score(self.world, a, b)) for b in ids]
                           for a in ids]
        return self._pairs

    def suffixes[T](self, of: Callable[[list[int]], T]) -> Suffix[T]:
        """A value of each role's candidates from each start on."""
        return [[of(role[start:]) for start in range(len(role) + 1)] for role in self.roles]

    def extremes(self, values: Sequence[float]) -> tuple[Suffix[list[float]], Suffix[list[float]]]:
        """Per role and start: the running sums of the largest values from
        there on, and of the smallest, TEAM_SIZE at most."""
        def top(rest: list[int]) -> list[float]:
            return _prefix(sorted((values[i] for i in rest), reverse=True)[:TEAM_SIZE])

        def bottom(rest: list[int]) -> list[float]:
            return _prefix(sorted(values[i] for i in rest)[:TEAM_SIZE])
        return self.suffixes(top), self.suffixes(bottom)

    def counts(self, branch: Branch) -> list[int]:
        """The six's count per role on every completion of the branch."""
        out = [0] * len(ROLES)
        for i in branch.picks:
            out[self.role_of[i]] += 1
        for r, _, n in branch.open:
            out[r] += n
        return out


def _slack(values: Sequence[float], count: int = TEAM_SIZE) -> float:
    """The slack of a sum of `count` of these values taken in another order:
    none where they are whole numbers, else SLACK per unit of the largest
    sum of magnitudes."""
    if all(v == int(v) for v in values if math.isfinite(v)):
        return 0.0
    return SLACK * (1.0 + count * max((abs(v) for v in values), default=0.0))


# --- the metric rules -----------------------------------------------------------

class Rule(NamedTuple):
    """How one metric reads over a branch, and the slack its interval takes
    outward on both ends."""
    read: Callable[[Branch, Env], Abstract]
    slack: float = 0.0


class Spec(NamedTuple):
    """A metric's rule as the table holds it: what builds it on a search's
    Space, and the metrics it reads, which are computed first."""
    build: Callable[[Space], Rule]
    needs: tuple[str, ...] = ()


type Feature = Callable[[Hero, Space], float]
type Known = Callable[[Hero, Space], float | None]


def _fixed(value: Abstract) -> Spec:
    """A metric every completion holds the same value of."""
    return Spec(lambda space: Rule(lambda branch, env: value))


def _sum(feature: Feature) -> Spec:
    """A sum over the six: the picks' own, plus each open role's smallest
    and largest few."""
    def build(space: Space) -> Rule:
        values = [float(feature(h, space)) for h in space.heroes]
        tops, bottoms = space.extremes(values)

        def read(branch: Branch, env: Env) -> Abstract:
            total = 0.0
            for i in branch.picks:
                total += values[i]
            lo = hi = total
            for r, start, n in branch.open:
                lo += bottoms[r][start][n]
                hi += tops[r][start][n]
            return Iv(lo, hi)
        return Rule(read, _slack(values))
    return Spec(build)


def _count(test: Callable[[Hero, Space], object]) -> Spec:
    """How many of the six pass a test."""
    return _sum(lambda h, space: 1.0 if test(h, space) else 0.0)


def _per_pick(test: Callable[[Hero, Space], object]) -> Spec:
    """The share of the six that pass a test."""
    counted = _count(test)

    def build(space: Space) -> Rule:
        rule = counted.build(space)

        def read(branch: Branch, env: Env) -> Abstract:
            return _div(rule.read(branch, env), Iv(TEAM_SIZE, TEAM_SIZE))
        return Rule(read)
    return Spec(build)


def _scaled(key: str, by: Callable[[Space], float]) -> Spec:
    """Another metric divided by a board constant; 0 where it is 0."""
    def build(space: Space) -> Rule:
        divisor = by(space)

        def read(branch: Branch, env: Env) -> Abstract:
            return _div(env[key], Iv(divisor, divisor))
        return Rule(read)
    return Spec(build, (key,))


def _ratio(numerator: str, denominator: str) -> Spec:
    """One metric over another, 0 where the second is 0."""
    return Spec(lambda space: Rule(lambda branch, env: _div(env[numerator], env[denominator])),
                (numerator, denominator))


def _roles(of: Callable[[list[int]], Abstract]) -> Spec:
    """A metric the shape fixes: read off the six's count per role."""
    return Spec(lambda space: Rule(lambda branch, env: of(space.counts(branch))))


def _known_suffixes(space: Space, values: Sequence[float | None]
                    ) -> Suffix[tuple[list[float], int]]:
    """Per role and start: the known values from there on, ascending, and how
    many candidates have none."""
    def of(rest: list[int]) -> tuple[list[float], int]:
        known = sorted(v for i in rest if (v := values[i]) is not None)
        return known, len(rest) - len(known)
    return space.suffixes(of)


def _mean(known: Known, fallback: str | None = None) -> Spec:
    """The mean of the known values among the six - 0 with none known, or
    `fallback`'s value. Over j known values among the open picks it is at
    most (the picks' sum + the j largest open) / (the picks' count + j), and
    j runs from what each role must take to what it can."""
    def build(space: Space) -> Rule:
        values = [known(h, space) for h in space.heroes]
        table = _known_suffixes(space, values)

        def read(branch: Branch, env: Env) -> Abstract:
            total, count = 0.0, 0
            for i in branch.picks:
                v = values[i]
                if v is not None:
                    total += v
                    count += 1
            highs: list[float] = []
            lows: list[float] = []
            least = most = 0
            for r, start, n in branch.open:
                asc, unknown = table[r][start]
                take = min(n, len(asc))
                highs += asc[len(asc) - take:]
                lows += asc[:take]
                least += max(0, n - unknown)
                most += take
            highs.sort(reverse=True)
            lows.sort()
            lo, hi, up, down = INF, -INF, total, total
            for j in range(most + 1):
                if j:
                    up += highs[j - 1]
                    down += lows[j - 1]
                if j < least:
                    continue
                if count + j:
                    hi = max(hi, up / (count + j))
                    lo = min(lo, down / (count + j))
                else:
                    empty = env[fallback] if fallback else FALSE
                    if not isinstance(empty, Iv):
                        return ANY
                    hi, lo = max(hi, empty.hi), min(lo, empty.lo)
            return Iv(lo, hi)
        return Rule(read, _slack([v for v in values if v is not None]))
    return Spec(build, (fallback,) if fallback else ())


def _extreme_of(known: Known, lowest: bool, default: float = 0.0) -> Spec:
    """The largest (or, `lowest`, the smallest) known value among the six;
    `default` where none is known. An open role that must take known values
    bounds the far end by the one it can least avoid."""
    def build(space: Space) -> Rule:
        values = [known(h, space) for h in space.heroes]
        table = _known_suffixes(space, values)

        def read(branch: Branch, env: Env) -> Abstract:
            picked = [v for i in branch.picks if (v := values[i]) is not None]
            near: list[float] = []            # the end every completion reaches
            far: list[float] = []             # what forces the other end
            available: list[float] = []
            none_possible = not picked
            if picked:
                near.append(min(picked) if lowest else max(picked))
                far.append(near[-1])
            for r, start, n in branch.open:
                asc, unknown = table[r][start]
                if asc:
                    near.append(asc[0] if lowest else asc[-1])
                    available.append(asc[-1] if lowest else asc[0])
                must = n - unknown
                if must > 0:
                    none_possible = False
                    far.append(asc[len(asc) - must] if lowest else asc[must - 1])
            ends: list[float] = []
            if far:
                ends.append(min(far) if lowest else max(far))
            elif available:
                ends.append(max(available) if lowest else min(available))
            if none_possible:
                near.append(default)
                ends.append(default)
            if not ends:
                return FALSE
            if lowest:
                return Iv(min(near), max(ends))
            return Iv(min(ends), max(near))
        return Rule(read)
    return Spec(build)


def _median(of: Callable[[Hero, Space], Sequence[float]], default: float = 0.0) -> Spec:
    """A median of the values the six carry lies between the least and the
    most of them; `default` where the six carries none."""
    def build(space: Space) -> Rule:
        values = [list(of(h, space)) for h in space.heroes]

        def ends(rest: list[int]) -> tuple[float, float, int]:
            flat = [v for i in rest for v in values[i]]
            return (min(flat, default=INF), max(flat, default=-INF),
                    sum(1 for i in rest if not values[i]))
        table = space.suffixes(ends)

        def read(branch: Branch, env: Env) -> Abstract:
            flat = [v for i in branch.picks for v in values[i]]
            lo, hi = min(flat, default=INF), max(flat, default=-INF)
            empty = not flat
            for r, start, n in branch.open:
                least, most, bare = table[r][start]
                lo, hi = min(lo, least), max(hi, most)
                empty = empty and bare >= n
            if empty:
                lo, hi = min(lo, default), max(hi, default)
            return Iv(lo, hi)
        return Rule(read)
    return Spec(build)


def _product(factor: Feature) -> Spec:
    """A product over the six of factors in 0..1: the picks' own times each
    open role's smallest few (the low end) and largest few (the high)."""
    def build(space: Space) -> Rule:
        values = [float(factor(h, space)) for h in space.heroes]
        if any(v < 0 for v in values):
            return Rule(lambda branch, env: WHOLE)

        def products(rest: list[int]) -> tuple[list[float], list[float]]:
            asc = sorted(values[i] for i in rest)
            low, high = [1.0], [1.0]
            for v in asc[:TEAM_SIZE]:
                low.append(low[-1] * v)
            for v in asc[::-1][:TEAM_SIZE]:
                high.append(high[-1] * v)
            return low, high
        table = space.suffixes(products)

        def read(branch: Branch, env: Env) -> Abstract:
            lo = 1.0
            for i in branch.picks:
                lo *= values[i]
            hi = lo
            for r, start, n in branch.open:
                low, high = table[r][start]
                lo *= low[n]
                hi *= high[n]
            return Iv(lo, hi)
        return Rule(read, SLACK * 2.0)
    return Spec(build)


def _pairwise(weight: Callable[[Space], list[list[float]]], per: float = 1.0) -> Spec:
    """A sum over the six's pairs, divided by `per`: the picks' own pairs,
    each open candidate's pairs with the picks, and half its best (or worst)
    pairs among the rest of the roster - each pair among the open picks is
    counted from both ends. Each role then takes its best (or worst) few."""
    def build(space: Space) -> Rule:
        matrix = weight(space)
        pool = space.candidates
        halves: list[list[tuple[float, float]]] = []     # [k][x] -> (best, worst)
        for k in range(TEAM_SIZE):
            row = []
            for x in range(len(space.heroes)):
                others = sorted(matrix[x][y] for y in pool if y != x)
                row.append((sum(others[len(others) - k:]) / 2 if k else 0.0,
                            sum(others[:k]) / 2))
            halves.append(row)
        flat = [v for row in matrix for v in row]

        def read(branch: Branch, env: Env) -> Abstract:
            picks = branch.picks
            inside = 0.0
            for a in range(len(picks)):
                for b in range(a + 1, len(picks)):
                    inside += matrix[picks[a]][picks[b]]
            lo = hi = inside
            m = sum(n for _, _, n in branch.open)
            for r, start, n in branch.open:
                half = halves[m - 1]
                best, worst = [], []
                for x in space.roles[r][start:]:
                    with_picks = 0.0
                    for p in picks:
                        with_picks += matrix[p][x]
                    best.append(with_picks + half[x][0])
                    worst.append(with_picks + half[x][1])
                best.sort(reverse=True)
                worst.sort()
                hi += sum(best[:n])
                lo += sum(worst[:n])
            return Iv(lo / per, hi / per)
        return Rule(read, _slack(flat, count=TEAM_SIZE * (TEAM_SIZE - 1) // 2) / per)
    return Spec(build)


def _masks(space: Space) -> list[int]:
    """Each hero's answers to red's picks, a bit per enemy."""
    world = space.world
    return [sum(1 << e for e, enemy in enumerate(space.red)
                if world.is_countered_by(enemy.id, h.id)) for h in space.heroes]


def _coverage(per_enemy: bool = False) -> Spec:
    """Red's picks answered by at least one of the six: at least the picks'
    own, at most what the picks and the open roles can answer between them
    and the picks' own plus each role's best few new answers. `per_enemy`
    reads it as a share of red's picks."""
    def build(space: Space) -> Rule:
        masks = _masks(space)
        enemies = len(space.red)

        def union(rest: list[int]) -> int:
            out = 0
            for i in rest:
                out |= masks[i]
            return out
        unions = space.suffixes(union)

        def read(branch: Branch, env: Env) -> Abstract:
            covered = 0
            for i in branch.picks:
                covered |= masks[i]
            reach, gain = covered, 0
            for r, start, n in branch.open:
                reach |= unions[r][start]
                news = sorted(((masks[x] & ~covered).bit_count()
                               for x in space.roles[r][start:]), reverse=True)
                gain += sum(news[:n])
            have = covered.bit_count()
            lo, hi = float(have), float(min(reach.bit_count(), have + gain))
            if per_enemy:
                return Iv(lo / enemies, hi / enemies) if enemies else FALSE
            return Iv(lo, hi)
        return Rule(read)
    return Spec(build)


def _double_covered() -> Spec:
    """Red's picks answered by two or more of the six: at least those the
    picks already answer twice, at most those the picks and each open role's
    answerers, n a role at most, can reach twice."""
    def build(space: Space) -> Rule:
        masks = _masks(space)
        enemies = range(len(space.red))
        table = space.suffixes(
            lambda rest: [sum(1 for i in rest if masks[i] >> e & 1) for e in enemies])

        def read(branch: Branch, env: Env) -> Abstract:
            have = [sum(1 for i in branch.picks if masks[i] >> e & 1) for e in enemies]
            can = list(have)
            for r, start, n in branch.open:
                for e, answerers in enumerate(table[r][start]):
                    can[e] += min(n, answerers)
            return Iv(float(sum(1 for c in have if c >= 2)), float(sum(1 for c in can if c >= 2)))
        return Rule(read)
    return Spec(build)


def _distinct_subroles() -> Spec:
    """team.subrole_diversity: the six's distinct subroles over six - at
    least the picks', at most those and every open role's, and never more
    than one per pick."""
    def build(space: Space) -> Rule:
        subroles = [h.subrole for h in space.heroes]
        table = space.suffixes(lambda rest: {subroles[i] for i in rest})

        def read(branch: Branch, env: Env) -> Abstract:
            have = {subroles[i] for i in branch.picks}
            reach = set(have)
            m = 0
            for r, start, n in branch.open:
                reach |= table[r][start]
                m += n
            return Iv(len(have) / TEAM_SIZE, min(len(reach), len(have) + m) / TEAM_SIZE)
        return Rule(read)
    return Spec(build)


def _partners(space: Space) -> tuple[list[int], list[bool], Suffix[int]]:
    """The synergy graph the wiki claims, by dense index: each hero's
    partners in the space, a bit per hero; whether it has a partner
    anywhere, which isolated counts; and each open role's candidates from
    each start on, a bit per hero."""
    index = {h.id: i for i, h in enumerate(space.heroes)}
    partners = [space.world.partners.get(h.id) or {} for h in space.heroes]
    masks = [sum(1 << index[p] for p in pair if p in index) for pair in partners]
    return masks, [bool(pair) for pair in partners], space.suffixes(
        lambda rest: sum(1 << i for i in rest))


def _bits(mask: int) -> list[int]:
    """The dense indices a mask holds."""
    out = []
    while mask:
        low = mask & -mask
        out.append(low.bit_length() - 1)
        mask ^= low
    return out


def _component(seed: int, allowed: int, masks: Sequence[int]) -> int:
    """The heroes of `allowed` the claimed pairs join to `seed`, a bit each."""
    group = frontier = 1 << seed
    while frontier:
        grown = 0
        for i in _bits(frontier):
            grown |= masks[i]
        frontier = grown & allowed & ~group
        group |= frontier
    return group


def _isolated() -> Spec:
    """team.isolated_count: the picks with a documented partner somewhere
    and none among the six. A pick is isolated on no completion where one
    of its partners is picked, and on every one where none is picked or
    left to an open role. An open candidate can be isolated only where it
    has a partner somewhere and none among the picks, so each open role
    adds at most its slots of those; and it adds at least its slots less
    the candidates that can be partnered - with no partner anywhere, or one
    among the picks or the open roles' candidates."""
    def build(space: Space) -> Rule:
        masks, partnered, unions = _partners(space)

        def read(branch: Branch, env: Env) -> Abstract:
            picked = sum(1 << i for i in branch.picks)
            reach = picked
            for r, start, _ in branch.open:
                reach |= unions[r][start]
            lo = hi = 0
            for i in branch.picks:
                if partnered[i] and not masks[i] & picked:
                    hi += 1
                    if not masks[i] & reach:
                        lo += 1
            for r, start, n in branch.open:
                rest = space.roles[r][start:]
                hi += min(n, sum(1 for x in rest if partnered[x] and not masks[x] & picked))
                lo += max(0, n - sum(1 for x in rest if not partnered[x] or masks[x] & reach))
            return Iv(float(lo), float(hi))
        return Rule(read)
    return Spec(build)


def _core() -> Spec:
    """team.core_size: the largest group the claimed pairs join among the
    six. A hero added only joins groups, so it is at least the picks'
    largest; and a group of the six lies within one group of the graph
    over the picks and every candidate the open roles have left, so it is
    at most, over those groups, the picks in one plus what each open role
    can seat there, its slots at most."""
    def build(space: Space) -> Rule:
        masks, _, unions = _partners(space)

        def largest(allowed: int, weigh: Callable[[int], int]) -> int:
            best, left = 0, allowed
            while left:
                group = _component((left & -left).bit_length() - 1, allowed, masks)
                best = max(best, weigh(group))
                left &= ~group
            return best

        def read(branch: Branch, env: Env) -> Abstract:
            picked = sum(1 << i for i in branch.picks)
            reach = picked
            for r, start, _ in branch.open:
                reach |= unions[r][start]
            lo = max(1, largest(picked, int.bit_count))
            hi = largest(reach, lambda group: (group & picked).bit_count() + sum(
                min(n, (unions[r][start] & group).bit_count()) for r, start, n in branch.open))
            return Iv(float(lo), float(max(lo, hi)))
        return Rule(read)
    return Spec(build)


def _banproof() -> Spec:
    """team.banproof_coverage: red's picks answered once the six's most
    banned pick is gone - never more than the coverage, and 0 while red
    has no picks."""
    def build(space: Space) -> Rule:
        def read(branch: Branch, env: Env) -> Abstract:
            cover = env["team.coverage"]
            if not space.red:
                return FALSE
            return Iv(0.0, cover.hi) if isinstance(cover, Iv) else ANY
        return Rule(read)
    return Spec(build, ("team.coverage",))


def _versus(feature: Callable[[Hero, Space], float]) -> Spec:
    """A sum over the six that reads red's picks, 0 while red has none."""
    return _sum(lambda h, space: feature(h, space) if space.red else 0.0)


def _answers(h: Hero, space: Space) -> float:
    return float(sum(1 for e in space.red if space.world.is_countered_by(e.id, h.id)))


def _exposures(h: Hero, space: Space) -> float:
    return float(sum(1 for e in space.red if space.world.is_countered_by(h.id, e.id)))


def _map_win(h: Hero, space: Space) -> float | None:
    return h.map_win(space.m.id) if space.m is not None else None


def _map_delta(h: Hero, space: Space) -> float | None:
    """A hero's win rate here over its own baseline, where both are known."""
    here = _map_win(h, space)
    return here - h.win if here is not None and h.win is not None else None


def _map_ban_factor(h: Hero, space: Space) -> float:
    ban = h.map_ban(space.m.id) if space.m is not None else None
    rate = h.ban if ban is None else ban
    return 1.0 - (rate or 0) / 100.0


def _on_map(on: Spec, off: Spec) -> Spec:
    """A map metric: `on` with a map set, `off` without one."""
    return Spec(lambda space: (on if space.m is not None else off).build(space),
                tuple({*on.needs, *off.needs}))


def _read(key: str) -> Spec:
    """Another metric's value, as it is."""
    return Spec(lambda space: Rule(lambda branch, env: env[key]), (key,))


TEAM_RULES: dict[str, Spec] = {
    "size": _fixed(Iv(TEAM_SIZE, TEAM_SIZE)),
    "open_slots": _fixed(FALSE),
    "tanks": _roles(lambda c: lift(c[0])),
    "damage": _roles(lambda c: lift(c[1])),
    "supports": _roles(lambda c: lift(c[2])),
    "subrole_diversity": _distinct_subroles(),
    "subroles": _fixed(Top(TEAM_SIZE)),
    "shape_flags": _roles(lambda c: Exact(shape_flags(*c))),
    "style_counts": _fixed(ANY),
    "style_top": _fixed(ANY),
    "style_lean": _fixed(ANY),
    "style_fit": _per_pick(lambda h, s: s.map_style is not None and s.map_style in h.styles),
    "shape_excess": _roles(lambda c: lift(sum(
        max(0, c[i] - EXPECTED_SHAPE[r]) for i, r in enumerate(ROLES)))),
    "pool_total": _sum(lambda h, s: h.pool + h.form_armor),
    "pool_min": _extreme_of(lambda h, s: h.pool, lowest=True),
    "weakest": _fixed(ANY),
    "armor_total": _sum(lambda h, s: h.armor + h.form_armor),
    "armor_share": _ratio("team.armor_total", "team.pool_total"),
    "shield_total": _sum(lambda h, s: h.shield),
    "shield_share": _ratio("team.shield_total", "team.pool_total"),
    "squish_count": _count(lambda h, s: h.pool <= SQUISHY_POOL),
    "squishies": _fixed(Top(TEAM_SIZE)),
    "overhealth_total": _sum(lambda h, s: h.overhealth),
    "dps_floor": _sum(lambda h, s: h.dps),
    "dps_count": _count(lambda h, s: h.dps),
    "burst_max": _extreme_of(lambda h, s: h.burst, lowest=False),
    "one_shots": _count(lambda h, s: h.burst >= SQUISHY_POOL and not h.melee),
    "burst_hero": _fixed(ANY),
    "burst_ranged": _extreme_of(lambda h, s: None if h.melee_only else h.burst, lowest=False),
    "ult_damage_total": _sum(lambda h, s: h.ult_damage),
    "dmg_ults": _count(lambda h, s: h.ult_deals_damage),
    "ult_cost_mean": _mean(lambda h, s: h.ult_cost),
    "hitscan": _count(lambda h, s: h.hitscan),
    "hitscan_reach": _count(lambda h, s: h.hitscan_range >= FLIER_REACH),
    "projectile": _count(lambda h, s: "projectile" in h.weapon_kinds),
    "beam": _count(lambda h, s: h.beam),
    "melee": _count(lambda h, s: h.melee),
    "aoe_count": _sum(lambda h, s: h.aoe_count),
    "aoe_damage_count": _sum(lambda h, s: h.aoe_damage_count),
    "range_known": _count(lambda h, s: h.max_range is not None),
    "range_median": _median(lambda h, s: [] if h.max_range is None else [h.max_range]),
    "range_max": _extreme_of(lambda h, s: h.max_range, lowest=False),
    "range_min": _extreme_of(lambda h, s: h.max_range, lowest=True),
    "dmg_amp": _count(lambda h, s: h.dmg_amp),
    "hps_floor": _sum(lambda h, s: h.hps),
    "heal_peak_total": _sum(lambda h, s: max(h.peak_heal, h.self_heal)),
    "heal_peak_supports": _sum(lambda h, s: h.peak_heal if h.role == "support" else 0.0),
    "heal_peak_max": _extreme_of(lambda h, s: h.peak_heal, lowest=False),
    "heal_ratio": _scaled("team.heal_peak_supports", lambda s: s.world.heal_bench),
    "hps_supports": _sum(lambda h, s: h.hps if h.role == "support" else 0.0),
    "hps_ratio": _scaled("team.hps_supports", lambda s: s.world.hps_bench),
    "heal_amp": _count(lambda h, s: h.heal_amp),
    "antiheal": _count(lambda h, s: h.antiheal < 0),
    "cleanse": _count(lambda h, s: h.cleanse_tools),
    "invuln": _count(lambda h, s: h.invuln_tools),
    "team_cleanse": _count(lambda h, s: h.team_cleanse_tools),
    "team_saves": _count(lambda h, s: h.save_tools),
    "lifelines": _count(lambda h, s: h.peak_heal or h.hps or h.self_heal or h.self_hps
                        or h.lifesteal),
    "cooldown_median": _median(lambda h, s: h.cooldowns),
    "cooldown_count": _sum(lambda h, s: len(h.cooldowns)),
    "cc_count": _count(lambda h, s: h.cc_tools),
    "mobility_count": _count(lambda h, s: h.mobility_tools),
    "flyers": _count(lambda h, s: h.flyer),
    "light_flyers": _count(lambda h, s: h.flyer and h.role != "tank"),
    "barrier_hp": _sum(lambda h, s: h.barrier_hp),
    "barrier_count": _count(lambda h, s: h.barrier_hp),
    "barrier_piercers": _count(lambda h, s: h.pierces_barrier),
    "pierce_dps": _sum(lambda h, s: h.dps if h.pierces_barrier else 0.0),
    "deployables": _count(lambda h, s: h.deployables),
    "synergy_edges": _pairwise(lambda s: [[1.0 if a is not b and s.world.synergy(a.id, b.id)
                                           else 0.0 for b in s.heroes] for a in s.heroes]),
    "synergy_score": _pairwise(Space.pairs),
    "synergy_density": _scaled("team.synergy_edges",
                               lambda s: TEAM_SIZE * (TEAM_SIZE - 1) // 2),
    "isolated_count": _isolated(),
    "isolated": _fixed(Top(TEAM_SIZE)),
    "core_size": _core(),
    "pairs": _fixed(Top(TEAM_SIZE * (TEAM_SIZE - 1) // 2)),
    "unwritten_pairs": _fixed(Top(TEAM_SIZE * (TEAM_SIZE - 1) // 2)),
    "unwritten_cells": _pairwise(lambda s: [[float(s.world.unwritten_cells(a.id, b.id))
                                             if a is not b else 0.0 for b in s.heroes]
                                            for a in s.heroes]),
    "win_mean": _mean(lambda h, s: h.win),
    "pick_mass": _sum(lambda h, s: h.pick or 0),
    "availability": _product(lambda h, s: 1.0 - (h.ban or 0) / 100.0),
    "map_availability": _product(_map_ban_factor),
    "max_ban_rate": _extreme_of(lambda h, s: h.ban or 0, lowest=False),
    "max_ban_hero": _fixed(ANY),
    "rank_sensitive_count": _count(lambda h, s: h.rank_spread >= RANK_SENSITIVE),
    "trend_sum": _sum(lambda h, s: h.trend if h.trend is not None else 0.0),
    "map_win_mean": _on_map(_mean(_map_win, "team.win_mean"), _read("team.win_mean")),
    "map_pick_mass": _on_map(_sum(lambda h, s: h.map_pick(s.m.id) or 0 if s.m else 0),
                             _read("team.pick_mass")),
    "map_specialists": _on_map(_count(lambda h, s: (d := _map_delta(h, s)) is not None
                                      and d >= SPECIALIST_DELTA), _fixed(FALSE)),
    "map_offmap": _on_map(_count(lambda h, s: (d := _map_delta(h, s)) is not None
                                 and d <= -SPECIALIST_DELTA), _fixed(FALSE)),
    "home_map_hits": _on_map(_count(lambda h, s: s.m is not None and s.m.id in h.best_maps),
                             _fixed(FALSE)),
    "coverage": _coverage(),
    "coverage_share": _coverage(per_enemy=True),
    "unanswered": _fixed(Top(TEAM_SIZE)),
    "answer_edges": _versus(_answers),
    "exposure_edges": _versus(_exposures),
    "exposed_count": _versus(lambda h, s: 1.0 if _exposures(h, s) else 0.0),
    "exposed": _fixed(Top(TEAM_SIZE)),
    "safe_count": _versus(lambda h, s: 0.0 if _exposures(h, s) else 1.0),
    "net_edges": _versus(lambda h, s: _answers(h, s) - _exposures(h, s)),
    "double_covered": _double_covered(),
    "banproof_coverage": _banproof(),
}


def _red(space: Space, key: str) -> float:
    """One of red's team metrics, a number."""
    return float(number(space.objective.red_t[key]))


def _less_red(key: str, red: str) -> Spec:
    """A metric of the six less one of red's."""
    def build(space: Space) -> Rule:
        theirs = _red(space, red)
        return Rule(lambda branch, env: _sub(env[key], Iv(theirs, theirs)))
    return Spec(build, (key,))


def _red_less(red: str, key: str) -> Spec:
    """One of red's metrics less the six's."""
    def build(space: Space) -> Rule:
        theirs = _red(space, red)
        return Rule(lambda branch, env: _sub(Iv(theirs, theirs), env[key]))
    return Spec(build, (key,))


def _chew_ours() -> Spec:
    """matchup.chew_time_ours: red's pool over the six's damage, 999 where
    either is 0."""
    def build(space: Space) -> Rule:
        pool = _red(space, "pool_total")

        def read(branch: Branch, env: Env) -> Abstract:
            dps = env["team.dps_floor"]
            if not pool:
                return Iv(999.0, 999.0)
            if not isinstance(dps, Iv):
                return ANY
            out = _div(Iv(pool, pool), dps)
            return join(out, Iv(999.0, 999.0)) if dps.lo <= 0 <= dps.hi else out
        return Rule(read)
    return Spec(build, ("team.dps_floor",))


def _chew_theirs() -> Spec:
    """matchup.chew_time_theirs: the six's pool over red's damage, 999 where
    either is 0."""
    def build(space: Space) -> Rule:
        dps = _red(space, "dps_floor")

        def read(branch: Branch, env: Env) -> Abstract:
            pool = env["team.pool_total"]
            if not dps:
                return Iv(999.0, 999.0)
            if not isinstance(pool, Iv):
                return ANY
            out = _div(pool, Iv(dps, dps))
            return join(out, Iv(999.0, 999.0)) if pool.lo <= 0 <= pool.hi else out
        return Rule(read)
    return Spec(build, ("team.pool_total",))


def _range_diff() -> Spec:
    """matchup.range_diff: the six's median reach less red's, 0 where either
    side publishes none."""
    def build(space: Space) -> Rule:
        red_known = _red(space, "range_known")
        red_median = _red(space, "range_median")

        def read(branch: Branch, env: Env) -> Abstract:
            known, median = env["team.range_known"], env["team.range_median"]
            if not red_known or not isinstance(known, Iv):
                return FALSE if not red_known else ANY
            gap = _sub(median, Iv(red_median, red_median))
            if known.lo >= 1:
                return gap
            return FALSE if known.hi < 1 else join(gap, FALSE)
        return Rule(read)
    return Spec(build, ("team.range_known", "team.range_median"))


def _heal_need() -> Spec:
    """matchup.heal_need: monotone in the six's pool (compute.heal_need)."""
    def build(space: Space) -> Rule:
        read_red = compute.heal_read(space.world, space.objective.red_t)

        def read(branch: Branch, env: Env) -> Abstract:
            pool = env["team.pool_total"]
            if not isinstance(pool, Iv):
                return ANY
            ends = (compute.heal_need(read_red, pool.lo), compute.heal_need(read_red, pool.hi))
            return Iv(min(ends), max(ends))
        return Rule(read)
    return Spec(build, ("team.pool_total",))


def _heal_shortfall() -> Spec:
    """matchup.heal_shortfall: monotone in the need and in the healing, so
    its range over a box is its range over the box's corners."""
    def read(branch: Branch, env: Env) -> Abstract:
        need, healing = env["matchup.heal_need"], env["team.hps_floor"]
        if not (isinstance(need, Iv) and isinstance(healing, Iv)):
            return ANY
        corners = [compute.heal_shortfall(n, h) for n in (need.lo, need.hi)
                   for h in (healing.lo, healing.hi)]
        return Iv(min(corners), max(corners))
    return Spec(lambda space: Rule(read, SLACK * 4.0), ("matchup.heal_need", "team.hps_floor"))


MATCHUP_RULES: dict[str, Spec] = {
    "pool_diff": _less_red("team.pool_total", "pool_total"),
    "dps_diff": _less_red("team.dps_floor", "dps_floor"),
    "hps_diff": _less_red("team.hps_floor", "hps_floor"),
    "burst_vs_heal": _less_red("team.burst_max", "heal_peak_max"),
    "heal_vs_burst": _less_red("team.heal_peak_max", "burst_max"),
    "chew_time_ours": _chew_ours(),
    "chew_time_theirs": _chew_theirs(),
    "tempo_diff": _red_less("cooldown_median", "team.cooldown_median"),
    "range_diff": _range_diff(),
    "exposure_share": _scaled("team.exposed_count", lambda s: TEAM_SIZE),
    "ult_answers": _sum(lambda h, s: float(bool(h.invuln_tools)) + float(bool(h.cleanse_tools))),
    "heal_need": _heal_need(),
    "heal_shortfall": _heal_shortfall(),
}

# every metric a branch can read, by its dotted key
RULES: dict[str, Spec] = {
    **{"team." + k: v for k, v in TEAM_RULES.items()},
    **{"matchup." + k: v for k, v in MATCHUP_RULES.items()}}


def plan(space: Space, keys: Sequence[str]) -> list[tuple[str, Rule]]:
    """The rules for `keys` and what they read, each after its needs."""
    ordered: list[tuple[str, Rule]] = []
    seen: set[str] = set()

    def visit(key: str) -> None:
        if key in seen:
            return
        seen.add(key)
        spec = RULES[key]
        for need in spec.needs:
            visit(need)
        ordered.append((key, spec.build(space)))
    for key in sorted(keys):
        visit(key)
    return ordered


def evaluate(steps: Sequence[tuple[str, Rule]], branch: Branch) -> Env:
    """A branch's Env: each planned metric's range, its slack outward."""
    env: Env = {}
    for key, rule in steps:
        value = rule.read(branch, env)
        if rule.slack and isinstance(value, Iv):
            value = Iv(value.lo - rule.slack, value.hi + rule.slack)
        env[key] = value
    return env


# --- the objective's bound ------------------------------------------------------

class Frame(NamedTuple):
    """The walk's state at a node: the picks so far by dense index, the
    default engine's own part of them, their pairs, and each hero's pairs
    with them (None where synergy weighs nothing)."""
    picks: tuple[int, ...]
    own: float
    paired: float
    partners: list[float] | None


class _Heuristic(NamedTuple):
    """A heuristic as the bound reads it: its metric, its frozen scale, and
    its gate - settled for the board, or read off the branch."""
    metric: str
    norm: Norm
    gate: bool | None
    when: Evaluator | None
    fixed: Abstract | None         # a metric the board settles


class _Scored(NamedTuple):
    """A scored heuristic as the bound reads it."""
    weight: float
    gate: bool | None
    when: Evaluator | None
    bonus: Evaluator | None
    penalty: Evaluator | None


def _board_values(objective: Objective) -> dict[str, Abstract]:
    """The names a board settles - the enemy's, the map's and the world's
    metrics - each as a value."""
    return {"%s.%s" % (section, key): lift(value)
            for section, bag in objective.static.items() for key, value in bag.items()}


def _six_names(expr: Expr | None) -> set[str]:
    """The team.* and matchup.* names an expression reads."""
    if expr is None:
        return set()
    return {n for n in expr.names if n.split(".", 1)[0] in ("team", "matchup")}


class Bound:
    """The objective's bound over the walk's branches on one Space: the
    default engine's terms jointly, then every heuristic and scored term of
    the playbook apart, summed in the order the score sums them. It orders
    the Space's candidates by their potential - a pick's own part of the
    engine plus half its five best pairs - as it is built.

    The swap search's keep term (Objective.keep) is a pick's own part too:
    `swap` for a reference hero, nothing for another, added to the engine's
    own parts - or alone, with the engine off - so the bound carries it
    exactly, and the walk takes the reference heroes first. The score
    multiplies it once where the bound sums it hero by hero; the engine's
    slack, which counts every own part's magnitude, covers the difference."""

    def __init__(self, objective: Objective, space: Space) -> None:
        self.space = space
        heroes = space.heroes
        base = objective.base
        pool = space.candidates
        self.own: list[float] | None = None
        self.pairs: list[list[float]] | None = None
        self.halves: list[list[float]] = []
        self.engine_slack = 0.0
        kept = [objective.swap if h.id in objective.keep else 0.0 for h in heroes]
        if base is None and objective.keep:
            self.own = kept
        if base is not None:
            self.own = [base.unary(h, TEAM_SIZE) + k for h, k in zip(heroes, kept, strict=True)]
            weight = base.scaled.synergy
            if weight:
                self.pairs = [[weight * v for v in row] for row in space.pairs()]
                for k in range(TEAM_SIZE):
                    row = []
                    for x in range(len(heroes)):
                        others = sorted((self.pairs[x][y] for y in pool if y != x), reverse=True)
                        row.append(sum(others[:k]) / 2)
                    self.halves.append(row)
        if self.own is not None:
            largest = sorted((abs(v) for v in self.own), reverse=True)[:TEAM_SIZE]
            spread = max((abs(v) for row in self.pairs for v in row), default=0.0) \
                if self.pairs else 0.0
            self.engine_slack = SLACK * (1.0 + sum(largest) + 15 * spread)
            potential = [self.own[x] + (self.halves[TEAM_SIZE - 1][x] if self.halves else 0.0)
                         for x in range(len(heroes))]
        else:
            potential = [0.0] * len(heroes)
        self.draws = [objective.draws[h.id] for h in heroes]
        space.order(potential, self.draws)
        self._own_tops = space.extremes(self.own)[0] if self.own is not None else None
        self._draw_tops = space.extremes(self.draws)[0]
        self._terms(objective)

    def _terms(self, objective: Objective) -> None:
        """The playbook's terms, each compiled over abstract values, and the
        metrics they read planned."""
        static = _board_values(objective)
        reads: set[str] = set()
        self.limits: list[Evaluator] = []
        for s in objective.limits:
            if s.require is not None and not is_shape_limit(s):
                self.limits.append(abstract(s.require, s.params, static))
                reads |= _six_names(s.require)
        self.heuristics: list[_Heuristic] = []
        for norm in objective.norms:
            g = norm.strategy
            gate = objective.gates[g.id]
            metric = g.metric or ""
            if gate is False:
                continue
            fixed = None
            if metric.split(".", 1)[0] in ("team", "matchup"):
                reads.add(metric)
            else:                                   # a key the namespace lacks reads 0
                fixed = static.get(metric, FALSE)
            when = None
            if gate is None and g.when is not None:
                when = abstract(g.when, g.params, static)
                reads |= _six_names(g.when)
            self.heuristics.append(_Heuristic(metric, norm, gate, when, fixed))
        self.scored: list[_Scored] = []
        for r in objective.scored:
            gate = objective.gates[r.id]
            if gate is False or not r.weight:
                continue
            compiled = [abstract(e, r.params, static) if e is not None else None
                        for e in (r.when if gate is None else None, r.bonus, r.penalty)]
            reads |= _six_names(r.when if gate is None else None)
            reads |= _six_names(r.bonus) | _six_names(r.penalty)
            self.scored.append(_Scored(r.weight, gate, *compiled))
        self.steps = plan(self.space, sorted(reads))

    # --- the walk's state ---------------------------------------------------

    def start(self) -> Frame:
        """The frame of the locked picks."""
        frame = Frame((), 0.0, 0.0, [0.0] * len(self.space.heroes) if self.pairs else None)
        for x in self.space.locked:
            frame = self.push(frame, x)
        return frame

    def push(self, frame: Frame, x: int) -> Frame:
        """The frame with one more pick."""
        own = frame.own + self.own[x] if self.own is not None else 0.0
        partners = frame.partners
        if partners is None or self.pairs is None:
            return Frame((*frame.picks, x), own, 0.0, None)
        row = self.pairs[x]
        return Frame((*frame.picks, x), own, frame.paired + partners[x],
                     [a + b for a, b in zip(partners, row, strict=True)])

    # --- the bound ------------------------------------------------------------

    def engine(self, frame: Frame, open_roles: tuple[tuple[int, int, int], ...]) -> float:
        """The default engine's bound: the picks' own parts and pairs, then
        each open role's best few by their own part, their pairs with the
        picks and half their best pairs among the rest."""
        if self.own is None:
            return 0.0
        total = frame.own + frame.paired
        m = sum(n for _, _, n in open_roles)
        if frame.partners is None or self._own_tops is None or not m:
            if self._own_tops is not None:
                for r, start, n in open_roles:
                    total += self._own_tops[r][start][n]
            return total + self.engine_slack
        own, partners, half = self.own, frame.partners, self.halves[m - 1]
        for r, start, n in open_roles:
            values = sorted((own[x] + partners[x] + half[x]
                             for x in self.space.roles[r][start:]), reverse=True)
            total += sum(values[:n])
        return total + self.engine_slack

    def of(self, frame: Frame, open_roles: tuple[tuple[int, int, int], ...]) -> float | None:
        """The most any completion of the branch scores; None where a limit
        fails on every completion."""
        env = evaluate(self.steps, Branch(frame.picks, open_roles))
        for limit in self.limits:
            if truth(limit(env)) is False:
                return None
        total = self.engine(frame, open_roles)
        for h in self.heuristics:
            gate = h.gate if h.gate is not None else (
                truth(h.when(env)) if h.when is not None else True)
            if gate is False:
                continue
            total += self._heuristic(h, env, gate)
        for s in self.scored:
            total += self._scored(s, env)
        return total

    @staticmethod
    def _heuristic(h: _Heuristic, env: Env, gate: bool | None) -> float:
        """A heuristic's most on the branch: its norm at the metric's better
        end; a need never pays, so one whose guard may not hold costs 0."""
        norm = h.norm
        raw = h.fixed if h.fixed is not None else env.get(h.metric, FALSE)
        if norm.span is None:
            value = 1.0 if norm.need else 0.5
        elif isinstance(raw, Iv):
            value = normalised(raw.lo if norm.minimize else raw.hi, norm.low, norm.span,
                               norm.minimize, norm.need)
        else:
            value = 1.0
        weighted = norm.weight * (value - 1.0) if norm.need else norm.weight * value
        return max(0.0, weighted) if gate is None else weighted

    @staticmethod
    def _scored(s: _Scored, env: Env) -> float:
        """A scored heuristic's most on the branch: its weight times the
        bonus's high end less the penalty's low end, where the gate holds;
        0 where it need not."""
        gate = s.gate if s.gate is not None else truth(s.when(env)) if s.when else True
        if gate is False:
            return 0.0
        bonus = s.bonus(env) if s.bonus is not None else FALSE
        penalty = s.penalty(env) if s.penalty is not None else FALSE
        if not (isinstance(bonus, Iv) and isinstance(penalty, Iv)):
            return INF
        top = s.weight * (bonus.hi - penalty.lo)
        top += SLACK * (1.0 + s.weight * (max(abs(bonus.lo), abs(bonus.hi))
                                          + max(abs(penalty.lo), abs(penalty.hi))))
        if top != top:
            return INF
        return max(0.0, top) if gate is None else top

    def tiebreak(self, frame: Frame, open_roles: tuple[tuple[int, int, int], ...]) -> float:
        """The highest tie-break any completion of the branch holds: the
        picks' draws, then each open role's largest from its start on - exact,
        as the draws are whole numbers far below 2**53."""
        total = sum(self.draws[x] for x in frame.picks)
        for r, start, n in open_roles:
            total += self._draw_tops[r][start][n]
        return total


def roster(world: World, locked: Sequence[Hero], banned: set[int]) -> list[list[Hero]]:
    """Each role's candidates for the open slots: released, unbanned and not
    locked, by hero id."""
    taken = {h.id for h in locked} | banned
    return [sorted((h for h in world.heroes.values()
                    if h.role == role and h.released and h.id not in taken),
                   key=lambda h: h.id) for role in ROLES]

