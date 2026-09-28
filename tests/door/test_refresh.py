"""The daily refresh's clock: the scheduler's arithmetic, the cache ages
that make a refresh due, the loop, the time it reads from the environment
and the tools each refresh calls. Pure - stubbed tools, no network, no
database."""

from datetime import datetime

import pytest

from door import refresh
from door.mcp.schema import ToolReply
from tests.db.test_cache import write_aged


def test_seconds_until_the_next_daily_run():
    now = datetime(2026, 9, 13, 14, 0, 0)
    assert refresh.seconds_until("05:00", now) == 15 * 3600
    assert refresh.seconds_until("14:30", now) == 30 * 60
    assert refresh.seconds_until("14:00", now) == 24 * 3600      # now counts as passed
    with pytest.raises(ValueError, match="HH:MM"):
        refresh.seconds_until("5pm", now)


def test_cache_age_reads_the_newest_page(tmp_path):
    assert refresh.cache_age_hours([str(tmp_path / "missing")]) is None
    write_aged(tmp_path / "old.html", "x", hours=100)
    write_aged(tmp_path / "newer.html", "x", hours=30)
    assert 29.9 < refresh.cache_age_hours([str(tmp_path)]) < 30.1


def test_refresh_once_survives_a_bad_day(monkeypatch):
    from door.mcp import tools
    logs = []
    nowhere = tools.Context(dsn="postgresql://nowhere")
    monkeypatch.setattr(tools.Context, "call", lambda ctx, name, **kw: (_ for _ in ()).throw(
        RuntimeError("blizzard 504")))
    ok, text = refresh.refresh_once(nowhere, logs.append)
    assert ok is False and "504" in text and any("FAILED" in line for line in logs)
    traceback = next(line for line in logs if line.startswith("Traceback"))
    assert traceback.endswith("RuntimeError: blizzard 504")
    monkeypatch.setattr(tools.Context, "call",
                        lambda ctx, name, **kw: ToolReply("sync_all: done", {}))
    ok, _ = refresh.refresh_once(nowhere, logs.append)
    assert ok is True


def test_the_loop_refreshes_stale_data_on_start_then_waits(monkeypatch):
    runs, waits = [], []
    monkeypatch.setattr(refresh, "cache_age_hours", lambda *a: 30.0)
    monkeypatch.setattr(refresh, "refresh_once", lambda ctx, log: runs.append(ctx) or (True, ""))

    def sleep(seconds):
        waits.append(seconds)
        if len(waits) == 2:
            raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        refresh.run_forever("ctx", "05:00", log=lambda m: None, sleep=sleep)
    assert runs == ["ctx"] * 2 and all(0 < w <= 24 * 3600 for w in waits)


def test_the_loop_refuses_a_time_that_is_not_hh_mm_before_it_refreshes(monkeypatch):
    monkeypatch.setattr(refresh, "refresh_once", lambda ctx, log: pytest.fail("it refreshed"))
    with pytest.raises(ValueError, match="HH:MM"):
        refresh.run_forever("ctx", "5pm", log=lambda m: None)


def test_the_refresh_time_is_read_from_the_environment_at_start(monkeypatch):
    # tools.Context resolves its dsn lazily, so nothing here touches a database
    times = []
    monkeypatch.setattr(refresh, "run_forever", lambda ctx, at: times.append(at))
    monkeypatch.setenv("COUNTRIX_REFRESH_AT", "06:30")
    refresh.main()
    monkeypatch.delenv("COUNTRIX_REFRESH_AT")
    refresh.main()
    assert times == ["06:30", refresh.DEFAULT_AT]


def test_full_refresh_is_due_when_the_slow_caches_are_stale(tmp_path):
    assert refresh.FULL_DAYS == 7
    assert refresh.full_due([str(tmp_path / "none")]) is True        # nothing cached
    write_aged(tmp_path / "Ana.wikitext", "x", hours=24 * 3)
    assert refresh.full_due([str(tmp_path)]) is False
    write_aged(tmp_path / "Ana.wikitext", "x", hours=24 * 8)
    assert refresh.full_due([str(tmp_path)]) is True
    # the daily refresh refetches the Patches table; the rest still says stale
    write_aged(tmp_path / "Mei.wikitext", "x", hours=24 * 9)
    write_aged(tmp_path / "cargo_patches.json", "x", hours=1)
    assert refresh.full_due([str(tmp_path)]) is True
    assert refresh.full_due() in (True, False)     # the default reads the wiki cache


def test_daily_refresh_touches_only_what_moves(monkeypatch):
    from door.mcp import tools
    calls = []
    monkeypatch.setattr(tools.Context, "call", lambda ctx, name, **kw: calls.append(
        (name, kw.get("refresh"))) or ToolReply("%s: ok\n  rows  1" % name, {}))
    monkeypatch.setattr(refresh, "full_due", lambda: False)
    ok, text = refresh.refresh_once(tools.Context(dsn="postgresql://nowhere"), lambda m: None)
    # patches first: the day's snapshot is stamped with the patch live today
    assert ok and calls == [("pull_patches", True), ("pull_rates", True),
                            ("load_authored", None)]
    # the log keeps each tool's headline line, not its counts
    assert text == "pull_patches: ok; pull_rates: ok; load_authored: ok"
    # the hero articles (kits, synergies, counters) are the full refresh's: a
    # daily refetch would keep the wiki cache young and full_due() never true
    assert not set(refresh.DAILY) & {"pull_kits", "pull_synergies", "pull_counters"}
    assert "pull_counters" in [spec.name for spec in tools.REGISTRY.pulls()]
    # the calls above are stubbed, so a renamed tool would pass them: the names are checked here
    assert {name for name, _ in calls} <= set(tools.REGISTRY.names())
    calls.clear()
    monkeypatch.setattr(refresh, "full_due", lambda: True)
    ok, text = refresh.refresh_once(tools.Context(dsn="postgresql://nowhere"), lambda m: None)
    assert ok and calls == [("sync_all", True)] and text == "sync_all: ok"
    assert {name for name, _ in calls} <= set(tools.REGISTRY.names())
