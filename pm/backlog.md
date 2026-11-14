# Backlog

What is worth doing next, why, and what it would cost. Ordered by payoff
over blast radius; the first is the one to pick up. The maintainer skill
keeps it current.

## Next

- **A private server runs the stack.** On hold at the owner's word on
  2026-10-06. The stack's clock - the refresh at 05:00, the dump at
  04:30 - runs only while the Mac is awake with Docker up, and the board
  reaches no device but the Mac. The owner chose on 2026-10-05 to host
  it on one DigitalOcean Droplet: 4 GB with weekly backups, about $29 a
  month, reached over Tailscale behind a Cloud Firewall that admits
  nothing, compose.yaml as it is. The stack ran whole on the Mac's
  Docker Desktop that day - the image, the five services, migration 030
  applied in place, a dump, a full refresh in 815 s - and has not run on
  Linux. The board answers 403 to any name but a local one
  (`db/web.py`), so its tailnet name through `tailscale serve` needs
  `--allow-host`, which the stack has no setting for: a
  `COUNTRIX_ALLOW_HOST` in `.env` that compose hands the ui container,
  and until then a server-only `compose.override.yaml` whose ui command
  passes the flag. The door stays unpublished, reached through an SSH
  tunnel, where localhost passes its guard. A non-root user owns the
  checkout, a `--depth 1` clone, with its ids in `.env` as
  `COUNTRIX_UID` and `COUNTRIX_GID`, or no container can write its bind
  mounts; `.env` also takes `POSTGRES_PASSWORD` and
  `COUNTRIX_MCP_TOKEN`, made on the server before the first start, and
  `TZ`. The caches go up first, their times kept (`rsync -a`):
  `orchestrator.py up` gives `docker compose up` ten minutes, compose
  waits there on data's health, and a build from empty caches takes
  about ten. A dump of the embedded cluster restores once the stack has
  started (docs/db.md, The nightly dump), since only migrations 011 and
  012 make the board's login, and a dump from before migration 030 wants
  `pull_terrain` after. The dumps rotate on the server's own disk and
  its weekly backup runs up to a week behind, so a copy pulled to the
  Mac keeps the rates history. A tune through the server's door writes
  the server's checkout and can stop the next pull, so the playbook
  changes on the Mac and ships through git. Whom the tailnet admits is
  the owner's call under the rates' personal-use terms. docs/security.md
  ("Nothing is hosted"), the README, the guide's install page and the
  `up` skill say the stack is local. Cost: about $29 a month; a morning
  for the first run; an hour for the setting, its test and the docs.
- **The wiki catches up with Season 5.** Season 5 began on 2026-10-06,
  and on 2026-11-14 the wiki had still not written all of it. The owner
  chose that day that Blizzard's patch notes set what the wiki lags:
  `facts/patch_notes.py` lays 26 fixes, each citing the notes' lines
  that `pull_patch_notes` stores - Sombra's Hotfix and Cyberspace rows
  and Virus gone, the stale dps fields of the Machine Pistol, the Scrap
  Gun, the Solar Rifle, the Revdraw Crossbow and Dragonblade, Trash
  Compactor's stale falloff and its 6v6 cooldown, Junker Queen's health
  in both formats, Mauga's armor, D.Va's 5v5 health, D.Mon's Fusion
  Repeater, Propulsors and Focused Fusion, Kiriko's Ofuda range,
  Deliverance's decay, Combat Fuel, and the 6v6 cooldown lines of
  Winston's and Zarya's barriers. As each article moves,
  `test_every_patch_fix_still_lays` fails and the board warns: drop that
  fix. Once Sombra's article writes Cyberspace, dump the database
  (docs/db.md), refresh the caches and `db_rebuild` - an incremental
  pull keeps Virus's row - then retire `KIT_LAGS` and re-pin what moves.
  Grímsvötn is pooled from the notes under Blizzard's label; once the
  wiki pools Watchpoint: Grimsvötn, `pull_maps` renames the row,
  `pull_terrain` reads its article, and `MAP_LAGS` retires. Cost: a
  rebuild of about 8 minutes, then the pins.
- **A missing wiki article is asked for on every pull.** The wiki's
  Abilities table named "All heroes" as a hero on 2026-11-14, and
  `pull_kits` asks for an article of that name each run: the cache keeps
  no miss, so a pull from the caches, and the tests that run one, reach
  the network for it. Caching a missing page, or reading only the names
  the roster or an announcement could hold, ends it. Cost: an hour.
