"""The Streamable HTTP transport, the data-layer container's door: a client
POSTs one JSON-RPC message to /mcp and gets the response as JSON (a
notification gets 202). No server-initiated streams and no sessions, so
GET /mcp is 405. /health reports the database the tools are pointed at; a
status that raises answers 500 with its type and message (db.web.failure).

db.web's guard refuses a request that does not name this server before any
of it runs. The door then asks for the bearer token when one is set,
refuses a body not labelled application/json with 415, caps a body at
MAX_BODY, and holds each client address to RATE_LIMIT tool calls a
RATE_WINDOW. A tool call it admits is logged on stderr before it runs, with
the client's address and the tool's name.

Each request runs on a thread of its own, but the messages are handled one
at a time, as over stdio: a playbook write reads its file, edits it and
writes it back whole, and two at once would lose one edit.
"""

import hmac
import json
import os
import sys
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from urllib.parse import urlsplit

from db import web
from door.mcp.server import PARSE_ERROR, Server, error_response

MAX_BODY = 1 << 20            # one request is a tool call, not an upload
DRAIN_CHUNK = 1 << 16         # bytes read at a time from an oversize body
RATE_LIMIT = 120              # tool calls per client address per RATE_WINDOW
RATE_WINDOW = 60              # seconds
MAX_TRACKED_CLIENTS = 1000    # past this, clients unseen for a window are forgotten


class _RejectedError(Exception):
    """A request to /mcp the door turns away before its message is handled:
    the status, the JSON body - {"error": reason} unless the reply
    needs its own - and any headers."""

    def __init__(
            self, code: int, reason: str, payload: Mapping[str, object] | None = None,
            headers: Mapping[str, str] | None = None) -> None:
        super().__init__(code, reason)
        self.code = code
        self.payload: Mapping[str, object] = {"error": reason} if payload is None else payload
        self.headers = dict(headers or {})


class HttpHandler(web.Handler):
    server_version = "countrix-mcp/2.1"
    server: "HttpServer"

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/health":
            try:
                return self._json(self.server.status())
            except Exception as error:  # noqa: BLE001  # the request boundary
                return self._json(*web.failure(error))
        if path == "/mcp":
            return self._json(
                {"error": "this server has no server-initiated stream; POST JSON-RPC to /mcp"},
                405, {"Allow": "POST"})
        self._json({"error": "nothing here"}, 404)

    def _check_token(self) -> None:
        """With a token configured, every /mcp request must carry it: one that
        does not is refused 401."""
        token = self.server.token
        header = self.headers.get("Authorization") or ""
        if token and not (header.startswith("Bearer ")
                          and hmac.compare_digest(header[7:].strip(), token)):
            raise _RejectedError(401, "a bearer token is required",
                                 headers={"WWW-Authenticate": "Bearer"})

    def do_POST(self) -> None:
        """One JSON-RPC message: the token checked, the body's JSON label
        checked, the body read, a tool call admitted against the client's
        rate and logged, then handled - 202 for a notification, else the
        answer."""
        if urlsplit(self.path).path != "/mcp":
            return self._json({"error": "nothing here"}, 404)
        try:
            self._check_token()
            if not (self.headers.get("Content-Type") or "").startswith("application/json"):
                raise _RejectedError(415, "a JSON body is required")
            message = self._read_message()
            self._admit(message)
        except _RejectedError as rejected:
            return self._json(rejected.payload, rejected.code, rejected.headers)
        self._log_call(message)
        with self.server.one_at_a_time:
            response = self.server.mcp.handle(message)
        self._json(response, 202 if response is None else 200)

    def _read_message(self) -> object:
        """The request's JSON body, decoded - `null` included, which is a
        message the server answers. A Content-Length that is missing, not a
        number or not positive is refused, a body past MAX_BODY is drained
        and refused, and one that is not JSON is a parse error."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length <= 0:             # missing, not a number, or no body at all
            raise _RejectedError(400, "a positive Content-Length is required")
        if length > MAX_BODY:
            drained = 0
            while drained < min(length, 16 * MAX_BODY):     # let the client finish sending
                chunk = self.rfile.read(min(DRAIN_CHUNK, length - drained))
                if not chunk:
                    break
                drained += len(chunk)
            self.close_connection = True
            raise _RejectedError(413, "request too large")
        try:
            return json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise _RejectedError(
                400, "bad JSON", error_response(None, PARSE_ERROR, "bad JSON")) from None

    def _admit(self, message: object) -> None:
        """Refuse a tool call past the client address's rate: the budget is
        the host's."""
        if (isinstance(message, dict) and message.get("method") == "tools/call"
                and not self.server.admit(self.client_address[0])):
            raise _RejectedError(429, "too many calls; try again in a minute",
                                 headers={"Retry-After": str(RATE_WINDOW)})

    def _log_call(self, message: object) -> None:
        """One line on stderr for a tool call, before it runs: the tool's
        name, after the client's address and the time log_message writes,
        so a write, a migration or a rebuild over HTTP leaves a record of
        who asked for it."""
        if isinstance(message, dict) and message.get("method") == "tools/call":
            params = message.get("params")
            name = params.get("name") if isinstance(params, dict) else None
            self.log_message("tools/call %r", name)


class HttpServer(web.LocalServer):
    """The MCP server over HTTP: the door's token, the rate limit per client
    address, the status /health reports, and the lock a message is handled
    under, one at a time."""

    def __init__(
            self, address: tuple[str, int], mcp: Server,
            status: Callable[[], Mapping[str, object]], allowed_hosts: Iterable[str] = (),
            token: str | None = None, rate_limit: int = RATE_LIMIT) -> None:
        super().__init__(address, HttpHandler, allowed_hosts)
        self.mcp = mcp
        self.status = status
        self.token = token if token is not None else os.environ.get("COUNTRIX_MCP_TOKEN") or None
        self.rate_limit = rate_limit
        self._calls: dict[str, list[float]] = {}
        self._lock = threading.Lock()
        self.one_at_a_time = threading.Lock()

    def admit(self, client: str) -> bool:
        """One tool call against a sliding window of RATE_WINDOW seconds per
        client address; False past the limit."""
        now = time.monotonic()
        with self._lock:
            recent = [t for t in self._calls.get(client, ()) if now - t < RATE_WINDOW]
            if len(recent) >= self.rate_limit:
                self._calls[client] = recent
                return False
            recent.append(now)
            self._calls[client] = recent
            if len(self._calls) > MAX_TRACKED_CLIENTS:
                self._calls = {
                    c: ts for c, ts in self._calls.items() if ts and now - ts[-1] < RATE_WINDOW}
        return True


def serve(
        mcp: Server, host: str, port: int, status: Callable[[], Mapping[str, object]],
        allowed_hosts: Iterable[str] = ()) -> None:
    """Serve `mcp` (a Server) over HTTP until interrupted, answering to the
    local names and `allowed_hosts`."""
    httpd = HttpServer((host, port), mcp, status, allowed_hosts)
    sys.stderr.write("countrix mcp: http://%s:%d/mcp%s\n" % (
        host, port, " (bearer token required)" if httpd.token else ""))
    httpd.serve_forever()
