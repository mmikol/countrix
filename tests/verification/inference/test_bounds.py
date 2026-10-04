"""The search's bounds, held to what they bound. Every team and matchup
metric has a rule and every node type and operator the expression
whitelist admits has one; and on random branches of random boards, synergy
cells no article writes among them, under the reference playbook and
scratch strategies of every form - a need, text gates, and/or/not, a
chained comparison, a clamped division, len, in, if, powers and
remainders, the synergy graph's isolated picks and largest group, rules
on per-pick counts that the fold bounds with the default engine, every
one of them or the heaviest within its cap - and the swap search's keep
term, the default engine on and off, every metric's range holds its
value on every completion, every expression's holds its value, the bound
and every bound the walk asks of a branch hold every completion's score,
the tie-break bound its tie-break, and a branch the limits rule out holds
no six that keeps them. The fold takes the heaviest count rules within
its cap, and the playstyle rules hold where two styles can lead a six.
Every board is the synthetic World's: no database."""

import ast
import copy
import dataclasses
import itertools
import math
import os
import random

import pytest

from facts import compute
from facts.draft import Draft
from facts.team import TEAM_METRICS, team_metrics
from inference import bounds, catalog, expr, intervals, ranges
from inference.base import OFF
from inference.expr import scope
from inference.scoring import Candidate
from inference.solver import Solver, _open
from tests.verification.inference import ASSUMPTIONS_ONLY, DEFAULT

SCRATCH = {
    "solo-mobility": (
        "metric: team.mobility_count\ndirection: maximize\nweight: 2\nwhen: team.supports <= 1"),
    "text-gate": (
        "when: team.style_top == 'dive' or team.style_lean == 'brawl'\n"
        "bonus: min(team.hitscan, 2) * 1.5"),
    "chained": (
        "when: 1 <= team.supports <= 2 and not (enemy.flyers >= 1)\n"
        "penalty: max(0, team.squish_count - 3) ** 2"),
    "clamped": "bonus: min(team.hps_floor / max(team.pool_total, 1) * 10, 3)",
    "listed": (
        "bonus: (1 if 'Flanker' in team.subroles else 0) + len(team.squishies) * 0.25"
        " + (0.5 if team.shape_flags == ['double tank'] else 0)"),
    "rounded": (
        "penalty: abs(round(matchup.pool_diff / 100, 1)) % 3"
        " + team.cooldown_count // 4 * 0.1 + (-team.trend_sum) * 0"),
    "picked": (
        "when: team.supports >= params.LEAST\nbonus: max([team.dps_count, team.hitscan_reach,"
        " team.dmg_ults]) - min(team.range_known, 2)\nparams:\n  LEAST: 2"),
    "slow-chew": "metric: matchup.chew_time_theirs\ndirection: maximize\nweight: 1",
    "availability": "metric: team.map_availability\ndirection: maximize\nweight: 1",
    "doubled": "metric: team.double_covered\ndirection: maximize\nweight: 1",
    "weakest": "metric: team.pool_min\ndirection: maximize\nweight: 0.5",
    "shared": "metric: team.armor_share\ndirection: minimize\nweight: 0.5",
    "costly": "metric: team.ult_cost_mean\ndirection: minimize\nweight: 0.5",
    "tempo": "metric: matchup.tempo_diff\ndirection: maximize\nweight: 0.5",
    "lonely": "metric: team.isolated_count\ndirection: maximize\nweight: 0.5",
    "tight-core": "metric: team.core_size\ndirection: minimize\nweight: 0.5",
    # a list beside a count: a term the walk reads afresh, its values unhashable
    "flagged": "bonus: (0.5 if team.shape_flags == ['double tank'] else 0) + min(team.flyers, 1)",
    # rules on per-pick counts alone, which the fold bounds with the default
    # engine: a bonus on two counts, a heuristic and a penalty on one, a gate
    # the six decides off a count, and a need guarded on one
    "two-counts": "bonus: min(team.mobility_count, 2) * 0.5 + min(team.cc_count, 1)",
    "count-metric": "metric: team.hitscan\ndirection: maximize\nweight: 1",
    "count-penalty": "penalty: max(0, 1 - team.team_saves) * 0.75",
    "count-gate": "when: team.squish_count >= 4\nbonus: min(team.invuln, 2) * 0.5",
    "count-need": (
        "metric: team.dmg_amp\ndirection: maximize\nweight: 1\nwhen: team.melee >= 1"),
}
LIMITS = {
    "ranged": "require: team.range_known >= 2 or team.hitscan >= 1",
}


def playbook(directory):
    """The reference playbook, copied to `directory` (catalog_copy), with the
    scratch strategies beside it."""
    for kind, rules in (("heuristic", SCRATCH), ("constraint", LIMITS)):
        for sid, body in rules.items():
            with open(os.path.join(directory, "%s.md" % sid), "w", encoding="utf-8") as handle:
                handle.write("---\nname: %s\nkind: %s\n%s\n---\nx\n" % (sid, kind, body))
    return catalog.load(directory)


def test_every_metric_and_every_expression_rule_has_a_bound():
    """A metric without a rule, or a node type or operator the whitelist
    admits without an interval rule, would leave the bound nothing to read:
    the tables must cover the registry and the whitelist exactly. Each rule
    says how its metric aggregates over the six, in the words the strategy
    registry shows: one line of ASCII."""
    assert set(ranges.TEAM_RULES) == set(TEAM_METRICS)
    assert set(ranges.MATCHUP_RULES) == set(compute.MATCHUP_METRICS)
    assert set(intervals.NODES) == set(expr._RULES)
    assert set(intervals.OPERATORS) == {*expr.BINARY, *expr.UNARY, *expr.COMPARE}
    for key, rule in ranges.RULES.items():
        words = rule.aggregate
        assert words and words.isascii() and words == words.strip() and "\n" not in words, key
        assert not words.endswith("."), key


def holds(value, abstract):
    """Whether a concrete value lies in an abstract one."""
    if isinstance(abstract, intervals.Top):
        return not isinstance(value, list | dict) or len(value) <= abstract.size
    if isinstance(abstract, intervals.Exact):
        return value == abstract.value
    if isinstance(abstract, intervals.Seq):
        return isinstance(value, list | tuple) and len(value) == len(abstract.items) and all(
            holds(v, a) for v, a in zip(value, abstract.items, strict=True))
    if isinstance(value, bool | int | float):
        return abstract.lo <= value <= abstract.hi
    return False


def branches(solver, rng, count):
    """Random nodes of the walk on a solver's board: a shape, the first j of
    its slots filled at rising places of each role's walk order, and the
    next slot's first place; and the shape's root, its open roles around
    the locked picks."""
    walk = solver._walker()
    roles = walk.space.roles
    shapes = solver._slots(walk.space)
    for _ in range(count):
        slots = rng.choice(shapes)
        j = rng.randint(0, len(slots))
        picks, start, frame = [], 0, walk.start()
        for i in range(j):
            role = roles[slots[i]]
            if i == 0 or slots[i - 1] != slots[i]:
                start = 0
            later = sum(1 for s in slots[i + 1:] if s == slots[i])
            place = rng.randint(start, len(role) - 1 - later)
            picks.append(role[place])
            frame = walk.push(frame, role[place])
            start = place + 1
        if j < len(slots) and (j == 0 or slots[j - 1] != slots[j]):
            start = 0
        yield walk, frame, _open(slots, j, start), _open(slots, 0, 0)


def completions(walk, frame, open_roles):
    """Every six the branch can still become."""
    parts = [itertools.combinations(walk.space.roles[r][start:], n) for r, start, n in open_roles]
    for combo in itertools.product(*parts):
        yield [walk.space.heroes[i] for i in (*frame.picks, *(x for part in combo for x in part))]


BOARDS = [
    Draft("Harbor Gate", side="attack"),
    Draft("Ember Ruins", ("Mortar", "Gale", "Balm")),
    Draft("Harbor Gate", ("Gale", "Needle"), ("Kite",), side="defense"),
    Draft("Salt Flats", ("Anvil", "Rook"), (), ("Myrrh",)),
    Draft(None, ("Quarry",), ("Balm", "Sorrel")),
]


# the default engine with synergy weighing as much as the rates: the pair bound's own test
PAIRS_HEAVY = dataclasses.replace(DEFAULT, synergy=2.0)


def imputing(world):
    """A copy of the world whose articles write both cells of every pair
    but four: neither writes Rook with Balm or Needle with Sorrel, so each
    of their cells reads the claim share, 0.625 here, and one article
    leaves Anvil with Kite blank, and Sorrel's leaves Gale, whom Gale's
    claims, so each of those reads the share once more."""
    world = copy.copy(world)
    released = [h for h in world.heroes.values() if h.released]
    ids = {h.name: h.id for h in released}
    blank = {(ids[a], ids[b]) for a, b in (
        ("Rook", "Balm"), ("Balm", "Rook"), ("Needle", "Sorrel"), ("Sorrel", "Needle"),
        ("Anvil", "Kite"), ("Sorrel", "Gale"))}
    world.synergy_written = {(a.id, b.id) for a, b in itertools.permutations(
        released, 2)} - blank
    world.synergy_cell = 0.625
    assert [world.unwritten_cells(ids[a], ids[b]) for a, b in (
        ("Rook", "Balm"), ("Needle", "Sorrel"), ("Anvil", "Kite"), ("Gale", "Sorrel"))] == [
            2, 2, 1, 1]
    return world


# the swap search's reference heroes and raw cost where a case keeps them
KEEP, KEEP_COST = ("Anvil", "Rook", "Gale", "Balm"), 0.35
CASES = {
    "scratch-base-off": ("scratch", OFF, False, False),
    "scratch-base-on": ("scratch", DEFAULT, False, False),
    "engine-alone": ("assumptions", DEFAULT, False, False),
    "engine-pairs-heavy": ("assumptions", PAIRS_HEAVY, False, False),
    "unwritten-pairs": ("scratch", PAIRS_HEAVY, True, False),
    "keep-base-off": ("scratch", OFF, False, True),
    "keep-alone": ("assumptions", OFF, False, True),
    "keep-base-on": ("assumptions", DEFAULT, False, True),
    "keep-scratch-base-on": ("scratch", DEFAULT, False, True),
    "capped-fold": ("capped", DEFAULT, False, False)}


@pytest.mark.parametrize(("rules", "base", "imputed", "keeps"), list(CASES.values()),
                         ids=list(CASES))
def test_every_bound_holds_every_completion_of_random_branches(
        synthetic_world, catalog_copy, monkeypatch, rules, base, imputed, keeps):
    """On random branches of each board, for every six the branch can still
    become: each team and matchup metric lies in its rule's range, each
    strategy's expressions lie in their abstract values, the tie-break lies
    under its bound, the score under the bound and under every bound the
    walk asks of the branch (Bound.bounds) - the engine's with every other
    term at the shape's root, the whole, and the fold - and a branch a
    bound rules out holds no six that keeps every limit. Under the scratch
    strategies the fold takes every count, so it meets each form of count
    rule, and capped it takes the heaviest and the rest are bounded apart;
    either way it is asked on many branches and reads below the whole bound
    on some. Under assumptions alone the bound is the default engine's and
    the keep term's, nothing else's slack beside it, and on some branch it
    is within a hair of a completion's score."""
    if rules == "scratch":      # every count folds, so the fold meets each form of count rule
        monkeypatch.setattr(bounds, "FOLD_COUNTS", len(ranges.RULES))
    rules = playbook(catalog_copy) if rules in ("scratch", "capped") else ASSUMPTIONS_ONLY
    world = imputing(synthetic_world) if imputed else synthetic_world
    keep = frozenset(world.hero(name).id for name in KEEP) if keeps else frozenset()
    rng = random.Random("bounds|%s|%s|%s%s" % (len(rules), base, imputed,
                                               "|keep" if keeps else ""))
    closest = math.inf
    keys = sorted(ranges.RULES)
    checked = folds = tighter = 0
    for draft in BOARDS:
        m, red, locked, banned = world.resolve(draft.map_name, draft.red, draft.blue, draft.bans)
        solver = Solver(world, m, red=red, locked=locked, banned=banned,
                        side=draft.side, catalog=rules, base=base, keep=keep, swap=KEEP_COST)
        static = bounds._board_values(solver)
        expressions = [(s, e, intervals.abstract(e, s.params, static))
                       for s in rules for e in (s.when, s.require, s.bonus, s.penalty)
                       if e is not None]
        for walk, frame, open_roles, root in branches(solver, rng, 60):
            branch = ranges.Branch(frame.picks, open_roles)
            env = ranges.evaluate(ranges.rule_order(walk.space, keys), branch)
            top = walk.of(frame, open_roles)
            asked = list(walk.bounds(frame, open_roles, root))
            folds += len(asked) == 3
            tighter += len(asked) == 3 and asked[2] < asked[1]
            tiebreak = walk.tiebreak(frame, open_roles)
            for six in completions(walk, frame, open_roles):
                cand = solver.score(solver.prepare(Candidate(six)), detail=False)
                ns = cand.ns
                for key in keys:
                    section, name = key.split(".", 1)
                    assert holds(ns[section][name], env[key]), (draft, key, ns[section][name],
                                                                env[key])
                sc = scope(ns)
                for strategy, e, abstract in expressions:
                    sc["params"] = strategy.params_section
                    assert holds(e.evaluate(sc), abstract(env)), (strategy.id, e.source)
                if top is None:
                    assert cand.violations, draft
                    continue
                assert cand.tiebreak <= tiebreak
                if not cand.violations:
                    assert cand.score <= top, (draft, cand.score, top)
                    assert all(b is not None and cand.score <= b for b in asked), (
                        draft, cand.score, asked)
                    closest = min(closest, top - cand.score)
                checked += 1
    assert checked > 1000
    assert rules is ASSUMPTIONS_ONLY or (folds > 50 and tighter)
    assert rules is not ASSUMPTIONS_ONLY or closest < 1e-9    # the engine's bound is tight


def test_the_fold_takes_the_heaviest_count_rules_within_its_cap(
        synthetic_world, catalog_copy, monkeypatch):
    """The vectors the fold weighs multiply with each count it reads, so it
    reads FOLD_COUNTS counts at most: of the terms on per-pick counts alone
    it takes the heaviest first, ties in the score's order, each where it
    and those taken before it read no more counts than that. Under the
    scratch strategies and a penalty on saves at three times their weight,
    which the score sums after lighter count rules, every board holds more
    such counts than the cap: the fold takes the penalty over a lighter rule
    before it, a term it leaves out would take it past the cap with the
    terms taken before it, and every term it takes is one the uncapped fold
    takes."""
    with open(os.path.join(catalog_copy, "heavy-save.md"), "w", encoding="utf-8") as handle:
        handle.write("---\nname: heavy-save\nkind: heuristic\nweight: 3\n"
                     "penalty: max(0, 1 - team.team_saves)\n---\nx\n")
    rules = playbook(catalog_copy)

    def walker(draft):
        m, red, locked, banned = synthetic_world.resolve(
            draft.map_name, draft.red, draft.blue, draft.bans)
        return Solver(synthetic_world, m, red=red, locked=locked, banned=banned,
                      side=draft.side, catalog=rules, base=DEFAULT)._walker()
    for draft in BOARDS:
        capped = walker(draft)
        with monkeypatch.context() as uncapped:
            uncapped.setattr(bounds, "FOLD_COUNTS", len(ranges.RULES))
            whole = walker(draft)
        terms = capped.terms
        counts = {n for f in capped._fold for n in terms[f.term].reads}
        assert len(counts) == len(capped._counts) <= bounds.FOLD_COUNTS < len(whole._counts)
        assert capped._in_fold < whole._in_fold, draft
        heavy = max(sorted(whole._in_fold), key=lambda i: terms[i].weight)
        assert terms[heavy].weight == 3 and heavy in capped._in_fold, draft
        assert any(i < heavy and i not in capped._in_fold for i in whole._in_fold), draft
        taken: set[str] = set()
        for i in sorted(sorted(whole._in_fold), key=lambda i: -terms[i].weight):
            wanted = taken | set(terms[i].reads)
            if i in capped._in_fold:
                taken = wanted
            assert (i in capped._in_fold) == (len(wanted) <= bounds.FOLD_COUNTS), (
                draft, terms[i].reads)


# heroes given a second playstyle, so that brawl and dive can both pass half a six
TWO_STYLES = ("Anvil", "Kite", "Rook", "Gale", "Balm", "Sorrel")


def test_the_playstyle_rules_hold_every_completion_where_two_styles_can_lead(synthetic_world):
    """team.style_lean and team.style_share hold every completion of random
    branches on a roster where six heroes carry both brawl and dive, so both
    can pass half a six and tie there: on boards whose maps reward brawl,
    dive and poke, the tie goes to the map's style, else to the name, as
    facts.team ranks them. The lean reads each of brawl, dive, '' and any
    on some branch, and settles some branch whose six ties its two leading
    styles; the share reads less than its whole range on some."""
    for name in TWO_STYLES:
        synthetic_world.hero(name).styles = {"brawl", "dive"}
    keys = ("team.style_lean", "team.style_share")
    rng = random.Random("bounds|styles")
    read, settled_ties, narrowed = set(), 0, False
    for map_name in ("Harbor Gate", "Ember Ruins", "Salt Flats"):
        m = synthetic_world.resolve(map_name, (), (), ())[0]
        solver = Solver(synthetic_world, m, red=[], locked=[], catalog=ASSUMPTIONS_ONLY, base=OFF)
        for walk, frame, open_roles, _ in branches(solver, rng, 80):
            env = ranges.evaluate(ranges.rule_order(walk.space, keys),
                                  ranges.Branch(frame.picks, open_roles))
            lean, share = env["team.style_lean"], env["team.style_share"]
            read.add(lean)
            narrowed = narrowed or share.hi - share.lo < 0.5
            for six in completions(walk, frame, open_roles):
                team = team_metrics(synthetic_world, six, m, (), only=("style_lean",))
                for key, value in (("style_lean", lean), ("style_share", share)):
                    assert holds(team[key], value), (map_name, six, key, team[key], value)
                counts = team["style_counts"]
                tied = counts.get("brawl", 0) == counts.get("dive", 0) > 3
                settled_ties += tied and isinstance(lean, intervals.Exact)
    assert {intervals.Exact("brawl"), intervals.Exact("dive"), intervals.Exact(""),
            intervals.ANY} <= read
    assert narrowed and settled_ties


def test_an_expression_reads_three_ways_where_a_branch_leaves_it_open():
    """A comparison a branch cannot settle reads either; `and`, `or` and an
    if join the outcomes they can take; a division by a range that holds 0
    reads anything, and a floor division's quotient that underflows to 0
    still floors below it; a name the board settles is its value."""
    static = {"enemy.flyers": intervals.Iv(1.0, 1.0), "map.side": intervals.Exact("attack")}

    def read(source, **env):
        compiled = intervals.abstract(expr.Expr(source), {"LIMIT": 2.0}, static)
        return compiled({"team." + k: v for k, v in env.items()})
    maybe = intervals.Iv(1.0, 3.0)
    assert read("team.tanks >= 2", tanks=maybe) == intervals.MAYBE
    assert read("team.tanks >= 1", tanks=maybe) == intervals.TRUE
    assert read("team.tanks > params.LIMIT + 1", tanks=maybe) == intervals.FALSE
    assert read("1 <= team.tanks <= 3 and map.side == 'attack'", tanks=maybe) == intervals.TRUE
    assert read("team.tanks and 5", tanks=intervals.Iv(0.0, 2.0)) == intervals.Iv(0.0, 5.0)
    assert read("team.tanks or 5", tanks=intervals.Iv(0.0, 2.0)) == intervals.Iv(0.0, 5.0)
    assert read("7 if enemy.flyers else team.tanks", tanks=maybe) == intervals.Iv(7.0, 7.0)
    assert read("1 / team.tanks", tanks=intervals.Iv(0.0, 2.0)) == intervals.WHOLE
    assert read("1 / team.tanks", tanks=intervals.Iv(0.0, 0.0)) == intervals.FALSE
    tiny = read("team.tanks // 1e10", tanks=intervals.Iv(-1e-320, -1e-320))
    assert tiny.lo <= -1e-320 // 1e10 == -1.0 <= tiny.hi
    assert read("team.tanks // 2", tanks=intervals.Iv(0.0, 0.0)) == intervals.FALSE
    assert read("team.tanks ** 2", tanks=intervals.Iv(-1.0, 3.0)) == intervals.Iv(0.0, 9.0)
    assert read("len(team.subroles)", subroles=intervals.Top(6)) == intervals.Iv(0.0, 6.0)
    assert read("'x' in team.subroles", subroles=intervals.Top(6)) == intervals.MAYBE
    assert read("team.style_top == 'dive'", style_top=intervals.ANY) == intervals.MAYBE
    assert read("-team.tanks % 3", tanks=maybe) == intervals.Iv(0.0, 3.0)
    assert set(intervals.NODES) >= {ast.BoolOp, ast.Compare}
