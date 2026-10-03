"""The board in prose: the verdict read off blue's current comp, the badge
above each picker, the game plan - the ground, what to play on
it, what red's picks mean, the family of heroes to stay in and what the
six is built for - and a blurb a stage of the plan (stage_blurb), worded
from the facts, the default engine's terms and the strategies the solver
scored. No sentence comes from anywhere else.
"""

from collections.abc import Iterable, Mapping, Sequence
from typing import Literal, NamedTuple

from facts import compute
from facts.board_facts import StageTerrainValue, TerrainValue
from facts.draft import TEAM_SIZE, Side
from facts.factset import FactSet
from facts.model import Hero, Map, World
from facts.team import team_metrics, text
from facts.team_facts import counted
from inference import base
from inference.result import (
    NOT_ALLOWED,
    Badge,
    Badges,
    Momentum,
    Odds,
    Result,
    StageRules,
    StageSwap,
    rates_queue,
)


class HeadToHead(NamedTuple):
    """Blue's six and red's likely six scored against each other on the
    default engine alone, and the board's floor on the same terms: the
    lowest such score among the board's reference sixes."""
    blue: float
    red: float
    floor: float


class Seats(NamedTuple):
    """What the verdict reads off a board: blue's current comp; its fill, the
    best six reachable from half-drafted picks, which the seat is read
    through; red's likely six, which nothing optimizes; and the two sixes
    head to head, where they were measured."""
    current: Result
    expected: Result
    fill: Result | None = None
    head: HeadToHead | None = None


def momentum(seats: Seats) -> Momentum:
    """Where blue's picks stand, read off blue's current comp on its
    optimal's scale, and the badge above each picker.

    A half-drafted seat is read through its fill - the best six reachable from
    what it has. Scoring the picks alone sums over a smaller team, so a
    perfectly played draft would read low and could fall when the right pick
    lands; that measures how many picks are in, not how good they are. Red is
    never optimized and never scored: its badge is its likely six's pull.
    Each badge is worded here, so the page shows the engine's words and
    decides nothing."""
    cur, fill = seats.current, seats.fill
    badges = Badges(blue=_badge(cur, fill), red=_likely_badge(seats.expected))
    why = cur.unscored()
    share = _now(cur, fill).share() if cur.blue and why is None else None
    partial = bool(cur.blue and cur.partial)
    odds = fight_odds(seats.head)
    verdict = _verdict_line(share, partial, fill is not None, why)
    if odds is not None:
        verdict += "; fight odds on the meta: blue %d%%, red %d%%" % (odds["blue"], odds["red"])
    return Momentum(blue=share, partial=partial, odds=odds, verdict=verdict, badges=badges)


def fight_odds(head: HeadToHead | None) -> Odds | None:
    """The fight odds: each side's score above the board's floor as its part
    of 100, a score below the floor counted as 0 - so the split holds still
    when every score is scaled or shifted alike. None where the two sixes
    were not measured, or where neither stands above the floor."""
    if head is None:
        return None
    blue, red = max(head.blue - head.floor, 0.0), max(head.red - head.floor, 0.0)
    if blue + red <= 0.0:
        return None
    share = round(100.0 * blue / (blue + red))
    return Odds(blue=share, red=100 - share, tip=ODDS_TIP)


# the strip's tooltip: what the odds compare, and what they are not
ODDS_TIP = (
    "blue's six and red's likely six head to head on the meta alone - win rates, synergy"
    " and counters against each other, no playbook rule for either side; red's six is its"
    " picks and likeliest heroes, never optimized. Each side's part of 100 is its score"
    " above the board's floor. A comparison, not a chance of winning")


def _now(current: Result, fill: Result | None) -> Result:
    """A seat as the verdict reads it: its fill while it is half-drafted and
    one was solved, else its current comp."""
    return fill if fill is not None and current.partial and current.blue else current


def _badge(current: Result, fill: Result | None) -> Badge:
    """The badge above blue's picker: "not allowed", with the limits the
    picks break, where the playbook rules the comp out; "unscored", with the
    reason, whenever the current comp cannot be a share of anything - picks
    or not; before any pick the suggested six's 100, the seat's optimal by
    definition; else the picks' share of the seat's optimal, a half-drafted
    seat read through the best six its picks reach where that fill was
    solved, as the verdict reads it. The tip says what the figure is a share
    of, and whether a fill was read."""
    why = current.unscored()
    if why is not None:
        return Badge(label=NOT_ALLOWED if current.barred else "unscored", tip=why)
    if not current.blue:
        return Badge(label="100 / 100", tip="no blue picks yet: the suggested six is this"
                                            " seat's optimal, 100")
    share = _now(current, fill).share()
    # a half-drafted seat whose fill was not solved is read off its picks: say so
    filled = current.partial and fill is not None
    reach = "the best six from your picks reaches" if filled else "your picks reach"
    return Badge(label="%d / 100" % share, tip="%s %d%% of the best six for this board"
                                                % (reach, share))


def _likely_badge(likely: Result) -> Badge:
    """The badge above red's picker: the pull of red's likely six - its
    revealed picks, and for each open slot the hero the map's pick rates and
    the wiki's synergies pull first (facts.compute.expected_picks). The pull
    ranks heroes; it is no share and no probability."""
    pull = sum(p.get("pull", 0.0) for p in likely.picks)
    held = any(p["locked"] for p in likely.picks)
    six = "their picks and the likeliest heroes for the rest" if held else "their likely six"
    tip = (
        "%s: %.1f pull - each hero's pick rate here, plus %g for each documented synergy"
        " pair on the six" % (six, pull, compute.SYNERGY_PULL))
    return Badge(label="%.0f pull" % pull, tip=tip)


def _verdict_line(share: int | None, partial: bool, filled: bool, why: str | None) -> str:
    """Blue's standing in words: a half-drafted seat says whether it was read
    through its fill or, where none was solved, off its picks alone."""
    if why is not None:                  # picks not allowed, or a board that waits
        return "blue " + why if why.startswith(NOT_ALLOWED) else why
    if share is None:
        return "no blue picks yet: the suggested six is blue's optimal, 100 / 100"
    how = (" (the best six from its picks)" if filled else " (its picks alone)") if partial else ""
    return "blue %d / 100 of its optimal%s" % (share, how)


MODE_GROUND = {
    "Control": "one point in three arenas - whoever holds the point's ground holds the round",
    "Escort": "a payload path with a choke between phases - the fight moves with the cart",
    "Hybrid":
        "a capture point and then the payload path - the first fight is at the point,"
        " the rest along the route",
    "Push": "one long lane with the robot - fights follow the barricade and regrouping"
            " costs distance",
    "Flashpoint": "five points across a wide map - long rotations between fast fights, so"
                  " arriving first and together matters",
}
STYLE_PLAY = {
    "dive": "pick a target, commit together with mobile tanks and flankers, and get out with"
            " supports who can follow",
    "brawl":
        "hold ground as a group, sustain the front line with area healing, and win the"
        " close-range trade",
    "poke": "take the long sightlines, chip from range with healers who reach, and make them"
            " walk into damage",
}
SAME_LEAN = {
    "dive": "both sides dive - peel for your backline first, then commit on theirs",
    "brawl":
        "both sides fight at close range - the side that sustains longer and trades"
        " ultimates better wins the ground",
    "poke": "both sides chip from range - take the sightlines first and win the range trade",
}
THEIR_LEAN = {
    "dive": "expect them to commit on one of your backline - stay together, peel, and punish"
            " the divers as they land",
    "brawl":
        "they want to hold ground as a group - do not walk into their front line; split"
        " them or out-range them",
    "poke": "they want to chip from range - close the distance behind cover or take the"
            " sightlines first",
}
SIDE_PLAY = {
    "attack":
        "attacking: you have to break their hold, so take the high ground before you"
        " commit and go in together",
    "defense":
        "defending: the ground is yours - set up on the high ground and make them"
        " walk into you",
}


# the map.terrain facts' features, as the plan words them
TERRAIN_GROUND = {
    "chokes": "chokes", "interiors": "interiors", "high_ground": "high ground",
    "flanks": "flank routes", "sightlines": "long sightlines", "open_ground": "open ground",
    "hazards": "environmental hazards", "cover": "cover",
}

TERRAIN_NAMED = 3   # standout features the plan names, largest first
STAGES_NAMED = 3    # stages the plan names for their terrain, largest first, in play order


def _and(items: Iterable[str]) -> str:
    items = list(items)
    return ", ".join(items[:-1]) + " and " + items[-1] if len(items) > 1 else "".join(items)


def _sentence(text: str) -> str:
    text = text.strip().rstrip(".")
    return text[:1].upper() + text[1:] + "."


FAMILY_SIZE = 5     # heroes the plan names per role


def _family(world: World, m: Map | None, style: str, role: str,
            bans: Iterable[str]) -> list[str]:
    """A style's heroes in one role, by the wiki's playstyle tags: released
    and unbanned, fewest tags first, then best win rate here."""
    out = {h.name for h in map(world.hero, bans) if h is not None}

    def rate(h: Hero) -> float:
        return (h.map_win(m.id) if m is not None else None) or h.win or 0.0
    heroes = [
        h for h in world.heroes.values()
        if h.role == role and style in h.styles and h.released and h.name not in out]
    return [h.name for h in sorted(heroes, key=lambda h: (len(h.styles), -rate(h), h.name))
            ][:FAMILY_SIZE]


def plan(
        world: World, m: Map | None, side: Side, bans: Sequence[str],
        red_h: Sequence[Hero], six: Result) -> str:
    """The game plan in prose for `six`, the six the comps tab shows for blue
    - blue's optimal before any blue pick, the fill around one to five, the
    picks themselves at six: the ground, blue's picks it keeps, what to play
    on it, what red's picks mean (their likely six until one is revealed),
    the family of heroes to stay in when you stray from the six, and what the
    six is built for - from the same facts and strategies the solver scored,
    so that picks can be tailored toward the optimal without matching it.
    Ends with what it rests on."""
    lean = six.playstyle
    yours = _yours(six)
    read = _ground(m, side, six.facts)
    for sentence in (_keeps(six, yours), _style_read(m, lean, red_h)):
        if sentence is not None:
            read.append(sentence)
    lines = [" ".join(read)]
    for line in (_them(world, m, red_h, lean, six),
                 _family_line(world, m, lean, bans), _above_all(six, lean)):
        if line is not None:
            lines.append(line)
    queue = rates_queue(six.facts) if six.facts is not None else ""
    lines.append(_basis(m, side, bans, red_h, queue, len(yours)))
    return "\n".join(lines)


def _yours(six: Result) -> list[str]:
    """Blue's own picks in the six: a fill's locks, a full six's heroes, and
    none in the optimal, which blue's picks never constrain."""
    if six.kind == "fill":
        return list(six.locked)
    return list(six.blue) if six.kind == "evaluate" else []


def _keeps(six: Result, yours: Sequence[str]) -> str | None:
    """What the six does with blue's picks: keeps them and fills the rest, or
    is them."""
    if six.kind == "evaluate":
        return "The six is the one you picked."
    if yours:
        return "The six keeps your pick%s (%s) and fills the rest." % (
            "" if len(yours) == 1 else "s", ", ".join(yours))
    return None


def _ground(m: Map | None, side: Side, facts: FactSet | None) -> list[str]:
    """The ground: the map's mode, the terrain its facts stress, and the side."""
    if m is None:
        return ["No map yet, so this is the meta's best six: what is winning right now, built"
                " to fit together."]
    ground = MODE_GROUND.get(m.mode or "", "the fight follows the objective")
    read = ["%s is a %s map: %s." % (m.name, m.mode, ground)]
    if facts is not None:
        read += _terrain(m, facts)
    if side in SIDE_PLAY:
        read.append("You are " + SIDE_PLAY[side] + ".")
    return read


def _terrain(m: Map, facts: FactSet) -> list[str]:
    """The ground the wiki's article stresses - the map.terrain facts above
    the ordinary map - and the stages whose own text stresses a feature, the
    map.stage_terrain facts."""
    read = []
    terrain: list[TerrainValue] = [f.value for f in facts.find("map.terrain", m.name)]
    stressed = [t["feature"] for t in terrain if t["z"] > 0][:TERRAIN_NAMED]
    if stressed:
        read.append("The wiki's article stresses %s."
                    % _and(TERRAIN_GROUND[f] for f in stressed))
    stages: list[StageTerrainValue] = [f.value for f in facts.find("map.stage_terrain", m.name)]
    stressing = sorted(stages, key=lambda s: -s["features"][0]["z"])[:STAGES_NAMED]
    staged = [
        (s["stage"], _and(TERRAIN_GROUND[x["feature"]] for x in s["features"]))
        for s in sorted(stressing, key=lambda s: m.stages.index(s["stage"]))]
    if staged:
        read.append("; ".join(("%s has the %s" if i == 0 else "%s the %s") % pair
                              for i, pair in enumerate(staged)) + ".")
    return read


def _style_read(m: Map | None, lean: str, red_h: Sequence[Hero]) -> str | None:
    """What to play: the style the map rewards against the six's lean."""
    map_style = m.style_top if m is not None else ""
    if map_style and lean == map_style:
        return "The map rewards %s and the six leans into it: %s." % (lean, _advice(lean))
    if map_style and lean:
        return ("The map rewards %s, but %sthe six leans %s: %s."
                % (map_style, "against this red " if red_h else "", lean, _advice(lean)))
    if lean:
        return "The six leans %s: %s." % (lean, _advice(lean))
    if map_style:
        return "The map rewards %s: %s." % (map_style, _advice(map_style))
    return None


def _advice(lean: str) -> str:
    """How to play a style: its advice, or, for a style the plan has no
    words for, its picks."""
    return STYLE_PLAY.get(lean, "play to its picks")


def _them(
        world: World, m: Map | None, red_h: Sequence[Hero], lean: str,
        blue_r: Result) -> str | None:
    """What red's picks mean: their lean against the six's, and which picks
    of the six answer which of theirs - read off the hero.vs_answers facts
    the picks cite. With nothing revealed, their likely six (_unrevealed)."""
    if not red_h:
        return _unrevealed(blue_r)
    n = len(red_h)
    theirs = team_metrics(world, red_h, m, [])
    red_lean = text(theirs["style_lean"]) or text(theirs["style_top"])
    them = "Their %s%s (%s)" % (counted(n), " so far" if n < TEAM_SIZE else "",
                                ", ".join(h.name for h in red_h))
    s = "s" if n == 1 else ""
    if red_lean in THEIR_LEAN and red_lean == lean:
        them += " lean%s %s too: %s." % (s, red_lean, SAME_LEAN[red_lean])
    elif red_lean in THEIR_LEAN:
        them += " lean%s %s: %s." % (s, red_lean, THEIR_LEAN[red_lean])
    else:
        them += " show%s no lean yet." % s
    return them + _answers([h.name for h in red_h], _answered(blue_r))


def _unrevealed(six: Result) -> str | None:
    """Their likely six while red has revealed nothing, as the default
    engine's counter term read it: a six searched with that term on counters
    it, and says so; blue's own six, or a six searched with the term off,
    only names it. None where no counter term read it."""
    read = next((c for c in six.contributions
                 if c["id"] == base.COUNTERS and c.get("likely") and c.get("against")), None)
    if read is None:
        return None
    likely = read.get("against", [])
    if six.kind != "evaluate" and read["applies"]:
        return "No red pick yet: the six counters their likely six (%s)." % ", ".join(likely)
    return "No red pick yet: their likely six is %s." % _and(likely)


def _answered(six: Result) -> dict[str, list[str]]:
    """Each enemy the six answers, and the picks of the six that answer it,
    in pick order: the hero.vs_answers facts filed under the six's own side,
    the facts its picks' reasons cite."""
    answered: dict[str, list[str]] = {}
    if six.facts is None:
        return answered
    for p in six.picks:
        for f in six.facts.find("hero.vs_answers", p["hero"]):
            if f.team == "blue":
                for enemy in f.value:
                    answered.setdefault(enemy, []).append(p["hero"])
    return answered


def _answers(names: Sequence[str], answered: Mapping[str, Sequence[str]]) -> str:
    """Who in the six answers each of red's picks, most answered first, and
    the picks nobody answers."""
    out = ""
    pairs = sorted(((k, v) for k, v in answered.items() if k in names),
                   key=lambda kv: -len(kv[1]))
    if pairs:
        out += " " + _sentence("; ".join(
            "%s answer%s %s" % (_and(v), "" if len(v) > 1 else "s", k) for k, v in pairs[:4]))
    missing = [k for k in names if k not in answered]
    if missing:
        out += " Nobody in the six answers %s - respect %s." % (
            _and(missing), "them" if len(missing) > 1 else "that pick")
    return out


def _family_line(world: World, m: Map | None, lean: str, bans: Sequence[str]) -> str | None:
    """The family to stay in: the six's style's heroes in each role."""
    if not lean:
        return None
    parts = []
    for role, plural in (("tank", "Tanks"), ("damage", "Damage"), ("support", "Supports")):
        names = _family(world, m, lean, role, bans)
        if names:
            parts.append("%s: %s." % (plural, ", ".join(names)))
    if not parts:
        return None
    return "If you stray from the six, stay in its family. " + " ".join(parts)


def _above_all(blue_r: Result, lean: str) -> str | None:
    """What the six is built for: its four heaviest scoring terms - not the
    shape every legal six pays, nor a rule named for another style ("Dive the
    pocket" on a poke six); a rule on the map's style is about the map."""
    titles = {s.id: s.name for s in blue_r.catalog} | base.TITLES
    skip = {s.id for s in blue_r.catalog
            if (s.form == "scored" and s.category == "shape")
            or (s.name.split()[0].lower() in STYLE_PLAY and s.name.split()[0].lower() != lean
                and not (s.when and "map.style_top" in s.when.names))}
    top = sorted((c for c in blue_r.contributions
                  if c["applies"] and c["weighted"] > 0.05
                  and c["id"] not in skip),
                 key=lambda c: -c["weighted"])[:4]
    if not top:
        return None
    return ("Above all: "
            + "; ".join(titles.get(c["id"], c["id"]).lower() for c in top) + ".")


def _basis(
        m: Map | None, side: Side, bans: Sequence[str], red_h: Sequence[Hero],
        queue: str, yours: int) -> str:
    """What the plan rests on, the rates named by the queue they were
    captured in, and blue's picks where the six keeps them."""
    basis = ["the %srates and counters" % ("%s " % queue if queue else "")]
    if m is not None:
        basis.append("the map")
    if side:
        basis.append("the side")
    if bans:
        basis.append(counted(len(bans), "ban"))
    if yours:
        basis.append("your " + counted(yours))
    if red_h:
        basis.append("red's " + counted(len(red_h), "revealed pick"))
    return "Based on: %s." % ", ".join(basis)


def stage_blurb(
        m: Map, stage: str, index: tuple[int, int], rules: StageRules,
        swaps: Sequence[StageSwap], gains: Sequence[str], cost: float, *,
        outcome: Literal["origin", "solved", "unsolved", "infeasible"] = "solved",
        lean: str = "") -> str:
    """A stage of the plan in four sentences at most, each dropped when it
    has nothing to say: the ground - the stage, its place on the route
    (`index`, phase and phases; (0, 0) for an arena), and what its own text
    stresses, else that it reads as the map; what changes here - the rules
    its ground turns on and off; what came of its search (`outcome`): the
    six the board suggests played as it is (origin), no six within the
    search's budget (unsolved) or the stage's limits (infeasible), else the
    swaps and what the six gains most on (`gains`, titled), or the six kept
    under the cost; and how to play it, where the six's lean turns (`lean`,
    empty where it holds)."""
    place = ", phase %d of %d" % index if index[1] > 1 else ""
    stressed = compute.stage_standouts(m, stage)[:TERRAIN_NAMED]
    if stressed:
        ground = "its own text stresses %s" % _and(TERRAIN_GROUND[s.feature] for s in stressed)
    else:
        ground = "the wiki says too little of it, so it reads as %s" % m.name
    read = ["%s%s: %s" % (stage, place, ground)]
    changes = []
    if rules["on"]:
        changes.append("%s count%s here" % (_and(rules["on"]), "" if len(rules["on"]) > 1 else "s"))
    if rules["off"]:
        changes.append("%s drop%s out" % (_and(rules["off"]), "" if len(rules["off"]) > 1 else "s"))
    if changes:
        read.append("; ".join(changes))
    if outcome == "origin":
        read.append("Play the six the board suggests here")
    elif outcome == "infeasible":
        read.append("No six keeps this stage's limits: keep the six before it")
    elif outcome == "unsolved":
        read.append("Not solved within the search's budget: keep the six before it")
    elif swaps:
        said = _and("%s for %s" % (s["out"], s["in"]) for s in swaps)
        read.append("Swap %s%s" % (said, ": the six gains most on %s" % _and(gains)
                                   if gains else ""))
    else:
        read.append("Keep the six: no swap pays for its cost (%s)" % cost_text(cost))
    if lean in STYLE_PLAY:
        read.append("The six turns %s here: %s" % (lean, STYLE_PLAY[lean]))
    return " ".join(_sentence(r) for r in read)


def cost_text(value: float) -> str:
    """A swap cost as the blurb and the swaps' verdict write it: whole where
    it is whole."""
    return "%d" % value if value == int(value) else "%g" % value
