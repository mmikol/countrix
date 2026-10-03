"""The MCP door's tests, and Offline, the door's context over no database,
which the data layer's and the board gate's tests share too."""

import contextlib

from door.mcp import tools


class Offline(tools.Context):
    """The door's context, every tool family registered, over no database:
    connect hands a tool the stand-in "cx" and opens nothing, so a test
    stubs whatever reads it."""

    def connect(self, boot=False):
        return contextlib.nullcontext("cx")
