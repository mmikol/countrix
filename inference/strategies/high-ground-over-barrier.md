---
name: High ground looks over a barrier
kind: heuristic
category: map
weight: 1
when: map.high_ground >= params.STANDOUT
penalty: min(team.barrier_hp / params.BARRIER_HP, params.BARRIER_CAP) * 0.5
params:
  STANDOUT: 0.5
  BARRIER_HP: 1000
  BARRIER_CAP: 2
---
# High ground looks over a barrier

A barrier faces one way and the enemy on the high ground above it shoots past it, so on a map built around high ground a barrier tank is a slow pick paying for a tool that does not work. Reinhardt is named as ineffective on Numbani's first two points for the high ground around them. Each 1000 of barrier health costs half the rule's weight, up to 2000, on the ground whose high ground stands 0.5 sd or more above the ordinary map's.
