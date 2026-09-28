-- Recording the owner's games is no longer a feature: no map played is
-- entered by hand, nothing judges the playbook against played maps, and
-- nothing learns from them. The strategies are the one input a user
-- writes, and the only rows under the `user` source. The two tables 024
-- added go, with their rows: the picks first, since they reference the
-- matches. pm/backlog.md holds what bringing them back would take.
BEGIN;

DROP TABLE IF EXISTS match_picks;
DROP TABLE IF EXISTS matches;

COMMIT;
