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

One input is written by hand: the playbook, which the solver reads; [The
catalog](#the-catalog) lists the shipped rules, and the default engine
scores every board beneath them ([The objective](#the-objective)). A
pull tool fills every other table. The solver tests run on the reference
playbook in [tests/fixtures/playbook/](../tests/fixtures/playbook/),
which holds a file of every form but the draft. The package's map is the
[inference/__init__.py](../inference/__init__.py) docstring, and each
module's docstring holds its detail.

## How a six is chosen

A six is chosen by inference on maxims and facts: the playbook's rules
and the database's numbers about the board make one objective, weighted
and constrained, and the solver solves it exactly. Five steps, in order:

```
space  = every six of released, unbanned heroes that keeps the locked picks,
         each set once, grouped tank, damage, support; at most two tanks
legal  = the space, less every six a limit rules out           a limit weighs nothing
score  = meta x (rate x rates + synergy x synergy + counter x counters)
       + each heuristic's term, times its weight               from the same facts
COMP   = the legal six of highest score, exactly; the next best after it, in order
```

1. **The space.** A six is a set, held grouped as tanks, damage and
   supports. It keeps the locked picks, leaves out the banned and the
   unreleased, and fields at most two tanks, the queue's own limit.
   Today's 53 released heroes - 15 tanks, 24 damage, 14 supports - make
   22,957,480 sixes, and 18,040,386 of them field two tanks or fewer.
2. **The limits prune.** A limit removes every six that breaks it and
   adds nothing to one that keeps it. The shipped limits - at most three
   supports, at least one tank and at least one support
   (`at-most-three-supports`, `six-fields-a-tank`,
   `six-fields-a-support`) - leave 13,030,920 legal sixes on an open
   board, and a ban or a locked pick leaves fewer. Blue's own comp that
   breaks a limit is not allowed; red's revealed picks are facts, never
   ruled out ([The share](#the-share)).
3. **The meta scores.** The default engine scores every legal six on its
   win rates, synergies and counters, and `meta.md`'s `meta` scales it
   ([The objective](#the-objective)).
4. **The heuristics adjust.** Each heuristic adds or subtracts, times its
   weight, from the same facts ([How a strategy file
   works](#how-a-strategy-file-works)). The shipped playbook's fourteen
   were researched on 2026-10-03 from Blizzard's site and forums, the
   wiki and the Reddit record (`inference/README.md`): the healing floor
   ([The healing floor](#the-healing-floor)); the 6v6 shape, two of each
   role; a save and a barrier on every six; one playstyle, with a need
   for each of dive, brawl and poke; the damage to break two tanks and a
   damage amplifier; and four rules on the ground in play - long
   sightlines, hazard edges, Flashpoint and high ground, a defended choke
   - each gated where its feature stands out, 0.5 sd or more above the
   ordinary map's (a `STANDOUT` dial), or on the mode and the side.
5. **The argmax.** The search returns the legal six of highest score,
   proved by branch and bound, and the next best in rank order as the
   alternatives ([The search](#the-search)). Every reason it gives cites
   a numbered fact (F1, F2, ...).

Once blue has picks, the board also answers which of them to trade ([The
swaps](#the-swaps)) and lays the map out a stage at a time ([The plan
stage by stage](#the-plan-stage-by-stage)). The weights are not learned
([How the weights move](#how-the-weights-move)), and a score is not a
probability ([The share](#the-share)). Each rule's reasons are in the Why
sections: [the weights](#why-the-weights-are-the-playbooks), [the
unwritten synergy pair](#why-an-unwritten-synergy-pair-is-not-zero) and
[the exact search](#why-the-search-is-exact).

**The ground in play.** A board is played on the whole map or on one of
its stages - a Control or Flashpoint round, an Escort or Hybrid phase -
named by `stage` (`/api/board`, the board tools; the roster lists each
map's). The stage moves the `map.*` metrics and nothing else, and every
seat of the board plays it. A terrain feature reads the map's article,
raised to the stage's own where the stage's text - the article's
sections and sentences about it, and the heroes' map-strategy notes on
it - names the feature `STAGE_MENTIONS` (2) times or more, and more
often than the map's (`facts.compute.ground`, over
`facts.tables.derive_stage_terrain`): the stage's mentions per thousand
words, pulled toward its map's rate by `STAGE_PRIOR_WORDS` (100) words of
it, so a 20-word text counts a sixth and a 200-word one two thirds, then
read in standard deviations from the maps' mean, as the map's own rate
is. The pull weighs the text by its length, not by the value it yields:
on the maps of 2026-10-04 one mention in 20 words still reads 1 to 2.7
sd above the mean on six of the eight features, enough to open a terrain
rule's gate, and one word can be a misreading - Havana's Distillery has
"Vats blocking sightlines" - so one mention raises nothing. A stage's
text can add a feature, never drop one, since a text that leaves a
feature out has not said it is absent. `map.stage` and `map.objective`
(a point, a payload or a push) say where the fight is, and `map.name`
which map. The scale is measured on the whole map, each heuristic read
wherever the board settles its gate, so every stage of a map shares one;
the floor is the stage's own. With a stage named, the facts state the
ground in play (`map.ground`), and a rule gated on the terrain cites it.

**The rates are a proxy.** Blizzard publishes rates for Competitive Role
Queue, 5v5, one tank a side; no source publishes Open Queue 6v6, the
mode the playbook assumes (`open-queue-ranked`). The rates stand in for
it, for direction and not for decimals, and a value a hero has only
beside a second tank is missing from them: Zarya's, in a two-tank front
line, is the plain case. The kit is read in 6v6
([architecture.md](architecture.md#the-scope)); the rates cannot be.

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
  every ordered pair of released heroes, and of each loser's six best
  answers, scoring 0.5 or more and more than the reverse, those on a
  pair the wiki leaves out weigh 1 each; the others are not replaced.
  The other side is six heroes: its locked picks and its likeliest
  heroes for the rest on this map past the bans
  (`compute.expected_picks`), its likely six before any pick, on the
  board and in `infer` alike, so a reveal replaces one likely hero and
  the term's weight holds still as red picks. Of the objective's terms
  only this one reads the likely heroes or a derived edge: every other
  term reads the side's revealed picks, and the
  `team.*` and `enemy.*` counter metrics read the wiki's graph against
  them. The board
  names every derived edge it counts with the mechanism and the numbers
  that fired.

The weights are the playbook's. `meta.md`, beside the strategy files,
holds four numbers, each within 0..10: `meta`, which scales the whole
engine, and under it `rate`, `synergy` and `counter`, each term's points
per unit. The shipped file sets 1, 1, 0.13 and 0.025. `rate` is 1, so the
rate term is in win-rate points; `synergy` and `counter` were set so that
each term's median spread across a board's reference sample was about
half the rate term's, then halved against 6v6 results, so each is now
about a quarter of it; the module docstring holds the rule, and [Why the
weights are the playbook's](#why-the-weights-are-the-playbooks) what it
measured, why synergy moved from 0.1 and why both were halved. A heuristic on a metric still moves a six by its
weight at most, a scored one by its weight times its bonus less its
penalty; the math page says how that compares with the base's spread. Each
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
heuristics and the meta carry every weight, each one the owner's to turn.
So the engine's weights live in `meta.md` beside the strategy files,
where the `tune` tool changes them as it changes a strategy's weight -
validated, documented and logged - and one meta weight over them leans
on or silences the whole engine at once, from the file for good or from
the Meta slider for a session. What a term counts inside - a derived
counter edge against a wiki edge, the pick rate that halves a rate
edge's trust, the needs' shared budget - stays in code as the term's
definition: the counter tallies stay whole numbers, which the search's
exactness leans on.

The synergy and counter weights first followed the calibration's rule:
each term's median range over a board's reference sample, red's likely
six against the seat, about half the rate term's. The counter graph's
median range is 41 - the wiki's edges at 2 and the kit's fill at 1 - so
counter weighed 0.05; the synergy score's is 8.1, each unwritten cell
read at the written cells' claim share, so synergy weighed 0.26.

A 6v6 benchmark then halved both, to 0.13 and 0.025, so each term's range
is now about a quarter of the rate term's. The rates are 5v5 Role Queue,
and the game the engine solves is 6v6, which neither Blizzard nor the
wiki measures. On a private benchmark against CounterWatch's public 6v6
numbers - PC players' matches, kept out of this repository and off the
board - sixes picked with both weights halved scored a little better on
most of the maps held out of the tuning, under both of its readings of a
counter: the win rate of one hero against another, and its duel rating.
Turning both off scored no better on average and far less evenly, and
would leave the engine blind to red's picks. `tuning-log.md` records each
setting and its reason.

### Why an unwritten synergy pair is not zero

The wiki's synergy data is the Team Synergy column of each hero's
article: a cell per teammate, rated, written in prose, or left as a
placeholder. A pair an article writes off ("no notable synergy", rated
POOR) and a pair no article writes about are not the same, and the
second is the common case: at the pull of 2026-09-28, 747 of the 1,378
pairs of released heroes had no cell in either article. The holes are
not spread evenly. The newest heroes' articles are near blank - no
article writes a pair for D.Mon or Shion, and Sierra, Venture, Emre,
Freja and Hazard have two to five written pairs each of 52, where the
median hero has 24 - so a blank read as 0 would say "these heroes do not
work together" where the truth is "nobody has written it down yet", and
the synergy term would charge the newest heroes for being new.

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
side's likely six, whose pick score adds `PARTNER_POINTS` for each
documented partner.
A fixture's stamp (`base.stamp`) names the reading, so one recorded
under an earlier reading reads as another objective.

**Why a cell and not a pair.** 483 of the 631 written pairs have one
cell written and the other blank. Read by the pair - a pair neither
article writes at the written pairs' mean, 1.06, and a written pair at
its claims - a pair one article claims reads below a pair nobody wrote
about: Ana with Cassidy 1, Ana with Tracer 1.06. Read by the cell they
read 1.86 and 1.72. The synergy term is honest about the documented
pairs and neutral about the rest; the rates and the counter graph decide
between heroes the wiki has not compared.

## The share

Blue's optimal six is its 100, and its 0 is the seat's floor: the lowest
score among the reference sixes its scale drew (`Solver.floor`, from
`inference/scale.py`), and a fill takes the seat's. A comp's share is its
place on that span:

```
share = clamp((score - floor) / (best - floor), 0, 1) x 100
```

A score is signed, since the rate term counts each pick's edge over 50,
so a share read from zero put every six below zero at 0; the floor puts
blue's comps on a real scale. A best no higher than the floor leaves
nothing to divide, and every comp but the optimal reads *unscored*.

Red is never optimized: the board's red is its likely six around its
revealed picks (`compute.expected_picks`), each open slot filled with
the hero of the highest pick score - how often a six fields it, its
pick rate with a tank's doubled for a six's two tank seats, plus
`PARTNER_POINTS` for each partner already on the six - and red's badge
is how often a six fields those heroes on average. Red has no share.
The fight odds compare the two sides another way (`plan.fight_odds`):
blue's six and red's likely six on one scale, the default engine alone
against red's six, each counter between them counted once, no playbook
rule for either side. The gap between the two scores, divided by the
meta and the rate weight into win-rate points, goes through the
additive model's logistic curve at `base.LOGIT_PER_POINT` log-odds a
point, 4 x 6 / 100 = 0.24: a pick that wins a share p of its matches
adds about 4 (p - 0.5) to its six's log-odds, and the rate term is a
mean over six picks. Synergy and counters enter at their weights over
the rate weight; no sample is drawn, and for the same two sixes the
meta moves no odds. Blue's six is chosen on the engine and the
playbook's rules together, and the meta scales the engine alone, so
until blue holds a full six the meta can change that six - the optimal
before any pick, the fill while blue drafts - and the odds follow the
new six. They are the additive model's reading of the gap, not a
chance of winning measured from matches (the math page, Fight odds).

A comp the limits rule out is not allowed: blue's full six that breaks
one, or picks that no six keeping them completes within the limits
(their fill is then not solved). The fill searches every six on the
roster that keeps the picks, so a fill that ends with none is a proof,
and only that rules the picks out. Such a comp carries no score and no
share, and its breakdown keeps the limits alone; blue's optimal and
red's likely six still render. The badge reads `not allowed: breaks <the
limit's name>`, or, where the picks break no limit as they stand, `not
allowed: no six that keeps these picks meets the playbook's limits`.
Red's revealed picks are the other side's facts and are never ruled out.
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

**Why joint.** Each pick's best single swap, taken alone, can conflict:
two tanks in for one slot, one hero taken twice, or a union of bests
below the joint answer. One search over every legal six gives one
consistent answer, and taking one of its swaps leaves the rest the
answer from the new picks: with R' the picks after one swap, `net_R'(x)
<= net_R(target) + c = net_R'(target)` for every six x. Red's seat is
never searched for swaps; its picks are the other side's facts.

The verdict reads `swap <pick> for <hero>: <before> -> <after> / 100 of
the optimal, at a cost of <c> / 100 a swap`, or `keep the picks: no swap
gains its cost of <c> / 100`.

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
`swaps.chain`), from one origin: the six the comps tab shows - blue's
picks at six, the fill around fewer, the optimal before any pick.

- **The phases of a route** (Hybrid, Escort) chain: each phase's six is
  the best reachable from the phase before, each hero changed costing
  the swap cost, by the same exact search as the swaps. A hero stays into
  the next phase unless swapping gains more than the cost there. The
  chain is greedy, stage by stage: it never trades a swap now against
  one later.
- **The arenas** (Control rounds, Flashpoint points) come up in no fixed
  order, so each is reached from the origin, never from the arena listed
  before it.
- **A chosen stage** is the board's own swap answer from the origin - the
  swaps suggested above the picks, else the origin itself - and the
  phases before it read as played, with no six; the phases after it go
  on from its six.

Red on every stage is its revealed picks with its likeliest heroes for
the rest. Two stages
that score every six alike from the same six - the same gates and the
same map values a rule reads (`Objective.ground_key`) - are one search.
A stage past the search's budget reads not solved, and the next phase
goes on from the last six that was.

Each row's blurb is worded from the facts, never a model, four sentences
at most, each dropped when it has nothing to say: the ground its own
text stresses, else that its text stresses nothing beyond the map, else,
with no text of its own, that it reads as the map; the rules its ground
turns on and off against the whole map; the swaps and the two terms the
six gains most on, or the six kept under the cost; and how to play it
where the six's lean turns (`plan.stage_blurb`). A stage differs from its
map only through the ground in play - its terrain, its name and, on a
Hybrid, its objective - and the rules that read them, since the rates are
per map. Read from the wiki's page cache on 2026-10-04 under the shipped
playbook, 35 of the 64 stages have text of their own and 18 of those
stress a feature beyond their map, each on two mentions or more; 3 score
a six of their own on an open board - Ilios's Ruins, Nepal's Sanctum,
which `edges-reward-displacement` names, and Route 66's Western Town
Complex on attack - where 2 did when a stage read only the paragraphs
about it alone. At the shipped swap cost of 10 the plan still keeps the
board's six through every stage of an open board: the stages that score
apart gain less than a swap costs, and a lower cost on the Swap cost
slider shows them.

**Rules that pull opposite ways.** Both rules of an opposing pair count,
at the owner's word. Under the shipped playbook of 2026-10-03 the healing
floor and the 6v6 shape pull apart: a third support raises a six's
healing, and `two-of-each-role` charges it, so a six takes one only where
the healing it adds outweighs that charge.

`tests/verification/inference/test_stage_plan.py` holds each phase and each
arena to an enumeration on the synthetic World.

## The search

`inference/solver.py` returns the best sixes of the whole legal space:
every six of released, unbanned heroes that holds the locked picks, each
once, at most two tanks and every limit kept - 13,030,920 on an open board
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
over pairs, the enemies answered, the distinct subroles, the largest
playstyle's share and the playstyle a majority carry, the isolated
picks and the largest group of the claimed synergy graph, or fixed by the
shape - and every team and matchup key has its rule. An expression's
range comes from its tree: an operator takes its operands' ends, a
comparison is true, false or either, and `and`, `or` and `if` join the
values they can take. A limit false on every six of a branch drops it. A
metric the bound sums in another order than the metric itself carries a
slack, `SLACK` (1e-12) per unit of its addends, outward on both ends; one
of whole numbers carries none, so a threshold on a count reads exactly.

The walk asks three bounds of a branch, cheapest first, each only while
the ones before keep it (`Bound.bounds`):

- the default engine's terms as above, with every other term at its most
  over the branch's whole shape - every six of that shape around the
  locked picks - read once a shape, so a branch it drops reads no metric;
- the bound above;
- the fold: the default engine and the terms that read nothing but
  per-pick counts of 0 or 1 bounded together - in the shipped playbook
  `six-carries-a-save`, `carry-a-damage-amplifier`, and where the map
  turns them on `edges-reward-displacement`,
  `sightlines-want-long-hitscan` and `mobility-wins-races`. Apart, the
  engine seats each open role's best candidates and each such term the
  heroes that suit it, who need not be the same; the fold takes, over
  each vector of counts the open picks can add, the best the engine's
  terms reach with picks that add it plus each count term at the picks'
  counts and that vector. A six's count is its picks' parts added up - a
  sum's rule is exact on a full six - so a term read at that count bounds
  it on the six. The fold adds its terms in another order than the score,
  so it carries `SLACK` per unit of each term's magnitude, beside the
  engine's. It reads `FOLD_COUNTS` (4) counts at most: it takes such
  terms heaviest first, ties in the score's order, each where the counts
  it and those taken before it read stay within the cap, and a term it
  leaves out is bounded apart, as above. The vectors multiply with each
  count the fold reads, and past a few the fold costs the walk more than
  its pruning saves: on Ilios against three red picks, the shipped
  playbook with twelve more count rules took about 18 s a search with
  every count folded, 3 s with none and under 2 s with four.

What a term reads decides its most, so each term's most is memoised on
those values, `MEMO_CAP` (4,096) of them a term, and a term on the shape
alone - the role counts, `team.shape_excess`, `team.shape_flags` - is read
once a shape.

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
blue's optimal, the fill, bans, locks and plateaus - and
`tests/verification/inference/test_bounds.py` holds every rule and the whole
bound to every completion of random branches. On the built database,
`.venv/bin/python -m tests.verification.inference.prove_exact` brute-forces
every legal six of a real board, in slices, against the search, and its
`draw` stage holds the tie-break's draw even over the real roster.

### Why the search is exact

The owner's rule: the solver optimises exactly over the whole legal
space - every six, duplicates removed, at most two tanks, the playbook's
limits - and no per-role shortlist may restrict which heroes can appear.
A search that sweeps a shortlist and climbs from its best can only return
the best six it met: on Samoa against D.Va, Roadhog, Sombra, Lúcio and
Brigitte one returned a two-one-three where a two-two-two scored higher,
since the shape it needed was never searched from a good start, and no
pool size could promise it would be. The exact search proves its answer
and costs less, about 0.05 s a search and about half a second a board in
one process, the slowest maps included. `top` is its one knob, and it buys the next best sixes in
order.

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
whatever the stage. The field is 11,115 sixes on an open board under
the shipped limits; where every heuristic on a metric reads a team key
under a gate the board settles or one the six decides from team keys,
and every limit is a shape limit, each is read on the sections
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
25 strategy files in `inference/strategies/`: 3 constraints (limits), 14 heuristics (6 on a metric, 8 scored) and 8 assumptions. Regenerated by `.venv/bin/python -m door.mcp call db_docs`.

#### The meta

`meta.md`: meta 1 x (rate 1, synergy 0.13, counter 0.025); swap cost 10 - the default engine's weights, which the tune tool changes (id `meta`)

The default engine scores every six before the playbook's rules do: each pick's win rate on the map, trusted by its pick rate (rate), the wiki's synergy scores among the six, a cell no article writes at the written cells' claim share (synergy), and the counter graph against the other side (counter). The meta scales the three together - 0 is the playbook alone, 1 the engine as calibrated - and the board's Meta slider sets it for a session without touching this file. Rate is 1, so its term is in win-rate points. Synergy and counter were set so that each term spread a typical board's sixes about half as far as the rates do - synergy set again once a blank cell read at the written cells' claim share - and were then halved against 6v6 results: the rates are 5v5, and on a private benchmark against CounterWatch's public 6v6 numbers, kept out of this repository, sixes picked with both terms at half that weight scored a little better on most of the maps held out of the tuning. The swap cost, in share points of blue's span, is what a swap of one of blue's picks must gain before the board suggests it - the stand-in for the ultimate charge and the walk a swap costs - and what each hero changed between two stages of the plan costs; at 10 a board with blue's six drafted is offered one or two; a board's own swap weight sets it for a session without touching this file, and 0 suggests the optimal six outright.

#### Constraints

##### Never more than three supports (`at-most-three-supports`, shape, limit)

`require team.supports <= params.MAX_SUPPORTS` - always holds
params: MAX_SUPPORTS=3

A six fields at most three supports, on every board. Open Queue sets no cap on supports, so this rule sets one: a six with a fourth support is never chosen. Measured as the six's support count.

##### A six always fields a support (`six-fields-a-support`, shape, limit)

`require team.supports >= params.MIN_SUPPORTS` - always holds
params: MIN_SUPPORTS=1

A six always fields at least one support, on every board. Supports are the team's backbone: most heroes heal only after several seconds out of combat, so a six with no support cannot sustain through a fight, and killing the supports is how the other side's heroes are told to win one. The six's support count is held at one or more, beside the cap of three.

##### A six always fields a tank (`six-fields-a-tank`, shape, limit)

`require team.tanks >= params.MIN_TANKS` - always holds
params: MIN_TANKS=1

A six always fields at least one tank, on every board. The tank leads the charge - it draws the other side's fire, holds space and breaks fortified positions and chokes - and a six with none leaves its supports with no one in front of them and nothing to walk behind against two tanks. The six's tank count is held at one or more, beside the queue's own cap of two.

#### Heuristics

##### Bring damage that breaks two tanks (`damage-breaks-two-tanks`, damage)

`maximize team.dps_floor` - summed published per-second damage figures (a floor: misses and healing ignored). weight 0.5

A six brings enough sustained damage to burn through two tanks' worth of health. In 6v6 the second tank adds a pool, mitigation and often a second barrier to chew through before a kill, healing holds space but never takes it, and support-heavy lines are said to struggle to finish anyone. The summed published damage per second of the six's picks is the measure, a floor that ignores misses.

##### Mobility wins races and high ground (`mobility-wins-races`, map)

`maximize team.mobility_count` - picks with a movement or evasive ability. weight 1; when `map.mode == 'Flashpoint' or map.high_ground >= params.STANDOUT`
params: STANDOUT=0.5

On Flashpoint and on high ground, the picks that move win the ground. Flashpoint's next point opens across the largest maps in the game, so a slow six arrives one player at a time, and high ground goes to whoever can get up and back without the long way round the defenders are watching. Picks with a movement or evasive ability are counted on Flashpoint and on the ground whose high ground stands 0.5 sd or more above the ordinary map's.

##### Long sightlines want long hitscan (`sightlines-want-long-hitscan`, map)

`maximize team.hitscan_reach` - hitscan picks whose weapon publishes a reach of 30 m or more. weight 1; when `map.sightlines >= params.STANDOUT`
params: STANDOUT=0.5

Long sightlines belong to long-reach hitscan. A hitscan shot lands the instant it is fired at any range the map offers, so on open lanes the fight opens where a Widowmaker, Ashe or Soldier: 76 already hits and projectiles and short guns do not, and Blizzard's designers add corner cover and run a train across Neon Junction to keep snipers from locking it down. Hitscan picks whose weapons reach 30 m or more are counted on the ground whose sightlines stand 0.5 sd or more above the ordinary map's.

##### A brawl six heals the scrum (`brawl-heals-the-scrum`, shape)

`maximize team.hps_per_support` - sustained healing per support, hp per second: the supports' mean. weight 0.5, a need; when `team.style_lean == 'brawl'`

A brawl six outlasts the other side at close range by healing through the fight. Brawl moves as one tight group and trades damage face to face, so its supports need consistent healing, from an area or a high primary output, that keeps the tanks up through the trade, and area healing is called strongest when the team is grouped. The supports' sustained healing per support is read while brawl is the six's majority playstyle, and a shortfall costs up to the weight.

##### A dive six moves together (`dive-moves-together`, shape)

`maximize team.mobility_count` - picks with a movement or evasive ability. weight 0.5, a need; when `team.style_lean == 'dive'`

A dive six moves as one: every pick reaches the target with the tanks and gets out when the cooldowns are spent. Dive takes several angles and rejoins at once, so a pick with no movement tool is the straggler the other side turns on, and a dive tank who lands without teammates dies fast. Picks with a movement or evasive ability are counted while dive is the six's majority playstyle, and a shortfall costs up to the weight.

##### A poke six needs reach (`poke-needs-reach`, shape)

`maximize team.range_median` - median of each pick's longest published range. weight 0.5, a need; when `team.style_lean == 'poke' and team.range_known >= params.KNOWN`
params: KNOWN=3

A poke six wins the chip war before the fight closes, and it chips only what it reaches. Poke trades damage from range and from several angles, its tanks playing from the sides rather than the front, so a short-range pick idles through the poke or walks in alone. The median of the picks' longest published ranges is read while poke is the six's majority playstyle and three or more picks publish a range, and a shortfall costs up to the weight.

##### Carry a damage amplifier (`carry-a-damage-amplifier`, damage, scored)

weight 0.5; bonus `min(team.dmg_amp, params.AMPS) / params.AMPS`
params: AMPS=1

A six carries a pick that amplifies its teammates' damage. A Discord Orb, a damage boost or a Nano Boost adds a kill threat without adding a gun: it makes a tank's large pool killable and turns a target that was surviving into one that is not, which counts most against two tanks. The rule pays its weight when at least one pick amplifies damage.

##### The tank line carries a barrier (`tank-line-barrier`, durability, scored)

weight 1; penalty `max(0, 1 - team.barrier_hp / params.FRONT_BARRIER)`
params: FRONT_BARRIER=600

The tank line carries a barrier that shields the team. In 6v6 the two tanks split the work, one holding ground behind a barrier while the other dives or peels; two tanks with no barrier between them are called no better than one, with nothing to stop a hit before it lands, and Blizzard added cover to its maps when the format lost a tank and its shields. Barrier health on the six is read against 600, a main tank's barrier: at 600 or more it costs nothing, and each part short of it costs that share of the weight.

##### Edges reward displacement (`edges-reward-displacement`, map, scored)

weight 1.5; when `map.hazards >= params.STANDOUT or (map.name == 'Nepal' and map.stage == 'Sanctum')`; bonus `min(max(team.shove_count - params.SHOVE_FLOOR, 0), params.SHOVE_CAP) / params.SHOVE_CAP`
params: SHOVE_CAP=3, SHOVE_FLOOR=2, STANDOUT=0.5

Where the ground has drops, displacement kills. A knockback, hook or pull over a pit, a ledge or a lava moat removes a full-health enemy outright, and the wiki's pages for Ilios, Lijiang Tower, Nepal and Samoa each name the abilities that do it on or beside the objective. Each pick with a tool that moves an enemy beyond the second earns a third of the weight, up to three, on the ground whose hazards stand 0.5 sd or more above the ordinary map's and on Nepal's Sanctum, which the wiki names.

##### Commit to one playstyle (`commit-to-one-playstyle`, shape, scored)

weight 0.5; when `team.style_share <= params.SPLIT`; penalty `1`
params: SPLIT=0.5

A six commits to one plan, dive, brawl or poke. Each archetype wins one way - brawl walks in as one unit, dive collapses on one target from several angles, poke holds range from several angles - and a six split between them fights as two half-teams: a brawl tank in front of a poke backline can neither peel a dive nor swing at what stands far away. Each pick's playstyles are counted as fractions of one, a pick with two styles giving half to each, and a six whose largest style carries no more than half its picks pays the weight.

##### Two of each role (`two-of-each-role`, shape, scored)

weight 4.5; penalty `(team.shape_excess + max(0, params.TANKS - team.tanks)) / params.WORST`
params: TANKS=2, WORST=3

A six plays two tanks, two damage and two supports. In 6v6 the second tank holds the off-angle and doubles the front's mitigation, so one tank facing two loses the trade for space, two damage picks make the pressure that lets the tanks take it, and each pick past two in a role gives one of those jobs up; a third support behind both tanks is the one off-shape six called strong. Each pick over two in a role costs a third of the weight, a six one tank short pays that once more, and a one-tank six with four damage pays the whole weight.

##### Defenders stack barriers at a choke (`defenders-stack-barriers`, side, scored)

weight 1; when `map.side == 'defense' and map.chokes >= params.STANDOUT`; bonus `min(team.barrier_hp / params.STACKED, 1)`
params: STACKED=2400, STANDOUT=0.5

Defending a hard choke, a six stacks barrier health across the one lane the attackers must use. In 6v6 two tanks' barriers laid over a small choke held so well that matches made no progress until ultimates broke them - the double-shield hold - and the defenders pick that ground in their setup time. Barrier health pays the rule in proportion up to 2400, two barrier tanks' worth, on defense on the ground whose chokes stand 0.5 sd or more above the ordinary map's.

##### Heal at the other side's rate (`heal-rate`, sustain, scored)

weight 2; penalty `matchup.heal_shortfall`

A six heals at least the share of its own pool that the other side heals of its own each second, and never less than the other side's healing in full; an unrevealed slot on that side reads as the 2-2-2's missing role at its median. In 6v6 the second tank on each side brings bigger pools and more incoming damage, so supports heal almost all fight, two light healers fall behind and a lone support is focused first, and with anti-heal on both sides the healing half of the race breaks even at that share. The charge is the weight times the share of that need the six leaves unhealed.

##### Every six carries a save (`six-carries-a-save`, sustain, scored)

weight 0.75; penalty `max(0, params.SAVES - team.team_saves)`
params: SAVES=1

Every six carries at least one save: an invulnerability, a death-prevention or a cleanse that lands on a teammate. 6v6 fights turn on ultimate combos and burst windows that land faster than any heal, and a Protection Suzu, Immortality Field, Life Grip, Transcendence or Projected Barrier makes the combo miss or breaks the stun chain before the kill. The picks carrying such a save are counted, Mercy's Resurrect among them, and a six short of one pays the weight.

#### Assumptions

##### Deterministic, not probabilistic (`deterministic-not-probabilistic`, assumptions)

*assumption* - prose the solver takes as given and the session holds a comp to

The same board, playbook and weights always give the same six, the same score and the same alternatives: nothing is sampled when a board is solved, and every seed is a string read off the board. A score, a share and the fight odds are the playbook's arithmetic over the facts, not probabilities of winning, because nothing is fitted to match results. A higher score means a better six under these rules and weights, and higher odds a stronger six than the other on the meta, never a greater chance to win.

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
| `team.style_share` | the largest playstyle's share of the picks, each pick's tags counted as fractions of one (a pick with k tags adds 1/k to each) |
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
| `team.hps_per_support` | sustained healing per support, hp per second: the supports' mean |
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
| `team.cc_count` | picks with crowd control (stun, sleep, immobilize, hinder, knockback, knockdown, hack, or a slow) |
| `team.shove_count` | picks with a tool that moves an enemy: a knockback, a hook, a displacement |
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
| `map.chokes` | chokepoints, narrow streets, corridors, tunnels, gates and doorways on the ground in play: the wiki article's mentions per thousand words, in sd from the mean of the maps with text (0 with no text), raised to the stage's own where a stage is in play and its text names them 2 times or more and more often - its rate pulled toward the map's by 100 words of it, on the same scale |
| `map.interiors` | rooms, caves and other indoor ground on the ground in play: the wiki article's mentions per thousand words, in sd from the mean of the maps with text (0 with no text), raised to the stage's own where a stage is in play and its text names them 2 times or more and more often - its rate pulled toward the map's by 100 words of it, on the same scale |
| `map.high_ground` | high ground, rooftops, balconies and other vertical ground on the ground in play: the wiki article's mentions per thousand words, in sd from the mean of the maps with text (0 with no text), raised to the stage's own where a stage is in play and its text names them 2 times or more and more often - its rate pulled toward the map's by 100 words of it, on the same scale |
| `map.flanks` | flank routes and side paths on the ground in play: the wiki article's mentions per thousand words, in sd from the mean of the maps with text (0 with no text), raised to the stage's own where a stage is in play and its text names them 2 times or more and more often - its rate pulled toward the map's by 100 words of it, on the same scale |
| `map.sightlines` | long sightlines on the ground in play: the wiki article's mentions per thousand words, in sd from the mean of the maps with text (0 with no text), raised to the stage's own where a stage is in play and its text names them 2 times or more and more often - its rate pulled toward the map's by 100 words of it, on the same scale |
| `map.open_ground` | open ground and ground said to lack cover on the ground in play: the wiki article's mentions per thousand words, in sd from the mean of the maps with text (0 with no text), raised to the stage's own where a stage is in play and its text names them 2 times or more and more often - its rate pulled toward the map's by 100 words of it, on the same scale |
| `map.hazards` | drops, pits and other environmental hazards on the ground in play: the wiki article's mentions per thousand words, in sd from the mean of the maps with text (0 with no text), raised to the stage's own where a stage is in play and its text names them 2 times or more and more often - its rate pulled toward the map's by 100 words of it, on the same scale |
| `map.cover` | cover on the ground in play: the wiki article's mentions per thousand words, in sd from the mean of the maps with text (0 with no text), raised to the stage's own where a stage is in play and its text names them 2 times or more and more often - its rate pulled toward the map's by 100 words of it, on the same scale |
| `world.heal_bench` | 2 x the median peak heal across the released supports |
| `world.hps_bench` | 2 x the median sustained healing across the released supports |
<!-- /generated:catalog -->
