"""Blue's swaps: which of blue's picks to trade, and for whom, as one joint
answer - the best six reachable from the picks as they stand, each pick
dropped costing the swap cost.

    raw_cost    the swap cost in the objective's own points: the cost is set
                in share points of blue's span (meta.md's swap, a board's
                weights=swap:v), each (best - floor) / 100 on this board
    keeping     the search's Solver: blue's seat with nothing locked, the
                keep term on blue's picks, on blue's optimal's scale
    search      the target: over every legal six x of the released, unbanned
                roster, the one that maximises score(x) - c x |R - x|, R
                blue's picks and c the raw cost. Written as a keep bonus -
                score(x) + c x |x & R|, the same less c x |R| - it is each
                pick's own part, which the search's bound carries exactly
                (scoring.Objective's keep term), so the search is the one
                exact branch and bound on blue's seat, on blue's optimal's
                scale, ties broken by the board's draw. The winner is scored
                again on blue's plain objective before anything reads it
    paired      the swaps: each pick the target drops, in the order sent,
                matched to an incoming hero of its role, then any left to
                the incoming heroes left, in seat order; its place among the
                picks as sent. A half-drafted seat's incoming heroes past
                those fill its empty slots
    verdict     the swaps in words

A swap is suggested only where the target's net beats the six that keeps
every pick - the picks at six, the fill around fewer - at SCORE_PLACES; a
tie keeps the picks. Where no six keeps them (a six that breaks a limit,
picks no six completes), the target is the cheapest way back to an allowed
six. One search answers every pick at once, so the swaps never conflict -
two tanks in for one slot, a hero taken twice - and taking one leaves the
rest the best answer from the new picks: for R' = R less the pick dropped
plus the hero taken, net_R'(x) <= net_R(T) + c = net_R'(T). Blue's seat
alone is searched; red's picks are the other side's facts.
"""

from collections.abc import Sequence
from typing import NamedTuple

from facts.model import Hero
from inference.base import OFF
from inference.result import OpenSlot, Pick, Result, Span, SwapPair
from inference.scoring import Candidate, quantized
from inference.solver import Infeasible, Solver


def raw_cost(cost: float, span: Span) -> float | None:
    """The swap cost in the objective's points: `cost` share points of the
    seat's span, each a hundredth of its optimal's lead over its floor;
    None where the seat is unscored - no lead to take a share of."""
    if span.floor is None or span.best <= span.floor:
        return None
    return cost * (span.best - span.floor) / 100.0


class Target(NamedTuple):
    """The swap search's answer: the six, scored on the seat's plain
    objective with its breakdown, and whether its net beats the six that
    keeps every pick - whether a swap is suggested at all."""
    six: Candidate
    gains: bool


def keeping(plain: Solver, picks: Sequence[Hero], cost: float) -> Solver:
    """The swap search's Solver on `plain`'s board - blue's optimal's,
    nothing locked - with `cost` points, the raw cost, for each of `picks`
    a six keeps, on `plain`'s scale: its bounds and its floor."""
    solver = Solver(plain.world, plain.m, red=plain.red, locked=(),
                    banned=[plain.world.heroes[i] for i in sorted(plain.banned)],
                    side=plain.side, stage=plain.stage, catalog=plain.catalog,
                    base=plain.base.weights if plain.base is not None else OFF,
                    check=plain.check, keep=frozenset(h.id for h in picks), swap=cost)
    solver.adopt_scale(plain)
    return solver


def search(
        plain: Solver, picks: Sequence[Hero], cost: float,
        keeper: Sequence[Hero] | None) -> Target:
    """The best six reachable from `picks` at `cost` a pick dropped, in the
    objective's points, on `plain`'s board and scale - blue's optimal's
    Solver, nothing locked. `keeper` is the best six that keeps every pick
    (the picks at six, the fill around fewer); None where none does. The
    search is exact over every legal six; Unbounded past its budget."""
    solver = keeping(plain, picks, cost)
    keep = solver.keep
    solved = solver.solve(top=1)
    if not solved.ranked:
        raise Infeasible("no composition satisfies the limits on this board - relax a"
                         " constraint in inference/strategies/")
    best = solved.ranked[0]
    gains = not keep <= set(best.key)
    if gains and keeper is not None:
        kept = solver.score(solver.prepare(Candidate(keeper)), detail=False)
        gains = quantized(best.score) > quantized(kept.score)
    return Target(six=plain.score(plain.prepare(Candidate(best.heroes))), gains=gains)


def paired(picks: Sequence[Hero], target: Result) -> tuple[list[SwapPair], list[OpenSlot]]:
    """The swaps from `picks` (in the order sent) to `target`'s six, and
    the heroes left for the empty slots: each dropped pick meets an
    incoming hero of its role first, in seat order, then whichever are
    left; its `at` is its place among the picks."""
    names = {h.name for h in picks}
    incoming = [p for p in target.picks if p["hero"] not in names]
    kept = set(target.blue)
    dropped = [(at, h) for at, h in enumerate(picks) if h.name not in kept]
    matched = {}
    for at, h in dropped:
        same = next((p for p in incoming if p["role"] == h.role), None)
        if same is not None:
            incoming.remove(same)
            matched[at] = same
    for at, _ in dropped:
        if at not in matched and incoming:
            matched[at] = incoming.pop(0)
    pairs = [
        SwapPair({"out": h.name, "in": matched[at]["hero"], "at": at,
                  "portrait": matched[at].get("portrait"), "why": matched[at]["why"]})
        for at, h in dropped if at in matched]
    return pairs, open_slots(incoming)


def open_slots(picks: Sequence[Pick]) -> list[OpenSlot]:
    """Heroes for the empty slots, as the page draws them."""
    return [OpenSlot(hero=p["hero"], role=p["role"], portrait=p.get("portrait"), why=p["why"])
            for p in picks]


def verdict(pairs: Sequence[SwapPair], cost: float, before: int | None, after: int,
            odds: tuple[int, int] | None, *, partial: bool) -> str:
    """The suggestion in words: each swap, blue's share before and after -
    the picks filled where the seat is half-drafted - and the fight odds
    where both are read; or that the picks keep, and the cost that held
    them."""
    if not pairs:
        return "keep the picks: no swap gains its cost of %s / 100" % _number(cost)
    if before is None:
        share = "back to an allowed six, %d / 100 of the optimal" % after
    else:
        share = "%d -> %d / 100 of the optimal%s" % (
            before, after, " (the picks filled)" if partial else "")
    fight = ", fight odds %d -> %d" % odds if odds is not None else ""
    return "swap %s: %s%s, at a cost of %s / 100 a swap" % (
        _swaps(pairs), share, fight, _number(cost))


def withheld(pairs: Sequence[SwapPair], odds: tuple[int, int]) -> str:
    """Why a suggestion is withheld: its swaps would lower the fight odds."""
    return "keep the picks: the best swaps (%s) would lower the fight odds %d -> %d" % (
        _swaps(pairs), *odds)


def _swaps(pairs: Sequence[SwapPair]) -> str:
    """The swaps as the verdict names them: each pick out for its hero in."""
    return ", ".join("%s for %s" % (p["out"], p["in"]) for p in pairs)


def _number(value: float) -> str:
    """A cost as the verdict writes it: whole where it is whole."""
    return "%d" % value if value == int(value) else "%g" % value
