"""The door over all three layers: an MCP server whose tools are the data
layer's pulls - every source fetched, cleaned and stored in Postgres - and
the tools the facts and inference layers expose through it: the facts, the
solver and the playbook. Every write to Postgres or the playbook runs under
one of them.

    .venv/bin/python -m door.mcp                  serve over stdio (what .mcp.json launches)
    python -m door.mcp --http --port 8020         serve over HTTP on 127.0.0.1 (the data
                                                  container adds --host and --allow-host)
    .venv/bin/python -m door.mcp list             print the tools
    .venv/bin/python -m door.mcp call pull_maps   run one tool from the shell

    server       the protocol: JSON-RPC answered from a server's tools,
                 whichever transport carries it
    stdio        the stdio transport, one message a line
    http         the Streamable HTTP transport, and the bearer token, the
                 body cap and the rate limit a client is held to
    schema       a tool as the protocol serves it: its arguments as JSON
                 Schema, its reply, and the Tool that checks every call
    registry     the one Registry every family declares its tools into, the
                 order it lists the families in, and the Context a call
                 lands in
    tools        every family imported, so the registry is whole, and the
                 Context the servers and the refresher use
    pulls        pull, clean, store: the pull_* tools, load_authored, sync_all
    lifecycle    the database's life: status, migrate, rebuild, the
                 generated docs, read-only query
    boards       the five properties a board tool takes, and board_tool,
                 which hands its function the one Draft they name
    facts        the facts layer: roster and a board's facts
    solver       the inference layer: infer, reach, board
    playbook     the metric vocabulary, the strategies and the tools that
                 write them, the tuning log
    __main__     the command line above

The protocol and its transports are dependency-free (server, stdio, http,
schema): the door is its own few hundred lines, and the surface is the
standard one - initialize, tools/list, tools/call - so any MCP client can
drive it.
"""
