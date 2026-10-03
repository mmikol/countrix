"""Fetching: the page cache, its freshness and the request loop, shared by
every source.

    cached_get       one page, from the cache if it is there and fresh
    cached           the cache sequence every reader runs through: the fresh
                     copy, else what it produces, else the stale copy
    request          one page asked for under a RequestPolicy and handed to
                     a reader; a failure is retried while attempts remain
    RequestPolicy    a source's attempts, backoff, timeout and pace
    cache_key        a request as a file name in the cache
    session          a requests session that identifies this project
    PullContext      what a pull's run() takes beside its connection: the page
                     cache, the session, the log (stderr unless the caller
                     names another - over stdio, stdout is the MCP wire) and
                     the cutoff. Without one a page is kept forever (a build
                     from the caches); a refresh's cutoff, the moment it
                     began, refetches every page written before it, so the
                     pulls of one refresh fetch a shared article once. A
                     page that fails to refetch keeps its cached copy and is
                     listed in the context's stale, so a flaky source
                     degrades to yesterday's numbers, never to an empty
                     table, and the pull says so. Every page served adds
                     its write time to the context's captured, so a pull
                     dates what it read by when its pages were fetched

Each source package (blizzard, wiki) names its own endpoints
and its own `sources` row, so provenance lives with the source. Fetching
yields raw markup; reading it is the package's job.
"""

import dataclasses
import os
import random
import re
import time
from collections.abc import Callable, Mapping

import requests

from db import SECONDS_PER_HOUR, Log, to_stderr, write_whole

MAX_BACKOFF = 60.0


class FetchError(Exception):
    """A page that could not be had."""


class RateLimitError(FetchError):
    """The source answered, and its answer says to slow down."""


@dataclasses.dataclass(frozen=True)
class RequestPolicy:
    """How a source is asked for a page.

    attempts counts every request, the first included, so 1 means no retry.
    backoff is the first wait after a failure and doubles each attempt, up to
    MAX_BACKOFF. delay is the pause after a page, jittered.

    Attempts are for a source that stalls under load and does not fail
    outright - Blizzard's rates page answers a few hundred sequential
    requests with a 504. A source that needs hundreds of pages raises both
    attempts and backoff: giving up mid-run loses the whole stage, and the
    wait is cheap next to refetching everything.
    """

    attempts: int = 1
    backoff: float = 1.0
    timeout: float = 30
    delay: float = 1.0


USER_AGENT = "countrix/0.1 (personal project; contact via repo)"


def session() -> requests.Session:
    """A requests session that says who we are."""
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


@dataclasses.dataclass(frozen=True)
class PullContext:
    """What a pull runs with: the page cache it reads through, the session
    it fetches on, where its progress lines go, and when a cached page is
    stale. cutoff, a time.time() stamp, makes every page written before it
    stale - the moment a refresh began, so a page one pull of the refresh
    wrote is fresh for the next. With None a page is kept forever (a build
    from the caches).

    stale holds 'name: error' for each page whose refetch failed and whose
    cached copy was read instead. captured holds the write time of each
    page served, a time.time() stamp: a cached copy's, or a fetched page's
    as it was written, so a build from the caches dates a page as the
    refresh that fetched it did. The context stays frozen: only the lists'
    contents change."""
    cache_dir: str
    session: requests.Session = dataclasses.field(default_factory=session)
    log: Log = to_stderr
    cutoff: float | None = None
    stale: list[str] = dataclasses.field(default_factory=list)
    captured: list[float] = dataclasses.field(default_factory=list)


def _age(path: str) -> float:
    """Seconds since a cached page was written."""
    return time.time() - os.path.getmtime(path)


def _read_cache(path: str) -> str:
    """A cached page's text."""
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _keep_stale(pull: PullContext, path: str, error: Exception) -> str:
    """A refetch failed: fall back to the cached copy, record it in the pull's
    stale and say so in its log."""
    name = os.path.basename(path)
    pull.stale.append("%s: %s" % (name, error))
    hours = _age(path) / SECONDS_PER_HOUR
    pull.log("warning: %s; keeping the cached copy from %.0fh ago (%s)" % (error, hours, name))
    return _read_cache(path)


def cache_key(*parts: object) -> str:
    """A filesystem-safe name for a request."""
    return re.sub(r"[^A-Za-z0-9]+", "_", "_".join(str(p) for p in parts)).strip("_")


def request[T](
        session: requests.Session, url: str, params: Mapping[str, str] | None,
        policy: RequestPolicy, read: Callable[[requests.Response], T]) -> T:
    """One page asked for under `policy`, and what `read` makes of it.

    A requests failure or a RateLimitError from `read` is retried while attempts
    remain, and raises FetchError when they run out. Any other FetchError
    from `read` is the answer, and is not retried.
    """
    last_error: Exception | None = None
    for attempt in range(policy.attempts):
        try:
            response = session.get(url, params=params, timeout=policy.timeout)
            response.raise_for_status()
            result = read(response)
        except (requests.RequestException, RateLimitError) as error:
            last_error = error
            if attempt + 1 < policy.attempts:     # no point waiting to give up
                # Drop the pooled connections before trying again. A source
                # that answers "Remote end closed connection without response"
                # has hung up on a keep-alive socket, and retrying down the
                # same dead socket fails identically however long we wait.
                session.close()
                time.sleep(min(MAX_BACKOFF, policy.backoff * 2 ** attempt))
        else:
            # Jittered, so a few hundred sequential requests do not arrive as a clock.
            # The jitter is politeness and not a secret, so B311 does not apply.
            time.sleep(policy.delay * random.uniform(0.75, 1.5))  # nosec B311
            return result
    raise FetchError("%s failed after %d attempts: %s" % (url, policy.attempts, last_error))


def cached(pull: PullContext, name: str, produce: Callable[[], str]) -> str:
    """The text of cache file `name` in the pull's cache, fresh from the cache
    or from produce().

    A copy written since the pull's cutoff, or any copy when it has none,
    is read and nothing is asked for. Otherwise produce() runs and its text
    is written. When it fails with a FetchError, the stale copy is kept and
    named in the pull's stale, and the failure surfaces only when there is
    none. The write time of the copy served joins the pull's captured.
    """
    path = os.path.join(pull.cache_dir, name)
    if os.path.exists(path) and (pull.cutoff is None or os.path.getmtime(path) >= pull.cutoff):
        text = _read_cache(path)
    else:
        try:
            text = produce()
        except FetchError as error:
            if not os.path.exists(path):
                raise
            text = _keep_stale(pull, path, error)
        else:
            write_whole(path, text)   # never half a page a later build reads as whole
    pull.captured.append(os.path.getmtime(path))
    return text


def cached_get(
        pull: PullContext, url: str, key: str, params: Mapping[str, str] | None = None, *,
        policy: RequestPolicy) -> str:
    """One page as text, through the pull's page cache as `key`.html."""
    return cached(pull, key + ".html", lambda: request(
        pull.session, url, params, policy, lambda response: response.text))
