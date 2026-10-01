# The DATA LAYER - `db/`

Pull every source, clean it and store it in Postgres. This layer owns
`DATA = HEROES ∪ MAPS ∪ META`: the tables a board's facts are derived
from. Every row carries a `source_id`, and that is the only distinction
drawn between what was measured, what was judged and what was written by
hand. One input is written by hand, and carries the `user` source: the
strategies ([inference.md](inference.md)). Every other table is pulled
from Blizzard or the wiki.

**One door.** Every write runs under a door tool ([mcp.md](mcp.md)); a
read opens its own connection through `db.psql.default_dsn()`.

```bash
.venv/bin/python -m door.mcp list                        # the tools
.venv/bin/python -m door.mcp call db_rebuild             # build from scratch
.venv/bin/python -m door.mcp call sync_all               # update everything
.venv/bin/python -m door.mcp call pull_rates '{"refresh": true}'
```

## The layout

Each package's `__init__.py` docstring maps its modules, and each
module's docstring says what it reads. The two tables below hold what
the maps leave out: which pull writes which tables, and the schema's
steps.

### `data/` - one package per source

| module | writes | runs after |
| --- | --- | --- |
| `blizzard/heroes.py` - `pull_heroes` | `roles`, `subroles`, `heroes`, `abilities`, `perks` | nothing: it runs first |
| `wiki/heroes.py` - `pull_kits` | `abilities`, `ability_stats`, `weapons`, `weapon_configs`, `weapon_stats`, `perks`, `perk_stats`, `stat_keys`, `heroes`, `kit_6v6` | `pull_heroes` |
| `wiki/maps.py` - `pull_maps` | `game_modes`, `maps`, `map_modes`, `map_stages` | - |
| `wiki/terrain.py` - `pull_terrain` | `map_terrain`, `stage_terrain` | `pull_maps` |
| `wiki/patches.py` - `pull_patches` | `patches` | - |
| `blizzard/meta.py` - `pull_rates` | `regions`, `competitive_tiers`, `meta_snapshots`, `hero_meta`, `map_meta` | `pull_heroes`, `pull_maps`, `pull_patches` |
| `wiki/playstyles.py` - `pull_playstyles` | `playstyle` | `pull_heroes` |
| `wiki/synergies.py` - `pull_synergies` | `synergies`, `synergy_cells` | `pull_heroes` |
| `wiki/matchups.py` - `pull_counters` | `counters` | `pull_heroes` |

`wiki/kits/` is the kit pipeline `pull_kits` runs; `wiki/markup.py`,
`wiki/matchup_tables.py` and `wiki/strategy_sections.py` read the wiki's
markup and store nothing.

### `psql/migrations/` - the schema as a sequence

| folder | what it holds |
| --- | --- |
| `migrations/` | The schema as a sequence, one file per step: `001` sources and the foundation, `002` heroes, `003` maps, `004` meta, `005` playbook, `006` inference, `007` the three layers, `008` the ledger, `009` and `014` the tables that recorded matches, added and dropped again, `010` constraints and heuristics (the `strategies` table), `011` and `012` the `matrix_reader` login the `query` tool connects as, with the dynamic-SQL functions withdrawn from `PUBLIC`, `013` the assumption kind, `015` announced heroes, `016` the playbook each `strategies` row was mirrored from, `017` that column's comment, `018` `map_playstyle` and `comp_archetypes` dropped, `seasons` and `synergies` pulled from the wiki, `019` `map_strategy` and the third source's rates, snapshots and `sources` row dropped, `counters` pulled from the wiki, `020` `map_terrain`, the terrain features each map's wiki article names, `021` `stage_terrain`, with every Hybrid map's two phases and an Escort map's named stretches stored as stages, `022` the `strategies.playbook` comment under the Countrix name, `023` the columns nothing read dropped - `raw_value` on the three stat tables, `patches.platform` and `url`, `subroles.icon_url`, `stat_keys.label` and `unit`, `roles.name`, `024` and `027` the tables that recorded the owner's games, added and dropped again, `025` the 6v6 kit beside the 5v5 one: `heroes.health_6v6`, `shield_6v6` and `armor_6v6`, and `kit_6v6`, each 6v6 line of a hero's article, `026` `counters.basis` and `evidence`: each counter edge marked with the part of the article it was read in, the Match-Up column or the Strategy section, a Strategy edge with its sentence, `028` the data nothing read dropped - `seasons` and `meta_snapshots.season_id`, `ability_modifiers`, `perk_ability_effects`, `029` `synergy_cells`, the Team Synergy cells each article writes, so a pair neither article writes is told apart from one written off. A statement in an applied migration is never edited; a change is a new file, and a populated database catches up with `db_migrate`. The `--` prose above each `CREATE TABLE` is the data dictionary's text, and is kept current. |

## The order of a build

`sync_all` runs the pulls in dependency order - `blizzard.heroes`,
`wiki.heroes`, `wiki.maps`, `wiki.terrain`, `wiki.patches`,
`blizzard.meta`, `wiki.playstyles`, `wiki.synergies`, `wiki.matchups` -
then `load_authored`. Entity tables refresh in place;
each rates pull appends a dated snapshot, the series the trend facts
difference. The page caches (`.cache-blizzard/`, `.cache-wiki/` at the
repo root) make every build after the first cost almost no requests.

```mermaid
stateDiagram-v2
    [*] --> empty: docker compose up<br/>(on a host, db_rebuild<br/>creates the cluster)
    empty --> current: db_rebuild<br/>every migration, then sync_all
    empty --> unfilled: a db_rebuild whose<br/>sync_all failed
    unfilled --> current: sync_all<br/>every pull + load_authored
    current --> stale: a migration file<br/>the ledger lacks
    stale --> current: db_migrate<br/>keeps the data
    unfilled --> current: db_rebuild
    stale --> current: db_rebuild<br/>drops the rates history
    current --> current: the refresher - pull_patches + pull_rates daily,<br/>sync_all weekly, entities upsert in place,<br/>rates APPEND a dated snapshot
```

`db_rebuild` drops every table, reapplies the migrations and runs
`sync_all`, whatever the state - unless the playbook does not load, which
refuses it before anything is dropped. Docker's `data` container asks
`python -m db.psql.schema` for the state (`schema.state`), runs
`db_rebuild` on empty or unfilled and `db_migrate` on stale - a rebuild
there only when the migration fails - then serves the door; a refused
rebuild ends the container, which restarts until the playbook loads.
`db_status` and the door's `/health` report the same state, which the ui
and refresher containers wait on.

## Keeping it fresh

The `refresher` container runs the door's clock, `door/refresh.py`: once
a day `pull_patches` and `pull_rates` (a new dated snapshot), then the
strategies mirror, or `sync_all` with refresh on in their place once the
wiki cache is a week old, and a refresh at once on start when the cached
pages are 20 hours old. A page that fails to refetch keeps its cached
copy and is listed under `stale`; a rates pull that read one stamps no
snapshot and replies `pull_rates: nothing stored; stale: N`.

| setting | default | meaning |
| --- | --- | --- |
| `COUNTRIX_REFRESH_AT` | `05:00` | daily time, in the container's `TZ` (UTC unless set) |
| `COUNTRIX_BACKUP_AT` | `04:30` | the nightly dump's time, in the backup container's `TZ` (UTC unless set) - [The nightly dump](#the-nightly-dump) |

## The nightly dump

A rebuild drops every table, and the dated rates history goes with it:
the `meta_snapshots` rows and the `hero_meta` and `map_meta` rates tied
to them. No source gives it back - Blizzard's page publishes today's
rates only, and the page cache holds the last fetch alone - so the
trend facts start over. Everything else a rebuild pulls again from the
caches. The stack's `backup` service keeps the
history: postgres's own image, running a POSIX sh loop (`compose.yaml`)
that writes `pg_dump -Fc` of the database into `backups/` at the repo
root:

- on start when today's dump is missing, then nightly once the clock
  passes `COUNTRIX_BACKUP_AT`, by default half an hour before the
  refresh; the loop reads the wall clock every 15 seconds, so a host that
  slept through the time dumps on waking;
- into `.countrix-YYYY-MM-DD.dump.part`, renamed to
  `countrix-YYYY-MM-DD.dump` once `pg_dump` succeeds; a failure is tried
  twice more, a minute and then two apart, and three leave no file and
  wait for the next night;
- the newest 14 `countrix-*.dump` kept, each `0600` (umask 077), one log
  line a run;
- before `data` rebuilds a schema whose migration failed, one more:
  `prerebuild-YYYY-MM-DDTHHMMSS.dump`, which the rotation never prunes;
- a time that is not HH:MM exits 1, and `restart: unless-stopped` starts
  it again, the message in `docker compose logs backup` each time, until
  the setting is fixed; TERM ends it at once, with exit 0;
- unhealthy once the newest dump is older than 26 hours, so a missed
  night shows in `docker compose ps` and in `orchestrator.py status`.

The rebuild asks for its dump through the folder both containers mount:
`data`'s entrypoint writes `backups/.predump` and waits up to five minutes
for `backups/.predump.done`, where `backup` writes the new file's path or
`failed`; with no answer the rebuild goes on, and the newest nightly dump
holds the history. The rebuild never runs beside a dump it asked for. A
rebuild through the door's `db_rebuild` asks for none: dump first by hand
(below) when the history matters.

`orchestrator.py up` makes `backups/` before the containers start, as
the checkout's owner: left to Docker, a Linux host makes it root's and
the dump cannot write it. A dump taken after a rebuild holds the short
history since; restore the `prerebuild-*` one, or a nightly one taken
before the rebuild within 14 nights. The restore replaces the database
whole, so the snapshots taken since the dump go, and the next daily
refresh appends today's. A `prerebuild-*` dump stays until it is deleted
by hand.

The restore, from the repo root with the stack up; `backup` stops too, so
no dump holds a session that makes `dropdb` fail or reads a half-restored
database:

```bash
docker compose stop data ui refresher backup
docker compose exec -T db sh -c 'dropdb -U overwatch --if-exists overwatch && createdb -U overwatch overwatch'
docker compose exec -T db pg_restore -U overwatch -d overwatch --no-owner < backups/<file>.dump
docker compose run --rm data python -m door.mcp call db_migrate
docker compose start data ui refresher backup
```

A dump by hand, before a `db_rebuild` through the door, `0600` like the
loop's:

```bash
(umask 077 && docker compose exec -T db pg_dump -U overwatch -d overwatch -Fc > "backups/prerebuild-$(date +%Y-%m-%dT%H%M%S).dump")
```

`db_migrate` brings a dump taken under older migrations up to the
image's and keeps its rows. It runs before `data` starts, so a
migration that fails says so here: the data container's entrypoint
answers one with a rebuild, which would drop what was just restored.

## The schema

Generated from the live database by
`.venv/bin/python -m door.mcp call db_docs`; the section between the
markers is rewritten in place, the rest of this document is written by
hand.

### Data dictionary

<!-- generated:dictionary -->
Generated from the live schema (`.venv/bin/python -m door.mcp call db_docs`).

Two columns are omitted from the lists below: `source_id` (which source the
row came from, see `sources`) and `cao` - "current as of", when that row
was read. Every table but `sources` and `schema_migrations` carries both;
`sources` carries `cao` alone and `schema_migrations` neither.

| domain | tables |
| --- | --- |
| **foundation** | `schema_migrations` · `sources` |
| **HEROES** | `abilities` · `ability_kinds` · `ability_stats` · `heroes` · `kit_6v6` · `perk_stats` · `perk_tiers` · `perks` · `roles` · `stat_keys` · `subroles` · `weapon_config_slots` · `weapon_configs` · `weapon_stats` · `weapons` |
| **MAPS** | `game_modes` · `map_modes` · `map_stages` · `map_terrain` · `maps` · `stage_terrain` |
| **META** | `competitive_tiers` · `hero_meta` · `map_meta` · `meta_snapshots` · `patches` · `regions` |
| **PLAYBOOK** | `counters` · `playstyle` · `synergies` · `synergy_cells` |
| **INFERENCE** | `strategies` |


#### `abilities`

*HEROES · `002_heroes.sql`*

kind_id is NULL until pull_kits sets it. Blizzard's markup labels neither weapons nor ultimates, and its ordering does not identify them either, so nothing is guessed at scrape time.

| column | type | null | references |
| --- | --- | --- | --- |
| `ability_id` | integer | no |  |
| `hero_id` | integer | no | `heroes.hero_id` |
| `kind_id` | smallint | yes | `ability_kinds.kind_id` |
| `name` | text | no |  |
| `description` | text | no |  |
| `position` | smallint | no |  |
| `keywords` | text | yes |  |

#### `ability_kinds`

*HEROES · `002_heroes.sql`*

| column | type | null | references |
| --- | --- | --- | --- |
| `kind_id` | smallint | no |  |
| `code` | text | no |  |

#### `ability_stats`

*HEROES · `002_heroes.sql`*

One row per measurement, not per stat. A wiki value like "0.67 shots/s (max charge); 3.33 shots/s (min charge)" becomes two rows sharing a stat_key, separated by condition. Units are split into the unit on top and the unit underneath, so nothing has to parse a "/" to know what a number means. denominator_value carries the magnitude underneath - 1 for a plain rate, or the window a burst spans: "125 m/s" is 125 meters / seconds over 1, "1.25 shots/s" 1.25 shots / seconds over 1, "75 over 0.59 seconds" 75 hp / seconds over 0.59, and "14 seconds" 14 seconds with no unit underneath. A rate is therefore always value / denominator_value per unit_denominator. value is NULL where the measurement is not numeric (shot types, "partial"). value_text keeps the text each measurement was read from, so anything the parser misreads stays recoverable; the wiki markup behind it stays in the page cache. weapon_stats and perk_stats hold the same measurements for a weapon's firing config and for a perk.

| column | type | null | references |
| --- | --- | --- | --- |
| `ability_stat_id` | integer | no |  |
| `ability_id` | integer | no | `abilities.ability_id` |
| `stat_key_id` | integer | no | `stat_keys.stat_key_id` |
| `value` | numeric | yes |  |
| `unit_numerator` | text | yes |  |
| `unit_denominator` | text | yes |  |
| `denominator_value` | numeric | yes |  |
| `condition` | text | yes |  |
| `value_text` | text | no |  |

#### `competitive_tiers`

*META · `004_meta.sql`*

'all' is a real member of the tier dimension: it is the unfiltered figure the page reports, and keeping it as a row avoids a nullable dimension key. Region has no such member. Everything here is the Americas, so an "all regions" row would be a second population mixed in beside it. Bronze through Champion, plus the "All Tiers" aggregate the source reports alongside them. rank_order follows the source's own ordering.

| column | type | null | references |
| --- | --- | --- | --- |
| `tier_id` | integer | no |  |
| `code` | text | no |  |
| `name` | text | no |  |
| `rank_order` | smallint | no |  |

#### `counters`

*PLAYBOOK · `005_playbook.sql`*

Who answers whom: one row means countered_by_id answers hero_id, read in one part of a hero's wiki article (pull_counters), which basis names. match-up: the Match-Up column of the article's "Match-Ups and Team Synergy" section, each written cell read from the article hero's seat as a verdict - the other hero answers this one, this one answers the other, or neither - a verdict either way one directed edge, and a pair the two articles contradict on no edge. strategy: a sentence of the article's ==Strategy== section that names another hero beside a counter cue and says which way it runs (db/data/wiki/strategy_sections.py); evidence is that sentence, and a pair the two articles' sections contradict on gets no edge. An edge both parts state has a row for each. Reloaded whole.

| column | type | null | references |
| --- | --- | --- | --- |
| `hero_id` | integer | no | `heroes.hero_id` |
| `countered_by_id` | integer | no | `heroes.hero_id` |
| `basis` | text | no |  |
| `evidence` | text | yes |  |

#### `game_modes`

*MAPS · `003_maps.sql`*

| column | type | null | references |
| --- | --- | --- | --- |
| `mode_id` | integer | no |  |
| `code` | text | no |  |
| `name` | text | no |  |

#### `hero_meta`

*META · `004_meta.sql`*

Rates by region and tier. All rates are percentages as published (47.9 means 47.9%). These rows are across all maps.

| column | type | null | references |
| --- | --- | --- | --- |
| `hero_meta_id` | integer | no |  |
| `snapshot_id` | integer | no | `meta_snapshots.snapshot_id` |
| `hero_id` | integer | no | `heroes.hero_id` |
| `region_id` | integer | no | `regions.region_id` |
| `tier_id` | integer | no | `competitive_tiers.tier_id` |
| `win_rate` | numeric | yes |  |
| `pick_rate` | numeric | yes |  |
| `ban_rate` | numeric | yes |  |

#### `heroes`

*HEROES · `002_heroes.sql`*

The composite foreign key makes it impossible to pair a hero with a subrole belonging to a different role than the hero's own. health, shield and armor are the hero's own pool in 5v5, all in hp. Blizzard publishes none of them, so pull_kits fills them in; a hero with no shield or armor leaves those NULL rather than storing a zero the source never states. health_6v6, shield_6v6 and armor_6v6 are the same pool in 6v6 where the article's infobox gives one, NULL where it gives none and the 5v5 figure stands; a value that is not a whole number is rejected, never stored.

| column | type | null | references |
| --- | --- | --- | --- |
| `hero_id` | integer | no |  |
| `slug` | text | no |  |
| `name` | text | no |  |
| `role_id` | integer | no | `roles.role_id` |
| `subrole_id` | integer | no | `subroles.subrole_id` |
| `health` | smallint | yes |  |
| `shield` | smallint | yes |  |
| `armor` | smallint | yes |  |
| `portrait_url` | text | yes |  |
| `status` | text | no |  |
| `release_date` | date | yes |  |
| `health_6v6` | smallint | yes |  |
| `shield_6v6` | smallint | yes |  |
| `armor_6v6` | smallint | yes |  |

#### `kit_6v6`

*HEROES · `025_kit_6v6.sql`*

The 6v6 lines of each hero's kit: one row per line of the 6v6_details field an Ability_details block carries (pull_kits). piece is the block's ability name as the wiki writes it - an ability, a weapon or a perk of the hero. A line that says a stat increased or was reduced from A to B carries the stat its words name (stat_key_id, NULL where the pull maps none), from_value A and to_value B, a multiplier the wiki writes 2.5x held as the kit holds it, a percent (250). Any other line carries its words alone. A line whose figures do not parse is rejected, never stored. The 5v5 rows are left as they are; facts/kit_format.py moves a stat row from A to B when the format in force is 6v6. Reloaded whole with the kits.

| column | type | null | references |
| --- | --- | --- | --- |
| `kit_6v6_id` | integer | no |  |
| `hero_id` | integer | no | `heroes.hero_id` |
| `piece` | text | no |  |
| `stat_key_id` | integer | yes | `stat_keys.stat_key_id` |
| `from_value` | numeric | yes |  |
| `to_value` | numeric | yes |  |
| `value_text` | text | no |  |

#### `map_meta`

*META · `004_meta.sql`*

Rates per map. The source's filters compose, so a hero's rates on King's Row in Bronze are a different figure from its rates on King's Row overall, and both are published; only the whole-map figure is pulled, under tier_id 'all', which keeps the dimension key non-nullable. Region is carried but not swept: every row is the Americas. Widening either is a loop, not a migration - map x tier alone is about 270 requests against a source that refuses long sweeps.

| column | type | null | references |
| --- | --- | --- | --- |
| `map_meta_id` | integer | no |  |
| `snapshot_id` | integer | no | `meta_snapshots.snapshot_id` |
| `hero_id` | integer | no | `heroes.hero_id` |
| `map_id` | integer | no | `maps.map_id` |
| `tier_id` | integer | no | `competitive_tiers.tier_id` |
| `region_id` | integer | no | `regions.region_id` |
| `stage_id` | integer | yes | `map_stages.stage_id` |
| `win_rate` | numeric | yes |  |
| `pick_rate` | numeric | yes |  |
| `ban_rate` | numeric | yes |  |

#### `map_modes`

*MAPS · `003_maps.sql`*

One row per playable combination: the maps and modes of Standard Play, the competitive rotation (pull_maps). Every map belongs to one mode today, so this holds one row per map. It is many-to-many anyway: a map can be re-released under a second mode, and the degenerate join costs nothing.

| column | type | null | references |
| --- | --- | --- | --- |
| `map_id` | integer | no | `maps.map_id` |
| `mode_id` | integer | no | `game_modes.mode_id` |

#### `map_stages`

*MAPS · `003_maps.sql`*

Stages within a map, in play order (pull_maps). Control maps: the three stages of the Gameplay section's list (Ilios: Lighthouse, Well, Ruins). Flashpoint maps: the five points of the same list. Hybrid maps: the two phases the wiki's Hybrid article names, Assault (the capture point) then Escort (the payload). Escort maps: the stretches of the route, only where the map's article names them - the Gameplay subsections its opening lists (Havana: City Streets, Distillery, Sea Fort). Push maps: none. No source publishes per-stage rates, so map_meta.stage_id stays NULL.

| column | type | null | references |
| --- | --- | --- | --- |
| `stage_id` | integer | no |  |
| `map_id` | integer | no | `maps.map_id` |
| `position` | smallint | no |  |
| `name` | text | no |  |

#### `map_terrain`

*MAPS · `020_map_terrain.sql`*

A map's terrain, counted in its wiki article (pull_terrain). The sections about the ground and how it is played are kept - gameplay, strategy, the per-stage subsections, a rework's changes, the infobox's terrain line - and the lore, place-name lists and media are dropped. Each feature has one pattern (db/data/wiki/terrain.py): chokes, interiors, high_ground, flanks, sightlines, open_ground, hazards, cover. A map whose article has text holds all eight rows, zeros included; a map whose article has under 60 words of kept text holds none. Reloaded whole.

| column | type | null | references |
| --- | --- | --- | --- |
| `map_id` | integer | no | `maps.map_id` |
| `feature` | text | no |  |
| `mentions` | integer | no |  |
| `per_thousand` | numeric | no |  |

#### `maps`

*MAPS · `003_maps.sql`*

| column | type | null | references |
| --- | --- | --- | --- |
| `map_id` | integer | no |  |
| `name` | text | no |  |

#### `meta_snapshots`

*META · `004_meta.sql`*

| column | type | null | references |
| --- | --- | --- | --- |
| `snapshot_id` | integer | no |  |
| `captured_at` | timestamp with time zone | no |  |
| `queue` | text | no |  |
| `platform` | text | no |  |
| `input` | text | yes |  |
| `patch_id` | integer | yes | `patches.patch_id` |

#### `patches`

*META · `004_meta.sql`*

The game versions the meta moves with. A win rate is true of a patch, so a snapshot records which patch was live when it was captured. Pulled from the wiki's Patches cargo table (pull_patches); name is the wiki's own page name, since Blizzard ships most balance patches unversioned.

| column | type | null | references |
| --- | --- | --- | --- |
| `patch_id` | integer | no |  |
| `name` | text | no |  |
| `released` | date | no |  |

#### `perk_stats`

*HEROES · `002_heroes.sql`*

| column | type | null | references |
| --- | --- | --- | --- |
| `perk_stat_id` | integer | no |  |
| `perk_id` | integer | no | `perks.perk_id` |
| `stat_key_id` | integer | no | `stat_keys.stat_key_id` |
| `value` | numeric | yes |  |
| `unit_numerator` | text | yes |  |
| `unit_denominator` | text | yes |  |
| `denominator_value` | numeric | yes |  |
| `condition` | text | yes |  |
| `value_text` | text | no |  |

#### `perk_tiers`

*HEROES · `002_heroes.sql`*

| column | type | null | references |
| --- | --- | --- | --- |
| `tier_id` | smallint | no |  |
| `code` | text | no |  |
| `name` | text | no |  |
| `unlock_level` | smallint | no |  |

#### `perks`

*HEROES · `002_heroes.sql`*

| column | type | null | references |
| --- | --- | --- | --- |
| `perk_id` | integer | no |  |
| `hero_id` | integer | no | `heroes.hero_id` |
| `tier_id` | smallint | no | `perk_tiers.tier_id` |
| `name` | text | no |  |
| `description` | text | no |  |
| `position` | smallint | no |  |

#### `playstyle`

*PLAYBOOK · `005_playbook.sql`*

Which playstyle a hero belongs to, straight from the wiki's team composition page. The style vocabulary (dive, brawl, poke) is whatever the page says, kept as text rather than a three-row lookup table: the page is the vocabulary, and a new style there should load, not break.

| column | type | null | references |
| --- | --- | --- | --- |
| `hero_id` | integer | no | `heroes.hero_id` |
| `style` | text | no |  |

#### `regions`

*META · `004_meta.sql`*

| column | type | null | references |
| --- | --- | --- | --- |
| `region_id` | integer | no |  |
| `code` | text | no |  |
| `name` | text | no |  |

#### `roles`

*HEROES · `002_heroes.sql`*

| column | type | null | references |
| --- | --- | --- | --- |
| `role_id` | integer | no |  |
| `code` | text | no |  |
| `icon_url` | text | yes |  |

#### `schema_migrations`

*foundation · `008_schema_migrations.sql`*

| column | type | null | references |
| --- | --- | --- | --- |
| `filename` | text | no |  |
| `applied_at` | timestamp with time zone | no |  |

#### `sources`

*foundation · `001_initial_schema.sql`*

| column | type | null | references |
| --- | --- | --- | --- |
| `code` | text | no |  |
| `name` | text | no |  |
| `url` | text | no |  |

#### `stage_terrain`

*MAPS · `021_stage_terrain.sql`*

A stage's terrain, counted in the map's wiki article (pull_terrain) with map_terrain's features and patterns. A stage's text: every kept section under a heading that names the stage, and every paragraph or list item elsewhere that names it and no other stage. A Hybrid phase's text: every Assault or Escort section, attack and defense together; where the article names the route's stretches, the first is the capture point's and the rest the payload's. A stage with 20 words of text or more holds all eight rows, zeros included; a stage with less holds none. Reloaded whole with map_terrain.

| column | type | null | references |
| --- | --- | --- | --- |
| `stage_id` | integer | no | `map_stages.stage_id` |
| `feature` | text | no |  |
| `mentions` | integer | no |  |
| `per_thousand` | numeric | no |  |

#### `stat_keys`

*HEROES · `002_heroes.sql`*

The stat vocabulary: one row per stat code a kit carries, added by pull_kits and never reloaded. A value with no unit of its own is read in its stat's unit from STAT_UNITS in db/data/wiki/kits/kit_store.py ("damage = 90" is 90 hp), stored as the measurement's unit_numerator.

| column | type | null | references |
| --- | --- | --- | --- |
| `stat_key_id` | integer | no |  |
| `code` | text | no |  |

#### `strategies`

*INFERENCE · `010_constraints_and_heuristics.sql`*

The mirror of the playbook: one row per markdown file in inference/strategies/ - its kind (constraint | heuristic | assumption, the last added by 013), the frontmatter a machine scores by (metric, direction, weight, expressions, params) and the prose body a person argues with. Reloaded whole by load_authored and after every playbook write (tune, add_strategy, infer_strategy), so db_status and the query tool see the playbook as rows under the user source; the files remain the truth.

| column | type | null | references |
| --- | --- | --- | --- |
| `strategy_id` | text | no |  |
| `name` | text | no |  |
| `kind` | text | no |  |
| `category` | text | no |  |
| `direction` | text | yes |  |
| `metric` | text | yes |  |
| `weight` | numeric | yes |  |
| `expression` | text | yes |  |
| `params` | text | yes |  |
| `body` | text | no |  |
| `playbook` | text | no |  |

#### `subroles`

*HEROES · `002_heroes.sql`*

The ten subroles, each belonging to exactly one role, each carrying the passive it grants (e.g. "Tactician: Store excess ultimate charge.").

| column | type | null | references |
| --- | --- | --- | --- |
| `subrole_id` | integer | no |  |
| `role_id` | integer | no | `roles.role_id` |
| `code` | text | no |  |
| `name` | text | no |  |
| `passive_description` | text | no |  |

#### `synergies`

*PLAYBOOK · `005_playbook.sql`*

Which heroes work WITH which. Pulled from the Team Synergy column of the "Match-Ups and Team Synergy" section of every released hero's wiki article (pull_synergies). A cell is a claim unless it is a placeholder, rated below GOOD or MIRROR, or unrated and saying there is no synergy; a cell rated GOOD or better is a claim with no advice written too. score is 2 when both articles claim the pair, 1 when one does; note is the advice's first sentence, cut to a clause under 120 characters, or says the rating came with no advice. A pair no article claims has no row: synergy_cells says whether an article wrote it off or neither wrote it at all. No snapshot, region or tier: a judgement has no population behind it. Reloaded whole. Bidirectional, unlike counters. Synergy is a property of the PAIR: if Mei works with Tracer then Tracer works with Mei - one fact, one row. A counter is an arrow: Mei answering Tracer says nothing about the reverse. So each pair is stored once, lower hero_id first (a CHECK holds it), and read from either side.

| column | type | null | references |
| --- | --- | --- | --- |
| `hero_id` | integer | no | `heroes.hero_id` |
| `other_id` | integer | no | `heroes.hero_id` |
| `score` | smallint | yes |  |
| `note` | text | yes |  |

#### `synergy_cells`

*PLAYBOOK · `029_synergy_cells.sql`*

Which teammates each released hero's wiki article writes a Team Synergy cell for, one row per cell (pull_synergies, from the cells synergies is read from): hero_id's article writes a cell about other_id. A written cell is any that is not a placeholder - a claim, a rating below GOOD, an unrated "no synergy" - so a cell with no row is one no article writes, and facts/tables.py reads it at the share of the written cells that claim; a pair with no row either way reads twice that, the written pairs' mean as they read. Reloaded whole with synergies.

| column | type | null | references |
| --- | --- | --- | --- |
| `hero_id` | integer | no | `heroes.hero_id` |
| `other_id` | integer | no | `heroes.hero_id` |

#### `weapon_config_slots`

*HEROES · `002_heroes.sql`*

| column | type | null | references |
| --- | --- | --- | --- |
| `slot_id` | smallint | no |  |
| `code` | text | no |  |

#### `weapon_configs`

*HEROES · `002_heroes.sql`*

weapon_type lives here rather than on the weapon because it varies by config: Ana's Biotic Rifle is a projectile from the hip and hitscan in ADS.

| column | type | null | references |
| --- | --- | --- | --- |
| `config_id` | integer | no |  |
| `weapon_id` | integer | no | `weapons.weapon_id` |
| `slot_id` | smallint | no | `weapon_config_slots.slot_id` |
| `name` | text | no |  |
| `weapon_type` | text | yes |  |
| `position` | smallint | no |  |
| `keywords` | text | yes |  |

#### `weapon_stats`

*HEROES · `002_heroes.sql`*

| column | type | null | references |
| --- | --- | --- | --- |
| `weapon_stat_id` | integer | no |  |
| `config_id` | integer | no | `weapon_configs.config_id` |
| `stat_key_id` | integer | no | `stat_keys.stat_key_id` |
| `value` | numeric | yes |  |
| `unit_numerator` | text | yes |  |
| `unit_denominator` | text | yes |  |
| `denominator_value` | numeric | yes |  |
| `condition` | text | yes |  |
| `value_text` | text | no |  |

#### `weapons`

*HEROES · `002_heroes.sql`*

One row per weapon. A weapon's firing modes are configs, not weapons: Ana carries one Biotic Rifle, fired from the hip or down the sights.

| column | type | null | references |
| --- | --- | --- | --- |
| `weapon_id` | integer | no |  |
| `hero_id` | integer | no | `heroes.hero_id` |
| `name` | text | no |  |
| `position` | smallint | no |  |
<!-- /generated:dictionary -->
