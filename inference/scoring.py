"""The objective: what one six scores on one board.

    score(six) = base(six) + STRATEGIES(six)
    STRATEGIES = CONSTRAINTS ∪ HEURISTICS ∪ ASSUMPTIONS

The default engine's three terms come first (inference.base), unless the
board's BaseWeights are off, at meta 0; then the playbook's: limits prune and never
score, heuristics on a metric normalise and weigh, scored heuristics add
their weight times bonus less penalty; assumptions are the agent's. A
`when` reading only the enemy, the map and the world is settled once per
board, not once per candidate. A heuristic guarded on the six's own state
is a need: see Objective.score(). The legal shapes live in
inference.shapes. A board's stage moves the map's metrics (the ground in
play) and nothing else; the scale is measured on the whole map (prepare's
`measure`), so every stage of a map shares it.

The swap search (inference.swaps) adds one term, the keep term: `swap`
points for each hero of a reference six (`keep`) the six holds, added
right after the default engine's value. Maximising it is maximising the
score less `swap` for each reference hero dropped, over every legal six,
and it is a hero's own part, which the search's bound carries exactly
(inference.bounds). It is never a contribution: a six the swap search
finds is scored again on its seat's plain objective before anything reads
its score.

A six is scored in one seat order, whatever order it arrives in: tanks,
then damage, then supports, each by hero id (Candidate). The score is then a
function of the hero set, down to its last bit, which the exact search and
its proofs need. Sixes rank by rank_key: the score to SCORE_PLACES decimal
places, then the tie-break, then the names; two scores that round to the
same value tie, and the tie-break decides. The tie-break is the sum of the six's
draws: each hero's draw is a whole number hashed from the board's seed
(the map and the side) and the hero's id, so it favours no hero for its
rates or its name, every hero of a role has the same chance of winning a
tie across boards, and the same board draws the same numbers in every
process. The names settle only two sixes whose draws sum the same.
"""

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from typing import Literal, NamedTuple, NotRequired, TypedDict

from facts import compute, counters
from facts.draft import Side
from facts.model import ROLES, Hero, Map, World
from facts.team import NUMBER_TYPES, MetricBag, MetricValue, number, team_metrics
from inference.base import COUNTERS, RATES, READS, SYNERGY, Base, BaseWeights, Terms
from inference.expr import Expr, ExprError, Scope, Value, scope
from inference.shapes import is_shape_limit
from inference.strategy import Strategy, settled_by_board

NEED_BUDGET = 2.0                 # what one guarded state costs at most, or its largest need
SCORE_PLACES = 9                  # the decimal places a six's score ranks by
DRAW_BYTES = 5                    # a hero's tie-break draw: a whole number below 2**40


class Interval(NamedTuple):
    """The low and high a heuristic's raw value is read against on one board."""
    low: float
    high: float


# The records the objective passes around. A namespace is the metric bags by
# section.
type Scale = dict[str, Interval]                # heuristic id -> low, high
type Namespace = dict[str, MetricBag]


class MetricKey(NamedTuple):
    """A dotted metric key split: the namespace, and the key within it."""
    section: str
    key: str


class Norm(NamedTuple):
    """One heuristic's frozen scale for the scoring loop: the strategy, its
    reference low and spread (None where the sample never moved), its weight,
    whether it minimises, and whether it is a need."""
    strategy: Strategy
    low: float
    span: float | None
    weight: float
    minimize: bool
    need: bool


_EMPTY: MetricBag = {}


def _split_key(key: str | None) -> MetricKey:
    """A dotted metric key -> (namespace, key)."""
    section, _, name = (key or "").partition(".")
    return MetricKey(section=section, key=name)


def _not_a_number(value: MetricValue | None) -> float:
    """A metric read as a number that holds none: 0 when it is unset or empty,
    as the score has always read one. A name or a list is refused - the
    catalog keeps text metrics out of every place the solver reads a number,
    and a number itself never reaches here, so the loop pays no call for it."""
    if value:
        raise TypeError("a metric read as a number holds %r" % (value,))
    return 0.0


def _amount(value: Value, source: str) -> float:
    """A bonus or penalty expression's value, as the score adds it: a
    number; anything else is the playbook's error, named by its `source`."""
    if isinstance(value, (int, float)):               # a bool is an int
        return float(value)
    raise ExprError("%r - a bonus or penalty is a number, got %r" % (source, value))


def _slot_gate(held: list[bool | None], slot: int, s: Strategy, sc: Scope) -> bool:
    """A gate the candidate decides, read once per slot: the answer a strategy
    guarded the same way already left in `held`, else the strategy's `when`
    evaluated on this scope with its params and kept there."""
    gate = held[slot]
    if gate is None:
        sc["params"] = s.params_section
        when = s.when                  # set: a gate the candidate decides has one
        gate = held[slot] = when is None or bool(when.evaluate(sc))
    return gate


def normalised(raw: float, lo: float, span: float | None, minimize: bool, need: bool) -> float:
    """A heuristic's raw value on its reference scale, clamped to [0, 1] and
    flipped where it minimises; with no spread, the middle. Monotone in the
    raw value, so the search's bound reads it at the end of an interval."""
    if span is None:
        return 1.0 if need else 0.5    # a need nothing here can miss costs nothing
    norm = (raw - lo) / span
    if norm > 1.0:                     # the candidate sits outside the sample
        norm = 1.0
    elif norm < 0.0:
        norm = 0.0
    return 1.0 - norm if minimize else norm


class Contribution(TypedDict):
    """One term in a six's score, the default engine's or a strategy's: the
    `contributions` array of the public payload. Every term carries the
    required keys; the rest belong to the form that has them, and no term is
    padded with the others."""
    id: str
    kind: Literal["base", "constraint", "heuristic"]
    form: Literal["base", "limit", "heuristic", "scored"]
    applies: bool
    weighted: float
    metric: str | None                 # what the term reads: a metric, expressions, a source
    ok: NotRequired[bool]              # a limit: whether its require holds
    raw: NotRequired[float | None]     # a heuristic, and a base term
    weight: NotRequired[float]         # a base term
    against: NotRequired[list[str]]    # the counter term: the other side it read,
    likely: NotRequired[bool]          # whether any of it is likely heroes,
    revealed: NotRequired[int]         # how many of it are the side's picks,
    answers: NotRequired[int]          # and the graph's weight each way,
    exposures: NotRequired[int]
    derived: NotRequired[list[str]]    # each derived edge in it, worded
    norm: NotRequired[float]
    when: NotRequired[str | None]      # a heuristic, on a metric or scored
    spread: NotRequired[bool]          # an applying heuristic
    need: NotRequired[bool]
    bonus: NotRequired[float]          # a scored heuristic
    penalty: NotRequired[float]
    fact: NotRequired[str]             # the board fact that states the metric, if any
    text: NotRequired[str]


# a six's key, its hero ids sorted: a team holds distinct heroes, so the sorted
# ids name it as a set of them would, in 88 bytes where a frozenset takes 728
type SixKey = tuple[int, ...]


# a role's place in the seat order a six is scored in
ROLE_ORDER = {role: i for i, role in enumerate(ROLES)}


def seat_order(h: Hero) -> tuple[int, int]:
    """A pick's seat in the order every six is scored in: by role, then by
    hero id."""
    return ROLE_ORDER.get(h.role, len(ROLES)), h.id


class Candidate:
    """One six on its way through the search: its heroes in seat order, and
    once prepared and scored its namespace, limit breaches, raw values, base
    terms, score, tie-break and breakdown. A slim one keeps only the
    verdict. The seat order makes a six's score a function of its heroes:
    sums over the picks, pairs and the first of equals all read one order."""

    __slots__ = (
        "contributions",
        "heroes",
        "key",
        "ns",
        "raw",
        "scope",
        "score",
        "terms",
        "tiebreak",
        "violations",
    )

    def __init__(self, heroes: Iterable[Hero]) -> None:
        self.heroes = tuple(sorted(heroes, key=seat_order))
        self.key: SixKey = tuple(sorted(h.id for h in self.heroes))
        self.ns: Namespace | None = None
        self.scope: Scope | None = None
        self.score = 0.0
        self.tiebreak = 0.0
        self.contributions: list[Contribution] = []
        self.violations: list[str] = []
        # one metric value per heuristic, in catalog order, where it applies,
        # else None; empty on a slim candidate
        self.raw: Sequence[float | None] = []
        self.terms: Terms | None = None       # the default engine's, where it is on

    @property
    def names(self) -> list[str]:
        return [h.name for h in self.heroes]


def quantized(score: float) -> float:
    """A score as sixes rank by it: rounded to SCORE_PLACES decimal places.
    Rounding is monotone, so a bound on a score bounds its rounding too."""
    return round(score, SCORE_PLACES)


def rank_key(c: Candidate) -> tuple[float, float, list[str]]:
    """The order sixes rank in, best first: the quantized score, then the
    tie-break, then the names sorted - a property of the hero set on the
    board, so the order is total and a function of the compositions alone."""
    return (-quantized(c.score), -c.tiebreak, sorted(c.names))


def board_seed(m: Map | None, side: Side) -> str:
    """The seed a board's tie-break draws from: its map and its side. Red's
    picks, the bans and the locks leave it alone, so the six a tie settles
    holds still as the draft fills in."""
    return "tiebreak|%s|%s" % (m.name if m is not None else "", side)


def draw(seed: str, hero_id: int) -> float:
    """A hero's tie-break draw on a board: a whole number below 2**40 read
    from a hash of the board's seed and the hero's id - the same in every
    process, and blind to the hero's rates and name. Six of them sum exactly
    in any order, so the bound on a branch's draws is exact too."""
    digest = hashlib.blake2b(("%s|%d" % (seed, hero_id)).encode(), digest_size=DRAW_BYTES)
    return float(int.from_bytes(digest.digest(), "big"))


def _score_base(engine: Base, cand: Candidate, out: list[Contribution] | None) -> float:
    """The default engine's value; with `out`, a breakdown term per part, the
    counter term naming the side it read and the edges each way."""
    terms = cand.terms
    if terms is None:
        raise RuntimeError("score() takes a prepared candidate: its base terms are unset")
    if out is not None:
        w = engine.scaled                   # each term's weight, the meta applied
        for key, weight, raw in ((RATES, w.rate, terms.rates), (SYNERGY, w.synergy, terms.synergy),
                                 (COUNTERS, w.counter, float(terms.counters))):
            out.append({"id": key, "kind": "base", "form": "base", "applies": bool(weight),
                        "raw": raw, "weight": weight, "weighted": weight * raw,
                        "metric": READS[key]})
        out[-1].update({"against": [h.name for h in engine.opponent.heroes],
                        "likely": engine.opponent.likely,
                        "revealed": engine.opponent.revealed, "answers": terms.answers,
                        "exposures": terms.exposures,
                        "derived": [counters.said(engine.world, edge)
                                    for edge in engine.derived(cand.heroes)]})
    return engine.value(terms)


class Objective:
    """The part of a board's search that scores a six: the default engine and
    the playbook's objective against this enemy, on this map, side, stage and
    bans, with every `when` the board settles read once and the scale - each
    heuristic's low and high - once frozen, turned into the norms the scoring
    loop reads. The stage is one the map lists (facts.draft.board_stage),
    empty for the whole map."""

    def __init__(self, world: World, m: Map | None, *, red: Sequence[Hero],
                 banned: Sequence[Hero] = (), side: Side = "", stage: str = "",
                 catalog: list[Strategy], base: BaseWeights,
                 keep: frozenset[int] = frozenset(), swap: float = 0.0) -> None:
        self.world, self.m, self.red = world, m, list(red)
        # the keep term: `swap` points for each hero of `keep`, by id, a six holds
        self.keep, self.swap = keep, swap
        # the bans as given, which a sibling objective on this board is built
        # from, and their ids, which the roster and the map's ban count read
        self.banned_heroes = tuple(banned)
        self.banned = {h.id for h in banned}
        self.side, self.stage = side, stage
        self.catalog = catalog
        # the default engine's weights as given, and the engine on this board,
        # None while it is off
        self.base = base
        self.engine = Base(world, m, red=self.red, banned=banned, weights=base) if base.on else None
        # each hero's tie-break draw on this board (draw)
        seed = board_seed(m, side)
        self.draws = {h.id: draw(seed, h.id) for h in world.heroes.values()}
        self.limits = [s for s in catalog if s.form == "limit"]
        self.heuristics = [s for s in catalog if s.form == "heuristic"]
        self.scored = [s for s in catalog if s.form == "scored"]
        # the red side's metrics do not change across candidates
        self.red_t = team_metrics(world, self.red, m, ())
        self.static: Namespace = {
            "enemy": self.red_t,
            "map": compute.map_metrics(m, side, ban_count=len(self.banned), stage=stage),
            "world": compute.world_metrics(world)}
        # what the scale is measured on: the same board on the whole map, so
        # every stage of a map shares one scale (prepare's `measure`)
        self.measured: Namespace = self.static if not stage else dict(
            self.static, map=compute.map_metrics(m, side, ban_count=len(self.banned)))
        self.scale: Scale = {}               # heuristic id -> (min, max)
        self._norms: list[Norm] = []
        # each strategy's gate - True or False where `when` is settled for the
        # whole board, None where the candidate decides it; each heuristic
        # paired with its gate and with the slot it shares with every strategy
        # guarded the same way; a limit with its require:, which every limit
        # has and which always holds
        gates, slots, self.gate_slots = self._gates()
        self.gates = gates
        self._limits: list[tuple[Strategy, Expr]] = [
            (s, s.require) for s in self.limits if s.require is not None]
        self._scored = [(r, gates[r.id], slots.get(r.id, 0)) for r in self.scored]
        self._heuristics = [(g, gates[g.id], slots.get(g.id, 0), *_split_key(g.metric))
                            for g in self.heuristics]
        # needs that share a guard - its when and its params, as the gates key
        # a slot - share one budget (NEED_BUDGET; see score())
        guards = {g.id: (g.when.source, tuple(sorted(g.params.items())))
                  for g in self.heuristics if g.need and g.when is not None}
        written: dict[tuple[str, tuple[tuple[str, float], ...]], float] = {}
        largest: dict[tuple[str, tuple[tuple[str, float], ...]], float] = {}
        for g in self.heuristics:
            if g.id in guards:
                source = guards[g.id]
                written[source] = written.get(source, 0.0) + g.weight
                largest[source] = max(largest.get(source, 0.0), g.weight)
        self._needs = {sid: min(1.0, max(NEED_BUDGET, largest[source]) / written[source])
                       if written[source] else 1.0 for sid, source in guards.items()}
        self._freeze_norms()

    def _gates(self) -> tuple[dict[str, bool | None], dict[str, int], int]:
        """Every strategy's `when`, read once per board: True where there is
        none, True or False where the board settles it, None where the
        candidate decides it. -> (gate per id, slot per undecided id, how many
        slots). Strategies whose `when` and params are the same answer
        together, so they share a slot: a guard a dozen strategies write is
        evaluated once per candidate."""
        sc = scope(self.static)
        gates: dict[str, bool | None] = {}
        slots: dict[str, int] = {}
        groups: dict[tuple[str, tuple[tuple[str, float], ...]], int] = {}
        for s in self.catalog:
            if s.when is None:
                gates[s.id] = True
            elif settled_by_board(s.when.names):
                sc["params"] = s.params_section
                gates[s.id] = bool(s.when.evaluate(sc))
            else:
                gates[s.id] = None
                key = (s.when.source, tuple(sorted(s.params.items())))
                slots[s.id] = groups.setdefault(key, len(groups))
        return gates, slots, len(groups)

    # --- namespace and preparation -------------------------------------------

    def namespace(self, heroes: Sequence[Hero], static: Namespace | None = None) -> Namespace:
        """A six's metric bags: the board's (`static`, else the board's own) and
        the six's team and matchup."""
        team = team_metrics(self.world, heroes, self.m, self.red)
        ns = dict(self.static if static is None else static)
        ns["team"] = team
        ns["matchup"] = compute.matchup_metrics(self.world, team, self.red_t)
        return ns

    def prepare(self, cand: Candidate, *, measure: bool = False) -> Candidate:
        """Namespace, the limits' check, raw heuristic values. To `measure` - a
        six the scale is drawn from (inference.scale) - is to read it on the
        whole map (`measured`), a heuristic's raw value read wherever the
        board settles its `when`, on or off: the scale then holds still
        across the stages of a map, whose gates differ. Such a six is never
        scored as it stands: a heuristic the board gates off would count."""
        ns = cand.ns = self.namespace(cand.heroes, self.measured if measure else None)
        sc = cand.scope = scope(ns)
        held: list[bool | None] = [None] * self.gate_slots
        violations = []
        for s, require in self._limits:
            sc["params"] = s.params_section
            if not require.evaluate(sc):
                violations.append(s.id)
        cand.violations = violations
        raw: list[float | None] = []
        keep = raw.append
        for g, gate, slot, section, key in self._heuristics:
            if gate is None:
                gate = _slot_gate(held, slot, g, sc)
            elif measure:
                gate = True
            if gate:
                value = ns.get(section, _EMPTY).get(key)
                keep(float(value) if isinstance(value, NUMBER_TYPES) else _not_a_number(value))
            else:
                keep(None)
        cand.raw = raw
        if self.engine is not None:
            cand.terms = self.engine.terms(cand.heroes, number(ns["team"]["synergy_score"]))
        cand.tiebreak = sum(self.draws[h.id] for h in cand.heroes)
        return cand

    def lean_keys(self) -> frozenset[str] | None:
        """The team keys a six of the scale's field is read on, where they
        are all it needs (inference.scale): every heuristic on a metric reads
        a team key or one the board settles, under a gate the board settles
        or one the six decides from team keys and the board's own alone - its
        team keys read too - and every limit is a shape limit, which the
        field's shapes keep already. None where one is not - a matchup metric,
        a gate that reads matchup, a limit on a metric - and the field is
        prepared whole."""
        if not all(is_shape_limit(s) for s in self.limits):
            return None
        keys = set()
        for g, gate, _, section, key in self._heuristics:
            if section not in ("team", *self.measured):
                return None
            if section == "team":
                keys.add(key)
            if gate is None:
                read = self._guard_keys(g)
                if read is None:
                    return None
                keys |= read
        return frozenset(keys)

    def _guard_keys(self, g: Strategy) -> set[str] | None:
        """The team keys a gate the six decides reads, where every other name
        it reads is a param or a section the board settles; None where it
        reads one the lean read lacks (matchup)."""
        keys = set()
        for name in g.when.names if g.when is not None else ():
            section, _, key = name.partition(".")
            if section == "team":
                keys.add(key)
            elif section != "params" and section not in self.measured:
                return None
        return keys

    def measure_lean(self, cand: Candidate, keys: frozenset[str]) -> Candidate:
        """A six of the scale's field read on `keys` alone (lean_keys): its
        raw heuristic values as prepare(measure=True) reads them - a heuristic
        whose gate the six decides read where that gate holds on the six, the
        rest read whatever the board settles - and no limit broken: the
        field's shapes keep them."""
        bag = team_metrics(self.world, cand.heroes, self.m, self.red, only=keys)
        sc: Scope | None = None
        held: list[bool | None] = [None] * self.gate_slots
        raw: list[float | None] = []
        for g, gate, slot, section, key in self._heuristics:
            if gate is None:
                if sc is None:
                    sc = scope({**self.measured, "team": bag})
                if not _slot_gate(held, slot, g, sc):
                    raw.append(None)
                    continue
            value = (bag if section == "team" else self.measured.get(section, _EMPTY)).get(key)
            raw.append(float(value) if isinstance(value, NUMBER_TYPES) else _not_a_number(value))
        cand.raw, cand.violations = raw, []
        return cand

    def reads_the_stage(self) -> bool:
        """Whether a term of the playbook reads a map metric the board's stage
        moves from the whole map's: then a six measured on the whole map
        (prepare's `measure`) is not the six the board scores, beyond the
        heuristics its gates turn off."""
        whole, here = self.measured["map"], self.static["map"]
        moved = {"map.%s" % k for k, v in here.items() if whole.get(k) != v}
        return bool(moved and self._reads() & moved)

    def ground_key(self) -> tuple[object, ...]:
        """What makes two grounds of a map one search for the same six: each
        gate the board settles, and each map metric a term of the playbook
        reads, on this ground. Two stages with the same key score every six
        alike (inference.swaps.chain memoises on it)."""
        here = self.static["map"]
        read = sorted(n for n in self._reads() if n.startswith("map."))
        return (tuple(sorted(self.gates.items())),
                tuple((n, here.get(n.removeprefix("map."))) for n in read))

    def _reads(self) -> set[str]:
        """Every metric name a strategy reads: its metric and the names of
        its expressions."""
        read = {s.metric for s in self.catalog if s.metric}
        for s in self.catalog:
            for e in (s.require, s.when, s.bonus, s.penalty):
                if e is not None:
                    read |= set(e.names)
        return read

    @staticmethod
    def slim(cand: Candidate) -> Candidate:
        """Keep the verdict, drop the working: the namespace, the scope, the raw
        values and the breakdown. A search holds thousands of candidates at
        once and reads only their score, tie-break and picks; the winners are
        hydrated again before they are shown."""
        cand.ns = cand.scope = None
        cand.raw = ()
        cand.terms = None
        cand.contributions = []
        return cand

    def hydrate(self, cand: Candidate) -> Candidate:
        """A slim candidate prepared and scored again, with its breakdown."""
        if cand.ns is None:
            self.prepare(cand)
        return self.score(cand)

    # --- the frozen scale ------------------------------------------------------

    def set_scale(self, scale: Mapping[str, Interval]) -> None:
        """Each heuristic's low and high on this board, frozen here or
        elsewhere: inference.scale draws them, and a fill takes its seat's."""
        self.scale = dict(scale)
        self._freeze_norms()

    @property
    def norms(self) -> list[Norm]:
        """Each heuristic's frozen scale, in catalog order: what the score
        normalises by, and what the search's bound (inference.bounds) reads."""
        return self._norms

    def _freeze_norms(self) -> None:
        """One Norm per heuristic for the scoring loop. A spread of None -
        the sample never moved - normalises everything to 0.5."""
        self._norms = []
        for g in self.heuristics:
            lo, hi = self.scale.get(g.id, Interval(low=0.0, high=0.0))
            self._norms.append(Norm(
                strategy=g, low=lo, span=hi - lo if hi > lo else None,
                weight=g.weight * self._needs.get(g.id, 1.0),
                minimize=g.direction == "minimize", need=g.id in self._needs))

    # --- the score -------------------------------------------------------------

    def score(self, cand: Candidate, detail: bool = True) -> Candidate:
        """Score on the frozen scale; with detail, fill the breakdown too.

        The default engine's value comes first, where it is on; it reads no
        scale. The keep term follows it where a reference six is set, and
        is no contribution. A heuristic with no guard, or a guard on the board (enemy, map), adds
        weight x norm. A heuristic guarded on the six's own state (team.*,
        matchup.*) is a need - "a solo healer needs an escape" - and adds
        weight x (norm - 1): met in full it costs nothing, unmet it costs the
        weight, and entering the guarded state never pays. Needs written on
        one guard are scaled to sum to NEED_BUDGET at most, or to the
        largest of their weights where it is more, so a need alone on its
        guard weighs its own weight.

        With `detail`, every term is a Contribution: its optional keys belong
        to the form that has them, so a reader asks for those with .get()."""
        sc = cand.scope
        if sc is None:
            raise RuntimeError("score() takes a prepared candidate: hydrate() a slim one")
        held: list[bool | None] = [None] * self.gate_slots
        contributions: list[Contribution] = []
        out = contributions if detail else None
        total = 0.0 if self.engine is None else _score_base(self.engine, cand, out)
        if self.keep:
            total += self.swap * sum(1 for h in cand.heroes if h.id in self.keep)
        if out is not None:
            self._limit_terms(sc, out)
        total = self._score_heuristics(cand, total, out)
        total = self._score_scored(sc, held, total, out)
        cand.score = total
        cand.contributions = contributions
        return cand

    # Each form's terms take the running total and return it: subtotals summed
    # at the end would reassociate the additions and move a score in its last bit.

    def _limit_terms(self, sc: Scope, out: list[Contribution]) -> None:
        """The limits' lines in the breakdown: a limit is never weighted, so
        each costs nothing - prepare() has pruned what breaks it - and says
        whether this six keeps it."""
        for s, require in self._limits:
            sc["params"] = s.params_section
            out.append({"id": s.id, "kind": "constraint", "form": "limit",
                        "applies": True, "ok": bool(require.evaluate(sc)), "weighted": 0.0,
                        "metric": require.source})

    def _score_heuristics(self, cand: Candidate, total: float,
                          out: list[Contribution] | None) -> float:
        """The heuristics' terms: weight x norm, a need weight x (norm - 1)."""
        for raw, (g, lo, span, weight, minimize, need) in zip(cand.raw, self._norms, strict=True):
            if raw is None:
                if out is not None:
                    out.append({
                        "id": g.id, "kind": "heuristic", "form": "heuristic",
                        "applies": False, "raw": None, "norm": 0.0, "weighted": 0.0,
                        "metric": g.metric, "when": g.when.source if g.when else None})
                continue
            norm = normalised(raw, lo, span, minimize, need)
            weighted = weight * (norm - 1.0) if need else weight * norm
            total += weighted
            if out is not None:
                out.append({"id": g.id, "kind": "heuristic", "form": "heuristic",
                            "applies": True, "raw": raw, "norm": norm,
                            "weighted": weighted, "metric": g.metric,
                            "when": g.when.source if g.when else None,
                            "spread": span is not None, "need": need})
        return total

    def _score_scored(self, sc: Scope, held: list[bool | None], total: float,
                      out: list[Contribution] | None) -> float:
        """The scored heuristics' terms: weight x (bonus - penalty) while
        `when` holds."""
        for r, applies, slot in self._scored:
            if applies is None:
                applies = _slot_gate(held, slot, r, sc)
            bonus = penalty = 0.0
            if applies:
                sc["params"] = r.params_section
                if r.bonus is not None:
                    bonus = _amount(r.bonus.evaluate(sc), r.bonus.source)
                if r.penalty is not None:
                    penalty = _amount(r.penalty.evaluate(sc), r.penalty.source)
            weighted = r.weight * (bonus - penalty)
            total += weighted
            if out is not None:
                out.append({"id": r.id, "kind": "heuristic", "form": "scored",
                            "applies": applies, "bonus": bonus, "penalty": penalty,
                            "weighted": weighted, "metric": r.expressions,
                            "when": r.when.source if r.when else None})
        return total
