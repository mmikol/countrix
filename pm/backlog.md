# Backlog

What is worth doing next, why, and what it would cost. Ordered by payoff
over blast radius; the first is the one to pick up. The maintainer skill
keeps it current.

## Next

- **A text metric is refused as a bonus or penalty.** A strategy with
  `bonus: map.side` loads as scored, so `add_strategy` writes it, and
  every board where its guard holds then raises `ExprError` from
  `scoring._amount`. The catalog keeps text metrics out of a heuristic's
  `metric:` and not out of an expression. Probe each scored expression at
  load - each text metric read as empty and as a name, each number as 0
  and 1 - and refuse one that does not come out a number. Cost: a
  morning.
- **Red never reorders the scale's field.** `scale.board_prior` ranks the
  heroes whose sixes fix a seat's scale with three points for each enemy
  a hero answers, less three for each that answers it, read off
  `objective.red`; its docstring says it reads no locked pick. A red
  reveal can reorder the field, move the bounds the heuristics are
  normalised on and so move the terms of a six that did not change. Rank
  the field on the map alone (`board_prior` has no other caller) and hold
  the bounds across reds on a widened roster in a test. Cost: half a day
  and every share test.
- **What the mechanics audit left.** A need whose guarded state no
  reference six meets has no spread, reads 1 and costs nothing: give it
  its metric's unguarded bounds. One state written two ways
  (`team.supports <= 1`, `team.supports < 2`) is two guards and two
  budgets until a guard is normalised to its compiled comparison.
  `base.rate_edge` guards a missing rate and not a non-finite one, which
  then carries into the score: read it as no rate. `scoring.normalised`
  clamps to [0, 1], so a heuristic saturates past the highest six the
  sample and the field saw: widen the bounds with attainable extremes
  drawn once per board, keeping the clamp's guarantee. And the
  `team.one_shots` docstring misdescribes it: it counts picks with no
  melee weapon. Cost: a day.
- **Fuller stage texts.** 36 of the 64 stages have no text of their own
  on the wiki as the pull reads it, and most of the rest a few sentences,
  so under the rules of 2026-10-03 only Nepal's Sanctum scores a six of
  its own (the terrain rules they replaced made 8 stages of 5 maps do).
  Reading each article's stage sections more fully, or a second
  paragraph per stage, is the lever that makes the plan stage by stage
  say more. Cost: the map pull and its cache; no engine change.
- **A faster board under the researched playbook.** The researched rules
  made a search walk far more branches than the terrain playbook did only
  where `edges-reward-displacement` is on - about ten times on Ilios, three
  to four on Lijiang Tower and Samoa, near the old count elsewhere - and
  made every branch about three times as costly. The search now asks a
  cheap bound at the shape's root before it reads a metric, memoises each
  term's bound on what it reads, ranges `team.style_share` and
  `team.style_lean` on the branch, and folds the count rules, four counts
  at most, into the default engine's joint bound: Ilios walks 3,991
  branches where it walked 32,165, and a board takes about half a
  second, the slowest maps included. Most of that is now the scale's freeze, three quarters of it
  the field's sixes measured in `scale._field_sample`, which a board
  cannot share with the next while the field reads red (Red never
  reorders the scale's field). Cost: half a day once the field reads the
  map alone.
- **The keys the research could not use.** The 2026-10-03 research
  dropped sourced rules for want of a metric: peel tools near the
  backline (`team.support_peel`), team speed sources such as Speed Boost
  (`team.speed_sources`), walls and placed defences (`team.walls`,
  `team.placed_defences`), setup ultimates for combos, the supports' own
  damage (`team.dps_supports`) and a count of flankers (`team.flankers`).
  Three kit reads undercount: `team.team_saves` misses Lúcio's Sound
  Barrier, `team.barrier_hp` reads Domina's array as one segment, and
  Winston's bubble counts in full as a main tank's barrier. Each key is a
  metric and a range rule (CLAUDE.md, a new metric), then a rule through
  `add_strategy`; a rule on a count of 0 or 1 a pick folds with the
  default engine only among the heaviest rules within the fold's four
  counts (`FOLD_COUNTS`). Cost: half a day a key.
- **A source for the cover rule.** "Cover closes the distance" (cover
  rewards mobility, `team.mobility_count` where `map.cover` stands out)
  was held back on 2026-09-30 for want of a source, and the 2026-10-03
  research found the cover claims contested. Mine one, or file it as the
  owner's own rule, then add it through `add_strategy`.
- **Tunings by map.** The user's request: each map carries its own tuning
  set - a weight per heuristic (and a params dial where a rule has one)
  that applies when that map is on the board, so a rule can matter on
  King's Row and whisper on Ilios. Stored in the database, not the files:
  a `map_tunings` table (map, strategy, weight, params, reason, stamped)
  the `tune` tool writes when the call names a map; the catalog applies
  the map's set over the file's defaults when the solver is built for
  that map (`catalog.weighted` already layers a session's slider values
  the same way, so the map's set is one more layer under the sliders);
  the playbook tab shows the map's values when a map is chosen and the
  file's when none is, and the board result names which set it was
  scored under. Cost: two days - a migration, the tool's `map` argument,
  the layering, the tab, the facts line that names the set - and a test
  that the same six scores differently under two maps' sets.
- **The engine's inner constants as dials.** The owner turns every
  term's weight in `meta.md`; what a term counts inside still sits in
  code, stamped but not tunable: a derived counter edge against a wiki
  edge (`WIKI_WEIGHT` 2, `DERIVED_WEIGHT` 1 in `facts/counters.py`), the
  pick rate that halves a rate edge's trust (`RATE_PICK_HALF`, 3) and
  the needs' shared budget (`NEED_BUDGET`, 2, never below a need's own
  weight). Making them `meta.md` dials is the owner's call: the derived
  edge's would split the counter tally into two whole-number tallies,
  each weighted, so the search's integer tallies and its joint bound hold;
  `pick_half` needs a floor above 0. Cost: a day, with the bound's fuzz.
- **Voice control for the picks.** Say "blue Ana", "red Pharah", "swap
  Ana for Kiriko", "clear red" and the board sets the picks, no clicking
  - for a draft called out at the table. The browser's speech
  recognition (`SpeechRecognition`, Chrome and Safari; no key, no
  service) hears a phrase, a small grammar maps it to the board's own
  toggle calls with hero names matched the way the roster spells them
  (Lúcio, Soldier: 76, D.Va, Wrecking Ball), a mis-hear is refused with
  the flash the board already has, and a badge shows the microphone is
  live; off by default, a button in the header turns it on. Cost: a day,
  half of it the name matching; nothing leaves the browser.
- **Simulation and mathematical proving.** Two ways to check what the
  score claims. (a) A fight simulation from the kits' own numbers -
  damage and healing per second, pools, ranges, cooldowns - that plays a
  six against a six for a few seconds of engagement and says who is
  standing, so a comp's score can be set against a modelled fight rather
  than trusted; deterministic, seeded where it must draw. (b) Proofs of
  the solver's properties, as tests where they can be and as derivations
  on the math page where they cannot: the same board gives the same six;
  scaling every weight by one factor leaves the argmax unchanged; a
  normalised term stays within 0..1 and the reference sample bounds it;
  a rule at weight 0 is the objective
  without it; the optimum moves with a rule's weight and never back;
  every six's breakdown sums to its score, in every form; blue's optimal
  on a board is infer on blue's draft.
  Cost: (a) three to four days, the kit model most of it; (b) a day for
  the tests, a day for the page.
- **Recorded matches, playbook validation and learned weights.** The
  owner's, for later; the commit that follows 0ad5577 removed all three.
  A played map is recorded by hand - the map, blue's side, blue's result,
  both sixes as they stood longest on the field and the bans, blue always
  the owner's team - from a record tab on the board, a `/record` skill or
  a `record_match` tool, checked as the board checks a board (six a team,
  at most two tanks, a side on a sided map), stamped with the playbook's
  digest and stored under the `user` source. The playbook is judged
  against the recorded maps: each rescored from blue's seat, then models
  from a coin flip to the heroes plus the playbook score, fitted and
  scored out of sample on a time and a sessions split by log loss and
  Brier with intervals over sessions, each strategy family ablated, a
  playbook judged only on the maps from the first one played under its
  digest, and no verdict below (5.6 / b)^2 decided maps. Once about 191
  decided maps exist - enough to tell an even map from one won 60% of the
  time - the weights learn from them, the default engine's three
  included, the sliders the manual override and every change a
  tuning-log line. A fit only proposes: a weight changes when the owner
  accepts it through `tune`, and a proposal that does not beat the
  held-out score is refused. Cost: a day to restore the removed code from the tree
  before that commit - about 2,400 lines and 980 of tests - with a new
  migration for the two tables and the changes since; a day more for the
  learned weights once the maps exist.
- **Memoize the per-hero parts of the metrics.** `team.team_metrics`
  rebuilds each hero's pool, kit sums and keyword sets for every six it
  prepares, and is ~59% of a board under the exact search, nearly all of
  it the scale's 1,200 reference sixes; the search itself scores a few
  dozen. A per-world term table measured 3x on the function. Cost: a
  day; risk: none to the answer if the memo is keyed on the hero and the
  map.
- **What the scrub left in the data layer.** Domina's weapon publishes no
  rate (dps 0); conditional cooldowns are mis-split for some abilities;
  the match-up reader gives no verdict on about two in three written
  wiki cells, and seven hero articles have no written cell. Cost: two
  days.
- **Facts no metric reads.** The ability stats hold speed buffs and
  damage cuts (`mspeed_buff`, `damage_red`) that no metric in
  `facts/team.py` or `facts/compute.py` reads. Knockbacks as their own
  count (Control's edges), damage beams apart from healing beams, area
  healing apart from area damage. Cost: a day each.
- **A share's zero is one six.** Blue's floor is the lowest of its
  1,200 reference sixes, so one pathological six sets every share on the
  board and a roster or rates change moves them all through it; a floor
  far below the field crowds every share toward 100. A low quantile (the
  5th percentile) holds still, read off the sample's sorted scores. Cost:
  half a day, and every share moves once.
- **Bound the real-valued sums jointly.** The fold bounds the default
  engine together with the heaviest terms on per-pick counts of 0 or 1,
  four counts at most, so a six's worth and its counts come off the same
  picks (`Bound.bounds`). A term on a real-valued sum is still bounded
  apart, on its own best heroes: `damage-breaks-two-tanks` on
  `team.dps_floor` and `heal-rate` on the healing shortfall, both loose
  beside the engine on real boards. A linear upper bound on each, folded
  into the same pass, would take them in. Cost: a day, with its fuzz.
- **A fold sized by what it prunes.** The fold reads four counts at most
  (`FOLD_COUNTS`), the heaviest rules first, since the vectors it weighs
  multiply with each count: on Ilios with twelve more count rules at
  weight 0.5, folding every count took about 18 s a search and four
  under 2 s. Where count rules outweigh the default engine the whole
  fold prunes more than it costs: eight more at weight 5 took about 4 s
  folded whole and 7 s at four. A cap that weighs what a count's rules
  can move a six against the vectors the count adds would take both.
  Cost: a day, with test_bounds.
- **A strict dead-CSS test.** The test word-matches class names, so a dead
  compound selector passes (`.hcard .legend` did). Needs an exception list
  for the four classes built by concatenation.
- **Fetch the sources concurrently, one polite pace per host.** Blizzard
  and the wiki can be pulled at the same time while each keeps its delay; the database writes keep their order (heroes before
  kits). Only the first build and the weekly full refresh get faster.
  Cost: a day; risk: the politeness must stay per host, not per thread.
- **Run the test suite in parallel.** A worker plugin would take the
  local run from a little over two minutes to under one. The
  database-bound tests share one cluster and mostly read; the
  cache-driven pulls roll back. Cost: an hour; risk: a test that assumed
  it ran alone.
- **One writer at a time.** Nothing serialises the writers across
  processes: the refresher's start-up refresh and a session's `sync_all`
  can run together when the cached pages are 20 hours old, so Blizzard
  is asked at twice its pace and two DELETE-then-INSERT reloads can
  interleave. A `pg_try_advisory_lock` taken by `refresh_once` and the
  door's pulls, `sync_all`, `db_rebuild`, `db_migrate` and
  `load_authored`, with the callers told to wait on it, serialises every
  writer whichever process it runs in. Cost: half a day.

## Fact engine: more dependent variables

About half the fact kinds on a full board are independent (one hero, one
map, the meta, the bans); the rest are intersections (hero x map, hero x
enemy, hero x ally, the team, the matchup). What the data can still
yield, best first:

- **Refuse a second heuristic on an aliased metric.** Several keys are
  one measure under two names - every `matchup.*_diff` normalises exactly
  like its blue half because red is constant across a board's sample,
  `safe_count` is 6 minus `exposed_count`, `heal_ratio` is
  `heal_peak_supports` over a constant - so the catalog should refuse a
  second heuristic on an alias of a metric already in use. Two tags are
  still loose: `team.deployables` counts Reinhardt's, Sigma's and
  Ramattra's barriers and Mei's wall; `team.hitscan` counts support and
  tank guns. Cost: half a day for the alias table and the catalog check,
  half a day for the tags.
- **Tag every fact independent or dependent.** Each fact kind names the
  tables it joins (none for an independent one); the facts tab shows the
  tag and the board's counts by kind, so the equation's two terms are
  visible per board. Cost: half a day.
- **Pairwise numbers, blue pick against red pick.** One-shot: whose
  biggest hit meets whose pool. Time to kill: pool over damage floor,
  each way. Out-range: whose longest reach exceeds whose. All from
  numbers the hero facts already carry; today they exist only summed per
  team. Cost: a day; the matrix is 36 pairs at most.
- **Tool against tool, per pair.** Anti-heal against a healer, a piercer
  against a barrier holder, hitscan against a flyer, crowd control
  against an engage tool, an invulnerability against a damage ultimate, a
  cleanse against a debuff. The team-level "wars" exist; the per-pair
  version names who answers whom and with what, from the kit keywords
  plus a constant in `facts/compute.py` of which tool beats which.
  Cost: two days, half of it the constant.
- **History across captures.** Every rates pull appends a snapshot; only the last step
  is a fact. A hero's win-rate series, who is rising and falling, and the
  patch each change followed. Cost: a day.
- **Gaps named, not counted.** Coverage names the red picks still
  unanswered; name the pick nobody protects and the enemy nobody
  out-ranges too. Cost: an hour each.
- **Side-specific team facts.** On attack, the engage tools and anti-heal
  the team brings; on defense, its deployables and barriers. A side
  constraint would read these; a fact should state them. Cost: an hour.
- **What the community says and no metric measures.** Building the
  community playbook left these unexpressed, each said by several voices:
  rush as a style and speed boost (Lúcio, Juno); peel as its own tool
  set; main-tank and main-healer tags; per-role splits (a support line's
  damage, a tank pair's synergy, mobility per role); negative synergies
  (pairs that clash); healing and defensive ultimates as sustain (only
  damage ultimates carry a figure); projectile-eating tools (Defense
  Matrix, Kinetic Grasp) and hack against deployables; damage mitigation;
  a hero's win-rate variance across maps (generalist or specialist); ult
  charge lost on a swap. Each is a metric in `facts/compute.py` first,
  then a rule. Cost: an hour to a day each; the per-role splits are the
  cheapest and unlock the most.

What the sources do not publish, so no fact can: per-map rates by rank,
per-side rates, per-stage rates, and a strength for a counter beyond the
few match-ups the wiki rates (the counters table is a list).
