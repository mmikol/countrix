# Questions

## Will the best six win?

Countrix makes no such promise. The best six is the best for the model:
Blizzard's rates, the wiki's synergies and counters, the playbook's
rules and their weights, and the assumptions, every player playing
optimally among them. The search proves no legal six scores higher under
that model. Whether the model matches your lobby is for your games to
say.

## Why does it suggest heroes we do not play?

Countrix knows no hero pools. Lock in the heroes your team plays and the
board fills the rest around them; the alternatives under each six offer
the next best. Ban a hero only when the match bans it, since a ban takes
the hero from both teams.

## Why did red's six stay put when I picked for blue?

Red's likely six comes from how often each hero is picked, around red's
own picks. It reads no rule and is never optimized, so only a new map,
a ban or a red pick changes it.

## Is this 5v5 or 6v6?

6v6 Open Queue: six a side, any mix of roles, at most two tanks. The
kits are read in their 6v6 form from the wiki. The rates are the one
part in 5v5, since Blizzard publishes Role Queue rates alone. The board
drafts six a side and has no 5v5 mode.

## Can a team use it?

Yes. One player drives the board through the draft: the map, the side,
the bans, red's picks as they show and your own as you lock them in.
Between fights the swaps and the stage plan say what to change. A
team's own rules go into the playbook with `/strategy`, and its trust
in the meta goes on the Meta slider for a session, or into `meta.md`
with `/tune`.

## Does it use AI?

The board does not. It is arithmetic: a fixed formula and an exact
search, the same answer every time. Claude Code is optional: `/comp`
lets you ask for a comp in chat, and `/tune` and `/strategy` change the
playbook in your own words, all on the same engine the board runs.

## Will the same draft always give the same six?

Yes. The search is exact and deterministic. Where sixes tie, a fixed
draw from the map, the side and each hero picks one, and the six says
so.

## How fresh are the numbers?

F1, the first fact, gives the rates' capture date and patch. With the
Docker stack up, the refresher takes new rates every day; without it,
refresh them yourself ([the data](data.md#refresh-it-yourself)). A patch
newer than the rates raises a warning on the board.

## Where are my settings kept?

In your browser: the map, the stage, the side, the bans, the picks, the
slider weights and the open tab survive a reload. The board writes
nothing to the database or the playbook.

## Does it work for PC, or outside the Americas?

The rates are console, Americas. The counters, synergies and playstyles
hold for every rank and region by design. On PC or elsewhere the rates
stand in for your own, as they stand in for Open Queue.

## Why the name?

Countrix is short for Counter Utility Matrix: who counters whom, what a
six is worth once the facts are counted, and every row of the data
crossed with every other. The math page opens with it.

## Can I share it, or change it?

Countrix's code is free for noncommercial use under the PolyForm Strict
License 1.0.0, which allows no redistribution, no changes and no new
works; anything else needs a separate written licence from the author.
[Credits and licences](credits.md) has the rest.
