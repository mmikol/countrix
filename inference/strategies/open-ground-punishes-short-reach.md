---
name: Open ground punishes short reach
kind: heuristic
category: map
metric: team.range_min
direction: maximize
weight: 0.5
when: map.open_ground >= params.STANDOUT
params:
  STANDOUT: 0.5
---
# Open ground punishes short reach

On open ground the pick with the shortest reach is the one who spends the fight unable to shoot back. Beams and shotguns that own a corridor are helpless across a canyon, so a comp is judged there by its shortest longest-range. The smallest of the picks' longest published ranges is the measure, read on the ground whose open ground stands 0.5 sd or more above the ordinary map's.
