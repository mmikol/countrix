"""The search's bounds: the most any six a branch of the search can still
reach scores, read off the picks made so far and the candidates each open
role has left. The walk (inference.solver) drops a branch whose bound cannot
enter the top K, so a bound that ever read below a six it covers would lose
that six without a word: every rule here is sound by construction, and
tests/verification/inference/test_bounds.py holds each to it on random branches.
What a value can be over a branch is inference.intervals, and each metric's
range over a branch is inference.ranges.

    Frame                 the walk's state at a node: the picks so far and the
                          default engine's parts of them
    Bound                 the objective over a branch, summed in the order the
                          score sums it: the default engine's terms jointly -
                          each open pick's own part, its pairs with the picks
                          made, and half its best pairs among the rest - with
                          the swap search's keep term in each pick's own part,
                          then each heuristic and each scored term apart
    roster                each role's candidates for the open slots

Floating point: a metric's slack is inference.ranges'; every other step is
a monotone float operation taken at the right end of an interval, and the
terms add up in the score's own order, so a six's computed score never
exceeds its branch's computed bound.
"""

from collections.abc import Sequence
from typing import NamedTuple

from facts.draft import TEAM_SIZE
from facts.model import ROLES, Hero, World
from inference.expr import Expr
from inference.intervals import FALSE, INF, Abstract, Env, Evaluator, Iv, abstract, lift, truth
from inference.ranges import (
    PAIR_COUNT,
    SLACK,
    Branch,
    Open,
    Space,
    evaluate,
    pair_halves,
    rule_order,
)
from inference.scoring import Norm, Objective, normalised
from inference.shapes import is_shape_limit


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


def _gate(gate: bool | None, when: Evaluator | None, env: Env) -> bool | None:
    """A term's gate over a branch: the board's where it settles it, else
    its `when` read off the branch - None where its sixes may go either
    way - else open."""
    if gate is not None:
        return gate
    return truth(when(env)) if when is not None else True


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
        base = objective.engine
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
                self.halves = [[best for best, _ in row]
                               for row in pair_halves(self.pairs, pool, len(heroes))]
        if self.own is not None:
            largest = sorted((abs(v) for v in self.own), reverse=True)[:TEAM_SIZE]
            spread = max((abs(v) for row in self.pairs for v in row), default=0.0) \
                if self.pairs else 0.0
            self.engine_slack = SLACK * (1.0 + sum(largest) + PAIR_COUNT * spread)
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
        self.steps = rule_order(self.space, sorted(reads))

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

    def engine(self, frame: Frame, open_roles: Open) -> float:
        """The default engine's bound: the picks' own parts and pairs, then
        each open role's best few by their own part, their pairs with the
        picks and half their best pairs among the rest."""
        tops = self._own_tops
        if self.own is None or tops is None:
            return 0.0
        total = frame.own + frame.paired
        m = sum(n for _, _, n in open_roles)
        if frame.partners is None or not m:
            for r, start, n in open_roles:
                total += tops[r][start][n]
            return total + self.engine_slack
        own, partners, half = self.own, frame.partners, self.halves[m - 1]
        for r, start, n in open_roles:
            values = sorted((own[x] + partners[x] + half[x]
                             for x in self.space.roles[r][start:]), reverse=True)
            total += sum(values[:n])
        return total + self.engine_slack

    def of(self, frame: Frame, open_roles: Open) -> float | None:
        """The most any completion of the branch scores; None where a limit
        fails on every completion."""
        env = evaluate(self.steps, Branch(frame.picks, open_roles))
        for limit in self.limits:
            if truth(limit(env)) is False:
                return None
        total = self.engine(frame, open_roles)
        for h in self.heuristics:
            gate = _gate(h.gate, h.when, env)
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
        gate = _gate(s.gate, s.when, env)
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

    def tiebreak(self, frame: Frame, open_roles: Open) -> float:
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
