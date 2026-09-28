# How it fits together

Three layers over one database, each a folder at the root: `db/` (DATA),
`facts/` (FACTS) and `inference/` (STRATEGIES and the argmax). `db/` and
`inference/` each have a document in `docs/`; `facts/` has its package
docstring, and no doc. `ui/` is the board over them, and `door/` stands
over all three. Imports run db <- facts <- inference <- door, and
`tests/test_docs.py` holds that; `ui/` sits on top and may import any layer.

```
DATA           = HEROES ∪ MAPS ∪ META              the tables, as pulled and set
for each domain D in { HEROES, MAPS, META }:
  INDEPENDENT(D) = ⋃ facts(s)      over each selection s in D    s alone: its own row
  DEPENDENT(D)   = ⋃ facts(s ⋈ t)  over the other selections t   s joined with t, in D or beyond
  FACTS(D)       = INDEPENDENT(D) ∪ DEPENDENT(D)
FACTS          = FACTS(HEROES) ∪ FACTS(MAPS) ∪ FACTS(META)
FACTS(D) ∩ FACTS(E) = the joins of D with E: what only their intersection can say
STRATEGIES     = CONSTRAINTS ∪ HEURISTICS ∪ ASSUMPTIONS   the playbook: markdown files
COMP           = ARGMAX[ STRATEGIES( FACTS ) ]            the solver searches, the agent argues
```

The function the argmax takes is two layers. The default engine
(`inference/base.py`) is always on: it scores a six on its win rates on
the map, the wiki's synergy pairs among its picks and the wiki's counter
edges against the other side, so a playbook of assumptions alone still
gets scored sixes. The playbook's terms sit on top and adjust that
answer ([inference.md](inference.md#the-objective)).

One input is the user's, the strategies, which the solver reads; every
other table is pulled from Blizzard or the wiki.

No accounts, no keys, no API billing. The board is a local page and the
solver is deterministic; the model work (comps in chat, strategies
inferred from prose, the refresh that tunes with a reason) runs in Claude
Code on your subscription, and the board never calls a model.

## The folders

| folder | what it is | read |
| --- | --- | --- |
| `db/` | **DATA LAYER** - `data/` and `psql/` pull every source, clean it and store it, with the schema, its migrations and the embedded cluster; `web.py` is what the two HTTP servers share, from the Host-and-Origin guard to the one JSON reader. The bottom of the import graph: it imports nothing above it, and the layers over it read Postgres directly, over `db.psql.default_dsn()` | [db.md](db.md) |
| `facts/` | **FACTS LAYER** - everything the database knows about a board: the World (the database in memory), the metrics registry, the FactSet. It imports only `db`; the solver, the door and the board read the same numbers through it | [`facts/__init__.py`](../facts/__init__.py) |
| `inference/` | **INFERENCE LAYER** - the playbook of constraints, heuristics and assumptions in markdown, the solver, the tuning loop | [inference.md](inference.md) |
| `door/` | **THE DOOR** over all three layers - `mcp/`, the MCP server and its tools, under which every write runs; `refresh.py`, the clock that runs the tools daily and weekly | [mcp.md](mcp.md) |
| `ui/` | **THE BOARD** - the page (map, sides, bans, red and blue rosters) over the facts layer's facts and the inference layer's answer: `board.py`, `pages.py` and `static/` - the only presentation code | [ui.md](ui.md) |
| `tests/` | one folder per layer beside the root files' tests, with `synthetic.py`, a World of twelve released heroes, one announced hero and three maps built by hand, so a test works out its expected values with no database; `tests/fixtures/playbook/`, the reference playbook of every kind and form of strategy that the solver tests run on in place of `inference/strategies/`; and `tests/inference/record_reach.py`, the recorder that writes `tests/fixtures/reach.json`, a board per released hero, run from the repo root as `.venv/bin/python -m tests.inference.record_reach` | |
| `.claude/skills/` | the skills a Claude Code session runs here, one `SKILL.md` each | [The skills](#the-skills) |
| `pm/` | `backlog.md`: what is worth doing next, why and at what cost, in payoff order; the maintainer skill keeps it current | |
| `.github/workflows/` | `ci.yml`: lint, the types (mypy) and the tests that need no built database, held to 78% coverage, on pushes to `main` and on pull requests | |
| `.cache-blizzard/` `.cache-wiki/` | the page caches (gitignored): every build after the first costs almost no requests | |
| `backups/` | the `backup` service's nightly dumps of the stack's database (gitignored, each `0600`), the newest 14 `countrix-YYYY-MM-DD.dump`: the dated rates history a rebuild drops and no source gives back; a `prerebuild-*.dump` taken before `data` rebuilds a stale schema, which the rotation keeps. `orchestrator.py up` makes the folder | [db.md](db.md#the-nightly-dump) |

How they fit:

```mermaid
flowchart LR
    subgraph SOURCES["sources (free, no data APIs)"]
        BLZ["Blizzard<br/>roster, portraits, rates"]
        WIKI["Overwatch wiki<br/>kits, numbers, keywords,<br/>maps, terrain, patches, seasons,<br/>styles, synergies, counters"]
    end

    subgraph DATA["the door - door/mcp/ (an MCP server over all three layers)"]
        PULL["pull_* tools<br/>fetch (cached) -> clean -> store"]
        PLAY["load_authored<br/>the strategies mirror"]
        DBT["db_* · query"]
    end

    subgraph PG["PostgreSQL"]
        HEROES["HEROES<br/>roster, kits, stats,<br/>keywords, portraits"]
        MAPS["MAPS"]
        META["META<br/>dated snapshots"]
        PLAYBOOK["PLAYBOOK<br/>counters, synergies,<br/>styles"]
        INF["INFERENCE<br/>the strategies mirror"]
    end

    subgraph USER["FACTS LAYER - facts/, and the board - ui/board.py"]
        WORLD["World<br/>the database in memory,<br/>per request"]
        FACTS["FactSet<br/>F1.. hero · map · meta ·<br/>team · matchup<br/>S1.. the playbook's record"]
        BOARD["the board<br/>map + red/blue rosters"]
    end

    subgraph INFER["INFERENCE LAYER - inference/"]
        HEUR["strategies/*.md<br/>STRATEGIES = CONSTRAINTS ∪ HEURISTICS ∪ ASSUMPTIONS<br/>constraint: limit · heuristic: metric · scored"]
        SOLVER["solver<br/>enumerate · prune ·<br/>normalise · refine"]
    end

    BLZ & WIKI --> PULL
    HEUR --> PLAY
    PLAY --> INF
    PULL & PLAY --> PG
    PG --> WORLD --> FACTS --> BOARD
    WORLD --> SOLVER
    HEUR --> SOLVER
    SOLVER --> BOARD
    CHAT["Claude Code session<br/>/comp skill"] <-->|"MCP tools:<br/>pull_*, facts, infer, board"| DATA
```

The door gates every write to Postgres or the playbook, and the layers
read Postgres directly ([mcp.md](mcp.md)).

## The files

| file | purpose |
| --- | --- |
| `orchestrator.py` | the stack from a shell. `.venv/bin/python orchestrator.py` brings it up (the data container pulls and ingests when the database is empty or stale), waits, solves one board and prints the verdict. Verbs: `up` (default) · `status` · `down` |
| `compose.yaml` | one container per role: `db` (PostgreSQL 16), `data` (the door: builds the database, then serves every MCP tool over HTTP), `ui` (the board, with the inference engine in the board's process and the solver's worker pool beside it), `refresher` (the door's clock) and `backup` (the nightly `pg_dump` into `backups/`). The three app containers share one image; `db` and `backup` run postgres's. Every container but `db` runs unprivileged on a read-only root with every capability dropped and memory and process limits; `db` keeps the five capabilities the postgres image needs to start as root, with no read-only root and no limits. Every port is published on 127.0.0.1 only. Bind mounts keep the caches, `inference/strategies`, `docs` and `backups` on the host, so tuning, authoring and regenerating need no rebuild |
| `Dockerfile` | the one image, run as an unprivileged user (uid 1000, or `COUNTRIX_UID`/`GID` from `.env` on a Linux host whose checkout is owned by someone else); `docker-entrypoint.sh` takes the role as its argument and, for `data`, builds the database when it is empty, unfilled or behind the migrations |
| `docker-db` | run any host command against the compose database: `./docker-db .venv/bin/python -m door.mcp call infer '{"map": "Ilios"}'`, or the suite: `./docker-db .venv/bin/python -m pytest -q` |
| `.mcp.json` | registers the two MCP servers a Claude Code session sees: `countrix` (stdio, the local cluster) and `countrix-docker` (HTTP, the stack's database) - [mcp.md](mcp.md) |
| `requirements.txt` | psycopg, requests, beautifulsoup4 and pgserver pinned (pgserver is the embedded PostgreSQL a host build uses; the image and CI filter it out, since neither starts a cluster), then pytest and pytest-cov, and ruff and mypy pinned, since a new release of either finds new errors in unchanged code. CI and a local check run all four; the image leaves them out |
| `pyproject.toml` | ruff's rules (line length 100; outside the tests, an import sits in the module's import block); mypy's, which hold every function in `db`, `facts`, `inference`, `door`, `ui` and `orchestrator.py` to full annotations; the coverage bar, 75% where a database exists |
| `pytest.ini` | the `invariant` marker for tests that need a built database |
| `CLAUDE.md` | what a Claude Code session reads before it changes code: the commands, the layers in brief, what the tests hold a change to, the house rules and style |
| `SECURITY.md` | the terms - you run it at your own risk, no security commitment from the author - and how to report a vulnerability privately; the measures themselves are in [security.md](security.md) |
| `LICENSE` | PolyForm Strict 1.0.0: noncommercial use only, no redistribution, no changes or new works; anything else needs a separate license from the author |
| `.gitignore` `.dockerignore` | the caches, the cluster, the venv, `.env`, `backups/` |

## Deployment

```mermaid
flowchart LR
    subgraph HOST["your machine"]
        SESSION["Claude Code session<br/>/comp skill"]
        BROWSER["browser"]
        SHELL["./docker-db<br/>DATABASE_URL -> :5433"]
    end
    subgraph DOCKER["docker compose (one image, three containers, plus postgres and its nightly dump)"]
        DATA["data - the door<br/>builds when empty or stale,<br/>then MCP over HTTP :8020/mcp"]
        UI["ui - the board and the<br/>INFERENCE ENGINE :8017<br/>facts and comps in-process,<br/>the solver's worker pool"]
        DBC["db - postgres:16<br/>volume pgdata"]
        REF["refresher - the door's clock<br/>seasons + rates daily,<br/>every source weekly,<br/>and on start when stale"]
        BAK["backup - postgres:16<br/>pg_dump nightly at 04:30,<br/>the newest 14 in ./backups"]
    end
    SESSION -->|".mcp.json: countrix-docker"| DATA
    BROWSER --> UI
    UI --> DBC
    DATA --> DBC
    SHELL --> DBC
    REF --> DBC
    BAK --> DBC
```

The containers share one network; only `data` and `refresher` ever open a
connection out. `docker-entrypoint.sh` takes the role as its argument
(`data`, `ui`, `refresh`); `backup` runs its own sh loop on postgres's
image, and only a rebuild over a stale schema waits on it, up to five
minutes for the dump it asks for through `backups/`. Readiness has one
definition, `db.psql.schema.state`: empty, stale (a migration the ledger
lacks), unfilled (no heroes) or current. The entrypoint asks it through
`python -m db.psql.schema`; `ui` and `refresh` wait for current, up to the
data healthcheck's 900 s, then exit. The data container's `/health`
carries the state: compose's healthcheck holds `data` unhealthy until it
is current, and `depends_on` starts `ui` and `refresher` only then. The
board's `/health` is the engine's - the playbook and the database - and
its healthcheck gates nothing. The board admits boards by the sixes their
searches may enumerate, one `FIELD_BUDGET`'s worth at once
(`serve.Admission`), so the pool and the fields in flight fit the ui
container's 2 GiB. `orchestrator.py` waits only for a first reply and
reports the state in its verdict. [security.md](security.md) has
the rest of the measures.

Settings, from the environment or `.env` (the refresh and backup times are in [db.md](db.md)).
Each is read where it is used, so a change takes effect on the next call -
except the MCP server's token, `COUNTRIX_WORKERS` (read when the pool
starts) and the refresh clock, which are read once at start:

| setting | default | meaning |
| --- | --- | --- |
| `COUNTRIX_STRATEGIES` | empty | a playbook folder other than `inference/strategies/`, relative to the repo root or absolute |
| `COUNTRIX_WORKERS` | `max(6, min(cores, 12))` | the solver's worker processes |
| `COUNTRIX_PARALLEL` | `1` | `0`: every board in one process |
| `COUNTRIX_MCP_TOKEN` | unset | bearer token the MCP server requires over HTTP |
| `DATABASE_URL` | unset | the PostgreSQL to use. Unset, the embedded pgserver cluster at `db/psql/cluster`, which `db_init` or `db_rebuild` builds: the local run, on the same tools, facts and strategies as the stack. With neither, `NoDatabaseError` |

## The skills

Open the repo in a [Claude Code](https://claude.com/claude-code) session
and the `.claude/skills/` are yours: type `/name`, or say what you want
and a skill's description matches it. Each `.claude/skills/<name>/SKILL.md`
holds the whole playbook; [mcp.md](mcp.md) has the servers and every tool.

| skill | does | when |
| --- | --- | --- |
| `/up` | brings the stack up and current, and proves it: health, a board solved on the board, the URLs, the rates' capture date | before a game |
| `/comp` | "comp for King's Row, they have Zarya and Pharah, I'm on Ana": calls `infer` and `facts`, argues against the solver's optimum under the assumptions, answers with `[F#]` citations | during |
| `/tune` | changes a weight, a dial or an expression through `tune` | between games |
| `/strategy` | asks for a name, a kind and prose, infers the frontmatter and stores the strategy through `add_strategy` | when you learn something |
| `/patches` | pulls the patch list and, when a patch shipped since the capture, refetches what it changes: rates, kits, Blizzard's text | when a patch drops |
| `/heroes` | adds or refreshes heroes: Blizzard's roster, the wiki's kits, styles and synergies, the announced heroes ahead of release, counters | when the roster moves |
| `/maps` | adds or refreshes maps: the pool, modes and stages, their terrain, the per-map rates, the style each map rewards | when the pool moves |
| `/maintain` | the repo's maintainer: lint, types and tests two ways, docs current, stale names, dead code, layout, security posture, a report | after changes |
| `/desloppify` | the desloppify harness's own skill, as `update-skill` writes it (CLAUDE.md): scores the code and drives the cleanup loop | when you ask for a score |

## The scope

6v6 Open Queue Competitive is the target: six picks a side in any mix of
roles, at most two tanks. The kit is read in 6v6 too
(`facts.draft.KIT_FORMAT`): the wiki's hero articles give 6v6 pools and
6v6 lines ("Cooldown increased from 7 to 10 seconds"), which `pull_kits`
stores beside the 5v5 figures the Cargo table publishes, and the load lays
over them; a line whose 5v5 figure has moved since the wiki wrote it is
left unapplied and named on the board. The 5v5 figures stay stored, so a
5v5 reading of the kit is one constant away. No source publishes Open
Queue rates, so META is Competitive Role Queue on console (Americas), and
every snapshot fact says so. Rates carry the patch and season they were captured under, and
the board warns when patches shipped since. Judgements (counters,
synergies, playstyles) are tier- and region-agnostic by design, and a
table is a table: every row carries its source, and that is the only
distinction drawn between measured, judged and hand-written data. One
input is hand-written: the strategies. Players are assumed to play
optimally
([players-play-optimally.md](../inference/strategies/players-play-optimally.md)),
so a strategy encodes the game, never a lobby's habits.
