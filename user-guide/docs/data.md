# The data

Countrix reads two sources and nothing else: Blizzard's site and the
Overwatch Wiki. Every table but the playbook's is pulled from one of
them. There is no tracker, no third-party dataset and no API key.

| from | what |
| --- | --- |
| Blizzard | the roster - heroes, roles, subroles, portraits, ability and perk text - and the win, pick and ban rates, by rank tier and by map |
| the Overwatch Wiki | the kits and every number they publish, with the 6v6 figures beside the 5v5 ones; the maps, their modes and stages, and the ground each map's article describes; the patches; the playstyles (dive, brawl, poke); the synergy pairs; the counters |

## The rates

Blizzard's rates are Competitive Role Queue on console in the Americas:
the page offers no Open Queue. Countrix reads them as the nearest
numbers to 6v6 Open Queue anyone publishes, and the facts say so. Each
capture is kept as a dated snapshot, and the facts compare the newest
with the ones before. Blizzard's website terms grant the rates for
personal use.

## How fresh it is

- The facts tab's first fact, F1, says when the rates were captured,
  under which patch, and for which queue, platform and region.
- A patch newer than the rates raises a warning box under the bans bar:
  *1 patch(es) since the rates were captured (newest ...) - run
  pull_rates*.
- A hero the wiki announces ahead of release sits on the roster as
  *coming soon*. Once Blizzard lists the hero and the data refreshes,
  the portrait comes alive.

## The refresher

With the Docker stack up, the `refresher` container keeps the data
current on its own:

- every day at `COUNTRIX_REFRESH_AT` - 05:00 in the container's time
  zone, UTC unless `TZ` is set - the patch list and the rates, a new
  dated snapshot;
- every page of every source again, once the wiki's pages are a week
  old;
- at once on start, when the cached pages are 20 hours old.

A page that fails to refetch keeps its cached copy, so a source that is
down leaves yesterday's numbers in place.

The `backup` container dumps the database into `backups/` every night,
at `COUNTRIX_BACKUP_AT` (04:30 unless set), the newest 14 kept. The
dated rates history lives only in the database and in these dumps: a
rebuild drops it, and no source gives it back. Keep the dumps private,
since they hold the rates. [docs/db.md](https://github.com/mmikol/countrix/blob/main/docs/db.md#the-nightly-dump)
has the restore.

## Refresh it yourself

Every pull reads through a page cache, `.cache-blizzard/` and
`.cache-wiki/`, that keeps each page, so a build after the first costs
almost no requests. `{"refresh": true}` fetches the pages again:

```bash
.venv/bin/python -m door.mcp call pull_rates '{"refresh": true}'   # today's rates, a new snapshot
.venv/bin/python -m door.mcp call sync_all '{"refresh": true}'     # every source, minutes at the polite pace
.venv/bin/python -m door.mcp call db_status                        # the database's state, counts and snapshots
```

With the stack up, put `./docker-db` in front to reach its database.
The pulls keep a polite pace: a rates page every 5 seconds, a wiki page
every half second to 2 seconds. The board shows a refresh on the next
click, with no restart.

In Claude Code the house skills do it for you:

- `/patches` - a patch dropped: it pulls the patch list, refetches what
  the patch changes, and reports what moved;
- `/heroes` - the roster moved: a new hero, a reworked kit;
- `/maps` - the map pool moved: a new map, a mode or a stage.
