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
tool fills every other table. The shipped playbook is eight assumptions,
thirteen heuristics - `heal-rate`, scored ([The healing
floor](#the-healing-floor)), and twelve that read the terrain of the ground
in play - and one limit, `at-most-three-supports`, while it is rebuilt from the
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
   counts for less; the wiki's synergy scores among the six, cell by
   cell, a cell no article writes read at the written cells' claim
   share, as unknown and not as zero; and the counter graph against the
   other side's
   locked picks, else its likely six - the wiki's edges and, where the
   wiki has none, answers derived from the kits. `meta.md`'s `meta`
   weight scales the three together: 1 is the engine as calibrated, and
   0 leaves the playbook alone ([The objective](#the-objective)).
4. **The heuristics adjust.** Each heuristic reads the same facts,
   through the metric functions the board words as facts, and adds or
   subtracts, times its weight: a metric normalised to 0..1 on the
   board's scale, or a bonus less a penalty where its `when` holds
   ([How a strategy file works](#how-a-strategy-file-works)). The
   shipped playbook's `heal-rate` charges a six that heals less than the
   other side's rate up to its weight, 2 ([The healing
   floor](#the-healing-floor)), and twelve more read the terrain of the
   ground in play - chokes reward crowd control, sightlines want hitscan,
   high ground rewards fliers, a payload rewards the longest gun - each
   gated where its feature stands out, 0.5 sd or more above the ordinary
   map's (a `STANDOUT` dial), or on what the ground is won on (a payload,
   a capture point), two of them also on a stage their source names.
5. **The argmax.** The search returns the legal six of highest score,
   proved by branch and bound, and the next best in rank order as the
   alternatives, five unless a caller asks for up to twenty. Ties break
   by a draw per hero seeded by the map and the side, blind to rates and
   names, so a board has one answer, and the board says how many sixes
   tie. On an open board the search scores a few dozen sixes in full
   and proves that none of the rest can beat them ([The
   search](#the-search)). Every reason it gives cites a numbered fact
   (F1, F2, ...): each pick's reasons, and each bar of the breakdown,
   the engine's three terms among them.

**The swaps.** Once blue has picks, the board asks one more question of
the same objective: which of them to trade, and for whom. The answer is
one six, the best reachable from the picks as they stand when each pick
dropped costs the swap cost - `meta.md`'s `swap`, in share points of
blue's span - searched exactly over every legal six, and the swaps are
the picks it drops matched to the heroes it takes ([The
swaps](#the-swaps)).

**The plan stage by stage.** On a map with stages the board also lays
out the map a stage at a time: each phase of a route keeps its heroes
into the next unless a swap there beats the swap cost, and each arena is
reached from the six the board suggests ([The plan stage by
stage](#the-plan-stage-by-stage)).

**The ground in play.** A board is played on the whole map or on one of
its stages - a Control or Flashpoint round, an Escort or Hybrid phase -
named by `stage` (`/api/board`, the board tools; the roster lists each
map's). The stage moves the `map.*` metrics and nothing else, and every
seat of the board plays it. A terrain feature reads the map's article,
raised to the stage's own where the stage's text names it
`STAGE_MENTIONS` (2) times or more: a stage's text can add a feature,
never drop one, since a paragraph that leaves a feature out has not said
it is absent. `map.stage` and `map.objective` (a point, a payload or a
push) say where the fight is, and `map.name` which map. The scale is
measured on the whole map, each heuristic read wherever the board
settles its gate, so every stage of a map shares one; the floor is the
stage's own. With a stage named, the facts state the ground in play
(`map.ground`), and a rule gated on the terrain cites it.

**The weights are not learned.** No weight is fit to outcomes. A
heuristic's starting weight is derived from its prose on the house
scale, 0.25 a whisper, 1 the default, 2.5 strong and 4 dominant, when
`/strategy` stores it. The engine's rate weight is 1, so its term reads
in win-rate points, and its synergy and counter weights are set so that
each term spreads a typical board's sixes about half as far as the rate
term does ([The objective](#the-objective)). Every rule's weight and
each of the engine's four can be changed: `/tune` changes a file's for
good and logs why, a heuristic's slider on the playbook tab changes it
for a session, and the Meta slider scales the whole engine ([How the
weights move](#how-the-weights-move)). What a term counts inside is its
definition and stays in code, recorded in a fixture's stamp: a derived
counter edge at half a wiki edge (`WIKI_WEIGHT` 2, `DERIVED_WEIGHT` 1),
the pick rate that halves a rate edge's trust (`RATE_PICK_HALF`), and
the budget the needs on one guard share (`NEED_BUDGET`), which no single
need's weight is ever cut below.

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
Every term's weight is the playbook's and one meta scales the engine,
so no term's weight hides in code ([Why the weights are the
playbook's](#why-the-weights-are-the-playbooks)). An unwritten synergy
cell is unknown, not zero, so a new hero is not charged for being new
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
  six, read cell by cell: a pair has two cells, one in each hero's
  article, and each reads 1 where the article claims the pair, 0 where
  it writes the pair off, and where no article writes it, the share of
  the written cells that claim, computed at load. A pair both articles
  claim reads 2, and one neither writes the written pairs' mean ([Why an
  unwritten synergy pair is not
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
per unit. The shipped file sets 1, 1, 0.26 and 0.05. `rate` is 1, so the
rate term is in win-rate points; `synergy` and `counter` are set so that
each term's median spread across a board's reference sample is about
half the rate term's, about 2.1 points on a typical board; the module
docstring holds the rule, and [Why the weights are the
playbook's](#why-the-weights-are-the-playbooks) what it measured and why
synergy moved from 0.1. A heuristic still moves a six by its weight at
most; the math page says how that compares with the base's spread. Each
term is a bar of the breakdown, with the fact it read and its weight
with the meta applied: the counter bar's fact names the six it read.

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
as they were. That first `meta.md` was written by hand, with the code
that reads it, since no tool could yet write one; `tune` with id `meta`
now seeds a playbook folder that has none from the shipped file, and its
log line says so. What a term counts inside - a derived counter edge
against a wiki edge, the pick rate that halves a rate edge's trust, the
needs' shared budget - stays in code as the term's definition: the
counter tallies stay whole numbers, which the search's exactness leans
on, and making those dials is on the backlog, the owner's call.

The synergy weight moved from 0.1 to 0.26 on the owner's word, by the
calibration's own rule. At 0.1 the synergy score's median range over a
board's reference sample was 21 while an unwritten pair read 0, so the
term spread a typical board about 2.1 points, as the counter term does
at 0.05: the counter graph's median range is 41 - the wiki's edges at 2
and the kit's fill at 1. Reading what no article writes as unknown moved
that range: to 12.8 when an unwritten pair read the written pairs' mean,
where the rule gave 0.16, and to 8.1 once each unwritten cell reads the
written cells' claim share ([Why an unwritten synergy pair is not
zero](#why-an-unwritten-synergy-pair-is-not-zero)). A blank cell now
reads close to a claim, so sixes differ less in synergy, and at 0.1 the
term would have spread them about 0.8 points - two fifths of what the
calibration aimed at, and short of what a heuristic at weight 1 moves.
The rule, measured on the 30 maps with red's likely six against the
seat, gives 2.1 / 8.1, 0.26, and the tune tool set it (`tuning-log.md`,
which also records the 0.18 the half-mean reading briefly gave). The
weight restores the term's say, not the zero's verdicts: a hero no
article writes about still reads as the written heroes do on average.

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

A pair has two cells, one in each hero's article, and a cell no article
writes is unknown. It reads the share of the written cells that claim
their pair: 0.86 at that pull, 670 claims among 779 written cells.
`pull_synergies` records every written cell, a claim or not, in
`synergy_cells`, with the article it is in, and the load computes the
share from it (`facts.tables.impute_synergy`). A cell that writes the
pair off stays 0 and a claim stays 1, so a pair reads 2 where both
articles claim it, 1.86 where one claims it and the other is blank, 1.72
where neither writes it, 1 where one claims it and the other writes it
off, 0.86 where one writes it off and the other is blank, and 0 where
both write it off: every claim raises it and every write-off lowers it.
The share is over the written cells alone. Counted over every cell of
the written pairs, a blank as 0, it would be 0.53, and over every cell
of all 1,378 pairs 0.24, each deflated by the very blanks it stands in
for. It is also the one value at which a pair neither article writes
reads what the written pairs read on average, their blank cells read the
same way - 1.72 - so a hero no article writes about is charged nothing
and credited nothing against the heroes it does. Nor does the choice of
what gets written inflate it: the three articles that write a cell for
40 or more teammates, close to every one, claim 90% of the pairs they
write.

`team.synergy_score` reads it, and with it the default engine's synergy
term and any heuristic on the score. `team.unwritten_cells` counts the
blank cells among the picks and `team.unwritten_pairs` names the pairs
neither article writes, and the cohesion fact the synergy term cites
states both apart from the wiki's pairs, with the share a blank cell
reads at, so a reason never passes an unwritten cell off as a
documented one. The graph metrics - `team.synergy_edges`,
`synergy_density`, `core_size`, `isolated` and `pairs` - count the pairs
the wiki claims, and describe what is documented; so does the other
side's likely six, which adds `SYNERGY_PULL` for each documented partner.
A fixture's stamp (`base.stamp`) names the reading, so one recorded
under an earlier reading reads as another objective.

**Why a cell and not a pair.** The first reading, of 2026-09-28, was by
the pair: a pair neither article wrote read the written pairs' mean,
1.06 (670 claims over 631 written pairs), and a written pair read its
claims. But 483 of the 631 written pairs have one cell written and the
other blank, and the pair reading counted the blank as 0. A pair an
article claims then read below a pair nobody wrote about: Ana's article
claims Cassidy and Ashe and theirs are silent, so each pair read 1,
while Ana with Tracer, which neither article writes, read 1.06. 405
pairs read that way, and 78 that one article writes off and the other
leaves blank read 0, though half of each is unknown. The mean itself
counted those blanks as 0. A review proposed reading each blank cell at
half that mean, 0.53, which keeps 1.06 for a pair neither article
writes; but the written pairs would then read 1.47 on average against
that 1.06, and the heroes no article writes about would be charged
again, less than a zero charged them. Read at the claim share, Ana with
Cassidy or Ashe reads 1.86 and Ana with Tracer 1.72.

What each reading moved, on the shipped playbook, blue's optimal six per
map with red unrevealed. The pair reading, at synergy 0.1, changed all
30 boards: D.Mon, whose every pair is unwritten, gained 5 x 1.06 x 0.1 =
0.53 points on every six he was in, and was seated on 28 maps where he
had been on 15; Juno, 35 of whose 52 pairs are unwritten, on 21 where she
had been on 1; Vendetta on 10 where he had been on 2; Baptiste, 36 of
whose pairs are written, on 6 where he had been on 22. Of the eleven
heroes the reach fixture then named unseated, ten came closer to a seat
on their two best maps, and 34 of the fixture's 42 boards then still
seated their hero. The cell reading with synergy at 0.26 changed 19 of
the 30 boards from the pair reading's: Juno is seated on 11 maps where she
was on 21, Baptiste on 12 where he was on 6, Reinhardt on 16 where he
was on 11, D.Va on 1 where she was on 6, and D.Mon on 27 where he was
on 28. The reach fixture, recorded again, then seated 49 of
the 53 released heroes, as before, and the same four stayed unseated;
under the half-mean reading at 0.18 it would have seated 47, Kiriko in
and Cassidy, Hazard and Shion out. The synergy term is honest about the
documented pairs and neutral about the rest; the rates and the counter
graph decide between heroes the wiki has not compared.

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

## The swaps

Above blue's picks the board suggests the swaps that pay for their cost,
as one joint answer (`inference/swaps.py`, the board's `swaps`). For
blue's picks R, as sent, and the swap cost c:

```
target = the legal six x maximising  score(x) - c * |R - x|
c      = swap * (best - floor) / 100          swap: meta.md's, in share points
```

`|R - x|` counts the picks x drops, so a half-drafted seat's empty slots
fill for free and a full six pays c for each hero it replaces. Written as
a keep bonus, `score(x) + c * |x ∩ R|`, which differs by the constant
`c * |R|`, the term is each pick's own part, and the search's bound
carries it exactly beside the default engine's own parts: the target is
one branch and bound on blue's seat, over every legal six of the
released, unbanned roster, on blue's optimal's scale, ties broken by the
board's draw. The keep term ranks the search and nothing else - it is no
bar of any breakdown, and the target is scored again on blue's plain
objective, so its share is the one `evaluate` gives it.

The cost is in share points so that it reads in the badge's units on
every board and under every meta: a swap must gain that many of blue's
100 before it is suggested, the stand-in for the ultimate charge and the
walk a swap costs. The shipped cost is 10; 0 suggests blue's optimal six
outright, and the range is 0..50. The `tune` tool sets it (`{"id":
"meta", "field": "swap", ...}`), and a board's `weights=swap:<v>` sets it
for that board alone. A playbook folder whose `meta.md` predates the
dial reads the shipped file's.

A swap is suggested only where the target's net beats the six that keeps
every pick - the picks themselves at six, the fill around fewer - at
`SCORE_PLACES`: a tie keeps the picks. Where no six keeps them (a six
that breaks a limit, picks no six completes) the target is the cheapest
way back to an allowed six, and the verdict says so. Each dropped pick
is paired with an incoming hero of its own role where the target has
one, then with whichever is left, and carries its place among the picks
as sent (`at`), so the page draws the incoming portrait over that slot
and decides nothing; a half-drafted seat's empty slots show the fill's
heroes (`open`), whether or not a swap is suggested, as the rest of the
board does.

Where a swap is suggested, red's optimal, current comp and fill are
solved again against the target, and the fight odds read off them as the
board's own are read; a suggestion that would lower them is withheld,
and the verdict names the swaps it held back. The gate reads the picks
as they stand.

**Why joint.** Each pick's best single swap, taken alone, can conflict:
two tanks in for one slot, one hero taken twice, or a union of bests
below the joint answer. One search over every legal six gives one
consistent answer, and taking one of its swaps leaves the rest the
answer from the new picks: with R' the picks after one swap, `net_R'(x)
<= net_R(target) + c = net_R'(target)` for every six x. Red's seat is
never searched for swaps; its picks are the other side's facts.

The verdict reads `swap <pick> for <hero>: <before> -> <after> / 100 of
the optimal, fight odds <before> -> <after>, at a cost of <c> / 100 a
swap`, or `keep the picks: no swap gains its cost of <c> / 100`.

**Why swaps are scored.** The owner's words: swaps mid-fight should be
scored, and the engine "needs to be dynamic". A six is not held for the
map: players trade heroes as a match turns, so the board prices a trade
against what it gains, and the plan below prices it from stage to stage.

`tests/verification/inference/test_swaps.py` holds the search to a full
enumeration of the net on the synthetic World - a full, a half-drafted and a
not-allowed reference, the default engine on and off, the cost from 0 to
50 - and `tests/verification/inference/prove_exact.py`'s swap boards hold it
to a brute force of every legal six on the built database, around locks that
keep some of the reference and with nothing locked, as a board runs it.

## The plan stage by stage

The board carries a row a stage of the map, in play order (`Board.stages`,
`swaps.chain`), from one origin: the six the board suggests - blue's
picks with the swaps taken, the fill around fewer, the optimal before
any pick.

- **The phases of a route** (Hybrid, Escort) chain: each phase's six is
  the best reachable from the phase before, each hero changed costing
  the swap cost, by the same exact search as the swaps. A hero stays into
  the next phase unless swapping gains more than the cost there. The
  chain is greedy, stage by stage: it never trades a swap now against
  one later.
- **The arenas** (Control rounds, Flashpoint points) come up in no fixed
  order, so each is reached from the origin, never from the arena listed
  before it.
- **A chosen stage** is the origin itself, and the phases before it read
  as played, with no six.

Red on every stage is its revealed picks, else its likely six. Two stages
that score every six alike from the same six - the same gates and the
same map values a rule reads (`Objective.ground_key`) - are one search.
A stage past the search's budget reads not solved, and the next phase
goes on from the last six that was.

Each row's blurb is worded from the facts, never a model, four sentences
at most, each dropped when it has nothing to say: the ground its own
text stresses, else that it reads as the map; the rules its ground turns
on and off against the whole map; the swaps and the two terms the six
gains most on, or the six kept under the cost; and how to play it where
the six's lean turns (`plan.stage_blurb`). A stage differs from its map
only through its terrain and the rules that read it, since the rates are
per map: under the shipped playbook, 8 of the 64 stages score a six of
their own, on either side and with none - Havana's three, Midtown's and
Neon Junction's escort phases, two of Rialto's and Route 66's Western Town
Complex. 36 of the 64 have no text of their own on the wiki; fuller stage
texts are the lever (pm/backlog.md). At the shipped swap cost of 10 the
plan keeps the board's six through every stage of an open board: the
stages that score apart gain less than a swap costs, and a lower cost on
the Swap cost slider shows them.

**Rules that pull opposite ways.** Both rules of an opposing pair count,
at the owner's word. Where a hard choke and high ground both stand out
(Rialto's bridge, Route 66's Western Town Complex), the barrier pair
partly offsets: the first 1000 of barrier health nets half a weight, and
past 2000 nothing; the melee pair nets three quarters of a weight across
the scale's range of melee picks.

`tests/verification/inference/test_stage_plan.py` holds each phase and each
arena to an enumeration on the synthetic World.

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
over pairs, the enemies answered, the distinct subroles, the isolated
picks and the largest group of the claimed synergy graph, or fixed by the
shape - and every team and matchup key has its rule. An expression's
range comes from its tree: an operator takes its operands' ends, a
comparison is true, false or either, and `and`, `or` and `if` join the
values they can take. A limit false on every six of a branch drops it. A
metric the bound sums in another order than the metric itself carries a
slack, `SLACK` (1e-12) per unit of its addends, outward on both ends; one
of whole numbers carries none, so a threshold on a count reads exactly.

Sixes rank by `scoring.rank_key`: the score rounded to `SCORE_PLACES` (9)
decimal places, then the tie-break, then the names. The tie-break is the
sum of the six's draws: each hero's draw is a whole number below 2^40
hashed from the board's map and side and the hero's id (`scoring.draw`).
It reads no rate and no name, so a tie never leaks the meta back in;
every hero of a role has the same chance to win one across boards; and
the same board draws the same numbers in every process, so the answer is
repeatable. Red's picks, the bans and the locks leave the seed alone, so
the six a tie settles holds still as the draft fills in. The names decide
only two sixes whose draws sum the same. The rounding makes a plateau
finite: with the engine off, the healing floor scores every six that
heals enough exactly 0, and the tie-break's own bound - the picks' draws
and each open role's largest, exact because the draws are whole numbers -
settles which of them lead. Each six is scored in one seat order - tanks,
then damage, then supports, each by hero id - so its score is a function
of its heroes to the last bit, and a board is the same payload under any
hash seed.

An optimal six reports how many legal sixes share its rounded score,
itself among them (`Solver.ties`): read off the search's best K where a
six of a lower score closes it, else counted by a walk of its own, exact
up to `RANK_CAP` (100) within `TIE_BUDGET` (5,000) sixes scored, and "at
least" past either. More than one reads "one of N sixes tied at the
best score" on the board: none of them is better, and the draw picked
the one shown. With the meta at 0 and every weight at 0, every legal six
ties, which is what "every hero has an equal chance" means here; the
`ties-are-drawn` assumption states it in the playbook.

A full six's rank is its place in that order, one more than the legal
sixes that rank above it - a six that ties the optimal's rounded score
and loses the tie-break is not first, and ranks where the alternatives
list it: read off the seat's search where the six reaches its best K,
counted by a search of its own where it does not, which drops a branch
as the best-K search does, exact up to `RANK_CAP` (100); past it the six
reads outside the top 100. A search past `NODE_BUDGET`
branches or `SCORE_BUDGET` sixes scored in full raises `Unbounded`, a
refusal: the answer is exact or refused, never a guess. A search that ends
with no six proves that none exists, so blue's picks a fill finds nothing
for are not allowed. Every search runs in the calling process, one after
another; a board asks its client's lane (`inference/supersede.py`) every
`CHECK_EVERY` branches whether a newer board replaced it.

The suite holds the search to enumeration:
`test_the_search_reaches_the_enumerated_maximum` and its neighbours in
`tests/verification/inference/test_solver.py` compare the best sixes, the
score floats and the ranks with a full enumeration's on synthetic boards -
both seats, the fill, the countered case, bans, locks and plateaus - and
`tests/verification/inference/test_bounds.py` holds every rule and the whole
bound to every completion of random branches. On the built database,
`.venv/bin/python -m tests.verification.inference.prove_exact` brute-forces
every legal six of a real board, in slices, against the search.

### Why the search is exact

The owner's rule: the solver optimises exactly over the whole legal
space - every six, duplicates removed, at most two tanks, the playbook's
limits - and no per-role shortlist may restrict which heroes can appear.
The search it replaces kept each role's six highest-standing heroes,
swept the 13,101 sixes they allow, then climbed from the best of them by
local search over the whole roster. It scored about 14,500 of 17 million
sixes, and its answer was the best it met, not the best there is. On Samoa
against D.Va, Roadhog, Sombra, Lúcio and Brigitte the investigation that
led here found it returning a two-one-three where a two-two-two scored
higher: the shape it needed was never searched from a good start, and no
pool size could promise it would be.

Replayed on that data, the old search still answers the two-one-three
and the exact one the two-two-two, the same float a brute force of all
17,217,564 legal sixes found. On the data of that day, where an unwritten
synergy pair read the written pairs' mean, the old search happened to
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
most, or the largest of their weights where that is more, so a need alone
on its guard weighs its own weight, a slider's past 2 too. The scale is
a seeded sample of 1200 legal sixes plus the field of each role's top six
by the board's prior (`inference/scale.py`), measured on the whole map
whatever the stage. The field is 12,038 sixes on an open board; where
every heuristic on a metric reads a team key under a gate the board
settles, and every limit is a shape limit, each is read on the sections
of `team_metrics` those keys live in alone (`Objective.lean_keys`), the
same values at a third of the cost, and
`tests/verification/inference/test_scale.py` holds the two readings to the
same bounds and floor.

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
the field one of `meta`, `rate`, `synergy`, `counter` and `swap`, the
swap cost in share points ([The swaps](#the-swaps)), or `body`, the
file's prose rewritten whole, which the playbook tab shows on the Meta
card; a playbook folder with no `meta.md` is seeded from the shipped
one's, and the log line says so. The board's
sliders override a weight for one board - `weights=<id>:<0..10>` on
`/api/board`, `weights` on the `board` tool - the Meta slider among them
as `meta:<0..10>` and the swap cost as `swap:<0..50>`, and every result
names the weights it was scored under; the board writes none of them.
Three tools write a strategy file - `tune`, `add_strategy` and
`infer_strategy` - and `tune` writes
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

`heal-rate`, the shipped playbook's healing heuristic, scored, holds a six to a
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
22 strategy files in `inference/strategies/`: 1 constraint (a limit), 13 heuristics (9 on a metric, 4 scored) and 8 assumptions. Regenerated by `.venv/bin/python -m door.mcp call db_docs`.

#### The meta

`meta.md`: meta 1 x (rate 1, synergy 0.26, counter 0.05); swap cost 10 - the default engine's weights, which the tune tool changes (id `meta`)

The default engine scores every six before the playbook's rules do: each pick's win rate on the map, trusted by its pick rate (rate), the wiki's synergy scores among the six, a cell no article writes at the written cells' claim share (synergy), and the counter graph against the other side (counter). The meta scales the three together - 0 is the playbook alone, 1 the engine as calibrated - and the board's Meta slider sets it for a session without touching this file. Rate is 1, so its term is in win-rate points, and synergy and counter are set so that each term spreads a typical board's sixes about half as far as the rates do; synergy was set again once a blank cell read at the written cells' claim share, which narrowed its range. The swap cost, in share points of blue's span, is what a swap of one of blue's picks must gain before the board suggests it - the stand-in for the ultimate charge and the walk a swap costs - and what each hero changed between two stages of the plan costs; at 10 a board with blue's six drafted is offered one or two; a board's own swap weight sets it for a session without touching this file, and 0 suggests the optimal six outright.

#### Constraints

##### Never more than three supports (`at-most-three-supports`, shape, limit)

`require team.supports <= params.MAX_SUPPORTS` - always holds
params: MAX_SUPPORTS=3

A six fields at most three supports, on every board. Open Queue sets no cap on supports, so this rule sets one: a six with a fourth support is never chosen. Measured as the six's support count.

#### Heuristics

##### Choke maps reward melee (`choke-maps-reward-melee`, map)

`maximize team.melee` - picks with a melee weapon. weight 1; when `map.chokes >= params.STANDOUT or map.interiors >= params.STANDOUT`
params: STANDOUT=0.5

A map of tight chokes and rooms puts the fight in someone's face, where a melee weapon does its full damage and a long gun does not. Reinhardt is the community's brawl tank because he swings his hammer at close quarters. Picks with a melee weapon are counted, read on the ground whose chokes or interiors stand 0.5 sd or more above the ordinary map's.

##### Chokes reward crowd control (`chokes-reward-crowd-control`, map)

`maximize team.cc_count` - picks with crowd control (stun, sleep, immobilize, hinder, knockback). weight 1; when `map.chokes >= params.STANDOUT or map.interiors >= params.STANDOUT`
params: STANDOUT=0.5

Where a map funnels both teams into a choke, crowd control decides who gets through it. A stun, a wall or a knockback at a doorway takes a pick out of the fight at the one moment the whole team is committed, and enclosed space leaves nowhere to dodge it. Picks with a crowd-control tool are counted, read on the ground whose chokes or interiors stand 0.5 sd or more above the ordinary map's.

##### Capture points reward area effects (`control-area-healing`, map)

`maximize team.aoe_count` - kit pieces tagged area of effect or shockwave. weight 0.25; when `map.objective == 'point'`

A capture-point fight happens on one point with the whole six stacked on it, so healing and damage that touch an area touch everyone. Lúcio's aura and Junkrat's splash both reach the whole point, and a Lúcio and Brigitte pairing was called too strong on king of the hill. Kit pieces tagged area of effect are counted, read wherever the ground is won on a point: Control, Flashpoint and a Hybrid's first phase.

##### Escort lanes reward the longest gun (`escort-longest-gun`, map)

`maximize team.range_max` - the longest range on the team. weight 0.25; when `map.objective == 'payload'`

A payload runs down long lanes, and the pick with the longest reach on the six owns the lane before the fight closes. Every payload route opens onto a long sightline somewhere along the path, which is why the community names Escort as the mode that favours poke and Ashe as a Junkertown pick. The longest published range on the team is the measure, read wherever the ground is won on a payload: an Escort map and a Hybrid's later phase.

##### Flank routes want deployables (`flank-routes-want-deployables`, map)

`maximize team.deployables` - picks with deployables. weight 1; when `map.flanks >= params.STANDOUT`
params: STANDOUT=0.5

A placed object fights a flanker while the team looks elsewhere: turrets counter flank pressure, a wall cuts the diver off, and a tree or a barrier gives the backline something to stand behind. Symmetra is rated one of the better damage picks in coordinated play for her turrets against flanks, and Torbjörn is the answer offered to a flanking Anran. Picks with deployables are counted, read on the ground whose flank routes stand 0.5 sd or more above the ordinary map's.

##### High ground strands melee (`high-ground-strands-melee`, map)

`minimize team.melee` - picks with a melee weapon. weight 0.25; when `map.high_ground >= params.STANDOUT`
params: STANDOUT=0.5

On a map built around high ground a melee pick has no way to touch an enemy standing above and no quick way up. Reinhardt is named as the tank who suffers most where high ground matters, with nothing to throw at it but a Fire Strike, and brawl's movement tools are said to have no vertical component at all. Picks with a melee weapon are counted, minimised on the ground whose high ground stands 0.5 sd or more above the ordinary map's.

##### Open ground punishes short reach (`open-ground-punishes-short-reach`, map)

`maximize team.range_min` - the shortest longest-range. weight 1; when `map.open_ground >= params.STANDOUT`
params: STANDOUT=0.5

On open ground the pick with the shortest reach is the one who spends the fight unable to shoot back. Beams and shotguns that own a corridor are helpless across a canyon, so a comp is judged there by its shortest longest-range. The smallest of the picks' longest published ranges is the measure, read on the ground whose open ground stands 0.5 sd or more above the ordinary map's.

##### Sightlines want hitscan (`sightlines-want-hitscan`, map)

`maximize team.hitscan` - picks with a hitscan weapon or ability. weight 1; when `map.sightlines >= params.STANDOUT`
params: STANDOUT=0.5

Long sightlines belong to hitscan weapons, which land at any distance the map offers while projectiles arc and slow. On such a map the fight opens at the range where a Soldier: 76, Ashe or Widowmaker is already hitting and a projectile kit is not. Picks with a hitscan weapon or ability are counted, read on the ground whose sightlines stand 0.5 sd or more above the ordinary map's.

##### Vertical maps reward fliers (`vertical-maps-reward-fliers`, map)

`maximize team.flyers` - picks that fly or hover. weight 0.25; when `map.high_ground >= params.STANDOUT`
params: STANDOUT=0.5

A map with high ground everywhere rewards the picks that travel between its levels without a staircase. Echo is named as the fill pick for maps with verticality, and the maps with the most high ground are called best for heroes that move easily between low and high ground. Picks that fly or hover are counted, read on the ground whose high ground stands 0.5 sd or more above the ordinary map's.

##### Control points have edges (`control-points-have-edges`, map, scored)

weight 1; when `map.hazards >= params.STANDOUT or (map.name == 'Nepal' and map.stage == 'Sanctum')`; bonus `min(max(team.cc_count - params.BOOP_FLOOR, 0), params.BOOP_CAP) * 0.5`
params: BOOP_CAP=3, BOOP_FLOOR=2, STANDOUT=0.5

Control stages are built around drops - the well on Ilios, the sanctum pit on Nepal, the edges of Lijiang Tower - and a knockback or a pull turns a full-health enemy into a kill. Roadhog hooking into the well and Lúcio booping on Lighthouse are the community's Control examples, and Orisa is named as good on maps with environmental hazards. Each pick with crowd control beyond the second earns half the rule's weight, up to three, read on the ground whose hazards stand 0.5 sd or more above the ordinary map's and on Nepal's sanctum, which the examples name.

##### A hard choke needs a barrier (`hard-choke-needs-barrier`, map, scored)

weight 1; when `map.chokes >= params.STANDOUT or (map.name == 'Havana' and map.stage in ['City Streets', 'Sea Fort'])`; bonus `min(team.barrier_hp / params.CHOKE_BARRIER, 1)`
params: CHOKE_BARRIER=1000, STANDOUT=0.5

A hard choke is crossed behind a barrier or not at all, and a map whose fights are chokes is a map where one barrier is worth a pick. The community's list of the places a shield is needed is a list of hard chokes - King's Row first point, Eichenwalde third, Havana first and third - and the maps left off it have long sightlines instead. Barrier health earns the rule's weight in full at 1000 and nothing past it, read on the ground whose chokes stand 0.5 sd or more above the ordinary map's and on Havana's first and third stages, which the list names.

##### High ground looks over a barrier (`high-ground-over-barrier`, map, scored)

weight 1; when `map.high_ground >= params.STANDOUT`; penalty `min(team.barrier_hp / params.BARRIER_HP, params.BARRIER_CAP) * 0.5`
params: BARRIER_CAP=2, BARRIER_HP=1000, STANDOUT=0.5

A barrier faces one way and the enemy on the high ground above it shoots past it, so on a map built around high ground a barrier tank is a slow pick paying for a tool that does not work. Reinhardt is named as ineffective on Numbani's first two points for the high ground around them. Each 1000 of barrier health costs half the rule's weight, up to 2000, on the ground whose high ground stands 0.5 sd or more above the ordinary map's.

##### Heal at the other side's rate (`heal-rate`, sustain, scored)

weight 2; penalty `matchup.heal_shortfall`

A six heals at least the share of its total health that the other side heals of its own each second, and never less than the other side's healing in full; an unrevealed slot on that side is the 2-2-2 shape's missing role at the role's median pool and healing. With damage anti-heal on both sides, the healing half of the race between the two sixes breaks even at that share, and nothing in the kit sets a higher bar. The charge is the weight times the share of the need left unhealed.

#### Assumptions

##### Deterministic, not probabilistic (`deterministic-not-probabilistic`, assumptions)

*assumption* - prose the solver takes as given and the session holds a comp to

The same board, playbook and weights always give the same six, the same score and the same alternatives: nothing is sampled when a board is solved, and every seed is a string read off the board. A score, a share and the fight odds are the playbook's arithmetic over the facts, not probabilities of winning, because nothing is fitted to match results. A higher score means a better six under these rules and weights, never a greater chance to win.

##### This is Open Queue Ranked (`open-queue-ranked`, assumptions)

*assumption* - prose the solver takes as given and the session holds a comp to

The mode is Competitive Open Queue, 6v6: six picks per side in any mix of roles under the queue's own limit of two tanks. Rules written for Role Queue's 2-2-2 or for Quick Play do not bind here. Nothing is measured; the shape rules read from this.

##### All players play optimally (`players-play-optimally`, assumptions)

*assumption* - prose the solver takes as given and the session holds a comp to

Every player on both teams plays their hero as well as it can be played. A strategy therefore encodes the game - kits, ranges, cooldowns, maps, roles - and never a lobby's habits or a rank's tendencies. Nothing is measured; the session holds every comp to it.

##### Tied sixes are equally good (`ties-are-drawn`, assumptions)

*assumption* - prose the solver takes as given and the session holds a comp to

Two sixes that score the same are equally good, so the choice between them says nothing about either. The engine settles a tie by a draw per hero, seeded by the map and the side and blind to rates and names, so the same board always gives the same six and every hero of a role has the same chance across boards. The board says how many sixes tie, so a drawn six is never read as the best one; with the meta and every weight at zero, every legal six ties.

##### Console only (`console-only`, general)

*assumption* - prose the solver takes as given and the session holds a comp to

The owner plays on console, and the playbook is built for console play. The rates are the console pull, and no PC-only feature such as the Workshop Inspector log is assumed. Nothing is measured.

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
| `team.synergy_score` | summed synergy scores among the picks: a pair's claimed cells, and each cell no article writes at the written cells' claim share |
| `team.synergy_density` | synergy edges / possible pairs |
| `team.isolated_count` | picks with a documented partner somewhere and none on the team |
| `team.isolated` (text) | the isolated picks |
| `team.core_size` | largest connected group in the team's synergy graph |
| `team.pairs` (text) | the synergy pairs present |
| `team.unwritten_pairs` (text) | the pairs among the picks neither article writes a synergy cell for, read in synergy_score at the written pairs' mean |
| `team.unwritten_cells` | the synergy cells among the picks no article writes, two a pair, each read in synergy_score at the written cells' claim share |
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
| `map.arenas` | separate arenas, one played at a time: Control's 3, Flashpoint's 5; else 0 |
| `map.phases` | named parts of one route, played in order: Hybrid's 2, an Escort map's named stretches; else 0 |
| `map.bans` | bans already made in this match: a ban rate is a risk only before them |
| `map.name` (text) | the map's name; empty with no map |
| `map.stage` (text) | the stage in play, as the map lists it; empty for the whole map |
| `map.objective` (text) | what the ground in play is won on: point (Control, Flashpoint, a Hybrid's first phase), payload (Escort, a Hybrid's later phase), push (Push); empty for a Hybrid played whole, or no map |
| `map.chokes` | chokepoints, narrow streets, corridors, tunnels, gates and doorways on the ground in play: the wiki article's mentions per thousand words, in sd from the mean of the maps with text (0 with no text), raised to the stage's own where a stage is in play and its text names them 2 times or more |
| `map.interiors` | rooms, caves and other indoor ground on the ground in play: the wiki article's mentions per thousand words, in sd from the mean of the maps with text (0 with no text), raised to the stage's own where a stage is in play and its text names them 2 times or more |
| `map.high_ground` | high ground, rooftops, balconies and other vertical ground on the ground in play: the wiki article's mentions per thousand words, in sd from the mean of the maps with text (0 with no text), raised to the stage's own where a stage is in play and its text names them 2 times or more |
| `map.flanks` | flank routes and side paths on the ground in play: the wiki article's mentions per thousand words, in sd from the mean of the maps with text (0 with no text), raised to the stage's own where a stage is in play and its text names them 2 times or more |
| `map.sightlines` | long sightlines on the ground in play: the wiki article's mentions per thousand words, in sd from the mean of the maps with text (0 with no text), raised to the stage's own where a stage is in play and its text names them 2 times or more |
| `map.open_ground` | open ground and ground said to lack cover on the ground in play: the wiki article's mentions per thousand words, in sd from the mean of the maps with text (0 with no text), raised to the stage's own where a stage is in play and its text names them 2 times or more |
| `map.hazards` | drops, pits and other environmental hazards on the ground in play: the wiki article's mentions per thousand words, in sd from the mean of the maps with text (0 with no text), raised to the stage's own where a stage is in play and its text names them 2 times or more |
| `map.cover` | cover on the ground in play: the wiki article's mentions per thousand words, in sd from the mean of the maps with text (0 with no text), raised to the stage's own where a stage is in play and its text names them 2 times or more |
| `world.heal_bench` | 2 x the median peak heal across the released supports |
| `world.hps_bench` | 2 x the median sustained healing across the released supports |
<!-- /generated:catalog -->
