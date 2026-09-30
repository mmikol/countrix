"""One scale per board: what every heuristic on it is normalised against, as
functions of an Objective.

    sample      the REFERENCE: a seeded set of random legal sixes for this map
                and side. Heuristics are normalised against it, so infer, the
                fill and the current comp share one scale and a score means the
                same thing across calls. The seed is a string, so every process
                draws the same list.
    freeze      each heuristic's low and high over the sample and the board's
                field, adopted by the objective, and the board's floor: the
                lowest score among the reference sixes, the zero of every share
                on it

The low and high are measured on the whole map, each heuristic read
wherever the board settles its gate, on or off (Objective.prepare's
`measure`): a stage moves which rules apply, never the scale they are read
on, so every stage of a map shares one. The floor is the board's own, its
stage's gates and limits in force.
"""

import itertools
import math
import random
from collections.abc import Iterable, Iterator, Sequence

from facts.model import ROLES, Hero
from inference.scoring import Bounds, Candidate, Interval, Objective, SixKey
from inference.shapes import legal_shapes

REFERENCE_SIZE = 1200
REFERENCE_SEED = 20260913
SCALE_POOL = 6                    # each role's heroes in the field that fixes a board's scale


def sample(objective: Objective, size: int = REFERENCE_SIZE) -> list[Candidate]:
    """A seeded sample of `size` random legal sixes for this board,
    unprepared; every legal six, in the seeded order, on a roster that holds
    fewer. Deterministic for a given map and side, and independent of the
    locked picks, the enemies and the bans, so every call on one board
    shares a scale - and any process draws the same list.

    It must not depend on red or the bans. The sample fixes every
    heuristic's [lo, hi], so drawing it differently rescales the whole
    objective: a hero banned out of neither team would move the score of
    an unchanged six, banning could raise the reported maximum over a
    smaller feasible set, and `the optimal comp for this board` would
    stop being a function of the composition. Bans still screen the
    search's candidates (inference.bounds.roster) - it is only the
    measuring stick that has to hold still."""
    m = objective.m
    rng = random.Random("%d|%s|%s" % (  # nosec B311  # a str seed, stable across processes
        REFERENCE_SEED, m.id if m else 0, objective.side))
    by_role = {r: sorted((h for h in objective.world.heroes.values()   # by id: the draw
                          if h.role == r and h.released),              # must not hang on
                         key=lambda h: h.id)                           # a query's row order
                for r in ROLES}
    # a role short of released heroes for a shape: drawing one would raise
    shapes = [(t, d, s) for t, d, s in legal_shapes(objective.catalog)
                if t <= len(by_role["tank"]) and d <= len(by_role["damage"])
                and s <= len(by_role["support"])]
    # the legal sixes there are: a draw for more than that never ends
    space = sum(
        math.comb(len(by_role["tank"]), t) * math.comb(len(by_role["damage"]), d)
        * math.comb(len(by_role["support"]), s) for t, d, s in shapes)
    out: list[Candidate] = []
    seen: set[SixKey] = set()
    if shapes:
        while len(out) < min(size, space):
            t, d, s = rng.choice(shapes)
            heroes = (rng.sample(by_role["tank"], t) + rng.sample(by_role["damage"], d)
                      + rng.sample(by_role["support"], s))
            cand = Candidate(heroes)
            if cand.key in seen:
                continue
            seen.add(cand.key)
            out.append(cand)
    return out


def _prepared(objective: Objective, measure: bool = False) -> list[Candidate]:
    """The sample prepared on the board, minus what the limits refuse: the
    sixes the floor is read off; to `measure`, prepared as the scale reads
    them (Objective.prepare)."""
    return [c for c in (objective.prepare(c, measure=measure) for c in sample(objective))
            if not c.violations]


def _on_board(objective: Objective, measured: list[Candidate]) -> list[Candidate]:
    """The measured sample as the board reads it, to score its floor: the
    same sixes with each heuristic the board gates off read as off again;
    prepared anew on a stage whose moved map metrics a term reads
    (Objective.reads_the_stage), since its limits and scope are the
    stage's."""
    if objective.reads_the_stage():
        return _prepared(objective)
    off = [i for i, g in enumerate(objective.heuristics) if objective.gates[g.id] is False]
    if off:
        for cand in measured:
            raw = list(cand.raw)
            for i in off:
                raw[i] = None
            cand.raw = raw
    return measured


def _bounds_over(objective: Objective, prepared: Sequence[Candidate]) -> Bounds:
    """{heuristic id: Interval(low, high)} over prepared sixes. A heuristic
    no six here values is left out: the objective reads a missing id as
    (0, 0)."""
    out: Bounds = {}
    for i, g in enumerate(objective.heuristics):
        values = [value for c in prepared if (value := c.raw[i]) is not None]
        if values:
            out[g.id] = Interval(low=min(values), high=max(values))
    return out


def board_prior(objective: Objective, h: Hero) -> float:
    """The board's own ranking of a hero, which picks the field that fixes
    the scale: its win rate here, three points for each enemy it answers
    less three for each that answers it, one for the map's style and one
    for a map it is best on. It reads no locked pick: the field has to be
    the same for every seat and every set of locks on this board."""
    m, world = objective.m, objective.world
    here = h.map_win(m.id) if m is not None else None
    base = here if here is not None else (h.win if h.win is not None else 50.0)
    answers = sum(1 for e in objective.red if world.is_countered_by(e.id, h.id))
    exposed = sum(1 for e in objective.red if world.is_countered_by(h.id, e.id))
    style = 1 if (m is not None and m.style_top in h.styles) else 0
    best = 1 if (m is not None and m.id in h.best_maps) else 0
    return base + 3.0 * answers - 3.0 * exposed + style + best


def _board_pool(objective: Objective, role: str) -> list[Hero]:
    """One role's top SCALE_POOL released heroes by the board's own prior."""
    # not filtered by the bans, on purpose, exactly as sample() is not:
    # this field is half the population that fixes the scale, and a ban
    # that moved it would move the score of an unchanged six. Bans keep
    # banned heroes out of the search's candidates; the measuring stick
    # has to hold still
    heroes = [h for h in objective.world.heroes.values() if h.role == role and h.released]
    heroes.sort(key=lambda h: (-board_prior(objective, h), h.name))
    return heroes[:SCALE_POOL]


def _board_field(objective: Objective) -> Iterator[list[Hero]]:
    """The field that fixes this board's scale beside the sample, with
    nothing locked: each role's top SCALE_POOL by the board's own prior,
    over every legal shape.

    It must not read the locked picks. The bounds it feeds are the board's
    one scale: `infer`, the fill and `current` run with different locks on
    the same board, and a scale that moved with them would make a current
    comp and the optimal it is a share of two different numbers."""
    tanks, damage, supports = [_board_pool(objective, role) for role in ROLES]
    for t, d, s in legal_shapes(objective.catalog):
        if t > len(tanks) or d > len(damage) or s > len(supports):
            continue
        for a in itertools.combinations(tanks, t):
            for b in itertools.combinations(damage, d):
                for c in itertools.combinations(supports, s):
                    yield list(a) + list(b) + list(c)


def _field_sample(objective: Objective) -> list[Candidate]:
    """The board's field, measured (Objective.prepare) but unscored.

    The sample alone is 1,200 random legal sixes, and the search picks from
    comps far better than random, so a good six sat above the sample's high
    on most metrics and every one of them normalised to the same 1.0: the
    rule stopped telling them apart, and a weight raised past that bought
    nothing. The field belongs in the population that sets the scale.

    A six is read on the team keys its heuristics read alone where those
    are all it needs (Objective.lean_keys), the same values at a third of
    the cost; else it is prepared whole."""
    keys = objective.lean_keys()
    out = []
    for heroes in _board_field(objective):
        cand = Candidate(heroes)
        cand = (objective.prepare(cand, measure=True) if keys is None
                else objective.measure_lean(cand, keys))
        if not cand.violations:
            out.append(cand)
    return out


def freeze(objective: Objective) -> float | None:
    """Bounds per heuristic from the reference sample and the field, adopted
    by the objective; -> the floor, the lowest score among the reference
    sixes under them, None where no legal six is drawn. The sample is drawn
    once here. The field is read only where a heuristic on a metric exists:
    the bounds read nothing else, so a playbook without one skips it and
    lands on the same scale. Both are measured on the whole map; the floor
    is read on the board's stage."""
    measured = _prepared(objective, measure=True)
    field = _field_sample(objective) if objective.heuristics else []
    objective.adopt_bounds(_bounds_over(objective, measured + field))
    return _floor(objective, _on_board(objective, measured))


def _floor(objective: Objective, prepared: Iterable[Candidate]) -> float | None:
    """The lowest score among prepared reference sixes."""
    scores = [objective.score(cand, detail=False).score for cand in prepared]
    return min(scores) if scores else None
