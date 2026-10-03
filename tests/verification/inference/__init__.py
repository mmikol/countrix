"""The inference layer's tests, the reference playbook they prove the solver against and
its default engine weights (DEFAULT, its meta.md), its
assumptions alone (ASSUMPTIONS_ONLY) for a test that needs a playbook that scores nothing,
the shipped healing floor's fields (HEAL_RATE) and heal_rate(), a playbook of that rule
alone written where a test says, and two more written the same way - support_limit(),
at most three supports, which SUPPORTS breaks, and hazard_playbook(), the rules Ember
Ruins' Forge turns on - so no solver test reads inference/strategies/, the
recorded fixture, read with the objective it was recorded under and compared with the
one in force, evaluated(), a full six scored as the board scores its current comp, and
timeless(), a board's payload less the seconds each result took, for comparing two
solves, and six() and seated(), a recorded reach board solved afresh. Beside the tests:

    conftest.py      the folder's fixtures: a scratch playbook and the Harbor Gate board
    enumeration.py   the answers the search is held to, found without it, and the seats
                     it is compared on
    prove_exact.py   the hand-run proofs on the built database
    record_reach.py  the recorder of tests/fixtures/reach.json
"""

import dataclasses
import json
import os
import re
from typing import Any, TypedDict

import pytest

from db import ROOT
from facts.draft import Draft
from facts.model import World
from inference import base, catalog, engine, reach
from inference.result import Result
from inference.solver import Infeasible, Unbounded
from inference.strategy import Strategy

FIXTURES = os.path.join(ROOT, "tests", "fixtures")
# the former shipped playbook - every kind and every form - kept as the reference the
# solver's behaviours are proven against; the live playbook is the user's own
FIXTURE_PLAYBOOK = os.path.join(FIXTURES, "playbook")
# the reference playbook's four assumptions (locked-picks, objective, optimal-play,
# vintage): a playbook that scores nothing and writes no limit. A board's weights
# reach heuristics alone, so the shared list is never weighted in place
ASSUMPTIONS_ONLY = [s for s in catalog.load(FIXTURE_PLAYBOOK) if s.kind == "assumption"]
# the reference playbook's meta.md: the default engine at the weights it was calibrated
# at, which every test that runs the engine names, so none reads the live meta.md the
# owner tunes
DEFAULT = catalog.engine_weights(FIXTURE_PLAYBOOK)
# a board's brief at those weights, blue's swaps and the plan stage by stage left
# out: a test that reads them names its swap cost (test_swaps, test_stage_plan), so
# none reads the live meta.md's, and no other board pays for a stage's search
BRIEF = engine.Brief(base=DEFAULT, search_swaps=False, walk_stages=False)
DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
# the frontmatter of inference/strategies/heal-rate.md, which test_catalog holds
# the shipped file to
HEAL_RATE = {
    "kind": "heuristic", "category": "sustain", "weight": 2.0,
    "penalty": "matchup.heal_shortfall"}


def heal_rate(directory: str) -> list[Strategy]:
    """The shipped healing floor as a playbook of its own, in `directory`: a
    file with HEAL_RATE's fields, read back through the catalog."""
    fields = "".join("%s: %s\n" % (k, v) for k, v in HEAL_RATE.items())
    with open(os.path.join(directory, "heal-rate.md"), "w", encoding="utf-8") as handle:
        handle.write("---\nname: Heal at the other side's rate\n%s---\n# Heal at the other"
                     " side's rate\n\nThe healing floor.\n" % fields)
    return catalog.load(directory)


# four supports: one past the limit support_limit() writes
SUPPORTS = ("Balm", "Myrrh", "Sorrel", "Tansy")


def support_limit(directory: str | os.PathLike[str]) -> list[Strategy]:
    """A playbook of one limit, at most three supports, written in `directory`
    on a dial, as the shipped rule writes it."""
    with open(os.path.join(directory, "three-supports.md"), "w", encoding="utf-8") as handle:
        handle.write("---\nname: At most three supports\nkind: constraint\n"
                     "require: team.supports <= params.MAX_SUPPORTS\nparams:\n"
                     "    MAX_SUPPORTS: 3\n---\n# At most three supports\n\n"
                     "A six fields at most three supports.\n")
    return catalog.load(str(directory))


# a board that reads the terrain: a rule and a limit Forge's hazards turn on
HAZARD_RULES = {
    "hazard-cc": "---\nname: Hazards reward crowd control\nkind: heuristic\n"
                 "metric: team.cc_count\ndirection: maximize\nweight: 1\n"
                 "when: map.hazards >= 1.5\n---\nPush them off.\n",
    "hazard-needs-cc": "---\nname: Hazards need crowd control\nkind: constraint\n"
                       "require: team.cc_count >= 1 or map.hazards < 1.5\n---\nAlways.\n"}


def hazard_playbook(world: World, directory: str | os.PathLike[str]) -> list[Strategy]:
    """The reference playbook's assumptions and HAZARD_RULES, and Ember
    Ruins' Forge stage whose text raises its hazards past the map's."""
    for sid, text in HAZARD_RULES.items():
        with open(os.path.join(directory, "%s.md" % sid), "w", encoding="utf-8") as handle:
            handle.write(text)
    world.map("Ember Ruins").stage_z["Forge"]["hazards"] = 2.5
    return [*ASSUMPTIONS_ONLY, *catalog.load(str(directory))]


class Recorded(TypedDict):
    """A recorded fixture: the objective it was recorded under - the playbook's
    digest (catalog.playbook_digest) and the default engine's stamp
    (base.stamp, None with the engine off) - and its boards as the recorder
    wrote them."""
    playbook: str
    base: dict[str, float | str] | None
    boards: list[dict[str, Any]]


def recorded(name: str) -> Recorded:
    """tests/fixtures/<name>.json. A fixture that names no playbook or no
    engine, or holds no boards, fails the test that reads it."""
    with open(os.path.join(FIXTURES, "%s.json" % name), encoding="utf-8") as handle:
        fixture = json.load(handle)
    if not (isinstance(fixture, dict) and isinstance(fixture.get("playbook"), str)
            and DIGEST_RE.match(fixture["playbook"])):
        pytest.fail("tests/fixtures/%s.json names no playbook digest: re-record it" % name)
    if "base" not in fixture:
        pytest.fail("tests/fixtures/%s.json names no default engine: re-record it" % name)
    if not fixture.get("boards"):
        pytest.fail("tests/fixtures/%s.json records no boards" % name)
    return Recorded(playbook=fixture["playbook"], base=fixture["base"], boards=fixture["boards"])


def in_force() -> tuple[str, base.BaseStamp | None]:
    """The objective a board is solved under by default: the playbook in
    force's digest and the stamp of its meta.md's weights, as a fixture
    records them."""
    return catalog.playbook_digest(), base.stamp(catalog.engine_weights())


def evaluated(
        world: World, draft: Draft, *, catalog: list[Strategy],
        base: base.BaseWeights = DEFAULT) -> Result:
    """Blue's full six (`draft.blue`) scored and ranked against every legal
    six, as the board scores its current comp - through blue's optimal's
    search - without the board's other seats."""
    optimal = engine._optimal(world, dataclasses.replace(draft, blue=()), catalog=catalog,
                              base=base, top=engine.BOARD_TOP, seat="blue", kind="infer")
    return engine._evaluated(world, draft, catalog=catalog, base=base, seat="blue",
                             kind="evaluate", optimal=optimal)


def timeless(payload: dict[str, Any]) -> dict[str, Any]:
    """A board's payload (its to_dict(), or the JSON a server sent) less the
    seconds each result took: 'seconds' popped from every dict value holding
    one. The payload is changed in place and returned."""
    for value in payload.values():
        if isinstance(value, dict) and "seconds" in value:
            value.pop("seconds")
    return payload


def six(world: World, board: reach.Reach) -> list[str]:
    """The optimal six of a board a reach search recorded, solved afresh; none
    on a board the playbook's limits no longer fit."""
    try:
        top = engine.infer(world, Draft(map_name=board["map"], red=tuple(board["red"]),
                                        bans=tuple(board["banned"]), side=board["side"]), top=1)
    except (Infeasible, Unbounded):
        return []
    return top.blue


def seated(world: World, board: reach.Reach) -> bool:
    """Is the hero still in the optimal six of the board a search recorded for
    it? A board the playbook's limits no longer fit has fallen: it seats no one."""
    return board["hero"] in six(world, board)
