"""The search: the optimal six under the catalog, players playing optimally.
A Solver is the board's Objective (inference.scoring) on the board's scale
(inference.scale), searched exactly around the locked picks.

    shapes      the (tanks, damage, supports) triples the queue and the shape
                limits allow that can still seat the locked picks
    solve       the best sixes of the whole legal space - every six of
                released, unbanned heroes around the locked picks, each once,
                at most two tanks, every limit kept - in the full rank order
                (scoring.rank_key), by branch and bound: each shape is filled
                role by role, a role's picks at rising places of its walk
                order, and a branch is dropped only where its bound
                (inference.bounds) proves that no six in it can enter the
                top K. The answer is the enumeration's own, whatever order
                the walk takes; no hero is left out of any role
    outranking  how many legal sixes rank above a six in the full rank
                order, ties on the quantized score settled as the search
                settles them: the same walk, dropping every branch whose
                bound cannot reach it, exact up to RANK_CAP
    ties        how many legal sixes share the best six's quantized score,
                read off the search's best K where a lower six closes it,
                else counted by the same walk, exact up to RANK_CAP within
                TIE_BUDGET sixes scored, and "at least" past either

A search refuses rather than guesses: past NODE_BUDGET branches or
SCORE_BUDGET sixes scored in full it raises Unbounded, and a search that
ends with no six is Infeasible - a proof that no legal six exists.
"""

import bisect
import math
from collections.abc import Callable, Sequence
from typing import NamedTuple

from db import Refusal
from facts.model import ROLES, Hero, Map, World
from inference import scale
from inference.base import BaseWeights
from inference.bounds import Bound, Frame, Space, roster
from inference.scoring import Candidate, Objective, quantized, rank_key
from inference.shapes import Shape, legal_shapes
from inference.strategy import Strategy

RANK_CAP = 100                    # the ranks outranking() counts exactly; past it, "outside"
NODE_BUDGET = 2_000_000           # branches one search walks before it refuses
SCORE_BUDGET = 200_000            # sixes one search scores in full before it refuses
CHECK_EVERY = 4096                # branches between two asks whether the board is superseded
TIE_BUDGET = 5_000                # sixes a tie count scores before it answers "at least"


class Infeasible(Refusal):
    """No six meets the playbook's limits on this board. The board and the
    playbook answer it, so it is a Refusal: the server is not at fault."""


class Unbounded(Refusal):
    """A search that passed its budget before it proved its answer: a
    playbook whose terms the bound cannot narrow. The answer is exact or
    refused, never guessed."""


class Solved(NamedTuple):
    """A board's search: the solver that ran it, its ranked winners
    hydrated, and how many it was asked for - fewer ranked than that is
    every feasible six."""
    solver: "Solver"
    ranked: list[Candidate]
    size: int


class Tied(NamedTuple):
    """How many legal sixes share the best six's quantized score, itself
    among them, and whether the count stopped at RANK_CAP or a budget, so
    that at least that many do."""
    sixes: int
    at_least: bool


class Evaluated(NamedTuple):
    """A full six scored and ranked against every legal six - its rank, None
    where RANK_CAP sixes outrank it (outranked) or the count ran out of
    budget - and the seat's best sixes, hydrated."""
    target: Candidate
    field: list[Candidate]
    rank: int | None
    outranked: bool
    solver: "Solver"


# the roles still open at a node: (role, first candidate, picks left)
type Open = tuple[tuple[int, int, int], ...]


def _open(slots: Sequence[int], j: int, start: int) -> Open:
    """The roles slots[j:] still fill, the first from `start`, the rest from
    their first candidate."""
    out = []
    i = j
    while i < len(slots):
        k = i
        while k < len(slots) and slots[k] == slots[i]:
            k += 1
        out.append((slots[i], start if i == j else 0, k - i))
        i = k
    return tuple(out)


class _Best:
    """The K best sixes met so far, in rank order, and the prune the K-th
    sets: a branch whose bound rounds below its score, or ties it with a
    tie-break that cannot reach its own."""

    done = False

    def __init__(self, k: int) -> None:
        self.k = k
        self.items: list[tuple[tuple[float, float, list[str]], Candidate]] = []

    def prunes(self, bound: float, walk: Bound, frame: Frame, open_roles: Open) -> bool:
        if len(self.items) < self.k:
            return False
        worst = self.items[-1][0]
        score = quantized(bound)
        if score != -worst[0]:
            return score < -worst[0]
        return walk.tiebreak(frame, open_roles) < -worst[1]

    def offer(self, cand: Candidate) -> None:
        key = rank_key(cand)
        if len(self.items) >= self.k and key >= self.items[-1][0]:
            return
        bisect.insort(self.items, (key, cand), key=lambda item: item[0])
        del self.items[self.k:]


class _Count:
    """The legal sixes that rank above a target in the full rank order - a
    higher quantized score, the same with a higher tie-break, or both the
    same and the names first - counted up to a cap; a branch whose bound
    cannot reach the target is dropped, as _Best drops one."""

    def __init__(self, target: Candidate, cap: int) -> None:
        self.key = rank_key(target)
        self.cap, self.count, self.done = cap, 0, False

    def prunes(self, bound: float, walk: Bound, frame: Frame, open_roles: Open) -> bool:
        score = quantized(bound)
        if score != -self.key[0]:
            return score < -self.key[0]
        return walk.tiebreak(frame, open_roles) < -self.key[1]

    def offer(self, cand: Candidate) -> None:
        if rank_key(cand) < self.key:
            self.count += 1
            self.done = self.count >= self.cap


class _Ties:
    """The legal sixes whose quantized score reaches a best six's, counted
    up to a cap, among at most TIE_BUDGET sixes scored; a branch whose bound
    rounds below it is dropped."""

    def __init__(self, best: Candidate, cap: int) -> None:
        self.score = quantized(best.score)
        self.cap, self.count, self.seen, self.done = cap, 0, 0, False

    def prunes(self, bound: float, walk: Bound, frame: Frame, open_roles: Open) -> bool:
        return quantized(bound) < self.score

    def offer(self, cand: Candidate) -> None:
        self.seen += 1
        if quantized(cand.score) >= self.score:
            self.count += 1
        self.done = self.count >= self.cap or self.seen >= TIE_BUDGET


type Goal = _Best | _Count | _Ties


class Solver(Objective):
    """One board's search: the playbook's objective on this board, the scale
    it is normalised on, and the exact search around the locked picks."""

    def __init__(self, world: World, m: Map | None, *, red: Sequence[Hero],
                 locked: Sequence[Hero], banned: Sequence[Hero] = (), side: str = "",
                 catalog: list[Strategy], base: BaseWeights,
                 check: Callable[[], None] | None = None) -> None:
        super().__init__(world, m, red=red, banned=banned, side=side, catalog=catalog,
                         base=base)
        self.locked = list(locked)
        self._locked_by_role = {r: [h for h in self.locked if h.role == r] for r in ROLES}
        self.check = check            # raises where a newer board superseded this one
        self.considered = 0           # the legal sixes the last search's answer covers
        self.nodes = 0                # branches the last search walked
        self.leaves = 0               # sixes the last search scored in full
        # the lowest score among the reference sixes, once read: the zero of a
        # share on this board, as the optimal is its 100
        self.floor: float | None = None
        self._frozen = False
        self._bound: Bound | None = None

    # --- the scale ----------------------------------------------------------------

    def freeze_bounds(self) -> None:
        """Bounds per heuristic from the reference sample and the field, and
        the sample's floor."""
        self.floor = scale.freeze(self)
        self._frozen, self._bound = True, None

    def adopt_scale(self, other: "Solver") -> None:
        """The scale another solver on the same board froze - its bounds and
        its floor: a fill takes its seat's, and draws no sample."""
        self.adopt_bounds(other.bounds)
        self.floor = other.floor
        self._frozen, self._bound = True, None

    # --- the space ----------------------------------------------------------------

    def shapes(self) -> list[Shape]:
        """(tanks, damage, supports) triples the queue and the shape-only
        limits allow, that can still seat the locked picks."""
        locked = self._locked_by_role
        return legal_shapes(self.catalog, Shape(
            tanks=len(locked["tank"]), damage=len(locked["damage"]),
            supports=len(locked["support"])))

    def _walker(self) -> Bound:
        """The bound over this board's space, built once the scale is frozen."""
        if not self._frozen:
            self.freeze_bounds()
        if self._bound is None:
            space = Space(self, self.locked, roster(self.world, self.locked, self.banned))
            self._bound = Bound(self, space)
        return self._bound

    def _slots(self, space: Space) -> list[tuple[int, ...]]:
        """Each legal shape's open slots, role by role in ROLES order; a
        shape a role has too few candidates for holds no six."""
        out = []
        for shape in self.shapes():
            need = [shape[i] - len(self._locked_by_role[r]) for i, r in enumerate(ROLES)]
            if all(n <= len(space.roles[i]) for i, n in enumerate(need)):
                out.append(tuple(i for i, n in enumerate(need) for _ in range(n)))
        return out

    # --- the search -------------------------------------------------------------------

    def solve(self, top: int = 5) -> Solved:
        """The `top` best legal sixes, exactly, in rank order, hydrated."""
        goal = _Best(max(1, top))
        self._search(goal)
        return Solved(self, [self.hydrate(c) for _, c in goal.items], goal.k)

    def outranking(self, target: Candidate, cap: int | None = None) -> int | None:
        """How many legal sixes rank above `target` (scoring.rank_key), a six
        that ties its quantized score counted where the tie-break or the
        names put it first, as the alternatives are listed: exactly, or None
        once `cap` do - RANK_CAP where none is named."""
        goal = _Count(target, RANK_CAP if cap is None else cap)
        self._search(goal)
        return None if goal.done else goal.count

    def ties(self, solved: Solved) -> Tied:
        """How many legal sixes share the quantized score of `solved`'s best
        six, itself among them: read off the search's own best K where a
        six of a lower score closes it, else counted by a walk of its own -
        exactly up to RANK_CAP, and at least as many as it counted where the
        walk scores TIE_BUDGET sixes or passes the search's budget first."""
        ranked = solved.ranked
        best = quantized(ranked[0].score)
        tied = sum(1 for c in ranked if quantized(c.score) == best)
        if tied < len(ranked) or len(ranked) < solved.size:
            return Tied(tied, False)
        goal = _Ties(ranked[0], RANK_CAP)
        try:
            self._search(goal)
        except Unbounded:
            return Tied(max(goal.count, tied), True)
        return Tied(goal.count, goal.done)

    def _search(self, goal: Goal) -> None:
        """Walk every legal shape, strongest root bound first, into `goal`."""
        walk = self._walker()
        space = walk.space
        self.nodes = self.leaves = 0
        roots = self._slots(space)
        self.considered = sum(
            math.prod(math.comb(len(space.roles[r]), slots.count(r)) for r in range(len(ROLES)))
            for slots in roots)
        start = walk.start()
        ranked = []
        for slots in roots:
            bound = walk.of(start, _open(slots, 0, 0))
            if bound is not None:
                ranked.append((-bound, slots))
        ranked.sort()
        for _, slots in ranked:
            if goal.done:
                break
            self._branch(walk, goal, slots, 0, 0, start)

    def _branch(self, walk: Bound, goal: Goal, slots: tuple[int, ...], j: int, start: int,
                frame: Frame) -> None:
        """One node: its bound, then its leaf or its children - the next
        slot's role filled at each place from `start` that leaves the role's
        later slots room."""
        self.nodes += 1
        if not self.nodes % CHECK_EVERY:
            self._checkpoint()
        open_roles = _open(slots, j, start)
        bound = walk.of(frame, open_roles)
        if bound is None or goal.prunes(bound, walk, frame, open_roles):
            return
        if j == len(slots):
            self._leaf(walk, goal, frame)
            return
        role = slots[j]
        candidates = walk.space.roles[role]
        later = 0
        while j + 1 + later < len(slots) and slots[j + 1 + later] == role:
            later += 1
        for i in range(start, len(candidates) - later):
            if goal.done:
                return
            self._branch(walk, goal, slots, j + 1, i + 1 if later else 0,
                         walk.push(frame, candidates[i]))

    def _leaf(self, walk: Bound, goal: Goal, frame: Frame) -> None:
        """A six its branch's bound let through: scored in full, by the one
        objective, and offered to the goal where no limit breaks it."""
        self.leaves += 1
        if self.leaves > SCORE_BUDGET:
            raise Unbounded("the search scored %d sixes without proving its answer - a"
                            " playbook term the bound cannot narrow; tighten it in"
                            " inference/strategies/" % SCORE_BUDGET)
        cand = self.prepare(Candidate(walk.space.heroes[i] for i in frame.picks))
        if cand.violations:
            return
        goal.offer(self.slim(self.score(cand, detail=False)))

    def _checkpoint(self) -> None:
        """Every CHECK_EVERY branches: stop a superseded board, and a search
        past its budget."""
        if self.check is not None:
            self.check()
        if self.nodes > NODE_BUDGET:
            raise Unbounded("the search walked %d branches without proving its answer - a"
                            " playbook term the bound cannot narrow; tighten it in"
                            " inference/strategies/" % NODE_BUDGET)


def evaluate_comp(solved: Solved, heroes: Sequence[Hero]) -> Evaluated:
    """Score one full six on a seat's search and rank it against every legal
    six in the order the search lists them (scoring.rank_key): from the
    search's own top K where the six reaches it, else by outranking(); a
    count past its budget leaves it unranked. A six that ties the optimal's
    score but loses the tie-break is not first. A board with no feasible
    six is Infeasible, as infer refuses it."""
    solver = solved.solver
    if not solved.ranked:
        raise Infeasible("no composition satisfies the limits on this board - relax a"
                         " constraint in inference/strategies/")
    target = solver.score(solver.prepare(Candidate(heroes)))
    key = rank_key(target)
    ranked = solved.ranked
    if len(ranked) < solved.size or key <= rank_key(ranked[-1]):
        above: int | None = sum(1 for c in ranked if rank_key(c) < key)
    else:
        try:
            above = solver.outranking(target)
        except Unbounded:
            return Evaluated(target, ranked[:5], None, False, solver)
    return Evaluated(target, ranked[:5], None if above is None else 1 + above, above is None,
                     solver)
