---
name: Every six carries a save
kind: heuristic
category: sustain
weight: 0.75
penalty: max(0, params.SAVES - team.team_saves)
params:
  SAVES: 1
---
# Every six carries a save

Every six carries at least one save: an invulnerability, a death-prevention or a cleanse that lands on a teammate. 6v6 fights turn on ultimate combos and burst windows that land faster than any heal, and a Protection Suzu, Immortality Field, Life Grip, Transcendence or Projected Barrier makes the combo miss or breaks the stun chain before the kill. The picks carrying such a save are counted, Mercy's Resurrect among them, and a six short of one pays the weight.
