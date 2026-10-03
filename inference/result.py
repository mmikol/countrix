"""The Result and Board records and the facts they cite.

A Result is one seat's six on one board: who is in it and why, each pick
citing the board facts that justify it, the score and its breakdown per
strategy, and the runners-up. A Board holds the seven Results board()
solves, with the verdict, the seat badges, the plan and blue's swaps read
off them. Both render as JSON-ready data (to_dict: a ResultRecord, a
BoardRecord) and as text (rendered).
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Literal, NotRequired, TypedDict

from facts.board_facts import GroundValue
from facts.draft import TEAM_SIZE, Seat, Side
from facts.factset import Fact, FactSet
from facts.hero_facts import RateValue
from facts.model import ROLES, TERRAIN_FEATURES
from facts.records import Snapshot
from facts.team import SPECIALIST_DELTA, text
from inference import base as base_module
from inference import catalog as catalog_module
from inference.base import BaseRecord, BaseWeights
from inference.catalog import KindCounts
from inference.scoring import Candidate, Contribution
from inference.solver import RANK_CAP, Tied
from inference.strategy import Strategy

# what a result is, which its heading names
type ResultKind = Literal["infer", "evaluate", "current", "fill", "expected"]
# a stage of the plan: a phase of one route or an arena of its own
type StageKind = Literal["phase", "arena"]


class Pick(TypedDict):
    """One hero of a result's six, with the reason it is there and the ids of
    the facts the reason cites. A solved six carries each hero's subrole and
    portrait; red's likely six carries neither, and its pull instead
    (facts.compute.expected_picks)."""
    hero: str
    role: str
    locked: bool
    why: str
    evidence: list[str]
    subrole: NotRequired[str]
    portrait: NotRequired[str | None]
    pull: NotRequired[float]


class Alternative(TypedDict):
    """A runner-up six: its heroes, its score, and its share of the result's
    best - None until the result is scaled, and where it reads unscored.
    `blue` is the runner-up six, named as its Result names its own."""
    blue: list[str]
    score: float
    normalized: int | None


class Consideration(TypedDict):
    """An assumption of the playbook: prose a comp is reconciled against."""
    id: str
    name: str


# One swap the board suggests above blue's picks: the pick that goes (`out`),
# the hero that comes in (`in`), where the pick sits in blue's picks as sent
# (`at`), the incoming hero's portrait and the reason it is in the six. A
# functional TypedDict: `in` is a keyword, and the page reads the key by name
SwapPair = TypedDict("SwapPair", {
    "out": str, "in": str, "at": int, "portrait": str | None, "why": str})


class OpenSlot(TypedDict):
    """A hero the board draws in one of blue's empty slots: the fill's,
    whether or not a swap is suggested, as the rest of the board shows it."""
    hero: str
    role: str
    portrait: str | None
    why: str


# what came of blue's swap search: a swap suggested; the picks kept, no swap
# gaining its cost; or none searched, the seat unscored or the search refused
type SwapStatus = Literal["suggested", "keep", "none"]


class Swaps(TypedDict):
    """Blue's swaps, one joint answer (inference.swaps): what came of the
    search, the stage it was solved on, the cost in share points, the six
    the swaps make (the six the picks keep where none is suggested), each
    swap, the heroes the empty slots show - the fill's, as the rest of the
    board shows it - blue's share before and after, and the verdict in
    words."""
    status: SwapStatus
    stage: str
    cost: float
    six: list[str]
    pairs: list[SwapPair]
    open: list[OpenSlot]
    before: int | None
    after: int | None
    verdict: str


# One swap between two stages of the plan: the hero that goes, the one that
# comes in. Functional for the same reason as SwapPair
StageSwap = TypedDict("StageSwap", {"out": str, "in": str})


class StageRules(TypedDict):
    """The weighted rules a stage's ground turns on that the map as a whole
    does not, and those it turns off, by name."""
    on: list[str]
    off: list[str]


class StageRow(TypedDict):
    """One stage of the plan (inference.swaps.chain): its name, whether it
    is a phase of one route or an arena of its own, whether it is the
    board's chosen stage and whether that is already behind (`played`, no
    six), the six to play there, the swaps from the six before it, the
    terrain at or over the standout on its ground, the rules it turns on
    and off, the blurb, and whether its search finished within budget."""
    stage: str
    kind: StageKind
    current: bool
    played: bool
    six: list[str]
    swaps: list[StageSwap]
    ground: list[GroundValue]
    rules: StageRules
    blurb: str
    solved: bool


class Badge(TypedDict):
    """The badge above a seat's picker: its label, and what it means on hover."""
    label: str
    tip: str


class Badges(TypedDict):
    """The two seats' badges."""
    blue: Badge
    red: Badge


class Momentum(TypedDict):
    """Where blue's picks stand: blue's share of its optimal, whether blue is
    half-drafted, the verdict in words and the badge above each picker -
    blue's share, red's likely six's pull. The share is None where it cannot
    be read."""
    blue: int | None
    partial: bool
    verdict: str
    badges: Badges


class ResultRecord(TypedDict):
    """A result as to_dict() serves it, the JSON the shells read: the board
    it was solved on, the score - None where the comp is not allowed -
    whether it scores and why not, the heuristics' weights and the default
    engine's it was scored under, its share of the seat's best - None where
    it is partial or unscored - the picks, the breakdown, the breaches, the
    runners-up, its rank, the sixes tied at its score and the words for it,
    the search's size and time, the playbook's counts, the facts it cites,
    id to text, and the assumptions and drafts."""
    kind: ResultKind
    seat: Seat
    map: str | None
    red: list[str]
    blue: list[str]
    locked: list[str]
    bans: list[str]
    side: Side
    stage: str
    partial: bool
    score: float | None
    scoring: bool
    unscored: str | None
    weights: dict[str, float]
    base: BaseRecord
    normalized: int | None
    playstyle: str
    picks: list[Pick]
    contributions: list[Contribution]
    violations: list[str]
    alternatives: list[Alternative]
    rank: int | None
    outranked: bool
    tied: int
    tie: str | None
    considered: int
    seconds: float
    strategies: KindCounts
    cited: dict[str, str]
    considerations: list[Consideration]
    pending: list[str]


class BoardRecord(TypedDict):
    """A board as to_dict() serves it, the JSON the shells read: the board
    it was solved on, the plan, blue's swaps and the plan stage by stage,
    blue's results - the fill None where the board has none - the momentum,
    the shapes the roster allows, and red's likely six."""
    map: str | None
    side: Side
    stage: str
    bans: list[str]
    plan: str
    swaps: Swaps | None
    stages: list[StageRow]
    blue: ResultRecord
    current: ResultRecord
    fill: ResultRecord | None
    momentum: Momentum
    shapes: list[list[int]]
    expected: ResultRecord


@dataclass(frozen=True, slots=True)
class Span:
    """What a seat's shares are read on: its optimal six's score, the 100,
    and its floor, the 0 - the lowest score among the reference sixes the
    seat's scale drew (Solver.floor); None where none was legal, and zero
    stands in. Built by the engine and read by name, never unpacked."""
    best: float
    floor: float | None


def _pct(score: float, best: float, floor: float) -> int:
    """A score's place between the floor, 0, and the best, 100: the optimal
    six is 100, the current comp its place on blue's optimal's span, an
    alternative its place below the winner. A score is signed - the default
    engine counts each pick's edge over a coin flip - so the 0 is the seat's
    floor, not a score of zero. A best at or below the floor leaves nothing
    to divide, so only the best itself scores 100 there."""
    if best <= floor:
        return 100 if score >= best else 0
    return max(0, min(100, round(100.0 * (score - floor) / (best - floor))))


# what a comp its own picks rule out reads, before the rules it breaks
NOT_ALLOWED = "not allowed"
# a result no other six ties: the optimal alone at its score, or no optimal
UNTIED = Tied(1, False)


def not_allowed(rules: list[str]) -> str:
    """Why picks are ruled out, in the words every door uses: the limits
    they break, named, or - an empty list - that no six keeping them meets
    the limits."""
    if rules:
        return "%s: breaks %s" % (NOT_ALLOWED, ", ".join(rules))
    return "%s: no six that keeps these picks meets the playbook's limits" % NOT_ALLOWED


# what each kind of result is, as its rendered heading names it
HEADINGS: dict[ResultKind, str] = {
    "infer": "optimal comp", "evaluate": "evaluation", "current": "current comp",
    "fill": "your picks, the rest filled", "expected": "their likely starting comp"}
# the reason red's likely six carries no share: it is filled, never scored
LIKELIHOOD = (
    "unscored - filled from the map's pick rates and the wiki's synergies, which"
    " nothing scores")


@dataclass(kw_only=True, eq=False)
class Result:
    """One seat's six on one board: who is in it and why, what it scores and
    how that breaks down per strategy, the runners-up, and the facts it
    cites. Built empty around the board's names; record_candidate() writes
    the six onto it, scale_to() sets what 100 and 0 mean, and bar() rules it
    out. A Result reads from its own seat, as the Draft and the FactSet under
    it do: `blue` is the seat's six (its picks so far on a partial current
    comp), `red` the other seat's picks or likely six, and `seat` names which
    seat that is."""
    kind: ResultKind
    map_name: str | None
    red: list[str]
    blue: list[str]
    locked: list[str]
    catalog: list[Strategy]
    base: BaseWeights                  # the default engine's weights it was scored under
    bans: list[str] = field(default_factory=list)
    side: Side = ""
    stage: str = ""                    # the stage in play; empty for the whole map
    seat: Seat = "blue"
    partial: bool = False
    score: float = 0.0
    picks: list[Pick] = field(default_factory=list)
    contributions: list[Contribution] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)
    alternatives: list[Alternative] = field(default_factory=list)
    facts: FactSet | None = None
    considered: int = 0
    seconds: float = 0.0
    rank: int | None = None
    outranked: bool = False            # a full six RANK_CAP sixes outrank: no rank given
    # an optimal six: how many legal sixes share its score, itself among them
    tied: Tied = UNTIED
    playstyle: str = ""
    best: float | None = None          # the board's best score: what 100 means here
    floor: float | None = None         # the seat's floor: what 0 means here, else zero
    # why the comp is not allowed - the limits its own picks break - or None
    barred: str | None = None
    # the assumptions - nothing to score: what the agent reconciles the facts
    # against beyond the arithmetic
    considerations: list[Consideration] = field(init=False)
    # drafts: name, kind and prose only - shown, not scored, until /strategy
    pending: list[str] = field(init=False)

    def __post_init__(self) -> None:
        self.considerations = [Consideration(id=s.id, name=s.name)
                               for s in self.catalog if s.kind == "assumption"]
        self.pending = [s.id for s in self.catalog if s.pending]

    def scale_to(self, span: Span) -> None:
        """Set what 100 and 0 mean here - the seat's best score and its floor -
        and write each alternative's share of the span, None while the result
        reads unscored or the board waits (waiting(): the optimal no higher
        than the floor, which the optimal itself never reads as unscored).
        An unscored field ties, where no six ranks above another, so the rank
        goes too: every six would read first."""
        self.best, self.floor = span.best, span.floor
        scoring = self.unscored() is None and self.waiting() is None
        for alt in self.alternatives:
            alt["normalized"] = _pct(alt["score"], self.best, self._zero()) if scoring else None
        if not scoring:
            self.rank, self.outranked = None, False

    def share(self) -> int:
        """The score's place between what 0 and 100 mean here, 0-100."""
        return _pct(self.score, self._hundred(), self._zero())

    def _hundred(self) -> float:
        """What 100 means for the result: the board's best score, else its own."""
        return self.best if self.best is not None else self.score

    def _zero(self) -> float:
        """What 0 means for the result: the seat's floor, else zero."""
        return self.floor if self.floor is not None else 0.0

    def bar(self, rules: list[str]) -> None:
        """Rule the comp out: its own picks break these limits, named, or - an
        empty list - no six that keeps them meets the limits. It carries no
        score, no share and no rank, and says why; its breakdown keeps the
        limits alone, each saying whether the picks keep it."""
        self.barred = not_allowed(rules)
        self.contributions = [c for c in self.contributions if c["form"] == "limit"]
        self.alternatives, self.rank, self.considered = [], None, 0
        self.outranked, self.tied = False, UNTIED

    def unscored(self) -> str | None:
        """Why the result carries no share of a best, or None when it does.
        A comp its own picks rule out says so first (bar). The optimal six is
        100 by definition - it is the reference, and scored always; red's
        likely six is a greedy fill, never scored, and says so, the default
        engine on or off; any other comp reads unscored when nothing can be a
        share of anything: the best six scores no higher than the seat's
        floor, as every six does with the default engine off under a playbook
        that scores nothing."""
        if self.barred is not None:
            return self.barred
        if self.kind == "infer":
            return None
        if self.kind == "expected":
            return LIKELIHOOD
        return self.waiting()

    def waiting(self) -> str | None:
        """The reason nothing on this board scores, or None: the optimal six
        scores no higher than the seat's floor, so no comp is a share of it.
        Read off any result, the optimal included: unscored() gives it for
        every allowed comp but the optimal and red's likely six, and the
        swaps read it off blue's optimal, whose own unscored() is None by
        definition."""
        best, floor = self._hundred(), self._zero()
        if best > floor:
            return None
        return ("unscored on this board - the optimal six scores %.2f, not above the floor"
                " of %.2f, so no comp is a share of it" % (best, floor))

    def record_candidate(self, cand: Candidate, fs: FactSet, considered: int) -> None:
        """Write a scored candidate onto the result: its score, breakdown and
        breaches, the board's facts, how many sixes the search considered, the
        six's lean, and a pick per hero with the facts that justify it. Each
        contribution cites the board fact that states its metric."""
        if cand.ns is None:
            raise RuntimeError("record_candidate() takes a scored candidate: hydrate() a slim one")
        self.score = cand.score
        self.contributions = cand.contributions
        self.violations = cand.violations
        self.facts = fs
        self.considered = considered
        team = cand.ns["team"]
        self.playstyle = text(team["style_lean"]) or text(team["style_top"])
        locked = set(self.locked)
        for h in sorted(cand.heroes, key=lambda h: (ROLES.index(h.role), h.name)):
            why, evidence = _reasons(fs, h.name, h.name in locked)
            self.picks.append(Pick(hero=h.name, role=h.role, subrole=h.subrole,
                                   portrait=h.portrait, locked=h.name in locked, why=why,
                                   evidence=evidence))
        by_id = {s.id: s for s in self.catalog}
        for c in self.contributions:
            if c["kind"] == "base":
                fact = self._base_fact(fs, c)
            else:
                fact = _cited_fact(fs, _metric_keys(by_id.get(c["id"])))
            if fact is not None:
                c["fact"], c["text"] = fact.id, fact.text

    def _base_fact(self, fs: FactSet, c: Contribution) -> Fact | None:
        """The fact a default-engine term cites: for synergy, the board's own
        cohesion fact; for the other two, a fact of their own, written after
        the board's so no board fact's number moves."""
        if c["id"] == base_module.SYNERGY:
            return _cited_fact(fs, ["team.synergy_score"])
        if c["id"] == base_module.RATES:
            return base_module.write_rates_fact(fs, seat=self.seat, map_name=self.map_name,
                                                rates=c.get("raw") or 0.0)
        return base_module.write_counters_fact(
            fs, seat=self.seat, map_name=self.map_name, against=c.get("against", []),
            likely=c.get("likely", False), answers=c.get("answers", 0),
            exposures=c.get("exposures", 0), derived=c.get("derived", []))

    def to_dict(self) -> ResultRecord:
        """The result as JSON-ready data. The facts it cites ride along as
        `cited`, id to text; the board's whole FactSet is the facts route's."""
        cited = {}
        if self.facts is not None:
            ids = {fid for p in self.picks for fid in p["evidence"]}
            ids |= {c["fact"] for c in self.contributions if c.get("fact")}
            cited = {f.id: f.text for f in self.facts.facts if f.id in ids}
        unscored = self.unscored()
        scoring = unscored is None
        return {"kind": self.kind, "seat": self.seat, "map": self.map_name,
                "red": self.red, "blue": self.blue, "locked": self.locked,
                "bans": self.bans, "side": self.side, "stage": self.stage,
                "partial": self.partial,
                # a comp its own picks rule out carries no score at all
                "score": None if self.barred else round(self.score, 3),
                "scoring": scoring, "unscored": unscored,
                "weights": {s.id: s.weight for s in self.catalog if s.kind == "heuristic"},
                # the default engine's weights it was scored under: the meta and its dials
                "base": self.base.record(),
                # a partial team has no share to report: its score covers only the
                # picks it has. The fill result carries the number that means
                # something - the best six reachable from here
                "normalized": self.share() if scoring and not self.partial else None,
                "playstyle": self.playstyle, "picks": self.picks,
                "contributions": self.contributions, "violations": self.violations,
                "alternatives": self.alternatives, "rank": self.rank,
                "outranked": self.outranked,
                # the sixes that share an optimal's score, and the words for it
                "tied": self.tied.sixes, "tie": self.tie_label(),
                "considered": self.considered, "seconds": round(self.seconds, 2),
                "strategies": catalog_module.counts(self.catalog), "cited": cited,
                "considerations": self.considerations, "pending": self.pending}

    def rendered(self) -> str:
        """The result as text: the heading, the six and its score, and a line
        each for the picks, the breakdown and the alternatives."""
        counts = catalog_module.counts(self.catalog)
        unscored = self.unscored()
        under = (" under the meta at %g, %d constraints, %d heuristics and %d assumptions"
                 % (self.base.meta, counts["constraint"], counts["heuristic"],
                    counts["assumption"]))
        six = "%s%s" % (", ".join(self.blue), " (%s)" % self.playstyle if self.playstyle else "")
        if self.barred:
            lines = [self._headline(), "  %s - %s" % (six, NOT_ALLOWED),
                     "  NOT ALLOWED: " + self.barred.split(": ", 1)[-1]]
        else:
            lines = [self._headline(), "  %s - score %.2f %s%s, %d candidates considered in"
                     " %.1fs%s" % (six, self.score, self._share_label(unscored),
                                   self._rank_label(), self.considered, self.seconds, under)]
        if unscored and not self.barred:
            lines.append("  UNSCORED: " + unscored.split(" - ", 1)[-1])
        tie = self.tie_label()
        if tie:
            lines.append("  TIED: " + tie)
        if self.partial:
            lines.append("  PARTIAL: %d of %d picked - sums read low until the team is full"
                         % (len(self.blue), TEAM_SIZE))
        if self.violations:
            lines.append("  VIOLATES: " + ", ".join(self.violations))
        lines += ["  %-8s %-14s %s" % (p["role"], p["hero"] + ("*" if p["locked"] else ""),
                                       p["why"])
                  for p in self.picks]
        lines.append(self._breakdown())
        lines += ["  alt %d: %s (%.2f)" % (i, ", ".join(alt["blue"]), alt["score"])
                  for i, alt in enumerate(self.alternatives, start=1)]
        if self.considerations:
            lines.append("  ground rules to reconcile against: " + ", ".join(
                c["id"] for c in self.considerations))
        if self.pending:
            lines.append("  drafts not yet scored (run /strategy): " + ", ".join(self.pending))
        return "\n".join(lines)

    def _headline(self) -> str:
        """What the result is, for which seat, where and against whom."""
        return "%s for %s%s%s%s vs %s%s%s" % (
            HEADINGS[self.kind],
            "red" if self.seat == "red" else "blue",
            " on %s" % self.side if self.side else "",
            " on %s" % self.map_name if self.map_name else "",
            " - %s" % self.stage if self.stage else "",
            ", ".join(self.red) or "an unknown enemy",
            " (locked: %s)" % ", ".join(self.locked) if self.locked else "",
            " (banned: %s)" % ", ".join(self.bans) if self.bans else "")

    def tie_label(self) -> str | None:
        """How many sixes share the optimal's score, where more than one
        does: the tie-break's draw chose among them, and none is better."""
        count, at_least = self.tied
        if count < 2:
            return None
        return ("one of %s%d sixes tied at the best score - the board's draw picked it, and"
                " none of them is better" % ("at least " if at_least else "", count))

    def _rank_label(self) -> str:
        """Where a full six ranks among the legal sixes, if it is ranked."""
        if self.rank:
            return " (rank %d among the legal sixes)" % self.rank
        if self.outranked:
            return " (outside the top %d of the legal sixes)" % RANK_CAP
        return ""

    def _share_label(self, unscored: str | None) -> str:
        """The score's share of the best, or why there is none."""
        if self.kind == "expected":                # a greedy fill, not a score
            return "(from the map's pick rates and the synergies, no strategy read)"
        if unscored is not None:
            return "(unscored)"
        if self.partial:
            return "(partial - see the filled six for a share)"
        return "(%d/100)" % self.share()

    def _breakdown(self) -> str:
        """Each applying term's weighted part of the score, a need marked."""
        parts = ["%s %+.2f%s" % (c["id"], c["weighted"], " (need)" if c.get("need") else "")
                 for c in self.contributions
                 if c["applies"] and abs(c["weighted"]) >= 0.005]
        return "  breakdown: " + " · ".join(parts)


@dataclass(kw_only=True, eq=False)
class Board:
    """One draft: blue's Results board() solves, red's likely six, the verdict
    and prose read off them, and the shape limits the roster enforces.
    Carries the same to_dict()/rendered() pair as Result, so the shells hand a
    board to the caller the way they hand a single seat."""
    map_name: str | None
    side: Side
    stage: str
    bans: list[str]
    blue: Result
    current: Result
    fill: Result | None
    momentum: Momentum
    plan: str
    shapes: list[list[int]]
    expected: Result
    swaps: Swaps | None = None          # blue's swaps, None without blue picks
    stages: list[StageRow] = field(default_factory=list)    # the plan stage by stage

    def to_dict(self) -> BoardRecord:
        """The board as JSON-ready data."""
        return {"map": self.map_name, "side": self.side, "stage": self.stage, "bans": self.bans,
                "plan": self.plan, "swaps": self.swaps, "stages": self.stages,
                "blue": self.blue.to_dict(), "current": self.current.to_dict(),
                "fill": self.fill.to_dict() if self.fill else None, "momentum": self.momentum,
                "shapes": self.shapes,
                "expected": self.expected.to_dict()}

    def rendered(self) -> str:
        """The board as text: the plan, blue's results, red's likely six and the
        verdict."""
        parts = ["game plan:\n" + self.plan]
        parts += [r.rendered() for r in (self.blue, self.current) if r.blue or r.kind != "current"]
        if self.fill:
            parts.append(self.fill.rendered())
        parts.append(self.expected.rendered())
        parts.append("momentum: " + self.momentum["verdict"])
        if self.swaps is not None:
            parts.append("swaps: " + self.swaps["verdict"])
        if self.stages:
            parts.append("stages:\n" + "\n".join(_stage_line(row) for row in self.stages))
        return "\n\n".join(parts)


def _stage_line(row: StageRow) -> str:
    """A stage of the plan as one line: its name, marked where it is the
    board's, the six, and the blurb."""
    mark = " (here)" if row["current"] else ""
    if row["played"]:
        return "  %s%s: played" % (row["stage"], mark)
    six = ", ".join(row["six"]) if row["six"] else "not solved"
    return "  %s%s: %s - %s" % (row["stage"], mark, six, row["blurb"])


def rates_queue(fs: FactSet) -> str:
    """The queue the board's rates were captured in, as the game names it
    ("Role Queue"), read off the rates' meta.snapshot fact; empty where the
    board holds none. The source publishes no Open Queue rates, so a pick's
    win rate says which queue it is."""
    for f in fs.find("meta.snapshot"):
        snapshot: Snapshot = f.value
        queue = snapshot["queue"]
        if queue:
            return queue.removeprefix("competitive_").replace("_", " ").title()
    return ""


def _reasons(fs: FactSet, hero_name: str, locked: bool) -> tuple[str, list[str]]:
    """The facts that justify one pick, from the board's own FactSet - the
    facts about OUR copy of the hero: a mirror pick has facts on both sides
    (red's Tracer answers our Ana; ours partners our D.Va), and only the
    facts the FactSet filed under the seat's own side (its "blue") count. A
    win rate names the queue it was captured in."""
    why: list[str] = []
    evidence: list[str] = []
    queue = rates_queue(fs)
    rated = ", %s" % queue if queue else ""

    def own(key: str) -> list[Fact]:
        return [f for f in fs.find(key, hero_name) if f.team in (None, "blue")]

    def cite(key: str, template: Callable[[Fact], str]) -> None:
        found = own(key)
        if found:
            why.append(template(found[0]))
            evidence.append(found[0].id)

    cite("hero.vs_answers", lambda f: "answers %s" % ", ".join(f.value))
    partners = own("hero.with_ally")
    if partners:
        why.append("partner of %s" % ", ".join(f.value for f in partners[:3]))
        evidence.extend(f.id for f in partners[:3])
    cite("hero.map_win", lambda f: "wins %.1f%% here%s" % (f.value, rated))
    for f in own("hero.map_delta"):
        if f.value >= SPECIALIST_DELTA:
            why.append("map specialist (%+.1f)" % f.value)
            evidence.append(f.id)
    cite("hero.map_style_fit", lambda f: "fits the %s style" % f.value)
    cite("hero.home_map", lambda f: "top-%d map by rate" % f.value)
    cite("hero.vs_answered_by", lambda f: "CAUTION: answered by %s" % ", ".join(f.value))
    def overall(f: Fact) -> str:
        rate: RateValue = f.value
        return "wins %.1f%% across all ranks%s" % (rate["win"], rated)

    if not evidence:
        cite("hero.rate", overall)
    if locked:
        why.insert(0, "locked")
    return "; ".join(why), evidence


# the map's terrain metrics, which the ground in play's fact states (map.ground)
GROUND_KEYS = frozenset("map.%s" % f for f in TERRAIN_FEATURES)


def _metric_keys(strategy: Strategy | None) -> list[str]:
    """The metrics a contribution's fact can state: a heuristic's own, then
    every team, enemy and matchup key its expressions read, and the terrain
    of the ground in play."""
    if strategy is None:
        return []
    keys = [strategy.metric] if strategy.kind == "heuristic" and strategy.metric else []
    for e in (strategy.require, strategy.bonus, strategy.penalty, strategy.when):
        if e is not None:
            keys += [n for n in e.names
                     if n.startswith(("team.", "enemy.", "matchup.")) or n in GROUND_KEYS]
    return keys


def _cited_fact(fs: FactSet, keys: Iterable[str]) -> Fact | None:
    """The first board fact that states one of these metrics. A fact is indexed
    under the key it is worded around and under every other metric its sentence
    carries (FactSet.add's `also`), so the lookup is the metric itself. A team
    metric is stated about blue; a matchup metric about the two sides, and one
    team metric is only ever stated in a matchup sentence. Red's numbers that
    threaten blue ride their matchup sentence under their enemy.* keys. A map
    metric is stated about the map."""
    for key in keys:
        subjects = ((fs.draft.map_name or "",) if key.startswith("map.")
                    else ("blue", "blue vs red"))
        for subject in subjects:
            found = fs.find(key, subject)
            if found:
                return found[0]
    return None
