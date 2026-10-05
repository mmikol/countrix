# The sources - `db/data/`

Page to table. This folder pulls the DATA layer's two sources, Blizzard's
site and the Overwatch Wiki: it fetches their pages, reads them, matches
their names to the database's and stores the rows in Postgres. One package
per source, each owning the whole path from its pages to its tables, and
the two modules they share: the page cache (`cache.py`) and name matching
(`normalizer.py`).

[docs/db.md](../../docs/db.md) holds the schema - every table, column and
migration. This file names a table only to say which pull writes it.
[docs/architecture.md](../../docs/architecture.md) places the folder in
the layers: `db/psql/` is where the rows land, and this folder is how
they get there.

## The flow from page to table

```
  overwatch.blizzard.com               overwatch.fandom.com/api.php
  the roster, hero pages, rates        Cargo tables (JSON), wikitext
              |                                   |
              +-----------------+-----------------+
                                |
   cache.cached       .cache-blizzard/   .cache-wiki/
                      the fresh copy, else a fetch, else the stale copy
                                |  a page the cache cannot serve
   cache.request      one GET under the source's RequestPolicy:
                      retried, backed off, paced
                                |
                                v  raw text: HTML, JSON, wikitext
   the readers        BeautifulSoup (blizzard); markup, matchup_tables,
                      strategy_sections, kits/ (wiki)
                                |
                                v  NamedTuples and TypedDicts
   matching           each name keyed and looked up: name -> id
                                |
   run()              every page fetched first, then one transaction,
                      each row stamped with its source_id
                                |
                                v
                           PostgreSQL
                                |
   PullSummary  ->  door/mcp/pulls.py  ->  the tool's reply
```

Every pull runs the same four steps. It fetches every page it needs,
through the cache. It reads each page into typed records: the markup is
parsed once, and nothing downstream sees HTML or wikitext. It matches each
hero and map name to an id, and lists the names it cannot match. It stores
the rows in one transaction and returns a summary of what it wrote.

## The files

Each package's `__init__.py` maps its files - `db/data/`, `blizzard/`,
`wiki/` and `wiki/kits/` - and every module's docstring says what it
reads. A module a pull tool runs ends in `run()`. The others read markup
or serve the one that stores, and hold no `run()` of their own.

## The pull contract

Every domain module that fetches ends in one function:

```python
def run(connection: psycopg.Connection, pull: cache.PullContext) -> DomainSummary:
```

`cache.PullContext` is what a run takes beside its connection, and
`PullSummary` in `__init__.py` what it returns: their docstrings say what
each field holds, and each pull's summary adds its own counts. What a
pull could not use, or stored ahead of the roster, goes in a list in its
summary, never out of sight.

### The rules of a run

1. **Every page before the first write.** A run reads what it needs from
   the database, fetches every page, and only then writes, so no row stays
   locked across a fetch. A run that reads before it fetches commits that
   read before the first fetch - pull_rates its map ids, pull_terrain its
   maps, stages and released heroes, pull_synergies and pull_counters the
   released heroes - so no transaction stays open across the fetches
   either.
2. **One transaction.** A run writes, then commits once. The door opens
   the connection in a `with` block, so a run that raises leaves the
   tables as they were.
3. **One source row.** `psql.register_source`, handed `BLIZZARD` or
   `WIKI` and `psql.now()`, upserts the source's `sources` row, refreshes
   its `cao`, and returns the `source_id` every row the run writes
   carries.
4. **Names in SQL through `psql.identifier()`.** A table or column name
   reaches SQL text only as the identifier it returns, composed with
   `psycopg.sql.SQL`; every value is a parameter.
5. **A page a reader rejects fails; a page that will not fetch
   degrades.** A page a reader checks and does not recognise raises
   `BlizzardError` or `WikiError` once it is cached, and fails the pull:
   the roster and every hero page, the rates table and its filters, the
   Maps article and the Hybrid lead, the Team Composition page, and a
   synergies or counters pull that reads no claim at all. A reader of one
   article per entity takes what it finds: a map whose Gameplay section
   it cannot read gets no stages, and an article with too little kept
   terrain text is named in `without_text`. A page that would not fetch
   falls back to its stale copy, else to a `missing` line where the pull
   reads one page per entity, else the pull fails.

### The ways a run writes

| style | pulls | why |
| --- | --- | --- |
| upsert in place | pull_heroes, pull_maps, pull_patches, and the heroes pull_kits announces | an entity keeps its id, and the rows that hang off it survive |
| fill in | pull_kits, on the hero, ability and perk rows pull_heroes owns | Blizzard's text stays; the wiki adds kinds, keywords, pools and what Blizzard omits |
| reload whole | pull_kits's weapon, stat and 6v6 tables (`stat_keys` is upserted), pull_terrain, pull_playstyles, pull_synergies, pull_counters | the page is the whole truth: a row the source dropped goes |
| append | pull_rates | each new capture is one more dated snapshot, and the series is history |

pull_maps never deletes: the rates snapshots hang off `maps`, and a
`DELETE` there would cascade through every older snapshot's rows. Nothing
but `db_rebuild` drops the rates history. A map whose article will not
fetch and has no cached copy shows the difference: pull_maps keeps its
stages, and pull_terrain, which reloads both terrain tables, stores no
terrain for it.

## The page cache

`cache.py` holds the one page cache every source reads through, and the
one request loop behind it. Its docstrings are the reference: `cached`,
the sequence every reader runs through; `PullContext`, the cutoff that
makes a page stale; `request` and `RequestPolicy`, how a page is asked
for.

| source | folder | a page's file |
| --- | --- | --- |
| Blizzard | `.cache-blizzard/` | `<key>.html`: the roster under its URL, a hero page under its slug, a rates page under `rates` and its sorted query, the queue filter's page under `rates_queue_vocabulary` and its two pins |
| wiki | `.cache-wiki/` | `<title>.wikitext` for an article; `cargo_<table, lowercased>.json` for a Cargo table (`cargo_abilities.json`), every page of it in one file |

Both sit at the repo root (`db.CACHE_DIRS`), are gitignored, and are
created on a pull's first use (the door's `Context.cache`). The compose
stack bind-mounts them, so the containers and the host share one cache.

The cache never serves a stale page in place of a fetch. A page it holds
fresh is read, and nothing is asked for; without a cutoff every cached
page is fresh, so a pull or a `db_rebuild` without refresh builds from
the caches. A refresh's cutoff, the moment it began, makes every page
written before it stale, and a stale page is fetched again; `sync_all`
with refresh runs every pull under one cutoff, so a page one pull fetched
is read from the cache by the next. Only when that fetch fails is the
stale copy read, named in the summary's `stale` and logged with its age:
a flaky source degrades to yesterday's page, never to an empty table.
pull_rates then stores nothing, and the newest snapshot stays the last
real capture.

## The request policies

`cache.request` is the one request loop. It asks for a page under the
`RequestPolicy` its source names, retries a failed request or a rate
limit while attempts remain, backing off between tries, and pauses after
each page it gets; the two docstrings say how. A page the cache serves
costs no request and no pause. Each source names its own:

| policy | module | attempts | waits after a failure | timeout | pause after a page | what it paces |
| --- | --- | --- | --- | --- | --- | --- |
| `RATES_POLICY` | `blizzard/meta.py` | 6 | 5, 10, 20, 40, 60 s | 90 s | 5 s | the rates page, one request per tier and per map |
| `PAGE_POLICY` | `blizzard/heroes.py` | 3 | 1, 2 s | 30 s | 1 s | the roster and each hero page |
| `CARGO_POLICY` | `wiki/__init__.py` | 6 | 20, 40, 60, 60, 60 s | 60 s | 2 s | one Cargo page of 500 rows |
| `ARTICLE_POLICY` | `wiki/__init__.py` | 1 | - | 40 s | 0.5 s | one article's wikitext |

Every request carries the User-Agent `cache.session()` sets,
`countrix/0.1 (personal project; contact via repo)`: no key and no login.

## The name keys

`normalizer.py` matches a hero, map or ability name across the sources
and the database, and its docstring maps the keys and the problem each
solves. A pull looks a name up through `index` and `name_key`, or
`hero_key` where a former name can appear, never by `.lower()`, and
lists a name it cannot match in its summary.

## The Blizzard package - `blizzard/`

overwatch.blizzard.com/en-us: ordinary web pages, fetched with
`cache.cached_get` and read with BeautifulSoup. `blizzard/__init__.py`
maps the two pulls, `heroes.py` (pull_heroes) and `meta.py`
(pull_rates), and each module's docstring says what its pull reads and
stores.

**The rates licence.** Blizzard's rates page licenses its win, pick and ban
rates for personal use only. The page caches are gitignored, and nothing
public - a doc example, the math page, the registry - shows a rate figure
or text derived from one, except what the owner opened on 2026-10-05: the
study's results, its page and its report, and the README's screenshots of
the board, which show the numbers they compute. CounterWatch's 6v6 data,
which the study measures against, stays in the private benchmark
repository. This file quotes none.

## The wiki package - `wiki/`

overwatch.fandom.com, read through its MediaWiki API: the Cargo tables for
the structured data, article wikitext for the rest. `wiki/__init__.py` is
the client and the package's map - the seven pulls, the three readers
they share and the kit pipeline - and says why the API is the one open
path. Each module's docstring says what it reads and stores. The cells
pull_synergies keeps, and how the facts layer reads a cell no article
writes, are in docs/inference.md: [Why an unwritten synergy pair is not
zero](../../docs/inference.md#why-an-unwritten-synergy-pair-is-not-zero).

## The kit pipeline - `wiki/kits/`

```
  cargo_query("Abilities")          the Cargo table, one row per ability
          |
  kit_rows.parse_kits               {hero: HeroKit}: weapons, abilities, perks
          |
  hero_articles.supplement_kits     every hero's article, fetched once:
          |                         the fields Cargo lacks merged in, the
          |                         pools, six_a_side's 6v6 kit
          |
  wiki/heroes.run                   the upcoming heroes announced, from
          |                         the same articles
          |
  kit_store.store                   weapons: firing modes -> weapons
          |                         measurements: a value -> its rows
          v
  weapons, weapon_configs, weapon_stats, abilities, ability_stats,
  perks, perk_stats, stat_keys, kit_6v6, and each hero's pools
```

Nothing here ends in `run()`: `wiki/heroes.py` runs the pipeline, and
`kits/__init__.py` maps its modules.

## The door's pull tools

[door/mcp/pulls.py](../../door/mcp/pulls.py) registers each pull as a
tool with `@pull_tool(name, description, source=..., stored=...)`. A call:

1. builds a `PullContext` over the source's cache folder, with the door's
   log, and a cutoff when asked to refresh;
2. opens a connection and calls the module's `run()`;
3. copies the context's `stale` into the summary;
4. replies under the headline `<tool>: <stored>`, or
   `<tool>: nothing stored` when `tables` is empty, ending in `; stale: N`
   when a page came from the stale cache, over one line per count.

Registration order is dependency order, and `sync_all` runs the pulls in
it:

| # | tool | source | `run()` in | writes | runs here because |
| --- | --- | --- | --- | --- | --- |
| 1 | `pull_heroes` | blizzard | `blizzard/heroes.py` | roles, subroles, heroes, abilities, perks | everything links to a hero |
| 2 | `pull_kits` | wiki | `wiki/heroes.py` | the kit tables, each hero's pools, the announced heroes | it fills in the rows pull_heroes owns, and announces only a hero the roster lacks |
| 3 | `pull_maps` | wiki | `wiki/maps.py` | game_modes, maps, map_modes, map_stages | the terrain and the rates link to maps |
| 4 | `pull_terrain` | wiki | `wiki/terrain.py` | map_terrain, stage_terrain | a stage exists before its terrain, and pull_kits has fetched the hero articles whose map-strategy notes it reads |
| 5 | `pull_patches` | wiki | `wiki/patches.py` | patches | a snapshot links to the patch live at capture |
| 6 | `pull_rates` | blizzard | `blizzard/meta.py` | regions, competitive_tiers, meta_snapshots, hero_meta, map_meta | it needs the heroes, the maps and the patches |
| 7 | `pull_playstyles` | wiki | `wiki/playstyles.py` | playstyle | a style lists heroes on the roster |
| 8 | `pull_synergies` | wiki | `wiki/synergies.py` | synergies, synergy_cells | a synergy is a pair of released heroes |
| 9 | `pull_counters` | wiki | `wiki/matchups.py` | counters | a counter is a pair of released heroes, read beside their stored abilities |

docs/db.md says what `sync_all` and `db_rebuild` do ([The order of a
build](../../docs/db.md#the-order-of-a-build)) and what the refresher
runs and when ([Keeping it fresh](../../docs/db.md#keeping-it-fresh)).

```bash
.venv/bin/python -m door.mcp call pull_maps                       # one pull, from the cache
.venv/bin/python -m door.mcp call pull_rates '{"refresh": true}'  # one pull, refetched
.venv/bin/python -m door.mcp call sync_all                        # every pull, in order
.venv/bin/python -m door.mcp call sync_all '{"refresh": true}'    # every page refetched: minutes at the polite pace
```

The tool reference is [docs/mcp.md](../../docs/mcp.md).

## The tests

`tests/verification/db/` holds the layer's tests, one file per reader or
pull under `blizzard/` and `wiki/`. `test_pull_stores.py` runs every
pull's `run()` over `recording.py`'s connection, a stand-in for Postgres
that records every statement a store issues with its parameters, and
`test_sources_from_cache.py` runs every pull from the real page caches in
a transaction rolled back at the end. No test touches the network. A test
marked `invariant` needs the built database and skips without one.

```bash
.venv/bin/python -m pytest -q tests/verification/db -m 'not invariant'   # the folder's tests, no database
```

## The checklist for a new pull or table

A new source is not on it: the pulls read Blizzard's site and the wiki,
with no API key, and `tests/verification/db/test_authored_inputs.py` holds
that every pull reads one of the two.

### The steps for a new pull

1. A module in its source's package, named for its domain, whose
   docstring opens "Pull + clean + store" and says what it reads. It
   extracts first, markup to NamedTuples, and stores second.
2. It ends in `run(connection, pull)`, returning a TypedDict over
   `PullSummary`, or over `ArticlePullSummary` when it reads one page per
   entity; `tables` names every table it writes.
3. It fetches only through its package's helpers - `cached_get` under the
   source's policy, or `cargo_query`, `fetch_wikitext` and
   `fetch_articles` - and every page before its first write. A new kind of
   request gets a `RequestPolicy` of its own, paced for its source.
4. It matches names through `normalizer`, and lists the ones it cannot
   match in its summary.
5. It registers its source, stamps `source_id` on every row, names a table
   or column only through `psql.identifier()`, passes every value as a
   parameter, commits once and logs through `pull.log`.
6. A line for it in its package's `__init__.py` map: indented, the name,
   two spaces or more, then what it is. `tests/qa/test_docs.py` fails a file
   the map leaves out.
7. A tool in `door/mcp/pulls.py`, `@pull_tool(...)`, placed in dependency
   order. Regenerate docs/mcp.md, and add the tool to the set
   `tests/verification/door/mcp/test_mcp.py` holds.

   ```bash
   .venv/bin/python -c "from door.mcp import tools; tools.REGISTRY.write_docs()"
   ```

8. A row in docs/db.md's table of the `data/` modules, and its place in
   [The order of a build](../../docs/db.md#the-order-of-a-build).
9. Tests in `tests/verification/db/`, under its source's folder: its readers
   against a page the test holds, and its `run()` in `test_pull_stores.py`
   over the recording connection. Side effects are stubbed with
   `monkeypatch`.

### The steps for a new table

[CLAUDE.md](../../CLAUDE.md) holds them: the table under [What the tests
hold you to](../../CLAUDE.md#what-the-tests-hold-you-to), its migration
under [House rules](../../CLAUDE.md#house-rules). Beside them:
`source_id` references `sources`, and the `--` prose directly above the
`CREATE TABLE` is the table's data dictionary entry.

## The things the folder never does

- It never reads a third source. Blizzard's site and the wiki's API are
  the only hosts, with no API key, no login, and a User-Agent that names
  the project.
- It never fetches outside `cache.request`, never without a
  `RequestPolicy`, and never two pages at once.
- It never runs on its own and never writes outside a door tool: no
  `__main__`, no command line.
- It never writes the `user` source. The strategies are written by hand,
  through the door's playbook tools.
- It never imports a layer above `db/`, and never reads the environment.
- It never prints. Over stdio, stdout is the MCP wire; progress goes
  through `pull.log`.
- It never hardcodes the rates queue's code.
- It never stores a 6v6 figure it could not read.
- It never publishes a rate: the page caches are gitignored, and no doc
  quotes a figure.
