"""infer() and board(): the API over the solver.

    infer(world, Draft(map_name="King's Row", red=("Zarya", "Pharah"), blue=("Ana",),
                       side="attack"))

returns the optimal six around the locked picks, each pick with the facts
that justify it (the facts the board would show for map + red + the
six), the score broken down into the default engine's terms and each
strategy's, and the alternatives. board() does it for blue's seat - its
absolute optimal - scores the current blue picks as they stand, suggests
the swaps from blue's picks that pay for their cost (inference.swaps), and
reads red's likely six around its revealed picks
(facts.compute.expected_picks), which nothing solves or scores. Both
refuse a team past the queue's tanks, on either side, and a stage the map
does not list, and score under the default engine at the playbook's
weights (its meta.md) unless the caller names others; base.OFF, the meta
at 0, is the playbook alone. Blue's seat is solved on the board's stage -
the ground in play, the whole map where the draft names none. The limits
bind blue's own picks: the board reads a six that breaks one as not
allowed, and infer refuses locked picks no six completes. The records are
result.py's and the prose plan.py's. Every search is exact
(inference.solver) and runs in this process, one after another.
"""

import dataclasses
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import NamedTuple

from facts import board_facts, compute
from facts.draft import (
    TEAM_SIZE,
    Draft,
    Side,
    board_side,
    board_stage,
    check_tanks,
)
from facts.factset import FactSet
from facts.model import ROLES, Hero, Map, Resolved, World
from inference import catalog as catalog_module
from inference import supersede, swaps
from inference.base import LOGIT_PER_POINT, OFF, SWAP, BaseWeights
from inference.plan import HeadToHead, Seats, momentum, plan
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
    """A draft read for blue's seat: its names as the World's objects, and
    the side and stage the board plays, each as the map keeps it."""
    board: Resolved
    side: Side
    stage: str

    def result(
            self, kind: ResultKind, *, catalog: list[Strategy], base: BaseWeights,
            blue: list[str], locked: list[str], partial: bool = False) -> Result:
        """Blue's Result before its six is scored: the map, red's picks, the
        bans, the side and the stage."""
        m = self.board.map
        return Result(kind=kind, map_name=m.name if m else None,
                      red=[h.name for h in self.board.red], blue=blue, locked=locked,
                      catalog=catalog, base=base, bans=[h.name for h in self.board.banned],
                      side=self.side, stage=self.stage, partial=partial)


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


BOARD_TOP = 5               # the alternatives blue's optimal and fill keep


@dataclasses.dataclass(frozen=True, kw_only=True)
class Brief:
    """What a caller asks of one board beyond the draft: the playbook tab's
    weights ({heuristic id: 0..10}, META, the default engine's meta, and
    SWAP, the swap cost - for this board only), the check that says a newer
    request from the same client has superseded this one, the default
    engine's weights, the playbook's meta.md's (None) unless a caller names
    others (OFF turns it off), the swap cost in share points, meta.md's
    (None) unless a caller names another, whether to search blue's swaps,
    and whether to walk the plan stage by stage."""
    weights: Mapping[str, float] | None = None
    superseded: Callable[[], bool] | None = None
    base: BaseWeights | None = None
    swap: float | None = None
    search_swaps: bool = True
    walk_stages: bool = True


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
        if not draft.blue:
            return _optimal(world, draft, catalog=catalog, base=base, top=top,
                            kind="infer").result
        # around locked picks the share is the seat's own optimal's, as the
        # board reads its fill, so infer and the board give one six one share
        seat = _optimal(world, dataclasses.replace(draft, blue=()), catalog=catalog,
                        base=base, top=1, kind="infer")
        result = _optimal(world, draft, catalog=catalog, base=base, top=top, kind="infer",
                          scale_of=seat.solver).result
        result.scale_to(seat.span)
        return result
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
        top: int, kind: ResultKind, check: Callable[[], None] | None = None,
        scale_of: Solver | None = None) -> _Optimal:
    """Blue's optimal six around its locked picks (`draft.blue`) against
    red's revealed ones (`draft.red`), labelled `kind`, with `top`
    alternatives. `scale_of` is a solver on the same board whose scale this
    search takes - a fill takes the optimal's - and `check` is asked as the
    search runs whether the board was superseded."""
    started = time.monotonic()
    seated = _seat_board(world, draft)
    m, red_h, blue_h, bans_h = seated.board
    _check_teams(red_h, blue_h)
    result = seated.result(kind, catalog=catalog, base=base, blue=[],
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
        optimal: _Optimal) -> Result:
    """Blue's full six (`draft.blue`), scored and ranked against every legal
    six through the search of `optimal`, blue's own on this board, and read
    on its span. A six that breaks a limit is scored with its breaches
    listed; the board bars blue's before it gets here."""
    started = time.monotonic()
    seated = _seat_board(world, draft)
    red_h, blue_h = seated.board.red, seated.board.blue
    _check_teams(red_h, blue_h)
    result = seated.result("evaluate", catalog=catalog, base=base,
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
        base: BaseWeights, barred: list[str] | None = None) -> Result:
    """Blue's picks (`draft.blue`) as they stand against red's (`draft.red`),
    on the span of blue's `optimal`: its Solver's scale and floor, and its
    score, the 100. A full six is ranked against every legal six through
    the optimal's search, and reads "evaluate"; a partial team reads
    "current", scored on the scale the optimal's search froze, and says so.
    `barred` is the limits the picks break when their comp is not allowed
    (_barred): it is scored nowhere and ranked against nothing, and says
    why."""
    full = len(draft.blue) == TEAM_SIZE
    label: ResultKind = "evaluate" if full else "current"
    if full and barred is None:
        return _evaluated(world, draft, catalog=catalog, base=base, optimal=optimal)
    started = time.monotonic()
    seated = _seat_board(world, draft)
    blue_h = seated.board.blue
    picks = [h.name for h in blue_h]
    result = seated.result(label, catalog=catalog, base=base, blue=picks,
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
                     as revealed - before they reveal a pick, the default
                     engine's counter term reads their likely six - on this
                     map, side and bans; blue's own picks never constrain it
        current      blue's picks as they stand, scored against red's
                     selection on blue's optimal's scale - or not allowed, with
                     no score, where the playbook's limits rule them out: a
                     full six that breaks one, or picks that no six keeping
                     them completes within the limits
        swaps        the swaps from blue's picks that pay for their cost -
                     one joint answer, the best six reachable from the picks
                     when each pick dropped costs the swap cost (meta.md's,
                     the brief's, or its weights' SWAP), with blue's share
                     before and after (None without blue picks, or when the
                     brief does not ask for it)
        fill         blue's locked picks with the empty slots filled by the
                     solver - the best six that keeps what you hold, on
                     blue's optimal's scale (None unless one to five are
                     locked, or when no six keeps them and meets the limits)
        momentum     blue's standing, a half-drafted seat read through its
                     fill, the fight odds, and the badge above each picker:
                     blue's share, how often red's likely six is picked
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
        expected     red's likely six from the data alone - red's revealed
                     picks, and for each open slot the hero with the highest
                     pick score, past the bans; no strategy read, each pick
                     with its pick score. Red is never optimized: this is
                     what the board suggests for red, and what the counter
                     term and the fight odds read

    The brief's weights override the files' for this board only - the
    playbook tab's sliders, its Meta slider among them; the files stay as
    they are and every result says the weights it was scored under. The
    brief's base is the default engine's weights blue's seat scores under -
    the playbook's meta.md where it names none - the likely six its counter
    term reads where red has no picks.

    The searches run one after another in this process, each exact. Every
    CHECK_EVERY branches (inference.solver) a search asks the brief's check,
    and a board it reports superseded stops there and raises
    supersede.Superseded. A search past its budget (solver.Unbounded)
    refuses the board when it is blue's optimal; a fill it happens in reads
    None and leaves blue's picks allowed, since nothing proved them
    otherwise.
    """
    brief = Brief() if brief is None else brief
    catalog = catalog_module.weighted(
        catalog_module.load() if catalog is None else catalog, brief.weights)
    base = weights_in_force(brief.base, brief.weights)
    watch = supersede.Watch(brief.superseded)
    seated = _seat_board(world, draft)
    m, red_h, blue_h, bans_h = seated.board
    draft = dataclasses.replace(draft, side=seated.side, stage=seated.stage)
    _check_teams(red_h, blue_h)
    expected = _likely(world, m, red_h, bans_h, draft, catalog, base)
    # blue's seat: its own picks are `blue`, and red is its revealed picks alone -
    # the default engine's counter term reads red's likely six where it has none
    # (base.opponent), as infer does. Red is never solved
    blue_seat = dataclasses.replace(draft, blue=())
    ours = draft                                       # blue's current comp and fill
    solve = _Pass(world, catalog, base, watch)
    blue = solve.optimal(blue_seat)
    unsolved = False
    try:
        fill = solve.filled(ours, of=blue)
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
    cur = solve.current(ours, blue, stuck=stuck)
    # the six the comps tab shows for blue, which the plan describes: a comp
    # that is not allowed is described by the optimal instead
    held = len(draft.blue) == TEAM_SIZE and cur.barred is None
    shown = fill if fill is not None else cur if held else blue.result
    # the fight odds read that six against red's likely six on the default
    # engine alone; a comp the limits rule out has none
    measured = cur.barred is None and not (_drafting(draft) and fill is None)
    head = _head_to_head(world, m, draft, shown.blue, expected.blue, base,
                         bans_h) if measured else None
    mo = momentum(Seats(current=cur, expected=expected, fill=fill, head=head))
    # the swap cost, read once: the swaps above the picks and the chosen
    # stage's row are one answer
    cost = swap_in_force(brief) if brief.search_swaps or brief.walk_stages else 0.0
    suggested = None
    if brief.search_swaps and draft.blue:
        suggested = solve.swaps(draft, blue, _Seat(cur, fill, mo, unsolved), cost)
    staged = solve.stages(m, draft, blue, shown.blue, cost, suggested) if brief.walk_stages else []
    return Board(map_name=expected.map_name, side=draft.side, stage=draft.stage,
                 bans=list(draft.bans),
                 blue=blue.result, current=cur, fill=fill, momentum=mo,
                 plan=plan(world, m, draft.side, list(draft.bans), red_h, shown),
                 shapes=[list(s) for s in legal_shapes(catalog)], expected=expected,
                 swaps=suggested, stages=staged)


class _Seat(NamedTuple):
    """Blue's seat as the swaps read it: its current comp, its fill where it
    is half-drafted, the board's momentum, whose share is the swaps' before,
    and whether the fill ran out of budget."""
    current: Result
    fill: Result | None
    momentum: Momentum
    unsolved: bool = False


def _drafting(seat: Draft) -> bool:
    """Whether a seat is half-drafted - one to five picks, which a fill completes."""
    return 0 < len(seat.blue) < TEAM_SIZE


class _Pass:
    """One pass of a board, blue's seat alone - red is never solved: the
    world, the weighted playbook and the default engine's weights it is
    solved under, and the board's Watch, which every search asks as it
    runs."""

    def __init__(self, world: World, catalog: list[Strategy], base: BaseWeights,
                 watch: supersede.Watch) -> None:
        self.world, self.catalog, self.base, self.watch = world, catalog, base, watch

    def optimal(self, draft: Draft, *, kind: ResultKind = "infer",
                scale_of: Solver | None = None) -> _Optimal:
        """Blue's optimal six on `draft`, on `scale_of`'s scale where given."""
        self.watch.check()
        return _optimal(self.world, draft, catalog=self.catalog, base=self.base,
                        top=BOARD_TOP, kind=kind, check=self.watch.check,
                        scale_of=scale_of)

    def current(self, draft: Draft, optimal: _Optimal, *, stuck: bool) -> Result:
        """Blue's picks as they stand, on its optimal's scale; a full six is
        ranked against every legal six. The limits bind the picks: with
        `stuck` - True where the fill's search proved no six keeps them and
        meets the limits - a comp they rule out is not allowed."""
        self.watch.check()
        return _current(self.world, draft, optimal=optimal, catalog=self.catalog,
                        base=self.base, barred=_barred(self.world, draft, optimal, stuck))

    def filled(self, draft: Draft, *, of: _Optimal) -> Result | None:
        """Blue's picks (`draft.blue`) with the empty slots filled by the
        solver on the seat's scale, read on its span (`of`): how close the
        best completion comes. None unless the seat is half-drafted."""
        if not _drafting(draft):
            return None
        fill = self.optimal(draft, kind="fill", scale_of=of.solver).result
        fill.scale_to(of.span)
        return fill

    def swaps(self, draft: Draft, blue: _Optimal, seat: _Seat, cost: float) -> Swaps:
        """Blue's swaps (inference.swaps): the best six reachable from blue's
        picks (`draft.blue`) against red's revealed picks, at `cost` share
        points a pick dropped, on blue's optimal's board and scale."""
        picks = self.world.resolve(draft.map_name, draft.red, draft.blue, draft.bans).blue
        full = len(picks) == TEAM_SIZE
        before = seat.momentum["blue"]
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
                     before=before, after=before,
                     verdict=swaps.verdict([], cost, before, 0, partial=not full))

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
        ours = dataclasses.replace(draft, blue=tuple(h.name for h in target.six.heroes))
        six = _scored(self.world, ours, blue, target.six, self.catalog, self.base,
                      locked=[h.name for h in picks])
        pairs = swaps.paired(picks, target.six.heroes, six)
        after = six.share()
        return Swaps(status="suggested", stage=draft.stage, cost=cost, six=list(six.blue),
                     pairs=pairs, open=kept["open"], before=before, after=after,
                     verdict=swaps.verdict(pairs, cost, before, after, partial=not full))

    def stages(
            self, m: Map | None, draft: Draft, blue: _Optimal, origin: Sequence[str],
            cost: float, suggested: Swaps | None) -> list[StageRow]:
        """The plan stage by stage (inference.swaps.chain) from `origin`, the
        six the comps tab shows, against red's revealed picks, on blue's optimal's
        board and scale, at `cost` share points a hero changed; the board's
        chosen stage takes the board's own swap answer - a swap suggested, or
        the picks kept - solved on that stage, so its row and the swaps above
        the picks are one answer; a swap not searched leaves the row the
        origin's. An unscored seat's stages swap at no cost, and say so.
        Empty on a map without stages."""
        if m is None or not m.stages or not origin:
            return []
        six = self.world.resolve(None, (), tuple(origin)).blue
        taken = None
        if suggested is not None and suggested["status"] in ("suggested", "keep"):
            taken = swaps.Taken(
                six=self.world.resolve(None, (), tuple(suggested["six"])).blue
                if suggested["status"] == "suggested" else six,
                swaps=[StageSwap({"out": p["out"], "in": p["in"]}) for p in suggested["pairs"]])
        raw = swaps.raw_cost(cost, blue.span)
        if raw is None:
            raw = cost = 0.0
        self.watch.check()
        return swaps.chain(swaps.ChainStart(plain=blue.solver, chosen=draft.stage, origin=six,
                                            raw=raw, cost=cost, taken=taken))


def _scored(world: World, draft: Draft, optimal: _Optimal, cand: Candidate,
            catalog: list[Strategy], base: BaseWeights, locked: Sequence[str]) -> Result:
    """Blue's six `cand` (`draft.blue`), scored on its optimal's objective,
    as a Result on the optimal's span: its picks, their reasons and its
    breakdown - `locked`, the picks it keeps, marked."""
    seated = _seat_board(world, draft)
    result = seated.result("evaluate", catalog=catalog, base=base,
                           blue=_order(seated.board.blue),
                           locked=[name for name in locked if name in set(draft.blue)])
    result.record_candidate(cand, _board_facts(world, result, seated.side),
                            optimal.solver.considered)
    result.scale_to(optimal.span)
    return result


def _head_to_head(
        world: World, m: Map | None, draft: Draft, blue: Sequence[str], red: Sequence[str],
        base: BaseWeights, bans: Sequence[Hero]) -> HeadToHead | None:
    """Blue's six and red's likely six on one scale: the default engine alone
    against red's six - no playbook rule for either side, red's six scored
    and never searched. Red's six read against itself counts no counter, so
    each counter between the two sixes counts once, in blue's score. The gap
    is read in the rate term's unit, the win-rate point: the rate weight with
    the meta applied, over LOGIT_PER_POINT, is the engine's points per unit
    of log-odds, so no sample is drawn and the meta moves no odds. None with
    the engine off or a six short of a team."""
    if not base.on or len(blue) != TEAM_SIZE or len(red) != TEAM_SIZE:
        return None
    ours = world.resolve(None, (), tuple(blue)).blue
    theirs = world.resolve(None, (), tuple(red)).blue
    against_red = Objective(world, m, red=theirs, banned=bans, side=draft.side,
                            stage=draft.stage, catalog=[], base=base)

    def score(cand: Candidate) -> float:
        return against_red.score(against_red.prepare(cand), detail=False).score

    return HeadToHead(blue=score(Candidate(ours)), red=score(Candidate(theirs)),
                      per_logit=base.scaled().rate / LOGIT_PER_POINT)


def _check_teams(red_h: Sequence[Hero], blue_h: Sequence[Hero]) -> None:
    """Refuse a board the queue would not seat: a team past its tanks, red's
    (`red_h`) first, then blue's (`blue_h`). A team past six picks never
    gets this far: Draft refuses it."""
    check_tanks(red_h, "red")
    check_tanks(blue_h, "blue")


def _likely(
        world: World, m: Map | None, red_h: Sequence[Hero], bans_h: Sequence[Hero],
        draft: Draft, catalog: list[Strategy], base: BaseWeights) -> Result:
    """Red's likely six: its revealed picks, then for each open slot the hero
    with the highest pick score, past the bans (compute.expected_picks) - the
    six the board suggests for red. Red is never optimized and its Result
    holds no score: each pick carries how often a six fields it, its pick
    score and what it rests on. A Result like blue's, from red's side."""
    likely = compute.expected_picks(world, m, revealed=red_h, banned=bans_h)
    return Result(kind="expected", map_name=m.name if m else None, red=list(draft.blue),
                  blue=[p["hero"] for p in likely], locked=[h.name for h in red_h],
                  catalog=catalog, base=base, bans=list(draft.bans),
                  side=draft.flipped().side, stage=draft.stage, seat="red",
                  picks=[Pick(hero=p["hero"], role=p["role"], locked=p["locked"], why=p["why"],
                              evidence=[], on_six=p["on_six"], pick_score=p["score"])
                         for p in likely])
