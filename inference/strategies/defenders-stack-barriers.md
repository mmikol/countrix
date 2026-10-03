---
name: Defenders stack barriers at a choke
kind: heuristic
category: side
weight: 1
when: map.side == 'defense' and map.chokes >= params.STANDOUT
bonus: min(team.barrier_hp / params.STACKED, 1)
params:
  STANDOUT: 0.5
  STACKED: 2400
---
# Defenders stack barriers at a choke

Defending a hard choke, a six stacks barrier health across the one lane the attackers must use. In 6v6 two tanks' barriers laid over a small choke held so well that matches made no progress until ultimates broke them - the double-shield hold - and the defenders pick that ground in their setup time. Barrier health pays the rule in proportion up to 2400, two barrier tanks' worth, on defense on the ground whose chokes stand 0.5 sd or more above the ordinary map's.
