"""The stdio transport, what .mcp.json launches: JSON-RPC one message per
line on stdin, each answer one line on stdout, and a line that is not JSON
answered with a parse error. stdout is the wire, so nothing else is written
to it.
"""

import json
import sys
from collections.abc import Iterable
from typing import TextIO

from door.mcp.server import PARSE_ERROR, Response, Server, error_response


def serve(mcp: Server, stdin: Iterable[str] | None = None, stdout: TextIO | None = None) -> None:
    """Answer every line of stdin until it ends; the process's own stdin
    and stdout where none is given."""
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            _write(stdout, error_response(None, PARSE_ERROR, "bad JSON"))
            continue
        response = mcp.handle(message)
        if response is not None:
            _write(stdout, response)


def _write(stdout: TextIO, payload: Response) -> None:
    stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    stdout.flush()
