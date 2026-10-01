"""Reach: is a hero the right pick somewhere?

The intent is that the playbook makes a hero rare but never impossible. This is the
check, not the guarantee: for a hero it looks for a board that suits it - one of its
maps, a red it answers, a side - on which it is in the optimal six, banning the rivals
that hold its seat where it must, up to the five bans a match has. A rival is any hero
of the optimal six the best six holding the hero leaves out, of any role: in Open Queue
a seat is no role's, and a damage hero may take a tank's.

The two answers it gives are not symmetric. A board found is a proof: the hero seats
there, and re-solving that board shows it. A board not found is not a proof of the
opposite - the search tries every map but a few reds, and a board it never visits could
seat the hero. A hero it finds nothing for is one worth looking at: a wrong number, a
tool no metric reads, a rule that charges it for what it is not, or a board this search
does not reach. Under the shipped playbook, the default engine and the healing floor,
forty-nine of the fifty-three released heroes have a board and four do not
(tests/verification/inference/test_reach.py names them). Each board's optimal six is exact
(inference.solver), so a board found is a proof of the hero's seat there. The
`reach` tool runs the search; `.venv/bin/python -m tests.verification.inference.record_reach`
records a board per released hero in tests/fixtures/reach.json beside the objective
it ran under, and the suite checks none is lost.

    maps    every map, the ones its map rates lift it most on first: a board solves in
            about a tenth of a second, so none is left out
    reds    none (blue counters the likely six); the heroes it answers, two a role, on
            the counter graph the default engine scores (counters.weight: a wiki edge,
            then a derived one); the same without the heroes that answer it back
"""

from typing import NamedTuple, TypedDict

from facts import counters
from facts.draft import MAX_BANS, SIDES, Draft, is_sided
from facts.model import ROLES, Hero, Map, World
from inference import engine
from inference.solver import Infeasible, Unbounded

CLOSEST = 5         # boards the ban search starts from


class Reach(TypedDict):
    """A board a search found for a hero - the reach tool's answer and a row of
    tests/fixtures/reach.json. seated says whether the hero is in the board's
    optimal six; banned names the rivals banned, and the count is
    len(banned). On a board that does not seat the hero the rest describes
    the closest it came, gap the score it fell short by."""
    hero: str
    seated: bool
    map: str
    side: str
    red: list[str]
    banned: list[str]
    six: list[str]
    gap: float


class _Near(NamedTuple):
    """A board that did not seat the hero: its optimal six's lead over the
    best six that holds the hero, and the board."""
    gap: float
    map_name: str
    red: list[str]
    side: str


def maps(world: World, hero: Hero) -> list[Map]:
    """Every map, the ones its map rates lift it most on first."""
    base = hero.win or 50.0

    def lift(m: Map) -> float:
        return (hero.map_win(m.id) or base) - base

    return sorted(world.maps.values(), key=lambda m: (-lift(m), m.name))


def reds(world: World, hero: Hero) -> list[list[str]]:
    """The reds to try: none, then two a role of the heroes the hero answers
    on the graph the engine scores - a wiki edge before a derived one, one
    that answers it back last, then the most picked - then the same without
    those that answer it back."""
    others = [h for h in world.heroes.values() if h.released and h.id != hero.id]
    out: list[list[str]] = [[]]
    for strict in (False, True):
        red: list[str] = []
        for role in ROLES:
            pool = [h for h in others if h.role == role
                    and not (strict and counters.weight(world, hero.id, h.id))]
            pool.sort(key=lambda h: (-counters.weight(world, h.id, hero.id),
                                     counters.weight(world, hero.id, h.id),
                                     -(h.pick or 0), h.name))
            red += [h.name for h in pool[:2]]
        if red not in out:
            out.append(red)
    return out


def _rank(world: World, hero: Hero, name: str) -> bool:
    """A rival's place in the ban order: one of the hero's own role first."""
    found = world.hero(name)
    return found is None or found.role != hero.role


def search(world: World, name: str) -> Reach:
    """The first board that seats the hero, bans 0..MAX_BANS; with none, the
    closest it came, unseated. A board whose limits allow no six, or no six
    holding the hero, is a miss, as is one whose search refuses past its
    budget (solver.Unbounded), and the search goes on. It raises:

        Refusal       an unknown or announced hero, as World.resolve refuses
                      one on every board tool
        RuntimeError  a database without maps, which leaves no board to
                      search - the server's fault
        Infeasible    a Refusal: no board the search tries allows a six
                      within the playbook's limits
    """
    (hero,) = world.resolve(None, (), [name]).blue
    boards = maps(world, hero)
    if not boards:
        raise RuntimeError("reach: no board to search for %s: the database holds no maps"
                           % hero.name)
    near: list[_Near] = []
    fenced = past_budget = 0          # the misses, named in the refusal when nothing seats
    for m in boards:
        for red in reds(world, hero):
            for side in (SIDES if is_sided(m) else ("",)):
                try:
                    top = engine.infer(world, Draft(map_name=m.name, red=tuple(red), side=side),
                                       top=1)
                    if hero.name in top.blue:
                        return {"hero": hero.name, "seated": True, "map": m.name, "side": side,
                                "red": red, "banned": [], "six": top.blue, "gap": 0.0}
                    held = engine.infer(world, Draft(map_name=m.name, red=tuple(red),
                                                     blue=(hero.name,), side=side), top=1)
                except Infeasible:
                    fenced += 1
                    continue
                except Unbounded:
                    past_budget += 1
                    continue
                near.append(_Near(top.score - held.score, m.name, red, side))
    if not near:
        raise Infeasible("reach: no board the search tries seats %s within the playbook's"
                         " limits (%d allow no six with it, %d refuse past the search's budget)"
                         " - relax a constraint in inference/strategies/"
                         % (hero.name, fenced, past_budget))
    near.sort(key=lambda n: (n.gap, n.map_name, n.side))
    for board in near[:CLOSEST]:
        found = _banning(world, hero, board.map_name, board.red, board.side)
        if found is not None:
            return found
    closest = near[0]
    return {"hero": hero.name, "seated": False, "map": closest.map_name, "side": closest.side,
            "red": closest.red, "banned": [], "six": [], "gap": round(closest.gap, 3)}


def _banning(world: World, hero: Hero, map_name: str, red: list[str], side: str) -> Reach | None:
    """One board's ban search: each round bans the first rival that holds the
    hero's seat - a hero of the optimal six the best six holding the hero
    leaves out, of any role, its own role's first - up to MAX_BANS -> the
    board once the hero seats, or None when it never does, no rival is left
    to ban or a ban leaves no six within the playbook's limits."""
    banned: list[str] = []
    # one solve of this board per ban, not two: the board a ban produces is
    # the board the next round starts from, so the round reads it
    for _ in range(MAX_BANS + 1):
        try:
            top = engine.infer(world, Draft(map_name=map_name, red=tuple(red),
                                            bans=tuple(banned), side=side), top=1)
            if banned and hero.name in top.blue:
                return {"hero": hero.name, "seated": True, "map": map_name, "side": side,
                        "red": red, "banned": banned, "six": top.blue, "gap": 0.0}
            if len(banned) == MAX_BANS:
                break
            held = engine.infer(world, Draft(map_name=map_name, red=tuple(red),
                                             blue=(hero.name,), bans=tuple(banned), side=side),
                                top=1)
        except (Infeasible, Unbounded):
            return None
        rivals = sorted((h for h in top.blue if h not in held.blue and h not in red),
                        key=lambda h: _rank(world, hero, h))
        if not rivals:
            break
        banned = [*banned, rivals[0]]
    return None


def six(world: World, board: Reach) -> list[str]:
    """The optimal six of a board a search recorded, solved afresh; none on a
    board the playbook's limits no longer fit."""
    try:
        top = engine.infer(world, Draft(map_name=board["map"], red=tuple(board["red"]),
                                        bans=tuple(board["banned"]), side=board["side"]), top=1)
    except (Infeasible, Unbounded):
        return []
    return top.blue


def seated(world: World, board: Reach) -> bool:
    """Is the hero still in the optimal six of the board a search recorded for
    it? A board the playbook's limits no longer fit has fallen: it seats no one."""
    return board["hero"] in six(world, board)
