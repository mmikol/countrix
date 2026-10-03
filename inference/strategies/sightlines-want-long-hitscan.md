---
name: Long sightlines want long hitscan
kind: heuristic
category: map
metric: team.hitscan_reach
direction: maximize
weight: 1
when: map.sightlines >= params.STANDOUT
params:
  STANDOUT: 0.5
---
# Long sightlines want long hitscan

Long sightlines belong to long-reach hitscan. A hitscan shot lands the instant it is fired at any range the map offers, so on open lanes the fight opens where a Widowmaker, Ashe or Soldier: 76 already hits and projectiles and short guns do not, and Blizzard's designers add corner cover and run a train across Neon Junction to keep snipers from locking it down. Hitscan picks whose weapons reach 30 m or more are counted on the ground whose sightlines stand 0.5 sd or more above the ordinary map's.
