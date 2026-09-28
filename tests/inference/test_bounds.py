"""The search's bounds, held to what they bound. Every team and matchup
metric has a rule and every node type and operator the expression
whitelist admits has one; and on random branches of random boards, pairs
no article writes among them, under the reference playbook and scratch
strategies of every form - a need, text
gates, and/or/not, a chained comparison, a clamped division, len, in, if,
powers and remainders - every metric's range holds its value on every
completion, every expression's holds its value, the bound holds every
completion's score and tie-break, and a branch the limits rule out holds
no six that keeps them. Every board is the synthetic World's: no
database."""

import ast
import copy
import dataclasses
import itertools
import math
import os
import random
import shutil

import pytest

from facts import compute
from facts.draft import Draft
from facts.team import TEAM_METRICS
from inference import bounds, catalog, expr
from inference.base import OFF
from inference.expr import scope
from inference.scoring import Candidate
from inference.solver import Solver, _open
from tests.inference import ASSUMPTIONS_ONLY, DEFAULT, FIXTURE_PLAYBOOK

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
}
LIMITS = {
    "ranged": "require: team.range_known >= 2 or team.hitscan >= 1",
}


def playbook(tmp_path):
    """The reference playbook with the scratch strategies beside it."""
    for name in os.listdir(FIXTURE_PLAYBOOK):
        shutil.copy(os.path.join(FIXTURE_PLAYBOOK, name), tmp_path)
    for sid, body in SCRATCH.items():
        (tmp_path / ("%s.md" % sid)).write_text(
            "---\nname: %s\nkind: heuristic\n%s\n---\nx\n" % (sid, body), "utf-8")
    for sid, body in LIMITS.items():
        (tmp_path / ("%s.md" % sid)).write_text(
            "---\nname: %s\nkind: constraint\n%s\n---\nx\n" % (sid, body), "utf-8")
    return catalog.load(str(tmp_path))


def test_every_metric_and_every_expression_rule_has_a_bound():
    """A metric without a rule, or a node type or operator the whitelist
    admits without an interval rule, would leave the bound nothing to read:
    the tables must cover the registry and the whitelist exactly."""
    assert set(bounds.TEAM_RULES) == set(TEAM_METRICS)
    assert set(bounds.MATCHUP_RULES) == set(compute.MATCHUP_METRICS)
    assert set(bounds.NODES) == set(expr._RULES)
    assert set(bounds.OPERATORS) == {*expr.BINARY, *expr.UNARY, *expr.COMPARE}


def holds(value, abstract):
    """Whether a concrete value lies in an abstract one."""
    if isinstance(abstract, bounds.Top):
        return not isinstance(value, list | dict) or len(value) <= abstract.size
    if isinstance(abstract, bounds.Exact):
        return value == abstract.value
    if isinstance(abstract, bounds.Seq):
        return isinstance(value, list | tuple) and len(value) == len(abstract.items) and all(
            holds(v, a) for v, a in zip(value, abstract.items, strict=True))
    if isinstance(value, bool | int | float):
        return abstract.lo <= value <= abstract.hi
    return False


def branches(solver, rng, count):
    """Random nodes of the walk on a solver's board: a shape, the first j of
    its slots filled at rising places of each role's walk order, and the
    next slot's first place."""
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
        yield walk, frame, _open(slots, j, start)


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
    """A copy of the world whose articles write a cell for every pair but
    two - Rook with Balm, and Needle with Sorrel - so those two read at the
    written pairs' mean, 1.25 here, as an unwritten pair does."""
    world = copy.copy(world)
    released = [h for h in world.heroes.values() if h.released]
    unwritten = {frozenset((world.hero(a).id, world.hero(b).id))
                 for a, b in (("Rook", "Balm"), ("Needle", "Sorrel"))}
    world.synergy_written = {frozenset((a.id, b.id)) for a, b in itertools.combinations(
        released, 2)} - unwritten
    world.synergy_prior = 1.25
    assert all(world.synergy_unwritten(*pair) for pair in unwritten)
    return world


CASES = {
    "scratch-base-off": ("scratch", OFF, False),
    "scratch-base-on": ("scratch", DEFAULT, False),
    "engine-alone": ("assumptions", DEFAULT, False),
    "engine-pairs-heavy": ("assumptions", PAIRS_HEAVY, False),
    "unwritten-pairs": ("scratch", PAIRS_HEAVY, True)}


@pytest.mark.parametrize(("rules", "base", "imputed"), list(CASES.values()), ids=list(CASES))
def test_every_bound_holds_every_completion_of_random_branches(
        synthetic_world, tmp_path, rules, base, imputed):
    """On random branches of each board, for every six the branch can still
    become: each team and matchup metric lies in its rule's range, each
    strategy's expressions lie in their abstract values, the tie-break lies
    under its bound, the score under the bound, and a branch the bound
    rules out holds no six that keeps every limit. Under assumptions alone
    the bound is the default engine's, nothing else's slack beside it, and
    on some branch it is within a hair of a completion's score."""
    rules = playbook(tmp_path) if rules == "scratch" else ASSUMPTIONS_ONLY
    world = imputing(synthetic_world) if imputed else synthetic_world
    rng = random.Random("bounds|%s|%s|%s" % (len(rules), base, imputed))
    closest = math.inf
    keys = sorted(bounds.RULES)
    checked = 0
    for draft in BOARDS:
        m, red, locked, banned = world.resolve(draft.map_name, draft.red, draft.blue, draft.bans)
        solver = Solver(world, m, red=red, locked=locked, banned=banned,
                        side=draft.side, catalog=rules, base=base)
        static = bounds._board_values(solver)
        expressions = [(s, e, bounds.abstract(e, s.params, static))
                       for s in rules for e in (s.when, s.require, s.bonus, s.penalty)
                       if e is not None]
        for walk, frame, open_roles in branches(solver, rng, 60):
            branch = bounds.Branch(frame.picks, open_roles)
            env = bounds.evaluate(bounds.plan(walk.space, keys), branch)
            top = walk.of(frame, open_roles)
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
                    closest = min(closest, top - cand.score)
                checked += 1
    assert checked > 1000
    assert rules is not ASSUMPTIONS_ONLY or closest < 1e-9    # the engine's bound is tight


def test_an_expression_reads_three_ways_where_a_branch_leaves_it_open():
    """A comparison a branch cannot settle reads either; `and`, `or` and an
    if join the outcomes they can take; a division by a range that holds 0
    reads anything; a name the board settles is its value."""
    static = {"enemy.flyers": bounds.Iv(1.0, 1.0), "map.side": bounds.Exact("attack")}

    def read(source, **env):
        compiled = bounds.abstract(expr.Expr(source), {"LIMIT": 2.0}, static)
        return compiled({"team." + k: v for k, v in env.items()})
    maybe = bounds.Iv(1.0, 3.0)
    assert read("team.tanks >= 2", tanks=maybe) == bounds.MAYBE
    assert read("team.tanks >= 1", tanks=maybe) == bounds.TRUE
    assert read("team.tanks > params.LIMIT + 1", tanks=maybe) == bounds.FALSE
    assert read("1 <= team.tanks <= 3 and map.side == 'attack'", tanks=maybe) == bounds.TRUE
    assert read("team.tanks and 5", tanks=bounds.Iv(0.0, 2.0)) == bounds.Iv(0.0, 5.0)
    assert read("team.tanks or 5", tanks=bounds.Iv(0.0, 2.0)) == bounds.Iv(0.0, 5.0)
    assert read("7 if enemy.flyers else team.tanks", tanks=maybe) == bounds.Iv(7.0, 7.0)
    assert read("1 / team.tanks", tanks=bounds.Iv(0.0, 2.0)) == bounds.WHOLE
    assert read("1 / team.tanks", tanks=bounds.Iv(0.0, 0.0)) == bounds.FALSE
    assert read("team.tanks ** 2", tanks=bounds.Iv(-1.0, 3.0)) == bounds.Iv(0.0, 9.0)
    assert read("len(team.subroles)", subroles=bounds.Top(6)) == bounds.Iv(0.0, 6.0)
    assert read("'x' in team.subroles", subroles=bounds.Top(6)) == bounds.MAYBE
    assert read("team.style_top == 'dive'", style_top=bounds.ANY) == bounds.MAYBE
    assert read("-team.tanks % 3", tanks=maybe) == bounds.Iv(0.0, 3.0)
    assert set(bounds.NODES) >= {ast.BoolOp, ast.Compare}
