"""The DOOR over all three layers: the MCP tools every write runs under, and
the clock that runs them on a schedule.

The door gates every write to Postgres and the playbook. The code that
writes lives with what it writes - the pulls in db.data,
inference.catalog.mirror, which reloads the strategies table, and
inference.tune, which edits the playbook's files - and is called only from
a door tool.
Reads need no door tool: the board opens its own connection through
db.psql.default_dsn(), and a door tool opens one through its Context;
facts.tables.load reads over the connection it is handed, and inference/
reads only the World. The door imports db, facts and inference, and none
of them imports it.

    mcp/        the MCP server and its tools, the one door, for a session,
                the refresher, Docker's entrypoint and the shell alike
                (`.venv/bin/python -m door.mcp call <tool>`)
    refresh     the door's clock: the daily refresh, and the full one once
                the wiki cache is a week old, run through the door's tools
"""
