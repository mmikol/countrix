---
name: Edges reward displacement
kind: heuristic
category: map
weight: 1.5
when: map.hazards >= params.STANDOUT or (map.name == 'Nepal' and map.stage == 'Sanctum')
bonus: min(max(team.shove_count - params.SHOVE_FLOOR, 0), params.SHOVE_CAP) / params.SHOVE_CAP
params:
  STANDOUT: 0.5
  SHOVE_FLOOR: 2
  SHOVE_CAP: 3
---
# Edges reward displacement

Where the ground has drops, displacement kills. A knockback, hook or pull over a pit, a ledge or a lava moat removes a full-health enemy outright, and the wiki's pages for Ilios, Lijiang Tower, Nepal and Samoa each name the abilities that do it on or beside the objective. Each pick with a tool that moves an enemy beyond the second earns a third of the weight, up to three, on the ground whose hazards stand 0.5 sd or more above the ordinary map's and on Nepal's Sanctum, which the wiki names.
