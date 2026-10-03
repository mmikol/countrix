"""The board's pages: the shell, the math page, and the static files they
load. No server and no database - these read ui/pages.py's output
and the scripts' source. The scripts are pinned at their seams - the routes
and query keys they send, the ids they write, the globals and payload keys
they read - against what the shell and the server write. The decisions
only the client can make are pinned in the script: the stale-reply guard;
the HTML escape; the meta and swap-cost weights, never pruned as a stale
heuristic's are; the swaps and suggested slots, drawn only for the picks
the board in hand answered, held while a board solves and never offering a
picked hero; and a taken swap, checked against the bans and the role caps
as a pick is. Any other decision worth pinning is made on the server, as
the seat badge is (momentum.badges), and tested there."""

import os
import re

import pytest

from facts import board_facts, compute
from facts.draft import Draft
from facts.records import Patch
from inference import base, catalog, engine, scale, scoring, solver
from inference.result import Badge, Momentum, OpenSlot, Pick, StageRow, SwapPair, Swaps
from inference.scoring import Contribution
from inference.strategy import WEIGHT_RANGE, StrategyRecord
from tests.verification.inference import BRIEF, FIXTURE_PLAYBOOK
from ui import board, pages, serve


def scripts():
    """The page's three scripts as one text, in the order the page loads them."""
    return "".join(pages.static_file(name)[0].decode()
                   for name in ("comps.js", "playbook.js", "board.js"))


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
    assert "<footer" not in body
    assert "id='flash'" in body[:body.index("</header>")]
    comps = body[body.index("id='tab-comps'"):body.index("id='tab-facts'")]
    assert "id='inf-blue'" in comps and "id='inf-red'" in comps
    assert b".kind.assumption" in pages.static_file("board.css")[0]


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
    assert "id='plan'" in body and "id='momentum'" not in body     # red is never scored: no odds
    # scores live in the boxes
    assert "id='bluescore'" in body and "id='redscore'" in body
    assert "data-clear='red'" in body and "data-clear='blue'" in body
    # blue on the left, red on the right, like the boxes
    assert body.index("id='inf-blue'") < body.index("id='inf-red'")
    assert body.index("id='blueslots'") < body.index("id='redslots'")
    page = pages.view_math()
    assert "id='fight-odds'" not in page and "Red is never optimized" in page
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
    # the two pills, pinned top-right
    links = header[header.index("<span class='links'>"):]
    assert "href='/math'" in links and pages.REPO_URL in links
    assert links.count("<a ") == 2
    assert links.rstrip().endswith("GitHub</a></span>")
    # the page hands the scripts the counts they need
    assert "var TEAM = 6, BANS = 5, SWAP_MAX = 50;" in body
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
    assert names == ["TEAM", "BANS", "SWAP_MAX"]
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
    read("pairs open verdict status", Swaps.__annotations__)
    read("out in at portrait why", SwapPair.__annotations__)
    read("hero portrait why", OpenSlot.__annotations__)
    read("stage kind current played six swaps blurb solved", StageRow.__annotations__)
    read(
        "picks contributions alternatives considered seconds playstyle cited tie blue",
        solved["current"])
    read("hero role why evidence portrait", Pick.__annotations__)
    read("locked picks", solved["expected"])
    read(
        "id kind applies ok weighted form when bonus penalty norm spread need metric raw"
        " weight fact text", Contribution.__annotations__)
    read("badges", Momentum.__annotations__)
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
    suggest = function(script, "paintSuggestions")
    assert "answered() ? d.swaps : null" in suggest and "sw.open.filter(free)" in suggest
    assert "redAnswered() ? d.expected.picks" in suggest and "st.red.indexOf(p.hero)" in suggest
    assert "d.current.blue" in function(script, "answered")
    assert "d.expected.locked" in function(script, "redAnswered")
    assert "'blueswaps', 'stageplan'" in function(script, "solving")
    take = function(script, "takeSwap")
    assert "st.bans.indexOf(into)" in take and "roleCap('blue'" in take


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
    ("meta", "The meta, %s, scales the whole engine"),
    ("rate", "&middot; ( %s &middot; rates(x)"),
    ("rate", "Under it the rate term is in win-rate points and weighs %s."),
    ("synergy", "+ %s &middot; synergy(x)"),
    ("counter", "+ %s &middot; counters(x) )"),
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
    (compute, "SYNERGY_PULL", "pull(h) = pick(h, map) + %s &times; partners"),
    (scale, "REFERENCE_SIZE", "against %s random legal sixes"),
    (scale, "SCALE_POOL", "each role's %s released heroes"),
    (base, "COIN_FLIP", "t_p &middot; ( win_p &minus; %s )"),
    (pages, "MAX_TANKS", "at most %s tanks"),
    (pages, "MAX_BANS", "within a match's %s bans"),
    (scoring, "NEED_BUDGET", "min( 1, max( %s, the largest w on n's guard ) / &Sigma; w"),
    (scoring, "NEED_BUDGET", "one state costs %s at most"),
    (scoring, "SCORE_PLACES", "by their score to %s decimal places"),
    (solver, "RANK_CAP", "exactly up to %s"),
])
def test_the_math_page_quotes_each_constant_from_the_code(monkeypatch, module, name, phrase):
    """math.html quotes the code's numbers as placeholders ui/pages.py fills in,
    so a changed constant changes the page, and a phrase the page stops
    quoting from the code fails here. The page is read with its line breaks
    as spaces, so rewrapping the article moves no phrase."""
    monkeypatch.setattr(module, name, 37)
    assert phrase % "37" in " ".join(pages.view_math().split())


def test_the_math_page_writes_a_large_count_with_thousands_separators(monkeypatch):
    monkeypatch.setattr(scale, "REFERENCE_SIZE", 12000)
    assert "against 12,000 random legal sixes" in " ".join(pages.view_math().split())


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
    assert "score(x) = base(x)\n         + &Sigma; heuristics h" in page
    assert "norm_h(v) = clamp(" in page
    assert "A heuristic on a metric moves a six by its weight at most" in flat
    assert "What 100 means" in page and "not a win probability" in page
    assert "When nothing scores" in page
    # how a six is chosen: the five steps in order, then what a reader must not assume
    chosen = flat[flat.index("<h2 id='chosen'>"):flat.index("<h2 id='function'>")]
    steps = ["1 the space", "2 the limits", "3 the meta", "4 the heuristics", "5 the argmax"]
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
