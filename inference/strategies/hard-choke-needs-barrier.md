---
name: A hard choke needs a barrier
kind: heuristic
category: map
weight: 1
when: map.chokes >= params.STANDOUT or (map.name == 'Havana' and map.stage in ['City Streets', 'Sea Fort'])
bonus: min(team.barrier_hp / params.CHOKE_BARRIER, 1)
params:
  STANDOUT: 0.5
  CHOKE_BARRIER: 1000
---
# A hard choke needs a barrier

A hard choke is crossed behind a barrier or not at all, and a map whose fights are chokes is a map where one barrier is worth a pick. The community's list of the places a shield is needed is a list of hard chokes - King's Row first point, Eichenwalde third, Havana first and third - and the maps left off it have long sightlines instead. Barrier health earns the rule's weight in full at 1000 and nothing past it, read on the ground whose chokes stand 0.5 sd or more above the ordinary map's and on Havana's first and third stages, which the list names.
