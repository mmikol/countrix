# The playbook tab

The playbook is the set of rules Countrix scores with on top of the
default engine: one short file a rule, in `inference/strategies/`. The
playbook tab shows every rule as a card and lets you weigh each one for
your own session.

![The playbook tab: the meta card with its Meta and swap cost sliders, then the rules' cards, each heuristic with its weight slider](img/playbook-tab.png)

## The kinds of rule

- **Constraints**, the limits, cut the space: every six must keep them -
  *A six always fields a tank*. A limit weighs nothing.
- **Heuristics** weigh the sixes the limits leave: something to have
  more or less of, or a reward or a charge under a condition, each
  times its weight - *Every six carries a save*.
- **Assumptions** are what the playbook takes as given - *All players
  play optimally*. They are shown and never scored.

The buttons at the top jump to the meta and to each group, with its
count. Each card's left edge carries its kind's colour: blue for the
constraints, green for the heuristics, sand for the assumptions. The
line under a card's name gives its form as the solver reads it: what a
limit requires, the metric a heuristic reads and which way it wants it,
or the expressions a scored rule adds and subtracts, with its weight.

## The meta and its sliders

The first card, *The meta*, is the default engine's: its file,
`meta.md`, with its four weights, its swap cost and its prose. Two
sliders sit under it.

- **meta** scales the whole default engine, 0 to 10. At 0 the playbook
  scores alone; at 1 the engine counts as calibrated; above 1 its win
  rates, synergies and counters count for more against the playbook's
  rules.
- **swap cost**, 0 to 50 share points in halves, is what a swap of one
  of blue's picks must gain before the board suggests it. At 0 the board
  suggests blue's optimal six outright.

## A rule's weight

Under each heuristic sits its weight slider, 0 to 10 in hundredths, with
a box for the exact figure and *reset*, which puts back the weight in
the rule's file. A weight of 0 silences a rule without removing it.

## What a slider changes

A slider's setting is yours alone. It stays in your browser and rides
with every board you ask for, the next one solves under it, and the
files are untouched. A reload keeps it, and *clear all* leaves it alone.
A setting for a rule the playbook no longer holds is dropped when the
tab loads.

To change a weight for good, change the file through the door:
[tuning the playbook](tuning.md).

## Its math

Each card carries an *its math* link. A rule's opens its entry on
[the registry](registry.md): what the rule does in plain words, then its
formula with its own numbers. The meta's opens the default engine on
[the math page](math.md).
