"""The facts layer's tests, and stat(), a kit's stat row built by hand in the
shape the load reads it, which the scalars' tests share."""

from facts.kit import Stat


def stat(code, value, unit_num=None, unit_den=None, den=None, condition=None, text=None):
    """A stat row: its key, its value and its unit, a denominator's
    magnitude, the condition it holds under and its source text."""
    return Stat(code=code, value=value, unit_num=unit_num, unit_den=unit_den, den_value=den,
                condition=condition, text=text)
