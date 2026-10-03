"""What a value can be over a branch of the search, and an expression read
over such values. The search (inference.solver) bounds a branch before it
knows the six, so every value here covers each completion of the branch: a
bound read off them never falls below a six it covers.

    Iv, Exact, Seq, Top   what a value can be over a branch: every number
                          lo..hi (a bool is 0 or 1), one value known exactly
                          (a name, a list), a display of values, or anything -
                          a list at most `size` long where that is known
    subtract, divide      the interval operations the metric rules
                          (inference.ranges) read as well
    abstract              an expression read over those values, one rule for
                          each node type and operator the whitelist admits
                          (inference.expr): an operator takes the ends of its
                          operands' intervals, a comparison is true, false or
                          either, and `and`, `or` and `if` join the outcomes
                          they can take
"""

import ast
import math
import operator
from collections.abc import Callable, Mapping, Sequence
from typing import NamedTuple

from inference.expr import FUNCTIONS, Expr

INF = math.inf


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


def subtract(a: Abstract, b: Abstract) -> Abstract:
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


def divide(a: Abstract, b: Abstract) -> Abstract:
    """A division reads 0 at a zero divisor (inference.expr's divide)."""
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
    for a quotient that rounded up across a whole number - one that
    underflowed to 0 among them. Exactly 0 only where the dividend or the
    divisor is: the zero-safe division's 0."""
    q = divide(a, b)
    if not isinstance(q, Iv) or a == FALSE or b == FALSE:
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
    ast.Add: _add, ast.Sub: subtract, ast.Mult: _mul, ast.Div: divide,
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
            # Exact values are objects to mypy: one kind orders, and mixed
            # kinds raise TypeError, caught below
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
            return lift(FUNCTIONS[name](*(a.value for a in args if isinstance(a, Exact))))
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
