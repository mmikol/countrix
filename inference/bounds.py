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
    Bound                 the objective over a branch (of): the default
                          engine's terms jointly - each open pick's own part,
                          its pairs with the picks made, and half its best
                          pairs among the rest - with the swap search's keep
                          term in each pick's own part, then each heuristic
                          and each scored term apart, in the order the score
                          sums them; and the bounds the walk asks of a branch,
                          cheapest first (bounds): that engine bound with
                          every other term at its shape's root, of, and the
                          fold - the engine and the terms on per-pick 0/1
                          counts bounded together, the heaviest first, on
                          FOLD_COUNTS counts at most
    roster                each role's candidates for the open slots

Floating point: a metric's slack is inference.ranges'; every other step is
a monotone float operation taken at the right end of an interval, and the
terms add up in the score's own order, so a six's computed score never
exceeds its branch's computed bound. The fold alone adds them in another
order, and carries SLACK per unit of each term's magnitude it moves, beside
the engine's own slack.
"""

import itertools
from collections.abc import Callable, Iterable, Iterator, Sequence
from typing import NamedTuple

from facts.draft import TEAM_SIZE
from facts.model import ROLES, Hero, World
from inference.expr import Expr
from inference.intervals import FALSE, INF, Abstract, Env, Evaluator, Iv, abstract, lift, truth
from inference.ranges import (
    PAIR_COUNT,
    RULES,
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

MEMO_CAP = 4096                   # a term's bounds memoised before its memo starts afresh
FOLD_COUNTS = 4                   # the most counts the fold reads, the heaviest rules first

# what the fold's counts are on a six or added by open picks: one per folded count
type Vector = tuple[float, ...]


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

    @property
    def weight(self) -> float:
        """Its weight, the most it moves a six."""
        return self.norm.weight

    def most(self, env: Env) -> float:
        """Its most on a branch: 0 where its gate is shut on every
        completion, else its norm at the metric's better end; a need never
        pays, so one whose guard may not hold costs 0."""
        gate = _gate(self.gate, self.when, env)
        if gate is False:
            return 0.0
        norm = self.norm
        raw = self.fixed if self.fixed is not None else env.get(self.metric, FALSE)
        if norm.span is None:
            value = 1.0 if norm.need else 0.5
        elif isinstance(raw, Iv):
            value = normalised(raw.lo if norm.minimize else raw.hi, norm.low, norm.span,
                               norm.minimize, norm.need)
        else:
            value = 1.0
        weighted = norm.weight * (value - 1.0) if norm.need else norm.weight * value
        return max(0.0, weighted) if gate is None else weighted


class _Scored(NamedTuple):
    """A scored heuristic as the bound reads it."""
    weight: float
    gate: bool | None
    when: Evaluator | None
    bonus: Evaluator | None
    penalty: Evaluator | None

    def most(self, env: Env) -> float:
        """Its most on a branch: its weight, never below 0, times the
        bonus's high end less the penalty's low end where the gate holds; 0
        where it is shut, and at least 0 where it may not hold."""
        gate = _gate(self.gate, self.when, env)
        if gate is False:
            return 0.0
        bonus = self.bonus(env) if self.bonus is not None else FALSE
        penalty = self.penalty(env) if self.penalty is not None else FALSE
        if not (isinstance(bonus, Iv) and isinstance(penalty, Iv)):
            return INF
        top = self.weight * (bonus.hi - penalty.lo)
        top += SLACK * (1.0 + self.weight * (max(abs(bonus.lo), abs(bonus.hi))
                                             + max(abs(penalty.lo), abs(penalty.hi))))
        if top != top:
            return INF
        return max(0.0, top) if gate is None else top


class _Term(NamedTuple):
    """A heuristic or a scored term as the walk reads it: its most over a
    branch, read off the branch's Env alone; the team.* and matchup.* names
    it reads there; whether the six's shape alone fixes them all
    (ranges.Spec.shaped), so that its most is the same on every branch of a
    shape; and its weight, which orders the terms the fold takes."""
    most: Callable[[Env], float]
    reads: tuple[str, ...]
    shaped: bool
    weight: float


class _Fold(NamedTuple):
    """A term the fold bounds with the default engine: its place among the
    terms, and the places among the fold's counts of the counts it reads,
    in its reads' order."""
    term: int
    slots: tuple[int, ...]


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


def _added(first: float, rest: Iterable[float]) -> float:
    """`first`, then each of `rest` added one at a time in order, as the
    score adds its terms: each step is monotone, so a bound of each term
    added in this order bounds the score's sum."""
    total = first
    for value in rest:
        total += value
    return total


def _by_counts(
        candidates: Iterable[tuple[float, Vector]], n: int,
        caps: Sequence[float]) -> dict[Vector, float]:
    """The most n of the candidates add up to, by the counts they add, each
    count stopped at its cap. Candidates of one pattern of counts add the
    same counts, so n picks that take k of a pattern are worth most with its
    k best; every way of sharing n among the patterns is tried, and each
    vector keeps the most of the ways that reach it."""
    groups: dict[Vector, list[float]] = {}
    for value, pattern in candidates:
        groups.setdefault(pattern, []).append(value)
    zero: Vector = (0.0,) * len(caps)
    taken: dict[tuple[int, Vector], float] = {(0, zero): 0.0}
    for pattern, values in groups.items():
        values.sort(reverse=True)
        best = list(itertools.accumulate(values[:n], initial=0.0))
        grown: dict[tuple[int, Vector], float] = {}
        for (used, counts), value in taken.items():
            for k in range(min(n - used, len(best) - 1) + 1):
                state = (used + k, tuple([min(cap, a + k * b) for a, b, cap
                                          in zip(counts, pattern, caps, strict=True)]))
                if value + best[k] > grown.get(state, -INF):
                    grown[state] = value + best[k]
        taken = grown
    return {counts: value for (used, counts), value in taken.items() if used == n}


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
    slack, which counts every own part's magnitude, covers the difference.

    What a term reads decides its most, so each term's most is memoised on
    the values it reads, and a term on the shape alone is read once a
    shape: the walk meets the same few values on branch after branch."""

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
        self._plan_fold()

    def _terms(self, objective: Objective) -> None:
        """The playbook's terms, each compiled over abstract values, and the
        metrics they read planned: those a term on the shape alone reads
        apart, read once a shape (_shaped)."""
        static = _board_values(objective)
        reads: set[str] = set()
        self.limits: list[Evaluator] = []
        for s in objective.limits:
            if s.require is not None and not is_shape_limit(s):
                self.limits.append(abstract(s.require, s.params, static))
                reads |= _six_names(s.require)
        compiled: list[tuple[_Heuristic | _Scored, set[str]]] = []
        for norm in objective.norms:
            g = norm.strategy
            gate = objective.gates[g.id]
            metric = g.metric or ""
            if gate is False:
                continue
            fixed = None
            names: set[str] = set()
            if metric.split(".", 1)[0] in ("team", "matchup"):
                names.add(metric)
            else:                                   # a key the namespace lacks reads 0
                fixed = static.get(metric, FALSE)
            when = None
            if gate is None and g.when is not None:
                when = abstract(g.when, g.params, static)
                names |= _six_names(g.when)
            compiled.append((_Heuristic(metric, norm, gate, when, fixed), names))
        for r in objective.scored:
            gate = objective.gates[r.id]
            if gate is False or not r.weight:
                continue
            guard = r.when if gate is None else None
            evaluators = [abstract(e, r.params, static) if e is not None else None
                          for e in (guard, r.bonus, r.penalty)]
            names = _six_names(guard) | _six_names(r.bonus) | _six_names(r.penalty)
            compiled.append((_Scored(r.weight, gate, *evaluators), names))
        shaped: set[str] = set()
        self.terms: list[_Term] = []
        for term, names in compiled:
            alone = all(RULES[n].shaped for n in names)
            (shaped if alone else reads).update(names)
            self.terms.append(_Term(term.most, tuple(sorted(names)), alone, term.weight))
        self.steps = rule_order(self.space, sorted(reads))
        self.shape_steps = rule_order(self.space, sorted(shaped))
        self._any_shaped = any(t.shaped for t in self.terms)
        self._memos: list[dict[tuple[Abstract, ...], float]] = [{} for _ in self.terms]
        self._by_shape: dict[tuple[int, ...], list[float]] = {}
        self._roots: dict[Open, list[float] | None] = {}

    def _plan_fold(self) -> None:
        """The terms the fold bounds with the default engine: of those that
        read a name and nothing but per-pick 0/1 counts - sums whose each
        hero's part (ranges.Spec.feature) is 0 or 1 on this space - so that
        on a six their most is a function of the counts the six holds, the
        heaviest first, ties in the score's order, each where it and those
        taken before it read FOLD_COUNTS counts or fewer; and those counts'
        parts of each hero, by dense index. A sum's rule is exact on a full
        six, so a six's count is its heroes' parts added up. The vectors the
        fold weighs multiply with each count it reads, so past a few it costs
        the walk more than it saves; a term it leaves out is bounded apart,
        as of() bounds it, and the heaviest can move a six most."""
        per_pick: dict[str, list[float] | None] = {}

        def counted(key: str) -> list[float] | None:
            if key not in per_pick:
                feature = RULES[key].feature
                parts = None if feature is None else [
                    float(feature(h, self.space)) for h in self.space.heroes]
                per_pick[key] = parts if parts is not None and all(
                    v in (0.0, 1.0) for v in parts) else None
            return per_pick[key]
        foldable = [i for i, t in enumerate(self.terms)
                    if t.reads and all(counted(n) is not None for n in t.reads)]
        chosen: set[str] = set()
        folded = []
        for i in sorted(foldable, key=lambda i: -self.terms[i].weight):
            wanted = chosen.union(self.terms[i].reads)
            if len(wanted) <= FOLD_COUNTS:
                chosen = wanted
                folded.append(i)
        folded.sort()
        keys = sorted(chosen)
        self._counts = [got for k in keys if (got := per_pick[k]) is not None]
        self._fold = [_Fold(i, tuple(keys.index(n) for n in self.terms[i].reads))
                      for i in folded]
        self._in_fold = set(folded)
        # per count, the terms that read it where each reads it alone, else None
        self._alone: list[list[int] | None] = []
        for j in range(len(keys)):
            readers = [f for f in self._fold if j in f.slots]
            self._alone.append([f.term for f in readers]
                               if all(len(f.slots) == 1 for f in readers) else None)
        self._points: dict[tuple[int, Vector], float] = {}

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
        """The most any completion of the branch scores: the engine's bound,
        then each term's most on the branch, added in the score's order;
        None where a limit fails on every completion."""
        parts = self._parts(frame, open_roles)
        return None if parts is None else _added(self.engine(frame, open_roles), parts)

    def bounds(self, frame: Frame, open_roles: Open, root: Open) -> Iterator[float | None]:
        """The bounds the walk asks of a branch, cheapest first, each worked
        out only when asked, so a branch the first drops reads no metric;
        None where no six of the branch keeps every limit. First the
        engine's bound with each term's most at `root`, the open roles of
        the branch's shape around the locked picks: every six of the branch
        is one of the root's, so each term's most there bounds it too, and
        they add up in the score's order. Then of(). Then, where a term
        folds and a slot is open, the fold (_folded)."""
        engine = self.engine(frame, open_roles)
        rest = self._at_root(root)
        yield None if rest is None else _added(engine, rest)
        parts = self._parts(frame, open_roles)
        yield None if parts is None else _added(engine, parts)
        if parts is not None:
            folded = self._folded(frame, open_roles, parts)
            if folded is not None:
                yield folded

    def _parts(self, frame: Frame, open_roles: Open) -> list[float] | None:
        """Each term's most on the branch, in the score's order; None where a
        limit fails on every completion. A term on the shape alone is read
        once a shape (_shaped). Any other is memoised on the values it reads,
        which decide its most - MEMO_CAP of them before its memo starts
        afresh; a value that does not hash, a list, is read afresh."""
        branch = Branch(frame.picks, open_roles)
        env = evaluate(self.steps, branch)
        for limit in self.limits:
            if truth(limit(env)) is False:
                return None
        by_shape = self._shaped(branch) if self._any_shaped else []
        out: list[float] = []
        for i, term in enumerate(self.terms):
            if term.shaped:
                out.append(by_shape[i])
                continue
            memo = self._memos[i]
            key = tuple([env.get(n, FALSE) for n in term.reads])
            try:
                value = memo.get(key)
            except TypeError:
                out.append(term.most(env))
                continue
            if value is None:
                if len(memo) >= MEMO_CAP:
                    memo.clear()
                value = memo[key] = term.most(env)
            out.append(value)
        return out

    def _shaped(self, branch: Branch) -> list[float]:
        """Each term on the shape alone at the branch's shape, 0 for every
        other: the shape fixes each value such a term reads, so its most is
        the same on every branch of the shape, and is read once."""
        shape = tuple(self.space.counts(branch))
        got = self._by_shape.get(shape)
        if got is None:
            env = evaluate(self.shape_steps, branch)
            got = self._by_shape[shape] = [term.most(env) if term.shaped else 0.0
                                           for term in self.terms]
        return got

    def _at_root(self, root: Open) -> list[float] | None:
        """Each term's most over every six of a shape - its parts on the
        locked picks with `root` open - read once a shape; None where no
        six of the shape keeps every limit."""
        if root not in self._roots:
            self._roots[root] = self._parts(self.start(), root)
        return self._roots[root]

    # --- the fold -------------------------------------------------------------

    def _folded(self, frame: Frame, open_roles: Open, parts: Sequence[float]) -> float | None:
        """The fold: the default engine and every folded term bounded
        together (_joint), each other term as of() bounds it (`parts`).
        None where no term folds or no slot is open.

        Apart, the engine's bound seats each open role's best few by their
        worth, and a folded term's range the heroes that suit it best, who
        need not be the same; together each completion is read once, its
        worth and its counts off the same picks. The terms add up in another
        order than the score's, so beside the engine's own slack the fold
        carries SLACK per unit of each term's magnitude it moves - each other
        term's here, each folded one's in _joint - far more than the
        rounding of a few dozen additions can move a sum, whatever its terms
        cancel."""
        m = sum(n for _, _, n in open_roles)
        if not self._fold or not m:
            return None
        others = size = 0.0
        for i, value in enumerate(parts):
            if i not in self._in_fold:
                others += value
                size += abs(value)
        joint = frame.own + frame.paired + self.engine_slack + self._joint(frame, open_roles, m)
        return joint + others + SLACK * (1.0 + size)

    def _joint(self, frame: Frame, open_roles: Open, m: int) -> float:
        """The most the open picks add to the default engine and the folded
        terms together. A folded term reads only counts the six holds - the
        picks' and those its open picks add - so its most at those counts,
        each a point, bounds it on the six. For each vector of counts the
        open picks can add, the most open picks that add it are worth, each
        read as engine() reads it, bounds the engine's part of every
        completion that adds it, as engine() bounds it over all; with each
        folded term at the picks' counts and the vector, and SLACK per unit
        of each one's magnitude, that bounds those completions' engine and
        folded terms together, and the most over the vectors bounds the
        branch's."""
        have = [sum([c[x] for x in frame.picks], 0.0) for c in self._counts]
        best = -INF
        for added, value in self._vectors(frame, open_roles, m, have).items():
            worth = size = 0.0
            for f in self._fold:
                point = self._at(f.term, tuple([have[j] + added[j] for j in f.slots]))
                worth += point
                size += abs(point)
            best = max(best, value + worth + SLACK * size)
        return best

    def _vectors(self, frame: Frame, open_roles: Open, m: int, have: Sequence[float]
                 ) -> dict[Vector, float]:
        """Each vector of counts the open picks can add, and the most open
        picks that add it are worth to the engine: with one slot open, each
        pattern's best candidate; else role by role (_by_counts), the roles'
        vectors then added up, each count stopped at its cap (_caps) over
        the picks' counts, `have`."""
        if m == 1:
            ((r, start, _),) = open_roles
            single: dict[Vector, float] = {}
            for value, pattern in self._candidates(frame, r, start, m):
                if value > single.get(pattern, -INF):
                    single[pattern] = value
            return single
        caps = self._caps(have, m)
        vectors: dict[Vector, float] = {(0.0,) * len(caps): 0.0}
        for r, start, n in open_roles:
            role = _by_counts(self._candidates(frame, r, start, m), n, caps)
            merged: dict[Vector, float] = {}
            for counts, value in vectors.items():
                for more, gain in role.items():
                    state = tuple([min(cap, a + b)
                                   for a, b, cap in zip(counts, more, caps, strict=True)])
                    if value + gain > merged.get(state, -INF):
                        merged[state] = value + gain
            vectors = merged
        return vectors

    def _candidates(self, frame: Frame, r: int, start: int, m: int
                    ) -> Iterator[tuple[float, Vector]]:
        """Role r's candidates from `start` on: each one's worth as engine()
        reads it - its own part, plus its pairs with the picks and half its
        m - 1 best pairs where synergy weighs - and the counts it adds."""
        own, partners, counts = self.own, frame.partners, self._counts
        half = self.halves[m - 1] if partners is not None else None
        for x in self.space.roles[r][start:]:
            if own is None:
                value = 0.0
            elif partners is None or half is None:
                value = own[x]
            else:
                value = own[x] + partners[x] + half[x]
            yield value, tuple([c[x] for c in counts])

    def _caps(self, have: Sequence[float], m: int) -> list[float]:
        """Each folded count's cap on what the open picks add to it: where
        each term that reads it reads it alone, the least from which none of
        them moves up to m - the vectors alike from there on then merge, and
        each reads the same as at its own count; else m, which no vector
        passes."""
        caps = []
        for j, alone in enumerate(self._alone):
            cap = m
            if alone is not None:
                top = [self._at(i, (have[j] + m,)) for i in alone]
                while cap and [self._at(i, (have[j] + cap - 1,)) for i in alone] == top:
                    cap -= 1
            caps.append(float(cap))
        return caps

    def _at(self, i: int, counts: Vector) -> float:
        """Term i's most on a six whose counts it reads are `counts`, read
        at that point, once."""
        got = self._points.get((i, counts))
        if got is None:
            term = self.terms[i]
            got = self._points[i, counts] = term.most(
                {n: Iv(c, c) for n, c in zip(term.reads, counts, strict=True)})
        return got

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
