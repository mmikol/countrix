"""The board's HTML: the page shell, the math page, and the static files
they load - the stylesheet, the scripts and the display font.

The page is a shell over the static files: board.js loads last because it
calls into comps.js and playbook.js, and TEAM, BANS and SWAP_MAX come from
the page so the scripts keep no constant in step with the Python. The math page's
code numbers are filled in here too, from the modules that hold them, and
the default engine's weights from the playbook's meta.md, so math.html
quotes no constant of its own.
ui/board.py serves these; nothing here reads the database or knows a
route's handler.
"""

import html
import os
from typing import NamedTuple

from facts import compute, counters, scalars
from facts.draft import MAX_BANS, MAX_TANKS, TEAM_SIZE
from inference import base, bounds, catalog, scale, scoring, solver, strategy

GITHUB_MARK = (
    "<svg viewBox='0 0 16 16' width='15' height='15' aria-hidden='true'><path fill='currentColor' d='M8 0C3.58 0 0 3.58 0 8"  # noqa: E501
    "c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94"  # noqa: E501
    "-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2"  # noqa: E501
    "-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0"  # noqa: E501
    " 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95"  # noqa: E501
    ".29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0 0 16 8c0-4.42-3.58-8-8-8z'/></svg>")  # noqa: E501


REPO_URL = "https://github.com/mmikol/countrix"      # the repository the header links to


def esc(x: object) -> str:
    """Text escaped for HTML, None as nothing."""
    return html.escape(str(x if x is not None else ""))


# --- the static files ----------------------------------------------------------

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
# what is served, by extension: the pages' articles (.html) and the font's
# licence (.txt) sit beside these and are not
STATIC_TYPES = {".css": "text/css; charset=utf-8",
                ".js": "application/javascript; charset=utf-8",
                ".woff2": "font/woff2"}


class StaticFile(NamedTuple):
    """A file under ui/static as it is served: its bytes and content type."""
    body: bytes
    content_type: str


def static_file(name: str) -> StaticFile | None:
    """A file under ui/static, or None where the name is not one served."""
    ext = os.path.splitext(name)[1]
    if "/" in name or ".." in name or ext not in STATIC_TYPES:
        return None
    path = os.path.join(STATIC_DIR, name)
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as handle:
        return StaticFile(handle.read(), STATIC_TYPES[ext])


# --- the pages -------------------------------------------------------------------

HEAD = ("<!doctype html><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<link rel='stylesheet' href='/static/board.css'>")


def view_board() -> str:
    """The board: the header, the bans bar, the two rosters and the three
    panels, empty until the scripts fill them."""
    shell = (HEAD + "<title>Countrix</title><main>"
            "<header class='top'><h1>Countrix"
            "<span class='expand'> the counter utility matrix</span></h1>"
            "<div class='mapsel'><select id='mapsel'></select>"
            "<select id='stagesel' title='the stage in play; the whole map by default'"
            " style='display:none'></select><span class='mode' id='mode'></span>"
            "<span class='sideseg' id='sideseg' title=\"blue's side;"
            " red gets the other\">"
            "<button data-side='attack'>attack</button><button data-side='defense'>defense</button>"
            "</span>"
            "<button id='clearall' title='the map, the side, the bans and both teams'>"
            "clear all</button>"
            "<span class='flash' id='flash'></span></div>"
            "<span class='links'><a class='mathlink' href='/math'>the math</a>"
            "<a class='gh' href='%s' target='_blank' rel='noopener'>%s GitHub</a>"
            "</span>"
            "</header>"
            "<div class='bans' id='bans'><div class='banhead' id='banhead'"
            " title='open or close the ban picker'>"
            "<h3>bans</h3><span class='bancount' id='bancount'>"
            "</span><span class='banmini' id='banmini'></span>"
            "<span class='caret'>&#9656;</span></div>"
            "<div class='banbody'><div class='slots' id='banslots'></div>"
            "<div class='roles' id='banroster'></div></div></div>"
            "<div class='warnbox' id='vintage' style='display:none'></div>"
            "<div class='momentum' id='momentum'></div>"
            "<div class='teams'>"
            "<section class='team blue'><h2>blue team <span class='tscore' id='bluescore'"
            " title=\"your picks as a share of blue's optimal\">"
            "</span>"
            "<button class='clearteam' data-clear='blue'>clear</button>"
            "</h2>"
            "<div class='swaps' id='blueswaps'></div>"
            "<div class='slots' id='blueslots'></div><div class='roles' id='blueroster'>"
            "</div></section>"
            "<section class='team red'><h2>red team <span class='tscore' id='redscore'"
            " title=\"how often their likely six is picked\">"
            "</span>"
            "<button class='clearteam' data-clear='red'>clear</button>"
            "</h2>"
            "<div class='slots' id='redslots'></div><div class='roles' id='redroster'>"
            "</div></section>"
            "</div>"
            "<nav class='tabs'><button data-tab='comps'>comps</button>"
            "<button data-tab='facts'>facts</button>"
            "<button data-tab='playbook'>playbook</button></nav>"
            "<section class='panel' id='tab-comps'><div class='plan' id='plan'>"
            "</div><div class='stages' id='stageplan'></div><div class='seats'>"
            "<div class='seat blue' id='inf-blue'></div><div class='seat red' id='inf-red'>"
            "</div></div></section>"
            "<section class='panel' id='tab-facts'><div class='tools'>"
            "<input type='text' id='filter' placeholder='filter'>"
            "<span id='chips'></span><span id='factsn' class='count'></span></div>"
            "<table class='facts'><tbody id='factbody'></tbody></table></section>"
            "<section class='panel' id='tab-playbook'><div id='playbook'></div></section>"
            "</main><script>var TEAM = %d, BANS = %d, TANKS = %d, SWAP_MAX = %g;</script>"
            "<script src='/static/comps.js'></script>"
            "<script src='/static/playbook.js'></script>"
            "<script src='/static/board.js'></script>")
    return shell % (REPO_URL, GITHUB_MARK, TEAM_SIZE, MAX_BANS, MAX_TANKS, base.SWAP_RANGE[1])


def page(title: str, body: str) -> str:
    """A page in the shell the math and error pages share: the
    stylesheet, the title, and a header that links back to the board."""
    return (HEAD + "<title>%s</title>"
            "<main><header class='top'><h1><a href='/'>Counter <span>Utility Matrix</span></a></h1>"
            "</header>%s</main>" % (esc(title), body))


def _article(name: str) -> str:
    """One of ui/static's articles, as text."""
    with open(os.path.join(STATIC_DIR, name), encoding="utf-8") as handle:
        return handle.read()


def view_math() -> str:
    """The math page: ui/static/math.html in the page shell, the code
    constants it quotes filled in from their modules on every call, so the
    page follows the code, and the default engine's weights from the
    playbook in force's meta.md, which holds them. A literal percent in
    math.html is written %%."""
    weights = catalog.engine_weights()
    return page("the math", _article("math.html") % {
        "W_META": weights.meta,
        "W_RATE": weights.rate,
        "W_SYNERGY": weights.synergy,
        "W_COUNTER": weights.counter,
        "SWAP": catalog.swap_cost(),
        "SWAP_MAX": base.SWAP_RANGE[1],
        "WIKI_WEIGHT": counters.WIKI_WEIGHT,
        "DERIVED_WEIGHT": counters.DERIVED_WEIGHT,
        "TOP_ANSWERS": counters.TOP_ANSWERS,
        "THRESHOLD": counters.THRESHOLD,
        "RATE_PICK_HALF": base.RATE_PICK_HALF,
        "LOGIT_PER_POINT": base.LOGIT_PER_POINT,
        "PARTNER_POINTS": compute.PARTNER_POINTS,
        "REFERENCE_SIZE": format(scale.REFERENCE_SIZE, ","),
        "SCALE_POOL": scale.SCALE_POOL,
        "COIN_FLIP": base.COIN_FLIP,
        "MECHANISMS": len(counters.MECHANISMS),
        "MAX_TANKS": MAX_TANKS,
        "MAX_BANS": MAX_BANS,
        "WEIGHT_MAX": strategy.WEIGHT_RANGE[1],
        "NEED_BUDGET": scoring.NEED_BUDGET,
        "SCORE_PLACES": scoring.SCORE_PLACES,
        "RANK_CAP": solver.RANK_CAP,
        "FOLD_COUNTS": bounds.FOLD_COUNTS,
        "FORMATION_RADIUS": scalars.FORMATION_RADIUS,
        "TEAMMATES": scalars.TEAMMATES,
        "TEAMMATES_BUT_ONE": scalars.TEAMMATES - 1})

