-- THE DATA NOTHING READS: three tables and a column the pulls wrote and no
-- metric, playbook rule or page read.
--
-- seasons and meta_snapshots.season_id: a season's name only labelled the
-- meta.snapshot fact. The patch a snapshot links to dates its rates, and
-- the refresher pulls the patch list daily in the seasons' place.
-- ability_modifiers: the buff stats re-read as what each scales and whom
-- it lands on. The metrics read the same figures from ability_stats.
-- perk_ability_effects: the abilities a perk's text names. The hero.perk
-- fact prints that text whole.
--
-- The pulls stop writing them in the same change. The column goes before
-- the table it references.
BEGIN;

ALTER TABLE meta_snapshots DROP COLUMN IF EXISTS season_id;
DROP TABLE IF EXISTS seasons;
DROP TABLE IF EXISTS ability_modifiers;
DROP TABLE IF EXISTS perk_ability_effects;

COMMIT;
