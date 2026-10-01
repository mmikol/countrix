"""What the two HTTP servers share - the MCP door and the board - and the
one JSON reader orchestrator.py reads their answers with.

A server here answers only requests that name it: LocalServer holds the host
names it answers to, and Handler checks each request's Host and Origin
against them before any route is dispatched, so every method is guarded
alike. Handler also sends the replies - JSON, or bytes of a content type -
and logs one line on stderr for a request that failed or took a timed route.
A request that raised is answered by failure(): a Refusal is the caller's
error, 400 with its message; anything else is the server's fault, 500 with
the error's type and message, and the traceback goes to stderr, never to the
caller. Each server's /health answers a HealthStatus, ok or degraded.

read_json() is the one HTTP reader - the status and the decoded body of any
answer - under orchestrator.py's calls to the stack's servers.

Stdlib only, besides db.Refusal, so what stands on it - the MCP door's HTTP
transport (door/mcp/http.py) - stays dependency-free.
"""

import json
import sys
import time
import traceback
import urllib.error
import urllib.request
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from email.message import Message
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Literal, NamedTuple
from urllib.parse import urlsplit

from db import Refusal

# the names a request may call a local server by: an allowlisted Host, not a bind
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})  # nosec B104
# what each server's /health says of itself: ok, or degraded with the error
type HealthStatus = Literal["ok", "degraded"]


class Reply(NamedTuple):
    """A JSON reply: its body, a JSON object, and its HTTP status - what every
    JSON route of the board answers, and failure(). The body is a Mapping,
    so a route's typed record rides as it is, uncopied."""
    body: Mapping[str, object]
    status: int


def failure(error: BaseException) -> Reply:
    """The reply to a request that raised `error`."""
    if isinstance(error, Refusal):
        return Reply({"error": str(error)}, 400)
    traceback.print_exception(error, file=sys.stderr)
    return Reply({"error": "%s: %s" % (type(error).__name__, error)}, 500)


# --- the guard ---------------------------------------------------------------

def _hostname(url: str) -> str | None:
    """A URL's host name, lowercased, without its port or brackets; None when
    it has none or does not parse."""
    try:
        return urlsplit(url).hostname
    except ValueError:
        return None


def request_allowed(headers: Message, allowed: frozenset[str]) -> bool:
    """Whether a request names a server that answers to `allowed`: its Host
    header's host name is one of them, and so is its Origin's when it sends
    one. A missing or unparsable Host is refused, and so is `Origin: null`.
    The Host check stops DNS rebinding: a page rebound to this address
    sends a same-origin GET with no Origin, but under its own host name."""
    host = headers.get("Host")
    if not host or _hostname("//" + host) not in allowed:
        return False
    origin = headers.get("Origin")
    return origin is None or _hostname(origin) in allowed


class LocalServer(ThreadingHTTPServer):
    """A threading HTTP server that answers to the local names and to any
    `allowed_hosts`: a public host name it is published under."""

    def __init__(
            self, address: tuple[str, int], handler: type[BaseHTTPRequestHandler],
            allowed_hosts: Iterable[str] = ()) -> None:
        super().__init__(address, handler)
        self.allowed_hosts = LOCAL_HOSTS | frozenset(h.lower() for h in allowed_hosts)


class Handler(BaseHTTPRequestHandler):
    """A request to a LocalServer: refused with 403 before dispatch unless its
    Host and Origin name the server, then answered through _send and _json.
    `timed` names the routes whose every request is logged with how long it
    took - the solves; any other request is logged only when it fails."""
    server: LocalServer
    timed: frozenset[str] = frozenset()
    started: float | None = None

    def parse_request(self) -> bool:
        """The request line and headers, parsed, then the guard: a request
        that does not name this server is answered 403 and its connection
        closed, since an unread body must not be parsed as the next request."""
        self.started = time.monotonic()
        if not super().parse_request():
            return False
        if request_allowed(self.headers, self.server.allowed_hosts):
            return True
        self.close_connection = True
        self._json({"error": "host or origin not allowed"}, 403)
        return False

    def _send(
            self, data: bytes, ctype: str | None, code: int = 200,
            headers: Mapping[str, str] | None = None) -> None:
        """One reply: the status, the extra headers, the content type (none
        for an empty body) and length, and the body."""
        self.send_response(code)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        if ctype is not None:
            self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if data:
            self.wfile.write(data)

    def _json(
            self, payload: object, code: int = 200,
            headers: Mapping[str, str] | None = None) -> None:
        """A JSON reply; a payload of None is an empty body with no content
        type - the MCP door's 202."""
        if payload is None:
            return self._send(b"", None, code, headers)
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(data, "application/json", code, headers)

    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        """One line on stderr for a request that failed - a status of 400 or
        more - or took a timed route: the request line, the status and the
        seconds since the request was read. Nothing for the rest, and nothing
        on stdout, which over stdio is the MCP wire."""
        status = code if isinstance(code, int) else 0        # an HTTPStatus is an int
        if status < 400 and urlsplit(self.path).path not in self.timed:
            return
        spent = time.monotonic() - self.started if self.started is not None else 0.0
        self.log_message('"%s" %s %.2fs', self.requestline, status or code, spent)


# --- the reader --------------------------------------------------------------

@dataclass(frozen=True)
class JsonAnswer:
    """What a server answered over HTTP: its status and its body decoded as
    JSON, None when the body is not JSON."""
    status: int
    body: object


def read_json(request: urllib.request.Request | str, timeout: float) -> JsonAnswer:
    """The status and decoded body of any answer, an error status included.
    Nothing answering - a refused connection, a timeout - is an OSError and
    propagates, so each caller keeps the reason in its own words."""
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310  # the one caller, orchestrator.py, passes its own http literals
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as error:          # a URLError, so caught first
        status, raw = error.code, error.read()
    try:
        body = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        body = None
    return JsonAnswer(status, body)
