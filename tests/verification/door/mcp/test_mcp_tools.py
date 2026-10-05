"""The tools in-process: query, db_status, roster, the board tools,
db_migrate and metrics against the built database; and,
with no database, query's refusals, db_status's remedy for a stale schema,
the playbook writes' mirror, the Draft
a board tool hands its function, and how query turns a cell into JSON, pages
its rows and words an empty result. The one registry's family order is
test_mcp_registry's; the readiness every door reports and a migration that
fails are db.psql.schema's, in tests/verification/db/test_psql.py."""

import datetime
import decimal
import os

import psycopg
import pytest

from db import Refusal, psql
from db.psql import schema
from door.mcp import boards, lifecycle, tools
from facts import board_facts, tables
from facts.draft import Draft
from inference import catalog, tune
from tests.verification.door.mcp import Offline

# --- the tools against the built database ----------------------------------

@pytest.fixture(scope="module")
def ctx(db, dsn):
    return tools.Context(dsn=dsn)


@pytest.mark.invariant
def test_query_is_read_only(ctx):
    _text, data = ctx.call("query", sql="select count(*) from heroes")
    assert data["rows"][0][0] > 40
    text, data = ctx.call("query", sql="select generate_series(1, 300)")
    assert len(data["rows"]) == 200 and data["truncated"] is True
    assert text.endswith("\n(truncated: 200 rows shown)")
    _text, data = ctx.call("query", sql="select generate_series(1, 200)")
    assert len(data["rows"]) == 200 and data["truncated"] is False
    with pytest.raises(Refusal, match="read-only"):
        ctx.call("query", sql="delete from heroes")
    with pytest.raises(Refusal, match="read-only"):
        ctx.call("query", sql="select 1; drop table heroes")
    # what Postgres rejects is the caller's to fix too, answered in its words
    with pytest.raises(Refusal, match='query: column "nosuch" does not exist'):
        ctx.call("query", sql="select nosuch from heroes")
    # a write past the first word reaches the read-only transaction, which refuses it
    with pytest.raises(Refusal, match="query: "):
        ctx.call("query", sql="with d as (delete from heroes returning *) select * from d")


@pytest.mark.invariant
def test_db_status_and_roster(ctx):
    text, status = ctx.call("db_status")
    assert status["table_count"] >= 33 and status["counts"]["heroes"] > 40
    assert status["state"] == "current" and "state: current" in text
    assert status["counts"]["counters"] >= 100
    assert {s["source"] for s in status["snapshots"]} == {"blizzard"}
    text, roster = ctx.call("roster")
    assert any(h["name"] == "Ana" and h["portrait"] for h in roster["heroes"])
    assert any(m["name"] == "King's Row" and m["mode"] == "Hybrid" for m in roster["maps"])
    assert all(h["pool"] > 0 for h in roster["heroes"])
    kings_row = next(m for m in roster["maps"] if m["name"] == "King's Row")
    assert kings_row["sided"] and "King's Row (Hybrid, " in text and "sided)" in text


@pytest.mark.invariant
def test_facts_and_infer_through_the_tools(ctx):
    text, data = ctx.call("facts", map="King's Row", red=["Zarya"], blue=["Ana"])
    assert data["count"] > 300 and text.startswith("[F1]")
    with pytest.raises(Refusal, match="unknown heroes"):
        ctx.call("facts", red=["Goku"])
    with pytest.raises(Refusal, match="unknown heroes"):
        ctx.call("reach", hero="Nosuchhero")
    text, data = ctx.call("infer", map="King's Row", red=["Zarya"], blue=["Ana"])
    assert len(data["blue"]) == 6 and "Ana" in data["blue"]
    assert "optimal comp" in text


@pytest.mark.invariant
def test_db_migrate_is_idle_when_the_ledger_is_current(ctx):
    """A ledger behind the files is skipped, not migrated: a test run never
    applies a migration to the database the suite reads, which may be one
    another checkout shares."""
    with ctx.connect() as cx:
        behind = schema.pending(cx)
    if behind:
        pytest.skip("the ledger is behind the files (%s): db_migrate is not the suite's to run"
                    % ", ".join(behind))
    text, data = ctx.call("db_migrate")
    assert data["applied"] == [] and text.startswith("db_migrate: applied 0")


@pytest.mark.invariant
def test_query_runs_as_the_reader_role(ctx):
    _text, data = ctx.call("query", sql="select current_user, count(*) from heroes")
    assert data["rows"][0][0] == "matrix_reader" and data["rows"][0][1] > 0


# None of these touches the database, so they run without one (as CI does).

def test_query_refuses_file_and_server_reaching_sql_before_connecting():
    nowhere = tools.Context(dsn="postgresql://nowhere")
    # the three sleeps migration 012 revokes
    for sql in ("select pg_read_file('/etc/passwd')", "select * from pg_ls_dir('.')",
                "COPY heroes TO PROGRAM 'id'", "select pg_sleep(10)",
                "select pg_sleep_for('10 seconds')", "select pg_sleep_until(now() + '10s')"):
        with pytest.raises(Refusal, match=r"refuses|read-only"):
            nowhere.call("query", sql=sql)
    long = "select '%s'" % ("x" * (lifecycle.MAX_SQL_CHARS - 8))       # one character over
    assert len(long) == lifecycle.MAX_SQL_CHARS + 1
    with pytest.raises(Refusal, match="too long"):
        nowhere.call("query", sql=long)


def test_what_the_read_only_transaction_refuses_is_the_callers_to_fix(monkeypatch):
    """A statement past the first-word check can still write - a WITH that
    deletes, FOR UPDATE - or use what Postgres does not support: Postgres
    refuses it in the read-only transaction, and the caller hears a Refusal
    in its words, never INTERNAL. The connection is stubbed."""
    class Refusing:
        def __init__(self, error):
            self.error = error

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql):
            if not sql.startswith("SET "):
                raise self.error
    refused = (
        psycopg.errors.ReadOnlySqlTransaction("cannot execute DELETE in a read-only transaction"),
        psycopg.errors.FeatureNotSupported("FOR UPDATE is not allowed with aggregate functions"))
    for error in refused:
        monkeypatch.setattr(lifecycle.psycopg, "connect", lambda dsn, error=error: Refusing(error))
        with pytest.raises(Refusal, match="query: %s" % error):
            tools.Context(dsn="postgresql://nowhere").call("query", sql="select 1")


def test_db_status_answers_pending_migrations_with_db_migrate(monkeypatch):
    """A schema behind the files catches up through db_migrate, which keeps
    the data; db_status names it, never a rebuild, which drops the rates
    history."""
    monkeypatch.setattr(lifecycle, "read_status", lambda ctx: lifecycle.DbStatus(
        dsn="postgresql://nowhere", state="stale", table_count=1, counts={}, snapshots=[],
        newest_capture=None, pending_migrations=["099_future.sql"]))
    text, _ = tools.Context(dsn="postgresql://nowhere").call("db_status")
    assert text.endswith("\nPENDING MIGRATIONS (db_migrate keeps the data): 099_future.sql")


def test_only_db_rebuild_creates_the_cluster(tmp_path, monkeypatch):
    """The tool that builds the database reaches psql.boot, which may create
    the embedded cluster; every other tool resolves through default_dsn,
    which never does. A dsn given to the Context is used as it is, and
    neither is asked."""

    def refuse(said):
        def stub():
            raise psql.NoDatabaseError(said)
        return stub
    monkeypatch.setattr(psql, "boot", refuse("boot asked"))
    monkeypatch.setattr(psql, "default_dsn", refuse("resolver asked"))
    for name, asked in (("db_rebuild", "boot asked"), ("db_status", "resolver asked"),
                        ("db_migrate", "resolver asked")):
        with pytest.raises(psql.NoDatabaseError, match=asked):
            tools.Context().call(name)
    with pytest.raises(psycopg.OperationalError):
        tools.Context(dsn="postgresql://nobody@127.0.0.1:9/nowhere").call("db_rebuild")


def test_a_rebuild_refuses_a_playbook_that_does_not_load_before_it_drops_anything(
        tmp_path, monkeypatch):
    """sync_all mirrors the playbook after every pull, long after the drop, so
    a rebuild checks it first: a broken playbook costs no table."""
    monkeypatch.setenv("COUNTRIX_STRATEGIES", str(tmp_path))      # no strategies at all
    monkeypatch.setattr(psql, "boot", lambda: pytest.fail("the database was reached"))
    with pytest.raises(Refusal, match="nothing was dropped: the playbook does not load"):
        tools.Context().call("db_rebuild")


def test_metrics_tool_serves_the_vocabulary():
    text, data = tools.Context(dsn="postgresql://nowhere").call("metrics")
    assert "team.coverage_share" in data["metrics"] and "team.coverage_share" in data["numeric"]
    assert "map.side" in data["text"] and "map.side" not in data["numeric"]
    assert set(data["text"]) <= set(data["metrics"])
    assert text.splitlines()[0].startswith("team.")


def test_every_playbook_write_mirrors_the_catalog_once(catalog_copy, monkeypatch):
    """tune, add_strategy and infer_strategy each reload the strategies table
    once, after the write."""
    monkeypatch.setenv("COUNTRIX_STRATEGIES", catalog_copy)
    mirrored = []
    monkeypatch.setattr(catalog, "mirror", lambda cx, cat, directory=None: mirrored.append(
        (cx, len(cat))))
    ctx = Offline(dsn="postgresql://nowhere")
    heuristic = next(h for h in catalog.load() if h.kind == "heuristic")
    files = len(catalog.strategy_files(catalog_copy))
    ctx.call("tune", id=heuristic.id, field="weight", value=3, reason="a test")
    assert mirrored == [("cx", files)]
    ctx.call(
        "add_strategy", id="a-draft", name="A draft", kind="heuristic",
        body="Prose to infer from.", reason="a test")
    assert mirrored[1:] == [("cx", files + 1)]            # the new file is in the mirror
    ctx.call(
        "infer_strategy", id="a-draft", reason="a test", metric=heuristic.metric,
        direction="maximize", weight=1)
    assert len(mirrored) == 3
    assert not [h.id for h in catalog.load() if h.pending]


def test_a_playbook_write_reaches_the_database_before_it_moves_a_file(
        catalog_copy, tmp_path, monkeypatch):
    """tune, add_strategy and infer_strategy open the database before they
    write, as db_rebuild does before it drops: with the database out of
    reach each call fails with no strategy file, doc or log line moved, so
    the same call succeeds once the database is back."""
    monkeypatch.setenv("COUNTRIX_STRATEGIES", catalog_copy)
    monkeypatch.setattr(catalog, "mirror", lambda cx, cat, directory=None: None)
    documented = []
    monkeypatch.setattr(catalog, "write_docs", lambda cat, path=None: documented.append(len(cat)))
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}

    class Unreachable(tools.Context):
        def connect(self):
            raise psql.NoDatabaseError("no database")
    heuristic = next(h for h in catalog.load() if h.kind == "heuristic")
    calls = (
        ("tune", {"id": heuristic.id, "field": "weight", "value": 3, "reason": "a test"}),
        ("add_strategy", {"id": "a-draft", "name": "A draft", "kind": "heuristic",
                          "body": "Prose to infer from.", "reason": "a test"}),
        ("infer_strategy", {"id": heuristic.id, "reason": "a test", "weight": 2}))
    for name, arguments in calls:
        with pytest.raises(psql.NoDatabaseError):
            Unreachable(dsn="postgresql://nowhere").call(name, **arguments)
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before
    assert documented == []
    for name, arguments in calls:
        Offline(dsn="postgresql://nowhere").call(name, **arguments)
    assert len(documented) == 3 and len(tune.log_tail(5)) == 3


def test_add_strategy_stores_a_charge_with_a_numeric_penalty(catalog_copy, monkeypatch):
    """The door declares its strategy fields from the rule that checks them,
    so the numeric penalty the skill and the prompt promise a charge for a
    rule broken passes the schema, a category sets the file's like any
    field, and who asked reaches the log line as it does through tune. soft
    is no field, and the door refuses it before anything is written."""
    monkeypatch.setenv("COUNTRIX_STRATEGIES", catalog_copy)
    monkeypatch.setattr(catalog, "mirror", lambda cx, cat, directory=None: None)
    ctx = Offline(dsn="postgresql://nowhere")
    with pytest.raises(Refusal):
        ctx.call("add_strategy", id="tank-cap", name="Tank cap", kind="constraint",
                 body="At most one tank.", reason="a test", require="team.tanks <= 1", soft=True,
                 penalty=2)
    assert not os.path.exists(os.path.join(catalog_copy, "tank-cap.md"))
    _, added = ctx.call(
        "add_strategy", id="tank-cap", name="Tank cap", kind="heuristic",
        body="At most one tank.", reason="a test", when="not (team.tanks <= 1)",
        penalty=2, category="shape", by="a headless agent")
    assert added["form"] == "scored" and added["line"].endswith("[a headless agent]")
    stored = next(h for h in catalog.load() if h.id == "tank-cap")
    assert stored.penalty.source == "2" and stored.category == "shape" and stored.weighs


def test_add_strategy_refuses_a_bonus_that_adds_a_name(catalog_copy, monkeypatch):
    """`bonus: map.side` once went through the door and broke every board
    its rule applied on. The catalog refuses it on its probes before the
    file exists, so the door writes nothing, mirrors nothing and logs
    nothing."""
    monkeypatch.setenv("COUNTRIX_STRATEGIES", catalog_copy)
    mirrored = []
    monkeypatch.setattr(catalog, "mirror", lambda cx, cat, directory=None: mirrored.append(cat))
    with pytest.raises(Refusal, match=r"bonus 'map\.side' - a bonus or penalty is a number"):
        Offline(dsn="postgresql://nowhere").call(
            "add_strategy", id="side-bonus", name="Side bonus", kind="heuristic",
            body="The attack pays.", reason="a test", bonus="map.side")
    assert not os.path.exists(os.path.join(catalog_copy, "side-bonus.md"))
    assert not os.path.exists(os.path.join(catalog_copy, "tuning-log.md")) and mirrored == []


def test_the_tuning_log_tool_refuses_fewer_than_one_line(catalog_copy, monkeypatch):
    monkeypatch.setenv("COUNTRIX_STRATEGIES", catalog_copy)
    ctx = tools.Context(dsn="postgresql://nowhere")
    for lines in (0, -3):
        with pytest.raises(Refusal, match="lines is 1 or more"):
            ctx.call("tuning_log", lines=lines)
    assert ctx.call("tuning_log", lines=1)[0] == "no tuning yet"


def test_a_board_tool_hands_its_function_one_draft(tmp_path, monkeypatch):
    """The board tools share BOARD's six properties, first and in order, and
    each function gets them as one Draft: tuples, an empty name dropped as
    the board's query string drops it, what the call left out empty, and
    the stage as sent."""
    seen = []

    class Stub:
        def to_dict(self):
            return {}

        def rendered(self):
            return ""
    monkeypatch.setattr(tables, "load", lambda cx: None)
    monkeypatch.setattr(board_facts, "generate", lambda world, draft: seen.append(draft) or Stub())
    Offline(dsn="postgresql://nowhere").call(
        "facts", map="Ilios", red=["", "Ana"], bans=["Mei", ""])
    Offline(dsn="postgresql://nowhere").call("facts", map="Ilios", stage="Well")
    assert seen == [Draft("Ilios", ("Ana",), (), ("Mei",), ""), Draft("Ilios", stage="Well")]
    assert list(boards.BOARD) == ["map", "red", "blue", "bans", "side", "stage"]
    for name in ("facts", "infer", "board"):
        properties = list(tools.REGISTRY.get(name).schema["properties"])
        assert properties[:len(boards.BOARD)] == list(boards.BOARD)


def test_a_query_cell_arrives_as_json():
    """A date as ISO text, an array or JSONB cell as JSON all the way down, and
    anything JSON has no type for as its text."""
    day = datetime.date(2026, 9, 24)
    assert lifecycle._cell(day) == "2026-09-24"
    assert lifecycle._cell(datetime.datetime(2026, 9, 24, 5, 0)) == "2026-09-24T05:00:00"
    assert lifecycle._cell([1, [day, "x"], None]) == [1, ["2026-09-24", "x"], None]
    assert lifecycle._cell({"when": day, 3: (True, 1.5)}) == {"when": "2026-09-24",
                                                         "3": [True, 1.5]}
    assert lifecycle._cell(decimal.Decimal("0.515")) == "0.515"


def test_a_query_page_says_truncated_exactly_when_a_row_is_left_out():
    """Past MAX_ROWS rows, or past the byte budget; never at exactly MAX_ROWS."""
    rows, truncated = lifecycle._page([(n,) for n in range(lifecycle.MAX_ROWS + 1)])
    assert len(rows) == lifecycle.MAX_ROWS and truncated is True
    rows, truncated = lifecycle._page([(n,) for n in range(lifecycle.MAX_ROWS)])
    assert len(rows) == lifecycle.MAX_ROWS and truncated is False
    # each cell is cut to MAX_CELL characters and an ellipsis before the budget
    # counts it: a row of 300 is about 600 KB, so the second row spends the MiB
    wide = ["x" * 5000] * 300
    rows, truncated = lifecycle._page([wide, wide, wide])
    assert len(rows) == 1 and truncated is True
    assert {len(cell) for cell in rows[0]} == {lifecycle.MAX_CELL + 1}


def test_a_query_that_reads_no_row_says_so_under_its_header(monkeypatch):
    """Every statement query admits names its columns, so the header always
    leads, and a result with no row says so beneath it."""
    nowhere = tools.Context(dsn="postgresql://nowhere")
    monkeypatch.setattr(lifecycle, "_read_only", lambda dsn, body: (["name", "hero_id"], []))
    text, data = nowhere.call("query", sql="select name, hero_id from heroes where false")
    assert text == "name\thero_id\n(no rows)"
    assert data == {"columns": ["name", "hero_id"], "rows": [], "truncated": False}
    monkeypatch.setattr(lifecycle, "_read_only", lambda dsn, body: (["n"], [(1,), (2,)]))
    assert nowhere.call("query", sql="select 1 union select 2")[0] == "n\n1\n2"
