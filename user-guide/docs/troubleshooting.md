# Troubleshooting

## The board says "the board is not answering"

The page could not reach the board's server. Check that it runs:
`.venv/bin/python orchestrator.py status` for the stack, or the terminal
that runs `ui.board`. The page tries again on its own when it comes back
into view or the network returns. While the roster has not loaded, it
keeps asking, waiting twice as long each time, up to half a minute.

## The page answers 403

The board answers only to your own machine's names: open it at
http://localhost:8017 or http://127.0.0.1:8017. Countrix is built to run
on your own machine, and every port the stack publishes listens on
127.0.0.1 alone. A board reached under another name has to be started
with `--allow-host NAME`;
[docs/security.md](https://github.com/mmikol/countrix/blob/main/docs/security.md)
says what publishing one exposes.

## A board waits, or answers 429

The board solves one board at a time. Another request waits for its
turn, and after a minute it gives up with 429. Your own page never waits
behind itself: a newer board from the page stops the older one still
solving.

## A portrait will not take a click

- **Crossed out**: the hero is banned. Lift the ban in the bans bar.
- **Dimmed**: the team has no room for one more of that role - two
  tanks already, or as many supports as blue's playbook allows. The
  note in the header says how many the team may hold.
- **Dimmed with *coming soon***: the hero is announced and not yet
  released.

## Blue's badge reads "not allowed"

Blue's picks break one of the playbook's limits; hover the badge for
which. The swaps above blue's picks show the way back to an allowed six.

## Blue's badge reads "unscored"

Nothing on the board scores: the Meta slider and every rule's weight
stand at 0, so every six ties. Reset the sliders on the playbook tab.

## The fight odds show words, not numbers

Where there are no odds - the default engine off with the Meta slider at
0, or blue's picks not allowed - the strip shows the engine's verdict.

## A warning says patches shipped since the rates were captured

Refresh the rates: `pull_rates` with `{"refresh": true}` (see
[the data](data.md#refresh-it-yourself)), or `/patches` in Claude Code.
With the stack up, the refresher does it every day.

## The stack says NOT READY

The verdict names what failed. The usual fixes:

- a stale bind mount after the folder moved: run
  `docker compose up -d --force-recreate`, as the verdict says;
- *no strategies directory at ...*, with the stale bind mount's advice
  under it, while `.env` sets `COUNTRIX_STRATEGIES` to a full path: the
  containers cannot see a folder named so, and `--force-recreate` does
  not help. Name a folder inside the `countrix` folder, relative to it,
  or delete the line, then run `orchestrator.py up` again
  ([another playbook](tuning.md#another-playbook));
- a schema behind the migrations: the `data` container migrates it on
  its own; wait, then run `.venv/bin/python orchestrator.py status`
  again;
- the database never answered: read `docker compose logs db`;
- a strategy file does not load: the verdict names the file and the
  reason; fix it through `/tune`, or finish a draft through `/strategy`;
- a board did not solve: read `docker compose logs ui`.

A `backup:` line is a warning: no nightly dump is being taken, and
`docker compose logs backup` says why.

## "no DATABASE_URL and no embedded cluster"

Without Docker, the database has to be built once:
`.venv/bin/python -m door.mcp call db_rebuild`. `DATABASE_URL` points
Countrix at another PostgreSQL instead.

## Every board fails with a catalog error

A playbook file does not load, or `COUNTRIX_STRATEGIES` names a folder
without a `meta.md`. The error names the file and the reason. Fix a
field through `/tune` or the `tune` tool, finish a draft through
`/strategy`, or unset `COUNTRIX_STRATEGIES`.

## A port is taken

The stack uses 8017, 8020 and 5433. The board without Docker takes
another port with `--port`: `.venv/bin/python -m ui.board --port 8018`.
