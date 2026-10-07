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
