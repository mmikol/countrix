-- THE STAGE TERRAIN'S WORDS: how much text each stage was counted in. A
-- stage's text runs from 20 words to a few hundred, so its rate of mentions
-- swings on one mention where the text is short. The facts layer weighs the
-- stage's rate against its map's by the text's length (facts/tables.py), and
-- per_thousand cannot give the length back: a stage whose text names no
-- feature holds zeros. pull_terrain now also reads more of each article's
-- text about a stage - a paragraph that names several stages a sentence at
-- a time - and each stage's field in the released heroes' map-strategy
-- tables. The rows stored before this migration hold 0 words, and a stage of
-- 0 words reads as its map until pull_terrain runs again.
-- Run pull_terrain after this migration.
BEGIN;

ALTER TABLE stage_terrain
    ADD COLUMN words integer NOT NULL DEFAULT 0 CHECK (words >= 0);
ALTER TABLE stage_terrain ALTER COLUMN words DROP DEFAULT;

COMMENT ON TABLE stage_terrain IS
    'A stage''s terrain, counted with map_terrain''s features and patterns in the text the wiki has about the stage (pull_terrain). A stage''s text: in the map''s article, every kept section under a heading that names the stage, every paragraph or list item elsewhere that names it and no other stage, and of a paragraph that names several, each sentence that names it alone - a name of two words or more matched in any case, a one-word name as written; then the stage''s field in each released hero''s map-strategy table (the wiki''s MapStrategyTable template), matched by its map and stage keys. A Hybrid phase''s text: every Assault or Escort section, attack and defense together; where the article names the route''s stretches, the first is the capture point''s and the rest the payload''s. A stage with 20 words of text or more holds all eight rows, zeros included, each with the text''s words; a stage with less holds none. Reloaded whole with map_terrain.';
COMMENT ON COLUMN stage_terrain.per_thousand IS
    'mentions per thousand words of the stage''s text. A stage''s text is short, so one mention moves this far: the facts layer weighs it against the map''s rate by words.';
COMMENT ON COLUMN stage_terrain.words IS
    'The words of the stage''s text, the same on its eight rows; 0 on a row stored before the column was, which reads as the map.';

COMMIT;
