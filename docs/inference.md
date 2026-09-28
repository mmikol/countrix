# The INFERENCE LAYER - `inference/`

Facts in, the optimal composition out. The layer owns the right-hand
side of the equation in [architecture.md](architecture.md):

```
STRATEGIES = CONSTRAINTS ∪ HEURISTICS ∪ ASSUMPTIONS   the playbook: markdown files in strategies/
COMP       = ARGMAX[ STRATEGIES( FACTS ) ]  the solver searches; the agent argues
```

Two things infer:

- **The solver**: deterministic arithmetic. It reads the strategy files'
  frontmatter, scores six after six with the facts layer's metrics, and
  returns the best of every legal six, exactly ([The search](#the-search)).
  No model, no API, and no randomness but the reference sample's seeded
  draw. It cannot read prose.
- **The agent**: a Claude Code session on the `/comp` skill. It reads the
  same facts and the prose of the same strategies and reconciles them
  where arithmetic cannot. It runs when you ask it to, never on its own,
  on your subscription.

One input is written by hand: the playbook, which the solver reads. A pull
tool fills every other table. The shipped playbook is six assumptions, one
heuristic, `heal-rate`, scored ([The healing floor](#the-healing-floor)),
and one limit, `at-most-three-supports`, while it is rebuilt from the
citations in [inference/README.md](../inference/README.md); the default
engine scores every board beneath it ([The objective](#the-objective)).
The solver tests run on the reference playbook in
[tests/fixtures/playbook/](../tests/fixtures/playbook/), which holds a
file of every form but the draft. The package's map is the
[inference/__init__.py](../inference/__init__.py) docstring, and each
module's docstring holds its detail.

## How a six is chosen

A six is chosen by inference on maxims and facts. The maxims are the
playbook, rules in markdown a person reads and turns; the facts are the
data, what the database holds about the board. Together they make one
objective, weighted and constrained, and the solver solves it exactly:
the six it returns is the best of every legal six under that objective,
proved, and not the best a search happened to meet. Five steps, in order:

```
space  = every six of released, unbanned heroes that keeps the locked picks,
         each set once, grouped tank, damage, support; at most two tanks
legal  = the space, less every six a limit rules out           a limit weighs nothing
score  = meta x (rate x rates + synergy x synergy + counter x counters)
       + each heuristic's term, times its weight               from the same facts
COMP   = the legal six of highest score, exactly; the next best after it, in order
```

1. **The space.** A six is a set: the same heroes in another order are
   one six, held grouped as tanks, damage and supports. It keeps the
   locked picks, leaves out the banned and the unreleased, and fields at
   most two tanks, the queue's own limit. Today's 53 released heroes -
   15 tanks, 24 damage, 14 supports - make 22,957,480 sixes, and
   18,040,386 of them field two tanks or fewer.
2. **The limits prune.** A constraint is a limit: it removes every six
   that breaks it and adds nothing to one that keeps it. The shipped
   playbook's one, `at-most-three-supports`, removes 822,822 sixes and
   leaves 17,217,564 legal on an open board, about 17.2 million. A ban
   or a locked pick leaves fewer: four bans on Ilios leave 10,572,870,
   two locked picks on King's Row 163,242. Blue's own comp that breaks
   a limit is not allowed; red's revealed picks are facts, and never
   ruled out ([The share](#the-share)).
3. **The meta scores.** The default engine reads three things off the
   facts and scores every legal six: each pick's win-rate edge over 50
   on the map, trusted by its pick rate, so a rarely picked hero's edge
   counts for less; the wiki's synergy scores among the six, a pair
   neither article writes read at the written pairs' mean, as unknown
   and not as zero; and the counter graph against the other side's
   locked picks, else its likely six - the wiki's edges and, where the
   wiki has none, answers derived from the kits. `meta.md`'s `meta`
   weight scales the three together: 1 is the engine as calibrated, and
   0 leaves the playbook alone ([The objective](#the-objective)).
4. **The heuristics adjust.** Each heuristic reads the same facts,
   through the metric functions the board words as facts, and adds or
   subtracts, times its weight: a metric normalised to 0..1 on the
   board's scale, or a bonus less a penalty where its `when` holds
   ([How a strategy file works](#how-a-strategy-file-works)). The
   shipped playbook's one, `heal-rate`, charges a six that heals less
   than the other side's rate up to its weight, 2 ([The healing
   floor](#the-healing-floor)).
5. **The argmax.** The search returns the legal six of highest score,
   proved by branch and bound, and the next best in rank order as the
   alternatives, five unless a caller asks for up to twenty. Ties break
   by the six's mean map win rate, then by the names, so a board has one
   answer. On an open board the search scores a few dozen sixes in full
   and proves that none of the rest can beat them ([The
   search](#the-search)). Every reason it gives cites a numbered fact
   (F1, F2, ...): each pick's reasons, and each bar of the breakdown,
   the engine's three terms among them.

**The weights are not learned.** No weight is fit to outcomes. A
heuristic's starting weight is derived from its prose on the house
scale, 0.25 a whisper, 1 the default, 2.5 strong and 4 dominant, when
`/strategy` stores it. The engine's rate weight is 1, so its term reads
in win-rate points, and its synergy and counter weights were set so that
each term spreads a typical board's sixes about half as far as the rate
term does ([The objective](#the-objective)). Every weight can be
changed: `/tune` changes a file's for good and logs why, a heuristic's
slider on the playbook tab changes it for a session, and the Meta slider
scales the whole engine ([How the weights move](#how-the-weights-move)).

**A score is not a probability.** A score is a sum of weighted terms in
the objective's own units, and signed, since the rate term counts each
pick's edge over 50. The board reads it as a share - a seat's six placed
between the seat's floor, 0, and its optimal, 100 - and the fight odds
split the two seats' shares. Neither is a fitted win probability ([The
share](#the-share)).

**The rates are a proxy.** Blizzard publishes rates for Competitive Role
Queue, 5v5, one tank a side; no source publishes Open Queue 6v6, the
mode the playbook assumes (`open-queue-ranked`). The rates stand in for
it, for direction and not for decimals, and a value a hero has only
beside a second tank is missing from them: Zarya's, in a two-tank front
line, is the plain case. The kit is read in 6v6
([architecture.md](architecture.md#the-scope)); the rates cannot be.

**Why it is built this way.** Each step is one of the owner's rules, and
each rule's reasons are below. Constraints prune and never weigh, so a
rule either forbids a six or prices it, and a price is always a
heuristic's ([How a strategy file works](#how-a-strategy-file-works)).
Every weight is the playbook's and one meta scales the engine, so no
weight hides in code ([Why the weights are the
playbook's](#why-the-weights-are-the-playbooks)). An unwritten synergy
pair is unknown, not zero, so a new hero is not charged for being new
([Why an unwritten synergy pair is not
zero](#why-an-unwritten-synergy-pair-is-not-zero)). The search is exact
over every legal six, with no per-role shortlist deciding who can
appear ([Why the search is exact](#why-the-search-is-exact)). Written as
one pipeline, a board can be checked step by step: the space is
counted, the limits are named, every term is a bar with the fact it
read, and the argmax is proved.

## The objective

The solver maximises one number per six, the default engine's terms
first and the playbook's on top:

```
score(six) = base(six) + the playbook's terms (How a strategy file works)
base(six)  = meta x (rate x rates + synergy x synergy + counter x counters)
```

`base` is the default engine, `inference/base.py`. It is on unless its
meta is 0 and needs no strategy, so a playbook of assumptions alone gets
the sixes its three terms favour, scored and explained:

- **rates**: each pick's all-ranks win rate on the map - its overall rate
  with no map, or no row for it there - as points over 50, times
  `p / (p + RATE_PICK_HALF)` for its pick rate `p` on the same footing,
  averaged over the six. A rarely picked hero's rate rests on few
  matches, so its edge is pulled toward a coin flip; `RATE_PICK_HALF` is set
  so that only the rarest heroes lose more than half their edge. The term is centred on 50
  and not on the reference sample's mean: the zero is the same on every
  board and needs no sample. A score is therefore signed, and a share is
  read from the seat's floor, not from zero ([The share](#the-share)).
- **synergy**: `team.synergy_score`, the wiki's synergy scores among the
  six: 2 for a pair both heroes' articles claim, 1 for a pair one claims,
  0 for a pair an article writes off, and for a pair neither article
  writes a cell for, the mean score of the pairs one does, computed at
  load ([Why an unwritten synergy pair is not
  zero](#why-an-unwritten-synergy-pair-is-not-zero)).
- **counters**: the counter graph between the six and the other side,
  the weight of its answers less the weight of its exposures. A wiki
  edge, from the Match-Up tables or the Strategy sections, weighs 2.
  Where the wiki has no edge either way, `facts/counters.py` derives
  answers from the kits at load: thirteen mechanisms (anti-air, a flier,
  barrier piercing, anti-heal, burst, control, a projectile eater and a
  weapon it cannot take, armor, dive, saves, reach, tank-busting) score
  every ordered pair of released heroes, and each loser's six best
  answers, scoring 0.5 or more and more than the reverse, weigh 1 each.
  The other side is its locked picks, or, with none, its likely six on
  this map past the bans (`compute.expected_picks`, the six the board's
  red panel shows); either seat reads the other the same way. Only this
  term reads the likely six or a derived edge: the `team.*` and `enemy.*`
  counter metrics read the wiki's graph against the picks. The board
  names every derived edge it counts with the mechanism and the numbers
  that fired.

The weights are the playbook's. `meta.md`, beside the strategy files,
holds four numbers, each within 0..10: `meta`, which scales the whole
engine, and under it `rate`, `synergy` and `counter`, each term's points
per unit. The shipped file sets 1, 1, 0.1 and 0.05. `rate` is 1, so the
rate term is in win-rate points; `synergy` and `counter` were set so that
each term's median spread across a board's reference sample is about
half the rate term's, about 2.1 points on a typical board; the module
docstring holds the calibration. Reading an unwritten synergy pair at the
mean narrowed the synergy score's median range from 21 to 12.8, so at 0.1
the synergy term now spreads about 1.3 points; the calibration's rule
would set it near 0.16, a change for the `tune` tool. A heuristic still
moves a six by its weight at most; the math page says how that compares
with the base's spread. Each term is a bar of the breakdown, with the
fact it read and its weight with the meta applied: the counter bar's fact
names the six it read.

A `BaseWeights` rides the `Brief`, and `infer`'s `base`, into every
`Objective`. Left unset it is the playbook in
force's `meta.md` (`catalog.engine_weights`), with a board's own meta
over it where the playbook tab's Meta slider sets one
(`weights=meta:<0..10>`). Every result records the weights it was scored
under (`base` in its payload, and "under the meta at" in its text), and a
recorded fixture's stamp (`base.stamp`) records them beside the
playbook's digest, which leaves `meta.md` out. A folder with no
`meta.md`, or one that breaks a rule, is a `CatalogError` wherever the
weights are read. `base.OFF`, the meta at 0, turns the engine off, and a
board is the playbook's alone, as it was before the engine had a base; a
board at meta 0 is that board, bit for bit, but for the weights its
results record. The board and the MCP tools run the playbook's weights;
the tests name the reference playbook's (`tests/fixtures/playbook/meta.md`),
so tuning the live file moves none of them, and the tests that pin the
reference playbook's sixes turn the engine off. With the engine off and
a playbook that scores nothing, every six ties at zero and a board reads
*unscored*.

### Why the weights are the playbook's

The owner's rule is that constraints prune and never weigh, and that the
heuristics and the meta carry every weight, each one his to turn. The
heuristics' weights already lived in their files; the engine's three
were constants in `inference/base.py`, where only a commit could move
them and no slider reached them. They moved into `meta.md` so that the
`tune` tool changes them as it changes a strategy's weight - validated,
documented and logged - and one meta weight was put over them so that
the whole engine can be leaned on or silenced at once, from the file for
good or from the Meta slider for a session. The shipped file holds the
calibrated values under a meta of 1, and 1.0 x w is w in floating point,
so no score moved: the pinned boards and the reach fixture's boards stand
as they were.

### Why an unwritten synergy pair is not zero

The wiki's synergy data is the Team Synergy column of each hero's
article: a cell per teammate, rated, written in prose, or left as a
placeholder. `synergies` holds the pairs an article claims, and until
2026-09-28 a pair it lacked read 0 wherever a six was scored, whether an
article had written it off ("no notable synergy", rated POOR) or no
article had written a word about it. The two are not the same, and the
second is the common case: at that day's pull, 747 of the 1,378 pairs of
released heroes had no cell in either article. The holes are not spread
evenly. The newest heroes' articles are near blank - no article writes a
pair for D.Mon or Shion, and Sierra, Venture, Emre, Freja and Hazard have
two to five written pairs each of 52, where the median hero has 24 - so
a six holding one of them read "these heroes do not work together" where
the truth was "nobody has written it down yet". The synergy term charged
the newest heroes for being new, and nothing on the board said so.

A pair neither article writes is unknown, and reads the neutral prior:
the mean score of the pairs an article does write, 1.06 at that pull (670
points of claim over 631 written pairs). `pull_synergies` records every
written cell, a claim or not, in `synergy_cells`, and the load computes
the mean from it (`facts.tables.impute_synergy`). A written "no synergy"
stays 0, and a claim stays 1 or 2. The mean is over the written pairs
alone: over all 1,378 it would be 0.49, deflated by the very zeros it
stands in for. Nor does the choice of what gets written inflate it: of
the pairs the three articles that write a cell for 40 or more teammates
write, 90% are claims, and they score 1.17 on average, above the prior.

`team.synergy_score` reads it, and with it the default engine's synergy
term and any heuristic on the score. `team.unwritten_pairs` names the
pairs, and the cohesion fact the synergy term cites names them apart
from the wiki's, with the mean they read at, so a reason never passes an
unwritten pair off as a documented one. The graph metrics -
`team.synergy_edges`, `synergy_density`, `core_size`, `isolated` and
`pairs` - count the pairs the wiki claims, and describe what is
documented; so does the other side's likely six, which adds
`SYNERGY_PULL` for each documented partner. A fixture's stamp (`base.stamp`) names the reading, so one
recorded while an unwritten pair read 0 reads as another objective.

What it moved, on the shipped playbook at the shipped weights, blue's
optimal six per map with red unrevealed: all 30 boards changed. D.Mon,
whose every pair is unwritten, gains 5 x 1.06 x 0.1 = 0.53 points on
every six he is in, and is seated on 28 maps where he was on 15; Juno,
35 of whose 52 pairs are unwritten, on 21 where she was on 1; Vendetta on
10 where he was on 2; Baptiste, 36 of whose pairs are written, on 6 where
he was on 22. Of the eleven heroes the reach fixture names unseated, ten
come closer to a seat on their two best maps with red unrevealed - all
but Zarya - and none takes one there; 34 of the fixture's 42 boards still
seat their hero. The synergy term was honest about the documented pairs
and silent about the rest; the prior makes it neutral about the rest, and
the rates and the counter graph decide between heroes the wiki has not
compared.

## The share

Each seat's optimal six is its 100, and its 0 is the seat's floor: the
lowest score among the reference sixes its scale drew (`Solver.floor`,
from `inference/scale.py`), and a fill takes its seat's. A comp's share
is its place on that span:

```
share = clamp((score - floor) / (best - floor), 0, 1) x 100
odds  = each seat's share over the two shares' sum
```

A score is signed, since the rate term counts each pick's edge over 50,
so a share read from zero put every six below zero at 0, and against a
six above zero the odds read 100 to 0. The floor puts both seats on a
real scale; a mirror still reads 50 to 50. A best no higher than the
floor leaves nothing to divide, and every comp but the optimal reads
*unscored*.

A comp the limits rule out is not allowed: blue's full six that breaks
one, or picks that no six keeping them completes within the limits (their
fill is then not solved). The fill searches every six on the roster that
keeps the picks, so a fill that ends with none is a proof, and only that
rules the picks out. Such a comp carries no score, no share and no odds,
and its breakdown keeps the limits alone; blue's optimal and red's seat
still render. The badge and the strip read `not allowed: breaks <the
limit's name>`, or, where the picks break no limit as they stand, `not
allowed: no six that keeps these picks meets the playbook's limits`. Red's
revealed picks are the other side's facts and are never ruled out.
The `infer` tool refuses such picks in the same words.

## The search

`inference/solver.py` returns the best sixes of the whole legal space:
every six of released, unbanned heroes that holds the locked picks, each
once, at most two tanks and every limit kept - 17,217,564 on an open board
under the shipped playbook. It walks that space by branch and bound. Each
legal shape is filled role by role, a role's picks at rising places of its
walk order, and a branch - the picks so far and the candidates each open
role has left - is dropped only where its bound proves that no six in it
can enter the best K. The answer is the enumeration's own, in the full
rank order, whatever order the walk takes; no hero is left out of any
role, and the alternatives are the next best sixes in that order.

The bound (`inference/bounds.py`) adds up, in the score's own order:

- the default engine's terms together: the picks' own parts and their
  pairs, then each open role's best few candidates by their own part,
  their synergy with the picks, and half their best synergies among the
  rest of the roster. Each pair among the open picks is counted from both
  of its ends, so the two halves are never less than the pair;
- each heuristic on a metric at the better end of the metric's range over
  the branch, and a need at 0 where its guard may not hold;
- each scored heuristic at its weight times the bonus's high end less the
  penalty's low end, and 0 where its `when` may not hold.

A metric's range comes from the aggregate it is - a sum over the picks, a
mean or a median of the known values, a max or a min, a product, a sum
over pairs, the enemies answered, the distinct subroles, or fixed by the
shape - and every team and matchup key has its rule. An expression's
range comes from its tree: an operator takes its operands' ends, a
comparison is true, false or either, and `and`, `or` and `if` join the
values they can take. A limit false on every six of a branch drops it. A
metric the bound sums in another order than the metric itself carries a
slack, `SLACK` (1e-12) per unit of its addends, outward on both ends; one
of whole numbers carries none, so a threshold on a count reads exactly.

Sixes rank by `scoring.rank_key`: the score rounded to `SCORE_PLACES` (9)
decimal places, then the six's mean map win rate, then the names. The
rounding makes a plateau finite: with the engine off, the healing floor
scores every six that heals enough exactly 0, and the tie-break's own
bound, the best mean map win rate a branch can reach, settles which of
them lead. Each six is scored in one seat order - tanks, then damage, then
supports, each by hero id - so its score is a function of its heroes to
the last bit, and a board is the same payload under any hash seed.

A full six's rank counts the legal sixes whose rounded score beats its
own: read off the seat's search where the six reaches its best K, counted
by a search of its own where it does not, exact up to `RANK_CAP` (100);
past it the six reads outside the top 100. A search past `NODE_BUDGET`
branches or `SCORE_BUDGET` sixes scored in full raises `Unbounded`, a
refusal: the answer is exact or refused, never a guess. A search that ends
with no six proves that none exists, so blue's picks a fill finds nothing
for are not allowed. Every search runs in the calling process, one after
another; a board asks its client's lane (`inference/supersede.py`) every
`CHECK_EVERY` branches whether a newer board replaced it.

The suite holds the search to enumeration:
`test_the_search_reaches_the_enumerated_maximum` and its neighbours in
`tests/inference/test_solver.py` compare the best sixes, the score floats
and the ranks with a full enumeration's on synthetic boards - both seats,
the fill, the countered case, bans, locks and plateaus - and
`tests/inference/test_bounds.py` holds every rule and the whole bound to
every completion of random branches. On the built database,
`python -m tests.inference.prove_exact` brute-forces every legal six of a
real board, in slices, against the search.

### Why the search is exact

The owner's rule: the solver optimises exactly over the whole legal
space - every six, duplicates removed, at most two tanks, the playbook's
limits - and no per-role shortlist may restrict which heroes can appear.
The search it replaces kept each role's six highest-standing heroes,
swept the 13,101 sixes they allow, then climbed from the best of them by
local search over the whole roster. It scored about 14,500 of 17 million
sixes, and its answer was the best it met, not the best there is. On Samoa
against D.Va, Roadhog, Sombra, Lúcio and Brigitte the investigation that
led here found it returning a two-one-three at 3.8673 where a two-two-two
scored 3.8885: the shape it needed was never searched from a good start,
and no pool size could promise it would be.

Replayed on that data, the old search still answers the two-one-three
and the exact one the two-two-two at 3.8885, the same float a brute force
of all 17,217,564 legal sixes found. On today's data, where an unwritten
synergy pair reads the written pairs' mean, the old search happened to
find the best six on each of 126 boards tried - every map against red's
likely six, 90 seeded boards of random reds and bans, and six boards
brute-forced in full - so its misses were rare, and nothing said when one
happened. The exact search proves its answer, and costs less: 0.08 s a
search against the old 2.3 s in one process, and a whole board
0.19-0.33 s in one process against 1.1-3.7 s on twelve workers and
3.8-11.2 s without them.

Exactness retires what served the approximation: the process pool, its
rounds and the two settings that sized it; the per-role pool and the
`pool` knob of `infer`, `board` and `/api/board`; the field budget that
held the swept fields in memory; and the check that tried the roster when
the pools found no fill. `top` is the one knob left, and it buys the next
best sixes in order.

## How a strategy file works

Drop a markdown file into `strategies/` and it is live: the solver reads
the directory on every call, the board's playbook panel shows it, the
`strategies` tool serves it, and `load_authored` mirrors it into the
`strategies` table. Three markdown files there are no strategy:
`README.md`, `tuning-log.md`, and `meta.md`, the default engine's weights
([The objective](#the-objective)), whose name no strategy may take. The
frontmatter is the whole contract:

```markdown
---
name: Answer every revealed enemy
kind: heuristic
category: matchup
direction: maximize
metric: team.coverage_share
weight: 3
when: enemy.size >= 1
---
# Answer every revealed enemy
The share of revealed enemies at least one of our picks answers...
```

That is the reference playbook's `coverage.md`, cut short. A `#`
comment takes a whole line: after a value, it is read as part of the
value.

| kind | form | frontmatter | what the solver does |
| --- | --- | --- | --- |
| constraint | limit | `require: <expr>`, any threshold it reads under `params:`, and nothing weighted | discards a candidate that fails; never scores |
| heuristic | heuristic | `metric`, `direction` (`maximize` or `minimize`), `weight` | normalises the metric to [0, 1] on the board's scale (flipped for minimize) and adds `weight x norm` |
| heuristic | scored | `bonus: <expr>` and/or `penalty: <expr>`, `weight` | adds `weight x (bonus - penalty)` |
| assumption | | nothing: prose by definition | nothing: the solver takes it as given and the agent holds a comp to it |
| constraint or heuristic | draft | name, kind and prose only | nothing yet: shown and served until `/strategy` infers the rest or turns it into an assumption |

Constraints cut the space; heuristics weigh what is left. A constraint
always holds and is never weighted: it carries no `when`, `bonus`,
`penalty`, `metric`, `direction` or `weight`, and anything weighted is a
heuristic. A rule that should cost rather than forbid is a
scored heuristic, `when: not (<the rule>)` with its `penalty`; `soft:`
is refused, and so is any key that is not a field. A heuristic weighs a
metric or an expression, never both, and takes an optional `when` guard,
applying only where it holds. A heuristic on a metric guarded on the
six's own state (`team.*` or `matchup.*`) is a need: it adds
`weight x (norm - 1)`, so met it costs nothing and unmet it costs its
weight, and the needs on one guard cost `NEED_BUDGET` (2) together at
most. The scale is a seeded
sample of 1200 legal sixes plus the field of each role's top six by the
board's prior (`inference/scale.py`).

A strategy's prose is three sentences at most (`add_strategy` refuses
more): the claim, why and when, what is measured.

Expressions are a whitelist, compiled once and validated against the
metrics registry when the catalog loads: the `team`, `enemy`, `matchup`,
`map`, `world` and `params` sections, arithmetic, comparisons, `and`,
`or`, `not`, `x if c else y`, and `min`, `max`, `abs`, `round`, `len`,
`int`, `float`, `bool`. A key that is not in the registry, or a
`params.NAME` not declared under `params:`, is refused at load, so a typo
never scores silently. A key a section lacks reads 0, and a division,
floor division or remainder by zero reads 0 for that operation alone.
`params:` (an indented block of NAME: number) are the dials an expression
reads as `params.NAME`. Every key a strategy may reference is in the
vocabulary generated at the end of this document.

The solver never infers a formula or a weight from prose; a model does.
The `/strategy` skill turns a name, a kind and up to three sentences into
frontmatter, or into `kind: assumption` where nothing is measurable, and
stores it through `add_strategy`. A file dropped in with only a name, a
kind and prose is a draft, which the solver ignores until `/strategy`
completes it through `infer_strategy`. No API key anywhere.

## How the weights move

The default engine's weights are `meta.md`'s, and the `tune` tool moves
them: `{"id": "meta", "field": "synergy", "value": 0.2, "reason": ...}`,
the field one of `meta`, `rate`, `synergy` and `counter`. The board's
sliders override a weight for one board - `weights=<id>:<0..10>` on
`/api/board`, `weights` on the `board` tool - the Meta slider among them
as `meta:<0..10>`, and every result names the weights it was scored
under; the board writes none of them. Three tools write a strategy file -
`tune`, `add_strategy` and `infer_strategy` - and `tune` writes
`meta.md`, each validated through the catalog before it writes and
logged with its reason in `strategies/tuning-log.md`.

## Sustained healing

`hero.hps` is the healing a hero lands on teammates a second, summed over
every teammate each piece reaches and over every piece that runs beside
the others. The caster's own healing is out. `facts/scalars.py` derives
it from the kit rows at load and keeps each piece's share in
`hero.hps_pieces`; `team.hps_floor` sums `hps` over a six.

- **R1 The weapon.** The best healing weapon at its published rate, the
  reload in, onto one target. A beam's heal row sets its rate before the
  hps field (Mercy: 55, where the field says 60).
- **R2 A cast.** Heal per cast x teammates reached / cycle. The cycle is
  the cooldown, and the cooldown plus the duration where the effect is
  held or deployed and the page does not say the cooldown starts on use
  (`HELD`). Of two instant figures under different conditions the smaller
  counts: the larger is conditional (120 at low health).
- **R3 A resource.** A beam that spends energy fires until x% is spent,
  waits out the regen delay and regenerates, at the x that heals most
  (`energy_duty`). A heal that lingers after the beam counts in the off
  time; a refund of the energy is more beam time.
- **R4 Reach.** An area heal counts the teammates the formation puts in
  its radius, at most five.
- **R5 Beside the weapon.** A piece the weapon cannot run beside is out
  (Lifeline ends on primary fire). A channel that holds the weapon takes
  its time off the weapon (the Pulsar Torpedoes lock).
- **R6 Out.** Ultimates, perks, self-healing, overhealth, healing
  amplification (`hero.heal_amp` carries it) and saves with no heal
  figure (Immortality Field, Resurrect).
- **R7 The tick.** Where a heal row's tick disagrees with its per-second
  figure, the tick sets the rate: Wuyang's stream ticks 25 and 50 where
  its rows read 20 and 55.

**The formation.** The six stand spread uniformly over a disk of radius
R = `FORMATION_RADIUS`. With s = r / R, the chance two of them stand
within r of each other is the disk's distance distribution:

```
p(r) = 1 + (2/pi)(s^2 - 1) acos(s/2) - (s/(2 pi))(1 + s^2/2) sqrt(4 - s^2)    s < 2, else 1
around the caster      reach = 5 p(r)
on an aimed teammate   reach = 1 + 4 p(r)
hps                    = sum over the counted pieces of heal x reach / cycle
```

At R = 15, p(12) = 0.426: Crossfade's 18/s on a 12 m radius heals 2.13
teammates, 38.36 hp/s.

**The constants.** Every radius, cooldown, duration and energy rate is
the wiki's. The judgements sit in `facts/scalars.py` beside their pages:

| Constant | Value | Its page and reason |
|---|---|---|
| `FORMATION_RADIUS` | 15 m | the shortest single-target heal range among the supports (Caduceus Staff, Biotic Grasp, Healing Pylon); the wiki gives no fight size. Two teammates stand 13.6 m apart on average |
| `PYLON_UPTIME` | 1/3 | Illari: the pylon lives one 7 s cooldown, then the 14 s destroyed one |
| `TORPEDO_VIEW` | 0.5 | Juno: no target cap; half the teammates past the aimed one stand in front of her |
| `LOCK_NEAR` | 5 m | Juno: the lock takes 0.35 s at 5 m, 1 s at the 40 m targeting range |
| `SPRAY_TARGETS` | 1 | Moira: "all allies in front", width unpublished |
| `FLAIL_CONTACT` | 1 | Brigitte: the Flail lands throughout, as `hero.dps` holds every weapon on |
| `INSPIRE_LOCKOUT` | 1.25 s | Brigitte: Inspire fires on every third 0.6 s swing, once each 1.8 s |
| `EMPTY_WAIT` | 0.4 s | Illari: an emptied bar waits before it recharges |
| `TICK_RATES` | 25 + 50 | Wuyang: the stream's tooltip ticks, the passive one free |
| `ENERGY_REFUND` | 33% | Wuyang: Guardian Wave refunds the stream's resource |

`HELD`, `CASTER`, `AIMED`, `NOT_BESIDE`, `OWN_HEALS` and `BOOSTS` name the
pieces the wiki has no field for. Mauga's Cardiac Overdrive heals the
teammates 50% of the damage they deal: `facts/tables.py` reads that at
the 2-2-2 role-median dps of his five teammates, 94.29, once the roster's
dps is known.

The 6v6 kit as of 2026-09-26:

| Hero | hps | The pieces |
|---|---|---|
| Baptiste | 111.76 | Biotic Launcher splash 94.00, Regenerative Burst 17.76 |
| Juno | 107.59 | Mediblaster 75.28, Pulsar Torpedoes 32.31 |
| Jetpack Cat | 99.18 | Biotic Pawjectiles 87.18, Purr 12.00 |
| Brigitte | 98.36 | Inspire 73.36, Repair Pack 25.00 |
| Ana | 92.72 | Biotic Rifle 83.33, Biotic Grenade 9.39 |
| Kiriko | 81.50 | Healing Ofuda 74.34, Protection Suzu 7.16 |
| Illari | 70.07 | Solar Rifle beam 53.41, Healing Pylon 16.67 |
| Mizuki | 69.79 | Remedy Aura 38.36, Healing Kasa 31.43 |
| Moira | 69.40 | Biotic Grasp 49.40, Biotic Orb 20.00 |
| Lifeweaver | 60.35 | Healing Blossom 56.18, Life Grip 4.17 |
| Mercy | 60.00 | Caduceus Staff 55.00, Flash Heal 5.00 |
| Lúcio | 54.56 | Crossfade 38.36, Amp It Up 16.20 |
| Wuyang | 48.07 | Restorative Stream 41.41 (the wave's refund 3.54 in), Guardian Wave 6.67 |
| Zenyatta | 35.00 | Orb of Harmony 35.00 |
| Mauga | 16.32 | Cardiac Overdrive 16.32 |
| Soldier: 76 | 4.77 | Biotic Field 4.77 |

Every other released hero heals no teammate. `world.hps_bench`, twice
the median support, is 139.87: Illari and Mizuki.

## The healing floor

`heal-rate`, the shipped playbook's one heuristic, scored, holds a six to a
healing threshold set by the kit. It reads `matchup.heal_shortfall`;
`facts/compute.py` computes it and `matchup.heal_need` (`heal_read`,
`heal_need`, `heal_shortfall`), and the board words both in one fact.

The model is a race. A six has a pool P (`team.pool_total`: health,
shield, armor and a form's armor), damage D (`team.dps_floor`) and
healing onto teammates H (`team.hps_floor`, reloads in): an area heal
counts the teammates it reaches and a beam what its resource sustains
([Sustained healing](#sustained-healing)). Each side's damage lays the
same anti-heal k on the other's healing, so blue
loses (D_r - k H_b) / P_b of its pool a second and red
(D_b - k H_r) / P_r. Blue wins the race when red loses the larger share,
and the margin splits in two:

```
margin = [D_b / P_r - D_r / P_b]  +  k [H_b / P_b - H_r / P_r]
          the damage half             the healing half
```

The damage half is 1/`chew_time_ours` - 1/`chew_time_theirs`. The healing
half breaks even when blue heals the same share of its own pool a second
as red heals of its own, and k cancels there. That share times blue's
pool is the need, floored at red's healing in full:

```
need      = max(H_r, H_r / P_r x P_b)
shortfall = max(0, need - H_b) / need         0 when need is 0
charge    = 2 x shortfall                     heal-rate's weight
```

The floor is there because parity alone asks less healing of a smaller
six, and the race never rewards a smaller pool: its margin rises with
P_b. Under parity alone the engine drops a tank to slip under the bar;
the floor stops that. The margin also rises with every support added, so a rule
that maximised healing would drive toward five supports; a floor does not.

**Red as read.** Red's locked picks, and each open slot a role the 2-2-2
(`EXPECTED_SHAPE`) still misses: d_r = max(0, 2 - red's count in r),
spread over the open slots as f = open / sum(d_r), each missing seat at
its role's median pool (`World.pool_medians`, a form's armor in) and a
missing support at half `world.hps_bench`, the median support's healing:

```
H_r = enemy.hps_floor  + f x d_support x hps_bench / 2
P_r = enemy.pool_total + f x sum over r of d_r x pool_medians[r]
```

A red that has shown its two supports reads as two, not as two and a
share of a third. A complete red that heals nothing needs nothing. The
likely six is not read: it rests on pick rates.

**The threshold.** With red empty, red is the 2-2-2 of role-median
heroes: H_r = `world.hps_bench` = 139.87 hp/s and P_r = twice the sum of
`World.pool_medians` = 2 x (525 + 250 + 237.5) = 2025, the 6v6 kit as of
2026-09-26. A six must heal 6.91% of its own pool a second, and never less
than 139.87 hp/s. Everything in it is kit data; no rate enters. The
sources hold no absolute winning threshold - no fight length, no ultimate
charge - so the rule promises parity with the other side's healing and
nothing more. At parity the race is the damage half's, which no shipped
rule prices.

**What it moves.** A six with one support falls under the bar against
any red that heals, so the engine answers with a second support and keeps
a third only where the pair heals little. Within a board the shortfall
mostly follows the support count; the rest is how much the pair heals,
which a count would miss. The weight, 2, sets a six at full shortfall
beside the synergy and counter terms, each of which spreads a typical
board's sixes a point or two ([The objective](#the-objective) has the
figures).

**What it inherits.** The bar is only as good as `hps`, and a
World-wide error cancels, since the bench moves with it; an error on one
hero does not. Three limits stand:

- *The bench is a step.* Its median pair, Illari 70.07 and Mizuki 69.79,
  sits with Moira 69.40 inside 0.7 hp/s, each set by a different
  judgement (the pylon's uptime; R and the full aura; the spray's
  reach). One of them past Kiriko lifts the bench to about 151.
- *Overheal is out.* An untargeted area heal lands on full-health
  teammates too, where a single-target healer picks a hurt one; the
  sources give no overheal share, so the rule favours the area heal by
  that margin.
- *Brigitte rests on the Flail.* Her 98.36 holds the Flail in contact
  throughout; at half contact Inspire gives 36.68 and she reads 61.7.

Perks, ultimates, self-healing and health packs are out, on both sides
alike. Over 126,900 uniform random sixes against random reds, a
six with one support is under the floor 90% of the time, with two 39%,
with three 7%.

## The catalog

<!-- generated:catalog -->
8 strategy files in `inference/strategies/`: 1 constraint (a limit), 1 heuristic (0 on a metric, 1 scored) and 6 assumptions. Regenerated by `.venv/bin/python -m door.mcp call db_docs`.

#### The meta

`meta.md`: meta 1 x (rate 1, synergy 0.1, counter 0.05) - the default engine's weights, which the tune tool changes (id `meta`)

The default engine scores every six before the playbook's rules do: each pick's win rate on the map, trusted by its pick rate (rate), the wiki's synergy scores among the six (synergy), and the counter graph against the other side (counter). The meta scales the three together - 0 is the playbook alone, 1 the engine as calibrated - and the board's Meta slider sets it for a session without touching this file. Rate is 1, so its term is in win-rate points, and synergy and counter are set so that each term spreads a typical board's sixes about half as far as the rates do.

#### Constraints

##### Never more than three supports (`at-most-three-supports`, shape, limit)

`require team.supports <= params.MAX_SUPPORTS` - always holds
params: MAX_SUPPORTS=3

A six fields at most three supports, on every board. Open Queue sets no cap on supports, so this rule sets one: a six with a fourth support is never chosen. Measured as the six's support count.

#### Heuristics

##### Heal at the other side's rate (`heal-rate`, sustain, scored)

weight 2; penalty `matchup.heal_shortfall`

A six heals at least the share of its total health that the other side heals of its own each second, and never less than the other side's healing in full; an unrevealed slot on that side is the 2-2-2 shape's missing role at the role's median pool and healing. With damage anti-heal on both sides, the healing half of the race between the two sixes breaks even at that share, and nothing in the kit sets a higher bar. The charge is the weight times the share of the need left unhealed.

#### Assumptions

##### This is Open Queue Ranked (`open-queue-ranked`, assumptions)

*assumption* - prose the solver takes as given and the session holds a comp to

The mode is Competitive Open Queue, 6v6: six picks per side in any mix of roles under the queue's own limit of two tanks. Rules written for Role Queue's 2-2-2 or for Quick Play do not bind here. Nothing is measured; the shape rules read from this.

##### All players play optimally (`players-play-optimally`, assumptions)

*assumption* - prose the solver takes as given and the session holds a comp to

Every player on both teams plays their hero as well as it can be played. A strategy therefore encodes the game - kits, ranges, cooldowns, maps, roles - and never a lobby's habits or a rank's tendencies. Nothing is measured; the session holds every comp to it.

##### Console only (`console-only`, general)

*assumption* - prose the solver takes as given and the session holds a comp to

The owner plays on console, and the playbook is built for console play. The rates are the console pull, the recorded maps are console maps entered by hand, and no PC-only feature such as the Workshop Inspector log is assumed. Nothing is measured.

##### The rates are a console pull (`console-pull`, uncertainty)

*assumption* - prose the solver takes as given and the session holds a comp to

The pick, win and ban rates the board reads were captured for console play, not PC. A comp is built for console hands, and a PC figure is never assumed in its place. Nothing is measured.

##### Not rank specific (`rank-agnostic`, uncertainty)

*assumption* - prose the solver takes as given and the session holds a comp to

The playbook applies at every rank alike: the rates are the all-ranks figures and no rule turns on a rank. A hero whose value swings by rank is noted as uncertainty, never as a rank's rule. Nothing is measured.

##### Region agnostic (`region-agnostic`, uncertainty)

*assumption* - prose the solver takes as given and the session holds a comp to

The playbook applies in every region alike. The rates it reads are one region's capture, a stated proxy for direction and never for decimals, and no rule turns on where a match is played. Nothing is measured.

#### The vocabulary

Every key a strategy may reference, with its meaning. `enemy.*` are
the `team.*` metrics computed for the red side.

| key | meaning |
| --- | --- |
| `team.size` | picks locked on this team |
| `team.open_slots` | slots still open (6 - size) |
| `team.tanks` | tank count |
| `team.damage` | damage count |
| `team.supports` | support count |
| `team.subrole_diversity` | distinct subroles / size (1.0 = every pick a different job) |
| `team.subroles` (text) | the subroles present |
| `team.shape_flags` (text) | TANKLESS / double tank / triple DPS / NO SUPPORT / solo heal |
| `team.style_counts` (text) | picks per playstyle tag (a hero can carry several) |
| `team.style_top` (text) | the modal playstyle among the picks |
| `team.style_lean` (text) | the playstyle a strict majority of picks carry, else none |
| `team.style_fit` | share of picks tagged with the map's rewarded style (0 without a map) |
| `team.shape_excess` | picks over EXPECTED_SHAPE's two per role |
| `team.pool_total` | team effective HP: sum of health + shield + armor, plus a form's armor by its uptime |
| `team.pool_min` | the weakest pick's pool - focus fire finds the minimum |
| `team.weakest` (text) | who holds the smallest pool |
| `team.armor_total` | summed armor, a form's by its uptime |
| `team.armor_share` | armor / pool |
| `team.shield_total` | summed recharging shields |
| `team.shield_share` | shields / pool |
| `team.squish_count` | picks at or under 250 pool |
| `team.squishies` (text) | the picks at or under 250 pool |
| `team.overhealth_total` | summed peak overhealth a kit can grant |
| `team.dps_floor` | summed published per-second damage figures (a floor: misses and healing ignored) |
| `team.dps_count` | picks whose kit publishes a per-second damage figure |
| `team.burst_max` | the biggest single hit on the team, a headshot where one counts |
| `team.one_shots` | picks whose biggest hit, not a melee swing, kills a 250-pool hero |
| `team.burst_hero` (text) | who holds the biggest single hit |
| `team.burst_ranged` | the biggest single hit from a pick that is not melee-only |
| `team.ult_damage_total` | summed max damage across the team's damage ultimates |
| `team.dmg_ults` | ultimates that carry a damage figure |
| `team.ult_cost_mean` | mean ultimate charge cost where published |
| `team.hitscan` | picks with a hitscan weapon or ability |
| `team.hitscan_reach` | hitscan picks whose weapon publishes a reach of 30 m or more |
| `team.projectile` | picks whose weapons are projectile |
| `team.beam` | picks with a damaging beam |
| `team.melee` | picks with a melee weapon |
| `team.aoe_count` | kit pieces tagged area of effect or shockwave |
| `team.aoe_damage_count` | kit pieces that damage an area |
| `team.range_known` | picks whose weapons publish a range: the three below read these alone, and read 0 where none does |
| `team.range_median` | median of each pick's longest published range |
| `team.range_max` | the longest range on the team |
| `team.range_min` | the shortest longest-range |
| `team.dmg_amp` | picks that amplify someone's damage |
| `team.hps_floor` | summed sustained healing onto teammates, hp per second over every teammate reached, reloads in |
| `team.heal_peak_total` | summed biggest single heal per pick, its own self-heal included |
| `team.heal_peak_supports` | summed biggest single heal (one cast, hp) across the supports |
| `team.heal_peak_max` | the biggest single heal a teammate can receive |
| `team.heal_ratio` | support heal peak / the roster's two-support bench |
| `team.hps_supports` | summed sustained healing across the supports, hp per second |
| `team.hps_ratio` | support sustained healing / the roster's two-support bench |
| `team.heal_amp` | picks that amplify healing |
| `team.antiheal` | picks with anti-heal |
| `team.cleanse` | picks with a cleanse |
| `team.invuln` | picks with an invulnerability or a death-prevention |
| `team.team_cleanse` | picks with a cleanse that lands on a teammate |
| `team.team_saves` | picks with an invulnerability, death-prevention or cleanse that lands on a teammate |
| `team.lifelines` | picks carrying any healing at all, their own and lifesteal included |
| `team.cooldown_median` | median cooldown across every ability on the team |
| `team.cooldown_count` | cooldowns counted |
| `team.cc_count` | picks with crowd control (stun, sleep, immobilize, hinder, knockback) |
| `team.mobility_count` | picks with a movement or evasive ability |
| `team.flyers` | picks that fly or hover |
| `team.light_flyers` | picks that fly or hover, tanks aside |
| `team.barrier_hp` | summed barrier health the team fields |
| `team.barrier_count` | picks with a barrier |
| `team.barrier_piercers` | picks whose kit ignores barriers |
| `team.pierce_dps` | summed damage of the picks whose kit ignores barriers |
| `team.deployables` | picks with deployables |
| `team.synergy_edges` | the wiki's synergy pairs among the picks |
| `team.synergy_score` | summed synergy scores among the picks, a pair neither article writes at the written pairs' mean |
| `team.synergy_density` | synergy edges / possible pairs |
| `team.isolated_count` | picks with a documented partner somewhere and none on the team |
| `team.isolated` (text) | the isolated picks |
| `team.core_size` | largest connected group in the team's synergy graph |
| `team.pairs` (text) | the synergy pairs present |
| `team.unwritten_pairs` (text) | the pairs among the picks neither article writes a synergy cell for, read in synergy_score at the written pairs' mean |
| `team.win_mean` | mean all-ranks win rate |
| `team.pick_mass` | summed all-ranks pick rate |
| `team.availability` | chance every pick survives the ban screen: product of (1 - ban) |
| `team.map_availability` | the same from this map's ban rates (the all-ranks ban where a map publishes none; equal to availability without a map) |
| `team.max_ban_rate` | the highest ban rate on the team |
| `team.max_ban_hero` (text) | who carries the highest ban rate |
| `team.rank_sensitive_count` | picks whose win rate swings 6+ points across ranks |
| `team.trend_sum` | summed win-rate movement since the rates last changed |
| `team.map_win_mean` | mean win rate on the map (the all-ranks mean without a map) |
| `team.map_pick_mass` | summed pick rate on the map |
| `team.map_specialists` | picks running 2.5+ points over their own baseline here |
| `team.map_offmap` | picks running 2.5+ points under their own baseline here |
| `team.home_map_hits` | picks whose three best maps by rate include this map |
| `team.coverage` | enemies answered by at least one pick |
| `team.coverage_share` | coverage / enemies revealed |
| `team.unanswered` (text) | enemies no pick answers |
| `team.answer_edges` | (enemy, pick) counter edges: picks answering enemies |
| `team.exposure_edges` | (pick, enemy) counter edges: enemies answering picks |
| `team.exposed_count` | picks answered by at least one enemy |
| `team.exposed` (text) | the exposed picks |
| `team.safe_count` | picks no enemy answers |
| `team.net_edges` | answer edges minus exposure edges |
| `team.double_covered` | enemies answered by two or more picks |
| `team.banproof_coverage` | coverage recomputed without the highest-ban answerer |
| `matchup.pool_diff` | blue effective HP minus red |
| `matchup.dps_diff` | blue damage floor minus red |
| `matchup.hps_diff` | blue healing floor minus red |
| `matchup.burst_vs_heal` | blue's biggest hit minus red's biggest single save |
| `matchup.heal_vs_burst` | blue's biggest single save minus red's biggest hit |
| `matchup.chew_time_ours` | seconds of blue's floor damage to chew red's pool (999 if unknown) |
| `matchup.chew_time_theirs` | seconds of red's floor damage to chew blue's pool |
| `matchup.tempo_diff` | red median cooldown minus blue's (positive: blue cycles faster) |
| `matchup.range_diff` | blue median reach minus red's; 0 where a side's picks publish none: unknown, no gap |
| `matchup.exposure_share` | share of blue answered by red |
| `matchup.ult_answers` | blue invulnerabilities plus cleanses |
| `matchup.heal_need` | hp/s blue must heal: red's healing per pool times blue's pool, at least red's healing; red's open slots read as the 2-2-2's missing roles |
| `matchup.heal_shortfall` | share of heal_need blue's healing floor leaves unhealed, 0..1 (0 when nothing is needed) |
| `map.known` | 1 if a map is set |
| `map.sided` | 1 if the mode has an attacking and a defending side (Escort, Hybrid) |
| `map.side` (text) | this seat's side on a sided map: attack, defense, or empty |
| `map.style_top` (text) | the playstyle the map rewards most: the rates' lift plus the terrain's lean |
| `map.style_margin` | top style score minus the runner-up, in sd |
| `map.mode` (text) | the game mode |
| `map.stages` | separate arenas, one played at a time: Control's 3, Flashpoint's 5; else 0 |
| `map.phases` | named parts of one route, played in order: Hybrid's 2, an Escort map's named stretches; else 0 |
| `map.bans` | bans already made in this match: a ban rate is a risk only before them |
| `map.chokes` | chokepoints, narrow streets, corridors, tunnels, gates and doorways: the wiki article's mentions per thousand words, in sd from the mean of the maps with text (0 with no text) |
| `map.interiors` | rooms, caves and other indoor ground: the wiki article's mentions per thousand words, in sd from the mean of the maps with text (0 with no text) |
| `map.high_ground` | high ground, rooftops, balconies and other vertical ground: the wiki article's mentions per thousand words, in sd from the mean of the maps with text (0 with no text) |
| `map.flanks` | flank routes and side paths: the wiki article's mentions per thousand words, in sd from the mean of the maps with text (0 with no text) |
| `map.sightlines` | long sightlines: the wiki article's mentions per thousand words, in sd from the mean of the maps with text (0 with no text) |
| `map.open_ground` | open ground and ground said to lack cover: the wiki article's mentions per thousand words, in sd from the mean of the maps with text (0 with no text) |
| `map.hazards` | drops, pits and other environmental hazards: the wiki article's mentions per thousand words, in sd from the mean of the maps with text (0 with no text) |
| `map.cover` | cover: the wiki article's mentions per thousand words, in sd from the mean of the maps with text (0 with no text) |
| `world.heal_bench` | 2 x the median peak heal across the released supports |
| `world.hps_bench` | 2 x the median sustained healing across the released supports |
<!-- /generated:catalog -->
