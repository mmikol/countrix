"""The board's pages: the shell, the math page, the strategy registry's
seams, and the static files they load. No server and no database - these
read ui/pages.py's and ui/registry.py's output and the scripts' source.
The scripts are pinned at their seams - the routes and query keys they
send, the ids they write, the globals and payload keys they read -
against what the shell and the server write. The decisions
only the client can make are pinned in the script: the stale-reply guard;
the HTML escape; the meta and swap-cost weights, never pruned as a stale
heuristic's are; the swaps and suggested slots, drawn only for the picks
the board in hand answered, held while a board solves and never offering a
picked hero; each team's row, its picks and suggestions drawn together
tank, damage, support while the picks stay stored as picked, each role
keeping its slots while a board solves; a taken swap, checked against the
bans and the role caps as a pick is; and on the registry, the dialog a rule
opens in - the address that names it, the page held still on Back and
Forward, the links that open it and the ones that stay links, the focus,
no markup written, and the entries it copies, hidden but where scripts are
off, the script fails or the dialog is missing, and in print. Any other
decision worth pinning is made on the server, as the seat badge is
(momentum.badges), and tested there."""

import os
import re

import pytest

from db.data.wiki import terrain
from facts import board_facts, compute, tables
from facts.draft import TEAM_SIZE, Draft
from facts.model import ROLES
from facts.records import Patch
from inference import base, bounds, catalog, engine, plan, scale, scoring, solver
from inference.result import (
    Badge,
    Momentum,
    Odds,
    OpenSlot,
    Pick,
    StageRow,
    SwapPair,
    Swaps,
)
from inference.scoring import Contribution
from inference.strategy import WEIGHT_RANGE, StrategyRecord
from tests.verification.inference import BRIEF, FIXTURE_PLAYBOOK
from ui import board, pages, registry, serve


def scripts():
    """The page's three scripts as one text, in the order the page loads them."""
    return "".join(pages.static_file(name)[0].decode()
                   for name in ("comps.js", "playbook.js", "board.js"))


def registry_script():
    """The registry page's script, which opens a rule in its dialog."""
    return pages.static_file(registry.SCRIPT)[0].decode()


def function(script, name):
    """One top-level function's source: from its `function name(` to the next
    top-level function, or the end."""
    start = script.index("function %s(" % name)
    end = script.find("\nfunction ", start + 1)
    return script[start:] if end < 0 else script[start:end]


def test_board_page_has_two_rosters_and_the_three_panels():
    body = pages.view_board()
    assert "class='team red'" in body and "class='team blue'" in body
    nav = body[body.index("<nav class='tabs'>"):body.index("</nav>")]
    assert nav.count("<button") == 3
    for name in ("comps", "facts", "playbook"):
        assert "<button data-tab='%s'>%s</button>" % (name, name) in nav
        assert "id='tab-%s'" % name in body
    # the facts total sits inside the facts panel, beside the filter - not on the tab
    assert "factsn" not in nav
    facts_panel = body[body.index("id='tab-facts'"):body.index("id='tab-playbook'")]
    assert "id='factsn' class='count'" in facts_panel
    assert "up to five, all optional" not in body            # the bans bar carries no hint
    # a team header is its name, its figure and its clear button: no subtitle, no counter
    for team in ("blue", "red"):
        h2 = body[body.index("<h2>%s team" % team) + len("<h2>"):]
        h2 = h2[:h2.index("</h2>")]
        assert h2.count("<") == 4, h2
        assert "id='%sscore'" % team in h2 and "data-clear='%s'" % team in h2
    assert "ARGMAX[" not in body and "href='/math'" in body   # the equation lives on /math
    # one footer, the notices', and no status line or capture date in it
    assert body.count("<footer") == 1 and pages.FOOTER in body
    assert "id='status'" not in body and "id='captured'" not in body
    assert "id='flash'" in body[:body.index("</header>")]
    comps = body[body.index("id='tab-comps'"):body.index("id='tab-facts'")]
    assert "id='inf-blue'" in comps and "id='inf-red'" in comps
    assert b".kind.assumption" in pages.static_file("board.css")[0]


def test_every_page_ends_in_the_footer_of_notices():
    """Every page the board serves - the board, /math, /registry and the
    error pages - closes on pages.FOOTER, the last thing in <main>:
    Blizzard's notice for Overwatch, written as its copyright-notices page
    gives it with the copyright sign, the line that Countrix is not
    Blizzard's, and the Overwatch Wiki's credit and licence with NOTICE's
    address. The facts panel credits the wiki again under its table, since
    its facts quote the wiki's words."""
    board_page = pages.view_board()
    served = {
        "board": board_page, "math": pages.view_math(), "registry": registry.view_registry(),
        "error": pages.page("error", "<p>x</p>")}
    for name, body in served.items():
        assert body.count("<footer") == 1, name
        assert body.index(pages.FOOTER) + len(pages.FOOTER) == body.index("</main>"), name
    for phrase in (
            "Overwatch&trade; &copy; 2016 Blizzard Entertainment, Inc. All rights reserved.",
            "Overwatch is a trademark or registered trademark of Blizzard Entertainment, Inc."
            " in the U.S. and/or other countries.",
            "Countrix is a fan project, not affiliated with or endorsed by Blizzard"
            " Entertainment.",
            "href='https://overwatch.fandom.com'",
            "href='https://creativecommons.org/licenses/by-nc-sa/3.0/'",
            "written by its contributors and licensed under", "href='%s'" % pages.NOTICE_URL):
        assert phrase in pages.FOOTER, phrase
    assert pages.NOTICE_URL.startswith(pages.REPO_URL) and pages.NOTICE_URL.endswith("/NOTICE")
    facts = board_page[board_page.index("id='tab-facts'"):board_page.index("id='tab-playbook'")]
    assert pages.WIKI in facts and pages.WIKI_LICENSE in facts
    css = pages.static_file("board.css")[0].decode()
    assert "footer.legal {" in css


def test_the_ban_picker_is_a_roster():
    body = pages.view_board()
    assert "id='banhead'" in body and "id='banslots'" in body and "id='banroster'" in body
    assert "id='banmini'" in body and "id='bancount'" in body
    css = pages.static_file("board.css")[0].decode()
    assert ".bans.open .banbody" in css and ".bans .tile.banned" in css


def test_the_page_is_a_shell_over_static_files():
    body = pages.view_board()
    assert "/static/board.css" in body and "/static/board.js" in body
    order = [body.index("/static/%s.js" % n) for n in ("comps", "playbook", "board")]
    assert order == sorted(order)      # board.js loads last: it calls the others
    assert "id='plan'" in body and "id='momentum'" in body         # the fight odds strip
    # scores live in the boxes
    assert "id='bluescore'" in body and "id='redscore'" in body
    assert "data-clear='red'" in body and "data-clear='blue'" in body
    # blue on the left, red on the right, like the boxes
    assert body.index("id='inf-blue'") < body.index("id='inf-red'")
    assert body.index("id='blueslots'") < body.index("id='redslots'")
    page = pages.view_math()
    assert "id='fight-odds'" in page and "Red is never optimized" in page
    # a table of contents: every link resolves to an id on the page
    toc = page[page.index("<nav class='toc'>"):page.index("</nav>")]
    targets = re.findall(r"href='#([^']+)'", toc)
    assert targets and all(("id='%s'" % t) in page for t in targets), targets
    for name in ("chosen", "likely-comp", "counter", "weights", "what-100-means", "argmax",
                 "deterministic"):
        assert name in targets
    assert "<h2 id='equation'>The Counter Utility Matrix</h2>" in page  # the name is the equation
    # and the page says what the short name stands for
    assert "<b>Countrix</b> is short for <b>Counter Utility Matrix</b>" in page
    css = pages.static_file("board.css")[0].decode()
    for rule in (".tile.capped", ".tile.soon", ".inf-six + .inf-six"):
        assert rule in css, rule
    assert "id='clearall'" in body
    header = body.split("</header>")[0]
    # the three pills, pinned top-right: the math, the registry beside it, GitHub
    links = header[header.index("<span class='links'>"):]
    assert "href='/math'" in links and pages.REPO_URL in links
    assert links.count("<a ") == 3
    assert links.index("href='/math'") < links.index("href='/registry'") < links.index(
        pages.REPO_URL)
    assert links.rstrip().endswith("GitHub</a></span>")
    # the page hands the scripts the counts they need
    assert "var TEAM = 6, BANS = 5, TANKS = 2, SWAP_MAX = 50;" in body
    data, ctype = pages.static_file("board.js")
    assert ctype.startswith("application/javascript") and b"function paint" in data
    data, ctype = pages.static_file("comps.js")
    assert ctype.startswith("application/javascript") and b"function resultHTML" in data
    data, ctype = pages.static_file("playbook.js")
    assert ctype.startswith("application/javascript") and b"function renderPlaybook" in data
    assert pages.static_file("math.html") is None          # the article is not served on its own
    data, ctype = pages.static_file("board.css")
    assert ctype.startswith("text/css") and b".tile.banned" in data
    assert pages.static_file("../board.py") is None and pages.static_file("nope.js") is None


def test_the_display_font_ships_with_the_board_and_its_licence():
    """The page loads nothing from another host: the headings' face is served
    from ui/static, and the SIL OFL that lets it travel travels beside it."""
    data, ctype = pages.static_file("bebas-neue.woff2")
    assert ctype == "font/woff2" and data.startswith(b"wOF2")
    css = pages.static_file("board.css")[0].decode()
    assert "@font-face" in css and "url('/static/bebas-neue.woff2')" in css
    assert "fonts.googleapis" not in css and "@import" not in css
    assert pages.static_file("OFL.txt") is None            # beside the font, not served
    with open(os.path.join(pages.STATIC_DIR, "OFL.txt"), encoding="utf-8") as handle:
        licence = handle.read()
    assert "SIL OPEN FONT LICENSE Version 1.1" in licence and "Dharma Type" in licence


def test_the_scripts_send_the_routes_and_query_keys_the_board_reads():
    """Each route the scripts ask for is the board's own, each a GET - the
    board writes nothing - and each key of a board's query is sent in the
    spelling parse_board reads, with the sliders' weights and the page's
    client, which serve.handle_board reads beside them."""
    script = scripts()
    for route in ("/api/roster", "/api/facts?", "/api/board?", "/api/strategies"):
        assert route in script, route
    assert "POST" not in script
    for key in ("map", "stage", "side", "red", "blue", "bans", "weights", "client"):
        assert "'%s='" % key in script, key


def test_the_scripts_write_the_ids_and_read_the_globals_the_shell_holds():
    """Every element a script looks up by a literal id is one the shell
    renders, the data attributes the clicks read are the shell's, each
    global the shell sets is read, and the weight slider and its number box
    carry the bounds the strategy rule checks a weight against."""
    script, body = scripts(), pages.view_board()
    ids = set(re.findall(r"\bel\('([^']+)'\)", script))
    assert len(ids) >= 20
    assert [i for i in sorted(ids) if "id='%s'" % i not in body] == []
    for attribute in ("data-tab", "data-clear", "data-side"):
        assert attribute in script and attribute in body, attribute
    for attribute in ("data-swap-in", "data-swap-out"):       # drawn by the script alone
        assert attribute in script, attribute
    shell = re.search(r"<script>var (.*?);</script>", body).group(1)
    names = [part.split(" = ")[0] for part in shell.split(", ")]
    assert names == ["TEAM", "BANS", "TANKS", "SWAP_MAX"]
    for name in names:
        assert re.search(r"\b%s\b" % name, script), name
    assert script.count("min='%g' max='%g' step='0.01'" % WEIGHT_RANGE) == 2


def test_the_scripts_read_payload_keys_the_server_writes(synthetic_world, monkeypatch):
    """Each key a script reads off a payload is one the server writes: the
    board and a seat on it, a pick, a contribution, the momentum and a
    badge, a strategy, a fact, and the roster with its heroes, maps and
    patches. No script reads the raw sum."""
    script = scripts()

    def read(keys, written):
        for key in keys.split():
            assert key in written, key
            assert re.search(r"\.%s\b" % key, script), key
    solved = engine.board(synthetic_world, Draft("Harbor Gate", ("Mortar",), ("Balm",)),
                          catalog=catalog.load(FIXTURE_PLAYBOOK), brief=BRIEF).to_dict()
    read(
        "plan momentum shapes current fill expected blue map side swaps stages",
        solved)
    read("pairs open verdict", Swaps.__annotations__)
    read("out in at portrait why", SwapPair.__annotations__)
    read("hero role portrait why", OpenSlot.__annotations__)
    read("stage kind current played six swaps blurb solved", StageRow.__annotations__)
    read(
        "picks contributions alternatives considered seconds playstyle cited tie blue",
        solved["current"])
    read("hero role why evidence portrait", Pick.__annotations__)
    read("locked picks", solved["expected"])
    read(
        "id kind applies ok weighted form when bonus penalty norm spread need metric raw"
        " weight fact text", Contribution.__annotations__)
    read("badges odds verdict", Momentum.__annotations__)
    read("blue red tip", Odds.__annotations__)
    read("label tip", Badge.__annotations__)
    read(
        "id name kind form weight direction metric need when require penalty bonus params body",
        StrategyRecord.__annotations__)
    monkeypatch.setenv("COUNTRIX_STRATEGIES", FIXTURE_PLAYBOOK)
    playbook = serve.handle_strategies().body
    read("strategies meta", playbook)
    read("meta rate synergy counter swap body", playbook["meta"])
    fact = board_facts.generate(synthetic_world, Draft()).to_dict()["facts"][0]
    read("id key subject text scope team source warn", fact)
    monkeypatch.setattr(board.tables, "load", lambda cx: synthetic_world)
    synthetic_world.newer_patches = [Patch("a patch", "2026-09-30")]
    roster = board.api_roster(None).body
    read("heroes maps role_icons newer_patches", roster)
    read("name role subrole portrait status release_date", roster["heroes"][0])
    read("name mode style sided stages", roster["maps"][0])
    read("name", roster["newer_patches"][0])
    assert not re.search(r"\.score\b", script)


def test_the_meta_slider_rides_the_weights_key_under_the_name_the_engine_reads():
    """The playbook tab's Meta slider is a weight row like a heuristic's: its
    id is base.META, which parse_weights passes through beside the
    heuristics' ids and BaseWeights.metered reads, so it rides the one
    weights=id:value key, is never pruned as a stale heuristic, and starts
    at meta.md's meta."""
    script = scripts()
    assert "var META = '%s';" % base.META in script
    assert "live[META] = true;" in function(script, "pruneWeights")
    render = function(script, "renderPlaybook")
    assert "weightRow({ id: META, name: 'the meta', weight: m.meta }, 'meta')" in render
    assert catalog.parse_weights(["%s:0.5" % base.META, "coverage:2"]) == {
        base.META: 0.5, "coverage": 2.0}
    assert catalog.META_FILE == base.META + ".md" and base.META in base.DIALS


def test_the_swap_cost_slider_rides_the_weights_key_the_engine_reads_to_its_ceiling():
    """The playbook tab's Swap cost slider is one more weight row: its id is
    base.SWAP, which parse_weights clamps to SWAP_RANGE and the engine reads
    as the board's swap cost, so it rides the one weights=id:value key, is
    never pruned, starts at meta.md's swap and reaches the ceiling the page
    is given."""
    script, body = scripts(), pages.view_board()
    assert "var SWAP = '%s';" % base.SWAP in script
    assert "live[SWAP] = true;" in function(script, "pruneWeights")
    assert "costRow(m)" in function(script, "renderPlaybook")
    assert "SWAP_MAX = %g;" % base.SWAP_RANGE[1] in body
    assert catalog.parse_weights(["%s:99" % base.SWAP]) == {base.SWAP: base.SWAP_RANGE[1]}


def test_the_swap_row_and_the_slots_it_fills_follow_the_picks_the_board_answered():
    """A swap and a suggested slot are drawn only for the picks the board in
    hand answered - the current comp's picks, in the order sent, and red's
    likely six's revealed ones - so a local change hides them until the next
    board lands; a picked hero is never suggested again; red's empty slots
    show its likely six; the swap row and the stage plan wait with the rest
    while a board is solving; and a swap is checked against the bans and the
    role caps as a pick is."""
    script = scripts()
    assert "answered() ? d.swaps : null" in function(script, "paintSwaps")
    suggest = function(script, "paintRows")
    assert "answered() ? d.swaps : null" in suggest and "sw.open.filter(free)" in suggest
    assert "redAnswered() ? d.expected.picks" in suggest and "st.red.indexOf(p.hero)" in suggest
    assert "d.current.blue" in function(script, "answered")
    assert "d.expected.locked" in function(script, "redAnswered")
    assert "'blueswaps', 'stageplan'" in function(script, "solving")
    take = function(script, "takeSwap")
    assert "st.bans.indexOf(into)" in take and "roleCap('blue'" in take
    # the playbook's limits are blue's: red meets the queue's tank limit alone
    assert "if (team === 'red') return role === 'tank' ? TANKS : null;" in function(
        script, "roleCap")


def test_each_team_row_reads_tank_damage_support_and_a_click_names_its_hero():
    """Both team rows are drawn through one ordering, lineup: a team's picks
    and the suggestions for its open slots together, role by role in the
    server's ROLES order, a role's picks first in pick order, then its
    suggestions in the board's order, then empty slots up to the slots the
    role holds in the six the board in hand drew (shapeOf), the picks never
    cut. So while a board solves a pick or a clear in one role moves no other
    role's slots unless it changes how many a role holds - a red pick past a
    role's slots, or its clear, shifts red's picks a slot until the board
    lands - and blue's first
    pick is drawn among the optimal's suggestions, the board in hand's when
    it answered no blue pick, and red's picks keep their places while red's
    suggestions wait for the board that answers them. The stored picks are
    never sorted, so the board is asked in the order picked. A slot's place
    names no pick: a click reads the hero the slot shows, and a swap sits
    over its pick wherever the row draws it, the drawn pick whose place
    among the picks is the pair's `at`. Only an empty slot carries a number,
    counted among the empty slots."""
    script = scripts()
    roles = re.search(r"var ROLES = \[([^\]]*)\];", script).group(1)
    assert re.findall(r"'([a-z]+)'", roles) == list(ROLES)
    order = function(script, "lineup")
    assert "var picks = st[team].map(function (name, at) { return { name: name, at: at }; });" \
        in order
    assert "var open = suggested.map(function (p) { return { name: p.hero, p: p }; });" in order
    assert "r = ROLES.indexOf(h ? h.role : p ? p.role : '');" in order
    assert "return r < 0 ? ROLES.length : r;" in order
    assert "for (var r = 0; r <= ROLES.length; r++) {" in order
    assert "var room = Math.max(shape && r < ROLES.length ? shape[r] : 0, mine.length);" in order
    assert "mine.concat(open.filter(function (x) { return rank(x.name, x.p) === r; }))" \
        ".slice(0, room);" in order
    assert "while (role.length < room) role.push(null);" in order
    # past six, a role over its slots takes the last empty slots, then the
    # last suggestions - never a pick
    assert "row.length > TEAM && k >= 0; k--) if (!row[k]) row.splice(k, 1);" in order
    assert "row.length > TEAM && k >= 0; k--) if (row[k].p) row.splice(k, 1);" in order
    shape = function(script, "shapeOf")
    assert "six.picks.filter(function (p) { return p.role === role; }).length" in shape
    rows = function(script, "paintRows")
    assert "st.blue.length && asked.length ? d.fill : d.blue;" in rows
    assert "var six = src || (asked.length ? d.current : null);" in rows
    assert "paintRow('blue', lineup('blue', open, shapeOf(six)))" in rows
    assert "paintRow('red', lineup('red', likely, shapeOf(ok ? d.expected : null)))" in rows
    paint = function(script, "paint")
    assert "var rows = paintRows();" in paint and "paintSwaps(rows.blue);" in paint
    assert not re.search(r"st(\.blue|\.red|\[team\])\.sort\(", script)
    # each slot draws its entry's hero, a pick solid and a suggestion dashed,
    # with no number; an empty slot counts among the empty slots
    row = function(script, "paintRow")
    assert "s.className = x.p ? 'slot suggested' : 'slot full'; s.setAttribute('data-h', x.name);" \
        in row
    assert "s.removeAttribute('data-h')" in row and "(++empty)" in row
    assert row.count("class='idx'") == 1 and "(i + 1)" not in row
    # a click reads data-h, never a slot's place
    assert not re.search(r"data-i\b", script)
    assert "var hit = near('[data-h][data-team]');" in script
    assert "name = hit.getAttribute('data-h')" in script
    assert "y.at === x.at" in function(script, "paintSwaps")


def test_a_reply_to_an_older_request_is_dropped_and_its_board_cancelled():
    """The guard only the page can keep: each refresh numbers its requests,
    so a reply or a failure from an older one - the facts or the board -
    is dropped, and a newer board request aborts the older one, whose
    server stops solving it."""
    refresh = function(scripts(), "refresh")
    assert refresh.count("mine !== seq") == 4
    assert "solve.abort()" in refresh and "signal" in refresh


def test_an_apostrophe_cannot_close_a_single_quoted_attribute():
    """King's Row in a title='...' attribute must not end the attribute at the
    apostrophe."""
    script = scripts()
    esc = function(script, "esc")
    replaced = "King's Row <b> \"x\" & y"
    for pattern, entity in re.findall(r"\.replace\(/(.)/g,\s*'([^']+)'\)", esc):
        replaced = replaced.replace(pattern, entity)
    assert "'" not in replaced and "<" not in replaced and '"' not in replaced


@pytest.mark.parametrize(("dial", "phrase"), [
    ("meta", "base(x) = %s &middot; ( "),
    ("meta",
        "The engine weight, <code>meta</code> in <code>meta.md</code>, is %s: it scales the"
        " whole default engine"),
    ("rate", "&middot; ( %s &middot; rates(x)"),
    ("rate", "Under it the rate term is in win-rate points and weighs %s."),
    ("synergy", "+ %s &middot; synergy(x)"),
    ("counter", "+ %s &middot; counters(x) )"),
    # the fight odds read the gap in win-rate points: over the meta and the rate weight
    ("meta", "gap = ( s(blue) &minus; s(red) ) / ( %s &middot; "),
    ("rate", "&middot; %s ), in win-rate points"),
    ("synergy", "= rates(blue) &minus; rates(red) + %s / "),
    ("counter", "&minus; synergy(red) ) + %s / "),
])
def test_the_math_page_quotes_each_weight_from_the_playbooks_meta_file(
        monkeypatch, tmp_path, dial, phrase):
    """The default engine's weights are the playbook's: the math page reads
    them from the meta.md in force on every call, so a tuned weight changes
    the page, and a phrase that stops quoting it fails here."""
    with open(os.path.join(FIXTURE_PLAYBOOK, catalog.META_FILE), encoding="utf-8") as handle:
        text = handle.read()
    (tmp_path / catalog.META_FILE).write_text(
        re.sub(r"^%s: .*$" % dial, "%s: 3.7" % dial, text, count=1, flags=re.M),
        encoding="utf-8")
    monkeypatch.setenv("COUNTRIX_STRATEGIES", str(tmp_path))
    assert phrase % "3.7" in " ".join(pages.view_math().split())


@pytest.mark.parametrize(("module", "name", "phrase"), [
    (base, "RATE_PICK_HALF", "t_p = pick_p / ( pick_p + %s )"),
    (base, "LOGIT_PER_POINT", "k = 4 &middot; 6 / 100 = %s"),
    (compute, "PARTNER_POINTS", "pick score(h) = on_six(h) + %s &times; partners"),
    (tables, "STAGE_PRIOR_WORDS", "pulled toward its map's rate by %s words of that rate"),
    (tables, "STAGE_PRIOR_WORDS", "( 1000 &middot; mentions + %s &middot; map rate )"),
    (compute, "STAGE_MENTIONS", "the stage's counts only where its text names the feature %s"
                                " times or more"),
    (terrain, "STAGE_MIN_WORDS", "one mention in a %s-word text"),
    (terrain, "STAGE_MIN_WORDS", "A stage with under %s words of its own reads as its map"),
    (scale, "REFERENCE_SIZE", "against %s random sixes of a legal shape"),
    (scale, "SCALE_POOL", "each role's %s released heroes"),
    (base, "COIN_FLIP", "t_p &middot; ( win_p &minus; %s )"),
    (pages, "MAX_TANKS", "at most %s tanks"),
    (pages, "MAX_BANS", "within a match's %s bans"),
    (scoring, "NEED_BUDGET", "min( 1, max( %s, the largest w on n's guard ) / &Sigma; w"),
    (scoring, "NEED_BUDGET", "the needs on one guard cost %s at most together"),
    (scoring, "SCORE_PLACES", "by their score to %s decimal places"),
    (solver, "RANK_CAP", "exactly up to %s"),
    (bounds, "FOLD_COUNTS", "each where it and those taken before it read %s counts at most"),
    (bounds, "FOLD_COUNTS", "so it reads %s counts at most"),
])
def test_the_math_page_quotes_each_constant_from_the_code(monkeypatch, module, name, phrase):
    """math.html quotes the code's numbers as placeholders ui/pages.py fills in,
    so a changed constant changes the page, and a phrase the page stops
    quoting from the code fails here. The page is read with its line breaks
    as spaces, so rewrapping the article moves no phrase."""
    monkeypatch.setattr(module, name, 37)
    assert phrase % "37" in " ".join(pages.view_math().split())


def test_the_math_page_reads_its_fight_odds_examples_off_the_curve():
    """The fight-odds section's worked examples are plan.fight_odds' own, at
    the slope the page quotes and meta and rate 1, where an engine point is
    a win-rate point: a gap of one point and of four, and one pick's 3-point
    edge in a six, half a point of the rate term."""
    flat = " ".join(pages.view_math().split())

    def odds(gap):
        split = plan.fight_odds(plan.HeadToHead(blue=gap, red=0.0,
                                                per_logit=1.0 / base.LOGIT_PER_POINT))
        return "%d to %d" % (split["blue"], split["red"])
    assert "A gap of one point reads %s and four points %s;" % (odds(1.0), odds(4.0)) in flat
    assert "the new six reads %s against the old" % odds(3.0 / TEAM_SIZE) in flat


def test_the_math_page_writes_a_large_count_with_thousands_separators(monkeypatch):
    monkeypatch.setattr(scale, "REFERENCE_SIZE", 12000)
    assert "against 12,000 random sixes of a legal shape" in " ".join(pages.view_math().split())


def test_the_math_page_states_the_equation_and_the_layers():
    page = pages.view_math()
    for line in ("DATA           = HEROES &cup; MAPS &cup; META",
                 "for each domain D in { HEROES, MAPS, META }:",
                 "  INDEPENDENT(D) = &#8899; facts(s)",
                 "  DEPENDENT(D)   = &#8899; facts(s &#8904; t)",
                 "  FACTS(D)       = INDEPENDENT(D) &cup; DEPENDENT(D)",
                 "FACTS          = FACTS(HEROES) &cup; FACTS(MAPS) &cup; FACTS(META)",
                 "FACTS(D) &cap; FACTS(E) = the joins of D with E",
                 "STRATEGIES     = CONSTRAINTS &cup; HEURISTICS &cup; ASSUMPTIONS",
                 "COMP           = ARGMAX[ STRATEGIES( FACTS ) ]"):
        assert line in page
    # every domain yields both kinds; the dependent ones are the joins, stated as such
    assert "<b>independent</b> facts" in page and "<b>dependent</b> facts" in page
    assert "heroes\n&#8904; map_meta" in page or "heroes &#8904; map_meta" in page
    # the function itself: what it reads, the default engine under the playbook's terms,
    # the formula, the scale, how a heuristic's reach compares with the base, the empty case
    assert "The function: STRATEGIES( FACTS )" in page
    flat = " ".join(page.split())
    assert "<b>The default engine</b>" in page and "Only this term reads a derived edge" in flat
    assert "score(x) = base(x)\n         + &Sigma; rewards h" in page
    assert "norm_h(v) = clamp(" in page
    assert "A heuristic on a metric moves a six by its weight at most" in flat
    assert "What 100 means" in page and "not a win probability" in page
    assert "When nothing scores" in page
    # how a six is chosen: the five steps in order, then what a reader must not assume
    chosen = flat[flat.index("<h2 id='chosen'>"):flat.index("<h2 id='function'>")]
    steps = [
        "1 the space", "2 the limits", "3 the default engine", "4 the heuristics", "5 the argmax"]
    assert [chosen.index(s) for s in steps] == sorted(chosen.index(s) for s in steps)
    for claim in ("weighs nothing", "The weights are not learned", "A score is not a probability",
                  "a proxy for Open Queue 6v6", "unknown, not zero"):
        assert claim in chosen, claim
    assert "The data layer" in page and "The inference layer" in page and "The board" in page
    assert "never calls a language model" in page
    # the counter: blue's own six above the optimal that ignores its picks
    counter = page[page.index("<p id='counter'>"):]
    assert "shows blue's six above the optimal" in counter[:counter.index("</p>")]
    # red is never solved: nothing scores blue's six against red's best reply
    assert "if countered optimally" not in page and "Red is never solved" in page


def test_the_registry_is_a_page_in_the_shell_the_math_page_links_and_the_cards_link_into():
    """/registry is ui/registry.py's page in the shell the math page has,
    with a table of contents whose links land on headings the page shows -
    the top and each kind's table, never in the entries' box it hides; the
    math page's paragraphs on the strategies and on the heuristics' forms
    link it; and each playbook card links its rule's entry, /registry#<id>,
    which the registry anchors by the same id."""
    page = registry.view_registry()
    assert page.startswith(pages.HEAD) and "<h2 id='%s'>The strategy registry</h2>" % (
        registry.TOP) in page
    toc = page[page.index("<nav class='toc'>"):page.index("</nav>")]
    targets = re.findall(r"href='#([^']+)'", toc)
    assert targets == [registry.TOP, *(a for a, _ in registry.GROUPS.values())]
    hidden = page.index("<div id='%s' class='entries'>" % registry.ENTRIES)
    assert all(-1 < page.find("<h2 id='%s'>" % t) < hidden for t in targets), targets
    flat = " ".join(pages.view_math().split())
    strategies = flat[flat.index("<p><b>STRATEGIES</b>"):]
    assert "<a href='/registry'>the strategy registry</a>" in strategies[
        :strategies.index("</p>")]
    forms = flat[flat.index("A heuristic's condition, its <code>when</code>"):]
    assert "<a href='/registry'>the strategy registry</a>" in forms[:forms.index("</p>")]
    script = scripts()
    card = function(script, "renderPlaybook")
    assert "mathLink('/registry#' + esc(h.id)" in card[card.index("function card("):]
    assert "class='reglink' href='\" + href + \"'" in function(script, "mathLink")
    for s in catalog.load():
        assert "<div class='hcard %s' id='%s'>" % (s.kind, s.id) in page, s.id


def test_the_registry_loads_its_script_and_holds_the_dialog_it_opens():
    """The registry loads registry.js after its article, as the board loads
    its scripts, and holds every element the script looks up by a literal
    id - the dialog, its close button and its body, and the entries' box -
    inside the article, so an entry in the dialog wears the article's
    styles. The script reads the entries the server anchors by their ids,
    each named by its first <b>; no other element on the page is one."""
    page, script = registry.view_registry(), registry_script()
    data, ctype = pages.static_file(registry.SCRIPT)
    assert ctype.startswith("application/javascript") and b"function show" in data
    assert page.endswith("</main><script src='/static/%s'></script>" % registry.SCRIPT)
    ids = set(re.findall(r"\bel\('([^']+)'\)", script))
    assert ids == {"rule_box", "rule_shut", "rule_body", registry.ENTRIES}
    article = page[page.index("<article class='math'>"):page.index("</article>")]
    assert article.rstrip().endswith(registry.DIALOG)
    dialog = ids - {registry.ENTRIES}
    assert [i for i in sorted(dialog) if "id='%s'" % i not in registry.DIALOG] == []
    assert "<div id='%s' class='entries'>" % registry.ENTRIES in article
    assert registry.DIALOG.startswith("<dialog id='rule_box' class='rulebox'")
    assert "<button type='button' id='rule_shut'" in registry.DIALOG
    assert "document.querySelectorAll('.hcard[id]')" in function(script, "start")
    assert "copy.querySelector('b')" in function(script, "show")
    strategies = catalog.load()
    assert re.findall(r"class='hcard[^']*' id='([^']+)'", page) == [s.id for s in strategies]
    for s in strategies:
        entry = page[page.index("id='%s'>" % s.id):]
        assert entry.index("<b>") == entry.index("<b>%s</b>" % pages.esc(s.name)), s.id


def test_the_registry_script_keeps_the_address_and_the_dialog_in_step():
    """The address names the open rule. A click pushes its hash and a rule
    opened inside the dialog replaces it, so one Back closes it; the dialog
    follows Back, Forward and a hash typed in; closing it any way takes the
    hash away - back to the entry before the one the page pushed, or cleared
    in place where the page arrived with it. Back or Forward onto a rule
    leaves the page where it is: the browser puts back the scroll that
    address had when it was last left, after the popstate handler, so the
    handler puts the page back a frame later, before the frame is drawn. A
    hash names a rule only where it is an entry's id, decoded with care and
    looked up where no prototype key answers. The entries give their ids up
    to the script before it reads the hash the page arrived with, so the
    dialog's copy never repeats one and the browser's jump to that entry
    finds nothing, and the page stays where it was. A browser without the
    dialog shows the entries instead."""
    script = registry_script()
    rule = function(script, "rule")
    assert "var RULES = Object.create(null);" in script
    assert "try { id = decodeURIComponent(id); } catch (e) { return null; }" in rule
    assert "return RULES[id] ? id : null;" in rule
    opened = function(script, "openRule")
    assert "history.pushState({ pushed: true }, '', '#' + id);" in opened
    assert "if (box.open) { history.replaceState(history.state, '', '#' + id);" in opened
    closed = function(script, "afterClose")
    assert "if (history.state && history.state.pushed) history.back();" in closed
    assert "else history.replaceState(null, '', location.pathname + location.search);" in closed
    sync = function(script, "sync")
    assert "var id = rule(location.hash);" in sync and "else if (box.open) box.close();" in sync
    traversed = function(script, "traversed")
    assert traversed.index("var x = window.scrollX, y = window.scrollY;") < traversed.index(
        "sync();") < traversed.index(
        "if (box.open) requestAnimationFrame(function () { window.scrollTo(x, y); });")
    start = function(script, "start")
    assert "window.addEventListener('popstate', traversed);" in start
    assert "window.addEventListener('hashchange', sync);" in start
    assert "box.addEventListener('close', afterClose);" in start
    assert start.index("card.removeAttribute('id');") < start.rindex("sync();")
    assert script.rstrip().endswith("if (box && box.showModal) start();\n"
                                    "else if (entries) entries.style.display = 'block';")


def test_a_plain_click_on_a_rule_opens_it_and_every_other_link_stays_a_link():
    """Only a plain click on a link whose hash is an entry's id opens the
    dialog: a click with a modifier stays the browser's, and /math, the
    sources and a section's anchor stay links. Every in-page link the
    registry writes is a rule's or one of the page's own anchors, which hold
    an underscore no rule's id can, as every other id the page writes does,
    the dialog's among them, so the script's lookups never find an entry.
    Esc closes the dialog natively, the close button and a press and release
    on the backdrop close it, and the focus goes to the dialog itself on
    opening - on the close button, Space, the browser's page down, would
    press it - and back to the link that opened it on closing, without
    moving the page."""
    script, page = registry_script(), registry.view_registry()
    start = function(script, "start")
    assert ("e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey"
            " || e.altKey") in start
    assert "e.target.closest('a[href^=\"#\"]')" in start
    assert "rule(link.getAttribute('href'))" in start
    assert start.index("if (!id) return;") < start.index("e.preventDefault();")
    assert "shut.addEventListener('click', function () { box.close(); });" in start
    assert "pressed = outside(e) && performance.now() - openedAt > SECOND_PRESS;" in start
    assert "if (pressed && outside(e)) box.close();" in start
    assert "e.target === box" in function(script, "outside")
    show = function(script, "show")
    assert "if (!box.open) { box.showModal(); openedAt = performance.now(); }" in show
    # the dialog takes the focus itself, whichever rule it shows
    assert show.index("box.showModal(); openedAt") < show.index("box.focus();")
    assert "<dialog id='rule_box' class='rulebox' tabindex='-1'>" in registry.DIALOG
    assert "shut.focus" not in script
    assert "openedBy = link;" in function(script, "openRule")
    assert "if (openedBy) openedBy.focus({ preventScroll: true });" in function(
        script, "afterClose")
    rules = {s.id for s in catalog.load()}
    own = {registry.TOP, *(a for a, _ in registry.GROUPS.values())}
    hrefs = set(re.findall(r"href='#([^']+)'", page))
    assert hrefs - rules == own and not own & rules
    others = set(re.findall(r"\sid=['\"]([^'\"]+)['\"]", page)) - rules
    assert others == own | set(re.findall(r"\bel\('([^']+)'\)", script))
    assert all("_" in i and not catalog.ID_RE.fullmatch(i) for i in others)


def test_the_registry_script_writes_no_markup():
    """An entry enters the dialog as a copy of the server's node, which the
    server escaped; the one text the script sets, the dialog's name, it sets
    as an attribute's text. It parses no string as HTML, so nothing it reads
    from the address or the page can become markup."""
    script = registry_script()
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write",
                 "createContextualFragment", "DOMParser", "eval(", "Function("):
        assert sink not in script, sink
    show = function(script, "show")
    assert "RULES[id].cloneNode(true)" in show and "pane.replaceChildren(copy);" in show
    assert "box.setAttribute('aria-label', name ? name.textContent : id);" in show
    assert script.count("setAttribute(") == 1


def test_the_registry_hides_its_entries_but_without_scripts_and_in_print():
    """The page shows the tables and hides the entries' box from the first
    paint: board.css, which the head loads before anything is drawn, hides
    it, for the dialog to copy. Where scripts are off, the noscript style in
    the head, after the stylesheet, shows it, as the script does in a browser
    without the dialog, so the links scroll to the entries. Where the script
    fails to load or to run, the entries keep their ids, and board.css shows
    the box once a link or the address makes one the page's target; the rule
    asks for the id the script takes, so it never matches once the script
    has run. Print shows it too, without the dialog, which Chrome would print
    over every page, and without the dialog's hold on the page's scroll -
    each rule after the screen rule it overrides."""
    page, script = registry.view_registry(), registry_script()
    css = pages.static_file("board.css")[0].decode()
    head, body = page[:page.index("<main>")], page[page.index("<main>"):]
    assert head.endswith(registry.NOSCRIPT)
    assert head.index("/static/board.css") < head.index(registry.NOSCRIPT)
    assert registry.NOSCRIPT == (
        "<noscript><style>.math .entries { display:block; }</style></noscript>")
    assert "<noscript" not in body and "<div id='%s' class='entries'>" % registry.ENTRIES in body
    # hidden on screen by a rule of its own, outside any @media block
    assert "\n.math .entries { display:none; }\n" in css
    # shown for the entry a link or the address targets while it keeps the id start() takes
    target = "\n.math .entries:has(.hcard[id]:target) { display:block; }\n"
    assert css.index("\n.math .entries { display:none; }\n") < css.index(target) < css.index(
        "@media print {")
    assert "card.removeAttribute('id');" in function(script, "start")
    printed = css[css.index("@media print {"):]
    printed = printed[:printed.index("\n}") + 2]
    for rule in (".math .entries { display:block; }", ".math .rulebox { display:none; }",
                 "html:has(.rulebox[open]) { overflow:visible; }"):
        assert rule in printed, rule
    for screen in (".math .entries { display:none; }",
                   "html:has(.rulebox[open]) { overflow:hidden; }"):
        assert css.index(screen) < css.index("@media print {"), screen
    assert script.rstrip().endswith("else if (entries) entries.style.display = 'block';")
