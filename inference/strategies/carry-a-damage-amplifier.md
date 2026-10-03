---
name: Carry a damage amplifier
kind: heuristic
category: damage
weight: 0.5
bonus: min(team.dmg_amp, params.AMPS) / params.AMPS
params:
  AMPS: 1
---
# Carry a damage amplifier

A six carries a pick that amplifies its teammates' damage. A Discord Orb, a damage boost or a Nano Boost adds a kill threat without adding a gun: it makes a tank's large pool killable and turns a target that was surviving into one that is not, which counts most against two tanks. The rule pays its weight when at least one pick amplifies damage.
