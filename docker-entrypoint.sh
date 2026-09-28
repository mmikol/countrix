#!/bin/sh
# One image, one container per role. The first argument is the role:
#
#   data        the door: build the database when it is empty, unfilled or
#               behind the migrations (the first build scrapes the sources;
#               the mounted caches make later builds cheap; a rebuild over
#               the rates history waits for backup's dump first), then serve
#               every MCP tool on 8020
#   ui          the board and the INFERENCE ENGINE: wait for the database,
#               serve it on 8017
#   refresh     the door's clock: wait for the database, then refresh it
#               daily (door/refresh.py)
#
# Anything else is run as a command in the image:
#   docker compose run data python -m door.mcp call sync_all
set -e
role="${1:-ui}"
case "$role" in
    data|ui|refresh) ;;
    *) exec "$@" ;;
esac

# empty, stale, unfilled or current: db.psql.schema.state, the one definition
# of ready. It waits a minute for the database to answer, then exits 1.
db_state() {
    python -m db.psql.schema
}

# a rebuild over a stale schema drops the dated rates history: the backup
# service is asked for a dump its rotation never prunes (/backups/.predump),
# and the rebuild waits PREDUMP_WAIT seconds at most for its answer, past which
# the newest nightly dump in backups/ holds the history
PREDUMP_WAIT=300
predump() {
    rm -f /backups/.predump.done 2>/dev/null || true
    if ! touch /backups/.predump 2>/dev/null; then
        echo "data: /backups is not mounted or not writable - rebuilding with no dump first" >&2
        return 0
    fi
    waited=0
    while [ ! -e /backups/.predump.done ]; do
        if [ "$waited" -ge "$PREDUMP_WAIT" ]; then
            rm -f /backups/.predump
            echo "data: no dump from backup within $PREDUMP_WAIT s - the newest nightly dump in backups/ holds the history" >&2
            return 0
        fi
        sleep 5
        waited=$((waited + 5))
    done
    said=$(cat /backups/.predump.done)
    rm -f /backups/.predump.done
    case "$said" in
        ok\ *) echo "data: the rates history is kept in backups/${said#ok /backups/}" ;;
        *)     echo "data: the dump before the rebuild failed - the newest nightly dump in backups/ holds the history" >&2 ;;
    esac
}

# a refused rebuild - a playbook that does not load - ends the container, and
# the restart tries again once the file loads
rebuild() {
    python -m door.mcp call db_rebuild || {
        echo "data: the rebuild failed (above); the container retries on restart" >&2
        exit 1
    }
}

case "$role" in
    data)
        state=$(db_state)
        case "$state" in
            empty|unfilled)
                echo "data: $state database - running the first build (scrapes the sources once)"
                rebuild ;;
            stale)
                echo "data: schema behind the migrations - a dump, then a rebuild from the caches"
                predump
                rebuild ;;
            *)
                echo "data: database current" ;;
        esac
        exec python -m door.mcp --http --host 0.0.0.0 --port 8020 --allow-host data ;;
    ui|refresh)
        # as long as the data healthcheck's start_period: 90 waits of 10 s. The
        # probe runs as its own command, so set -e ends the container when it fails
        waits=0
        while :; do
            state=$(db_state)
            [ "$state" = "current" ] && break
            if [ "$waits" -ge 90 ]; then
                echo "$role: the database is still $state after 900 s - giving up" >&2
                exit 1
            fi
            echo "$role: waiting for data to build the database ($state)"
            waits=$((waits + 1))
            sleep 10
        done
        case "$role" in
            refresh) exec python -m door.refresh ;;
            *)       exec python -m ui.board --host 0.0.0.0 --port 8017 ;;
        esac ;;
esac
