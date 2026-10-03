---
name: Heal at the other side's rate
kind: heuristic
category: sustain
weight: 2
penalty: matchup.heal_shortfall
---
# Heal at the other side's rate

A six heals at least the share of its own pool that the other side heals of its own each second, and never less than the other side's healing in full; an unrevealed slot on that side reads as the 2-2-2's missing role at its median. In 6v6 the second tank on each side brings bigger pools and more incoming damage, so supports heal almost all fight, two light healers fall behind and a lone support is focused first, and with anti-heal on both sides the healing half of the race breaks even at that share. The charge is the weight times the share of that need the six leaves unhealed.
