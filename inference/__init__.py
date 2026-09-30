"""The INFERENCE LAYER: facts in, the optimal composition out.

The playbook, which imports nothing from the search:

    strategies/   the playbook - STRATEGIES = CONSTRAINTS ∪ HEURISTICS ∪ ASSUMPTIONS:
                  one markdown file per strategy, meta.md, the default
                  engine's weights, and tuning-log.md, a line per change. A
                  constraint is a limit (require: always holds, never
                  weighted); a heuristic weighs what is left, a metric
                  maximised or minimised or a bonus/penalty while a
                  condition holds; an assumption is prose the agent holds a
                  comp to
    README.md     the citation record the playbook is rebuilt from: a line
                  per strategy id, shipped or removed, with the threads a
                  rule was drawn from or the user's word for an assumption
    frontmatter   the dialect a strategy file's frontmatter is written in
    expr          the safe expression language the frontmatter uses
    strategy      one strategy: its fields, its kind and form, and the rules
                  every file keeps
    catalog       reads the playbook's files into strategies, orders, mirrors
                  and documents them, and meta.md into the default engine's
                  weights; AUTHORED, the `sources` row the mirror carries
    tune          one validated, logged edit to a strategy file or to
                  meta.md; add and complete

The search, which reads the playbook:

    base          the default engine: a six's win rates on the map, the
                  wiki's synergies and its counters against the other side,
                  under one meta weight, the terms the playbook's sit on top of
    scoring       the objective: what one six scores on one board, the
                  default engine's terms and then the playbook's
    shapes        the legal shapes: the role counts a six may take around the
                  locked picks
    scale         the board's one scale: the seeded reference sample and field
                  every heuristic is normalised against, and the board's floor
    bounds        the search's bounds: the most any six a branch can reach
                  scores, each metric's and expression's range over it
    solver        the exact search over every legal six under the constraints
                  and heuristics, by branch and bound; players are assumed to
                  play optimally
    engine        infer() and board(): the API over the solver
    result        the Result and Board records and their citations into the
                  facts the facts layer generated
    plan          the game plan and the verdict in prose
    swaps         blue's swaps: the best six reachable from blue's picks when
                  each pick dropped costs the swap cost, one exact search,
                  paired with the picks it replaces
    supersede     latest wins: a board a newer request replaced stops at its
                  next check
    reach         the board each released hero is optimal on, within a match's bans
    serve         the engine's handlers, which the board runs in-process
"""
