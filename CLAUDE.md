# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Countrix picks Overwatch 2 team compositions: a PostgreSQL database pulled
from Blizzard and the wiki, a board that turns every pick into numbered
facts, and a deterministic solver over a markdown playbook. Python 3.12:
`http.server` for the served layers, requests and beautifulsoup4 for the
scrapers, psycopg (pgserver for the embedded cluster), no web framework, no
JS build step. The docs are the reference -
[docs/architecture.md](docs/architecture.md) first, then docs/db.md and
docs/inference.md for their layers; `facts/` has its package docstring, and
no doc. This file is what a session needs before it changes code.

## Commands

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt

.venv/bin/ruff check db facts inference door ui tests orchestrator.py           # the paths CI lints
.venv/bin/python -m mypy db facts inference door ui orchestrator.py             # the types CI checks

.venv/bin/python -m pytest -q -p no:cacheprovider --cov                         # full suite, 75% bar, needs the built database
COUNTRIX_NO_DATABASE=1 .venv/bin/python -m pytest -q -rs -p no:cacheprovider --cov --cov-fail-under=78   # what CI sees: no database
.venv/bin/python -m pytest -q tests/test_docs.py                                # one file
.venv/bin/python -m pytest -q 'tests/test_docs.py::test_the_overview_names_everything_at_the_root'   # one test
.venv/bin/python -m pytest -q -m 'not invariant'                                # everything that needs no database

.venv/bin/python -m door.mcp call db_rebuild      # build the database: the embedded cluster at db/psql/cluster
.venv/bin/python -m door.mcp call db_migrate      # apply new migrations in place, keeping the data
.venv/bin/python -m door.mcp list                 # the MCP tools; `call <tool> '<json>'` runs one in-process
.venv/bin/python -m door.mcp call db_docs         # regenerate every generated doc section (needs the database)
.venv/bin/python -m ui.board --port 8018          # the board, engine in-process (8017 is the compose board)
.venv/bin/python orchestrator.py up|status|down   # the Docker stack; a bare orchestrator.py is up
```

Pulls and `db_rebuild` read the page caches, which keep a page forever;
`'{"refresh": true}'` refetches everything from the network, minutes at the
polite pace. The stack's `refresher` container refreshes the data daily.

Tests marked `invariant` need the database and skip without one, through
the `db` fixture. The suite targets `db/psql/cluster` when that
cluster is built and `DATABASE_URL` is unset; `DATABASE_URL` or
`./docker-db <command>` points it at another Postgres. CI sets no
variable: it has no cluster and no pgserver.

The solver searches exactly, in the process that calls it: a board is a
few searches of tens of milliseconds each, one after another, and spawns
no worker. `.venv/bin/python -m tests.inference.prove_exact` checks it
by hand against a brute force of every legal six on a board of the built
database, in slices under five minutes each (its docstring says how).

Without the database, two generated sections regenerate on their own:
`.venv/bin/python -c "from door.mcp import tools; tools.REGISTRY.write_docs()"`
(docs/mcp.md) and
`.venv/bin/python -c "from inference import catalog; catalog.write_docs(catalog.load())"`
(the catalog in docs/inference.md). The second writes nothing while
`COUNTRIX_STRATEGIES` names another playbook folder - that variable picks the
playbook in force, relative to the repo root, and is read on every call.

## Architecture

Three layers over one database, each a folder at the root: `db/` (DATA),
`facts/` (FACTS), `inference/` (STRATEGIES and the argmax). `ui/` is the
board over them, and `door/` stands over all three. Imports run
db <- facts <- inference <- door <- ui.

- **One door for writes.** Every write to Postgres or the playbook runs
  under a tool. Each family module (`pulls`, `lifecycle`, `facts`, `solver`,
  `playbook` in `door/mcp/`) declares its tools with `@tool(...)`
  into the one `REGISTRY` (`door/mcp/registry.py`), which lists them in `FAMILIES`'
  order, and `door/mcp/tools.py` imports every family. A call arrives over
  stdio, HTTP or in-process (`ctx.call`), and is checked against the
  tool's schema by the same `Tool` wrapper on every path.
  The code that writes lives with what it writes - the pulls in `db/data`,
  the strategies table in `inference.catalog.mirror`, the playbook's files
  in `inference.tune` - and only the tools call it. Reads bypass the door:
  the board, `facts/` and `inference/` read through
  `db.psql.default_dsn()` - `DATABASE_URL`, else the embedded pgserver
  cluster at `db/psql/cluster`, started on first touch; only db_rebuild
  creates it (`psql.boot`), and a read with neither raises
  `psql.NoDatabaseError`.
- **One user input.** The strategies are the only data written by hand,
  and the only rows under the `user` source; every other table is pulled
  from Blizzard or the wiki.
- **One definition per metric.** `facts/team.py` defines every team
  metric and `facts/compute.py` the matchup, map and world ones, each in a
  registry, and `compute.registry()` gathers them. The facts engine words
  them as facts, the solver scores the same functions, and the catalog
  validates a strategy's `metric` against the registry, so the number on the
  board and the number the solver maximises cannot drift. `facts/` is a
  shared library: `inference/`, the door's `facts`, `solver`, `boards` and
  `playbook` modules, the board and the tests' reach recorder import it.
- **Facts are numbered.** `FactSet` numbers facts F1.. in emission order;
  a solver contribution cites a fact by metric key (`also=` on
  `FactSet.add`). Adding a fact renumbers every later id.
- **The playbook is markdown.** `inference/strategies/*.md` - the filename is
  the id; frontmatter sets the kind (constraint, heuristic, assumption).
  Constraints cut the space; heuristics weigh what is left. The form is
  derived, never written: a constraint is a limit (`require:`), which always
  holds and is never weighted; a heuristic is on a metric (`metric:`, form
  heuristic) or scored (`bonus:`/`penalty:` times its weight); then
  assumption, or draft (name, kind and prose only). A key outside the
  fields, `soft:` among them, is refused. `inference/catalog.py` reads it,
  each file parsed by `frontmatter.py` and checked by `strategy.py`
  (`Strategy`, `CatalogError`); one bad file makes `catalog.load` raise
  everywhere. `meta.md` beside the strategy files is no strategy and no
  strategy may take its name: it holds the default engine's weights
  (below). The shipped playbook is eight assumptions, one heuristic,
  `heal-rate`, scored (the healing floor, `matchup.heal_shortfall`,
  docs/inference.md), and one limit, `at-most-three-supports`, while
  it is rebuilt rule by rule from the citation record in
  `inference/README.md`. Solver behaviour is tested against the 19-file
  reference playbook in `tests/fixtures/playbook/` and its own `meta.md`
  (`DEFAULT` and `BRIEF` in tests/inference/__init__.py), or its four
  assumptions alone (`ASSUMPTIONS_ONLY` there) where a test needs a
  playbook that scores nothing; no solver test reads
  `inference/strategies/`.
- **The default engine scores first.** `inference/base.py` scores every six
  on its win rates on the map (each pick's edge over 50, trusted by its pick
  rate), the wiki's synergy scores - read cell by cell, one cell in each
  hero's article: a claim 1, a write-off 0, and a cell no article writes
  (no `synergy_cells` row) at the written cells' claim share
  (`facts.tables.impute_synergy`), never 0 (docs/inference.md, Why an
  unwritten synergy pair is not zero) - and the counter graph against the
  other side - its locked picks, else its likely six: a wiki edge 2, and
  on a pair the wiki leaves out a kit-derived one 1 (`facts/counters.py`,
  which the team.* counter metrics never read) - and the playbook's terms
  sit on top, so the shipped playbook's boards are scored, never
  *unscored*. Its weights are the playbook's, in `meta.md`: `meta`, which
  scales the whole engine, over the `rate`, `synergy` and `counter` dials
  (1, 1, 0.26, 0.05 shipped); `tune` with id `meta` changes them and the
  file's prose (`body`), and the playbook tab's Meta slider
  (`weights=meta:<v>`) sets the meta for a session. No term's weight
  lives in code; what a term counts inside - `WIKI_WEIGHT` and
  `DERIVED_WEIGHT`, `RATE_PICK_HALF`, `NEED_BUDGET` - is its definition,
  and a fixture's stamp records it. A `BaseWeights` rides the `Brief`
  (`base=` on `infer`, `Objective` and `Solver`); left
  unset it is the playbook in force's `meta.md` (`engine.weights_in_force`),
  and every result and `base.stamp` record it. A test that runs the engine
  names the reference playbook's weights, never the live file's.
  `base.OFF`, the meta at 0, is the playbook alone, byte for byte the
  engine before it had a base: a test that pins the reference playbook's
  sixes or scores passes it.
- **The kit is read in 6v6.** `facts.draft.KIT_FORMAT` names the format;
  `tables.load` lays the wiki's 6v6 pools and lines (`heroes.*_6v6`,
  `kit_6v6`) over the 5v5 rows before `derive_scalars` (`facts/kit_format.py`).
  The 5v5 figures stay stored, and each change names the one it moved.
- **The solver is deterministic.** `engine.board()` returns a Board of up to
  seven Results (blue, red, current, red_current, fill, countered, expected);
  fill is None unless one to five blue picks are locked, countered is None
  without blue picks or when the caller's `Brief` leaves it out, as the
  page's boards do. Each seat has one scale: reference sixes drawn from a
  string seed, the map and the side, bounded against the enemy; the lowest
  of their scores is the seat's floor, a share's 0, as its optimal is the
  100. current shares blue's optimal's scale, red_current red's, so within
  a seat infer, the fill and current are comparable. The search is exact
  (`inference/solver.py`, its bounds in `inference/bounds.py`): every
  legal six of the released, unbanned roster, each once, by branch and
  bound, in one total order - the score to `SCORE_PLACES` decimals, then
  the six's tie-break draws, then sorted names - each six scored in one
  seat order. A draw is a hash of the board's map and side and the hero's
  id (`scoring.draw`), never a rate or a name, so with nothing scoring
  every legal six ties and the draw alone picks; the optimal reports how
  many sixes share its score (`Solver.ties`), and the `ties-are-drawn`
  assumption says so in the playbook.
  A new metric or expression construct needs a bound rule, and
  `tests/inference/test_bounds.py` fails without one. Blue's picks the
  limits rule out - a full six that breaks one, or picks the fill's search
  proves no six completes - are not allowed: no score, no share, no odds;
  red's picks are never ruled out. A search past its budget refuses
  (`solver.Unbounded`), never guesses.
- **The board** (`ui/board.py`, its pages in `ui/pages.py`) serves
  `/api/facts` and answers `/api/board`, `/api/strategies` and `/health`
  with `inference/serve.py`'s handlers, all in its own process - the
  compose stack's `ui` container runs the engine.
  `serve.Admission` solves `BOARDS_AT_ONCE` (one) board at a time. The
  board answers GET alone and writes nothing: a slider's weight rides
  with the session's requests. Both HTTP servers, the board and the
  MCP door, stand on `db/web.py`: a request whose Host or Origin is not a
  local name or one given with `--allow-host` is refused with 403.
- **Docker** runs one image as three roles, plus postgres and `backup`, the
  nightly `pg_dump` into `backups/` on postgres's image (`compose.yaml`,
  `docker-entrypoint.sh`). Migrations ship in the image, not a mount: once
  `orchestrator.py up` rebuilds it, any new migration file makes the `data`
  container `db_migrate` on start, which keeps the data. A migration that
  fails is answered with `db_rebuild`, which drops the dated rates
  history; it first asks `backup` for a `prerebuild-*` dump the rotation
  keeps, which gives the history back (docs/db.md, The nightly dump).

## What the tests hold you to

`tests/test_docs.py` and friends fail on ordinary changes. Before committing:

- A new tracked file or folder at the root must be named in
  `docs/architecture.md` - a file in The files, a folder in The folders. The
  test greps the whole doc for the name.
- A new module, folder or file inside a package gets a line in the map of
  its package's `__init__.py` docstring: indented, the name, then two
  spaces or more before what it is (`.py` optional, a folder's slash too).
  A name that only opens a wrapped line of prose does not count.
- Every quoted `"COUNTRIX_..."` name in `db/`, `facts/`, `inference/`,
  `door/`, `ui/` or `orchestrator.py` must appear in docs/architecture.md
  or docs/db.md, and is read where it is used or by `main()` at start: an
  `os.environ`, `os.getenv` or `os.path.expanduser` (it reads HOME) that
  runs at import fails `test_no_module_reads_the_environment_at_import`.
- A new migration is named by its number in docs/db.md's `migrations/`
  row, the one inventory of the schema's steps. The whole chain must build
  an empty database: an invariant test applies it to a scratch database
  on the target server and compares the tables with the built one.
- Only a door tool in `door/mcp/` calls the playbook's writers -
  `catalog.mirror` and `tune.tune`/`add`/`complete`. A new call site
  elsewhere fails the test; route it through a tool.
- Each layer imports only the layers below it: `db/` imports nothing above
  it, `facts/` only `db/`, `inference/` `db/` and `facts/`, `door/` all
  three; `ui/`, `tests/` and `orchestrator.py` import any of them. An
  upward import, deferred or not, fails
  `test_each_layer_imports_only_the_layers_below_it`.
- A line indented 1 to 16 columns sits on a multiple of 4, docstring maps
  and SQL in strings included, and a continuation hangs 4 columns in after
  a bracket that ends its line (8 for a def's parameters). One line off the
  stop makes desloppify read the indent unit as 1 and count every column
  as nesting.
- Text between `<!-- generated:NAME -->` markers is rendered from code and
  compared with a fresh render. Never edit it by hand; change the source
  (a `@tool` description, strategy frontmatter, a migration comment) and
  regenerate.
- Adding or renaming an MCP tool: regenerate docs/mcp.md; each house skill
  must still name the tools `MUST_NAME` (tests/test_docs.py) lists;
  tests/door/mcp/test_mcp.py holds the tool set too.
- A new strategy file is cited as a ``- `id` `` line in `inference/README.md`.
  A house skill or a doc names a strategy only by an id the playbook
  holds: a backticked id the record cites and `inference/strategies/`
  lacks is a dropped rule, and fails.
- A new table carries `source_id` and `cao`, has rows and is named in
  `facts/tables.py` (a test greps its source); regenerate the data
  dictionary in docs/db.md. Its migration also wants a `schema.DOC_DOMAIN`
  entry keyed by filename, or docs/db.md files it under foundation - no
  test catches that one.
- A new metric: an entry in `TEAM_METRICS` (`VERSUS_METRICS` for one that
  reads the other side), `MATCHUP_METRICS`, `MAP_METRICS` or
  `WORLD_METRICS` and the key its function computes (the namespace must
  equal the registry), and in `TEXT_METRICS` when its value is a name or a
  list - `tests/facts/test_metrics.py` checks every registry key's kind
  against it - and a bound rule in `inference/bounds.py` (its aggregate: a
  sum, a mean, a count, fixed by the shape), which
  `tests/inference/test_bounds.py` fails a key without; then regenerate
  the catalog vocabulary in docs/inference.md.
- `tests/ui/test_pages.py` pins the scripts at their seams (routes, query
  keys, element ids, the payload keys they read against what the server
  writes) and holds that every `board.css` class is used; a decision worth
  pinning is made on the server, as the seat badge is (`momentum.badges`).
  The math page renders the code constants it quotes (`view_math` fills
  them in), so a literal percent in `ui/static/math.html` is written `%%`.
- `test_the_search_reaches_the_enumerated_maximum` in
  `tests/inference/test_solver.py` is the regression gate on the search:
  synthetic boards - red revealed, locks, bans, a pair that pays only
  together, a widened roster - under the reference playbook with a role
  queue and with the open queue's shapes, the default engine on and off,
  the search's best six sixes against a full enumeration's, element for
  element, with no database, so CI runs it. A board it misses is a solver
  defect: fix the search, never swap the board out.
- `tests/fixtures/reach.json` records a board per released hero that
  seats it, beside the objective it was recorded under - the playbook's
  digest (`catalog.playbook_digest`) and the default engine's stamp
  (`base.stamp`). After a deliberate change to the objective,
  `.venv/bin/python -m tests.inference.record_reach` re-records it, and
  the commit says what moved.

## House rules

- A session never hand-edits the playbook. Changes go through `tune`
  (a strategy's prose as `body`, `meta.md`'s weights and prose too, and it
  seeds a folder's missing `meta.md` from the shipped one), `add_strategy`
  or `infer_strategy`.
  They validate, rewrite the docs catalog for the shipped playbook and
  append a reasoned line to `tuning-log.md` beside the playbook in force.
  A draft the user drops in by hand (name, kind, prose) is input;
  `/strategy` fills its frontmatter through `infer_strategy`.
  Called without `directory=`, `tune`/`add`/`complete` rewrite the live
  playbook, so tests pass a temporary copy.
- Migrations are `db/psql/migrations/NNN_name.sql`; new ones wrap in
  `BEGIN;`/`COMMIT;` (010-013 do not, and `schema.apply` commits after each
  file either way). The ledger records filenames only: never edit a
  statement in an applied migration, add the next number. The `--` prose
  is documentation the data dictionary reads, and is kept current.
  `db_migrate` keeps the data, locally and in the `data` container;
  `db_rebuild` drops it.
- Over stdio, stdout is the JSON-RPC wire. Code reachable from a tool logs
  through `ctx.log` or stderr, never `print`. A refusal raises `db.Refusal`;
  anything else is the server's fault.
- A table or column name reaches SQL only as the `psycopg.sql.Identifier`
  that `db.psql.identifier()` returns, composed with `psycopg.sql.SQL`;
  values are always parameters.
- Pulls read only Blizzard's site and the wiki, through the page caches and
  the one request loop in `db/data/cache.py`, each at the pace of its own
  `RequestPolicy`: 5 s a page for the rates (`RATES_POLICY` in
  `db/data/blizzard/meta.py`); for the wiki (`db/data/wiki/__init__.py`),
  2 s a Cargo page with six attempts to wait out a rate limit
  (`CARGO_POLICY`), and 0.5 s an article, asked for once
  (`ARTICLE_POLICY`). No third source, no API keys.
- Blizzard's rates page licenses its win, pick and ban rates for personal
  use only. Nothing public - a README image, a doc example, a published page -
  shows a rate figure or text derived from one.
- A pull matches a hero or map name against the database through
  `db.data.normalizer` - `index` and `name_key`, or `hero_key` where a former
  name can appear - never by `.lower()`.
- Never `docker compose down -v`: it deletes the database volume.

## Style

- `%`-formatting, never f-strings or `.format()` (ruff's UP031/UP032 are off
  for this).
- Every function and method carries full type annotations, and a record
  that crosses a module boundary is a dataclass, NamedTuple or TypedDict,
  not an ad-hoc dict or tuple. A TypedDict is a shape that is or becomes
  JSON, or holds optional keys; a NamedTuple is a row a parser or a query
  yields, which a reader may unpack; a dataclass is the rest -
  configuration, a mutable tally that never becomes JSON, or a record that
  must not act as a tuple (keyword-only, or carrying a check or a derived
  field). `Any` is for arbitrary JSON. mypy holds the annotations in CI
  (`[tool.mypy]` in pyproject.toml, `warn_unused_ignores` among them); the
  tests need none and are not checked.
- A type alias is a PEP 695 `type` statement, never a bare assignment; a
  recursive one names itself unquoted. It is defined in one module and
  imported everywhere else; `test_every_type_alias_is_a_type_statement`
  fails a bare one.
- Imports sit in the module's import block; an optional dependency is
  imported there inside `try`/`except ImportError`, as pgserver is in
  `db/psql/__init__.py`. A function-level import is a deliberate deferral
  and says why, `# noqa: PLC0415  # <why>`; ruff fails any other outside
  `tests/`.
- Every module opens with a docstring saying what it does. Test names are
  declarative sentences (`test_the_overview_names_everything_at_the_root`);
  side effects are stubbed with `monkeypatch`, not mocks.
- Prose in docs, comments, skills and commits is terse, declarative, present
  tense and ASCII, with a spaced hyphen where a dash would go. Headings name
  things with the definite article ("The files"). Non-ASCII is kept to math
  notation, the middle-dot separator, accented hero names and the board's
  glyphs (the ban cross, the ellipsis). `.claude/skills/desloppify/SKILL.md`
  is the tool's own text: leave it as `update-skill` writes it.
- Commit subjects state the outcome as a sentence, no type prefix, no period
  ("The scale holds still under bans"). The body says why, in prose wrapped
  near 72 columns, with measured numbers such as the test count.
- `pm/backlog.md` is the payoff-ordered backlog; `/maintain` keeps it and the
  docs current and records what the checks missed under its Lessons learned.

## Desloppify

The desloppify harness scores the code and drives the cleanup loop. It is
not in requirements.txt, so CI and the image stay lean; install it into the
venv and restore its local config, which lives in the gitignored
`.desloppify/`:

```bash
.venv/bin/pip install --upgrade "desloppify[full]"
.venv/bin/desloppify update-skill claude        # refreshes .claude/skills/desloppify/SKILL.md
for p in .venv .cache-blizzard .cache-wiki db/psql/cluster .claude/worktrees; do .venv/bin/desloppify exclude $p; done
```

The target score is set with `desloppify config set target_strict_score
<n>` and lives only in that local config. A subjective review is blind:
its reviewers score from the code alone, never from a score or a target.

The loop, from the repo root:
`PATH="$PWD/.venv/bin:$PATH" .venv/bin/desloppify scan --path .` (the scan
counts bandit as installed only when PATH finds it; without it Security
confidence stays at 0.6), then `next`, fix, `plan resolve <id> --attest
"I have actually ... not gaming ..."` (`next` prints the exact command),
repeat; `status` shows the scores. Follow the scan's own
instructions. Its commits follow the house style above, not its
`desloppify: ...` template.
