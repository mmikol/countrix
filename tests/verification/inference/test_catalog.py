"""The catalog: what a strategy file may be named, how the playbook in force
is chosen, how the catalog reads as text, the files a playbook reads and
fingerprints, the frontmatter and the forms a strategy takes, and the
weights one board overrides."""

import os
import re
import shutil
from collections.abc import Iterable
from pathlib import Path

import pytest

from db import Refusal
from facts import compute
from inference import catalog, tune
from inference.frontmatter import Parsed, parse_frontmatter
from inference.shapes import legal_shapes
from inference.strategy import KINDS, CatalogError, Strategy, settled_by_board
from tests.verification.inference import FIXTURE_PLAYBOOK, HEAL_RATE


def _fights(strategies: Iterable[Strategy]) -> list[str]:
    """Each unguarded heuristic against every heuristic that weighs its metric
    the other way, worded for the failure. A scored heuristic weighs no
    metric, so it fights nothing here."""
    by_metric = {}
    for strategy in strategies:
        if strategy.form == "heuristic":
            by_metric.setdefault(strategy.metric, []).append(strategy)
    fights = []
    for metric, group in sorted(by_metric.items()):
        for one in group:
            if one.when is not None:
                continue                      # a guarded pair is a situation, not a fight
            for other in group:
                if other.direction != one.direction:
                    fights.append("%s: %s (always, %s) opposes %s (%s)"
                                  % (metric, one.id, one.direction, other.id, other.direction))
    return fights


def test_no_ungated_heuristic_opposes_a_gated_one_on_its_metric():
    """A heuristic with no `when` reads on every board, so one that maximises a
    metric another minimises under a guard fights that guard wherever it holds:
    weight is spent on both sides and the board cannot say which it answered.
    Opposed pairs are fine - they must both be guarded, into different
    situations."""
    fights = _fights(catalog.load(FIXTURE_PLAYBOOK))
    assert not fights, fights


@pytest.mark.parametrize("when, fights", [
    ("", ["team.exposed_count: always-exposed (always, maximize) opposes exposure (minimize)"]),
    ("when: enemy.size >= 1\n", []),
], ids=["always", "guarded"])
def test_a_heuristic_fights_a_guarded_one_it_opposes_unless_it_is_guarded_too(
        catalog_copy, when, fights):
    """The guard can fail: beside the reference's exposure, which minimises
    team.exposed_count once red has a pick, a heuristic that maximises it on
    every board is a fight, and the same heuristic under a guard is not."""
    Path(catalog_copy, "always-exposed.md").write_text(
        "---\nname: Walk into every counter\nkind: heuristic\ncategory: matchup\n"
        "direction: maximize\nmetric: team.exposed_count\nweight: 1\n%s---\n"
        "Stand where the revealed enemies answer the most picks.\n" % when,
        encoding="utf-8")
    assert _fights(catalog.load(catalog_copy)) == fights


def test_a_filename_that_is_not_lowercase_kebab_is_refused_before_the_folder_counts(tmp_path):
    """The id is the filename, so the id rule runs on every file before the
    empty-folder check: a folder holding only a badly named file is refused
    for its name."""
    (tmp_path / "Bad_Name.md").write_text("---\nname: x\nkind: assumption\n---\nx\n",
                                          encoding="utf-8")
    with pytest.raises(CatalogError, match="lowercase-kebab"):
        catalog.load(str(tmp_path))


def test_the_docs_word_every_form_the_reference_playbook_holds(tmp_path, monkeypatch):
    """write_docs words a limit, two scored heuristics - a charge for a rule
    broken and a charge that grows - and a heuristic on a metric under their
    headings, and drops each file's title line - the heading names it."""
    monkeypatch.delenv("COUNTRIX_STRATEGIES", raising=False)
    path = tmp_path / "inference.md"
    path.write_text("# The doc\n\n<!-- generated:catalog -->\n<!-- /generated:catalog -->\n",
                    encoding="utf-8")
    assert catalog.write_docs(catalog.load(FIXTURE_PLAYBOOK), path=str(path)) == str(path)
    text = path.read_text(encoding="utf-8")
    assert "##### At most two tanks (`open-queue-tanks`, shape, limit)\n\n" \
        "`require team.tanks <= 2` - always holds\n" in text
    assert "weight 1; when `enemy.flyers >= 1 and not (team.hitscan >= 1)`; penalty `2.5`" in text
    assert "weight 1; penalty `max(0, team.squish_count - 4) * 1.0`" in text
    assert "1 constraint (a limit), 14 heuristics (8 on a metric, 6 scored)" in text
    assert "`maximize team.pool_total` - " in text and "\n# At most two tanks" not in text


def test_the_rendered_catalog_is_one_line_per_strategy_led_by_its_kind():
    playbook = catalog.load(FIXTURE_PLAYBOOK)
    lines = catalog.catalog_rendered(playbook).split("\n")
    assert len(lines) == len(playbook)
    for line, strategy in zip(lines, playbook, strict=True):
        assert line.startswith(strategy.kind) and strategy.id in line


def test_a_file_named_for_another_id_cannot_hijack_it(catalog_copy):
    Path(catalog_copy, "aaa.md").write_text(
        "---\nname: x\nkind: assumption\nid: coverage\n---\nx\n",
        encoding="utf-8")
    with pytest.raises(CatalogError) as caught:
        catalog.load(catalog_copy)
    assert str(caught.value).startswith("aaa.md: ") and "id: is the filename" in str(caught.value)


def test_another_playbook_is_chosen_by_the_environment(monkeypatch, tmp_path):
    """COUNTRIX_STRATEGIES names another folder of strategy files; the
    shipped playbook is the default, and the docs are written from it alone."""
    monkeypatch.delenv("COUNTRIX_STRATEGIES", raising=False)
    assert catalog.strategies_dir() == catalog.SHIPPED_DIR
    other = tmp_path / "other"                      # one rule, copied from the playbook
    other.mkdir()
    shutil.copy(os.path.join(FIXTURE_PLAYBOOK, "open-queue-tanks.md"), other)
    monkeypatch.setenv("COUNTRIX_STRATEGIES", str(other))
    chosen = catalog.strategies_dir()
    assert chosen == str(other)
    one = catalog.load(chosen)
    assert {h.id for h in one} == {"open-queue-tanks"}
    assert catalog.write_docs(one, path=str(tmp_path / "never.md")) is None
    assert not (tmp_path / "never.md").exists()


def test_a_playbooks_digest_reads_its_strategy_files_and_nothing_beside_them(catalog_copy):
    """A recorded fixture holds the digest of the playbook it was recorded under.
    The tuning log, the README and anything that is not markdown never move
    it; a line added to one strategy file does."""
    digest = catalog.playbook_digest(catalog_copy)
    assert digest == catalog.playbook_digest(FIXTURE_PLAYBOOK)
    for name in ("tuning-log.md", "README.md", "notes.txt"):
        Path(catalog_copy, name).write_text("# beside the playbook\n", encoding="utf-8")
    assert catalog.strategy_files(catalog_copy) == catalog.strategy_files(FIXTURE_PLAYBOOK)
    assert catalog.playbook_digest(catalog_copy) == digest
    with Path(catalog_copy, "cohesion.md").open("a", encoding="utf-8") as handle:
        handle.write("One more line.\n")
    assert catalog.playbook_digest(catalog_copy) != digest


def test_a_folder_that_is_not_there_holds_no_playbook(tmp_path):
    with pytest.raises(CatalogError, match="no strategies directory"):
        catalog.strategy_files(str(tmp_path / "gone"))
    with pytest.raises(CatalogError, match="no strategies directory"):
        catalog.playbook_digest(str(tmp_path / "gone"))


def test_frontmatter_parses_scalars_and_params():
    """true, false and null are the dialect's only words: No, yes, ~ and a
    bracketed value stay the text they are, so a strategy named No keeps
    its name."""
    meta, body = parse_frontmatter(
        "---\nname: No\nweight: 2.5\nsoft: true\nhard: false\nn: -4\nf: 1e3\nw: word\n"
        "z: null\nyes: yes\nt: ~\ntags: [a, b]\nparams:\n  K: 3\n---\n# X\nbody\n")
    assert meta == {"name": "No", "weight": 2.5, "soft": True, "hard": False, "n": -4,
                    "f": 1000.0, "w": "word", "z": None, "yes": "yes", "t": "~",
                    "tags": "[a, b]", "params": {"K": 3}}
    assert type(meta["n"]) is int and type(meta["f"]) is float
    assert body == "# X\nbody"
    parsed = parse_frontmatter("---\nname: Y\n---\nprose\n")
    assert isinstance(parsed, Parsed) and (parsed.meta, parsed.body) == ({"name": "Y"}, "prose")


def test_the_reference_and_the_live_playbooks_are_valid_and_reference_real_metrics():
    live = catalog.load()                       # the user's playbook: whatever it holds today
    assert live and {h.kind for h in live} <= set(KINDS)
    assert all(h.metric in compute.registry() for h in live if h.form == "heuristic")
    for h in live:                              # each file keeps to the add tool's limit
        assert tune.sentence_count(h.body) <= tune.MAX_SENTENCES, h.id
    cat = catalog.load(FIXTURE_PLAYBOOK)        # the reference: every kind and every form
    kinds = {h.kind for h in cat}
    assert kinds == set(KINDS) == {"constraint", "heuristic", "assumption"}
    forms = {h.form for h in cat}
    assert forms == {"limit", "scored", "heuristic", "assumption"}
    assert {h.form for h in cat if h.kind == "heuristic"} == {"heuristic", "scored"}
    assert {h.form for h in cat if h.kind == "constraint"} == {"limit"}
    assert all(h.form == "assumption" for h in cat if h.kind == "assumption")
    assert {h.id for h in cat if h.kind == "assumption"} >= {"optimal-play", "vintage", "objective"}
    registry = compute.registry()
    for h in cat:
        if h.form == "heuristic":
            assert h.metric in registry and h.metric not in compute.TEXT_METRICS
        for e in (h.when, h.require, h.bonus, h.penalty):
            for name in (e.names if e else []):
                assert name in registry or name[7:] in h.params, (h.id, name)
    assert any(h.id == "open-queue-tanks" for h in cat)


def test_the_shipped_healing_floor_is_a_scored_heuristic_at_weight_two():
    """inference/strategies/heal-rate.md, the shipped playbook's healing
    heuristic: weighted, so a heuristic, and scored - it charges its weight
    times matchup.heal_shortfall on every board, unguarded, and it is the
    one rule that reads the shortfall. HEAL_RATE holds the same fields, so
    the solver tests that stand it in for the file prove this rule."""
    shipped = catalog.load(catalog.SHIPPED_DIR)
    heal = next(h for h in shipped if h.id == "heal-rate")
    assert (heal.kind, heal.form, heal.category, heal.weight) == (
        "heuristic", "scored", "sustain", 2.0)
    assert heal.penalty is not None and heal.penalty.source == "matchup.heal_shortfall"
    assert heal.when is None and heal.bonus is None and heal.require is None
    assert {k: heal.to_dict()[k] for k in HEAL_RATE} == HEAL_RATE
    def reads(h):
        sources = [e.source for e in (h.when, h.bonus, h.penalty, h.require) if e is not None]
        return " ".join([*sources, h.metric or ""])
    assert [h.id for h in shipped if "matchup.heal_shortfall" in reads(h)] == ["heal-rate"]


def test_the_shipped_limits_hold_one_to_three_supports_and_a_tank():
    """inference/strategies/at-most-three-supports.md, the owner's limit: a
    require on the Support role's count with three as its dial, never
    weighted - a shape limit, so no legal shape seats a fourth support and
    the roster refuses one. Beside it the research's two floors,
    six-fields-a-support and six-fields-a-tank, leave no legal shape
    without a support or a tank."""
    shipped = catalog.load(catalog.SHIPPED_DIR)
    limit = next(s for s in shipped if s.id == "at-most-three-supports")
    assert (limit.kind, limit.form, limit.category, limit.weighs) == (
        "constraint", "limit", "shape", False)
    assert limit.require is not None
    assert limit.require.source == "team.supports <= params.MAX_SUPPORTS"
    assert limit.params == {"MAX_SUPPORTS": 3}
    assert sorted(s.id for s in shipped if s.form == "limit") == [
        "at-most-three-supports", "six-fields-a-support", "six-fields-a-tank"]
    shapes = legal_shapes(shipped)
    assert max(shape.supports for shape in shapes) == 3
    assert min(shape.supports for shape in shapes) == 1
    assert min(shape.tanks for shape in shapes) == 1


def test_catalog_rejects_a_goal_on_an_unknown_metric(tmp_path):
    (tmp_path / "bad.md").write_text(
        "---\nname: bad\nkind: heuristic\ndirection: maximize\nmetric: team.nope\n---\nx\n",
        "utf-8")
    with pytest.raises(CatalogError, match="not a registered fact key"):
        catalog.load(str(tmp_path))
    (tmp_path / "bad.md").write_text(
        "---\nname: bad\nkind: heuristic\nwhen: team.tanks > params.T\nbonus: 1\n---\nx\n",
        "utf-8")
    with pytest.raises(CatalogError, match="params"):
        catalog.load(str(tmp_path))


def test_a_constraint_is_a_limit_a_heuristic_weighs_and_an_assumption_is_prose(tmp_path):
    """Constraints cut the space, heuristics weigh what is left: a constraint
    is a require and nothing weighted, a heuristic weighs a metric or bonus
    less penalty - a flat penalty included, the charge for a rule broken -
    and never both, and soft: is refused wherever it stands."""
    def load_one(text):
        (tmp_path / "x.md").write_text(text, encoding="utf-8")
        return catalog.load(str(tmp_path))[0]
    limit = load_one("---\nname: l\nkind: constraint\nrequire: team.tanks <= 2\n---\nx\n")
    assert limit.form == "limit" and not limit.weighs
    assert load_one("---\nname: s\nkind: heuristic\nbonus: team.tanks\n---\nx\n").form == "scored"
    charge = load_one("---\nname: c\nkind: heuristic\nwhen: not (team.tanks <= 1)\n"
                      "penalty: 2\n---\nx\n")
    assert charge.form == "scored" and charge.weighs and not charge.need
    assert load_one("---\nname: p\nkind: assumption\n---\nx\n").form == "assumption"
    # awaiting /strategy
    assert load_one("---\nname: d\nkind: constraint\n---\nx\n").form == "draft"
    assert load_one("---\nname: d\nkind: heuristic\n---\nx\n").pending
    assert not load_one("---\nname: p\nkind: assumption\n---\nx\n").pending
    assert load_one("---\nname: g\nkind: heuristic\ndirection: maximize\nmetric: team.tanks\n"
                    "---\nx\n").form == "heuristic"
    for bad in ("---\nname: b\nkind: constraint\nrequire: team.tanks <= 2\nbonus: 1\n---\nx\n",
                "---\nname: b\nkind: constraint\nmetric: team.tanks\n---\nx\n",
                # a constraint always holds and is never weighted
                "---\nname: b\nkind: constraint\nrequire: team.tanks <= 2\nwhen: map.known == 1\n"
                "---\nx\n",
                "---\nname: b\nkind: constraint\nrequire: team.tanks <= 2\nweight: 2\n---\nx\n",
                "---\nname: b\nkind: constraint\nrequire: team.tanks <= 2\npenalty: 2\n---\nx\n",
                "---\nname: b\nkind: constraint\nbonus: team.tanks\n---\nx\n",
                "---\nname: b\nkind: constraint\nrequire: team.tanks <= 2\ndirection: maximize\n"
                "---\nx\n",
                "---\nname: b\nkind: heuristic\nwhen: team.tanks > 1\npenalty: 2\nsoft: false\n"
                "---\nx\n",
                "---\nname: b\nkind: heuristic\ndirection: maximize\nmetric: team.tanks\n"
                "require: team.tanks <= 2\n---\nx\n",
                "---\nname: b\nkind: constraint\nrequire: team.tanks <= 2\nsoft: true\n---\nx\n",
                "---\nname: b\nkind: rule\nrequire: team.tanks <= 2\n---\nx\n",
                "---\nname: b\nkind: assumption\nrequire: team.tanks <= 2\n---\nx\n",
                "---\nname: b\nkind: goal\ndirection: maximize\nmetric: team.tanks\n---\nx\n",
                "---\nname: b\nkind: strategy\n---\nx\n",
                # a heuristic weighs a metric or an expression, not both
                "---\nname: b\nkind: heuristic\ndirection: maximize\nmetric: team.tanks\n"
                "penalty: 1\n---\nx\n",
                # a dial is NAME: a finite number
                "---\nname: b\nkind: heuristic\nbonus: params.X\nparams:\n  X: inf\n---\nx\n",
                "---\nname: b\nkind: heuristic\nbonus: params.x\nparams:\n  x: 1\n---\nx\n"):
        with pytest.raises(CatalogError):
            load_one(bad)


def test_a_key_that_is_not_a_field_is_refused_by_name(tmp_path):
    """A frontmatter key outside strategy.FIELDS - a typo, a form's leftover -
    would read as nothing and score silently wrong: the catalog refuses it,
    naming the key. soft: is refused by name, a limit always holding; id is
    the filename's own, which the catalog checks against the file."""
    path = tmp_path / "typo.md"
    head = "---\nname: Typo\nkind: heuristic\nmetric: team.tanks\ndirection: maximize\n"
    path.write_text(head + "wieght: 3\n---\nx\n", encoding="utf-8")
    with pytest.raises(CatalogError, match=r"^typo: wieght is not a strategy field \(the"):
        catalog.load(str(tmp_path))
    path.write_text(head + "weight: 3\nsoft: true\n---\nx\n", encoding="utf-8")
    with pytest.raises(CatalogError, match=r"^typo: soft: is refused - a limit always holds"):
        catalog.load(str(tmp_path))
    path.write_text(head + "weight: 3\nid: typo\n---\nx\n", encoding="utf-8")
    assert catalog.load(str(tmp_path))[0].weight == 3


def test_a_guard_is_settled_by_the_board_when_it_reads_only_red_the_map_the_world_and_params():
    assert settled_by_board(["enemy.size", "map.known", "world.heal_bench", "params.X"])
    assert not settled_by_board(["enemy.size", "team.supports"])
    assert not settled_by_board(["matchup.pool_diff"])


def test_weights_override_a_heuristic_for_one_board_and_never_the_file():
    """The playbook tab's sliders: `id:value` strings or a mapping become
    weights clamped to the file's range; the catalog's heuristic carries the
    override in a copy, the loaded one and its file are untouched, and a
    constraint or an unknown id is ignored."""
    parsed = catalog.parse_weights(["a:2", "b:11", "c:-1"])
    assert parsed == {"a": 2.0, "b": 10.0, "c": 0.0}
    assert catalog.parse_weights({"a": "3.5"}) == {"a": 3.5}
    # a malformed weight is refused, never dropped
    for malformed, said in ((["nonsense"], "id:value"), (["d:x"], "not a number"),
                            ({"e": None}, "not a number"), (["d:nan"], "not a number"),
                            (["e:inf"], "not a number")):
        with pytest.raises(Refusal, match=said):
            catalog.parse_weights(malformed)
    cat = catalog.load(FIXTURE_PLAYBOOK)
    heuristic = next(h for h in cat if h.kind == "heuristic")
    scored = next(h for h in cat if h.form == "scored")          # a heuristic too: it weighs
    limit = next(h for h in cat if h.form == "limit")
    before = heuristic.weight
    over = catalog.weighted(cat, {heuristic.id: 7.5, scored.id: 3, limit.id: 9, "no-such": 1})
    assert next(h for h in over if h.id == heuristic.id).weight == 7.5
    assert next(h for h in over if h.id == scored.id).weight == 3
    assert heuristic.weight == before                        # the loaded one is untouched
    assert next(h for h in over if h.id == limit.id) is limit  # a constraint's stays its own
    assert catalog.weighted(cat, {}) is cat and len(over) == len(cat)


def test_meta_md_holds_the_engines_weights_and_is_no_strategy(catalog_copy):
    """meta.md beside the strategy files is the default engine's weights and
    its prose: the catalog never loads it as a strategy, and the digest
    leaves it out - a fixture's stamp records the weights. The live
    playbook holds one the engine can read."""
    meta = catalog.read_meta(catalog_copy)
    assert meta.weights.record() == {"meta": 1.0, "rate": 1.0, "synergy": 0.1, "counter": 0.05}
    assert meta.body.startswith("# The meta\n")
    assert catalog.META_FILE not in catalog.strategy_files(catalog_copy)
    assert "meta" not in {s.id for s in catalog.load(catalog_copy)}
    digest = catalog.playbook_digest(catalog_copy)
    path = Path(catalog_copy, catalog.META_FILE)
    path.write_text(path.read_text(encoding="utf-8").replace("rate: 1\n", "rate: 2\n"),
                    encoding="utf-8")
    assert catalog.engine_weights(catalog_copy).rate == 2.0
    assert catalog.playbook_digest(catalog_copy) == digest
    assert catalog.meta_record(catalog.read_meta(catalog_copy))["rate"] == 2.0
    assert catalog.meta_rendered(meta.weights, 10.0) == (
        "meta 1 x (rate 1, synergy 0.1, counter 0.05); swap cost 10")
    assert catalog.read_meta(catalog.SHIPPED_DIR).weights.on


def test_meta_md_sets_the_swap_cost_and_a_folder_without_one_reads_the_shipped(
        catalog_copy, tmp_path, monkeypatch):
    """The shipped meta.md sets the swap cost, in share points; a folder
    written before the dial - the reference playbook's - reads the shipped
    one's, and one that sets its own reads its own, served and rendered
    beside the weights. The cost keeps its own range, 0..50, and swap.md is
    no strategy: the id is the dial's. With the shipped file silent too, a
    folder without one is refused by name."""
    shipped = Path(catalog.SHIPPED_DIR, catalog.META_FILE).read_text(encoding="utf-8")
    assert catalog.parse_meta(shipped).swap is not None
    path = Path(catalog_copy, catalog.META_FILE)
    text = path.read_text(encoding="utf-8")
    assert catalog.parse_meta(text).swap is None
    assert catalog.swap_cost(catalog_copy) == catalog.swap_cost(catalog.SHIPPED_DIR)
    path.write_text(text.replace("counter: 0.05\n", "counter: 0.05\nswap: 25\n"),
                    encoding="utf-8")
    meta = catalog.read_meta(catalog_copy)
    assert catalog.swap_cost(catalog_copy) == 25.0 == catalog.meta_record(meta)["swap"]
    assert catalog.meta_rendered(meta.weights, meta.swap) == (
        "meta 1 x (rate 1, synergy 0.1, counter 0.05); swap cost 25")
    for bad in ("51", "-1", "much"):
        path.write_text(text.replace("counter: 0.05\n", "counter: 0.05\nswap: %s\n" % bad),
                        encoding="utf-8")
        with pytest.raises(CatalogError, match=r"^meta.md: swap is a number within 0\.\.50"):
            catalog.read_meta(catalog_copy)
    path.write_text(text, encoding="utf-8")
    Path(catalog_copy, "swap.md").write_text(
        "---\nname: Swap\nkind: assumption\n---\nx\n", encoding="utf-8")
    with pytest.raises(CatalogError, match=r"^swap\.md: swap is meta\.md's and no strategy's"):
        catalog.load(catalog_copy)
    silent = tmp_path / "silent"
    silent.mkdir()
    (silent / catalog.META_FILE).write_text(text, encoding="utf-8")
    monkeypatch.setattr(catalog, "SHIPPED_DIR", str(silent))
    with pytest.raises(CatalogError, match=r"swap unset - the shipped meta\.md sets the swap cost"):
        catalog.read_meta(catalog_copy)


def test_a_boards_swap_weight_keeps_the_swap_costs_range():
    """The swap cost rides a board's weights beside the heuristics' and the
    meta, clamped to its own range, 0..50 share points, not a weight's."""
    assert catalog.parse_weights(["swap:80", "meta:80", "swap-ish:30"]) == {
        "swap": 50.0, "meta": 10.0, "swap-ish": 10.0}
    assert catalog.parse_weights({"swap": "-3"}) == {"swap": 0.0}
    cat = catalog.load(FIXTURE_PLAYBOOK)
    assert catalog.weighted(cat, {"swap": 20.0}) == cat


@pytest.mark.parametrize(("text", "message"), [
    ("---\nmeta: 1\nrate: 1\nsynergy: 0.1\n---\nx\n", "counter unset"),
    ("---\nmeta: 1\nrate: 1\nsynergy: 0.1\ncounter: 0.05\nweight: 2\n---\n", "weight is not"),
    ("---\nmeta: 11\nrate: 1\nsynergy: 0.1\ncounter: 0.05\n---\nx\n", r"within 0\.\.10"),
    ("---\nmeta: 1\nrate: -1\nsynergy: 0.1\ncounter: 0.05\n---\nx\n", r"within 0\.\.10"),
    ("---\nmeta: 1\nrate: one\nsynergy: 0.1\ncounter: 0.05\n---\nx\n", "rate is a number"),
    ("meta: 1\n", "no frontmatter"),
])
def test_a_meta_file_that_breaks_a_rule_is_refused_by_name(tmp_path, text, message):
    (tmp_path / catalog.META_FILE).write_text(text, encoding="utf-8")
    with pytest.raises(CatalogError, match="^meta.md: .*%s" % message):
        catalog.read_meta(str(tmp_path))


def test_a_playbook_without_a_meta_file_has_no_engine_weights(tmp_path, monkeypatch):
    """Every playbook folder holds its meta.md: a folder without one is a
    CatalogError wherever the weights are read, the playbook in force's
    included, so a lost file stops the board rather than scoring quietly
    without the engine."""
    shutil.copy(os.path.join(FIXTURE_PLAYBOOK, "open-queue-tanks.md"), tmp_path)
    monkeypatch.setenv("COUNTRIX_STRATEGIES", str(tmp_path))
    assert [s.id for s in catalog.load()] == ["open-queue-tanks"]
    with pytest.raises(CatalogError, match=r"meta\.md: missing"):
        catalog.engine_weights()


@pytest.mark.invariant
def test_every_map_and_stage_a_strategy_names_is_one_the_database_holds(world):
    """A strategy that names a map or a stage in an expression - map.name ==
    'Havana', map.stage in ['City Streets', 'Sea Fort'] - names one the maps
    and their stages hold, as the map lists it: a name spelled otherwise
    would leave its gate shut on every board without a word."""
    names = {m.name for m in world.maps.values()}
    stages = {s for m in world.maps.values() for s in m.stages}
    literal = re.compile(r"map\.(name|stage)\s*(?:==|in)\s*(\[[^\]]*\]|'[^']*')")
    for s in catalog.load():
        for expr in (s.require, s.when, s.bonus, s.penalty):
            if expr is None:
                continue
            for kind, value in literal.findall(expr.source):
                held = names if kind == "name" else stages
                assert set(re.findall(r"'([^']*)'", value)) <= held, (s.id, value)
