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

What the sources do not publish, so no fact can: per-map rates by rank,
per-side rates, per-stage rates, and a strength for a counter beyond the
few match-ups the wiki rates (the counters table is a list).
