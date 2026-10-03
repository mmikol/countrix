---
name: The tank line carries a barrier
kind: heuristic
category: durability
weight: 1
penalty: max(0, 1 - team.barrier_hp / params.FRONT_BARRIER)
params:
  FRONT_BARRIER: 600
---
# The tank line carries a barrier

The tank line carries a barrier that shields the team. In 6v6 the two tanks split the work, one holding ground behind a barrier while the other dives or peels; two tanks with no barrier between them are called no better than one, with nothing to stop a hit before it lands, and Blizzard added cover to its maps when the format lost a tank and its shields. Barrier health on the six is read against 600, a main tank's barrier: at 600 or more it costs nothing, and each part short of it costs that share of the weight.
