# Backlog

What is worth doing next, why, and what it would cost. Ordered by payoff
over blast radius; the first is the one to pick up. The maintainer skill
keeps it current.

## Next

- **Blue's seat reads red's likely six through the counter term alone.**
  Until red reveals a pick, `engine.board` hands blue's seat, current,
  fill, swaps and stages the likely six as red's picks (`enemy =
  draft.red or tuple(expected.blue)`), so every `enemy.*` and `matchup.*`
  metric reads it - `heal-rate`'s `matchup.heal_shortfall` among them -
  and the scale's field ranks against it; `infer`, which reach proves
  against, reads an empty red. docs/inference.md and the math page say
  the counter term alone reads the likely six. The seats take
  `draft.red` as it is, `base.opponent` alone falls back to the likely
  six and its `same` check goes, and the plan says "counters" only where
  the counter term read it; test_engine and test_base pin today's
  reading and flip. Cost: half a day, and reach re-recorded if a board
  moves.
- **A text metric is refused as a bonus or penalty.** A strategy with
  `bonus: map.side` loads as scored, so `add_strategy` writes it, and
  every board where its guard holds then fails: `scoring._amount` reads
  `float("attack")`, and a list raises. The catalog keeps text metrics
  out of a heuristic's `metric:` and not out of an expression. Probe each
  scored expression at load - each text metric read as empty and as a
  name, each number as 0 and 1 - refuse one that does not come out a
  number, and drop `str` from `_amount`. Cost: a morning.
- **Red never reorders the scale's field.** `scale.board_prior` ranks the
  heroes whose sixes fix a seat's scale with three points for each enemy
  a hero answers, less three for each that answers it, read off
  `objective.red`; its docstring says it reads no locked pick. A red
  reveal can reorder the field, move the bounds the heuristics are
  normalised on and so move the terms of a six that did not change. Rank
  the field on the map alone (`board_prior` has no other caller) and hold
  the bounds across reds on a widened roster in a test. Cost: half a day
  and every share test.
- **What the mechanics audit left.** The `mechanics` branch (2026-09-26,
  deleted 2026-10-01; the three items above come from it) held four
  smaller points. A need's budget keys on its guard's text while its
  gate's slot keys on text and params, so one guard under two params
  shares one budget, and a need whose guarded state no reference six
  meets has no spread, reads 1 and costs nothing: key the budget on text
  and params, and give such a need its metric's unguarded bounds. One
  state written two ways (`team.supports <= 1`, `team.supports < 2`) is
  two guards and two budgets until a guard is normalised to its compiled
  comparison. `base.rate_edge` guards a missing rate and not a
  non-finite one, which then carries into the score: read it as no
  rate. `scoring.normalised` clamps to [0, 1], so a heuristic saturates
  past the highest six the sample and the field saw: widen the bounds
  with attainable extremes drawn once per board, keeping the clamp's
  guarantee. And two docstrings misdescribe their code: `counters.derive`
  keeps each loser's six best answers before it drops those the wiki
  has an edge on (the module, the function and docs/inference.md say the
  reverse), and `team.one_shots` counts picks with no melee weapon.
  Cost: a day.
- **Fuller stage texts.** 36 of the 64 stages have no text of their own
  on the wiki as the pull reads it, and most of the rest a few sentences,
  so the terrain rules score a six of their own on 8 stages of 5 maps.
  Reading each article's stage sections more fully, or a second
  paragraph per stage, is the lever that makes the plan stage by stage
  say more. Cost: the map pull and its cache; no engine change.
- **A source for the cover rule.** "Cover closes the distance" (cover
  rewards mobility, `team.mobility_count` where `map.cover` stands out)
  was drafted with the terrain rules and held back on 2026-09-30: the
  citation record has no source for it. Mine one, or file it as the
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
- **What the healing figures leave out.** `Hero.hps` now sums every
  piece over the teammates it reaches and holds a beam to its resource
  (docs/inference.md, Sustained healing). Three limits stand: the bench
  sits on Illari, Mizuki and Moira within 0.7 hp/s, each on a judgement;
  overheal is out, which favours an untargeted area heal; Brigitte's
  98.36 holds the Flail in contact throughout, 61.7 at half. The sources
  give no overheal share and no fight size. Cost: open until one does.
- **The fact engine's dependent variables.** The equation is stated per
  domain (a selection's own row, then its joins) and the math page says
  so; the joins the data can still yield are listed under "Fact engine"
  below, best first.
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
  fight odds split 100 exactly; a rule at weight 0 is the objective
  without it; the optimum moves with a rule's weight and never back;
  every six's breakdown sums to its score, in every form; each seat of a
  board is infer on that seat's draft, which holds once blue's seat reads
  red as infer does (above). The mechanics branch held the last four and
  the scaling as tests on the pooled search.
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
  against the recorded maps: each rescored from both seats, then models
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
- **One hero on most boards.** D.Mon is in most optimal sixes on the
  strength of the roster's highest win rate. A win rate on a low pick
  rate is a specialist's: weigh it by its sample.
- **A share's zero is one six.** Each seat's floor is the lowest of its
  1,200 reference sixes, so one pathological six sets every share on the
  board and a roster or rates change moves them all through it; a floor
  far below the field crowds every share toward 100. A low quantile (the
  5th percentile) holds still, read off the sample's sorted scores. Cost:
  half a day, and every share moves once.
- **Bound the metric heuristics jointly.** The exact search bounds each
  heuristic on a summed metric apart, so each takes its own best heroes;
  folding such a term's line into the default engine's joint bound (its
  metric is a per-pick sum) cut the reference playbook's nodes by half to
  two thirds in the design's prototype. The shipped playbook does not
  need it; a heavy playbook would. Cost: a day, with its fuzz.
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
- **Gaps named, not counted.** Coverage says "answers 2/3 red picks";
  name the unanswered pick, the pick nobody protects, the enemy nobody
  out-ranges. Cost: an hour each.
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

## Done

- **Swaps are scored, and the plan runs stage by stage.** A board names
  the stage in play and the map metrics read its terrain; above blue's
  picks the board suggests the swaps that pay for their cost as one
  joint answer, clickable; each phase of a route keeps its heroes unless
  a swap beats the cost, each arena is reached from the board's six, and
  every row carries a blurb from the facts. The swap cost is meta.md's
  fifth field and a slider. Twelve terrain heuristics from the citation
  record read the ground in play; the scale's field is read on the keys
  they need alone, which holds a board near half a second.
- **Blue's picks are offered the swaps that pay for their cost.** With
  blue picks the board answers which to trade and for whom, as one joint
  six: the best legal six reachable from the picks when each pick dropped
  costs the swap cost, `meta.md`'s fifth field (`swap`, share points of
  blue's span, 10 shipped), which `tune` moves and `weights=swap:<v>`
  overrides for a board. The cost is a per-hero keep bonus the bound
  carries exactly, so the search stays one exact branch and bound, held
  to enumeration in `tests/inference/test_swaps.py` and to brute force on
  real boards (`prove_exact`'s swap boards). The board draws the swaps in
  a later step, with the stage plan.
- **A tie is a draw, and the engine is verified in stages.** Tied sixes
  break by a per-board draw per hero (`scoring.draw`, seeded by the map
  and the side) in place of the mean map win rate, so a tie leaks no rate
  and favours no name; an optimal six says how many sixes share its score
  (`Solver.ties`). `tests/inference/test_stages.py` holds the null
  objective, the meta alone and dummy heuristics to enumeration on the
  synthetic World, and `tests/inference/verify_engine.py` checks the same
  stages on the built database. Two assumptions state it in the playbook:
  `ties-are-drawn` and `deterministic-not-probabilistic`.
- **The search is exact.** Branch and bound over every legal six of the
  released roster replaces the per-role pool, its sweep and the local
  search (`inference/bounds.py`, `inference/solver.py`); the process pool,
  its two settings and the `pool` knob go, and a board solves in one
  process. The search is held to enumeration in the suite and to a brute
  force of every legal six on real boards (`tests/inference/prove_exact.py`),
  and docs/inference.md says why (Why the search is exact).
- **A synergy cell no article writes reads the claim share, and
  synergy weighs 0.26.** The load keeps each written cell's article and
  reads a blank cell at the share of the written cells that claim, 0.86,
  so a pair one article claims no longer reads below a pair nobody wrote
  about; `team.unwritten_cells` counts the blanks. The owner's
  recalibration then measured the synergy score's median range at 8.1
  and set synergy from 0.1 to 0.26 through `tune`, and `meta.md`'s prose
  says both (docs/inference.md, Why an unwritten synergy pair is not
  zero; Why the weights are the playbook's).
- **An unwritten synergy pair is unknown, not zero.** `pull_synergies`
  keeps every written Team Synergy cell in `synergy_cells` (migration
  029) and keeps a rating GOOD or better that has no advice text; the
  load read a pair neither article writes at the written pairs' mean,
  1.06, which `team.synergy_score` and the default engine's synergy term
  read, and `team.unwritten_pairs` and the cohesion fact name
  (docs/inference.md, Why an unwritten synergy pair is not zero).
- **Every weight is the playbook's, under one meta.** The default
  engine's rate, synergy and counter weights leave `inference/base.py`
  for `meta.md` beside the strategy files, with a meta weight over the
  three; `tune` with id `meta` writes it, the playbook tab's Meta slider
  sets the meta for a session (`weights=meta:<v>`), and every result and
  `base.stamp` record the weights. The shipped values are the calibrated
  ones, so no score moved.
- **The engine keeps only what a board reads** - `3c78ae8`. The
  unscored-by-strategy paths, the heuristic confidence field and dead
  branches in the catalog, the solver and the frontmatter reader go.
- **Every fact on a board has a reader** - `317edd0`. Facts that
  restated others, the playbook's S record and the 5v5 reading of the
  kit go; a two-pick King's Row board drops from 826 facts to 816.
- **Patches daily** - `ade29e3`. The refresher pulls the patches before
  the rates each day, so a snapshot is stamped against a current patch
  list. `seasons`, `ability_modifiers` and `perk_ability_effects`, which
  nothing read, go in migration 028.
- **The door serves its tools alone** - `3ccb73d`. Resources, prompts,
  batches, sessions, `evaluate`, `db_init` and `list_sources` go; the
  door speaks protocol 2025-06-18.
- **The board writes nothing** - `6059487`. The weight's store button,
  `POST /api/weight` and the remote inference service go; the session
  sliders stay, and `tune` alone changes a file.
- **No model runs unattended** - `825fb41`. A bare `orchestrator.py` is
  `up`; the headless `/refresh` agents, `derive_strategies` and the run,
  agents, refresh and test verbs go.
- **The rates history is dumped nightly.** The `backup` service, on
  postgres's image and boxed like the app containers, writes a
  `pg_dump` into `backups/` every night and keeps fourteen: the dated
  snapshots a rebuild drops and no source gives back. The data container
  migrates a stale schema in place; a rebuild after a failed migration
  asks it for one more first, which the rotation keeps. docs/db.md has
  the restore.
- **Nothing is written to `db/raw`.** The CSV mirror and `export_csv`
  and the door's audit log are deleted.
- **The sentry is gone, and the engine runs in `ui`.** Its quarantine
  hid the failure the catalog makes loud, its patterns matched ordinary
  prose and missed real injections, and nothing read its flags; every
  write now runs under a door tool without exception. The inference
  container is merged into `ui`, which runs the engine and its pool in
  process at 2 GiB and admits boards by the sixes their searches may
  enumerate (`serve.Admission`, a 429 past a minute). `db_rebuild`
  refuses a playbook that does not load before it drops anything, which
  the sentry had been hiding by winning the race.
- **The strategies are the one user input** - `data-only-inputs` branch.
  `seasons` and `synergies` are pulled from the wiki (`pull_seasons`,
  `pull_synergies`); `map_playstyle` and `comp_archetypes` are dropped
  (migration 018): a map's styles are derived at load from the per-map
  rates and the wiki's hero playstyles, the expected shape is
  `compute.EXPECTED_SHAPE`. The authored CSVs are deleted and
  `load_authored` mirrors the strategy files only. The daily refresh
  pulls the seasons, so a snapshot is stamped with the season live that
  day. The scraped counter site is gone (migration 019): `pull_counters`
  reads the Match-Up cells of every hero's wiki article into `counters`,
  `map_strategy` is dropped and a hero's best maps are derived at load
  from Blizzard's per-map rates, the second rates population and its
  snapshots are deleted. The sources are Blizzard's site and the wiki.
- **Facts audited, strategies weighed against them, weights fitted** -
  `facts-and-weights` branch. Hero numbers rebuilt from the kit rows
  (keywords, three kit sets, units), 238 strategies
  reviewed against the database with 102 fixed, weights fitted to 117
  community comps (held-out AUC 0.79 -> 0.86), a second scrub of 71
  findings applied. Never-picked heroes 19 -> 9 of 53.
- **Every search split across a worker pool** - `scrub` branch. Static
  guards evaluated once per solver, shared guards once per candidate,
  sections as attribute lookups; the reference sample and the enumeration
  sliced across `max(6, min(cores, 12))` spawned workers, verdicts only
  crossing. A board 1.6-2.1 s -> 0.3-0.5 s, sequential 1.7x, answers
  byte-identical.
- **The community's rules are the playbook** - `community-playbook`
  branch. Three hundred mined from reddit (r/OverwatchUniversity,
  r/Competitiveoverwatch, r/Overwatch: 172 threads and 11,800 comments
  through reddit) by twelve analysts over two
  passes, standardized, stored through the validated add, checked on six
  boards and their reference samples; then five reviewers read them
  against each other and 62 went as duplicates behind aliased metrics or
  cancelling pairs, ten guards and dials were retuned and five bodies
  rewritten: 238 rules and the user's five assumptions, a citation for
  every one in `inference/README.md`. The user's hand-built rules were
  removed on their word; the queue's two-tank cap returned as a quoted
  rule. Under 300 rules a board peaked at 1.8 GB and died in its 1 GiB
  container: the solver now scores every candidate slim (score and
  tie-break only) and hydrates the winners' breakdowns, so a board peaks
  at 150 MB and solves in about 5 seconds instead of 1.5 - the
  memoization item above is the rest of the way back.
- **Maintenance, end to end** - `maintain` branch. Five parallel passes
  (the three layers, the docs and skills, the root and infrastructure):
  dead code, dead styling and stale comments out, the docs shorter and
  true, each container mounting only what it reads, the gitignore cut to
  what the tree produces, tests that could not fail replaced by pins;
  then the older migrations' comments rewritten as history, the board's
  last helper text removed, the launch configs named for the project,
  and `--cov` defined once in pyproject.
- **The look is the game's again** - `fe32e70`. Dark surfaces, Bebas
  Neue, a gold accent, red and blue for the sides.
- **Six debts cleared** - `debt` branch. The suite shares the most-read
  board (three minutes to two locally, four to three in the image); red's likely comp is a
  `Result` like every seat; the fixture playbook is the nineteen rules
  the tests use; the script trusts the engine's unscored reason; the
  math page is `ui/static/math.html`; the board script is three files
  (comps, playbook, board). Found on the way: the derive prompt anchored
  its style on rule ids the playbook no longer holds - it now falls back
  to one file per form.
- **Red's likely picks from the map and the meta** - `team-headers`
  branch. `compute.expected_picks`: their revealed picks, then the
  most-picked heroes on the map, within the queue's two-tank limit; the
  comps tab's right seat.
- **A heuristic's weight stores into its file from the board** - `f131f80`.
- **A heuristic's weight is a slider under its card** - `2156473`. Only
  heuristics have one; 1 to 10 to the hundredth with a number box for the
  exact figure; the file's weight is the inferred default and a reset; a
  setting rides with the board request (`weights=id:value`, `weights` on
  the `board` tool) and never touches the file.
- **Unscored, never 100 / 100** - `0c10dd7`. A playbook with no scoring
  term ties every legal six at zero; the board now says so.
- **The roster holds to the playbook's shape limits** - `d1b0718`.
- **Run a board's independent solves in parallel** - `5baaa95`. Blue's
  optimal and red's counter in two spawned workers, the fill in the
  parent, the pessimistic case after; a click halves on a machine with
  spare cores (2.1 s to 1.1 s), the answer is the sequential one.
- **A deterministic solver** - `bf91ef8`. Style ties broke by set order,
  so the process's hash seed could change the answer; ties break by name.
- **A 75% coverage bar and ruff at 100 columns** - `bf91ef8`.
- **Announced heroes end to end** - `382ac1a`.
