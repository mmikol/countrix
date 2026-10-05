# Install and start

Countrix runs on your machine in one of two ways. With Docker, one
command starts the database, the board, the door and a clock that keeps
the data fresh. Without Docker, an embedded database and the board run
straight from Python.

## What you need

- Git and Python 3.12.
- For the Docker way, [Docker](https://www.docker.com/products/docker-desktop/)
  with Compose v2.
- For the way without Docker, macOS or Linux on x86_64, where the
  embedded PostgreSQL runs.
- A network connection for the first build, which reads every page it
  needs from Blizzard and the wiki.

## Get the code

```bash
git clone https://github.com/mmikol/countrix.git && cd countrix
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

Every command in this guide runs from the `countrix` folder.

## With Docker

```bash
.venv/bin/python orchestrator.py up
```

Then open **http://localhost:8017**.

The first start builds the image, then the database from the sources,
about ten minutes at a polite pace. Later starts reuse the database and
take seconds. The command waits until everything answers, solves one
board and ends with a verdict:

```text
READY - board http://localhost:8017, MCP over HTTP http://localhost:8020/mcp
```

`NOT READY` names what failed; [troubleshooting](troubleshooting.md#the-stack-says-not-ready)
has the usual fixes.

| what | where |
| --- | --- |
| the board | http://localhost:8017 |
| the door, the tool server Claude Code talks to | http://localhost:8020/mcp |
| PostgreSQL | localhost:5433 |

Every port listens on your own machine alone (127.0.0.1).

```bash
.venv/bin/python orchestrator.py status    # what is running, how fresh the data is
.venv/bin/python orchestrator.py down      # stop everything; the database stays
```

The stack runs five containers: the database (`db`), the door (`data`),
the board (`ui`), the refresher that keeps the data current, and a
nightly backup of the database into `backups/`, the newest 14 kept.

!!! danger "Never run `docker compose down -v`"
    It deletes the database's volume, and with it the dated history of
    the rates, which no source gives back.

The README's quick start adds a line that points the board at the
reference playbook, the one the tests prove the solver against. This
guide describes the shipped playbook: leave that line out.

## Without Docker

An embedded PostgreSQL holds the database in `db/psql/cluster`:

```bash
.venv/bin/python -m door.mcp call db_rebuild   # build the database, once
.venv/bin/python -m ui.board                   # the board, http://localhost:8017
```

The first `db_rebuild` reads the sources like the stack's first start.
`--port` moves the board to another port: `--port 8018` runs it beside
a stack on 8017. Ctrl-C stops it. Without Docker nothing refreshes the
data on a clock; [the data](data.md#refresh-it-yourself) says how to
refresh it by hand.

## The settings

The stack reads these from a file named `.env` in the `countrix` folder.
All are optional.

| setting | what it does |
| --- | --- |
| `COUNTRIX_MCP_TOKEN` | a token the door asks for over HTTP; unset, it asks for none |
| `POSTGRES_PASSWORD` | the database's password; `overwatch` when unset |
| `COUNTRIX_REFRESH_AT` | the refresher's daily time, `05:00` when unset |
| `COUNTRIX_BACKUP_AT` | the nightly backup's time, `04:30` when unset |
| `TZ` | the time zone of those two times; UTC when unset |
| `COUNTRIX_UID`, `COUNTRIX_GID` | on Linux, the user and group that own the checkout, when they are not 1000 |

`COUNTRIX_STRATEGIES` names another playbook folder; [tuning the
playbook](tuning.md#another-playbook) has it.
