---
name: Mobility wins races and high ground
kind: heuristic
category: map
metric: team.mobility_count
direction: maximize
weight: 1
when: map.mode == 'Flashpoint' or map.high_ground >= params.STANDOUT
params:
  STANDOUT: 0.5
---
# Mobility wins races and high ground

On Flashpoint and on high ground, the picks that move win the ground. Flashpoint's next point opens across the largest maps in the game, so a slow six arrives one player at a time, and high ground goes to whoever can get up and back without the long way round the defenders are watching. Picks with a movement or evasive ability are counted on Flashpoint and on the ground whose high ground stands 0.5 sd or more above the ordinary map's.
