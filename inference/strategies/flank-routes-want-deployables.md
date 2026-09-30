---
name: Flank routes want deployables
kind: heuristic
category: map
metric: team.deployables
direction: maximize
weight: 1
when: map.flanks >= params.STANDOUT
params:
  STANDOUT: 0.5
---
# Flank routes want deployables

A placed object fights a flanker while the team looks elsewhere: turrets counter flank pressure, a wall cuts the diver off, and a tree or a barrier gives the backline something to stand behind. Symmetra is rated one of the better damage picks in coordinated play for her turrets against flanks, and Torbjörn is the answer offered to a flanking Anran. Picks with deployables are counted, read on the ground whose flank routes stand 0.5 sd or more above the ordinary map's.
