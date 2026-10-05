"""The board: a map selector and a red and a blue roster, organised and
styled like the game's hero select, over the facts layer and the inference
layer.

    python -m ui.board            # serves http://localhost:8017

http.server and psycopg, no web framework, no build step. This module is
the board's server - the roster and facts endpoints, and the handler that
routes to them, to the engine's routes ui/serve.py answers and to the
pages ui/pages.py, ui/registry.py and ui/study.py render: the board, /math,
/registry, each rule's math, and /study, the proof and the study's
results. Every click re-reads the database: the facts
panel is the FactSet for (map, side, red, blue, bans); the comps panel is
the inference layer's board - red's likely six around its picks, each
with its pick score, blue's picks filled and its optimal counter to red's,
blue's picks scored as a share of its optimal, the fight odds and the game
plan; the playbook panel is the strategies catalog as it sits on disk.
JSON endpoints under /api/ serve them; /health is the engine's - the
playbook and the database - for the container's healthcheck and
orchestrator.py.

The board writes nothing: a weight set on the playbook panel rides with
the session's own requests and never reaches a strategy file.

A request whose Host or Origin names another server is refused with 403
before it is routed (db.web's guard; --allow-host adds a name the board is
published under). A request that raises is answered by db.web.failure: a
Refusal 400 with its message, anything else 500 with its type and message,
the traceback on stderr. Every board solved, and every request that fails,
leaves a line on stderr.
"""

import argparse
from urllib.parse import parse_qs, urlsplit

import psycopg

from db import psql, web
from facts import board_facts, tables
from facts.draft import Query, parse_board
from facts.roster import roster_of
from ui import pages, registry, serve, study

# --- JSON endpoints ---------------------------------------------------------

def api_roster(cx: tables.Connection) -> web.Reply:
    """The roster the door's roster tool lists, with the role icons and the
    patches newer than the rates the page draws beside it."""
    world = tables.load(cx)
    listed = roster_of(world)
    return web.Reply({"heroes": listed["heroes"], "maps": listed["maps"],
                      "role_icons": world.role_icons,
                      "newer_patches": [p._asdict() for p in world.newer_patches]}, 200)


def api_facts(cx: tables.Connection, query: Query) -> web.Reply:
    draft = parse_board(query)
    world = tables.load(cx)
    return web.Reply(board_facts.generate(world, draft).to_dict(), 200)


# --- server -----------------------------------------------------------------

class Handler(web.Handler):
    timed = frozenset({"/api/board"})

    def _html(self, body: str, code: int = 200) -> None:
        self._send(body.encode("utf-8"), "text/html; charset=utf-8", code)

    def _failed(self, path: str, error: Exception) -> None:
        """A request that raised answers in the shape the route promised: JSON
        under /api/, the error page for a page, in the words and status
        db.web.failure gives it - never a traceback."""
        reply = web.failure(error)
        if path.startswith("/api/"):
            return self._json(reply.body, reply.status)
        page = pages.page("error", "<pre class='warnbox'>%s</pre>" % pages.esc(reply.body["error"]))
        return self._html(page, reply.status)

    def _not_found(self, path: str) -> None:
        if path.startswith("/api/"):
            return self._json({"error": "nothing here"}, 404)
        return self._html(pages.page("not found", "<p>Nothing here.</p>"), 404)

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        path, query = parsed.path, parse_qs(parsed.query)
        try:
            if path == "/":
                return self._html(pages.view_board())
            if path.startswith("/static/"):
                served = pages.static_file(path[len("/static/"):])
                if served is None:
                    return self._not_found(path)
                return self._send(
                    served.body, served.content_type, headers={"Cache-Control": "no-cache"})
            if path == "/math":
                return self._html(pages.view_math())
            if path == "/registry":
                return self._html(registry.view_registry())
            if path == "/study":
                return self._html(study.view_study())
            if path == "/api/strategies":
                return self._json(*serve.handle_strategies())
            if path == "/health":
                return self._json(*serve.handle_health())
            if path not in ("/api/roster", "/api/facts", "/api/board"):
                return self._not_found(path)
            with psycopg.connect(psql.default_dsn()) as cx:
                if path == "/api/roster":
                    return self._json(*api_roster(cx))
                if path == "/api/board":
                    return self._json(*serve.handle_board(cx, query))
                return self._json(*api_facts(cx, query))
        except Exception as error:  # noqa: BLE001  # the request boundary
            return self._failed(path, error)


def command_line(argv: list[str] | None = None) -> argparse.Namespace:
    """The command line: where the board listens, and --allow-host,
    repeated, a host it answers to beside the local ones - the public name
    of a published board, without which every request answers 403."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8017)
    parser.add_argument("--allow-host", action="append", default=[], metavar="NAME")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Serve the board."""
    args = command_line(argv)
    server = web.LocalServer((args.host, args.port), Handler, args.allow_host)
    print("Countrix: http://%s:%d" % (args.host, args.port))
    server.serve_forever()


if __name__ == "__main__":
    main()
