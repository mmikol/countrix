"""The kit as Blizzard's patch notes leave it where the wiki has not caught
up: FIXES, each citing the lines it rests on, laid over the stored kit
before the 6v6 overlay (kit_format) and derive_scalars read it.

    patch_notes.apply(world)

The wiki writes a patch into its articles days or weeks after it ships, and
a figure it has not written reads as the old one. Each fix names the
figure the wiki holds and the one Blizzard's notes give, and cites the
notes' lines, word for word, under the patch they shipped in. A fix lays
only where its cited lines are among the hero's notes (patch_notes, pulled
from Blizzard's site) and the kit still holds the wiki's figure: once the
wiki writes the patch the figure is gone, the fix lays nothing, and it is
kept on the hero as not applied, which the board warns of and
test_every_patch_fix_still_lays fails on - the session that sees it drops
the fix. A fix's comment says what the wiki holds and what Blizzard's lines
make of it, and any arithmetic the rows need.

Fixes are code, as the kit lists in scalars.py are: no figure here is
stored, and the strategies stay the one input written by hand.
"""

import re
from dataclasses import dataclass

from db import KIND_ABILITY
from facts.kit import KitPiece, Stat
from facts.model import Hero, World
from facts.records import KitFix, KitLine

# how near a stored value must sit to a fix's figure to be it
SAME = 0.01
FIGURE_RE = re.compile(r"\d+(?:\.\d+)?")


def _same(a: float | None, b: float) -> bool:
    return a is not None and abs(a - b) <= SAME


def _pieces(hero: Hero, name: str) -> list[KitPiece]:
    """The pieces a fix names: a weapon config, an ability or a perk, by its
    whole name, or every config of a weapon by the weapon's."""
    return [k for k in (*hero.weapons, *hero.abilities, *hero.perks)
            if name and name in (k.name, k.extra.get("weapon"))]


def _row(code: str, value: float, unit_num: str | None = None, unit_den: str | None = None,
        den_value: float | None = None, condition: str = "", text: str = "") -> Stat:
    """A stat row as the kits pull stores one, built for a reworked piece."""
    return Stat(code=code, value=value, unit_num=unit_num, unit_den=unit_den,
                den_value=den_value, condition=condition, text=text or "%g" % value)


def _short(row: Stat) -> str:
    """A row as the board words a fix: "110 over 4.4 s (over time)", "25/s (zone)"."""
    out = "%g" % (row.value or 0)
    if row.unit_den == "seconds":
        out += "/s" if row.den_value in (None, 1.0) else " over %g s" % row.den_value
    return out + (" (%s)" % row.condition if row.condition else "")


def _copy(row: Stat) -> Stat:
    """A fresh row: a World is built per request, and the load moves rows in place."""
    return Stat(code=row.code, value=row.value, unit_num=row.unit_num, unit_den=row.unit_den,
                den_value=row.den_value, condition=row.condition, text=row.text)


@dataclass(frozen=True, kw_only=True)
class Fix:
    """One figure the wiki has not caught up on: the hero, the patch whose
    notes give it, the lines it cites word for word, and the piece and stat
    it lays on ("" for the hero's pools). `lay` changes the hero's kit and
    says whether it found the wiki's figure to change."""
    hero: str
    patch: str
    # a line as the notes write it, or "<piece>: <line>" where the line
    # alone ("Removed.") would match another piece's
    cites: tuple[str, ...]
    piece: str = ""
    stat: str | None = None
    before: float | None = None
    after: float | None = None

    def lay(self, hero: Hero) -> bool:
        raise NotImplementedError

    def change(self) -> str:
        """What the fix does, worded for the board."""
        return "%s %g -> %g" % ((self.stat or "").replace("_", " "), self.before or 0,
                                self.after or 0)

    def record(self, applied: bool, why: str = "") -> KitFix:
        return KitFix(piece=self.piece, stat=self.stat, before=self.before, after=self.after,
                      patch=self.patch, applied=applied, text=why or " ".join(self.cites),
                      change=self.change())


@dataclass(frozen=True, kw_only=True)
class Move(Fix):
    """A stat the wiki holds at `before` that the notes put at `after`: every
    row of it on the piece at `before`, under `condition` where one is named,
    moves, and its words with it where they hold the figure once."""
    condition: str | None = None

    def lay(self, hero: Hero) -> bool:
        assert self.stat is not None and self.before is not None and self.after is not None
        moved = False
        for piece in _pieces(hero, self.piece):
            for stat in piece.stats.get(self.stat, ()):
                if not _same(stat.value, self.before):
                    continue
                if self.condition is not None and stat.condition != self.condition:
                    continue
                stat.value = self.after
                said = [m for m in FIGURE_RE.finditer(stat.text)
                        if _same(float(m.group()), self.before)]
                if len(said) == 1:
                    found = said[0]
                    stat.text = "%s%g%s" % (
                        stat.text[:found.start()], self.after, stat.text[found.end():])
                moved = True
        return moved


@dataclass(frozen=True, kw_only=True)
class Drop(Fix):
    """Rows of a stat the notes have made stale - a rate figure the patch
    moved, a fire mode it removed - at `values`: they go, and the piece's
    other rows answer for it."""
    values: tuple[float, ...]

    def change(self) -> str:
        return "the stale %s %s dropped" % (
            (self.stat or "").replace("_", " "), ", ".join("%g" % v for v in self.values))

    def lay(self, hero: Hero) -> bool:
        assert self.stat is not None
        dropped = False
        for piece in _pieces(hero, self.piece):
            rows = piece.stats.get(self.stat, [])
            kept = [s for s in rows if not any(_same(s.value, v) for v in self.values)]
            if len(kept) < len(rows):
                piece.stats[self.stat] = kept
                dropped = True
        return dropped


@dataclass(frozen=True, kw_only=True)
class Restate(Fix):
    """A stat row whose words hold `holding` - the wiki's figure, written as
    prose with no value - restated as the notes make it."""
    holding: str
    row: Stat

    def change(self) -> str:
        return "%s %s" % ((self.stat or "").replace("_", " "), _short(self.row))

    def lay(self, hero: Hero) -> bool:
        assert self.stat is not None
        restated = False
        for piece in _pieces(hero, self.piece):
            rows = piece.stats.get(self.stat, [])
            for i, stat in enumerate(rows):
                if self.holding in "%s %s" % (stat.text, stat.condition):
                    rows[i] = _copy(self.row)
                    restated = True
        return restated


@dataclass(frozen=True, kw_only=True)
class Rework(Fix):
    """A piece the notes rework, or add, whose heal the wiki has not written:
    its rows replaced by the notes' and its keywords set. It lays while the
    piece holds no heal row; the wiki's own rows retire it."""
    keywords: str
    rows: tuple[Stat, ...]

    def change(self) -> str:
        return "the notes' rows - %s" % ", ".join(
            "%s %s" % (r.code, _short(r)) for r in self.rows if r.code in ("heal", "damage"))

    def lay(self, hero: Hero) -> bool:
        pieces = [k for k in _pieces(hero, self.piece) if k.kind == KIND_ABILITY]
        if len(pieces) != 1 or pieces[0].stats.get("heal"):
            return False
        piece = pieces[0]
        piece.stats.clear()
        for row in self.rows:
            piece.stats[row.code].append(_copy(row))
        fresh = KitPiece(piece.name, piece.kind, piece.description, self.keywords)
        piece.atoms, piece.keywords = fresh.atoms, fresh.keywords
        return True


@dataclass(frozen=True, kw_only=True)
class Remove(Fix):
    """A piece the notes remove that the wiki's rows still carry."""

    def change(self) -> str:
        return "removed"

    def lay(self, hero: Hero) -> bool:
        kept = [k for k in hero.abilities if k.name != self.piece]
        removed = len(kept) < len(hero.abilities)
        hero.abilities[:] = kept
        return removed


@dataclass(frozen=True, kw_only=True)
class Pool(Fix):
    """A health, armor or shield pool the wiki holds at `before`, 5v5's or,
    with `six`, the 6v6 figure, that the notes put at `after`."""
    six: bool = False

    def change(self) -> str:
        return super().change() + (" in 6v6" if self.six else "")

    def lay(self, hero: Hero) -> bool:
        assert self.stat is not None and self.before is not None and self.after is not None
        if self.six:
            if not _same(hero.six_pools.get(self.stat), self.before):
                return False
            hero.six_pools[self.stat] = int(self.after)
            return True
        if not _same(getattr(hero, self.stat), self.before):
            return False
        setattr(hero, self.stat, int(self.after))
        return True


@dataclass(frozen=True, kw_only=True)
class SixFrom(Fix):
    """A 6v6 line written against a 5v5 figure the notes have since moved in
    5v5 alone: it reads from the new 5v5 figure, so 6v6 keeps its own."""

    def change(self) -> str:
        return "the 6v6 %s line reads from %g" % ((self.stat or "").replace("_", " "),
                                                  self.after or 0)

    def lay(self, hero: Hero) -> bool:
        assert self.before is not None and self.after is not None
        for i, line in enumerate(hero.six_lines):
            if (line.piece == self.piece and line.stat == self.stat
                    and _same(line.before, self.before)):
                hero.six_lines[i] = line._replace(before=self.after)
                return True
        return False


@dataclass(frozen=True, kw_only=True)
class SixLine(Fix):
    """A 6v6 figure the notes give that the wiki's 6v6 lines lack."""
    text: str

    def change(self) -> str:
        return "%s %g in 6v6" % ((self.stat or "").replace("_", " "), self.after or 0)

    def lay(self, hero: Hero) -> bool:
        if any(line.piece == self.piece and line.stat == self.stat for line in hero.six_lines):
            return False
        hero.six_lines.append(KitLine(
            piece=self.piece, stat=self.stat, before=self.before, after=self.after,
            text=self.text))
        return True


# --- the fixes -------------------------------------------------------------
# Each read against the notes since August 2026 and the wiki's articles of
# 2026-11-14, every numeric balance line checked against the row it moves.
# Lines the wiki has caught up on, and lines no stored row holds (cast and
# recovery times, hit volumes, perk percentages the kit keeps no row for),
# have no fix.

OCT6 = "October 6, 2026 Patch"
OCT13 = "October 13, 2026 Patch"
NOV3 = "November 3, 2026 Patch"
SEP8 = "September 8, 2026 Patch"
SEP17 = "September 17, 2026 Patch"
AUG11 = "August 11, 2026 Patch"

FIXES: tuple[Fix, ...] = (
    # Sombra's rework into a support. The wiki's Hotfix block still holds
    # Hack's rows - a 1 s ability disable, a 45 s hacked health pack, the
    # hacked keyword the crowd control reads - and no heal. The notes: 65 at
    # once, then 25 a second until 175 in all, so 110 over 4.4 s, written as
    # a total over its time as the wiki writes Regenerative Burst's; 2
    # charges, 8 s, 17 m; it lasts 12 s at most, 10 s since November 3.
    Rework(hero="Sombra", patch=OCT6, piece="Hotfix", cites=(
        "Hotfixing an ally heals them for 65 instant health and 25 health per second over"
        " its duration.",
        "Hotfix lasts on an ally until either 175 total healing is done or until 12 seconds"
        " have passed.",
        "Hacked health pack duration decreased from 45 seconds to 30 seconds.",
        "Cast time is 0.5 seconds.", "Range is 17 meters.", "Has 2 charges.",
        "Cooldown is 8 seconds."),
        keywords="", rows=(
            _row("cooldown", 8, "seconds", text="8 seconds"),
            _row("charges", 2, "charges"),
            _row("range", 17, "meters", text="17 meters"),
            _row("cast_time", 0.5, "seconds", text="0.5 seconds"),
            _row("heal", 65, "hp", condition="instant", text="65"),
            _row("heal", 110, "hp", "seconds", 4.4, condition="over time",
                 text="25 per second, until 175 in all"),
            _row("duration", 12, "seconds", condition="over time", text="12 seconds max"),
            _row("duration", 30, "seconds", condition="health packs", text="30 seconds"))),
    Move(hero="Sombra", patch=NOV3, piece="Hotfix", stat="duration", before=12, after=10,
        cites=("Duration reduced from 12 to 10 seconds.",)),
    # Cyberspace has no block on the wiki. The notes: a projectile whose
    # explosion heals allies 40 and deals 20 (40 until October 13), then a
    # 5 m zone for 3 s, 30 healing and 25 damage a second; 13 s since
    # October 13. Its zone's heal is written as 90 over the 3 s, as above.
    # Its weaken - the enemy's own damage and healing cut 40% - has no stat
    # the kit reads.
    Rework(hero="Sombra", patch=OCT6, piece="Cyberspace", cites=(
        "Launch a projectile that explodes on impact, creating a zone that weakens enemies"
        " and heals allies.",
        "Initial explosion deals 40 damage to enemies and 40 healing to allies.",
        "Zone deals 25 damage per second to enemies and 30 healing per second to allies.",
        "Zone duration is 3 seconds.", "Zone radius is 5 meters."),
        keywords="area of effect;;spherical::travel time", rows=(
            _row("cooldown", 12, "seconds", text="12 seconds"),
            _row("damage", 40, "hp", condition="explosion", text="40"),
            _row("damage", 25, "hp", "seconds", 1, condition="zone", text="25 per second"),
            _row("heal", 40, "hp", condition="explosion", text="40"),
            _row("heal", 90, "hp", "seconds", 3, condition="zone",
                 text="30 per second for 3 seconds"),
            _row("duration", 3, "seconds", condition="zone", text="3 seconds"),
            _row("radius", 5, "meters", condition="zone", text="5 meters"))),
    Move(hero="Sombra", patch=OCT13, piece="Cyberspace", stat="damage", before=40, after=20,
        condition="explosion", cites=("Explosion damage reduced from 40 to 20.",)),
    Move(hero="Sombra", patch=OCT13, piece="Cyberspace", stat="cooldown", before=12, after=13,
        cites=("Cooldown increased from 12 to 13 seconds.",)),
    Remove(hero="Sombra", patch=OCT6, piece="Virus", cites=("Virus: Removed.",)),
    # The Machine Pistol's dps field reads 140 while firing, 114.3 with the
    # reload: 7 a shot, before October 13. Its rows hold 6.5 at 20 a second,
    # 60 rounds and a 1.2 s reload: 130, and 92.86 with the reload.
    Drop(hero="Sombra", patch=OCT13, piece="Machine Pistol", stat="dps", values=(140,),
        cites=("Damage reduced from 7 to 6.5.",)),
    # The Scrap Gun's dps field, 203.13 and 154.76 with the reload, is the
    # volley before October 13's center projectile. Its rows: 216 a volley at
    # 1.25 volleys a second, 6 volleys a magazine, 1.75 s to reload - 270,
    # and 197.86 with the reload.
    Drop(hero="Roadhog", patch=OCT13, piece="Scrap Gun", stat="dps", values=(203.13,),
        cites=("Center projectile damage increased from 34 to 40.",)),
    # Trash Compactor's block carries the removed secondary fire's 24 - 39 m
    # post-detonation falloff, which read as Roadhog's reach. The notes give
    # it an explosion of 2 to 6 m and no falloff range.
    Drop(hero="Roadhog", patch=OCT6, piece="Trash Compactor", stat="damage_falloff_range",
        values=(24, 39), cites=(
            "Scrap Gun \u2013 Secondary Fire: Removed.",
            "Explosion inner radius of 2 meters, explosion outer radius of 6 meters with a 30%"
            " falloff scalar.")),
    SixLine(hero="Roadhog", patch=OCT6, piece="Trash Compactor", stat="cooldown", before=10,
            after=11, text="Cooldown is 11 seconds in 6v6",
            cites=("Cooldown is 10 seconds in 5v5.", "Cooldown is 11 seconds in 6v6.")),
    # The Solar Rifle's dps field reads 77.7 while firing at full charge, 68
    # with the reload, from before the 0.575 s charge. Its rows: 75 a shot at
    # 1.21 a second - 90.75 - and 14 shots before a 1.5 s reload, so 11.57 s
    # of fire in 13.07: 80.33. The rate cannot read it off the rows, whose
    # fastest fire rate is the uncharged shot's.
    Restate(hero="Illari", patch=NOV3, piece="Solar Rifle", stat="dps", holding="77.7",
            row=_row("dps", 90.75, "hp", "seconds", 1, condition="80.33 overall w/ reload",
                     text="(max charge): 90.75 while firing"),
            cites=("Time to maximum charge reduced from 0.65 to 0.575.",)),
    # The crossbow's dps field, 165 and 103.92 with the reload, is 30 a bolt.
    # Its rows: 28 at 5.5 a second, 15 bolts, 1.6 s - 154, and 97.06.
    Drop(hero="Freja", patch=SEP8, piece="Revdraw Crossbow", stat="dps", values=(165,),
        cites=("Damage reduced from 30 to 28.",)),
    # Dragonblade's dps field, 158.05, is 110 a swing at the old speed. Its
    # rows: 100 a swing at 1.65 a second.
    Drop(hero="Genji", patch=OCT6, piece="Dragonblade", stat="dps", values=(158.05,),
        cites=("Damage reduced from 110 to 100.", "Swing speed increased by 15%.")),
    Pool(hero="Junker Queen", patch=NOV3, stat="health", before=375, after=425,
        cites=("Base health increased from 375 to 425.",)),
    Pool(hero="Junker Queen", patch=NOV3, stat="health", before=450, after=500, six=True,
        cites=("Base health increased from 450 to 500. (6v6)",)),
    Pool(hero="Mauga", patch=NOV3, stat="armor", before=125, after=150,
        cites=("Base armor increased from 125 to 150.",)),
    Move(hero="Mauga", patch=AUG11, piece="Combat Fuel", stat="overhealth", before=3, after=4,
        cites=("Overhealth gained per shot increased from 3 to 4.",)),
    Pool(hero="D.Va", patch=SEP8, stat="health", before=175, after=200,
        cites=("Mech base health increased from 175 to 200. (5v5)",)),
    Move(hero="D.Mon", patch=SEP17, piece="Fusion Repeater", stat="damage", before=16,
        after=15, cites=("Damage reduced from 16 to 15.",)),
    Move(hero="D.Mon", patch=SEP17, piece="Fusion Repeater", stat="cooldown", before=4,
        after=5, cites=("Cooldown increased from 4 to 5 seconds.",)),
    Move(hero="D.Mon", patch=SEP17, piece="Propulsors", stat="energy", before=25, after=30,
        condition="energy cost", cites=("Fuel drain rate increased from 25 to 30.",)),
    Move(hero="D.Mon", patch=SEP17, piece="Focused Fusion", stat="damage", before=45,
        after=36, condition="with perk", cites=("Damage per bullet reduced from 45 to 36.",)),
    Move(hero="Kiriko", patch=SEP8, piece="Healing Ofuda", stat="range", before=35, after=30,
        condition="lock on", cites=("Maximum seeking range reduced from 35 to 30 meters.",)),
    Move(hero="Doctrine", patch=OCT6, piece="Deliverance", stat="duration", before=5, after=4,
        condition="overhealth & debuff decay",
        cites=("Decay duration reduced from 5 to 4 seconds.",)),
    # The 6v6 lines were written against the 5v5 cooldowns before September
    # 8 moved them in 5v5 alone: 6v6 keeps 13 s and 10 s.
    SixFrom(hero="Winston", patch=SEP8, piece="Barrier Projector", stat="cooldown", before=12,
            after=10, cites=("Cooldown reduced from 12 to 10 seconds. (5v5)",)),
    SixFrom(hero="Zarya", patch=SEP8, piece="Particle Barrier", stat="cooldown", before=11,
            after=12, cites=("Cooldown increased from 11 to 12 seconds. (5v5)",)),
)


def apply(w: World, fixes: tuple[Fix, ...] = FIXES) -> None:
    """Lay every fix whose cited lines are among its hero's notes, in order,
    keeping on each hero what each did (Hero.kit_fixes)."""
    by_name = {h.name: h for h in w.heroes.values()}
    for each in w.heroes.values():
        each.kit_fixes = []
    for fix in fixes:
        hero = by_name.get(fix.hero)
        if hero is None:
            continue
        said = [n for n in hero.notes if n.patch == fix.patch]
        noted = {n.line for n in said} | {"%s: %s" % (n.piece, n.line) for n in said}
        unnoted = [line for line in fix.cites if line not in noted]
        if unnoted:
            hero.kit_fixes.append(fix.record(
                False, "the %s notes hold no line %r" % (fix.patch, unnoted[0])))
            continue
        laid = fix.lay(hero)
        hero.kit_fixes.append(fix.record(laid, "" if laid else "the wiki has caught up"))
