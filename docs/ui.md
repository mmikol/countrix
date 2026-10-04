# The board - `ui/`

The page over the three layers. Every click - a map, a side, a ban, a hero
on either roster - becomes a request that reads the database, and back
come every fact about that board (the facts layer's, in
[`facts/`](../facts/__init__.py)), blue's optimal six with blue's picks
scored, red's likely six, and the playbook as it sits on disk. No layer imports
the board or its pages.

```bash
.venv/bin/python -m ui.board              # http://localhost:8017, the local cluster
```

An `http.server` handler over psycopg, no web framework, no build step.
The board computes the facts and the comps in its own process, as the
compose stack's `ui` container does. It writes nothing.

## `board.py`, `serve.py`, `pages.py` and `registry.py` - the pages and their endpoints

`pages.py` renders the page, a shell over the static files that injects
only `TEAM` (six), `BANS` (five) and `SWAP_MAX` (the swap cost's ceiling,
`base.SWAP_RANGE`), and the math page; `registry.py` renders the strategy
registry in the math page's shell. `board.py` serves them and the JSON
endpoints behind the host guard `db/web.py` puts on both servers
([security.md](security.md)); `serve.py` answers the board, the catalog
and the health for it.

| route | serves |
| --- | --- |
| `/` | the board: the map selector, the attack/defense switch (Escort and Hybrid maps), the bans bar, the red and blue rosters grouped by role, and three panels - **comps**, **facts**, **playbook** |
| `/static/<file>` | `board.css`, `board.js`, `comps.js`, `playbook.js` and `bebas-neue.woff2`, nothing else |
| `/api/roster` | the roster `facts/roster.py` builds, which the door's `roster` tool lists too: every hero (role, subrole, health pool, portrait, status, release day) and every map (mode, top style, sided or not, its stages in play order), with the role icons and the patches newer than the rates |
| `/api/facts?map=&side=&red=&blue=&bans=[&stage=]` | the FactSet for the board as JSON: the facts and their count; a stage the map lists adds the ground in play (`map.ground`) |
| `/api/board?map=&side=&red=&blue=&bans=[&stage=&weights=&client=]` | the board solved at any step of the draft, every seat on the stage in play (the whole map without one), under the playbook tab's weights: the `board` tool's answer ([mcp.md](mcp.md#the-tools)), from `serve.handle_board`. One board solves at a time; another waits, and answers 429 after a minute (`serve.Admission`); a newer board from the same `client` stops one still solving, which answers 400 (`serve.LATEST`, a lane per client) |
| `/api/strategies` | the catalog: every constraint, heuristic and assumption with its kind, form, frontmatter and body, from `serve.handle_strategies` |
| `/health` | the engine's health, from `serve.handle_health`: ok or degraded, the strategies, the drafts pending and the heroes, and the error naming what is out of reach. The ui container's healthcheck and `orchestrator.py` read it |
| `/math` | `static/math.html` in the page shell, the numbers it quotes filled in by `pages.py` - the default engine's four weights and the swap cost from the playbook's `meta.md`, and from the code `SWAP_MAX`, the counter graph's four constants, `RATE_PICK_HALF`, `COIN_FLIP`, the fight odds' `LOGIT_PER_POINT`, `PARTNER_POINTS`, `REFERENCE_SIZE`, `SCALE_POOL`, `NEED_BUDGET`, the search's `SCORE_PLACES` and `RANK_CAP`, the counter graph's mechanisms, `MAX_TANKS`, `MAX_BANS`, the weight slider's top, and the healing formation's radius and teammates: the equation, how a six is chosen, the scoring function with the default engine under the playbook, the board and how the layers fit |
| `/registry` | the strategy registry, rendered by `registry.py` on every call from the code the solver runs, so it cannot drift from it: every strategy of the playbook in force, a card each anchored by its id (`/registry#<id>`), grouped as limits, heuristics and assumptions under a table of every rule at a glance. A card says in plain words what its rule does, then gives its formula: its form as the code reads it (a limit; a reward or a need - a heuristic on a metric whose gate the board or the six settles; a scored heuristic; an assumption; a draft), its weight and the most it moves a six, its gate with its params filled in and who settles it, and its term in the math page's notation with its own numbers - a need's share of its guard's budget from `scoring.need_scales`. Then each metric it reads, with the registry's meaning (`facts/team.py`, `facts/compute.py`) and how its range rule aggregates it over the six (`Spec.aggregate` in `inference/ranges.py`), its prose, and its entry and sources in `inference/README.md` - where two rules have held its id, the last entry, the earlier rule's folded away and marked so. Each form links its section of `/math`, which gives the forms in general; the page quotes no rate |

The board answers GET alone: any other method is a 501, after the host
guard.

`/api/roster`, `/api/facts` and `/api/board` each open their own
connection and load a fresh World, so a `pull_rates` or a tune shows on
the next click without a restart.

## `static/` - the board's look and behaviour

```
static/
  board.css      the look: the game's - dark surfaces, Bebas Neue headings, a gold accent, red and blue for the sides
  bebas-neue.woff2  the display face, Bebas Neue Regular, served from the board itself
  OFL.txt        its licence, the SIL Open Font License 1.1, which travels with the font
  board.js       state, the rosters, the picks, the bans, the fetches, boot
  comps.js       the comps tab: a seat's result and the two seats
  playbook.js    the playbook tab: the groups, the cards, the weight sliders
  math.html      the math page's article
```

`board.js` loads last, since it calls the other two. It keeps the map, the
side, the bans, both teams' picks and the slider weights in
`localStorage`, so a reload mid-game keeps the board. A click on a
portrait toggles that hero on that team: a banned hero cannot be picked,
and a hero may play for both teams, never twice on one. A change
debounces, then fetches facts and the board together. Each board request
names the page (`client`), so the server stops a board the page has moved
past - that one answers 400 - and the page aborts the older request. A
request that fails says so where its answer would have gone, keeps nothing
of the last board, and is tried again when the page comes back into view
or the network returns. A roster that fails to load is said in the warning
box and asked for again, the wait doubling up to half a minute; nothing
else is drawn before it.

**The rosters.** One tile renderer draws both rosters and the ban picker
as the same hero select: portrait tiles in tank, damage and support
columns, lit when picked, dotted when on the other team, crossed out when
banned. A tile dims once its team's limits leave no room for one more of
its role, and a click on it is refused with a note. Blue's limits are the
queue's two tanks and the playbook's shape limits - the
`(tanks, damage, supports)` triples the board result carries; red's are
the queue's two tanks alone, since the playbook's limits are blue's and
red's picks are never ruled out. An **announced** hero, one the wiki knows
ahead of release, sits in its role column as the same tile, dimmed and
tagged "coming soon", with its portrait or a silhouette. It has no click
handler, so it never enters the state, and the solver never fields it;
once Blizzard lists the hero, the tile comes alive on the next refresh.

**The swaps.** Above blue's picks, where the board suggests a swap, the
incoming hero's portrait sits over the pick it replaces (`swaps.pairs`,
each at its pick's place), under the board's verdict; a click trades that
pick in place, and the board solves again. The suggestion is one joint
answer ([The swaps](inference.md#the-swaps)): taking one leaves the rest
the board's answer from the new picks, and a half-drafted seat's empty
slots show the fill's heroes (`swaps.open`), as they do without a swap.
Nothing is drawn for red.

**The stage picker** beside the map lists the map's stages after WHOLE
MAP, hidden on a map without stages and cleared when the map changes; a
stage rides every request as `stage=`.

**The bans bar** starts collapsed: the count and the current bans as small
portraits, a click on one un-bans it. Opened, it shows the five slots (two
red, two blue, the lobby's) over the rosters' portrait grid. A click on a
tile bans that hero, which leaves both rosters and the search; a click on
a banned tile or its slot un-bans it; at five, the rest dim.

**The comps panel** answers at every stage of a draft: the game plan in
prose on top, then the plan stage by stage on a map with stages - a row a
stage in play order, its six with the heroes swapped in outlined, marked
where it is the board's stage and dimmed where it is played, and its
blurb ([The plan stage by stage](inference.md#the-plan-stage-by-stage)) -
then two seats, neither with a score. Blue's (left) shows
the six the plan describes - *your picks, the rest filled* from one to
five picks, *your six* at six - over blue's *optimal vs red's picks* (*vs
red's likely six* before red reveals one, alone before any pick), which
blue's own picks never constrain. Red's (right) is their likely six,
*their picks, the rest likely* once red reveals one: red's picks, then a
two-two-two filled slot by slot with the hero of the highest pick score -
how often a six fields it, plus 2 for each synergy partner already on the
six - past the bans, with red's badge in its title. Red is never
optimized: it reads no strategy, and only a new map, ban or red pick sends
it back to *searching*. Under a six's cards sit
the search's numbers (the candidates, every six of the legal shapes its
answer covers; the seconds; the lean), the default engine's
three terms - `base.rates`, `base.synergy`, `base.counters`, a bar each
with the fact it read, always shown - then the strategies in three tabs -
*satisfied*, *costing* with the summed cost, *did not read* - under a
filter, each bar's tooltip saying why it paid or did not, and last the
alternatives. The bars share one scale.

**The fight odds** strip above the teams splits 100 between blue's six
and red's likely six, both scored on the default engine alone against
red's six, the gap between them in win-rate points, put through the
additive model's logistic curve ([The share](inference.md#the-share));
it shows no percent sign, since the split is the model's reading of the
gap, not a chance of winning measured from matches. Its tooltip is the
engine's words; where there are no odds the strip shows the engine's
verdict instead. It reads *solving* while a board is searched.

**The badges** above the pickers: blue's is its comp as a share of blue's
optimal, read from the seat's floor, the lowest of its reference sixes,
up to its optimal ([The share](inference.md#the-share)). Blue still
drafting reads the share the best six from its picks reaches, and the
tooltip says so; before any pick the badge shows the suggested six's 100.
Where blue's own picks break one of the playbook's limits the badge reads
*not allowed*, the limit named in the tip, and the comp has no score or
share; where the optimal scores no higher than the floor, as every six
does when a caller turns the engine off under a playbook that scores
nothing, it reads *unscored*, the engine's reason in the tooltip. Red's
badge is how often a six fields the heroes of its likely six, on average
(*24% avg pick*), since red has no share. The engine
words each badge (`momentum.badges`, a label and a tip); the page only
shows it.

**The suggestions.** Blue's empty slots carry the fill - the best six that
keeps your locked picks, the optimal six before any pick - and red's carry
its likely six around its picks, each a click from locking, its reasons
(and for red its pick score) in the tooltip and on the comps tab. A filled
slot's tooltip is the reason this board gives its hero: blue's from the
fill or the six, red's from their likely six.

**The facts panel** filters by text and by scope and says how many it
holds beside the filter ("12 of 464 facts" under a filter); the tab
carries no number.

**The playbook panel** opens with the meta, the card of `meta.md`: its
four weights and swap cost, its prose, the Meta slider, which scales the
whole default engine, and the Swap cost slider, 0 to `SWAP_MAX` (50)
share points in halves, sent as `weights=swap:<value>`. Under it the catalog follows in three groups in the
equation's order, under a row of anchors, each card edged in its kind's
colour and its meta line its form. Under each heuristic sits a slider for
its weight, 0 to 10 to the hundredth, with a number box, a reset and the
file's weight as the default; the Meta slider is one more of the kind. A
setting stays in the browser and rides with every board request as
`weights=<id>:<value>`, the meta's as `weights=meta:<value>`; the solver
applies it to that board only (each result names its `weights`), and the
file is untouched. A setting whose heuristic the catalog no longer holds
is dropped when the playbook loads; the meta's and the swap cost's are
always kept. Only `tune` changes a file's weight, the meta's and the swap
cost included. Each card's *its math* links its rule's entry on the
registry (`/registry#<id>`), the meta's the default engine on the math
page.

**The header** pins three pills top-right: *the math*, *the registry*
beside it, and the repository on GitHub; the header's right padding keeps
the row clear of them. Below 800 px they join the row instead, beside the
title where both fit and under it where they would meet. Its *clear all* empties the map, the side, the bans and both teams
and leaves the weights; each team's box has its own *clear*. Its only
messages are short-lived flashes - a banned pick, a full team, a refused
pick. A patch newer than the rates raises the warning box; the rates'
capture date is a fact.

`board.css` puts the game's look on a faint diagonal stripe and colours
the kinds: blue for constraints, green for heuristics, sand for
assumptions. The core palette is tokens in `:root`; the rest, the sand
`#d9b36a` among them, are literals. The code, the styles and the font are
served from `static/`, Impact standing in until the font arrives; the
portraits and role icons load as `<img>` from Blizzard's CDNs.

## One click on the board

```mermaid
sequenceDiagram
    actor You
    participant Board as ui/board.py
    participant Facts as facts/ (World + FactSet)
    participant Solver as inference/ (solver)
    participant DB as PostgreSQL

    You->>Board: pick the map and your side, set the bans,<br/>click red picks as they reveal, lock your blue picks
    Board->>Facts: /api/facts (map, side, red, blue, bans)
    Facts->>DB: load the World (25 queries)
    Facts-->>Board: F1..Fn - every fact about those heroes,<br/>the map, each team, the matchup
    Board->>Solver: /api/board (map, side, red, blue, bans)
    Solver->>Solver: blue's seat: shapes the limits allow · every legal six,<br/>bounded and pruned · the best proved, a few dozen scored in full
    Solver->>Solver: red's likely six: their picks, the rest by pick score (pick rate and synergy)
    Solver->>Solver: blue's current comp: six locked -> ranked among every legal six;<br/>fewer -> scored with the optimal search's bounds
    Solver->>Facts: the FactSet for each (map, side, red, the six)
    Solver-->>Board: the game plan, blue's optimal with reasons and [F#]<br/>citations, red's likely six with its pick scores, the fight odds, the suggestions for the empty slots
```

Sides exist on Escort and Hybrid maps only, and the facts say which side
each team holds. The rates do not split by side, so a strategy brings the
side in through a `when` that reads `map.side`. The shipped playbook holds
one, `defenders-stack-barriers`, which pays stacked barrier health on
defense at a hard choke; the two in the [fixture
playbook](../tests/fixtures/playbook/) show the form - engage tools and
anti-heal on attack, deployables, barriers and reach on defense.
