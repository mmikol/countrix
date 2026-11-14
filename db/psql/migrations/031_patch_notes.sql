-- BLIZZARD'S PATCH NOTES: every line Blizzard's live patch notes write under
-- a hero since the month pull_patch_notes starts from. The wiki writes a
-- patch into its articles some days or weeks after it ships, and a figure it
-- has not caught up on reads as the old one. The facts layer lays a fix over
-- such a figure (facts/patch_notes.py), and each fix cites the line it rests
-- on: a fix whose line this table does not hold is not applied, so every
-- figure that does not come from the wiki comes from Blizzard's own words.
-- Run pull_patch_notes after this migration to fill it.
BEGIN;

-- One row per line Blizzard's live patch notes write under a hero in a
-- balance section (pull_patch_notes): the patch it shipped in, the hero, the
-- piece the line sits under - an ability, a weapon's fire mode or a perk as
-- the notes name it, '' for a line on the hero itself - its place in the
-- hero's entry, and the line as written. A developer comment, a bug fix and
-- a Stadium power are no balance line and have no row. Reloaded whole.
CREATE TABLE patch_notes (
    patch_note_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    patch_id      integer NOT NULL REFERENCES patches(patch_id) ON DELETE CASCADE,
    hero_id       integer NOT NULL REFERENCES heroes(hero_id) ON DELETE CASCADE,
    piece         text NOT NULL,
    position      integer NOT NULL,
    line          text NOT NULL,
    source_id     integer NOT NULL REFERENCES sources(source_id),
    cao           timestamptz NOT NULL DEFAULT now(),
    UNIQUE (patch_id, hero_id, position)
);

CREATE INDEX ix_patch_notes_hero ON patch_notes (hero_id);

COMMIT;
