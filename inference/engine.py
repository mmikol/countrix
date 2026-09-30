"""infer() and board(): the API over the solver.

    infer(world, Draft(map_name="King's Row", red=("Zarya", "Pharah"), blue=("Ana",),
                       side="attack"))

returns the optimal six around the locked picks, each pick with the facts
that justify it (the facts the board would show for map + red + the
six), the score broken down into the default engine's terms and each
strategy's, and the alternatives. board() does it for both seats - blue's
absolute optimal, red around its revealed ones, on opposite sides of a
sided map - and scores the current blue picks as they stand. Both refuse
a team past the queue's tanks, on either seat, and a stage the map does
not list, and score under the default engine at the playbook's weights
(its meta.md) unless the caller names others; base.OFF, the meta at 0, is
the playbook alone. Every seat of a board is solved on its stage - the
ground in play, the whole map where the draft names none. The limits
bind blue's own picks: the board reads a six that breaks one as not
allowed, and infer refuses locked picks no six completes. The records are
result.py's and the prose plan.py's. Every search is exact
(inference.solver) and runs in this process, one after another.
"""

import contextlib
import dataclasses
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import NamedTuple

from db import Refusal
from facts import board_facts, compute
from facts.draft import (
    TEAM_SIZE,
    Draft,
    Seat,
    board_side,
    board_stage,
    check_tanks,
    opposite,
)
from facts.factset import FactSet
from facts.model import ROLES, Hero, Map, World
from inference import catalog as catalog_module
from inference import supersede
from inference.base import OFF, BaseWeights
from inference.plan import Seats, momentum, plan
from inference.result import (
    Alternative,
    Board,
    Pick,
    Result,
    ResultKind,
    Span,
    not_allowed,
)
from inference.scoring import Candidate, Objective
from inference.shapes import legal_shapes
from inference.solver import Infeasible, Solved, Solver, Unbounded, evaluate_comp
from inference.strategy import Strategy

TOP_DEFAULT = 5             # alternatives when a caller names none
TOP_CEILING = 20            # the most alternatives a caller may ask for


def clamp_top(top: str | float | None = None) -> int:
    """The alternatives a caller asks for, 1..TOP_CEILING: left out (None),
    TOP_DEFAULT; any number, 0 and negatives included, clamped into the
    range, so an MCP tool's 0 and a query string's "0" both read as the
    floor. The search has no width to choose - it is exact - so this is its
    one knob, and every door that takes it from a caller passes it through
    here. Anything else, [] included, raises Refusal, which every door
    answers as the caller's error."""
    try:
        return max(1, min(int(TOP_DEFAULT if top is None else top), TOP_CEILING))
    except (TypeError, ValueError) as error:
        raise Refusal("top must be a number: %s" % error) from error


BOARD_TOP = 5               # the alternatives each of a board's seats keeps


class Brief(NamedTuple):
    """What a caller asks of one board beyond the draft: the playbook tab's
    weights ({heuristic id: 0..10}, and META, the default engine's meta -
    for this board only), whether to solve the countered case - the MCP
    board prints it, the page never reads it - the check that says a newer
    request from the same client has superseded this one, and the default
    engine's weights, the playbook's meta.md's (None) unless a caller names
    others (OFF turns it off)."""
    weights: Mapping[str, float] | None = None
    countered: bool = True
    superseded: Callable[[], bool] | None = None
    base: BaseWeights | None = None


def weights_in_force(
        base: BaseWeights | None, weights: Mapping[str, float] | None = None) -> BaseWeights:
    """The default engine's weights a board or an infer scores under: the
    caller's `base`, else the playbook in force's meta.md
    (catalog.engine_weights), with a board's own meta on top where its
    `weights` set one (BaseWeights.metered)."""
    return (catalog_module.engine_weights() if base is None else base).metered(weights)


def _order(heroes: Iterable[Hero]) -> list[str]:
    return [h.name for h in sorted(heroes, key=lambda h: (ROLES.index(h.role), h.name))]


def _board_facts(world: World, result: Result, side: str) -> FactSet:
    """The facts of the board a result stands on: its map and stage, both
    sides as it names them, its bans, and the side."""
    return board_facts.generate(world, Draft(
        map_name=result.map_name, red=tuple(result.red), blue=tuple(result.blue),
        bans=tuple(result.bans), side=side, stage=result.stage))


def infer(
        world: World, draft: Draft, *, catalog: list[Strategy] | None = None,
        top: int = TOP_DEFAULT, base: BaseWeights | None = None) -> Result:
    """Blue's optimal six around its locked picks (`draft.blue`) against red's
    revealed ones, on the draft's side of a sided map. No catalog is the
    playbook in force; a catalog given, [] included, is the caller's. The
    default engine scores under `base`, the playbook in force's meta.md
    where it is None; OFF leaves the playbook alone. The search is exact,
    so locked picks no six completes within the limits are proved so, and
    refused as not allowed, in the words the board uses."""
    catalog = catalog_module.load() if catalog is None else catalog
    base = weights_in_force(base)
    try:
        return _optimal(world, draft, catalog=catalog, base=base, top=top, seat="blue",
                        kind="infer").result
    except Infeasible as error:
        if not draft.blue:
            raise
        raise Infeasible(not_allowed(_ruled_out(world, draft, catalog))) from error


class _Optimal(NamedTuple):
    """A seat's optimal six, the Solver that found it and its search: the
    seat's current comp is scored under the scale that search froze, on its
    span, and ranked against the search."""
    result: Result
    solver: Solver
    solved: Solved

    @property
    def span(self) -> Span:
        """The seat's span: its optimal's score, the 100, and the floor its
        reference sixes set, the 0."""
        return Span(best=self.result.score, floor=self.solver.floor)


def _broken(objective: Objective, heroes: Sequence[Hero]) -> list[str]:
    """The names of the playbook's limits `heroes` break as they stand, in
    catalog order: the check the search prunes by."""
    names = {s.id: s.name for s in objective.catalog}
    return [names[sid] for sid in objective.prepare(Candidate(heroes)).violations]


def _optimal(
        world: World, draft: Draft, *, catalog: list[Strategy], base: BaseWeights,
        top: int, seat: Seat, kind: ResultKind, check: Callable[[], None] | None = None,
        scale_of: Solver | None = None) -> _Optimal:
    """The optimal six for `seat` around its locked picks (`draft.blue`)
    against the other seat's revealed ones (`draft.red`), labelled `kind`,
    with `top` alternatives. `scale_of` is a solver on the same board whose
    scale this search takes - a fill takes its seat's - and `check` is asked
    as the search runs whether the board was superseded."""
    started = time.time()
    m, red_h, blue_h, bans_h = world.resolve(draft.map_name, draft.red, draft.blue, draft.bans)
    side, stage = board_side(m, draft.side), board_stage(m, draft.stage)
    _check_teams(red_h, blue_h, seat)
    result = Result(kind=kind, map_name=m.name if m else None, red=[h.name for h in red_h],
                    blue=[], locked=[h.name for h in blue_h], catalog=catalog, base=base,
                    bans=[h.name for h in bans_h], side=side, stage=stage, seat=seat)
    solver = Solver(world, m, red=red_h, locked=blue_h, banned=bans_h, side=side, stage=stage,
                    catalog=catalog, base=base, check=check)
    if scale_of is not None:
        solver.adopt_scale(scale_of)
    solved = solver.solve(top=max(top, 1) + 1)
    if not solved.ranked:
        raise Infeasible("no composition satisfies the limits around the"
                         " locked %s picks - relax a constraint in inference/strategies/"
                         % seat)
    best = solved.ranked[0]
    result.blue = _order(best.heroes)
    fs = _board_facts(world, result, side)
    result.record_candidate(best, fs, solver.considered)
    result.tied = solver.ties(solved)
    result.alternatives = [Alternative(blue=_order(c.heroes), score=round(c.score, 3),
                                       normalized=None)
                           for c in solved.ranked[1:top + 1]]
    optimal = _Optimal(result, solver, solved)
    result.scale_to(optimal.span)
    result.seconds = time.time() - started
    return optimal


def _evaluated(
        world: World, draft: Draft, *, catalog: list[Strategy], base: BaseWeights,
        seat: Seat, kind: ResultKind, solved: Solved | None) -> Result:
    """`seat`'s full six (`draft.blue`), scored and ranked against every
    legal six, labelled `kind`. `solved` takes the seat's own search from a
    caller that already ran it on this board; None searches it here. A six
    that breaks a limit is scored with its breaches listed: the board bars
    blue's before it gets here, and ranks red's."""
    started = time.time()
    m, red_h, blue_h, bans_h = world.resolve(draft.map_name, draft.red, draft.blue, draft.bans)
    side, stage = board_side(m, draft.side), board_stage(m, draft.stage)
    _check_teams(red_h, blue_h, seat)
    if len(blue_h) != TEAM_SIZE:
        raise Refusal("evaluate needs exactly %d %s picks (got %d)"
                         % (TEAM_SIZE, seat, len(blue_h)))
    result = Result(kind=kind, map_name=m.name if m else None, red=[h.name for h in red_h],
                    blue=[h.name for h in blue_h], locked=[], catalog=catalog, base=base,
                    bans=[h.name for h in bans_h], side=side, stage=stage, seat=seat)
    if solved is None:
        solved = Solver(world, m, red=red_h, locked=[], banned=bans_h, side=side, stage=stage,
                        catalog=catalog, base=base).solve(top=BOARD_TOP + 1)
    evaluated = evaluate_comp(solved, blue_h)
    fs = _board_facts(world, result, side)
    result.record_candidate(evaluated.target, fs, evaluated.solver.considered)
    result.rank, result.outranked = evaluated.rank, evaluated.outranked
    result.alternatives = [Alternative(blue=_order(c.heroes), score=round(c.score, 3),
                                       normalized=None)
                           for c in evaluated.field[:3]]
    result.seconds = time.time() - started
    # the board's best known six is the 100, not this comp's own best rival: a
    # beaten six must not read 100 because nothing it was compared against beat it
    result.scale_to(Span(best=max([result.score] + [a["score"] for a in result.alternatives]),
                         floor=evaluated.solver.floor))
    return result


def _current(
        world: World, draft: Draft, *, optimal: _Optimal, catalog: list[Strategy],
        base: BaseWeights, seat: Seat, kind: ResultKind,
        barred: list[str] | None = None) -> Result:
    """`seat`'s picks (`draft.blue`, from that seat's perspective) as they
    stand against the other seat's (`draft.red`), on the span of the seat's
    `optimal`: its Solver's bounds and floor, and its score, the 100. A full
    six is ranked against every legal six through the optimal's search, and
    reads "evaluate" where `kind` is "current", any other kind staying as
    given; a partial team is scored under the bounds the optimal's search
    froze, and says so. `barred` is the limits the picks break when their
    comp is not allowed (_barred): it is scored nowhere and ranked against
    nothing, and says why."""
    full = len(draft.blue) == TEAM_SIZE
    if full and barred is None:
        result = _evaluated(world, draft, catalog=catalog, base=base, seat=seat,
                            kind="evaluate" if kind == "current" else kind,
                            solved=optimal.solved)
        result.scale_to(optimal.span)
        return result
    started = time.time()
    m, red_h, blue_h, bans_h = world.resolve(draft.map_name, draft.red, draft.blue, draft.bans)
    side = board_side(m, draft.side)
    result = Result(kind="evaluate" if full and kind == "current" else kind,
                    map_name=m.name if m else None, red=[h.name for h in red_h],
                    blue=[h.name for h in blue_h], locked=[] if full else [h.name for h in blue_h],
                    catalog=catalog, base=base, bans=[h.name for h in bans_h], side=side,
                    stage=board_stage(m, draft.stage), seat=seat, partial=not full)
    solver = optimal.solver
    if blue_h:
        cand = solver.prepare(Candidate(blue_h))
        solver.score(cand)
        result.record_candidate(cand, _board_facts(world, result, side), solver.considered)
    result.scale_to(optimal.span)
    if barred is not None:
        result.bar(barred)
    result.seconds = time.time() - started
    return result


def _barred(world: World, draft: Draft, optimal: _Optimal, stuck: bool) -> list[str] | None:
    """The limits a seat's own picks (`draft.blue`) break when its comp is not
    allowed, or None where it is. Not allowed: a full six that breaks one, or
    picks the fill's exact search proved no six completes within the limits
    (`stuck`). A half-drafted seat that breaks a limit it can still meet
    (one tank under a two-tank rule) is allowed: the picks to come can mend
    it."""
    blue_h = world.resolve(draft.map_name, draft.red, draft.blue, draft.bans)[2]
    if len(draft.blue) == TEAM_SIZE:
        return _broken(optimal.solver, blue_h) or None
    return _broken(optimal.solver, blue_h) if stuck else None


def _ruled_out(world: World, draft: Draft, catalog: list[Strategy]) -> list[str]:
    """The limits blue's picks (`draft.blue`) break as they stand - none where
    they break none alone - once the exact search has proved that no six on
    the whole roster that keeps them meets the limits."""
    m, red_h, blue_h, bans_h = world.resolve(draft.map_name, draft.red, draft.blue, draft.bans)
    return _broken(Objective(world, m, red=red_h, banned=bans_h, side=board_side(m, draft.side),
                             stage=board_stage(m, draft.stage), catalog=catalog, base=OFF),
                   blue_h)


def board(
        world: World, draft: Draft, *, catalog: list[Strategy] | None = None,
        brief: Brief | None = None) -> Board:
    """The whole board in one pass, at whatever step the draft is at - no map
    (the meta's best six), a map, a map and a side, the stage in play, bans,
    red's picks as they reveal:

        blue         blue's optimal six: the best counter to red's selection
                     as revealed - or, before they reveal a pick, to their
                     likely six - on this map, side and bans; blue's own
                     picks never constrain it
        red          red's optimal six: their best counter to blue's
                     selection, on the other side - the scale red's current
                     comp is measured on
        current      blue's picks as they stand, scored against red's
                     selection on blue's optimal's scale - or not allowed, with
                     no score, where the playbook's limits rule them out: a
                     full six that breaks one, or picks that no six keeping
                     them completes within the limits
        red_current  red's picks as they stand, scored against blue's
                     selection on red's optimal's scale; red's picks are the
                     other side's facts, never ruled out
        countered    blue's picks against red's optimal six - how you hold
                     if they answer you perfectly: a full six as it stands, a
                     half-drafted one filled, on the scale of blue's best
                     counter to that six (None without blue picks, when the
                     brief does not ask for it, when blue's picks are not
                     allowed, or when no six answers)
        fill         blue's locked picks with the empty slots filled by the
                     solver - the best six that keeps what you hold, on
                     blue's optimal's scale (None unless one to five are
                     locked, or when no six keeps them and meets the limits)
        momentum     the verdict from the two current comps, each
                     half-drafted seat read through its fill; red's fill is
                     solved for the verdict and not kept
        plan         the game plan in prose, from the same facts, for the six
                     the comps tab shows for blue: its optimal before any
                     blue pick, the fill around one to five, the picks
                     themselves at six
        shapes       the (tanks, damage, supports) triples the queue and the
                     playbook's shape limits allow - what the roster enforces
                     as you pick; a team past six picks or two tanks is refused
        expected     red's likely six from the data alone - a two-two-two from
                     the map's pick rates and the wiki's synergies, past the
                     bans - static for the board, no strategy read; what the
                     comps tab shows for red and what blue counters until red
                     reveals a pick

    The brief's weights override the files' for this board only - the
    playbook tab's sliders, its Meta slider among them; the files stay as
    they are and every result says the weights it was scored under. The
    brief's base is the default engine's weights every seat scores under -
    the playbook's meta.md where it names none - the likely six its counter
    term reads where the other seat has no picks.

    The searches run one after another in this process, each exact. Every
    CHECK_EVERY branches (inference.solver) a search asks the brief's check,
    and a board it reports superseded stops there and raises
    supersede.Superseded. A search past its budget (solver.Unbounded)
    refuses the board when it is a seat's optimal; a fill, red's fill or
    the countered case it happens in reads None, and a fill that runs out
    leaves blue's picks allowed, since nothing proved them otherwise.
    """
    brief = Brief() if brief is None else brief
    catalog = catalog_module.weighted(
        catalog_module.load() if catalog is None else catalog, brief.weights)
    base = weights_in_force(brief.base, brief.weights)
    watch = supersede.Watch(brief.superseded)
    m, red_h, blue_h, bans_h = world.resolve(draft.map_name, draft.red, draft.blue, draft.bans)
    draft = dataclasses.replace(draft, side=board_side(m, draft.side),
                                stage=board_stage(m, draft.stage))
    _check_teams(red_h, blue_h, "blue")
    expected = _expected(world, m, bans_h, draft, catalog, base)
    enemy = draft.red or tuple(expected.blue)
    # each seat's draft, from that seat's perspective: its own picks are `blue`
    blue_seat = dataclasses.replace(draft, red=enemy, blue=())
    # and every seat on the draft's stage: both sides fight on the same ground
    red_seat = Draft(map_name=draft.map_name, red=draft.blue, blue=(), bans=draft.bans,
                     side=opposite(draft.side), stage=draft.stage)
    ours = dataclasses.replace(draft, red=enemy)       # blue's current comp and fill
    theirs = Draft(map_name=draft.map_name, red=draft.blue, blue=draft.red, bans=draft.bans,
                   side=opposite(draft.side), stage=draft.stage)
    solve = _Pass(world, catalog, base, watch)
    blue = solve.optimal(blue_seat, seat="blue")
    red = solve.optimal(red_seat, seat="red")
    try:
        fill = solve.filled(ours, seat="blue", of=blue)
        stuck = False
    except Infeasible:
        # the exact search proved no six keeps blue's picks and meets the
        # limits: the fill is not solved, and blue's current comp is not allowed
        fill, stuck = None, True
    except Unbounded:
        fill, stuck = None, False
    # a full six is ranked against every legal six through its seat's search;
    # 100 is the seat's optimal, whatever it holds. The limits bind blue's picks
    cur = solve.current(ours, blue, seat="blue", stuck=stuck)
    red_cur = solve.current(theirs, red, seat="red")
    try:
        red_fill = solve.filled(theirs, seat="red", of=red)
    except (Infeasible, Unbounded):
        # red's revealed picks are the other side's facts, not ours to limit: past
        # a limit they already break no fill exists, and red is read off its picks
        red_fill = None
    countered = None
    if cur.barred is None and brief.countered and draft.blue:
        # a what-if: where no six answers red's six around blue's picks, it is not solved
        with contextlib.suppress(Infeasible, Unbounded):
            countered = solve.countered(dataclasses.replace(draft, red=tuple(red.result.blue)))
    seats = Seats(current=cur, red_current=red_cur, blue=blue.result, red=red.result,
                  fill=fill, red_fill=red_fill, countered=countered)
    # the six the comps tab shows for blue, which the plan describes: a comp
    # that is not allowed is described by the optimal instead
    held = len(draft.blue) == TEAM_SIZE and cur.barred is None
    shown = fill if fill is not None else cur if held else blue.result
    return Board(map_name=expected.map_name, side=draft.side, stage=draft.stage,
                 bans=list(draft.bans),
                 blue=blue.result, red=red.result, current=cur, red_current=red_cur,
                 fill=fill, countered=countered, momentum=momentum(seats),
                 plan=plan(world, m, draft.side, list(draft.bans), red_h, shown),
                 shapes=[list(s) for s in legal_shapes(catalog)], expected=expected)


def _drafting(seat: Draft) -> bool:
    """Whether a seat is half-drafted - one to five picks, which a fill completes."""
    return 0 < len(seat.blue) < TEAM_SIZE


class _Pass:
    """One pass of a board: the world, the weighted playbook and the default
    engine's weights it is solved under, and the board's Watch, which every
    search asks as it runs."""

    def __init__(self, world: World, catalog: list[Strategy], base: BaseWeights,
                 watch: supersede.Watch) -> None:
        self.world, self.catalog, self.base, self.watch = world, catalog, base, watch

    def optimal(self, draft: Draft, *, seat: Seat, kind: ResultKind = "infer",
                scale_of: Solver | None = None) -> _Optimal:
        """`seat`'s optimal six on `draft`, on `scale_of`'s scale where given."""
        self.watch.check()
        return _optimal(self.world, draft, catalog=self.catalog, base=self.base,
                        top=BOARD_TOP, seat=seat, kind=kind, check=self.watch.check,
                        scale_of=scale_of)

    def current(self, draft: Draft, optimal: _Optimal, *, seat: Seat,
                stuck: bool | None = None) -> Result:
        """`seat`'s picks as they stand, on its optimal's scale; a full six is
        ranked against every legal six. With `stuck` - blue's seat, True where
        the fill's search proved no six keeps the picks and meets the limits -
        the limits bind the picks, and a comp they rule out is not allowed;
        None leaves the picks as the other side's facts."""
        self.watch.check()
        barred = None if stuck is None else _barred(self.world, draft, optimal, stuck)
        return _current(self.world, draft, optimal=optimal, catalog=self.catalog,
                        base=self.base, seat=seat, kind="current", barred=barred)

    def filled(
            self, draft: Draft, *, seat: Seat, of: _Optimal,
            kind: ResultKind = "fill") -> Result | None:
        """`seat`'s picks (`draft.blue`) with the empty slots filled by the
        solver on the seat's scale, read on its span (`of`): how close the
        best completion comes. None unless the seat is half-drafted."""
        if not _drafting(draft):
            return None
        fill = self.optimal(draft, seat=seat, kind=kind, scale_of=of.solver).result
        fill.scale_to(of.span)
        return fill

    def countered(self, draft: Draft) -> Result | None:
        """Blue's picks (`draft.blue`) against red's optimal six (`draft.red`):
        how they hold if red answers perfectly, on the scale of blue's best
        counter to that six. A full six is ranked against every legal six; a
        half-drafted one is filled, as the fill reads blue's picks."""
        top = self.optimal(dataclasses.replace(draft, blue=()), seat="blue")
        if _drafting(draft):
            return self.filled(draft, seat="blue", of=top, kind="countered")
        return _current(self.world, draft, optimal=top, catalog=self.catalog,
                        base=self.base, seat="blue", kind="countered")


def _check_teams(red_h: Sequence[Hero], blue_h: Sequence[Hero], seat: Seat) -> None:
    """Refuse a board the queue would not seat: a team past its tanks, on
    either seat - the other seat's team (`red_h`) first, then `seat`'s own
    (`blue_h`), each named from `seat`'s perspective. A team past six picks
    never gets this far: Draft refuses it."""
    check_tanks(red_h, "red" if seat == "blue" else "blue")
    check_tanks(blue_h, seat)


def _expected(
        world: World, m: Map | None, bans_h: Sequence[Hero], draft: Draft,
        catalog: list[Strategy], base: BaseWeights) -> Result:
    """Red's likely six - the map and the meta alone, past the bans - static
    for the board; until red reveals a pick it is what blue's seat counters.
    A Result like every other seat: its picks carry the reason each rests on."""
    likely = compute.expected_picks(world, m, banned=bans_h)
    return Result(kind="expected", map_name=m.name if m else None, red=[],
                  blue=[p["hero"] for p in likely], locked=[], catalog=catalog, base=base,
                  bans=list(draft.bans), side=draft.side, stage=draft.stage, seat="red",
                  picks=[Pick(hero=p["hero"], role=p["role"], locked=p["locked"], why=p["why"],
                              evidence=[])
                         for p in likely])
