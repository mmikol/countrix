---
name: Control points have edges
kind: heuristic
category: map
metric: team.cc_count
direction: maximize
weight: 1
when: map.hazards >= 0.5 or (map.name == 'Nepal' and map.stage == 'Sanctum')
---
# Control points have edges

Control stages are built around drops - the well on Ilios, the sanctum pit on Nepal, the edges of Lijiang Tower - and a knockback or a pull turns a full-health enemy into a kill. Roadhog hooking into the well and Lúcio booping on Lighthouse are the community's Control examples, and Orisa is named as good on maps with environmental hazards. Picks with crowd control are counted, read on the ground whose hazards stand 0.5 or more above the ordinary map's and on Nepal's sanctum, which the examples name.
