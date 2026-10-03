"""The answers the search is held to, found without it, and the seats it is
compared on: every legal six of a board (legal_sixes), scored by a solver's
own objective and ranked (enumerated) and read as the comparisons read them
(verdicts); every legal six less the swap cost of the picks it drops
(netted); the Solver of a board's seat (seated) and blue's plain seat with
its span (plain_seat); and the synthetic World widened to seven a role
(widened). Pytest does not collect it."""

import copy
import dataclasses
import itertools

from db.data.normalizer import name_key
from inference.result import Span
from inference.scoring import Candidate, quantized, rank_key
from inference.shapes import legal_shapes
from inference.solver import Solver


def shape(six):
    """A six's (tanks, damage, supports)."""
    return tuple(sum(1 for h in six if h.role == r) for r in ("tank", "damage", "support"))


def legal_sixes(world, playbook, locked=(), banned=()):
    """Every six of the world's released heroes that holds the locked picks,
    fields no banned hero and takes a shape the playbook allows."""
    shapes = set(legal_shapes(playbook))
    taken = {h.id for h in (*locked, *banned)}
    free = [h for h in world.heroes.values() if h.released and h.id not in taken]
    sixes = ([*locked, *rest] for rest in itertools.combinations(free, 6 - len(locked)))
    return [six for six in sixes if shape(six) in shapes]


def enumerated(solver):
    """Every legal six of a solver's board that keeps the limits, scored by
    the solver's own objective and ranked: the answer the search must give,
    found without it."""
    sixes = legal_sixes(solver.world, solver.catalog, solver.locked, solver.banned_heroes)
    scored = [solver.score(solver.prepare(Candidate(six)), detail=False) for six in sixes]
    return sorted((c for c in scored if not c.violations), key=rank_key)


def verdicts(sixes):
    """Sixes as the comparison reads them: the score's float, the tie-break
    and the names."""
    return [(c.score, c.tiebreak, sorted(c.names)) for c in sixes]


def netted(plain, picks, raw):
    """Every legal six of the board scored by the plain objective less `raw`
    for each pick it drops, best first: the answer, found without the keep
    term or the search."""
    keep = {h.id for h in picks}
    out = []
    for six in legal_sixes(plain.world, plain.catalog, (), plain.banned_heroes):
        cand = plain.score(plain.prepare(Candidate(six)), detail=False)
        if not cand.violations:
            out.append((cand.score - raw * len(keep - set(cand.key)), cand))
    return sorted(out, key=lambda pair: (-quantized(pair[0]), -pair[1].tiebreak,
                                         sorted(pair[1].names)))


def seated(world, draft, playbook, base, scale_of=None, keep=(), swap=0.0):
    """The Solver of a board's seat, on `scale_of`'s scale where given; with
    `keep`, the swap search's keep term: `swap` for each of those heroes a
    six holds."""
    m, red, locked, banned = world.resolve(draft.map_name, draft.red, draft.blue, draft.bans)
    solver = Solver(world, m, red=red, locked=locked, banned=banned, side=draft.side,
                    stage=draft.stage, catalog=playbook, base=base,
                    keep=frozenset(world.hero(name).id for name in keep), swap=swap)
    if scale_of is not None:
        solver.adopt_scale(scale_of)
    return solver


def plain_seat(world, draft, playbook, base):
    """Blue's optimal's Solver on the board - blue's seat, nothing locked,
    against red's picks - its scale frozen, and its span."""
    solver = seated(world, dataclasses.replace(draft, blue=()), playbook, base)
    best = solver.solve(top=1).ranked[0]
    return solver, Span(best=best.score, floor=solver.floor)


def widened(world):
    """The world with three stronger twins of each role's best hero: seven a
    role, 38,038 legal sixes under the open queue, room for the bound to
    prune."""
    world = copy.copy(world)
    world.heroes, world.by_key = dict(world.heroes), dict(world.by_key)
    next_id = max(world.heroes) + 1
    for role in ("tank", "damage", "support"):
        best = max((h for h in world.heroes.values() if h.role == role and h.released),
                   key=lambda h: h.win)
        for i in range(3):
            twin = dataclasses.replace(best, id=next_id, name="%s %d" % (best.name, i + 2),
                                       win=best.win + 1 + i)
            world.heroes[twin.id] = twin
            world.by_key[name_key(twin.name)] = twin.id
            next_id += 1
    return world
