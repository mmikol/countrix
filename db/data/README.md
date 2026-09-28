# The sources - `db/data/`

Page to table. This folder pulls the DATA layer's two sources, Blizzard's
site and the Overwatch Wiki: it fetches their pages, reads them, matches
their names to the database's and stores the rows in Postgres. One package
per source, each owning the whole path from its pages to its tables, and
the two modules they share: the page cache (`cache.py`) and name matching
(`normalizer.py`).

[docs/db.md](../../docs/db.md) holds the schema - every table, column and
migration. This file names a table only to say which pull writes it.

## The folder's role

Countrix is three layers over one database, each a folder at the root:
`db/` (DATA), `facts/` (FACTS) and `inference/` (STRATEGIES and the
argmax). `door/` stands over all three, and `ui/` over the door
([docs/architecture.md](../../docs/architecture.md)). `db/` is the bottom
of the import graph, and `db/data/` is its pull half: `db/psql/` is where
the rows land, this folder is how they get there.

| who | what it does with this folder |
| --- | --- |
| [door/mcp/pulls.py](../../door/mcp/pulls.py) | calls every `run()`: one `pull_*` tool per source and domain, and `sync_all` over them all. Outside the tests, nothing else calls one |
| `db/psql/` | lends the runs the helpers they write with: `register_source`, `lookup_ids`, `identifier`, `scalar`, `now`, `current_patch`, `current_season` and `SEASON_ON_DATE` |
| `facts/` | imports only `normalizer` from this folder - `name_key` in `tables.py` and `model.py`, `ability_key` in `kit_format.py` - to key a name the way the pulls keyed it |
| the rest | reads the tables over `db.psql.default_dsn()`, never this folder |

The layer rule has three consequences here. Nothing in this folder imports
`facts/`, `inference/`, `door/` or `ui/`. Nothing here is an entry point:
no `__main__`, no command line; a pull runs when a door tool calls it. And
nothing here writes outside a door tool, so every write is checked
against the tool's schema first.

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

```
db/data/
  __init__.py             the package map; PullSummary, ArticlePullSummary
  README.md               this file
  cache.py                the page cache, its freshness, the request loop
  normalizer.py           one hero, map or ability name across sources
  blizzard/               overwatch.blizzard.com
    __init__.py           the endpoints, the sources row, BlizzardError
    heroes.py             pull_heroes: the roster and each hero page
    meta.py               pull_rates: the rates page as a dated snapshot
  wiki/                   overwatch.fandom.com, through its MediaWiki API
    __init__.py           the client: Cargo, wikitext, fetch_articles
    markup.py             the wiki's two markups, and the tidying both need
    matchup_tables.py     a hero article's Match-Ups and Team Synergy tables
    strategy_sections.py  a hero article's Strategy section, as edges
    heroes.py             pull_kits: the Cargo kit table and hero articles
    maps.py               pull_maps: modes, maps and stages
    terrain.py            pull_terrain: each map article's ground, counted
    patches.py            pull_patches: the game versions
    seasons.py            pull_seasons: the seasons that have started
    playstyles.py         pull_playstyles: dive, brawl, poke
    synergies.py          pull_synergies: the Team Synergy column
    matchups.py           pull_counters: the Match-Up column and Strategy
    kits/                 the kit pipeline pull_kits runs
      __init__.py         the pipeline's map
      kit_rows.py         a Cargo row -> a weapon, ability or perk entry
      hero_articles.py    an article -> the stats Cargo lacks, the pools
      six_a_side.py       an article -> its 6v6 kit
      measurements.py     a stat value -> its measurements
      weapons.py          firing modes grouped into weapons
      modifiers.py        a buff's quantity and target, off its wording
      kit_store.py        the kits into the tables
```

A module a pull tool runs ends in `run()`. The others read markup or
serve the one that stores, and hold no `run()` of their own. Every
package's `__init__.py` maps its files, and every module's docstring says
what it reads.

## The pull contract

Every domain module that fetches ends in one function:

```python
def run(connection: psycopg.Connection, pull: cache.PullContext) -> DomainSummary:
```

### The PullContext

What a run takes beside its connection, a frozen dataclass in `cache.py`:

| field | what it is | default |
| --- | --- | --- |
| `cache_dir` | the source's page cache folder; None reads through no cache | required |
| `session` | the requests session every page is fetched on | `cache.session()` |
| `log` | where progress lines go | `db.to_stderr` |
| `max_age` | the seconds a cached page stays fresh | None |
| `cutoff` | a `time.time()` stamp: a page written before it is stale | None |
| `stale` | 'file: error' for each page whose refetch failed and whose cached copy was read | an empty list |

The context is frozen; only the contents of `stale` change. The log
defaults to stderr because over stdio, stdout is the MCP wire: a pull
never prints. The door passes the log of the call the pull runs under.

### The summaries

| type | fields | returned by |
| --- | --- | --- |
| `PullSummary` | `tables`, the tables the run wrote, empty when it wrote none; `stale`, filled by the door | pull_rates, pull_patches, pull_seasons, pull_playstyles |
| `ArticlePullSummary` | the same, and `missing`: 'name: error' for each page or article that would not fetch | pull_heroes, pull_kits, pull_maps, pull_terrain, pull_synergies, pull_counters |

Both are TypedDicts in `__init__.py`, and each pull's summary subclasses
one with its own counts (`RatesSummary`, `KitsSummary` and the rest). What
a pull could not use, or stored ahead of the roster, goes in a list, never
out of sight:

| list | pull | what it names |
| --- | --- | --- |
| `missing` | every `ArticlePullSummary` | a page or article that would not fetch, as 'name: error' |
| `unmatched` | pull_rates, pull_playstyles, pull_synergies, pull_counters | a hero name that keys to no hero the pull looks up: every stored hero for the first two, the released ones for the last two |
| `skipped_maps` | pull_rates | a map the database lacks, never fetched |
| `unknown_heroes` | pull_kits | a hero Cargo names that the roster lacks, its kit skipped |
| `announced` | pull_kits | a hero stored ahead of release from its `{{Upcoming}}` article |
| `rejected_6v6` | pull_kits | a 6v6 figure that should parse and does not |
| `without_text` | pull_terrain | a map whose article keeps under 60 words about the ground |
| `upcoming` | pull_seasons | a season not yet started, or with no full start date |
| `skipped` | pull_patches | a count, not a list: the patch pages with no date |
| `unpaired` | pull_synergies | a released hero in no pair, with the reason |
| `contradicted` | pull_counters | a pair two articles' Match-Up cells read opposite ways |
| `unwritten` | pull_counters | a released hero whose article gives no Match-Up reading |
| `no_edge` | pull_counters | a released hero in no counter edge |
| `strategy_dropped` | pull_counters | a pair the Strategy sections read as ambiguous or contradicted |

`stale` is not the run's to fill. The door copies the context's `stale`
into the summary once `run()` returns, so a run reports only what it
wrote and read.

### The rules of a run

1. **Every page before the first write.** A run reads what it needs from
   the database, fetches every page, and only then writes, so no row stays
   locked across a fetch. pull_rates commits its read of the map ids
   before its fetches, so no transaction stays open across them either.
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
   Maps article and the Hybrid lead, the Season pages, the Team
   Composition page, and a synergies or counters pull that reads no claim
   at all. A reader of one article per entity takes what it finds: a map
   whose Gameplay section it cannot read gets no stages, and an article
   with too little kept terrain text is named in `without_text`. A page
   that would not fetch falls back to its stale copy, else to a `missing`
   line where the pull reads one page per entity, else the pull fails.

### The ways a run writes

| style | pulls | why |
| --- | --- | --- |
| upsert in place | pull_heroes, pull_maps, pull_patches, and the heroes pull_kits announces | an entity keeps its id, and the rows that hang off it survive |
| fill in | pull_kits, on the hero, ability and perk rows pull_heroes owns | Blizzard's text stays; the wiki adds kinds, keywords, pools and what Blizzard omits |
| reload whole | pull_kits's weapon, stat, modifier, perk-link and 6v6 tables (`stat_keys` is upserted), pull_terrain, pull_seasons, pull_playstyles, pull_synergies, pull_counters | the page is the whole truth: a row the source dropped goes |
| append | pull_rates | each run is one more dated snapshot, and the series is history |

pull_maps never deletes: the rates snapshots hang off `maps`, and a
`DELETE` there would cascade through every older snapshot's rows. Nothing
but `db_rebuild` drops the rates history. A map whose article will not
fetch and has no cached copy shows the difference: pull_maps keeps its
stages, and pull_terrain, which reloads both terrain tables, stores no
terrain for it.

## The page cache

`cache.py` holds the one page cache every source reads through, and the
one request loop behind it.

### The cache folders

| source | folder | a page's file |
| --- | --- | --- |
| Blizzard | `.cache-blizzard/` | `<key>.html`: the roster under its URL, a hero page under its slug, a rates page under `rates` and its sorted query, the queue filter's page under `rates_queue_vocabulary` and its two pins |
| wiki | `.cache-wiki/` | `<title>.wikitext` for an article; `cargo_<table, lowercased>.json` for a Cargo table (`cargo_abilities.json`), every page of it in one file |

Both sit at the repo root (`db.CACHE_DIRS`), are gitignored, and are
created on a pull's first use (the door's `Context.cache`). The compose
stack bind-mounts them, so the containers and the host share one cache.
`cache_key` makes a request a file name: every run of characters outside
A-Z, a-z and 0-9 becomes one underscore, so "King's Row" is
`King_s_Row.wikitext`. A file's modification time is the page's age.

### The cache sequence

`cached(pull, name, produce)` is the sequence every reader runs through:

1. A cached copy the pull counts as fresh is read, and nothing is asked
   for.
2. Otherwise `produce()` fetches the page, and its text is written over
   any older copy.
3. When the fetch fails with a `FetchError` and a copy exists, the copy is
   read, named in `pull.stale` and logged with its age in hours.
4. With no copy at all, the failure surfaces.

Without a `cache_dir`, `cached` only produces. `cached_get` is `cached`
over one GET under a policy, which Blizzard's pages use; the wiki's
`cargo_query` and `fetch_wikitext` run `cached` over its API.

### The freshness

`is_stale(path, max_age, cutoff)`: a cached page is stale when it is older
than `max_age` seconds, or was written before `cutoff`. A bound that is
None never makes a page stale.

| `max_age` | `cutoff` | a cached page is | who runs this way |
| --- | --- | --- | --- |
| None | None | fresh forever: the source is asked only for a page the cache lacks | every pull without refresh, and so `db_rebuild`: a build from the caches |
| None | the moment the refresh began | fetched again when written before it, read when written since | a pull called with `{"refresh": true}`; `sync_all`'s pulls under one shared cutoff |
| seconds | - | fetched again once older than that | no door tool; it serves a caller that wants an age bound, the tests among them |

A refresh is a cutoff, not an age of zero, because an age of zero would
refetch a page that one pull of the same refresh just wrote. Under
`sync_all`'s one cutoff, pull_kits fetches every hero article and
pull_synergies and pull_counters read them from the cache; pull_maps
fetches every map article and pull_terrain reads them.

A page leaves the cache only when a refetch overwrites it or its file is
deleted. The rates pages are keyed by their full query, so widening the
rates' granularity resumes across runs from what is on disk
([docs/db.md](../../docs/db.md#widening-the-metas-granularity)).

### The stale fallback

A page whose refetch fails keeps its cached copy, so a flaky source
degrades to yesterday's page, never to an empty table, and the pull says
so:

- The copy is named in `pull.stale` and logged as a warning, with its age.
- The door copies the list into the summary's `stale`. The tool's
  headline ends in `; stale: N`, and `sync_all`'s names the pulls that
  read one.
- pull_rates stores nothing when a page came from the stale cache: no
  snapshot is stamped, `tables` is empty, the reply reads
  `pull_rates: nothing stored; stale: N`, and the newest snapshot stays
  the last real capture.
- pull_seasons reads its era subpages one by one, not through
  `fetch_articles`: a subpage with neither a fetch nor a copy fails the
  pull whole, since a missing era would stamp its snapshots with an
  earlier era's season.

### The errors

| class | module | meaning | what follows |
| --- | --- | --- | --- |
| `FetchError` | `cache` | a page that could not be had | the stale copy, else the failure |
| `RateLimitError` | `cache` | the source answered, and its answer says to slow down | retried while attempts remain |
| `WikiError` | `wiki` | the API answered, but not with what was asked for; or a pull's reader found a page in a shape it does not know | from the client: not retried - the stale copy, else a `missing` line or the failure; from a reader, once the page is cached: fails the pull |
| `BlizzardError` | `blizzard` | the site answered in a shape neither reader knows | raised by a reader once the page is cached; fails the pull |

The last three are `FetchError`s. A requests failure - a timeout, a
dropped connection, an error status - is retried like a rate limit and
becomes a `FetchError` when the attempts run out.

## The request policies

`request(session, url, params, policy, read)` is the one request loop. It
asks for a page, raises on an error status, and hands the response to
`read`, which turns it into text or rows. Then:

- A requests failure, or a `RateLimitError` from `read`, is retried while
  attempts remain. Before each retry the session's pooled connections are
  dropped: a source that hung up on a keep-alive socket fails the same way
  down it however long the wait. The wait is `backoff`, doubled each
  attempt, capped at 60 s (`MAX_BACKOFF`).
- When the attempts run out it raises `FetchError`.
- After every page it gets, it sleeps `delay`, jittered to between 0.75
  and 1.5 times, so a long run does not arrive as a clock.

Requests run one at a time: no pull fetches two pages at once. A page the
cache serves costs no request and no pause.

`RequestPolicy(attempts, backoff, timeout, delay)` is how a source is asked.
`attempts` counts every request, the first included, so 1 means no retry.
The defaults are one attempt, a 1 s backoff, a 30 s timeout and a 1 s
delay. Each source names its own:

| policy | module | attempts | waits after a failure | timeout | pause after a page | what it paces |
| --- | --- | --- | --- | --- | --- | --- |
| `RATES_POLICY` | `blizzard/meta.py` | 6 | 5, 10, 20, 40, 60 s | 90 s | 5 s | the rates page, one request per tier and per map |
| `PAGE_POLICY` | `blizzard/heroes.py` | 3 | 1, 2 s | 30 s | 1 s | the roster and each hero page |
| `CARGO_POLICY` | `wiki/__init__.py` | 6 | 20, 40, 60, 60, 60 s | 60 s | 2 s | one Cargo page of 500 rows |
| `ARTICLE_POLICY` | `wiki/__init__.py` | 1 | - | 40 s | 0.5 s | one article's wikitext |

Why each:

- **The rates page** stalls under load rather than failing outright: it
  answers a few hundred sequential requests with a 504, then closes
  connections. Some forty pages at speed is more than it takes, and being
  cut off loses the whole stage, so slower is faster overall.
- **The hero pages** all come from one host. A keep-alive socket it drops
  fails one request, and a retry on a fresh connection saves the pull.
- **Cargo** is a handful of paged requests, so it waits out a rate limit.
- **An article** is asked for once. A refresh reads some 200 of them, and
  one that fails keeps its cached copy or is missing until the next
  refresh; retrying each against a down wiki would outlast the refresh.

Every request carries the User-Agent `cache.session()` sets,
`countrix/0.1 (personal project; contact via repo)`: no key and no login.

The wiki's article HTML sits behind a bot challenge. The only open path is
its MediaWiki endpoint, `https://overwatch.fandom.com/api.php`, which
returns JSON for Cargo and raw wikitext for an article, and rate-limits.
An error the API states in its answer becomes a `RateLimitError` when it
says "rate limit", which is retried, and a `WikiError` otherwise.

## The name keys

`normalizer.py` matches one hero, map or ability across the sources and the
database.

The roster and the map pool carry names as Blizzard and the wiki write
them - "Lúcio", "D.Va", "Soldier: 76", "King's Row" - and the wiki's links
and templates write them other ways: "Lucio", "DVa", "Soldier76". A name
that fails to match is not a loud failure but a row silently dropped. The
differences are punctuation and accents, so a key folds them away.

| name | what it does | example |
| --- | --- | --- |
| `name_key(name)` | a hero or map name folded to its lowercase letters and digits, accents decomposed and stripped, not turned into spaces | "Lúcio" -> `lucio`, "Soldier: 76" -> `soldier76`, "King's Row" -> `kingsrow` |
| `hero_key(name)` | `name_key` through `RENAMED`, for a source that may still write a hero's former name | "McCree" -> `cassidy` |
| `RENAMED` | {former name_key: current name_key} | `{"mccree": "cassidy"}` |
| `ability_key(name)` | an ability name with one trailing parenthetical dropped and its case folded | "Void Accelerator (Omnic Form)" -> `void accelerator` |
| `index(name_to_id)` | a {name: id} lookup rekeyed by `name_key` | {"Lúcio": 1} -> {"lucio": 1} |
| `slug(name)` | a hero's slug as Blizzard's links write it: unaccented, lowercased, punctuation deleted, words joined by hyphens | "Soldier: 76" -> `soldier-76`, "D.Va" -> `dva` |
| `unaccented(name)` | a name with its accents dropped | "Lúcio" -> `Lucio` |

Two keys, for two problems. `name_key` is strict, and scoped to heroes and
maps, where no two names differ only by punctuation. `ability_key` is
looser, because Blizzard and the wiki disambiguate an ability differently
("Eject! (D.Mon)" against "Eject!"), and so it is only ever used within
one hero's kit, where it cannot collide across heroes.

The one way a pull matches a name to the database:

```python
hero_ids = index(psql.lookup_ids(cursor, "heroes", "name", "hero_id"))
hero_id = hero_ids.get(name_key(name))    # hero_key where a former name can appear
if hero_id is None:
    unmatched.append(name)                # reported in the summary
```

Never `.lower()`: "Lúcio" lowercased is still not `lucio`, and
"Soldier: 76" keeps its colon. A code the migrations seed in lower case -
an ability kind, a perk tier - needs no key.

| name | used by |
| --- | --- |
| `name_key` | `blizzard/meta.py` (heroes and maps), `wiki/heroes.py`, `wiki/playstyles.py`, `wiki/synergies.py`, `wiki/matchups.py`, `wiki/strategy_sections.py`, `wiki/kits/kit_store.py`; `facts/tables.py` and `facts/model.py` |
| `index` | `blizzard/meta.py`, `wiki/heroes.py`, `wiki/playstyles.py`, `wiki/synergies.py`, `wiki/matchups.py`: every pull that looks a name up against a table |
| `hero_key` | `wiki/synergies.py` and `wiki/matchups.py`, for a teammate or an enemy the wiki writes by a former name |
| `RENAMED`, `unaccented` | `wiki/matchups.py`: the names the prose may call a hero |
| `ability_key` | `wiki/kits/hero_articles.py`, `wiki/kits/six_a_side.py`, `wiki/kits/kit_store.py`; `facts/kit_format.py` |
| `slug` | `wiki/heroes.py`: an announced hero's row, keyed as Blizzard keys it, so Blizzard's listing later upserts the same row |

## The Blizzard package - `blizzard/`

overwatch.blizzard.com/en-us: ordinary web pages, fetched with
`cache.cached_get` and read with BeautifulSoup. Blizzard publishes prose
and no numbers, and omits some abilities outright; the weapons, the stats,
the missing abilities, the health pools and the maps come from the wiki.

### The endpoints - `blizzard/__init__.py`

The endpoints, named once (`BASE_URL`, `HEROES_URL`, `RATES_URL`);
`BLIZZARD`, the `sources` row every Blizzard row carries, code `blizzard`;
`BlizzardError`; and `attr`, a tag's attribute as text, since
BeautifulSoup splits a multi-valued attribute such as `class` into a list.

### The heroes pull - `blizzard/heroes.py`

pull_heroes reads the roster page and each hero page.

- **The roster.** Every hero card - its slug, taken from its link, its
  name, role, subrole and portrait - the ten subroles with the passive
  each grants, and the icon the role filter draws for each role.
- **A hero page.** Its abilities carousel - name, description, carousel
  position - and its perks section, two minor and two major; Stadium
  Powers are not read. `node_text` drops the input-icon images a
  description embeds and keeps the text of the spans that wrap its
  numbers: the schema stores gameplay text, not markup.
- **The store.** Roles in `db.ROLES` order, so `role_id` follows it;
  subroles; heroes, each marked `released`, since Blizzard listing a hero
  is its release; abilities and perks, upserted by hero and name. No
  ability is classified here: Blizzard labels neither weapons nor
  ultimates, and pull_kits fills the kind.
- **An announced hero.** A hero the wiki announced holds the wiki's kit
  until its page parses here. `_clear_wiki_kits` then deletes that kit,
  whose order would collide with Blizzard's carousel positions, and
  pull_kits, run after, adds back what Blizzard omits.
- **A page that fails.** A hero page that will not fetch is `missing`: the
  hero is stored from the roster and keeps the text it had. A page that
  fetches in a new shape fails the pull. An ability Blizzard renames
  collides with its old row on position and fails the stage on purpose: an
  update refreshes values, and a structural change to a kit is what
  `db_rebuild` is for.

### The rates pull - `blizzard/meta.py`

pull_rates reads the rates page and stores it as one new dated snapshot.
The page carries its rows as JSON on a `blz-data-table` element and its
filter vocabularies as `select` options. Three pins: the queue and the
platform are recorded on the snapshot (`queue`, `platform`, `input`), the
region on each `hero_meta` and `map_meta` row (`region_id`):

| pin | value | note |
| --- | --- | --- |
| queue | Competitive - Role Queue | the page offers no Open Queue. The queue's code is read from the page's own filter on every run, never hardcoded: Blizzard renumbered it once, and the old code silently served a different population |
| platform | console | the site spells it `input=Console`; the snapshot stores `db.PLATFORM` and `db.INPUT_DEVICE`, console and controller |
| region | Americas | on every request, the baseline included |

The run reads the map ids and commits, reads the queue filter, then fetches
the baseline (every tier together), one page per tier, and one page per map
across all ranks. Map by tier would be some 270 requests against 30, and
the source refuses a sweep that size well before its end; the rows carry a
tier, so widening needs no migration, only the inner loop. A map the
database lacks is never fetched and is listed in `skipped_maps`; a hero
the roster lacks, in `unmatched`.

It stores the region and the tiers, upserted; one `meta_snapshots` row
stamped with the capture time, the queue, the platform and input, the
current patch and the current season; `hero_meta` per tier and `map_meta`
per map, all ranks, each row under the region, with no stage, since
Blizzard's map filter stops at whole maps. Nothing is deleted, and a stale
page stamps no snapshot.

**The rates licence.** Blizzard's rates page licenses its win, pick and ban
rates for personal use only. The page caches are gitignored, and nothing
public - a README, a doc example, a published page - shows a rate figure
or text derived from one. This file quotes none.

## The wiki package - `wiki/`

overwatch.fandom.com, read through its MediaWiki API: the Cargo tables for
the structured data, article wikitext for the rest.

### The client - `wiki/__init__.py`

| name | what it is |
| --- | --- |
| `WIKI` | the `sources` row every wiki row carries, code `wiki` |
| `cargo_query(pull, table, fields)` | every row of a Cargo table, 500 a request, cached as one JSON file. Cargo exposes the wiki's structured data directly, far steadier than parsing article templates |
| `fetch_wikitext(pull, title)` | one article's raw wikitext, cached |
| `fetch_articles(pull, titles)` | every title's wikitext, as `Articles(found, missing)`: an article that raises `FetchError` is recorded as 'title: error' and logged, and the rest are read. Every per-article loop but pull_seasons' reads through this one guard: a missing era subpage fails that pull whole |
| `Articles` | what `fetch_articles` read: {title: wikitext}, and the titles that would not fetch |
| `WikiError` | the wiki answered, but not with what was asked for |
| `CARGO_POLICY`, `ARTICLE_POLICY` | the two paces, above |

### The readers

These three store nothing and hold no `run()`.

- **`markup.py`.** The wiki serves data two ways. Cargo returns rendered
  HTML, which `html_to_text` reads as Blizzard's pages are read; an
  article is MediaWiki markup, which `wikitext_to_text` reduces template
  by template, innermost first. Both share the tidying (`tidy`: links to
  their text, bold and italics, bare URLs, whitespace) and the patterns a
  loader cuts an article with: a link, a file with its caption, a
  citation, a wikitable, a comment, a tag. Beside them: `find_templates`
  and `parse_params`, brace-matched templates and their named parameters;
  `section_body`, a section to the next heading or the next top-level
  one; and `DATE` with `parse_date`, the wiki's date grammar, day or month
  first.
- **`matchup_tables.py`.** A hero article's "Match-Ups and Team Synergy"
  section: one table per role, a row per other hero, and in each row a
  Match-Up cell, advice about that hero as an enemy, and a Team Synergy
  cell, advice about it as a teammate. The wiki writes the tables two
  ways: a wikitable, or a `{{MatchupTable/<Role>}}` template with
  `<Hero>_matchup` and `<Hero>_synergy` parameters and their ratings.
  `section_rows(text, column)` reads one column of either into
  `Row(hero, cell)`, a template's rating leading its cell in bold as a
  wikitable writes it. `paragraphs` gives a cell as plain text, and
  `PLACEHOLDERS` are the cells that hold no advice. `released_articles`
  fetches every released hero's article: the one read pull_synergies and
  pull_counters share.
- **`strategy_sections.py`.** A hero article's `==Strategy==` section read
  into counter edges. Its prose names many heroes - enemies, allies,
  heroes compared with - so a hero becomes an edge only by where it sits
  around a cue. The article's own side is its hero's names, its pronoun,
  "you" and its abilities' names; every other released hero named is a
  foe. Seven cue classes - act, hit, avoid, patient, threatens, strong,
  weak - each say which side answers which. A cue reads nothing after a
  negation close before it or after a "from", in a sentence that hedges or
  compares, or, in a sentence about allies, against a foe the sentence
  does not call an enemy. A pair read both ways, or named beside a cue
  that reads no edge, is ambiguous and dropped; so is a pair two articles
  read opposite ways.

### The pulls

Each ends in `run()`, and each docstring opens "Pull + clean + store".

- **`heroes.py` - pull_kits.** The Cargo `Abilities` table, one row per
  ability (the fields in `CARGO_FIELDS`), read into each hero's kit
  (`kits/kit_rows.py`); then every hero's article (`kits/hero_articles.py`)
  for what Cargo does not register: the interaction flags, the health
  pools, the 6v6 kit. A hero the Cargo table names and the roster lacks
  gets a `heroes` row when its article is marked `{{Upcoming}}` - role,
  subrole, release day, status `announced` - so its kit loads ahead of
  release; Blizzard listing it later flips it to released. An announced
  hero whose subrole the roster does not hold yet is skipped.
  `kits/kit_store.py` writes the kits. Each article is asked for once: the
  announcements read the articles the supplement already fetched. Runs
  after pull_heroes, which owns the hero, ability and perk rows it fills
  in.
- **`maps.py` - pull_maps.** The Maps article's "Standard Play" section
  alone: each mode gallery - Control, Escort, Flashpoint, Hybrid, Push -
  and its maps. Former modes, Stadium, Arcade and the rest are out of
  scope. Each map's own article gives its stages by mode: a Control or
  Flashpoint map's submaps, from its Gameplay section's top-level bullets;
  an Escort map's stretches, where the Gameplay section opens by naming
  them and gives each a subsection; a Hybrid map's two phases, from the
  Hybrid article's lead; a Push map none. A map in two modes takes its
  stages from the first. Modes, maps and their combinations are upserted,
  never deleted; stages are upserted, so a map whose article will not
  fetch keeps the stages it had.
- **`terrain.py` - pull_terrain.** Each stored map's article, cut to the
  text about the ground: the infobox's `terrain =` line, then the kept
  sections. The lead and the sections about lore, history, media, other
  modes and events are dropped, and a rework's own subsection is kept
  wherever it sits; citations, galleries, tables, files and templates are
  stripped, and a list item under four words is dropped as a name. A lexicon
  of one pattern per feature counts the mentions of chokes, interiors, high
  ground, flanks, sightlines, open ground, hazards and cover, and each count
  per thousand words of kept text; an article with under 60 words kept says
  nothing usable. The same is counted per stage, over the sections headed by
  the stage and the paragraphs that name it and no other, 20 words at least.
  A Hybrid map's phase is named for a mode, so it takes every section headed
  Assault or Escort and, where the article names the route's stretches, the
  first stretch for the capture point and the rest for the payload.
  `map_terrain` and `stage_terrain` are reloaded whole, so a map whose
  article will not fetch and has no cached copy loses its terrain rows. Runs
  after pull_maps: a stage exists before its terrain.
- **`patches.py` - pull_patches.** The `Patches` Cargo table: each patch's
  page name and date, upserted by name. A page with no date anchors
  nothing and is skipped. Runs before pull_rates: a snapshot links to the
  most recent patch released at capture.
- **`seasons.py` - pull_seasons.** The Season article names one subpage
  per era, and each lists its seasons as `=== Season N: Name ===` headings
  with the run in parentheses beneath; a subpage that opens by naming its
  story arc prefixes its seasons with it. A season is stored once it has
  started; one without a full start date, or starting after today, is
  reported as upcoming. The table is reloaded whole, and every snapshot is
  restamped with the season live on its capture date
  (`psql.SEASON_ON_DATE`, the one rule `current_season` shares).
- **`playstyles.py` - pull_playstyles.** The Team Composition article:
  each `=== <Name> heroes ===` section and the heroes it links. A hero
  appears under every playstyle it suits, so the lists overlap by design.
  Reloaded whole: the page is the whole truth about styles.
- **`synergies.py` - pull_synergies.** The Team Synergy column of every
  released hero's article. A cell is a claim unless it is a placeholder,
  is rated below GOOD or MIRROR, or is unrated and opens by saying there
  is no synergy. A pair is stored once, the lower hero id first: score 2
  when both articles claim it, 1 when one does, and as its note the first
  sentence of the advice, cut to a clause under 120 characters. Reloaded
  whole.
- **`matchups.py` - pull_counters.** The Match-Up column of every released
  hero's article, each written cell a verdict from the article hero's
  seat: +1 it answers the enemy, -1 the enemy answers it, 0 neither. The
  wiki's MATCHUP or VS. rating decides where the cell gives one.
  Otherwise the prose is scored: the article's hero becomes "you" and the
  enemy "foe", a pronoun goes to the one whose article uses it, and
  weighted cue patterns add advantage or threat - whole in the first
  sentence and less in each later one, discounted in a concession,
  reversed at half weight after a negation. A margin under `MARGIN` is no
  verdict. A pair both articles read keeps its edge when they agree or one
  says neither, and has none when they contradict. The same articles'
  Strategy sections (`strategy_sections.py`) add edges of their own, each
  stored with the sentence that states it. `counters` is reloaded whole:
  one row means `countered_by_id` answers `hero_id`, its `basis`
  `match-up` or `strategy`. `aliases` gives the names the prose may use
  for a hero: its name, unaccented and unpunctuated, a former name
  (`RENAMED`) and its nicknames.

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
          |                         modifiers: what a buff scales, whom
          v                         it lands on
  weapons, weapon_configs, weapon_stats, abilities, ability_stats,
  ability_modifiers, perks, perk_stats, perk_ability_effects,
  stat_keys, kit_6v6, and each hero's pools
```

Nothing here ends in `run()`. Outside the tests, `wiki/heroes.py` is the
one module that imports the pipeline.

- **`kit_rows.py`.** Cargo's Abilities rows read into each hero's kit. The
  table has one row per ability: every stat its own column, a `removed`
  flag for retired kit, which is skipped, an `ability_key` column naming
  the input slot (a Cargo field, not `normalizer.ability_key`), and a
  keyword list. A row becomes a weapon's firing mode, an ability or a
  perk by its `ability_type`, which `split_type` unpicks: "Weapon;;Hip
  Fire" and "Weapon (Hip Fire)" both give the base Weapon and the mode
  Hip Fire. `ability_kind` maps a base to one of
  `db.ABILITY_KINDS`. Each kind of entry is a TypedDict - `WeaponEntry`,
  `AbilityEntry` and `PerkEntry` over `KitEntry` - and `HeroKit` holds a
  hero's three lists in Cargo's alphabetical order.
- **`hero_articles.py`.** What a hero's article adds. The
  `Template:Ability details` parameters Cargo never registers - the
  interaction flags (`ignores_matrix` and the like), `aoe`, `view_angle`,
  and `heal` where Cargo returns it empty - are merged into the kit only
  where Cargo left them empty; a retired "(old)" block is skipped. The
  infobox gives the health, shield and armor pools (`HeroProfile`), which
  Blizzard does not publish, and, in an article marked `{{Upcoming}}`,
  the role, subrole and release day (`Announcement`). `supplement_kits`
  reads every hero's article once and returns the pools, the count of
  stats merged, the articles and each hero's 6v6 kit.
- **`six_a_side.py`.** The 6v6 kit beside the 5v5 one Cargo publishes: the
  infobox's `health6v6`, `shield6v6` and `armor6v6`, and each ability
  block's `6v6_details` bullets ("Cooldown increased from 7 to 8
  seconds."). A "from A to B" line gives both figures, a multiplier
  written 2.5x held as a percent, 250; a line with no figure is kept as
  words. `with_stats` names the stat a line moves from the piece's own
  rows. A value that should be a figure and does not parse - a pool that
  is not a whole number, a change whose figures do not read - is rejected
  and named in `rejected_6v6`, never stored. Both kits stay stored:
  `facts.tables.load` lays `kit_6v6` and the `heroes.*_6v6` pools over the
  5v5 rows in the format `facts.draft.KIT_FORMAT` names
  (`facts/kit_format.py`), and `tables.load(cx, FIVE_V_FIVE)` reads the
  5v5 figures.
- **`measurements.py`.** A stat value split into rows, each a
  `Measurement(value, numerator, denominator, window, condition, text)`.
  A wiki value is rarely one number: it carries conditions in parentheses,
  variants after ";", a perk's before and after ("5 -> 7 meters"),
  alternatives ("10/20/30"), ranges, stored as a low row and a high row,
  bursts ("75 over 0.59 seconds", a window of 0.59) and yes/no glyphs,
  stored as 1 and 0. Units are canonical base quantities, and a rate is
  split into the unit on top and the unit underneath, so "125 m/s" is
  meters over seconds and nothing downstream parses a "/". A broken
  template keeps its text and no value. Every row keeps the text it was
  read from, so a misreading stays recoverable.
- **`weapons.py`.** The wiki lists one entry per firing mode.
  `group_weapons` sorts Cargo's alphabetical entries into firing order and
  groups them into weapons by three signals, in order: a shared base name
  once an "Alt Fire" or "(ADS)" suffix is dropped; a Hip Fire entry
  followed by an ADS one; a Primary Fire entry followed by a Secondary
  Fire one, unless both names end in the same noun - Mauga's Incendiary
  Chaingun and Volatile Chaingun are two weapons. Form-based entries (Mech
  and Pilot, Recon and Assault) never merge. Each ADS config is renamed
  after its weapon, "<weapon> (ADS)". `SLOT_IDS` maps a mode to the
  `weapon_config_slots` row the migrations seed.
- **`modifiers.py`.** What a buff scales and whom it lands on. The wiki
  gives a buff's size as a stat (`damage_amp`) but never says in a field
  what it scales or who takes it; the value's qualifier ("dealt", "taken",
  "received") and the ability's keywords ("amp outgoing", "amp incoming",
  "target ally") settle it. Where they settle nothing the answer is None:
  nothing here guesses.
- **`kit_store.py`.** The store. It reloads the weapon, stat, modifier and
  6v6 tables whole, dependents first; registers every stat code in
  `stat_keys`; and sets each profiled hero's 5v5 and 6v6 pools. Then, per
  hero: the weapons and their firing configs, with their stats; Blizzard's
  abilities classified, their kind and keywords set, and the ones Blizzard
  omits added after its positions; each ability's stats, in the default
  unit its stat takes (`STAT_UNITS`), and its modifiers; each perk's stats,
  and a link to every ability of the hero its text names
  (`perk_ability_effects`); the 6v6 lines. The hero, ability and perk rows
  pull_heroes owns are filled in, never replaced - except an announced
  hero's, whose wiki perks get rows of their own, two a tier, until
  Blizzard publishes the hero. A hero the roster lacks is skipped and
  named in `unknown_heroes`.

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
| 4 | `pull_terrain` | wiki | `wiki/terrain.py` | map_terrain, stage_terrain | a stage exists before its terrain |
| 5 | `pull_patches` | wiki | `wiki/patches.py` | patches | a snapshot links to the patch live at capture |
| 6 | `pull_seasons` | wiki | `wiki/seasons.py` | seasons, and each snapshot's season | a snapshot is stamped with the season live today |
| 7 | `pull_rates` | blizzard | `blizzard/meta.py` | regions, competitive_tiers, meta_snapshots, hero_meta, map_meta | it needs the heroes, the maps, the patches and the seasons |
| 8 | `pull_playstyles` | wiki | `wiki/playstyles.py` | playstyle | a style lists heroes on the roster |
| 9 | `pull_synergies` | wiki | `wiki/synergies.py` | synergies | a synergy is a pair of released heroes |
| 10 | `pull_counters` | wiki | `wiki/matchups.py` | counters | a counter is a pair of released heroes, read beside their stored abilities |

Three tools wear a name other than their module's: pull_kits runs
`wiki/heroes.py`, pull_rates `blizzard/meta.py` and pull_counters
`wiki/matchups.py`.

`sync_all` runs every `pull_*` tool in that order, then `load_authored`,
the strategies mirror, which is the inference layer's and not this
folder's. On a populated database it is an update: entities refresh in
place, the rates append a snapshot. With refresh on it runs every pull
under one cutoff, the moment it began, so a page one pull fetched is read
from the cache by the next.
`db_rebuild` drops every table, reapplies the migrations and runs
`sync_all`; without refresh it rebuilds from the caches at almost no
requests. `list_sources` reports each source, its cached page count and
the pulls that read it.

The refresher ([door/refresh.py](../../door/refresh.py)) runs pull_seasons
and pull_rates with refresh on each day, then `load_authored`; on a day the
wiki cache is older than `COUNTRIX_REFRESH_FULL_DAYS`, `sync_all` with
refresh on runs in their place. Its settings are in
[docs/db.md](../../docs/db.md#keeping-it-fresh).

```bash
.venv/bin/python -m door.mcp call list_sources                    # the sources, their caches, their pulls
.venv/bin/python -m door.mcp call pull_maps                       # one pull, from the cache
.venv/bin/python -m door.mcp call pull_rates '{"refresh": true}'  # one pull, refetched
.venv/bin/python -m door.mcp call sync_all                        # every pull, in order
.venv/bin/python -m door.mcp call sync_all '{"refresh": true}'    # every page refetched: minutes at the polite pace
```

The tool reference is [docs/mcp.md](../../docs/mcp.md).

## The tests

`tests/db/` mirrors the folder. No test here touches the network, and all
but one run without a database.

| file | what it holds |
| --- | --- |
| `test_cache.py` | the page cache and the request loop: refetch by age, the stale copy kept, a rate limit retried, an article asked for once |
| `blizzard/`, `wiki/` | one file per reader or pull |
| `recording.py` | `RecordingCursor` and its connection: a stand-in for Postgres that records every statement a store issues, with its parameters |
| `test_pull_stores.py` | every pull's `run()` over a recording connection and a page cache in `tmp_path`: the parameters it writes, its commits, its summary |
| `test_transforms.py` | the pure functions the pulls lean on: the measurement, name and map readers |
| `test_authored_inputs.py` | the two hand-written inputs, and that no pull reads a third source |
| `test_sources_from_cache.py` | invariant: every pull run from the real page caches in a transaction rolled back at the end; skipped without the caches or the database |

```bash
.venv/bin/python -m pytest -q tests/db -m 'not invariant'   # the folder's tests, no database
```

## The checklist for a new pull or table

A new source is not on it: the pulls read Blizzard's site and the wiki,
with no API key, and `tests/db/test_authored_inputs.py` holds that every
pull reads one of the two.

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
   two spaces or more, then what it is. `tests/test_docs.py` fails a file
   the map leaves out.
7. A tool in `door/mcp/pulls.py`, `@pull_tool(...)`, placed in dependency
   order. Regenerate docs/mcp.md, and add the tool to the set
   `tests/door/mcp/test_mcp.py` holds.

   ```bash
   .venv/bin/python -c "from door.mcp import tools; tools.REGISTRY.write_docs()"
   ```

8. A row in docs/db.md's table of the `data/` modules, and its place in
   [The order of a build](../../docs/db.md#the-order-of-a-build).
9. Tests in `tests/db/`, under its source's folder: its readers against
   a page the test holds, and its `run()` in `test_pull_stores.py` over
   the recording connection. Side effects are stubbed with `monkeypatch`.

### The steps for a new table

1. A migration, `db/psql/migrations/NNN_name.sql`, the next number,
   wrapped in `BEGIN;` and `COMMIT;`. A statement in an applied migration
   is never edited: a change is the next number.
2. The table carries `source_id`, referencing `sources`, and `cao`.
3. The `--` prose directly above its `CREATE TABLE` is its data dictionary
   entry, and is kept current.
4. Its number named in docs/db.md's `migrations/` row, the one inventory
   of the schema's steps.
5. A `DOC_DOMAIN` entry in `db/psql/schema.py`, keyed by the migration's
   filename, or docs/db.md files the table under foundation. No test
   catches this one.
6. The table named in `facts/tables.py`: a test greps its source for
   every table.
7. A pull fills it. After `sync_all`, no table is empty.
8. The whole chain builds an empty database: an invariant test applies
   every migration to a scratch database and compares its tables with the
   built one.
9. The schema sections of docs/db.md regenerated with `db_docs`, and the
   migration applied with `db_migrate`, which keeps the data. In Docker,
   `orchestrator.py up` rebuilds the image, and the `data` container
   rebuilds the database on a migration it lacks.

   ```bash
   .venv/bin/python -m door.mcp call db_migrate
   .venv/bin/python -m door.mcp call db_docs
   ```

## The things the folder never does

- It never reads a third source. Blizzard's site and the wiki's API are
  the only hosts, with no API key, no login, and a User-Agent that names
  the project.
- It never fetches outside `cache.request`, never without a
  `RequestPolicy`, and never two pages at once.
- It never asks for a page its cache holds fresh. Through the door, every
  cached page is fresh until a pull is asked to refresh.
- It never matches a hero or map name with `.lower()` or by a source's raw
  spelling: always through `normalizer`.
- It never drops an unmatched name out of sight: the summary lists it.
- It never writes while a page is still to fetch, and never commits half a
  pull.
- It never runs on its own and never writes outside a door tool: no
  `__main__`, no command line.
- It never writes the `user` source. The strategies are written by hand,
  through the door's playbook tools.
- It never imports a layer above `db/`, and never reads the environment.
- It never prints. Over stdio, stdout is the MCP wire; progress goes
  through `pull.log`.
- It never puts a table or column name into SQL except through
  `psql.identifier()`, nor a value except as a parameter.
- It never deletes the rates history: pull_rates appends, and a pull that
  read a stale page stamps no snapshot.
- It never hardcodes the rates queue's code, and never deletes a map or a
  mode.
- It never stores a 6v6 figure it could not read, and never guesses what
  a modifier scales or whom it lands on.
- It never publishes a rate: the page caches are gitignored, and no doc
  quotes a figure.
