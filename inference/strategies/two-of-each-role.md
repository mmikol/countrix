---
name: Two of each role
kind: heuristic
category: shape
weight: 4.5
penalty: (team.shape_excess + max(0, params.TANKS - team.tanks)) / params.WORST
params:
  TANKS: 2
  WORST: 3
---
# Two of each role

A six plays two tanks, two damage and two supports. In 6v6 the second tank holds the off-angle and doubles the front's mitigation, so one tank facing two loses the trade for space, two damage picks make the pressure that lets the tanks take it, and each pick past two in a role gives one of those jobs up; a third support behind both tanks is the one off-shape six called strong. Each pick over two in a role costs a third of the weight, a six one tank short pays that once more, and a one-tank six with four damage pays the whole weight.
