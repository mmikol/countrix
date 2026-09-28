"""The daily refresh: the database and the strategies mirror brought up to
date on a schedule. `python -m door.refresh`, the `refresher` container's
process, refreshes daily at COUNTRIX_REFRESH_AT (DEFAULT_AT, container
time), and at once on start when the cached pages are older than
MAX_AGE_HOURS.

A refresh comes in two sizes. The DAILY one refetches what moves day to
day - the wiki's seasons (a snapshot is stamped with the season live that
day) and the rates - then re-mirrors the strategies. The FULL one is
`sync_all` with refresh on: every page of every source, including the hero
pages and the wiki articles (kits, synergies, counters) that only change
with a patch; it runs when the wiki cache is older than FULL_DAYS. Either
way a page that fails keeps its cached copy, so a flaky source degrades to
yesterday's numbers rather than an empty table, and the pull's reply lists
it under stale: its first line, which the log keeps, ends with the count,
and sync_all's with the pulls that read one.
"""

import os
import statistics
import time
import traceback
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from typing import NamedTuple, NoReturn

from db import CACHE_DIRS, SECONDS_PER_HOUR
from door.mcp import tools

DEFAULT_AT = "05:00"      # the daily time when COUNTRIX_REFRESH_AT names none
MAX_AGE_HOURS = 20.0      # a cache older than this is refreshed at once on start
FULL_DAYS = 7.0           # a wiki cache older than this calls for a full refresh
# What moves between patches. Seasons first: rates stamp their snapshot with
# the season live today. No tool that reads the hero articles: refetching
# them daily would keep the wiki cache young and a full refresh never due.
DAILY = ("pull_seasons", "pull_rates")


def parse_at(text: str) -> tuple[int, int]:
    """'05:00' -> (5, 0); anything else is an error worth stopping on."""
    try:
        hours, minutes = text.strip().split(":")
        hour, minute = int(hours), int(minutes)
    except ValueError:
        raise ValueError("refresh time must be HH:MM, got %r" % text) from None
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ValueError("refresh time must be HH:MM, got %r" % text)
    return hour, minute


def seconds_until(at: str, now: datetime | None = None) -> float:
    """Seconds from `now` to the next occurrence of the HH:MM in `at`
    (tomorrow's if today's has passed or is now)."""
    hour, minute = parse_at(at)
    now = now or datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def _page_ages(cache_dirs: Iterable[str]) -> list[float]:
    """Seconds since each cached page in `cache_dirs` was written; a directory
    that does not exist holds none."""
    now = time.time()
    return [now - os.path.getmtime(os.path.join(path, name))
            for path in cache_dirs if os.path.isdir(path) for name in os.listdir(path)]


def cache_age_hours(cache_dirs: Iterable[str] | None = None) -> float | None:
    """Hours since the newest cached page across the sources; None if there
    is no cache at all (a first build)."""
    ages = _page_ages(cache_dirs or CACHE_DIRS.values())
    return min(ages) / SECONDS_PER_HOUR if ages else None


def full_due(cache_dirs: Iterable[str] | None = None) -> bool:
    """A full refresh is due when the slow-moving cache (the wiki's) is older
    than FULL_DAYS, or absent. Its age is the median page's: the daily
    refresh refetches a few pages (the Season pages), a full one all of them."""
    ages = _page_ages(cache_dirs or [CACHE_DIRS["wiki"]])
    if not ages:
        return True
    return statistics.median_high(ages) > FULL_DAYS * 24 * SECONDS_PER_HOUR


class Refreshed(NamedTuple):
    """What one refresh came to: whether it succeeded, and its summary or its
    error."""
    ok: bool
    text: str


def refresh_once(ctx: tools.Context, log: tools.Log = print) -> Refreshed:
    """One refresh -> (ok, text): daily (seasons, rates, strategies) or full
    (every source), as full_due() decides - its text each tool's headline,
    joined by "; ". Never raises; a failure returns (False, the error)."""
    started = time.time()
    try:
        # inside the try: full_due() lists and stats the page cache, which can
        # raise OSError like the refresh it decides, and the promise above has to hold
        full = full_due()
        log("refresh: starting a %s refresh at %s" % (
            "FULL" if full else "daily", datetime.now().strftime("%Y-%m-%d %H:%M")))
        if full:
            calls: list[tuple[str, dict[str, object]]] = [("sync_all", {"refresh": True})]
        else:
            calls = [(name, {"refresh": True}) for name in DAILY]
            calls.append(("load_authored", {}))
        text = "; ".join(ctx.call(name, **arguments).text.partition("\n")[0]
                         for name, arguments in calls)
    except Exception as error:  # noqa: BLE001  # a failed refresh leaves yesterday's data in place
        log(traceback.format_exc().rstrip())
        log("refresh: FAILED after %.0fs: %s: %s"
            % (time.time() - started, type(error).__name__, error))
        return Refreshed(False, str(error))
    log("refresh: done in %.0fs - %s" % (time.time() - started, text))
    return Refreshed(True, text)


def run_forever(
        ctx: tools.Context, at: str, log: tools.Log = print,
        sleep: Callable[[float], object] = time.sleep) -> NoReturn:
    """Refresh at once if the cache is stale, then daily at `at` (HH:MM). A
    time that is not HH:MM refuses before the first refresh."""
    parse_at(at)
    age = cache_age_hours()
    if age is None or age > MAX_AGE_HOURS:
        log("refresh: cached pages are %s - refreshing now"
            % ("absent" if age is None else "%.0fh old" % age))
        refresh_once(ctx, log)
    else:
        log("refresh: cached pages are %.0fh old - fresh enough" % age)
    while True:
        wait = seconds_until(at)
        log("refresh: next at %s (in %dh%02dm)" % (
            at, wait // SECONDS_PER_HOUR, (wait % SECONDS_PER_HOUR) // 60))
        sleep(wait)
        refresh_once(ctx, log)


def main() -> NoReturn:
    """The refresher container's loop, at COUNTRIX_REFRESH_AT or DEFAULT_AT,
    over DATABASE_URL or the embedded cluster; it never returns."""
    run_forever(tools.Context(log=print), os.environ.get("COUNTRIX_REFRESH_AT") or DEFAULT_AT)


if __name__ == "__main__":
    main()
