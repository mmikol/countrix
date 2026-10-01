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
    paired      the swaps: each pick the target drops matched to an incoming
                hero of its role, then any left to the incoming heroes left,
                both sides in seat order, as the stage plan's swaps are
                (moved); its place among the picks as sent. A half-drafted
                seat's empty slots show the fill's heroes, as the rest of the
                board does
    verdict     the swaps in words
    chain       the plan stage by stage (below)

A swap is suggested only where the target's net beats the six that keeps
every pick - the picks at six, the fill around fewer - at SCORE_PLACES; a
tie keeps the picks. Where no six keeps them (a six that breaks a limit,
picks no six completes), the target is the cheapest way back to an allowed
six. One search answers every pick at once, so the swaps never conflict -
two tanks in for one slot, a hero taken twice - and taking one leaves the
rest the best answer from the new picks: for R' = R less the pick dropped
plus the hero taken, net_R'(x) <= net_R(T) + c = net_R'(T). Blue's seat
alone is searched; red's picks are the other side's facts.

The stage plan walks the map's stages in play order from one origin, the
six the board suggests - blue's picks with the swaps taken, the fill around
fewer, the optimal without picks. The phases of a route (Hybrid, Escort)
chain: each phase's six is the best reachable from the one before, each
hero changed costing the swap cost, so a hero stays into the next stage
unless swapping gains more than the cost - greedy, stage by stage, never
trading a swap now against one later. The arenas (Control, Flashpoint) come
up in no fixed order, so each is reached from the origin. The board's
chosen stage is the origin itself, and the phases before it are played.
Two stages that score every six alike from the same six are one search
(scoring.Objective.ground_key); a stage past its budget is not solved, and
the next phase goes on from the last six that was.
"""

from collections.abc import Sequence
from typing import NamedTuple

from facts import compute
from facts.board_facts import GroundValue
from facts.model import Hero, Map
from facts.team import text
from inference import base, plan
from inference.base import OFF
from inference.result import (
    OpenSlot,
    Pick,
    Result,
    Span,
    StageKind,
    StageRow,
    StageRules,
    StageSwap,
    SwapPair,
)
from inference.scoring import Candidate, Objective, quantized, seat_order
from inference.solver import Infeasible, Solver, Unbounded


def raw_cost(cost: float, span: Span) -> float | None:
    """The swap cost in the objective's points: `cost` share points of the
    seat's span, each a hundredth of its optimal's lead over its floor - zero
    where no reference six was legal, as Span reads it; None where the seat
    is unscored - no lead to take a share of."""
    floor = 0.0 if span.floor is None else span.floor
    if span.best <= floor:
        return None
    return cost * (span.best - floor) / 100.0


class Target(NamedTuple):
    """The swap search's answer: the six, scored on the seat's plain
    objective with its breakdown, and whether its net beats the six that
    keeps every pick - whether a swap is suggested at all."""
    six: Candidate
    gains: bool


def keeping(plain: Solver, picks: Sequence[Hero], cost: float,
            stage: str | None = None) -> Solver:
    """The swap search's Solver on `plain`'s board - blue's optimal's,
    nothing locked - with `cost` points, the raw cost, for each of `picks`
    a six keeps, on `plain`'s scale: each heuristic's low and high, and its
    floor; on `stage` where given, else on `plain`'s."""
    solver = Solver(plain.world, plain.m, red=plain.red, locked=(), banned=plain.banned_heroes,
                    side=plain.side, stage=plain.stage if stage is None else stage,
                    catalog=plain.catalog, base=plain.base, check=plain.check,
                    keep=frozenset(h.id for h in picks), swap=cost)
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
    best = solver.solve(top=1).ranked[0]
    gains = not keep <= set(best.key)
    if gains and keeper is not None:
        kept = solver.score(solver.prepare(Candidate(keeper)), detail=False)
        gains = quantized(best.score) > quantized(kept.score)
    return Target(six=plain.score(plain.prepare(Candidate(best.heroes))), gains=gains)


def paired(picks: Sequence[Hero], six: Sequence[Hero], target: Result) -> list[SwapPair]:
    """The swaps from `picks` to `six`, matched as the stage plan's are
    (moved): both sides in seat order. Each carries the dropped pick's place
    among the picks as sent (`at`), the order the pairs come in, and the
    incoming hero's portrait and reason off `target`, the six scored."""
    place = {h.name: at for at, h in enumerate(picks)}
    told = {p["hero"]: p for p in target.picks}
    return sorted((SwapPair({"out": s["out"], "in": s["in"], "at": place[s["out"]],
                             "portrait": told[s["in"]].get("portrait"),
                             "why": told[s["in"]]["why"]})
                   for s in moved(picks, six)), key=lambda pair: pair["at"])


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
        return "keep the picks: no swap gains its cost of %s / 100" % plan.cost_text(cost)
    if before is None:
        share = "back to an allowed six, %d / 100 of the optimal" % after
    else:
        share = "%d -> %d / 100 of the optimal%s" % (
            before, after, " (the picks filled)" if partial else "")
    fight = ", fight odds %d -> %d" % odds if odds is not None else ""
    return "swap %s: %s%s, at a cost of %s / 100 a swap" % (
        _swaps(pairs), share, fight, plan.cost_text(cost))


def withheld(pairs: Sequence[SwapPair], odds: tuple[int, int]) -> str:
    """Why a suggestion is withheld: its swaps would not raise the fight odds."""
    return "keep the picks: the best swaps (%s) would not raise the fight odds %d -> %d" % (
        _swaps(pairs), *odds)


def _swaps(pairs: Sequence[SwapPair]) -> str:
    """The swaps as the verdict names them: each pick out for its hero in."""
    return ", ".join("%s for %s" % (p["out"], p["in"]) for p in pairs)


# --- the stage plan -----------------------------------------------------------

class Leg(NamedTuple):
    """One stage's answer from a reference six: the six to play there and
    the reference, each scored with its breakdown on the stage's objective
    (the keep term adds to the score and is no contribution), and whether
    the six is not the reference - a swap pays for its cost."""
    six: Candidate
    reference: Candidate
    gains: bool


type Memo = dict[tuple[object, ...], Leg]


def stages(m: Map | None) -> list[tuple[str, StageKind]]:
    """The map's stages in play order, each a phase of one route or an
    arena of its own; none on a map without stages."""
    return ([(s, "phase") for s in compute.phases(m)]
            + [(s, "arena") for s in compute.arenas(m)])


def leg(solver: Solver, reference: Sequence[Hero], memo: Memo) -> Leg:
    """The best six on `solver`'s stage reachable from `reference` - the
    swap search's Solver (keeping) on that stage, its keep term on the
    reference: exact over every legal six. The reference stays where no six
    beats its net at SCORE_PLACES and it keeps the stage's limits. Memoised
    on the stage's ground key and the reference; Unbounded past the search's
    budget."""
    key = (solver.ground_key(), tuple(sorted(h.id for h in reference)))
    if key in memo:
        return memo[key]
    ref = solver.score(solver.prepare(Candidate(reference)))
    best = solver.solve(top=1).ranked[0]
    gains = not solver.keep <= set(best.key) and (
        bool(ref.violations) or quantized(best.score) > quantized(ref.score))
    six = solver.score(solver.prepare(Candidate(best.heroes))) if gains else ref
    memo[key] = Leg(six=six, reference=ref, gains=gains)
    return memo[key]


def moved(reference: Sequence[Hero], six: Sequence[Hero]) -> list[StageSwap]:
    """The swaps from `reference` to `six`: each hero that goes, in seat
    order, met first by an incoming hero of its own role, in seat order, and
    only then, the same-role matches all made, by whichever are left - the
    one rule every swap is matched by, the board's (paired) among them."""
    kept = {h.id for h in six}
    going = [h for h in sorted(reference, key=seat_order) if h.id not in kept]
    held = {h.id for h in reference}
    coming = [h for h in sorted(six, key=seat_order) if h.id not in held]
    met: dict[int, Hero] = {}
    for h in going:
        same = next((c for c in coming if c.role == h.role), None)
        if same is not None:
            coming.remove(same)
            met[h.id] = same
    for h in going:
        if h.id not in met and coming:
            met[h.id] = coming.pop(0)
    return [StageSwap({"out": h.name, "in": met[h.id].name}) for h in going if h.id in met]


GAIN_NAMED = 0.05       # a term's rise, in the objective's points, the blurb names


def gains_on(reference: Candidate, six: Candidate, titles: dict[str, str]) -> list[str]:
    """What a stage's six gains most on over the reference: the two terms
    whose weighted contribution rises most, titled; none where nothing rises."""
    before = {c["id"]: c["weighted"] if c["applies"] else 0.0 for c in reference.contributions}
    rises = [
        ((c["weighted"] if c["applies"] else 0.0) - before.get(c["id"], 0.0), c["id"])
        for c in six.contributions]
    top = sorted((r for r in rises if r[0] > GAIN_NAMED), key=lambda r: (-r[0], r[1]))
    return [titles.get(sid, sid).lower() for _, sid in top[:2]]


def lean(cand: Candidate) -> str:
    """The six's lean as a Result reads it: its style, else the map's."""
    if cand.ns is None:
        return ""
    team = cand.ns["team"]
    return text(team["style_lean"]) or text(team["style_top"])


def ground(m: Map, stage: str) -> list[GroundValue]:
    """The terrain at or over the standout on a stage's ground, largest
    first, and whose text each feature was read off."""
    read = sorted((compute.ground(m, stage, f) for f in compute.TERRAIN_FEATURES),
                  key=lambda g: (-g.z, g.feature))
    return [GroundValue(feature=g.feature, z=g.z, source=g.source)
            for g in read if g.z >= compute.TERRAIN_STANDOUT]


def ruled(solver: Objective, whole: Objective) -> StageRules:
    """The weighted rules `solver`'s ground turns on that the map as a
    whole leaves off, and those it turns off, by name."""
    weighted = [s for s in solver.catalog if s.weighs]
    return StageRules(
        on=[s.name for s in weighted if solver.gates[s.id] is True and whole.gates[s.id] is False],
        off=[s.name for s in weighted if solver.gates[s.id] is False and whole.gates[s.id] is True])


def gates_on(plain: Objective, stage: str = "") -> Objective:
    """`plain`'s board on `stage` - the whole map where it names none - with
    the default engine off: the objective a stage's rules are read off
    (ruled), which reads only its gates."""
    return Objective(plain.world, plain.m, red=plain.red, banned=plain.banned_heroes,
                     side=plain.side, stage=stage, catalog=plain.catalog, base=OFF)


class Taken(NamedTuple):
    """The board's swap answer on its chosen stage: the six it makes (the
    origin where the picks keep) and its swaps."""
    six: Sequence[Hero]
    swaps: Sequence[StageSwap]


class ChainStart(NamedTuple):
    """What the stage plan is walked from: blue's optimal's Solver, whose
    board and scale every stage shares; the board's chosen stage; the
    origin - the six the comps tab shows; the raw cost and the cost in share
    points; and the board's swap answer on the chosen stage - a swap
    suggested, or the picks kept under the cost - None where it gave
    neither: it searched none, or withheld the swap."""
    plain: Solver
    chosen: str
    origin: Sequence[Hero]
    raw: float
    cost: float
    taken: Taken | None = None


def chain(p: ChainStart, memo: Memo | None = None) -> list[StageRow]:
    """The plan stage by stage (the module's docstring): a row a stage of
    the map, in play order; none on a map without stages."""
    m = p.plain.m
    if m is None:
        return []
    memo = {} if memo is None else memo
    titles = {s.id: s.name for s in p.plain.catalog} | base.TITLES
    whole = gates_on(p.plain)
    walk = stages(m)
    phases = [name for name, kind in walk if kind == "phase"]
    rows: list[StageRow] = []
    previous = p.origin
    played = p.chosen in phases
    for name, kind in walk:
        current = name == p.chosen
        if kind == "phase" and played and not current:
            rows.append(_row(m, name, kind, played=True))
            continue
        played = False
        reference = previous if kind == "phase" else p.origin
        index = (phases.index(name) + 1, len(phases)) if kind == "phase" else (0, 0)
        if current:
            rules = ruled(gates_on(p.plain, name), whole)
            # the board's own swap answer on this stage, one answer with the
            # swaps above the picks; where it gave none, the origin
            played_six = sorted(p.taken.six if p.taken is not None else p.origin,
                                key=seat_order)
            taken = list(p.taken.swaps) if p.taken is not None else []
            rows.append(_row(m, name, kind, current=True, six=[h.name for h in played_six],
                             swaps=taken, rules=rules, blurb=plan.stage_blurb(
                                 m, name, index, rules, taken, [], p.cost,
                                 outcome="origin" if p.taken is None else "solved")))
            if kind == "phase":
                previous = played_six
            continue
        solver = keeping(p.plain, reference, p.raw, stage=name)
        rules = ruled(solver, whole)
        try:
            got = leg(solver, reference, memo)
        except (Unbounded, Infeasible) as error:
            rows.append(_row(m, name, kind, rules=rules, solved=False, blurb=plan.stage_blurb(
                m, name, index, rules, [], [], p.cost,
                outcome="infeasible" if isinstance(error, Infeasible) else "unsolved")))
            continue
        heroes = got.six.heroes
        swaps = moved(reference, heroes)
        turned = lean(got.six)
        rows.append(_row(m, name, kind, six=[h.name for h in heroes], swaps=swaps, rules=rules,
                         blurb=plan.stage_blurb(
                             m, name, index, rules, swaps,
                             gains_on(got.reference, got.six, titles), p.cost,
                             lean=turned if turned != lean(got.reference) else "")))
        if kind == "phase":
            previous = heroes
    return rows


def _row(
        m: Map, stage: str, kind: StageKind, *, current: bool = False, played: bool = False,
        six: Sequence[str] = (), swaps: Sequence[StageSwap] = (),
        rules: StageRules | None = None, blurb: str = "", solved: bool = True) -> StageRow:
    """One row of the plan, its ground read off the map."""
    return StageRow(stage=stage, kind=kind, current=current, played=played, six=list(six),
                    swaps=list(swaps), ground=ground(m, stage),
                    rules=rules if rules is not None else StageRules(on=[], off=[]),
                    blurb=blurb, solved=solved)
