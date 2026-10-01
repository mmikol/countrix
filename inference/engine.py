"""infer() and board(): the API over the solver.

    infer(world, Draft(map_name="King's Row", red=("Zarya", "Pharah"), blue=("Ana",),
                       side="attack"))

returns the optimal six around the locked picks, each pick with the facts
that justify it (the facts the board would show for map + red + the
six), the score broken down into the default engine's terms and each
strategy's, and the alternatives. board() does it for both seats - blue's
absolute optimal, red around its revealed ones, on opposite sides of a
sided map - scores the current blue picks as they stand, and suggests the
swaps from blue's picks that pay for their cost (inference.swaps). Both refuse
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

from facts import board_facts, compute
from facts.draft import (
    TEAM_SIZE,
    Draft,
    Seat,
    Side,
    board_side,
    board_stage,
    check_tanks,
)
from facts.factset import FactSet
from facts.model import ROLES, Hero, Map, Resolved, World
from inference import catalog as catalog_module
from inference import supersede, swaps
from inference.base import OFF, SWAP, BaseWeights
from inference.plan import Seats, momentum, plan
from inference.result import (
    Alternative,
    Board,
    Momentum,
    Pick,
    Result,
    ResultKind,
    Span,
    StageRow,
    StageSwap,
    SwapOdds,
    Swaps,
    not_allowed,
)
from inference.scoring import Candidate, Objective
from inference.shapes import legal_shapes
from inference.solver import Infeasible, Solved, Solver, Unbounded, evaluate_comp
from inference.strategy import Strategy

TOP_DEFAULT = 5             # alternatives when a caller names none
TOP_CEILING = 20            # the most alternatives a caller may ask for


class _SeatBoard(NamedTuple):
    """A draft read for one seat: its names as the World's objects, and the
    side and stage the board plays, each as the map keeps it."""
    board: Resolved
    side: Side
    stage: str

    def result(
            self, kind: ResultKind, seat: Seat, *, catalog: list[Strategy],
            base: BaseWeights, blue: list[str], locked: list[str],
            partial: bool = False) -> Result:
        """The seat's Result before its six is scored: the map, the other
        side's picks, the bans, the side and the stage."""
        m = self.board.map
        return Result(kind=kind, map_name=m.name if m else None,
                      red=[h.name for h in self.board.red], blue=blue, locked=locked,
                      catalog=catalog, base=base, bans=[h.name for h in self.board.banned],
                      side=self.side, stage=self.stage, seat=seat, partial=partial)


def _seat_board(world: World, draft: Draft) -> _SeatBoard:
    """The draft's names resolved - World.resolve's refusals - with the side
    and stage the map keeps (board_side, board_stage)."""
    board = world.resolve(draft.map_name, draft.red, draft.blue, draft.bans)
    return _SeatBoard(board, board_side(board.map, draft.side),
                      board_stage(board.map, draft.stage))


def clamp_top(top: int | None = None) -> int:
    """The alternatives a caller asks for, 1..TOP_CEILING: left out (None),
    TOP_DEFAULT; any other number, 0 and negatives included, clamped into
    the range, so the MCP infer tool's 0 reads as the floor. The search has
    no width to choose - it is exact - so this is its one knob, and the tool
    passes a caller's through here once its schema has checked it is an
    integer."""
    return max(1, min(TOP_DEFAULT if top is None else top, TOP_CEILING))


BOARD_TOP = 5               # the alternatives each of a board's seats keeps


@dataclasses.dataclass(frozen=True, kw_only=True)
class Brief:
    """What a caller asks of one board beyond the draft: the playbook tab's
    weights ({heuristic id: 0..10}, META, the default engine's meta, and
    SWAP, the swap cost - for this board only), whether to solve the
    countered case - the MCP board prints it, the page never reads it - the
    check that says a newer request from the same client has superseded
    this one, the default engine's weights, the playbook's meta.md's (None)
    unless a caller names others (OFF turns it off), the swap cost in share
    points, meta.md's (None) unless a caller names another, whether to
    search blue's swaps, and whether to walk the plan stage by stage."""
    weights: Mapping[str, float] | None = None
    countered: bool = True
    superseded: Callable[[], bool] | None = None
    base: BaseWeights | None = None
    swap: float | None = None
    swaps: bool = True
    stages: bool = True


def weights_in_force(
        base: BaseWeights | None, weights: Mapping[str, float] | None = None) -> BaseWeights:
    """The default engine's weights a board or an infer scores under: the
    caller's `base`, else the playbook in force's meta.md
    (catalog.engine_weights), with a board's own meta on top where its
    `weights` set one (BaseWeights.metered)."""
    return (catalog_module.engine_weights() if base is None else base).metered(weights)


def swap_in_force(brief: Brief) -> float:
    """The swap cost a board suggests blue's swaps under, in share points:
    its weights' SWAP (the playbook tab's Swap cost slider), else the
    brief's, else the playbook in force's meta.md (catalog.swap_cost)."""
    if brief.weights and SWAP in brief.weights:
        return brief.weights[SWAP]
    return catalog_module.swap_cost() if brief.swap is None else brief.swap


def _order(heroes: Iterable[Hero]) -> list[str]:
    return [h.name for h in sorted(heroes, key=lambda h: (ROLES.index(h.role), h.name))]


def _board_facts(world: World, result: Result, side: Side) -> FactSet:
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
    started = time.monotonic()
    seated = _seat_board(world, draft)
    m, red_h, blue_h, bans_h = seated.board
    _check_teams(red_h, blue_h, seat)
    result = seated.result(kind, seat, catalog=catalog, base=base, blue=[],
                           locked=[h.name for h in blue_h])
    solver = Solver(world, m, red=red_h, locked=blue_h, banned=bans_h, side=seated.side,
                    stage=seated.stage, catalog=catalog, base=base, check=check)
    if scale_of is not None:
        solver.adopt_scale(scale_of)
    solved = solver.solve(top=max(top, 1) + 1)
    best = solved.ranked[0]
    result.blue = _order(best.heroes)
    fs = _board_facts(world, result, seated.side)
    result.record_candidate(best, fs, solver.considered)
    result.tied = solver.ties(solved)
    result.alternatives = [Alternative(blue=_order(c.heroes), score=round(c.score, 3),
                                       normalized=None)
                           for c in solved.ranked[1:top + 1]]
    optimal = _Optimal(result, solver, solved)
    result.scale_to(optimal.span)
    result.seconds = time.monotonic() - started
    return optimal


def _evaluated(
        world: World, draft: Draft, *, catalog: list[Strategy], base: BaseWeights,
        seat: Seat, kind: ResultKind, optimal: _Optimal) -> Result:
    """`seat`'s full six (`draft.blue`), scored and ranked against every
    legal six, labelled `kind`, through the search of `optimal`, the seat's
    own on this board, and read on its span. A six that breaks a limit is
    scored with its breaches listed: the board bars blue's before it gets
    here, and ranks red's."""
    started = time.monotonic()
    seated = _seat_board(world, draft)
    red_h, blue_h = seated.board.red, seated.board.blue
    _check_teams(red_h, blue_h, seat)
    result = seated.result(kind, seat, catalog=catalog, base=base,
                           blue=[h.name for h in blue_h], locked=[])
    evaluated = evaluate_comp(optimal.solved, blue_h)
    fs = _board_facts(world, result, seated.side)
    result.record_candidate(evaluated.target, fs, evaluated.solver.considered)
    result.rank, result.outranked = evaluated.rank, evaluated.outranked
    result.alternatives = [Alternative(blue=_order(c.heroes), score=round(c.score, 3),
                                       normalized=None)
                           for c in evaluated.field[:3]]
    result.scale_to(optimal.span)
    result.seconds = time.monotonic() - started
    return result


def _current(
        world: World, draft: Draft, *, optimal: _Optimal, catalog: list[Strategy],
        base: BaseWeights, seat: Seat, kind: ResultKind,
        barred: list[str] | None = None) -> Result:
    """`seat`'s picks (`draft.blue`, from that seat's perspective) as they
    stand against the other seat's (`draft.red`), on the span of the seat's
    `optimal`: its Solver's scale and floor, and its score, the 100. A full
    six is ranked against every legal six through the optimal's search, and
    reads "evaluate" where `kind` is "current", any other kind staying as
    given; a partial team is scored on the scale the optimal's search
    froze, and says so. `barred` is the limits the picks break when their
    comp is not allowed (_barred): it is scored nowhere and ranked against
    nothing, and says why."""
    full = len(draft.blue) == TEAM_SIZE
    label: ResultKind = "evaluate" if full and kind == "current" else kind
    if full and barred is None:
        return _evaluated(world, draft, catalog=catalog, base=base, seat=seat, kind=label,
                          optimal=optimal)
    started = time.monotonic()
    seated = _seat_board(world, draft)
    blue_h = seated.board.blue
    picks = [h.name for h in blue_h]
    result = seated.result(label, seat, catalog=catalog, base=base, blue=picks,
                           locked=[] if full else list(picks), partial=not full)
    solver = optimal.solver
    if blue_h:
        cand = solver.prepare(Candidate(blue_h))
        solver.score(cand)
        result.record_candidate(cand, _board_facts(world, result, seated.side),
                                solver.considered)
    result.scale_to(optimal.span)
    if barred is not None:
        result.bar(barred)
    result.seconds = time.monotonic() - started
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
    seated = _seat_board(world, draft)
    m, red_h, blue_h, bans_h = seated.board
    return _broken(Objective(world, m, red=red_h, banned=bans_h, side=seated.side,
                             stage=seated.stage, catalog=catalog, base=OFF),
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
        swaps        the swaps from blue's picks that pay for their cost -
                     one joint answer, the best six reachable from the picks
                     when each pick dropped costs the swap cost (meta.md's,
                     the brief's, or its weights' SWAP), with blue's share
                     and the fight odds before and after; the suggestion is
                     withheld where the odds would fall (None without blue
                     picks, or when the brief does not ask for it)
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
        stages       the plan stage by stage on a map with stages
                     (inference.swaps.chain), from the six the comps tab
                     shows for blue; empty on a map without stages, or when
                     the brief leaves it out
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
    seated = _seat_board(world, draft)
    m, red_h, blue_h, bans_h = seated.board
    draft = dataclasses.replace(draft, side=seated.side, stage=seated.stage)
    _check_teams(red_h, blue_h, "blue")
    expected = _expected(world, m, bans_h, draft, catalog, base)
    enemy = draft.red or tuple(expected.blue)
    # each seat's draft, from that seat's perspective: its own picks are `blue`
    blue_seat = dataclasses.replace(draft, red=enemy, blue=())
    ours = dataclasses.replace(draft, red=enemy)       # blue's current comp and fill
    # red's, the draft flipped, on the draft's stage: both sides fight on the same ground
    theirs = draft.flipped()
    red_seat = dataclasses.replace(theirs, blue=())
    solve = _Pass(world, catalog, base, watch)
    blue = solve.optimal(blue_seat, seat="blue")
    red = solve.optimal(red_seat, seat="red")
    unsolved = False
    try:
        fill = solve.filled(ours, seat="blue", of=blue)
        stuck = False
    except Infeasible:
        # the exact search proved no six keeps blue's picks and meets the
        # limits: the fill is not solved, and blue's current comp is not allowed
        fill, stuck = None, True
    except Unbounded:
        # the fill ran out of budget: no answer either way, which the swaps
        # must not read as a proof that no six keeps the picks
        fill, stuck, unsolved = None, False, True
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
    seats = Seats(current=cur, red_current=red_cur, fill=fill, red_fill=red_fill,
                  countered=countered)
    mo = momentum(seats)
    # the swap cost, read once: the swaps above the picks and the chosen
    # stage's row are one answer
    cost = swap_in_force(brief) if brief.swaps or brief.stages else 0.0
    suggested = None
    if brief.swaps and draft.blue:
        suggested = solve.swaps(draft, enemy, blue, _Seat(cur, fill, mo, unsolved), cost)
    # the six the comps tab shows for blue, which the plan describes: a comp
    # that is not allowed is described by the optimal instead
    held = len(draft.blue) == TEAM_SIZE and cur.barred is None
    shown = fill if fill is not None else cur if held else blue.result
    staged = solve.stages(m, draft, blue, shown.blue, cost, suggested) if brief.stages else []
    return Board(map_name=expected.map_name, side=draft.side, stage=draft.stage,
                 bans=list(draft.bans),
                 blue=blue.result, red=red.result, current=cur, red_current=red_cur,
                 fill=fill, countered=countered, momentum=mo,
                 plan=plan(world, m, draft.side, list(draft.bans), red_h, shown),
                 shapes=[list(s) for s in legal_shapes(catalog)], expected=expected,
                 swaps=suggested, stages=staged)


class _Seat(NamedTuple):
    """Blue's seat as the swaps read it: its current comp, its fill where it
    is half-drafted, the board's momentum, whose share and odds are the
    swaps' before, and whether the fill ran out of budget."""
    current: Result
    fill: Result | None
    momentum: Momentum
    unsolved: bool = False


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

    def swaps(
            self, draft: Draft, enemy: tuple[str, ...], blue: _Optimal, seat: _Seat,
            cost: float) -> Swaps:
        """Blue's swaps (inference.swaps): the best six reachable from blue's
        picks (`draft.blue`) against `enemy` - red's picks, else its likely
        six - at `cost` share points a pick dropped, on blue's optimal's
        board and scale. Where a swap is suggested, red's optimal, current
        comp and fill are solved again against the six it makes, and the
        fight odds read off them as the momentum reads the board's; a
        suggestion that lowers them is withheld."""
        picks = self.world.resolve(draft.map_name, draft.red, draft.blue, draft.bans).blue
        full = len(picks) == TEAM_SIZE
        before, odds = seat.momentum["blue"], seat.momentum["odds"]
        fill = seat.fill
        # the best six that keeps every pick: the picks at six, the fill around
        # fewer; none where no six keeps them
        keeper: list[Hero] | None = None
        if full and seat.current.barred is None:
            keeper = picks
        elif not full and fill is not None:
            keeper = self.world.resolve(None, (), fill.blue).blue
        kept = Swaps(status="keep", stage=draft.stage, cost=cost,
                     six=_order(keeper) if keeper is not None else [],
                     pairs=[], open=swaps.open_slots(
                         [p for p in fill.picks if not p["locked"]] if fill is not None else []),
                     before=before, after=before, odds=SwapOdds(before=odds, after=odds),
                     verdict=swaps.verdict([], cost, before, 0, None, partial=not full))

        def none(why: str) -> Swaps:
            kept["status"] = "none"
            kept["verdict"] = "no swaps: " + why
            return kept
        raw = swaps.raw_cost(cost, blue.span)
        if seat.unsolved:
            return none("the fill around the picks was not solved within the search's budget")
        if raw is None:
            return none(blue.result.waiting() or "the seat is unscored")
        self.watch.check()
        try:
            target = swaps.search(blue.solver, picks, raw, keeper)
        except (Infeasible, Unbounded) as error:
            return none(str(error))
        if not target.gains:
            return kept
        ours = dataclasses.replace(draft, red=enemy, blue=tuple(h.name for h in target.six.heroes))
        six = _scored(self.world, ours, blue, target.six, self.catalog, self.base,
                      locked=[h.name for h in picks])
        pairs = swaps.paired(picks, target.six.heroes, six)
        after = six.share()
        odds_after = self._against(draft, six)["odds"] if draft.red else None
        # blue's fight odds before and after, where both are read
        both = ((odds["blue"], odds_after["blue"])
                if odds is not None and odds_after is not None else None)
        # the owner's rule: a swap raises the score and the odds of winning a
        # fight, so a swap the odds read and do not rise on is withheld
        if both is not None and both[1] <= both[0]:
            kept["status"] = "withheld"
            kept["verdict"] = swaps.withheld(pairs, both)
            return kept
        return Swaps(status="suggested", stage=draft.stage, cost=cost, six=list(six.blue),
                     pairs=pairs, open=kept["open"], before=before, after=after,
                     odds=SwapOdds(before=odds, after=odds_after),
                     verdict=swaps.verdict(pairs, cost, before, after, both, partial=not full))

    def stages(
            self, m: Map | None, draft: Draft, blue: _Optimal, origin: Sequence[str],
            cost: float, suggested: Swaps | None) -> list[StageRow]:
        """The plan stage by stage (inference.swaps.chain) from `origin`, the
        six the comps tab shows, against blue's enemy, on blue's optimal's
        board and scale, at `cost` share points a hero changed; the board's
        chosen stage takes the board's own swap answer - a swap suggested, or
        the picks kept - solved on that stage, so its row and the swaps above
        the picks are one answer; a swap withheld or not searched leaves the
        row the origin's. An unscored seat's stages swap at no cost, and say
        so. Empty on a map without stages."""
        if m is None or not m.stages or not origin:
            return []
        six = self.world.resolve(None, (), tuple(origin)).blue
        taken = None
        if suggested is not None and suggested["status"] in ("suggested", "keep"):
            taken = swaps.Taken(
                six=self.world.resolve(None, (), tuple(suggested["six"])).blue
                if suggested["status"] == "suggested" else six,
                swaps=[StageSwap({"out": p["out"], "in": p["in"]}) for p in suggested["pairs"]])
        plain = blue.solver
        whole = Objective(self.world, m, red=plain.red, banned=plain.banned_heroes,
                          side=plain.side, catalog=plain.catalog, base=OFF)
        raw = swaps.raw_cost(cost, blue.span)
        if raw is None:
            raw = cost = 0.0
        self.watch.check()
        return swaps.chain(swaps.ChainStart(plain=plain, whole=whole, chosen=draft.stage,
                                            origin=six, raw=raw, cost=cost, taken=taken))

    def _against(self, draft: Draft, six: Result) -> Momentum:
        """The momentum were blue to field `six`, a Result on blue's
        optimal's span: red's optimal, current comp and fill solved again
        against it, and read with blue's six, as the board's own is."""
        theirs = dataclasses.replace(draft, blue=tuple(six.blue)).flipped()
        red = self.optimal(dataclasses.replace(theirs, blue=()), seat="red")
        red_cur = self.current(theirs, red, seat="red")
        try:
            red_fill = self.filled(theirs, seat="red", of=red)
        except (Infeasible, Unbounded):
            red_fill = None
        return momentum(Seats(current=six, red_current=red_cur, red_fill=red_fill))


def _scored(world: World, draft: Draft, optimal: _Optimal, cand: Candidate,
            catalog: list[Strategy], base: BaseWeights, locked: Sequence[str]) -> Result:
    """Blue's six `cand` (`draft.blue`), scored on its optimal's objective,
    as a Result on the optimal's span: its picks, their reasons and its
    breakdown - `locked`, the picks it keeps, marked."""
    seated = _seat_board(world, draft)
    result = seated.result("evaluate", "blue", catalog=catalog, base=base,
                           blue=_order(seated.board.blue),
                           locked=[name for name in locked if name in set(draft.blue)])
    result.record_candidate(cand, _board_facts(world, result, seated.side),
                            optimal.solver.considered)
    result.scale_to(optimal.span)
    return result


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
