---
name: Capture points reward area effects
kind: heuristic
category: map
metric: team.aoe_count
direction: maximize
weight: 0.25
when: map.objective == 'point'
---
# Capture points reward area effects

A capture-point fight happens on one point with the whole six stacked on it, so healing and damage that touch an area touch everyone. Lúcio's aura and Junkrat's splash both reach the whole point, and a Lúcio and Brigitte pairing was called too strong on king of the hill. Kit pieces tagged area of effect are counted, read wherever the ground is won on a point: Control, Flashpoint and a Hybrid's first phase.
