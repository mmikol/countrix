---
name: Never more than three supports
kind: constraint
category: shape
require: team.supports <= params.MAX_SUPPORTS
params:
  MAX_SUPPORTS: 3
---
# Never more than three supports

A six fields at most three supports, on every board. Open Queue sets no cap on supports, so this rule sets one: a six with a fourth support is never chosen. Measured as the six's support count.
