"""Each team.* and matchup.* metric's range over a branch's completions,
which the bound (inference.bounds) reads as the search walks.

    Space                 one search's heroes - the locked picks, then each
                          role's candidates in walk order - by dense index, and
                          the suffix tables the rules read
    RULES                 each team.* and matchup.* key's range over a branch's
                          completions, by the aggregate it is: a sum over the
                          picks, a mean or median of the known values, a max or
                          a min, a product, a sum over pairs, the enemies
                          answered, the distinct subroles, the claimed synergy
                          graph's isolated picks and largest group, or fixed by
                          the shape
    rule_order, evaluate  the rules a search reads, each after the rules it
                          reads, and their values over one branch
    pair_halves           half each hero's best and worst few pairs with the
                          rest of the roster, which the pairwise rules and
                          the bound's synergy term read

A metric a rule sums in another order than the metric itself carries a
slack, SLACK times the magnitude of its addends, outward on both ends; one
whose values are whole numbers is exact and carries none, so a threshold on
a count reads exactly. tests/verification/inference/test_bounds.py holds
every rule to every completion of random branches.
"""

import math
from collections.abc import Callable, Sequence
from typing import NamedTuple

from facts import compute
from facts.draft import EXPECTED_SHAPE, TEAM_SIZE
from facts.model import ROLES, SQUISHY_POOL, Hero
from facts.team import (
    FLIER_REACH,
    RANK_SENSITIVE,
    SPECIALIST_DELTA,
    number,
    pair_score,
    shape_flags,
)
from inference.intervals import (
    ANY,
    FALSE,
    INF,
    WHOLE,
    Abstract,
    Env,
    Exact,
    Iv,
    Top,
    divide,
    join,
    lift,
    subtract,
)
from inference.scoring import Objective

SLACK = 1e-12              # a float computation's slack per unit of its addends' magnitude
PAIR_COUNT = TEAM_SIZE * (TEAM_SIZE - 1) // 2      # the pairs a six holds


# the roles still open at a node: (role, first candidate, picks left)
type Open = tuple[tuple[int, int, int], ...]


class Branch(NamedTuple):
    """A node of the walk: the picks so far, locked ones included, by dense
    index, and the roles still open."""
    picks: tuple[int, ...]
    open: Open


# per role, per start: a value over the candidates from there on
type Suffix[T] = list[list[T]]


def _prefix(values: Sequence[float]) -> list[float]:
    """Running sums, from the empty one: [0, v0, v0 + v1, ...]."""
    out = [0.0]
    for v in values:
        out.append(out[-1] + v)
    return out


class Space:
    """One search's heroes by dense index - the locked picks, then each role's
    candidates: released, unbanned and not locked - and, once order() has put
    each role in walk order, the suffix tables the rules read."""

    def __init__(self, objective: Objective, locked: Sequence[Hero],
                 candidates: Sequence[Sequence[Hero]]) -> None:
        self.objective = objective
        self.world, self.m, self.red = objective.world, objective.m, objective.red
        self.heroes: list[Hero] = [*locked]
        self.roles: list[list[int]] = []
        for role in candidates:
            self.roles.append(list(range(len(self.heroes), len(self.heroes) + len(role))))
            self.heroes.extend(role)
        self.locked = list(range(len(locked)))
        self.role_of = [ROLES.index(h.role) for h in self.heroes]
        self.map_style = self.m.style_top if self.m is not None else None
        self._pairs: list[list[float]] | None = None

    @property
    def candidates(self) -> list[int]:
        """Every hero an open slot can take, by dense index."""
        return [i for role in self.roles for i in role]

    def order(self, potential: Sequence[float], draws: Sequence[float]) -> None:
        """Each role's candidates in walk order: the highest potential first,
        then the highest tie-break draw, then by hero id. The order speeds
        the search - on a plateau the draws lead it to the six the tie-break
        keeps - and moves no answer."""
        for role in self.roles:
            role.sort(key=lambda i: (-potential[i], -draws[i], self.heroes[i].id))

    def pairs(self) -> list[list[float]]:
        """Every pair's synergy score (facts.team.pair_score), by dense index."""
        if self._pairs is None:
            ids = [h.id for h in self.heroes]
            self._pairs = [[0.0 if a == b else float(pair_score(self.world, a, b)) for b in ids]
                           for a in ids]
        return self._pairs

    def suffixes[T](self, of: Callable[[list[int]], T]) -> Suffix[T]:
        """A value of each role's candidates from each start on."""
        return [[of(role[start:]) for start in range(len(role) + 1)] for role in self.roles]

    def extremes(self, values: Sequence[float]) -> tuple[Suffix[list[float]], Suffix[list[float]]]:
        """Per role and start: the running sums of the largest values from
        there on, and of the smallest, TEAM_SIZE at most."""
        def top(rest: list[int]) -> list[float]:
            return _prefix(sorted((values[i] for i in rest), reverse=True)[:TEAM_SIZE])

        def bottom(rest: list[int]) -> list[float]:
            return _prefix(sorted(values[i] for i in rest)[:TEAM_SIZE])
        return self.suffixes(top), self.suffixes(bottom)

    def counts(self, branch: Branch) -> list[int]:
        """The six's count per role on every completion of the branch."""
        out = [0] * len(ROLES)
        for i in branch.picks:
            out[self.role_of[i]] += 1
        for r, _, n in branch.open:
            out[r] += n
        return out


def _slack(values: Sequence[float], count: int = TEAM_SIZE) -> float:
    """The slack of a sum of `count` of these values taken in another order:
    none where they are whole numbers, else SLACK per unit of the largest
    sum of magnitudes."""
    if all(v == int(v) for v in values if math.isfinite(v)):
        return 0.0
    return SLACK * (1.0 + count * max((abs(v) for v in values), default=0.0))


# --- the metric rules -----------------------------------------------------------

class Rule(NamedTuple):
    """How one metric reads over a branch, and the slack its interval takes
    outward on both ends."""
    read: Callable[[Branch, Env], Abstract]
    slack: float = 0.0


class Spec(NamedTuple):
    """A metric's rule as the table holds it: what builds it on a search's
    Space, and the metrics it reads, which are computed first."""
    build: Callable[[Space], Rule]
    needs: tuple[str, ...] = ()


type Feature = Callable[[Hero, Space], float]
type Known = Callable[[Hero, Space], float | None]


def _fixed(value: Abstract) -> Spec:
    """A metric every completion holds the same value of."""
    return Spec(lambda space: Rule(lambda branch, env: value))


def _sum(feature: Feature) -> Spec:
    """A sum over the six: the picks' own, plus each open role's smallest
    and largest few."""
    def build(space: Space) -> Rule:
        values = [float(feature(h, space)) for h in space.heroes]
        tops, bottoms = space.extremes(values)

        def read(branch: Branch, env: Env) -> Abstract:
            total = 0.0
            for i in branch.picks:
                total += values[i]
            lo = hi = total
            for r, start, n in branch.open:
                lo += bottoms[r][start][n]
                hi += tops[r][start][n]
            return Iv(lo, hi)
        return Rule(read, _slack(values))
    return Spec(build)


def _count(test: Callable[[Hero, Space], object]) -> Spec:
    """How many of the six pass a test."""
    return _sum(lambda h, space: 1.0 if test(h, space) else 0.0)


def _per_pick(test: Callable[[Hero, Space], object]) -> Spec:
    """The share of the six that pass a test."""
    counted = _count(test)

    def build(space: Space) -> Rule:
        rule = counted.build(space)

        def read(branch: Branch, env: Env) -> Abstract:
            return divide(rule.read(branch, env), Iv(TEAM_SIZE, TEAM_SIZE))
        return Rule(read)
    return Spec(build)


def _scaled(key: str, by: Callable[[Space], float]) -> Spec:
    """Another metric divided by a board constant; 0 where it is 0."""
    def build(space: Space) -> Rule:
        divisor = by(space)

        def read(branch: Branch, env: Env) -> Abstract:
            return divide(env[key], Iv(divisor, divisor))
        return Rule(read)
    return Spec(build, (key,))


def _ratio(numerator: str, denominator: str) -> Spec:
    """One metric over another, 0 where the second is 0."""
    return Spec(lambda space: Rule(lambda branch, env: divide(env[numerator], env[denominator])),
                (numerator, denominator))


def _roles(of: Callable[[list[int]], Abstract]) -> Spec:
    """A metric the shape fixes: read off the six's count per role."""
    return Spec(lambda space: Rule(lambda branch, env: of(space.counts(branch))))


def _known_suffixes(space: Space, values: Sequence[float | None]
                    ) -> Suffix[tuple[list[float], int]]:
    """Per role and start: the known values from there on, ascending, and how
    many candidates have none."""
    def of(rest: list[int]) -> tuple[list[float], int]:
        known = sorted(v for i in rest if (v := values[i]) is not None)
        return known, len(rest) - len(known)
    return space.suffixes(of)


def _mean(known: Known, fallback: str | None = None) -> Spec:
    """The mean of the known values among the six - 0 with none known, or
    `fallback`'s value. Over j known values among the open picks it is at
    most (the picks' sum + the j largest open) / (the picks' count + j), and
    j runs from what each role must take to what it can."""
    def build(space: Space) -> Rule:
        values = [known(h, space) for h in space.heroes]
        table = _known_suffixes(space, values)

        def read(branch: Branch, env: Env) -> Abstract:
            total, count = 0.0, 0
            for i in branch.picks:
                v = values[i]
                if v is not None:
                    total += v
                    count += 1
            highs: list[float] = []
            lows: list[float] = []
            least = most = 0
            for r, start, n in branch.open:
                asc, unknown = table[r][start]
                take = min(n, len(asc))
                highs += asc[len(asc) - take:]
                lows += asc[:take]
                least += max(0, n - unknown)
                most += take
            highs.sort(reverse=True)
            lows.sort()
            lo, hi, up, down = INF, -INF, total, total
            for j in range(most + 1):
                if j:
                    up += highs[j - 1]
                    down += lows[j - 1]
                if j < least:
                    continue
                if count + j:
                    hi = max(hi, up / (count + j))
                    lo = min(lo, down / (count + j))
                else:
                    empty = env[fallback] if fallback else FALSE
                    if not isinstance(empty, Iv):
                        return ANY
                    hi, lo = max(hi, empty.hi), min(lo, empty.lo)
            return Iv(lo, hi)
        return Rule(read, _slack([v for v in values if v is not None]))
    return Spec(build, (fallback,) if fallback else ())


def _extreme_of(known: Known, lowest: bool) -> Spec:
    """The largest (or, `lowest`, the smallest) known value among the six;
    0 where none is known. An open role that must take known values
    bounds the far end by the one it can least avoid."""
    def build(space: Space) -> Rule:
        values = [known(h, space) for h in space.heroes]
        table = _known_suffixes(space, values)

        def read(branch: Branch, env: Env) -> Abstract:
            picked = [v for i in branch.picks if (v := values[i]) is not None]
            near: list[float] = []            # the end every completion reaches
            far: list[float] = []             # what forces the other end
            available: list[float] = []
            none_possible = not picked
            if picked:
                near.append(min(picked) if lowest else max(picked))
                far.append(near[-1])
            for r, start, n in branch.open:
                asc, unknown = table[r][start]
                if asc:
                    near.append(asc[0] if lowest else asc[-1])
                    available.append(asc[-1] if lowest else asc[0])
                must = n - unknown
                if must > 0:
                    none_possible = False
                    far.append(asc[len(asc) - must] if lowest else asc[must - 1])
            ends: list[float] = []
            if far:
                ends.append(min(far) if lowest else max(far))
            elif available:
                ends.append(max(available) if lowest else min(available))
            if none_possible:
                near.append(0.0)
                ends.append(0.0)
            if not ends:
                return FALSE
            if lowest:
                return Iv(min(near), max(ends))
            return Iv(min(ends), max(near))
        return Rule(read)
    return Spec(build)


def _median(of: Callable[[Hero, Space], Sequence[float]]) -> Spec:
    """A median of the values the six carry lies between the least and the
    most of them; 0 where the six carries none."""
    def build(space: Space) -> Rule:
        values = [list(of(h, space)) for h in space.heroes]

        def ends(rest: list[int]) -> tuple[float, float, int]:
            flat = [v for i in rest for v in values[i]]
            return (min(flat, default=INF), max(flat, default=-INF),
                    sum(1 for i in rest if not values[i]))
        table = space.suffixes(ends)

        def read(branch: Branch, env: Env) -> Abstract:
            flat = [v for i in branch.picks for v in values[i]]
            lo, hi = min(flat, default=INF), max(flat, default=-INF)
            empty = not flat
            for r, start, n in branch.open:
                least, most, bare = table[r][start]
                lo, hi = min(lo, least), max(hi, most)
                empty = empty and bare >= n
            if empty:
                lo, hi = min(lo, 0.0), max(hi, 0.0)
            return Iv(lo, hi)
        return Rule(read)
    return Spec(build)


def _product(factor: Feature) -> Spec:
    """A product over the six of factors in 0..1: the picks' own times each
    open role's smallest few (the low end) and largest few (the high)."""
    def build(space: Space) -> Rule:
        values = [float(factor(h, space)) for h in space.heroes]
        if any(v < 0 for v in values):
            return Rule(lambda branch, env: WHOLE)

        def products(rest: list[int]) -> tuple[list[float], list[float]]:
            asc = sorted(values[i] for i in rest)
            low, high = [1.0], [1.0]
            for v in asc[:TEAM_SIZE]:
                low.append(low[-1] * v)
            for v in asc[::-1][:TEAM_SIZE]:
                high.append(high[-1] * v)
            return low, high
        table = space.suffixes(products)

        def read(branch: Branch, env: Env) -> Abstract:
            lo = 1.0
            for i in branch.picks:
                lo *= values[i]
            hi = lo
            for r, start, n in branch.open:
                low, high = table[r][start]
                lo *= low[n]
                hi *= high[n]
            return Iv(lo, hi)
        return Rule(read, SLACK * 2.0)
    return Spec(build)


def pair_halves(matrix: Sequence[Sequence[float]], pool: Sequence[int],
                size: int) -> list[list[tuple[float, float]]]:
    """[k][x] -> (best, worst): half the sum of hero x's k best pairs in
    `matrix` with the rest of `pool`, and half its k worst, for each k below
    TEAM_SIZE and each of the `size` heroes. An open pick takes them for its
    pairs among the other open picks, each such pair counted from both
    ends."""
    halves: list[list[tuple[float, float]]] = []
    for k in range(TEAM_SIZE):
        row = []
        for x in range(size):
            others = sorted(matrix[x][y] for y in pool if y != x)
            row.append((sum(others[len(others) - k:]) / 2 if k else 0.0,
                        sum(others[:k]) / 2))
        halves.append(row)
    return halves


def _pairwise(weight: Callable[[Space], list[list[float]]]) -> Spec:
    """A sum over the six's pairs: the picks' own pairs,
    each open candidate's pairs with the picks, and half its best (or worst)
    pairs among the rest of the roster (pair_halves). Each role then takes
    its best (or worst) few."""
    def build(space: Space) -> Rule:
        matrix = weight(space)
        halves = pair_halves(matrix, space.candidates, len(space.heroes))
        flat = [v for row in matrix for v in row]

        def read(branch: Branch, env: Env) -> Abstract:
            picks = branch.picks
            inside = 0.0
            for a in range(len(picks)):
                for b in range(a + 1, len(picks)):
                    inside += matrix[picks[a]][picks[b]]
            lo = hi = inside
            m = sum(n for _, _, n in branch.open)
            for r, start, n in branch.open:
                half = halves[m - 1]
                best, worst = [], []
                for x in space.roles[r][start:]:
                    with_picks = 0.0
                    for p in picks:
                        with_picks += matrix[p][x]
                    best.append(with_picks + half[x][0])
                    worst.append(with_picks + half[x][1])
                best.sort(reverse=True)
                worst.sort()
                hi += sum(best[:n])
                lo += sum(worst[:n])
            return Iv(lo, hi)
        return Rule(read, _slack(flat, count=PAIR_COUNT))
    return Spec(build)


def _masks(space: Space) -> list[int]:
    """Each hero's answers to red's picks, a bit per enemy."""
    world = space.world
    return [sum(1 << e for e, enemy in enumerate(space.red)
                if world.is_countered_by(enemy.id, h.id)) for h in space.heroes]


def _coverage(per_enemy: bool = False) -> Spec:
    """Red's picks answered by at least one of the six: at least the picks'
    own, at most what the picks and the open roles can answer between them
    and the picks' own plus each role's best few new answers. `per_enemy`
    reads it as a share of red's picks."""
    def build(space: Space) -> Rule:
        masks = _masks(space)
        enemies = len(space.red)

        def union(rest: list[int]) -> int:
            out = 0
            for i in rest:
                out |= masks[i]
            return out
        unions = space.suffixes(union)

        def read(branch: Branch, env: Env) -> Abstract:
            covered = 0
            for i in branch.picks:
                covered |= masks[i]
            reach, gain = covered, 0
            for r, start, n in branch.open:
                reach |= unions[r][start]
                news = sorted(((masks[x] & ~covered).bit_count()
                               for x in space.roles[r][start:]), reverse=True)
                gain += sum(news[:n])
            have = covered.bit_count()
            lo, hi = float(have), float(min(reach.bit_count(), have + gain))
            if per_enemy:
                return Iv(lo / enemies, hi / enemies) if enemies else FALSE
            return Iv(lo, hi)
        return Rule(read)
    return Spec(build)


def _double_covered() -> Spec:
    """Red's picks answered by two or more of the six: at least those the
    picks already answer twice, at most those the picks and each open role's
    answerers, n a role at most, can reach twice."""
    def build(space: Space) -> Rule:
        masks = _masks(space)
        enemies = range(len(space.red))
        table = space.suffixes(
            lambda rest: [sum(1 for i in rest if masks[i] >> e & 1) for e in enemies])

        def read(branch: Branch, env: Env) -> Abstract:
            have = [sum(1 for i in branch.picks if masks[i] >> e & 1) for e in enemies]
            can = list(have)
            for r, start, n in branch.open:
                for e, answerers in enumerate(table[r][start]):
                    can[e] += min(n, answerers)
            return Iv(float(sum(1 for c in have if c >= 2)), float(sum(1 for c in can if c >= 2)))
        return Rule(read)
    return Spec(build)


def _distinct_subroles() -> Spec:
    """team.subrole_diversity: the six's distinct subroles over six - at
    least the picks', at most those and every open role's, and never more
    than one per pick."""
    def build(space: Space) -> Rule:
        subroles = [h.subrole for h in space.heroes]
        table = space.suffixes(lambda rest: {subroles[i] for i in rest})

        def read(branch: Branch, env: Env) -> Abstract:
            have = {subroles[i] for i in branch.picks}
            reach = set(have)
            m = 0
            for r, start, n in branch.open:
                reach |= table[r][start]
                m += n
            return Iv(len(have) / TEAM_SIZE, min(len(reach), len(have) + m) / TEAM_SIZE)
        return Rule(read)
    return Spec(build)


def _partners(space: Space) -> tuple[list[int], list[bool], Suffix[int]]:
    """The synergy graph the wiki claims, by dense index: each hero's
    partners in the space, a bit per hero; whether it has a partner
    anywhere, which isolated counts; and each open role's candidates from
    each start on, a bit per hero."""
    index = {h.id: i for i, h in enumerate(space.heroes)}
    partners = [space.world.partners.get(h.id) or {} for h in space.heroes]
    masks = [sum(1 << index[p] for p in pair if p in index) for pair in partners]
    return masks, [bool(pair) for pair in partners], space.suffixes(
        lambda rest: sum(1 << i for i in rest))


def _bits(mask: int) -> list[int]:
    """The dense indices a mask holds."""
    out = []
    while mask:
        low = mask & -mask
        out.append(low.bit_length() - 1)
        mask ^= low
    return out


def _component(seed: int, allowed: int, masks: Sequence[int]) -> int:
    """The heroes of `allowed` the claimed pairs join to `seed`, a bit each."""
    group = frontier = 1 << seed
    while frontier:
        grown = 0
        for i in _bits(frontier):
            grown |= masks[i]
        frontier = grown & allowed & ~group
        group |= frontier
    return group


def _isolated() -> Spec:
    """team.isolated_count: the picks with a documented partner somewhere
    and none among the six. A pick is isolated on no completion where one
    of its partners is picked, and on every one where none is picked or
    left to an open role. An open candidate can be isolated only where it
    has a partner somewhere and none among the picks, so each open role
    adds at most its slots of those; and it adds at least its slots less
    the candidates that can be partnered - with no partner anywhere, or one
    among the picks or the open roles' candidates."""
    def build(space: Space) -> Rule:
        masks, partnered, unions = _partners(space)

        def read(branch: Branch, env: Env) -> Abstract:
            picked = sum(1 << i for i in branch.picks)
            reach = picked
            for r, start, _ in branch.open:
                reach |= unions[r][start]
            lo = hi = 0
            for i in branch.picks:
                if partnered[i] and not masks[i] & picked:
                    hi += 1
                    if not masks[i] & reach:
                        lo += 1
            for r, start, n in branch.open:
                rest = space.roles[r][start:]
                hi += min(n, sum(1 for x in rest if partnered[x] and not masks[x] & picked))
                lo += max(0, n - sum(1 for x in rest if not partnered[x] or masks[x] & reach))
            return Iv(float(lo), float(hi))
        return Rule(read)
    return Spec(build)


def _core() -> Spec:
    """team.core_size: the largest group the claimed pairs join among the
    six. A hero added only joins groups, so it is at least the picks'
    largest; and a group of the six lies within one group of the graph
    over the picks and every candidate the open roles have left, so it is
    at most, over those groups, the picks in one plus what each open role
    can seat there, its slots at most."""
    def build(space: Space) -> Rule:
        masks, _, unions = _partners(space)

        def largest(allowed: int, weigh: Callable[[int], int]) -> int:
            best, left = 0, allowed
            while left:
                group = _component((left & -left).bit_length() - 1, allowed, masks)
                best = max(best, weigh(group))
                left &= ~group
            return best

        def read(branch: Branch, env: Env) -> Abstract:
            picked = sum(1 << i for i in branch.picks)
            reach = picked
            for r, start, _ in branch.open:
                reach |= unions[r][start]
            lo = max(1, largest(picked, int.bit_count))
            hi = largest(reach, lambda group: (group & picked).bit_count() + sum(
                min(n, (unions[r][start] & group).bit_count()) for r, start, n in branch.open))
            return Iv(float(lo), float(max(lo, hi)))
        return Rule(read)
    return Spec(build)


def _banproof() -> Spec:
    """team.banproof_coverage: red's picks answered once the six's most
    banned pick is gone - never more than the coverage, and 0 while red
    has no picks."""
    def build(space: Space) -> Rule:
        def read(branch: Branch, env: Env) -> Abstract:
            cover = env["team.coverage"]
            if not space.red:
                return FALSE
            return Iv(0.0, cover.hi) if isinstance(cover, Iv) else ANY
        return Rule(read)
    return Spec(build, ("team.coverage",))


def _versus(feature: Callable[[Hero, Space], float]) -> Spec:
    """A sum over the six that reads red's picks, 0 while red has none."""
    return _sum(lambda h, space: feature(h, space) if space.red else 0.0)


def _answers(h: Hero, space: Space) -> float:
    return float(sum(1 for e in space.red if space.world.is_countered_by(e.id, h.id)))


def _exposures(h: Hero, space: Space) -> float:
    return float(sum(1 for e in space.red if space.world.is_countered_by(h.id, e.id)))


def _map_win(h: Hero, space: Space) -> float | None:
    return h.map_win(space.m.id) if space.m is not None else None


def _map_delta(h: Hero, space: Space) -> float | None:
    """A hero's win rate here over its own baseline, where both are known."""
    here = _map_win(h, space)
    return here - h.win if here is not None and h.win is not None else None


def _map_ban_factor(h: Hero, space: Space) -> float:
    ban = h.map_ban(space.m.id) if space.m is not None else None
    rate = h.ban if ban is None else ban
    return 1.0 - (rate or 0) / 100.0


def _on_map(on: Spec, off: Spec) -> Spec:
    """A map metric: `on` with a map set, `off` without one."""
    return Spec(lambda space: (on if space.m is not None else off).build(space),
                tuple({*on.needs, *off.needs}))


def _read(key: str) -> Spec:
    """Another metric's value, as it is."""
    return Spec(lambda space: Rule(lambda branch, env: env[key]), (key,))


TEAM_RULES: dict[str, Spec] = {
    "size": _fixed(Iv(TEAM_SIZE, TEAM_SIZE)),
    "open_slots": _fixed(FALSE),
    "tanks": _roles(lambda c: lift(c[0])),
    "damage": _roles(lambda c: lift(c[1])),
    "supports": _roles(lambda c: lift(c[2])),
    "subrole_diversity": _distinct_subroles(),
    "subroles": _fixed(Top(TEAM_SIZE)),
    "shape_flags": _roles(lambda c: Exact(shape_flags(*c))),
    "style_counts": _fixed(ANY),
    "style_top": _fixed(ANY),
    "style_lean": _fixed(ANY),
    "style_share": _fixed(Iv(0.0, 1.0)),
    "style_fit": _per_pick(lambda h, s: s.map_style is not None and s.map_style in h.styles),
    "shape_excess": _roles(lambda c: lift(sum(
        max(0, c[i] - EXPECTED_SHAPE[r]) for i, r in enumerate(ROLES)))),
    "pool_total": _sum(lambda h, s: h.pool + h.form_armor),
    "pool_min": _extreme_of(lambda h, s: h.pool, lowest=True),
    "weakest": _fixed(ANY),
    "armor_total": _sum(lambda h, s: h.armor + h.form_armor),
    "armor_share": _ratio("team.armor_total", "team.pool_total"),
    "shield_total": _sum(lambda h, s: h.shield),
    "shield_share": _ratio("team.shield_total", "team.pool_total"),
    "squish_count": _count(lambda h, s: h.pool <= SQUISHY_POOL),
    "squishies": _fixed(Top(TEAM_SIZE)),
    "overhealth_total": _sum(lambda h, s: h.overhealth),
    "dps_floor": _sum(lambda h, s: h.dps),
    "dps_count": _count(lambda h, s: h.dps),
    "burst_max": _extreme_of(lambda h, s: h.burst, lowest=False),
    "one_shots": _count(lambda h, s: h.burst >= SQUISHY_POOL and not h.melee),
    "burst_hero": _fixed(ANY),
    "burst_ranged": _extreme_of(lambda h, s: None if h.melee_only else h.burst, lowest=False),
    "ult_damage_total": _sum(lambda h, s: h.ult_damage),
    "dmg_ults": _count(lambda h, s: h.ult_deals_damage),
    "ult_cost_mean": _mean(lambda h, s: h.ult_cost),
    "hitscan": _count(lambda h, s: h.hitscan),
    "hitscan_reach": _count(lambda h, s: h.hitscan_range >= FLIER_REACH),
    "projectile": _count(lambda h, s: "projectile" in h.weapon_kinds),
    "beam": _count(lambda h, s: h.beam),
    "melee": _count(lambda h, s: h.melee),
    "aoe_count": _sum(lambda h, s: h.aoe_count),
    "aoe_damage_count": _sum(lambda h, s: h.aoe_damage_count),
    "range_known": _count(lambda h, s: h.max_range is not None),
    "range_median": _median(lambda h, s: [] if h.max_range is None else [h.max_range]),
    "range_max": _extreme_of(lambda h, s: h.max_range, lowest=False),
    "range_min": _extreme_of(lambda h, s: h.max_range, lowest=True),
    "dmg_amp": _count(lambda h, s: h.dmg_amp),
    "hps_floor": _sum(lambda h, s: h.hps),
    "heal_peak_total": _sum(lambda h, s: max(h.peak_heal, h.self_heal)),
    "heal_peak_supports": _sum(lambda h, s: h.peak_heal if h.role == "support" else 0.0),
    "heal_peak_max": _extreme_of(lambda h, s: h.peak_heal, lowest=False),
    "heal_ratio": _scaled("team.heal_peak_supports", lambda s: s.world.heal_bench),
    "hps_supports": _sum(lambda h, s: h.hps if h.role == "support" else 0.0),
    "hps_ratio": _scaled("team.hps_supports", lambda s: s.world.hps_bench),
    "hps_per_support": _mean(lambda h, s: h.hps if h.role == "support" else None),
    "heal_amp": _count(lambda h, s: h.heal_amp),
    "antiheal": _count(lambda h, s: h.antiheal < 0),
    "cleanse": _count(lambda h, s: h.cleanse_tools),
    "invuln": _count(lambda h, s: h.invuln_tools),
    "team_cleanse": _count(lambda h, s: h.team_cleanse_tools),
    "team_saves": _count(lambda h, s: h.save_tools),
    "lifelines": _count(lambda h, s: h.peak_heal or h.hps or h.self_heal or h.self_hps
                        or h.lifesteal),
    "cooldown_median": _median(lambda h, s: h.cooldowns),
    "cooldown_count": _sum(lambda h, s: len(h.cooldowns)),
    "cc_count": _count(lambda h, s: h.cc_tools),
    "shove_count": _count(lambda h, s: h.shove_tools),
    "mobility_count": _count(lambda h, s: h.mobility_tools),
    "flyers": _count(lambda h, s: h.flyer),
    "light_flyers": _count(lambda h, s: h.flyer and h.role != "tank"),
    "barrier_hp": _sum(lambda h, s: h.barrier_hp),
    "barrier_count": _count(lambda h, s: h.barrier_hp),
    "barrier_piercers": _count(lambda h, s: h.pierces_barrier),
    "pierce_dps": _sum(lambda h, s: h.dps if h.pierces_barrier else 0.0),
    "deployables": _count(lambda h, s: h.deployables),
    "synergy_edges": _pairwise(lambda s: [[1.0 if a is not b and s.world.synergy(a.id, b.id)
                                           else 0.0 for b in s.heroes] for a in s.heroes]),
    "synergy_score": _pairwise(Space.pairs),
    "synergy_density": _scaled("team.synergy_edges", lambda s: PAIR_COUNT),
    "isolated_count": _isolated(),
    "isolated": _fixed(Top(TEAM_SIZE)),
    "core_size": _core(),
    "pairs": _fixed(Top(PAIR_COUNT)),
    "unwritten_pairs": _fixed(Top(PAIR_COUNT)),
    "unwritten_cells": _pairwise(lambda s: [[float(s.world.unwritten_cells(a.id, b.id))
                                             if a is not b else 0.0 for b in s.heroes]
                                            for a in s.heroes]),
    "win_mean": _mean(lambda h, s: h.win),
    "pick_mass": _sum(lambda h, s: h.pick or 0),
    "availability": _product(lambda h, s: 1.0 - (h.ban or 0) / 100.0),
    "map_availability": _product(_map_ban_factor),
    "max_ban_rate": _extreme_of(lambda h, s: h.ban or 0, lowest=False),
    "max_ban_hero": _fixed(ANY),
    "rank_sensitive_count": _count(lambda h, s: h.rank_spread >= RANK_SENSITIVE),
    "trend_sum": _sum(lambda h, s: h.trend if h.trend is not None else 0.0),
    "map_win_mean": _on_map(_mean(_map_win, "team.win_mean"), _read("team.win_mean")),
    "map_pick_mass": _on_map(_sum(lambda h, s: h.map_pick(s.m.id) or 0 if s.m else 0),
                             _read("team.pick_mass")),
    "map_specialists": _on_map(_count(lambda h, s: (d := _map_delta(h, s)) is not None
                                      and d >= SPECIALIST_DELTA), _fixed(FALSE)),
    "map_offmap": _on_map(_count(lambda h, s: (d := _map_delta(h, s)) is not None
                                 and d <= -SPECIALIST_DELTA), _fixed(FALSE)),
    "home_map_hits": _on_map(_count(lambda h, s: s.m is not None and s.m.id in h.best_maps),
                             _fixed(FALSE)),
    "coverage": _coverage(),
    "coverage_share": _coverage(per_enemy=True),
    "unanswered": _fixed(Top(TEAM_SIZE)),
    "answer_edges": _versus(_answers),
    "exposure_edges": _versus(_exposures),
    "exposed_count": _versus(lambda h, s: 1.0 if _exposures(h, s) else 0.0),
    "exposed": _fixed(Top(TEAM_SIZE)),
    "safe_count": _versus(lambda h, s: 0.0 if _exposures(h, s) else 1.0),
    "net_edges": _versus(lambda h, s: _answers(h, s) - _exposures(h, s)),
    "double_covered": _double_covered(),
    "banproof_coverage": _banproof(),
}


def _red(space: Space, key: str) -> float:
    """One of red's team metrics, a number."""
    return float(number(space.objective.red_t[key]))


def _less_red(key: str, red: str) -> Spec:
    """A metric of the six less one of red's."""
    def build(space: Space) -> Rule:
        theirs = _red(space, red)
        return Rule(lambda branch, env: subtract(env[key], Iv(theirs, theirs)))
    return Spec(build, (key,))


def _red_less(red: str, key: str) -> Spec:
    """One of red's metrics less the six's."""
    def build(space: Space) -> Rule:
        theirs = _red(space, red)
        return Rule(lambda branch, env: subtract(Iv(theirs, theirs), env[key]))
    return Spec(build, (key,))


# a chew time where either side's pool or damage is 0 (compute.matchup_metrics)
CHEW_POINT = Iv(compute.CHEW_UNKNOWN, compute.CHEW_UNKNOWN)


def _chew_ours() -> Spec:
    """matchup.chew_time_ours: red's pool over the six's damage,
    CHEW_POINT where either is 0."""
    def build(space: Space) -> Rule:
        pool = _red(space, "pool_total")

        def read(branch: Branch, env: Env) -> Abstract:
            dps = env["team.dps_floor"]
            if not pool:
                return CHEW_POINT
            if not isinstance(dps, Iv):
                return ANY
            out = divide(Iv(pool, pool), dps)
            return join(out, CHEW_POINT) if dps.lo <= 0 <= dps.hi else out
        return Rule(read)
    return Spec(build, ("team.dps_floor",))


def _chew_theirs() -> Spec:
    """matchup.chew_time_theirs: the six's pool over red's damage,
    CHEW_POINT where either is 0."""
    def build(space: Space) -> Rule:
        dps = _red(space, "dps_floor")

        def read(branch: Branch, env: Env) -> Abstract:
            pool = env["team.pool_total"]
            if not dps:
                return CHEW_POINT
            if not isinstance(pool, Iv):
                return ANY
            out = divide(pool, Iv(dps, dps))
            return join(out, CHEW_POINT) if pool.lo <= 0 <= pool.hi else out
        return Rule(read)
    return Spec(build, ("team.pool_total",))


def _range_diff() -> Spec:
    """matchup.range_diff: the six's median reach less red's, 0 where either
    side publishes none."""
    def build(space: Space) -> Rule:
        red_known = _red(space, "range_known")
        red_median = _red(space, "range_median")

        def read(branch: Branch, env: Env) -> Abstract:
            known, median = env["team.range_known"], env["team.range_median"]
            if not red_known:
                return FALSE
            if not isinstance(known, Iv):
                return ANY
            gap = subtract(median, Iv(red_median, red_median))
            if known.lo >= 1:
                return gap
            return FALSE if known.hi < 1 else join(gap, FALSE)
        return Rule(read)
    return Spec(build, ("team.range_known", "team.range_median"))


def _heal_need() -> Spec:
    """matchup.heal_need: monotone in the six's pool (compute.heal_need)."""
    def build(space: Space) -> Rule:
        read_red = compute.heal_read(space.world, space.objective.red_t)

        def read(branch: Branch, env: Env) -> Abstract:
            pool = env["team.pool_total"]
            if not isinstance(pool, Iv):
                return ANY
            ends = (compute.heal_need(read_red, pool.lo), compute.heal_need(read_red, pool.hi))
            return Iv(min(ends), max(ends))
        return Rule(read)
    return Spec(build, ("team.pool_total",))


def _heal_shortfall() -> Spec:
    """matchup.heal_shortfall: monotone in the need and in the healing, so
    its range over a box is its range over the box's corners."""
    def read(branch: Branch, env: Env) -> Abstract:
        need, healing = env["matchup.heal_need"], env["team.hps_floor"]
        if not (isinstance(need, Iv) and isinstance(healing, Iv)):
            return ANY
        corners = [compute.heal_shortfall(n, h) for n in (need.lo, need.hi)
                   for h in (healing.lo, healing.hi)]
        return Iv(min(corners), max(corners))
    return Spec(lambda space: Rule(read, SLACK * 4.0), ("matchup.heal_need", "team.hps_floor"))


MATCHUP_RULES: dict[str, Spec] = {
    "pool_diff": _less_red("team.pool_total", "pool_total"),
    "dps_diff": _less_red("team.dps_floor", "dps_floor"),
    "hps_diff": _less_red("team.hps_floor", "hps_floor"),
    "burst_vs_heal": _less_red("team.burst_max", "heal_peak_max"),
    "heal_vs_burst": _less_red("team.heal_peak_max", "burst_max"),
    "chew_time_ours": _chew_ours(),
    "chew_time_theirs": _chew_theirs(),
    "tempo_diff": _red_less("cooldown_median", "team.cooldown_median"),
    "range_diff": _range_diff(),
    "exposure_share": _scaled("team.exposed_count", lambda s: TEAM_SIZE),
    "ult_answers": _sum(lambda h, s: float(bool(h.invuln_tools)) + float(bool(h.cleanse_tools))),
    "heal_need": _heal_need(),
    "heal_shortfall": _heal_shortfall(),
}

# every metric a branch can read, by its dotted key
RULES: dict[str, Spec] = {
    **{"team." + k: v for k, v in TEAM_RULES.items()},
    **{"matchup." + k: v for k, v in MATCHUP_RULES.items()}}


def rule_order(space: Space, keys: Sequence[str]) -> list[tuple[str, Rule]]:
    """The rules for `keys` and what they read, each after its needs."""
    ordered: list[tuple[str, Rule]] = []
    seen: set[str] = set()

    def visit(key: str) -> None:
        if key in seen:
            return
        seen.add(key)
        spec = RULES[key]
        for need in spec.needs:
            visit(need)
        ordered.append((key, spec.build(space)))
    for key in sorted(keys):
        visit(key)
    return ordered


def evaluate(steps: Sequence[tuple[str, Rule]], branch: Branch) -> Env:
    """A branch's Env: each planned metric's range, its slack outward."""
    env: Env = {}
    for key, rule in steps:
        value = rule.read(branch, env)
        if rule.slack and isinstance(value, Iv):
            value = Iv(value.lo - rule.slack, value.hi + rule.slack)
        env[key] = value
    return env
