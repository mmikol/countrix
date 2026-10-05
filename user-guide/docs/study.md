# The study

The study asks whether the engine does what it claims: that it truly
optimizes a team, given its assumptions, and how its sixes compare with
the tools players use online. Its results are a page on the board, at
http://localhost:8017/study, and a report.

![The top of the study page](img/study.png)

What the study shows:

- **The proof.** That the search returns the best legal six for its own
  score, given the assumptions, and the checks that hold it to that.
- **The meta.** How close its sixes come to what players pick and to
  what wins, by Blizzard's numbers and by CounterWatch's 6v6 numbers.
- **Synergy and counters.** How much of each its sixes carry, by the
  wiki and by CounterWatch.
- **The rules.** What the playbook's heuristics add to a six, and what
  they cost it.
- **The benchmark.** Where Countrix's six lands beside CounterWatch's
  team builder and the kinds of tool players use online: popularity
  tier lists, win-rate tier lists and counter pickers.
- **Whether it holds.** On maps no weight was tuned on, with the
  favourite heroes banned, on an older capture of the rates, and with
  the engine run in memory on CounterWatch's 6v6 rates, which are never
  stored.

CounterWatch's raw data stays in a private benchmark repository; only
the study's results are published. Countrix itself still reads Blizzard
and the wiki alone.
