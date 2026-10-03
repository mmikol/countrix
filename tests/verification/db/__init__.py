"""The data layer's tests, and what several of them share: write_aged(), a
cached page written as if fetched hours ago, and two wiki pages as a pull
reads them - the Hybrid mode's article (HYBRID_PAGE) and the Team
Composition page (COMPOSITION)."""

import os
import time

HYBRID_PAGE = """[[File:Hybrid.png|right|frameless]]
'''Hybrid''' is one of the main [[game mode]]s. It is a combination of the
[[Assault]] and [[Escort (game mode)|Escort]] modes.

==Gameplay==
In the first section, the attacking team must capture a point.
"""

COMPOSITION = """
= Popular compositions =
Most teams settle on one style, such as [[Dive]].

== Dive ==
Dive wins on mobility, with heroes like [[Genji]].

=== Dive heroes ===
'''Tank:''' [[Winston]], [[D.Va|DVa]]
* note

== Brawl ==
Brawl fights close, behind [[Reinhardt]].

=== Brawl heroes ===
* '''Tank:''' [[Reinhardt]], [[Winston]]

=== Poke heroes ===
No list yet.

= References =
[[Tracer]]
"""


def write_aged(path, text, hours=48):
    """Write a cached page whose modification time is `hours` old."""
    path.write_text(text, encoding="utf-8")
    stamp = time.time() - hours * 3600
    os.utime(str(path), (stamp, stamp))
