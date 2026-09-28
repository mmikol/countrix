"""infer(), evaluate() and board(): the API over the solver.

    infer(world, Draft(map_name="King's Row", red=("Zarya", "Pharah"), blue=("Ana",),
                       side="attack"))

returns the optimal six around the locked picks, each pick with the facts
that justify it (the facts the board would show for map + red + the
six), the score broken down into the default engine's terms and each
strategy's, and the alternatives. board() does it for both seats - blue's
absolute optimal, red around its revealed ones, on opposite sides of a
sided map - and scores the current blue picks as they stand. All three
refuse a team past the queue's tanks, on either seat, and score under the
default engine unless the caller passes base.OFF. The limits bind blue's
own picks: evaluate refuses a six that breaks one, and the board reads such
picks as not allowed. The records are result.py's, the prose plan.py's and
the process pool parallel.py's.
"""

import contextlib
import dataclasses
import sys
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures.process import BrokenProcessPool
from math import comb
from typing import NamedTuple

from db import Refusal
from facts import board_facts, compute
from facts.draft import (
    MAX_TANKS,
    TEAM_SIZE,
    Draft,
    Seat,
    board_side,
    check_tanks,
    opposite,
)
from facts.factset import FactSet
from facts.model import ROLES, Hero, Map, World
from inference import catalog as catalog_module
from inference import parallel, supersede
from inference.base import DEFAULT, OFF, BaseWeights
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
from inference.solver import Infeasible, Solved, Solver, Swept, evaluate_comp
from inference.strategy import Strategy


class SearchBounds(NamedTuple):
    """How wide a search runs: candidates per role, and alternatives kept."""
    pool_size: int
    top: int


# the legal sixes one search may enumerate. A slim candidate holds about 450 bytes
# while its field is ranked (itself, its heroes tuple, key, score, tie-break,
# contributions and violations, by sys.getsizeof), so a field this size is about
# 225 MB. A board at pool 10 (411,825 sixes) holds up to three fields at once,
# about 550 MB: blue's and red's ranked together in two workers and, with a full
# six on a seat, that seat's revived again in this process to rank the six. The
# budget is sized against the 2 GiB each solving container has - ui, whose boards
# serve.Admission holds to one budget at once, and data for the door's solver
# tools
FIELD_BUDGET = 500_000


def field_size(pool: int) -> int:
    """The legal sixes a search over `pool` candidates per role enumerates
    with nothing locked and no shape limit but the queue's tanks: the sum
    over the queue's shapes of the product of C(pool, need) per role."""
    return sum(
        comb(pool, t) * comb(pool, d) * comb(pool, TEAM_SIZE - t - d)
        for t in range(MAX_TANKS + 1) for d in range(TEAM_SIZE - t + 1))


# the most candidates per role whose field fits the budget: 10, 411,825 sixes
POOL_CEILING = max(p for p in range(2, 13) if field_size(p) <= FIELD_BUDGET)
POOL_DEFAULT = 6            # candidates per role when a caller names none
TOP_DEFAULT = 5             # alternatives when a caller names none
TOP_CEILING = 20            # the most alternatives a caller may ask for


def clamp_search(pool: str | float | None = None,
                 top: str | float | None = None) -> SearchBounds:
    """Bounds on the search: pool 2..POOL_CEILING candidates per role, top
    1..TOP_CEILING alternatives. A knob left out (None) takes POOL_DEFAULT or
    TOP_DEFAULT; any number, 0 and negatives included, is clamped into its
    range, so an MCP tool's 0 and a query string's "0" both read as the
    floor. The pool is bounded by the field it would enumerate, not by a
    round number: pool 12 is 1,345,960 legal sixes, which ran the inference
    container out of memory. Every door that takes the two from a caller -
    the MCP tools and the HTTP service - passes them through here, so the
    search is bounded by one definition. Anything else, [] included, raises
    Refusal, which every door answers as the caller's error."""
    try:
        return SearchBounds(
            pool_size=max(2, min(int(POOL_DEFAULT if pool is None else pool), POOL_CEILING)),
            top=max(1, min(int(TOP_DEFAULT if top is None else top), TOP_CEILING)))
    except (TypeError, ValueError) as error:
        raise Refusal("pool and top must be numbers: %s" % error) from error


COUNTERED_POOL = 4          # a what-if: a smaller field is enough
BOARD_TOP = 5               # the alternatives each of a board's seats keeps


class Brief(NamedTuple):
    """What a caller asks of one board beyond the draft: the candidates per
    role, the playbook tab's weights ({heuristic id: 0..10}, for this board
    only), whether to solve the countered case - the MCP board prints it, the
    page never reads it - the check that says a newer request from the
    same client has superseded this one, and the default engine's weights,
    DEFAULT unless a caller turns it OFF."""
    pool_size: int = POOL_DEFAULT
    weights: Mapping[str, float] | None = None
    countered: bool = True
    superseded: Callable[[], bool] | None = None
    base: BaseWeights = DEFAULT


def _order(heroes: Iterable[Hero]) -> list[str]:
    return [h.name for h in sorted(heroes, key=lambda h: (ROLES.index(h.role), h.name))]


def _board_facts(world: World, result: Result, side: str) -> FactSet:
    """The facts of the board a result stands on: its map, both sides as it
    names them, its bans, and the side."""
    return board_facts.generate(world, Draft(
        map_name=result.map_name, red=tuple(result.red), blue=tuple(result.blue),
        bans=tuple(result.bans), side=side))


def infer(
        world: World, draft: Draft, *, catalog: list[Strategy] | None = None,
        pool_size: int = POOL_DEFAULT, top: int = TOP_DEFAULT,
        base: BaseWeights = DEFAULT) -> Result:
    """Blue's optimal six around its locked picks (`draft.blue`) against red's
    revealed ones, on the draft's side of a sided map. No catalog is the
    playbook in force; a catalog given, [] included, is the caller's. The
    default engine scores under `base`; OFF leaves the playbook alone.
    Locked picks no six can complete within the limits are refused as not
    allowed, in the words evaluate and the board use."""
    catalog = catalog_module.load() if catalog is None else catalog
    try:
        return _optimal(world, draft, catalog=catalog, base=base, pool_size=pool_size,
                        top=top, seat="blue", kind="infer", solved=None, began=None).result
    except Infeasible as error:
        ruled = _ruled_out(world, draft, catalog) if draft.blue else None
        if ruled is None:
            raise                   # no picks, or a six past the pools the search cut
        raise Infeasible(not_allowed(ruled)) from error


def evaluate(
        world: World, draft: Draft, *, catalog: list[Strategy] | None = None,
        pool_size: int = POOL_DEFAULT, base: BaseWeights = DEFAULT) -> Result:
    """Blue's full six (`draft.blue`), scored and ranked against the field the
    solver would have searched. A six that breaks one of the playbook's
    limits is refused, the rules named: it is not allowed, so it has no
    score. No catalog is the playbook in force; the default engine scores
    under `base`."""
    return _evaluated(world, draft,
                      catalog=catalog_module.load() if catalog is None else catalog,
                      base=base, pool_size=pool_size, seat="blue", kind="evaluate",
                      swept=None, limited=True)


class _Optimal(NamedTuple):
    """A seat's optimal six and the Solver that found it: the seat's current
    comp is scored under the bounds that search froze, on its span."""
    result: Result
    solver: Solver

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
        pool_size: int, top: int, seat: Seat, kind: ResultKind, solved: Solved | None,
        began: float | None) -> _Optimal:
    """The optimal six for `seat` around its locked picks (`draft.blue`)
    against the other seat's revealed ones (`draft.red`), labelled `kind`.
    `solved` takes a Solved the caller already has - a board's search, run
    across the worker pool - in place of searching here, and `began` the
    time that search started, which the result's seconds run from; None
    times the search this call makes."""
    started = time.time() if began is None else began
    m, red_h, blue_h, bans_h = world.resolve(draft.map_name, draft.red, draft.blue, draft.bans)
    side = board_side(m, draft.side)
    _check_teams(red_h, blue_h, seat)
    result = Result(kind=kind, map_name=m.name if m else None, red=[h.name for h in red_h],
                    blue=[], locked=[h.name for h in blue_h], catalog=catalog, base=base,
                    bans=[h.name for h in bans_h], side=side, seat=seat)
    if solved is None:
        solved = Solver(world, m, red=red_h, locked=blue_h, banned=bans_h, side=side,
                        catalog=catalog, base=base,
                        pool_size=pool_size).solve(top=max(top, 1) + 1)
    if not solved.ranked:
        raise Infeasible("no composition satisfies the limits around the"
                         " locked %s picks - relax a constraint in inference/strategies/"
                         % seat)
    best = solved.ranked[0]
    result.blue = _order(best.heroes)
    fs = _board_facts(world, result, side)
    result.record_candidate(best, fs, solved.solver.considered)
    result.alternatives = [Alternative(blue=_order(c.heroes), score=round(c.score, 3),
                                       normalized=None)
                           for c in solved.ranked[1:top + 1]]
    optimal = _Optimal(result, solved.solver)
    result.scale_to(optimal.span)
    result.seconds = time.time() - started
    return optimal


def _evaluated(
        world: World, draft: Draft, *, catalog: list[Strategy], base: BaseWeights,
        pool_size: int, seat: Seat, kind: ResultKind, swept: Swept | None,
        limited: bool = False) -> Result:
    """`seat`'s full six (`draft.blue`), scored and ranked against the field
    the solver would have searched, labelled `kind`. `swept` takes that field
    from a search the caller already ran on this board. `limited`: a six that
    breaks a limit is refused, the rules named, before any search."""
    started = time.time()
    m, red_h, blue_h, bans_h = world.resolve(draft.map_name, draft.red, draft.blue, draft.bans)
    side = board_side(m, draft.side)
    _check_teams(red_h, blue_h, seat)
    if len(blue_h) != TEAM_SIZE:
        raise Refusal("evaluate needs exactly %d %s picks (got %d)"
                         % (TEAM_SIZE, seat, len(blue_h)))
    if limited:
        # the limits read no scale and no engine term, so no search is drawn to check them
        broken = _broken(Objective(world, m, red=red_h, banned=bans_h, side=side,
                                   catalog=catalog, base=OFF), blue_h)
        if broken:
            raise Refusal(not_allowed(broken))
    result = Result(kind=kind, map_name=m.name if m else None, red=[h.name for h in red_h],
                    blue=[h.name for h in blue_h], locked=[], catalog=catalog, base=base,
                    bans=[h.name for h in bans_h], side=side, seat=seat)
    evaluated = evaluate_comp(world, m, blue_h, red=red_h, banned=bans_h, side=side,
                              catalog=catalog, base=base, pool_size=pool_size, swept=swept)
    fs = _board_facts(world, result, side)
    result.record_candidate(evaluated.target, fs, evaluated.solver.considered)
    result.rank = evaluated.rank
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
        base: BaseWeights, pool_size: int, seat: Seat, kind: ResultKind,
        swept: Swept | None, barred: list[str] | None = None) -> Result:
    """`seat`'s picks (`draft.blue`, from that seat's perspective) as they
    stand against the other seat's (`draft.red`), on the span of the seat's
    `optimal`: its Solver's bounds and floor, and its score, the 100. A full
    six is evaluated against the field - `swept`, when the caller already has
    it - and reads "evaluate" where `kind` is "current", any other kind
    staying as given; a partial team is scored under the bounds the optimal's
    search froze, and says so. `barred` is the limits the picks break when
    their comp is not allowed (_barred): it is scored nowhere and ranked
    against nothing, and says why."""
    full = len(draft.blue) == TEAM_SIZE
    if full and barred is None:
        result = _evaluated(world, draft, catalog=catalog, base=base, pool_size=pool_size,
                            seat=seat, kind="evaluate" if kind == "current" else kind,
                            swept=swept)
        result.scale_to(optimal.span)
        return result
    started = time.time()
    m, red_h, blue_h, bans_h = world.resolve(draft.map_name, draft.red, draft.blue, draft.bans)
    side = board_side(m, draft.side)
    result = Result(kind="evaluate" if full and kind == "current" else kind,
                    map_name=m.name if m else None, red=[h.name for h in red_h],
                    blue=[h.name for h in blue_h], locked=[] if full else [h.name for h in blue_h],
                    catalog=catalog, base=base, bans=[h.name for h in bans_h], side=side,
                    seat=seat, partial=not full)
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
    picks the fill's search found no six for in its pools (`stuck`) that
    _ruled_out confirms on the whole roster. A half-drafted seat that breaks
    a limit it can still meet (one tank under a two-tank rule) is allowed,
    as are picks whose completion lies past the pools or past the check's
    budget: the picks to come can mend them."""
    if len(draft.blue) == TEAM_SIZE:
        blue_h = world.resolve(draft.map_name, draft.red, draft.blue, draft.bans)[2]
        return _broken(optimal.solver, blue_h) or None
    return _ruled_out(world, draft, optimal.solver.catalog) if stuck else None


def _ruled_out(world: World, draft: Draft, catalog: list[Strategy]) -> list[str] | None:
    """The limits blue's picks (`draft.blue`) break as they stand - none where
    they break none alone - when no six on the whole roster that keeps them
    meets the limits (Solver.completes); None where one does, or where the
    check's budget runs out first."""
    m, red_h, blue_h, bans_h = world.resolve(draft.map_name, draft.red, draft.blue, draft.bans)
    around = Solver(world, m, red=red_h, locked=blue_h, banned=bans_h,
                    side=board_side(m, draft.side), catalog=catalog, base=OFF)
    return _broken(around, blue_h) if around.completes() is False else None


def board(
        world: World, draft: Draft, *, catalog: list[Strategy] | None = None,
        brief: Brief | None = None) -> Board:
    """The whole board in one pass, at whatever stage the draft is - no map
    (the meta's best six), a map, a map and a side, bans, red's picks as
    they reveal:

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
                     locked, or when the search's pools hold no six that keeps
                     them and meets the limits)
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
    playbook tab's sliders; the files stay as they are and every result says
    the weights it was scored under. The brief's base is the default
    engine's weights every seat scores under, the likely six its counter
    term reads where the other seat has no picks.

    Across the pool the searches are split and walked through their rounds
    together; in this process each seat searches for itself. A worker dying
    anywhere in the pooled pass is noted on stderr, drops the pool and runs
    the same pass here. A board the brief's check reports superseded stops
    at its next round, its unstarted tasks cancelled, and raises
    supersede.Superseded. A pooled pass that raises anything else cancels
    its unstarted tasks too, so a refused board leaves none queued.
    """
    brief = Brief() if brief is None else brief
    pooled = parallel.available(catalog)
    catalog = catalog_module.weighted(
        catalog_module.load() if catalog is None else catalog, brief.weights)
    watch = supersede.Watch(brief.superseded)
    if not pooled:
        return _board_once(world, draft, catalog=catalog, brief=brief, workers=None,
                           watch=watch)
    try:
        return _board_once(world, draft, catalog=catalog, brief=brief,
                           workers=parallel.POOL.executor(), watch=watch)
    except BrokenProcessPool as error:
        sys.stderr.write("countrix: a solver worker died (%s: %s); the board solves again in"
                         " this process\n" % (type(error).__name__, error))
        parallel.POOL.drop()
    finally:
        # a whole pass read or settled every task it sent, so this cancels only
        # what an interrupted one left queued
        watch.cancel_all()
    return _board_once(world, draft, catalog=catalog, brief=brief, workers=None, watch=watch)


def _board_once(
        world: World, draft: Draft, *, catalog: list[Strategy], brief: Brief,
        workers: parallel.Workers | None, watch: supersede.Watch) -> Board:
    """The board, its searches split across `workers`, or each run in this
    process where there are none, every round asking `watch` whether the
    board is superseded. The rounds go in the order that keeps the pool
    full: the two optimal seats rank their rosters and sweep, the fills sweep
    on their seats' scales, the seats merge and are solved, and the countered
    case, which needs red's six, sweeps while the fills merge."""
    m, red_h, blue_h, bans_h = world.resolve(draft.map_name, draft.red, draft.blue, draft.bans)
    draft = dataclasses.replace(draft, side=board_side(m, draft.side))
    _check_teams(red_h, blue_h, "blue")
    expected = _expected(world, m, bans_h, draft, catalog, brief.base)
    enemy = draft.red or tuple(expected.blue)
    # each seat's draft, from that seat's perspective: its own picks are `blue`
    blue_seat = dataclasses.replace(draft, red=enemy, blue=())
    red_seat = Draft(map_name=draft.map_name, red=draft.blue, blue=(), bans=draft.bans,
                     side=opposite(draft.side))
    ours = dataclasses.replace(draft, red=enemy)       # blue's current comp and fill
    theirs = Draft(map_name=draft.map_name, red=draft.blue, blue=draft.red, bans=draft.bans,
                   side=opposite(draft.side))
    solve = _Pass(world, catalog, brief, workers, watch)
    blue_split, red_split = solve.split(blue_seat, solve.half), solve.split(red_seat, solve.rest)
    blue_split.rank_roster()
    red_split.rank_roster()
    blue_split.sweep()
    red_split.sweep()
    # a fill is its seat's board, so it takes the seat's scale and draws none
    fill_split = solve.split(ours, solve.half, wanted=_drafting(ours), scale_of=blue_split)
    red_fill_split = solve.split(theirs, solve.rest, wanted=_drafting(theirs), scale_of=red_split)
    fill_split.sweep()
    red_fill_split.sweep()
    blue_split.merge()
    red_split.merge()
    blue = solve.optimal(blue_seat, blue_split, seat="blue")
    red = solve.optimal(red_seat, red_split, seat="red")
    countered_seat = dataclasses.replace(draft, red=tuple(red.result.blue))
    # a full six that breaks a limit is not allowed, so its countered case is
    # never sent out; half-drafted picks are known only once their fill merges
    broken = len(blue_h) == TEAM_SIZE and bool(_broken(blue.solver, blue_h))
    against_split, answer_split = solve.sweep_countered(countered_seat, allowed=not broken)
    for split in (fill_split, red_fill_split, against_split, answer_split):
        split.merge()
    try:
        fill = solve.filled(ours, fill_split, seat="blue", span=blue.span)
        stuck = False
    except Infeasible:
        # no six in the fill's pools keeps blue's picks and meets the limits:
        # the fill is not solved, and blue's current comp checks the roster
        fill, stuck = None, True
    # a full six is ranked against the field its seat's search just swept;
    # 100 is the seat's optimal, whatever it holds. The limits bind blue's picks
    cur = solve.current(ours, blue, blue_split, seat="blue", stuck=stuck)
    red_cur = solve.current(theirs, red, red_split, seat="red")
    try:
        red_fill = solve.filled(theirs, red_fill_split, seat="red", span=red.span)
    except Infeasible:
        # red's revealed picks are the other side's facts, not ours to limit: past
        # a limit they already break no fill exists, and red is read off its picks
        red_fill = None
    countered = None
    if cur.barred is None:
        # a what-if: where no six answers red's six around blue's picks, it is not solved
        with contextlib.suppress(Infeasible):
            countered = solve.countered(countered_seat, against_split, answer_split)
    else:
        # picks the limits rule out have no countered case: its tails, sent
        # before the fill said so, leave no worker busy once the board returns
        against_split.settle()
        answer_split.settle()
    seats = Seats(current=cur, red_current=red_cur, blue=blue.result, red=red.result,
                  fill=fill, red_fill=red_fill, countered=countered)
    # the six the comps tab shows for blue, which the plan describes: a comp
    # that is not allowed is described by the optimal instead
    held = len(draft.blue) == TEAM_SIZE and cur.barred is None
    shown = fill if fill is not None else cur if held else blue.result
    return Board(map_name=expected.map_name, side=draft.side, bans=list(draft.bans),
                 blue=blue.result, red=red.result, current=cur, red_current=red_cur,
                 fill=fill, countered=countered, momentum=momentum(seats),
                 plan=plan(world, m, draft.side, list(draft.bans), red_h, shown),
                 shapes=[list(s) for s in legal_shapes(catalog)], expected=expected)


def _drafting(seat: Draft) -> bool:
    """Whether a seat is half-drafted - one to five picks, which a fill completes."""
    return 0 < len(seat.blue) < TEAM_SIZE


# a search sent across the pool, or one each seat runs for itself
type Searching = parallel.Split | parallel.NullSplit


class _Pass:
    """One pass of a board: the world, the weighted playbook and the brief it
    is solved under, the board's Watch, and the searches it sends out -
    blue's and its fill's over half the pool's workers, red's, its fill's
    and the countered case's over the rest - or each seat searching for
    itself where there are none."""

    def __init__(self, world: World, catalog: list[Strategy], brief: Brief,
                 workers: parallel.Workers | None, watch: supersede.Watch) -> None:
        self.world, self.catalog, self.brief = world, catalog, brief
        self.watch = watch
        size = workers.size if workers is not None else 0
        self.half = max(1, size // 2)
        self.rest = max(1, size - self.half)
        self.run = None if workers is None else parallel.Run(
            workers.executor, world, catalog, brief.weights, BOARD_TOP + 1, self.watch)
        self.countered_pool = min(brief.pool_size, COUNTERED_POOL)

    def split(
            self, draft: Draft, slices: int, *, wanted: bool = True,
            pool_size: int | None = None, scale_of: Searching | None = None) -> Searching:
        """One search sent out, unless there are no workers or it is not
        wanted. With `scale_of`, a search on the same board, it takes that
        search's bounds and standing and draws no sample of its own."""
        if self.run is None or not wanted:
            return parallel.NullSplit(self.watch)
        spec = parallel.Spec(draft, self.brief.pool_size if pool_size is None else pool_size,
                             self.brief.base)
        if scale_of is None:
            return parallel.Split(self.run, spec, slices)
        return parallel.Split(self.run, spec, slices, scale_of.bounds, scale_of.standing)

    def optimal(
            self, draft: Draft, search: Searching, *, seat: Seat, kind: ResultKind = "infer",
            pool_size: int | None = None) -> _Optimal:
        """`seat`'s optimal six on `draft`, taken from `search` where it ran
        across the pool and timed from when it was sent out."""
        return _optimal(self.world, draft, catalog=self.catalog, base=self.brief.base,
                        pool_size=self.brief.pool_size if pool_size is None else pool_size,
                        top=BOARD_TOP, seat=seat, kind=kind, solved=search.solved(),
                        began=search.started)

    def current(
            self, draft: Draft, optimal: _Optimal, search: Searching, *, seat: Seat,
            stuck: bool | None = None) -> Result:
        """`seat`'s picks as they stand, on its optimal's scale; a full six is
        ranked against the field `search` swept. With `stuck` - blue's seat,
        True where the fill's pools held no six that keeps the picks and
        meets the limits - the limits bind the picks, and a comp they rule
        out is not allowed; None leaves the picks as the other side's
        facts."""
        barred = None if stuck is None else _barred(self.world, draft, optimal, stuck)
        swept = search.swept() if len(draft.blue) == TEAM_SIZE and barred is None else None
        return _current(self.world, draft, optimal=optimal, catalog=self.catalog,
                        base=self.brief.base, pool_size=self.brief.pool_size, seat=seat,
                        kind="current", swept=swept, barred=barred)

    def filled(
            self, draft: Draft, search: Searching, *, seat: Seat, span: Span,
            kind: ResultKind = "fill", pool_size: int | None = None) -> Result | None:
        """`seat`'s picks (`draft.blue`) with the empty slots filled by the
        solver, on the seat's `span`: how close the best completion comes.
        None unless the seat is half-drafted."""
        if not _drafting(draft):
            return None
        fill = self.optimal(draft, search, seat=seat, kind=kind, pool_size=pool_size).result
        fill.scale_to(span)
        return fill

    def _wants_countered(self, draft: Draft) -> bool:
        """Whether the countered case is solved: blue has picks, red a six,
        and the brief asks for it."""
        return bool(self.brief.countered and draft.blue and draft.red)

    def sweep_countered(self, draft: Draft, *, allowed: bool = True) -> tuple[Searching, Searching]:
        """The countered case's two searches, swept: blue's best counter to
        red's optimal six (`draft.red`), which is its 100, and blue's picks
        filled against that six on the same scale - the second only while
        blue is half-drafted. Picks the limits rule out (not `allowed`) send
        neither."""
        wanted = allowed and self._wants_countered(draft)
        against = self.split(dataclasses.replace(draft, blue=()), self.rest, wanted=wanted,
                             pool_size=self.countered_pool)
        against.sweep()
        answer = self.split(draft, self.rest, wanted=wanted and _drafting(draft),
                            pool_size=self.countered_pool, scale_of=against)
        answer.sweep()
        return against, answer

    def countered(self, draft: Draft, against: Searching, answer: Searching) -> Result | None:
        """Blue's picks (`draft.blue`) against red's optimal six (`draft.red`):
        how they hold if red answers perfectly, on the scale of blue's best
        counter to that six. A full six is ranked against that counter's
        field; a half-drafted one is filled, as the fill reads blue's picks.
        None where the countered case is not solved."""
        if not self._wants_countered(draft):
            return None
        top = self.optimal(dataclasses.replace(draft, blue=()), against, seat="blue",
                           pool_size=self.countered_pool)
        if _drafting(draft):
            return self.filled(draft, answer, seat="blue", span=top.span,
                               kind="countered", pool_size=self.countered_pool)
        return _current(self.world, draft, optimal=top, catalog=self.catalog,
                        base=self.brief.base, pool_size=self.countered_pool, seat="blue",
                        kind="countered", swept=against.swept())


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
                  bans=list(draft.bans), side=draft.side, seat="red",
                  picks=[Pick(hero=p["hero"], role=p["role"], rate=p["rate"],
                              locked=p["locked"], why=p["why"], evidence=[])
                         for p in likely])
