# Backlog

What is worth doing next, why, and what it would cost. Ordered by payoff
over blast radius; the first is the one to pick up. The maintainer skill
keeps it current.

## Next

- **A private server runs the stack.** The stack's clock - the refresh at
  05:00, the dump at 04:30 - runs only while the Mac is awake with Docker
  up, and the board reaches no device but the Mac. The owner chose on
  2026-10-05 to host it on one DigitalOcean Droplet: 4 GB with weekly
  backups, about $29 a month, reached over Tailscale behind a Cloud
  Firewall that admits nothing, compose.yaml as it is. The stack ran whole
  on the Mac's Docker Desktop that day - the image, the five services,
  migration 030 applied in place, a dump, a full refresh in 815 s - and
  has not run on Linux. The board answers 403 to any name but a local one
  (`db/web.py`), so its tailnet name through `tailscale serve` needs
  `--allow-host`, which the stack has no setting for: a
  `COUNTRIX_ALLOW_HOST` in `.env` that compose hands the ui container, and
  until then a server-only `compose.override.yaml` whose ui command passes
  the flag. The door stays unpublished, reached through an SSH tunnel,
  where localhost passes its guard. A non-root user owns the checkout, a
  `--depth 1` clone, with its ids in `.env` as `COUNTRIX_UID` and
  `COUNTRIX_GID`, or no container can write its bind mounts; `.env` also
  takes `POSTGRES_PASSWORD` and `COUNTRIX_MCP_TOKEN`, made on the server
  before the first start, and `TZ`. The caches go up first, their times
  kept (`rsync -a`): `orchestrator.py up` gives `docker compose up` ten
  minutes, compose waits there on data's health, and a build from empty
  caches takes about ten. A dump of the embedded cluster restores once the
  stack has started (docs/db.md, The nightly dump), since only migrations
  011 and 012 make the board's login, and a dump from before migration 030
  wants `pull_terrain` after. The dumps rotate on the server's own disk
  and its weekly backup runs up to a week behind, so a copy pulled to the
  Mac keeps the rates history. A tune through the server's door writes the
  server's checkout and can stop the next pull, so the playbook changes on
  the Mac and ships through git. Whom the tailnet admits is the owner's
  call under the rates' personal-use terms. docs/security.md ("Nothing is
  hosted"), the README, the guide's install page and the `up` skill say
  the stack is local. Cost: about $29 a month; a morning for the first
  run; an hour for the setting, its test and the docs.
- **CI builds the image.** CI lints, types and runs the suite without a
  database; nothing builds the Dockerfile, starts a container or applies a
  migration, so a broken image, a compose file that does not parse or a
  bind mount a container cannot write on Linux shows first on the server,
  at a deploy. A job builds the image, checks `docker compose config`,
  brings `db` and `backup` up until a dump lands in `backups/`, applies
  the migration chain with `db_migrate` run in the image, and starts the
  board on the migrated, empty schema as `matrix_reader` until `/health`
  answers - never data's entrypoint, which scrapes the sources on an empty
  database. The runner's user is uid 1001, so the job sets `COUNTRIX_UID`
  and `COUNTRIX_GID` from `id`, as a server whose owner is not 1000 must.
  `orchestrator.py up` makes `backups/` so the checkout's owner owns it,
  but not the two cache folders, which Docker on Linux makes root's on a
  fresh clone: it should make all three. Cost: half a day; a few minutes a
  run.
- **A new hero meets the kit lists unread.** The facts layer reads the
  kits through 18 lists of abilities and weapons the wiki has no field
  for, most in `facts/scalars.py` (`SAVE_TOOLS`, `CASTER`, `HELD`,
  `FORM_GATED`) and `FLAG_FAMILIES` in `facts/counters.py`. The audit of
  2026-10-05 (the study page, What is hard-coded) found that emptying them
  moves the optimal open six on 25 of the 30 maps, and that of the 21
  constants keyed on a name two do nothing today, one matches a word in an
  ability's name, and eight are explained only in code comments. The
  `heroes` skill pulls a hero and reports it and names no list, so a save
  the wiki does not tag or a heal held while it lasts goes uncounted until
  someone looks; Doctrine ships 2026-10-06. A skill step sets a new hero's
  pieces beside each list's rule, each rule goes in its list's comment,
  and the idle lists are dropped or given their reason. Cost: a morning.
- **A stuck seat names only the limits it cannot mend.** Where the exact
  search proves no six keeps blue's picks, the board (`engine._barred`)
  and `infer`'s refusal (`engine._ruled_out`, the answer `/comp` reads)
  name every limit the picks break as they stand (`_broken`), mendable
  ones too: blue Ana, Mercy, Kiriko and Moira on Ilios read "breaks Never
  more than three supports, A six always fields a tank", though the two
  open slots could still take a tank. Name only the limits the bound's
  intervals prove false on every completion of every shape that seats the
  picks (`Bound._parts` reads them so), and say `not_allowed([])` where
  none is named. The end-to-end run of 2026-10-05 found it. Cost: half a
  day.
- **Every red pick: who answers it, with what, and who out-ranges it.**
  The counter matrix (`facts/counters.py`, 8cca683) reads thirteen
  mechanisms on all 2,756 ordered pairs of released heroes - burst against
  a pool, reach past a gap, hitscan against a flier, anti-heal, a piercer
  against a barrier, control, eaters, saves - but the board words a pair
  only on its 217 derived edges (`hero.vs_derived`), and the wiki's 400
  edges say who answers whom, never with what. Coverage and the plan read
  the wiki's edges alone (`World.is_countered_by`), so a red pick the wiki
  gives no answer - D.Mon, Emre, Freja, Mizuki, Shion, Sierra, Sojourn -
  reads unanswered on every board ("Nobody in the six answers Sojourn -
  respect that pick"), though the counter term pays the kits' answers to
  it. Word each blue-red pair where a mechanism fires, both ways; name the
  kits' answer where the wiki has none; and name the red pick no blue pick
  out-ranges and the blue pick exposed to a red pick no teammate answers.
  Wording only: no metric and no search moves. Cost: a day.
- **Trace coverage with sys.monitoring and run the suite in parallel.**
  CI's test step took 594 to 1,175 s over the twelve runs to f4d0ce1,
  where the host runs the database-free suite in 103 s. Most of the gap is
  coverage's default tracer: the solver and bound tests take 30 s bare, 91
  s traced and 33 s under `core = "sysmon"` in `[tool.coverage.run]`,
  which Python 3.12 runs while the suite measures no branches. Then
  pytest-xdist, in the venv but not in requirements.txt: four workers take
  the database-free suite from 103 s to 49 s, all 902 passing, with
  `test_the_draw_gives_every_hero_of_a_role_the_same_chance` (30 s) the
  floor. Name the workers, `-n 4`, never `-n auto`. The database-bound
  tests share one cluster and mostly read; the cache-driven pulls roll
  back, and the migration chain's scratch database is named by pid. Cost:
  an hour; risk: two rolled-back pulls waiting on each other's rows.
- **One writer at a time.** Nothing serialises the pulls across processes.
  The refresher refreshes on start when the cached pages are 20 hours old,
  and `/up` offers `sync_all` with refresh on the stack's door when the
  rates capture is not today - after a day off, both run at once - so two
  request loops ask Blizzard together, each at its own pace, and the
  second rates pull, which reads whether its capture is stored before it
  takes the `sources` row lock, can fail on the capture's unique key or
  store a second snapshot of the day. The reloads of one source already
  wait on each other through the `sources` row each upserts before its
  DELETE (`psql.register_source`), and the mirror locks `strategies`
  (`catalog.mirror`). A `pg_try_advisory_lock` taken by `refresh_once` and
  the door's pulls, `sync_all`, `db_rebuild` and `db_migrate`, with the
  callers told to wait on it, serialises the writers on one database; a
  host session on the embedded cluster shares only the page caches. `/up`
  reading the refresher's log before it offers a refresh closes the
  overlap the docs lead to. Cost: half a day; the skill's check, minutes.
- **The scale's field is most of a board.** A board takes 0.3 to 0.4 s;
  about 0.29 s of it is the scale's freeze, and 0.21 s of that is the
  field's 11,115 sixes read lean in `scale._field_sample` (the 1,200
  reference sixes take 0.06 s, the search 0.01 to 0.2 s). Each hero's
  parts are fields `derive_scalars` sets at load; what a six pays for is
  `team.team_metrics(only=...)` building every key of a section to read
  the seven the shipped playbook's field needs, and `team_metrics` is 57
  to 70% of a board, nine calls in ten the field's. Read on those seven
  keys alone, Ilios's field took 0.023 s, not 0.176 s, which would take a
  board to 0.2 to 0.3 s - the queue a team's clicks wait in on the private
  server. The read comes from the registry's own definitions, never a
  copy. A playbook that reads `matchup.*` prepares its field whole (0.8 s
  under the reference playbook) and gains nothing here; sharing the field
  across boards needs it to read the map alone (Red never reorders the
  scale's field). Cost: a day; risk: none to the answer, which
  `tests/verification/inference/test_scale.py` holds bit for bit.
- **The match-up reader misses plain verdicts.** It leaves 858 of the
  1,260 written Match-Up cells without a verdict, and some state one
  plainly: D.Va's article says "In a one-on-one fight, Venture demolishes
  D.Va" and the graph holds no edge between them; Genji's calls Mei's slow
  "extremely dangerous to heroes who rely on close range and high mobility
  such as yourself", while the pair's one edge, Genji over Mei, comes from
  a Strategy sentence on Deflect stopping Blizzard. A missed verdict
  leaves its pair to the kit's derived edges, at half a wiki edge's
  weight, or to none. Seven articles - D.Mon, Freja, Hazard, Shion,
  Sierra, Sojourn, Venture - write no cell, and the derived edges answer
  for them. Add the cues a hand-read sample of no-verdict cells shows
  missing, and hold the reader to that sample. Cost: a day.
- **The metrics the rules lack.** Sourced rules wait on a metric: the
  2026-10-03 research dropped some for want of one, and the community
  record names more. First the kit reads that miscount, since shipped
  rules read them: `team.team_saves` misses Lúcio's Sound Barrier, so
  `six-carries-a-save` - which the study finds changes the six more often
  than any rule but two - charges a six whose only save is his;
  `team.barrier_hp` reads Domina's Barrier Array as one segment; and
  Winston's bubble meets `tank-line-barrier`'s 600 in full, as a main
  tank's barrier. Whether Sound Barrier is a save is the owner's call: the
  rule names invulnerability, death-prevention and cleanses. Then the
  keys, cheapest first: a count of flankers (`team.flankers`; Blizzard's
  Flanker subrole is a first cut) and the supports' own damage
  (`team.dps_supports`, a sum like `team.hps_supports`); speed sources
  such as Speed Boost (`team.speed_sources`, what a rush rule needs) and
  damage cuts, from the kits' `mspeed_buff` and `damage_red`, which no
  metric reads - most are the hero's own, so each key tells a teammate's
  piece from the hero's first; peel near the backline
  (`team.support_peel`); walls and placed defences (`team.walls`,
  `team.placed_defences`), once `team.deployables` stops counting tank
  barriers (A heuristic's metric is never an alias); setup ultimates for
  combos, and healing and defensive ultimates as sustain; main-tank and
  main-healer tags, a tank pair's synergy, mobility per role, pairs that
  clash and a hero's spread of win rates across maps. Each is a metric and
  its range rule (CLAUDE.md, a new metric), then a rule through
  `add_strategy`, and each widens what a team's own playbook can say. The
  fold bounds count rules with the default engine only among the heaviest
  within `FOLD_COUNTS` (4), and the shipped rules read up to four counts,
  so a new count rule can slow a board. Facts no metric reads stay for
  later: knockbacks as their own count, damage beams apart from healing
  beams, area healing apart from area damage. Cost: an hour each for the
  save fix, a sum or a subrole count; half a day for a kit read; each a
  tuning check and a re-recorded reach fixture besides.
- **Tunings by map.** The owner's request: a heuristic's weight per map,
  applied when that map is on the board, so a rule can matter on King's
  Row and whisper on Ilios. A `when:` gate already names maps and stages
  (`edges-reward-displacement` names Nepal's Sanctum, and test_catalog
  holds each name to the database's), but a heuristic weighs the same
  wherever it applies. The weights belong in the playbook, not the
  database: a `maps:` field in a strategy's frontmatter, a weight per map,
  which `tune` writes as `maps.<map>` the way it writes `params.NAME`.
  There the playbook's digest and the reach fixture record them, NOTICE's
  grant covers them, the Docker board reads them live from its mount, and
  no rebuild drops them - `db_rebuild`, which the data container also runs
  when a migration fails, drops every table. The engine lays a board's map
  weights over the file's and under the session's sliders
  (`catalog.weighted`); the playbook tab and the registry show them when a
  map is chosen, and a fact names the map whose weights scored the board.
  Params stay the file's: a gate already names a map. The study's
  rules-by-map table, where each rule applies and changes the six, is the
  evidence to set them from, and a team that prepares map by map keeps
  them on one shared board. Cost: two days - the field and its check, the
  layering, the tab, the registry, the fact, the docs and the guide - and
  a test that the same six scores differently under two maps' weights.
- **Recorded matches, playbook validation and learned weights.** The
  owner's, for later; b674704 removed all three on 2026-09-27. Nothing
  checks the engine against a played map: `tests/validation/` is empty,
  the study says the weights are never learned from match results, and the
  fight odds' tip says they are not a chance of winning measured from
  matches. A played map is recorded by hand - the map, blue's side, blue's
  result, both sixes as they stood longest on the field and the bans, blue
  always the owner's team - through a `record_match` tool and a `/record`
  skill; the board stays read-only, since it answers GET alone and compose
  keeps `ui` off the door. It is checked as a board is (six a team, at
  most two tanks, a side on a sided map), stamped with the playbook's
  digest and `base.stamp` (`playbook_digest` leaves `meta.md` out, so the
  2026-10-04 halving moved no digest) and stored under the `user` source.
  The playbook is judged against the recorded maps: each rescored from
  blue's seat through `engine.board`, then models from a coin flip to the
  heroes plus the playbook score, and the fight odds' own slope
  (`base.LOGIT_PER_POINT`), fitted and scored out of sample on a time and
  a sessions split by log loss and Brier with intervals over sessions,
  each strategy family ablated, a playbook judged only on maps played
  under its digest and stamp, and no verdict below about 191 decided maps
  - enough to tell an even map from one won 60% of the time. Then the
  weights learn from them, the default engine's three included, the
  sliders the manual override and every change a tuning-log line. A fit
  only proposes: a weight changes when the owner accepts it through
  `tune`, and a proposal that does not beat the weights in force on the
  held-out maps is refused. Cost: two to three days to port the removed
  code - about 2,400 lines and 980 of tests - onto today's engine, where
  `engine.evaluate`, `pool_size` and `team_metrics`'s `lean` are gone,
  `ui/charts.py` is the study's and the tests sit in three folders;
  migration 031 for the two tables, and the invariant tests that pin them
  gone flipped. A day more for the learned weights once the maps exist.
- **What the mechanics audit left.** Five faults, none of which moves a
  shipped board: every need's guard holds on 147 or more of a board's
  1,200 reference sixes, and no optimal on the 46 open boards, nor any
  top-five six on 60 boards with red picks, reads a heuristic past its
  scale. Two are worth an hour now. No rate is checked for being finite:
  `blizzard.meta.parse_rows` reads Blizzard's table through `json.loads`,
  which takes NaN and Infinity, the rate columns are `numeric`, and
  `facts.tables` reads them with `float`, so a NaN corrupts the search's
  ranking with no error and an Infinity seats its hero on every board;
  read a non-finite rate as none where the load reads it, which
  `base.rate_edge`, `scale.board_prior` and `compute.expected_picks` all
  sit behind. And `team.one_shots` is described as a biggest hit "not a
  melee swing" but counts picks with no melee weapon: Reinhardt, whose 300
  is Charge's pin, is the one hero the words admit and the count leaves
  out, and the board's fact words it the same way. The other three bite a
  playbook a team writes. A need whose guarded state no reference six
  meets has no spread, reads 1 and costs nothing: give it its metric's
  unguarded bounds. `need_guard` keys a guard on its text, so
  `team.supports <= 1` and `team.supports < 2`, or one text spaced two
  ways, are two guards and two budgets: key it on the compiled comparison.
  `scoring.normalised` clamps to [0, 1], so a heuristic saturates past the
  highest six the sample and the field saw: widen the bounds with
  attainable extremes drawn once per board, keeping the clamp's guarantee.
  Cost: an hour for the rate and the wording; a day for the other three.
- **The wiki's conditional cooldowns.** Nine abilities write their
  cooldown as `value;;label::value;;label` - Illari's Healing Pylon is `7
  seconds;;default::14 seconds;;under attack` - and
  `measurements.parse_measurements` splits on `;` and reads no `::`, so
  the first value is stored with no condition and the second value and
  both labels as rows with no value: Brigitte's Barrier Shield, Illari's
  Healing Pylon, Junker Queen's Carnage, Juno's Pulsar Torpedoes,
  Reinhardt's Barrier Field, Sigma's Experimental Barrier, Sombra's Hack,
  Torbjörn's Deploy Turret and Wrecking Ball's Grappling Claw. No shipped
  rule reads `team.cooldown_median`; the hero facts and the counter
  matrix's control and save cooldowns read the first value. Cost: a
  morning, and a kit pull from the cache.
- **Red never reorders the scale's field.** `scale.board_prior` ranks the
  heroes whose sixes fix a seat's scale with three points for each of
  red's revealed picks a hero answers, less three for each that answers it
  (`objective.red`), so a reveal reorders the field and moves the low and
  high every heuristic on a metric is normalised on - the measuring stick
  `scale.sample`'s docstring says must hold still. On Ilios 50 of 53
  single reveals reorder the field and 43 move a bound; over 90 boards -
  30 maps, one, three and six red picks - the scale moved on 79, the
  optimal six on one (Route 66 against Sigma) and a six's share by 0.02
  points at the median, 1.05 at most. Rank the field on the map alone
  (`board_prior` has no other caller), hold the bounds across reds in a
  test on a roster wider than `SCALE_POOL` a role, and say so where
  CLAUDE.md and the math page describe the field reading red. Cost: half a
  day, the tests that pin a six or a share on a real board with red
  revealed, and `tests/fixtures/reach.json` where a seat moves (31 of its
  51 boards reveal red).
- **The engine's inner constants as dials.** The owner turns every term's
  weight in `meta.md`; two numbers that shape the default engine still sit
  in code, recorded in `base.stamp` but not tunable: a derived counter
  edge's weight against a wiki edge's (`DERIVED_WEIGHT` 1, `WIKI_WEIGHT`
  2, `facts/counters.py`), which the study names among the model's own
  choices, and the pick rate that halves a rate edge's trust
  (`RATE_PICK_HALF`, 3, `inference/base.py`). The private benchmark can
  price other values in memory before either becomes a dial; making one a
  `meta.md` dial is the owner's call once a value moves the yardstick. The
  derived edge's dial splits the counter tally into a wiki and a derived
  tally, both whole numbers, each weighted, so the search's joint bound
  holds; `pick_half` reads 0 as full trust and refuses a negative.
  `NEED_BUDGET` needs no dial: it binds only where two needs share a
  guard, and no shipped need does. Cost: a day - the two fields and the
  stamp, the bound's fuzz, and the constants the math and study pages
  quote.
- **Voice control for the picks.** Say "blue Ana", "red Pharah", "ban
  Widowmaker", "swap Ana for Kiriko", "clear red" and the board sets them,
  hands on the controller - for picks called out at the console. The
  browser's `SpeechRecognition` hears a phrase and a small grammar maps it
  onto the board's own calls - `toggle`, `toggleBan`, `takeSwap` (which
  already checks the bans and the role caps) and the clear buttons -
  setting a pick, never toggling it off, so a phrase heard twice keeps it.
  A phrase that opens with no command word is ignored, so team chat moves
  nothing; a mis-hear is refused with the board's flash. A hero is matched
  by the names `matchups.aliases` reads the wiki's prose by, served with
  the roster, plus spoken forms for the 53 released heroes ("seventy six",
  D.Va beside D.Mon). Audio stays on the machine only where the page can
  ask for it: desktop Chrome or Edge 139 and later, `processLocally` with
  its language pack. Safari, iOS and Chrome on Android may send it to
  Apple's or Google's service and Firefox has none, so the button says
  which. The interface needs a secure page: localhost, or HTTPS on the
  private server. Off by default, a header button turns it on and a badge
  shows the microphone is live. Cost: a day and a half, half of it the
  names, with the guide's board page.
- **A fight simulation, and three properties the proof leaves untested.**
  The study page proves the search exact and deterministic and that a
  heavier weight never lowers its own rule in the optimal six, and the
  suite holds those. Three claims rest on the formula alone: a rule at
  weight 0 is the playbook without it; a six's breakdown sums to its score
  in every result a board returns, the swap target's included, whose
  search adds a keep term that is no contribution (`test_base` sums the
  engine's three terms only); and scaling every weight by one factor moves
  no six only where no two needs share a guard, since `NEED_BUDGET` is
  fixed (the meta alone is tested). Pin each on the reference playbook. A
  fight from the kits' own numbers - damage and healing per second, pools,
  ranges, cooldowns - that plays a six against a six for a few seconds and
  says who is standing would set a comp's score and the fight odds
  (`plan.fight_odds`) against a modelled fight rather than trust them; it
  reads the kit numbers the rules already read, so it tests the rules'
  arithmetic against a fight model, never against played games. Cost: half
  a day for the three tests; three to four days for the simulation, the
  kit model most of it.
- **A strict dead-CSS test.** `tests/qa/test_stylesheet.py` passes a
  `board.css` class whose word appears anywhere in its sources, and those
  now take in the math page, the registry and the study: 77 of the
  stylesheet's 181 classes are words their prose prints, so the test
  cannot tell whether those are worn, and a dead compound selector passes
  (`.hcard .legend` did). Match a class only where markup wears it - a
  class attribute of the rendered pages, read with BeautifulSoup, or a
  class string in a script - and hold each compound selector of the
  server-rendered pages to `select`; no test renders the DOM the board's
  scripts build, so their compound selectors stay unchecked. The names the
  scripts build from data each appear whole in markup elsewhere, so no
  exception list is needed. A probe finds no dead class today. Cost: two
  hours.

## Fact engine: more dependent variables

About half the fact kinds on a full board are independent (one hero, one
map, the meta, the bans); the rest are intersections (hero x map, hero x
enemy, hero x ally, the team, the matchup). What the data can still
yield, best first:

- **A heuristic's metric is never an alias.** Min-max normalisation over a
  board's sample, where red is fixed, reads a key offset or scaled by a
  constant exactly as the key it is built from: every `matchup.*_diff`
  (pool, damage and healing floors, tempo reversed, reach once both sides
  publish one), `matchup.burst_vs_heal`, `heal_vs_burst`, `exposure_share`
  and `chew_time_theirs`, and `team.safe_count`, `coverage_share`,
  `heal_ratio` and `hps_ratio`. Two heuristics on one measure under two
  keys pay it twice, and `/strategy` checks only the rules on the same
  key. The shipped playbook holds no such pair - of the matchup keys it
  reads `heal_shortfall` alone - and reuses `team.mobility_count` and
  `team.barrier_hp` on purpose under different gates, so the guard is for
  the next rule: the catalog refuses `metric:` on an alias and names the
  key that carries it (a guard or a bonus may still read one, where the
  offset means something), and the fixture playbook's `range-war` moves to
  `team.range_median`. Cost: half a day; risk: a playbook folder elsewhere
  that names an alias stops loading until it moves.
- **History across captures.** A rates pull of a new capture appends a
  snapshot stamped with the patch live at it; the board reads two, the
  latest and the latest earlier one whose rates differ, so a hero's move
  is one step (`hero.trend`, `team.trend_sum`). A series per hero - who is
  rising and falling, and the patch each move followed - would show what a
  patch did to the meta. It pays once captures span patches: the embedded
  cluster held five on 2026-10-05, 2026-09-13 to 10-05, and a rebuild
  drops them unless the nightly dump gives them back. The rates are Role
  Queue's on console, not Open Queue's. Cost: a day.

What the sources do not publish, so no fact can: per-map rates by rank,
per-side rates, per-stage rates, and a strength for a counter beyond the
few match-ups the wiki rates (the counters table is a list).
