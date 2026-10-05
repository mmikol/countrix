# Tuning the playbook

There are two ways to change how Countrix scores:

- **For a session**, the playbook tab's sliders. They change nothing on
  disk and stay in your browser: [the playbook tab](playbook.md).
- **For good**, the playbook's files, through the door. This page.

The playbook is the folder `inference/strategies/`: one markdown file a
rule, and `meta.md`, which holds the default engine's weights and the
swap cost. It is yours to change: anyone may change the files of the
playbook, its rules and the weights in `meta.md`, for their own
noncommercial use. The rest of Countrix stays under PolyForm Strict
([credits and licences](credits.md#countrix)).

Change it through the door's tools rather than by hand. A tool checks a
change before it writes anything, keeps the database's copy of the
playbook in step, and logs the change with its reason in `tuning-log.md`
beside the rules. A change that would not load - an unknown metric, an
expression that does not parse, a value out of range - is refused, and
nothing is written.

## The door

The door is Countrix's tool server, the one way in for every change to
the database or the playbook. It speaks MCP, the Model Context Protocol,
which is how Claude Code calls tools. `.mcp.json` registers it twice for
a Claude Code session opened in the `countrix` folder; Claude Code asks
you to approve them the first time.

| server | reaches |
| --- | --- |
| `countrix` | the local database, started by the session when it needs it |
| `countrix-docker` | the stack's database, over HTTP at http://localhost:8020/mcp - the one the board at http://localhost:8017 shows |

Both carry the same tools. With the stack up, use `countrix-docker`, so
what you change is what the board shows. When `.env` sets
`COUNTRIX_MCP_TOKEN`, the door asks for that token; `.mcp.json` sends
the variable of the same name from the environment Claude Code starts
in, so set it there too.

## The house skills

Open the repository in [Claude Code](https://claude.com/claude-code)
and type a skill's name, or say what you want in your own words.

- **`/comp`** asks for a comp in chat: *comp for King's Row, they have
  Zarya and Pharah, I'm on Ana*. It runs the board's own search and
  answers with six picks, a line of why for each, and the facts they
  cite. Follow-ups - *what if they swap to Pharah?*, *we're on the
  second point now* - run it again.
- **`/tune`** changes how something scores: *it keeps ignoring the
  counters*, *trust the meta less*, *it keeps telling me to swap*. It
  makes the smallest change that does it - a rule's weight, a dial, an
  expression, one of the default engine's weights or the swap cost -
  through the `tune` tool, and shows what moved on your board.
- **`/strategy`** adds a rule from three things in your words: a name,
  a kind (limit, heuristic or assumption) and a few sentences of prose.
  It brings them to the playbook's form, works out the math, stores the
  rule through `add_strategy`, and shows what it changes on a board. A
  draft - a file holding only a name, a kind and prose, dropped into the
  folder by hand - is ignored by the solver until `/strategy` finishes
  it.

`/up` brings the stack up and checks it before a game.

## The tools from a shell

The tools run without Claude Code too:

```bash
.venv/bin/python -m door.mcp call strategies     # meta.md's weights, then every rule
.venv/bin/python -m door.mcp call tune '{"id": "meta", "field": "swap", "value": 15, "reason": "fewer swap suggestions"}'
.venv/bin/python -m door.mcp call tune '{"id": "heal-rate", "field": "weight", "value": 1.5, "reason": "we play one main healer"}'
.venv/bin/python -m door.mcp call tuning_log     # every change and its reason, newest last
```

With the stack up, put `./docker-db` in front to reach its database:
`./docker-db .venv/bin/python -m door.mcp call tune '...'`; it reads
`POSTGRES_PASSWORD` from the shell, not from `.env`
([the settings](install.md#the-settings)). The board reads the files on
every request, so the next click shows the change.

What `tune` takes:

| `id` | `field` and `value` |
| --- | --- |
| a rule's id, its filename | `weight` (0 to 10; 1 to 4 is the working range), a dial `params.NAME`, an expression - `when`, `require`, `bonus` or `penalty` - or `body`, the prose, three sentences at most; also `kind`, `category`, `metric` and `direction` |
| `meta` | `meta`, `rate`, `synergy` or `counter` (each 0 to 10), `swap` (0 to 50), or `body`, its prose |

Every call takes a `reason`, a sentence the log keeps. A weight of 0
silences a rule without deleting it, and a meta of 0 silences the
default engine. Deleting a rule's file is your decision, never a tune.

A change lands in your checkout: the rule's file or `meta.md`,
`tuning-log.md`, and, for the shipped playbook, the catalog in
`docs/inference.md`.

## Another playbook

`COUNTRIX_STRATEGIES` points Countrix at another playbook folder. The
folder must hold a `meta.md`; `tune` with the id `meta` seeds one from
the shipped file. The repository carries one other playbook,
`tests/fixtures/playbook`, the reference the tests prove the solver
against.

- **Without Docker**, set it in the shell that starts the board or the
  tools: `COUNTRIX_STRATEGIES=my-playbook .venv/bin/python -m ui.board`.
  The folder is named relative to the `countrix` folder or by its full
  path, and the tools tune it where it is.
- **With the Docker stack**, set it in `.env`, and keep the folder
  inside the `countrix` folder, named relative to it. The image that
  `orchestrator.py up` builds carries a copy of the folder, and the
  containers read that copy: run `up` again after the folder changes.
  The copy is read-only, so the stack's tools cannot tune it. A full
  path works without Docker only: the containers cannot see it.
