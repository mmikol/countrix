---
name: Commit to one playstyle
kind: heuristic
category: shape
weight: 0.5
when: team.style_share <= params.SPLIT
penalty: 1
params:
  SPLIT: 0.5
---
# Commit to one playstyle

A six commits to one plan, dive, brawl or poke. Each archetype wins one way - brawl walks in as one unit, dive collapses on one target from several angles, poke holds range from several angles - and a six split between them fights as two half-teams: a brawl tank in front of a poke backline can neither peel a dive nor swing at what stands far away. Each pick's playstyles are counted as fractions of one, a pick with two styles giving half to each, and a six whose largest style carries no more than half its picks pays the weight.
