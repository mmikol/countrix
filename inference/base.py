"""The default engine: what a six scores before the playbook adds a term.

    base(six) = meta x (rate x rates + synergy x synergy + counter x counters)

    rates       each pick's win rate on the map, all ranks (its overall rate
                where there is no map or no row for it), in points over 50,
                times the share of that edge its pick rate earns - p / (p +
                RATE_PICK_HALF), the map's pick rate on a map - and averaged
                over the six
    synergy     team.synergy_score: the wiki's synergy scores among the six,
                cell by cell - a claim 1, a write-off 0, and a cell no
                article writes the written cells' claim share, so a pair
                neither article writes reads the written pairs' mean
                (facts.tables.impute_synergy)
    counters    the counter graph between the six and the other side
                (facts.counters): the weight of the edges by which its picks
                answer that side less the weight of those by which that side
                answers them, a wiki edge WIKI_WEIGHT (2) and, on a pair the
                wiki has no edge on either way, a derived one DERIVED_WEIGHT
                (1). The other side is its locked picks; with none, its likely
                six on this map (compute.expected_picks, past the bans),
                which only this term reads

It is always on and needs no playbook: under a playbook of assumptions the
board's sixes are the ones these three favour, and the strategies' terms
sit on top of it (inference.scoring). A heuristic moves a six by its weight
at most, since its norm is in [0, 1].

Only this term reads the kit's derived edges. The team.* counter metrics -
coverage, exposed_count, net_edges and their family - read the wiki's
graph alone: the playbook's counter rules are written and weighed against
the wiki's judgement, and a derived edge is the kit's reading, at half a
wiki edge's weight here. team.net_edges stays the wiki's edges counted once
each against red's picks; this term is the weighted graph against the side
it reads, another number under another name. The board says which edges
are derived: this term's fact lists each one with the mechanism that fired,
as do the heroes' facts (hero.vs_derived).

The rate term is centred on 50, a coin flip, and not on the reference
sample's mean: the zero is the same on every board, so a six's term needs no
sample and is a function of the six and the board alone; the pull toward 50
for a rarely picked hero shrinks to that same zero; and a comp's share of
the optimal reads as its share of the optimal's edge over a coin flip.

The weights are the playbook's, not the code's: meta.md beside the strategy
files holds them (inference.catalog.engine_weights), and the tune tool
changes them, validated and logged, as it changes a strategy. `meta` scales
the whole engine - 0 turns it off, 1 is the engine as calibrated - and
`rate`, `synergy` and `counter` weigh its three terms under it; a board's
own `meta` (the playbook tab's Meta slider, a weights query's meta:value)
stands in for the file's on that board alone. The owner's rule is that the
heuristics and the meta carry every weight and each one is his to turn, so
no term's weight is left in code, where only a commit could move it. What
a term counts inside is its definition and stays here, recorded in the
stamp: RATE_PICK_HALF, and a derived counter edge at DERIVED_WEIGHT
against a wiki edge's WIKI_WEIGHT, which keeps the tallies whole.

The calibration. rate is 1: the rate term is in win-rate points. The other
two are set so that each term's median range within one board is about
half the rate term's, measured over the reference sample
(inference.scale.sample, 1,200 legal sixes a board) on each of the 30
maps, each board's other side its likely six, the side the term reads
until one is revealed. meta.md holds the values, tuning-log.md beside it
their history, and docs/inference.md (Why the weights are the playbook's)
the measurements behind them. The rate term's own range reads Blizzard's
rates, which are licensed for personal use, so its figures stay out of
the repo. At meta 1 each term's weight is the file's exactly (1.0 x w is w
in floating point). OFF is meta 0 with every dial at 0, and a board scored
under it is the playbook's alone.
"""

import dataclasses
import math
from collections.abc import Mapping, Sequence
from typing import NamedTuple, Self, TypedDict

from facts import compute, counters
from facts.draft import Seat
from facts.factset import Fact, FactSet
from facts.model import Hero, Map, World
from facts.records import DerivedEdge

COIN_FLIP = 50.0        # the win rate the rate term is centred on
# The pick rate at which a hero's edge is trusted by half: trust = p / (p +
# RATE_PICK_HALF). A rarely picked hero's rate is read off few matches and
# swings, so its edge is pulled toward 50. A default in pick-rate points,
# chosen so that only the rarest heroes lose more than half their edge; the
# calibration read the personal-use rates and stays out of the repo.
RATE_PICK_HALF = 3.0

# the three terms' ids in a six's breakdown: a strategy's id is lowercase
# kebab, so none can take a dotted one
RATES, SYNERGY, COUNTERS = "base.rates", "base.synergy", "base.counters"
# what each term reads, as the breakdown words it, and its name in the game plan
READS = {
    RATES: "the six's win rates on the map, each trusted by its pick rate",
    SYNERGY: "team.synergy_score, the wiki's synergy scores among the six, a cell"
                " no article writes at the written cells' claim share",
    COUNTERS: "the counter graph between the six and the other side: a wiki edge 2, a derived"
                " one 1"}
TITLES = {
    RATES: "Win rates here", SYNERGY: "Synergy among the six",
    COUNTERS: "Answers to the other side"}


# the weight that scales the whole engine: meta.md's name in the playbook
# folder, its first field, and its key in a board's weights beside the
# heuristics' ids - no strategy can take it, as the file holds the name
META = "meta"
# meta.md's fields, in the order the file sets them: the meta and the three dials
DIALS = (META, "rate", "synergy", "counter")
# the swap cost: meta.md's fifth field and a board's weights key beside META,
# in share points of blue's span - what a swap of one of blue's picks must
# gain before the board suggests it (inference.swaps). It scores no six, so
# BaseWeights and the stamp leave it out and it moves no optimal six
SWAP = "swap"
SWAP_RANGE = (0.0, 50.0)            # the swap cost's range, in share points
FIELDS = (*DIALS, SWAP)             # meta.md's fields, in the order the file sets them


class BaseRecord(TypedDict):
    """The default engine's weights as a result's payload and meta.md's
    reader serve them: the meta and each term's weight under it."""
    meta: float
    rate: float
    synergy: float
    counter: float


class TermWeights(NamedTuple):
    """Each term's points per unit once the meta scales it: what a six's
    terms are multiplied by."""
    rate: float
    synergy: float
    counter: float


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class BaseWeights:
    """The default engine's weights: `meta`, which scales the whole engine,
    and each term's points per unit under it. The playbook's meta.md sets
    them (catalog.engine_weights), and nothing in code does. A board, the
    objective and every result carry one, so a board says what it was
    scored under; OFF is meta 0."""
    meta: float
    rate: float
    synergy: float
    counter: float

    @property
    def on(self) -> bool:
        """Whether any term scores: the meta and at least one dial are set."""
        return bool(self.meta and (self.rate or self.synergy or self.counter))

    def scaled(self) -> TermWeights:
        """Each term's weight times the meta."""
        return TermWeights(rate=self.meta * self.rate, synergy=self.meta * self.synergy,
                           counter=self.meta * self.counter)

    def metered(self, weights: Mapping[str, float] | None) -> Self:
        """These weights under a board's own meta where its weights set one
        (META, the playbook tab's Meta slider), for that board alone."""
        if not weights or META not in weights:
            return self
        return dataclasses.replace(self, meta=weights[META])

    def record(self) -> BaseRecord:
        """The weights as a payload holds them."""
        return BaseRecord(meta=self.meta, rate=self.rate, synergy=self.synergy,
                          counter=self.counter)


OFF = BaseWeights(meta=0.0, rate=0.0, synergy=0.0, counter=0.0)

# what the synergy term reads a cell no article writes at
# (facts.tables.impute_synergy), as a fixture's stamp names it: one recorded
# while such a pair read 0 names none, and one recorded while a pair was read
# whole names the written pairs' mean, and each reads as another objective
UNWRITTEN_SYNERGY = "the written cells' claim share a cell"


class BaseStamp(BaseRecord):
    """The default engine as a recorded fixture holds it: the weights, the
    pick rate that halves an edge, a derived counter edge's weight against
    a wiki edge's and what an unwritten synergy pair reads at, which with
    the playbook fix what a six scores."""
    pick_half: float
    derived: float
    unwritten: str


def stamp(weights: BaseWeights) -> BaseStamp | None:
    """What a fixture recorded under `weights` holds of the engine; None
    with it off, as a fixture recorded before the engine had a base reads."""
    if not weights.on:
        return None
    return BaseStamp(**weights.record(), pick_half=RATE_PICK_HALF,
                     derived=counters.DERIVED_WEIGHT / counters.WIKI_WEIGHT,
                     unwritten=UNWRITTEN_SYNERGY)


class Opponent(NamedTuple):
    """The other side the counter term reads: its heroes, and whether they are
    its likely six rather than picks it has made."""
    heroes: tuple[Hero, ...]
    likely: bool


class Edges(NamedTuple):
    """One hero's counter tally against the other side: the weight of the
    edges by which it answers that side's heroes, and of those by which they
    answer it (counters.weight)."""
    answers: int
    exposures: int


class Terms(NamedTuple):
    """A six's three base terms, unweighted: the trusted rate edge in points,
    the synergy score, and the counter graph's weight each way."""
    rates: float
    synergy: float
    answers: int
    exposures: int

    @property
    def counters(self) -> int:
        """Answer weight less exposure weight against the other side the
        term reads. team.net_edges counts the wiki's edges alone, once each,
        against red's picks alone."""
        return self.answers - self.exposures


def likely_six(world: World, m: Map | None, banned: Sequence[Hero]) -> tuple[Hero, ...]:
    """A side's likely six on this map past the bans, the one the board's red
    panel shows: compute.expected_picks with nothing revealed."""
    heroes = [world.hero(p["hero"]) for p in compute.expected_picks(world, m, banned=banned)]
    return tuple(h for h in heroes if h is not None)


def opponent(
        world: World, m: Map | None, red: Sequence[Hero], banned: Sequence[Hero]) -> Opponent:
    """The other side as the counter term reads it: its locked picks, else its
    likely six. Handed exactly that likely six, as the board hands blue's
    seat until red reveals a pick, it is the likely six still."""
    likely = likely_six(world, m, banned)
    if not red:
        return Opponent(heroes=likely, likely=True)
    same = {h.id for h in red} == {h.id for h in likely}
    return Opponent(heroes=tuple(red), likely=same)


def rate_edge(h: Hero, m: Map | None) -> float:
    """One hero's trusted win-rate edge in points: its win rate on the map
    (overall where there is no map or no row for it) over COIN_FLIP, times
    p / (p + RATE_PICK_HALF) for its pick rate p on the same footing - the
    map's where the map's row gives one. A hero with no rate has no edge."""
    row = h.map_rates.get(m.id) if m is not None else None
    win, pick = (row.win, row.pick) if row is not None else (h.win, h.pick)
    if pick is None:
        pick = h.pick
    if win is None or not pick:
        return 0.0
    return pick / (pick + RATE_PICK_HALF) * (win - COIN_FLIP)


class Base:
    """The default engine on one board: its weights, the other side the
    counter term reads, and each hero's trusted rate edge on the map and
    counter tally against that side, read once. A six's terms are then a
    sum of lookups and the synergy score its metrics already hold."""

    def __init__(self, world: World, m: Map | None, *, red: Sequence[Hero],
                 banned: Sequence[Hero], weights: BaseWeights) -> None:
        self.weights = weights
        self.scaled = weights.scaled()
        self.world = world
        self.opponent = opponent(world, m, red, banned)
        against = self.opponent.heroes
        self._edge = {h.id: rate_edge(h, m) for h in world.heroes.values()}
        self._edges = {h.id: Edges(
            answers=sum(counters.weight(world, e.id, h.id) for e in against),
            exposures=sum(counters.weight(world, h.id, e.id) for e in against))
            for h in world.heroes.values()}

    def derived(self, heroes: Sequence[Hero]) -> list[DerivedEdge]:
        """The derived edges the six's tally counts, each way, in seat order:
        what the counter fact names as derived."""
        against = self.opponent.heroes
        return [edge for h in heroes for e in against
                for edge in (self.world.derived.get((e.id, h.id)),
                             self.world.derived.get((h.id, e.id)))
                if edge is not None and counters.weight(
                    self.world, edge.loser, edge.winner) == counters.DERIVED_WEIGHT]

    def terms(self, heroes: Sequence[Hero], synergy: float) -> Terms:
        """A six's terms. The edges are summed exactly (math.fsum), so a six
        scores the same in any seat order and in any process."""
        rates = math.fsum(self._edge[h.id] for h in heroes) / len(heroes) if heroes else 0.0
        return Terms(rates=rates, synergy=synergy,
                     answers=sum(self._edges[h.id].answers for h in heroes),
                     exposures=sum(self._edges[h.id].exposures for h in heroes))

    def value(self, terms: Terms) -> float:
        """The weighted sum, each term's weight scaled by the meta, in one
        order everywhere it is taken."""
        w = self.scaled
        return w.rate * terms.rates + w.synergy * terms.synergy + w.counter * terms.counters

    def unary(self, h: Hero, size: int) -> float:
        """One pick's own part of value() in a team of `size`: its rate edge
        over the team and its counter tally, weighted. value() is the sum of
        these over the six plus the synergy term, which reads pairs; the
        search's bound (inference.bounds) adds them up apart."""
        w, edges = self.scaled, self._edges[h.id]
        return w.rate * self._edge[h.id] / size + w.counter * (edges.answers - edges.exposures)


# The facts the two terms no board fact states. A result's FactSet files the
# seat's own six as "blue", whichever seat it is, so the facts are filed there
# too; their words name the sides as the seat sees them.

def write_rates_fact(fs: FactSet, *, seat: Seat, map_name: str | None, rates: float) -> Fact:
    """The fact the rate term cites: the six's trusted edge over a coin flip."""
    where = "on %s" % map_name if map_name else "across the maps"
    fs.add(
        "team", "blue", RATES,
        "%s's six %s: %+.2f win-rate points over 50 a pick, all ranks, each pick's edge"
        " trusted by its pick rate" % (seat, where, rates),
        value=rates, unit="points", source="derived:" + RATES, team="blue")
    return fs.find(RATES)[-1]


def write_counters_fact(
        fs: FactSet, *, seat: Seat, map_name: str | None, against: Sequence[str],
        likely: bool, answers: int, exposures: int, derived: Sequence[str] = ()) -> Fact:
    """The fact the counter term cites: which of the other side's sixes it
    read - its picks, or its likely six - the graph's weight each way, and
    each derived edge in it, worded with its mechanism (counters.said)."""
    other = "blue" if seat == "red" else "red"
    if likely:
        whom = "%s's likely six %s" % (other, "on %s" % map_name if map_name else "with no map")
    else:
        whom = "%s as it stands" % other
    fs.add(
        "team", "blue", COUNTERS,
        "counters read %s: %s - %d into it, %d back (%+d), a wiki edge %d and a derived one %d%s"
        % (whom, ", ".join(against), answers, exposures, answers - exposures,
            counters.WIKI_WEIGHT, counters.DERIVED_WEIGHT,
            "".join("; %s" % said for said in derived)),
        value=answers - exposures, source="derived:" + COUNTERS, team="blue")
    return fs.find(COUNTERS)[-1]
