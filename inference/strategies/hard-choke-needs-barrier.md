---
name: A hard choke needs a barrier
kind: heuristic
category: map
metric: team.barrier_hp
direction: maximize
weight: 1
when: map.chokes >= 0.5 or (map.name == 'Havana' and map.stage in ['City Streets', 'Sea Fort'])
---
# A hard choke needs a barrier

A hard choke is crossed behind a barrier or not at all, and a map whose fights are chokes is a map where one barrier is worth a pick. The community's list of the places a shield is needed is a list of hard chokes - King's Row first point, Eichenwalde third, Havana first and third - and the maps left off it have long sightlines instead. Barrier health is measured, read on the ground whose chokes stand 0.5 or more above the ordinary map's and on Havana's first and third stages, which the list names.
