"""The legal shapes: the (tanks, damage, supports) triples the queue allows -
at most MAX_TANKS tanks, whatever the playbook holds - and the playbook's
shape-only limits allow (its own rule of form, 2-2-2 say), around whatever
picks are locked.
"""

from collections.abc import Iterable, Sequence
from typing import NamedTuple

from facts.draft import MAX_TANKS, TEAM_SIZE
from inference.expr import Expr, scope
from inference.strategy import Strategy

SHAPE_KEYS = {"team.tanks", "team.damage", "team.supports", "team.size", "team.open_slots"}


class Shape(NamedTuple):
    """A team's count per role: a six's shape, or the picks locked so far."""
    tanks: int
    damage: int
    supports: int


NO_PICKS = Shape(tanks=0, damage=0, supports=0)


def legal_shapes(catalog: Iterable[Strategy], locked: Shape = NO_PICKS) -> list[Shape]:
    """(tanks, damage, supports) triples the queue allows - at most MAX_TANKS
    tanks, whatever the playbook holds - and the catalog's shape-only limits
    allow (a playbook's own rule of form, 2-2-2 say), only those that
    can still seat the `locked` picks. The board carries the full list so the
    roster can refuse a pick no legal six could seat."""
    limits = _shape_limits(catalog)
    out: list[Shape] = []
    for t in range(MAX_TANKS + 1):
        for d in range(TEAM_SIZE + 1 - t):
            s = TEAM_SIZE - t - d
            if t < locked.tanks or d < locked.damage or s < locked.supports:
                continue
            if _shape_allowed(t, d, s, limits):
                out.append(Shape(tanks=t, damage=d, supports=s))
    return out


def is_shape_limit(strategy: Strategy) -> bool:
    """Whether a strategy is a limit that reads only a six's shape. A dial
    the limit reads (`params.MAX_SUPPORTS`) is its own number, not the
    six's, so it leaves the limit a shape limit. legal_shapes applies these
    whole, so the search never meets a six that breaks one."""
    return (strategy.form == "limit" and strategy.require is not None
            and {n for n in strategy.require.names if not n.startswith("params.")}
            <= SHAPE_KEYS)


def _shape_limits(catalog: Iterable[Strategy]) -> list[tuple[Strategy, Expr]]:
    """The catalog's shape limits, each with its require."""
    return [(strategy, strategy.require) for strategy in catalog
            if is_shape_limit(strategy) and strategy.require is not None]


def _shape_allowed(t: int, d: int, s: int, limits: Sequence[tuple[Strategy, Expr]]) -> bool:
    """Whether a (tanks, damage, supports) triple meets every shape limit."""
    stub = scope({"team": {"tanks": t, "damage": d, "supports": s,
                           "size": TEAM_SIZE, "open_slots": 0}})
    for strategy, require in limits:
        stub["params"] = strategy.params_section
        if not bool(require.evaluate(stub)):
            return False
    return True
