# The registry

The strategy registry writes out every rule of the playbook in force as
the solver reads it. Open it from the board's header, *the registry*, or
at http://localhost:8017/registry. The page is built from the code each
time it loads, so it says what the solver runs.

![The registry: the score's formula, then the limits, heuristics and assumptions, a table each](img/registry.png)

## The tables

The page opens with the score's formula and the playbook's count, then
one table a kind:

- **Limits** - each rule and what it requires, such as
  `team.tanks >= 1`.
- **Heuristics** - each rule, its form, its weight, the most it can move
  a six's score, and who settles its condition, its *gate*.
- **Assumptions** - each rule's name.

A heuristic takes one of three forms:

| form | what it does |
| --- | --- |
| reward | pays more the more (or the less) of a metric the six has, up to its weight |
| need | charges a six that falls short on a metric, up to its weight, where the six's own makeup calls for it |
| scored | adds its weight times a bonus less a penalty, two expressions over the facts |

Who settles a gate:

| gate settled by | means |
| --- | --- |
| none | the rule always counts |
| the board | the draft decides - the map, the stage, the side or red's picks |
| the six | the six's own makeup decides, as a brawl six's need for healing |

## A rule's entry

Click a rule - its row in a table, or a rule another entry names - and
its entry opens over the page:

- what the rule does, in plain words;
- its formula, with its own numbers and dials filled in;
- each metric it reads: what it means and how it adds up over the six;
- its prose, from its file;
- its sources, from the playbook's citation record.

![A rule's entry open in the registry's dialog over the tables](img/registry-dialog.png)

The page behind stays where it was. The address names the open rule -
`/registry#heal-rate` - so you can bookmark it or send it; opening that
address opens the rule. A rule opened from inside an entry takes its
place.

- Close the entry with Esc, its close button, a click outside it, or the
  browser's Back.
- Ctrl-click or Cmd-click a rule to open it in a new tab, open there.
- Space and the arrow keys scroll a long entry.
- With scripts off, and in print, every entry shows under the tables.

Each entry links its form's section of [the math page](math.md), which
gives the forms in general. The playbook tab's *its math* links land
here, each on its own rule.
