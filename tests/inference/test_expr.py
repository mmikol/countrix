"""The expression language the frontmatter uses: dotted names read as numbers,
nothing past the whitelist, and a sandbox that refuses what would hang or
exhaust it. No database."""

import pytest

from inference.expr import Expr, ExprError


def test_expressions_read_dotted_names_and_arithmetic():
    ns = {"team": {"tanks": 1, "hitscan": 3}, "params": {"X": 2}}
    assert Expr("team.tanks == 1 and team.hitscan >= params.X").evaluate(ns) is True
    assert Expr("min(team.hitscan, 2) * 1.5").evaluate(ns) == 3.0
    assert Expr("team.missing + 1").evaluate(ns) == 1          # unknown reads 0
    assert Expr("'dive' if team.tanks else 'brawl'").evaluate(ns) == "dive"
    assert Expr("team.tanks / 0").evaluate(ns) == 0.0


def test_a_division_by_zero_reads_zero_for_that_division_alone():
    """/, // and % by zero each read 0, and the rest of the expression is
    evaluated as written: a guard with a zero divisor on one side of an `or`
    still reads the other side."""
    ns = {"team": {"x": 3, "y": 0, "tanks": 1}}
    assert Expr("team.x / team.y > 1 or team.tanks == 1").evaluate(ns) is True
    assert Expr("team.x // team.y + team.x % team.y + 2").evaluate(ns) == 2
    assert Expr("min(team.x / team.y, 1) + 1").evaluate(ns) == 1
    assert Expr("team.x / (team.y / team.y)").evaluate(ns) == 0.0
    assert Expr("team.x / 2 + team.x // 2 + team.x % 2").evaluate(ns) == 1.5 + 1 + 1
    # a division nested in each divisor grows the code by one call a level
    nested = Expr("team.x / (" * 30 + "team.y" + ")" * 30)
    assert nested.evaluate(ns) == 0.0


def test_expressions_refuse_anything_beyond_the_whitelist():
    for bad in ("__import__('os')", "team.__class__", "[x for x in y]",
                "lambda: 1", "open('f')", "team.tanks = 2"):
        with pytest.raises(ExprError):
            Expr(bad).evaluate({"team": {}})
    # an operator outside the whitelist's tuples is refused as the node it sits in
    for bad, node in (("team.tanks | 1", "BinOp"), ("~team.tanks", "UnaryOp")):
        with pytest.raises(ExprError, match="unsupported syntax %s" % node):
            Expr(bad)


def test_expression_names_are_the_full_dotted_keys():
    assert Expr("team.tanks + enemy.flyers * params.K").names == [
        "enemy.flyers", "params.K", "team.tanks"]


def test_the_sandbox_refuses_what_would_hang_or_exhaust_it():
    from inference.expr import Expr, ExprError
    for bomb in ("9 ** 9 ** 9", "2 ** team.tanks", "'a' * 1000000000", "'x' + 'y'",
                 "'" + "s" * 201 + "' == team.style_lean", "-" * 45 + "1", "'%s' % team.x"):
        with pytest.raises(ExprError):
            Expr(bomb)
    assert Expr("team.tanks ** 2").evaluate({"team": {"tanks": 3}}) == 9
    # a bomb the parse lets through is refused at evaluation with its own message;
    # the wording is the platform's (macOS: 'Result too large', Linux: 'Numerical
    # result out of range'), so the test pins that a message follows the type
    with pytest.raises(ExprError, match=r"OverflowError: \S"):
        Expr("team.big ** 2").evaluate({"team": {"big": 1e200}})
    assert Expr("team.style_lean == 'dive'").evaluate({"team": {"style_lean": "dive"}}) is True


def test_a_shortfall_is_how_far_a_limit_is_from_holding():
    """0 where the expression holds; each failed comparison of numbers in a
    top-level `and` adds the distance between its sides, and any other
    failed clause adds 1 - the gradient a repair descends where the verdict
    alone is flat."""
    from inference.expr import scope
    limit = Expr("team.armor >= 10 and team.tanks == 2 and map.side == 'attack'")
    held = limit.shortfall(scope({"team": {"armor": 12, "tanks": 2}, "map": {"side": "attack"}}))
    assert held == 0
    short = limit.shortfall(scope({"team": {"armor": 7, "tanks": 2}, "map": {"side": "attack"}}))
    assert short == pytest.approx(3.0)
    worse = limit.shortfall(scope({"team": {"armor": 4, "tanks": 1}, "map": {"side": "defense"}}))
    assert worse == pytest.approx(6.0 + 1.0 + 1.0)
    assert Expr("team.a < 2").shortfall(scope({"team": {"a": 2}})) > 0      # at the edge
    assert Expr("not team.a").shortfall(scope({"team": {"a": 1}})) == 1.0
