-- THE WRITTEN SYNERGY CELLS: which teammates each hero's article writes a
-- Team Synergy cell for. synergies holds only the pairs an article claims,
-- so a pair it lacks was either written off - rated below GOOD, or saying
-- there is no synergy - or never written at all: a placeholder ("To be
-- added"), an empty cell, or no section. The wiki leaves most pairs
-- unwritten, and the newest heroes' articles are near blank, so reading
-- every pair synergies lacks as zero read "these two do not work
-- together" where the truth was "nobody wrote it down". The facts layer
-- reads each cell no article writes at the share of the written cells that
-- claim (facts/tables.py), and this table, which names the article each
-- written cell is in, is how it tells the two apart.
-- Run pull_synergies after this migration to fill it.
BEGIN;

-- Which teammates each released hero's wiki article writes a Team Synergy
-- cell for, one row per cell (pull_synergies, from the cells synergies is
-- read from): hero_id's article writes a cell about other_id. A written
-- cell is any that is not a placeholder - a claim, a rating below GOOD, an
-- unrated "no synergy" - so a cell with no row is one no article writes,
-- and facts/tables.py reads it at the share of the written cells that
-- claim; a pair with no row either way reads twice that, the written
-- pairs' mean as they read. Reloaded whole with synergies.
CREATE TABLE synergy_cells (
    hero_id   integer NOT NULL REFERENCES heroes(hero_id) ON DELETE CASCADE,
    other_id  integer NOT NULL REFERENCES heroes(hero_id) ON DELETE CASCADE,
    source_id integer NOT NULL REFERENCES sources(source_id),
    cao       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (hero_id, other_id),
    CHECK (hero_id <> other_id)
);

COMMENT ON TABLE synergies IS
    'Which heroes work WITH which. Pulled from the Team Synergy column of the "Match-Ups and Team Synergy" section of every released hero''s wiki article (pull_synergies). A cell is a claim unless it is a placeholder, rated below GOOD or MIRROR, or unrated and saying there is no synergy; a cell rated GOOD or better is a claim with no advice written too. score is 2 when both articles claim the pair, 1 when one does; note is the advice''s first sentence, cut to a clause under 120 characters, or says the rating came with no advice. A pair no article claims has no row: synergy_cells says whether an article wrote it off or neither wrote it at all. No snapshot, region or tier: a judgement has no population behind it. Reloaded whole. Bidirectional, unlike counters. Synergy is a property of the PAIR: if Mei works with Tracer then Tracer works with Mei - one fact, one row. A counter is an arrow: Mei answering Tracer says nothing about the reverse. So each pair is stored once, lower hero_id first (a CHECK holds it), and read from either side.';

COMMIT;
