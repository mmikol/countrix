"""The page cache in db/data/cache.py and the wiki's requests through it:
keep a page until a refresh's cutoff, keep the old page when the source
fails, retry a rate limit, ask for an article once. Pure - fake sessions,
no network, no database."""

import os
import time

import pytest
import requests

from db.data import cache, wiki
from tests.verification.db import write_aged

INSTANT = cache.RequestPolicy(backoff=0, delay=0)


class FakeResponse:
    def __init__(self, text="", payload=None, status=200):
        self.text, self._payload, self.status = text, payload, status

    def raise_for_status(self):
        if self.status >= 400:
            raise requests.HTTPError("%d" % self.status, response=self)

    def json(self):
        return self._payload


class FakeSession:
    """Answers with `text`, or raises when `fail` is set; with `answers`, hands
    them out one per request."""

    def __init__(self, text="new page", fail=False, payload=None, answers=None):
        self.text, self.fail, self.payload, self.calls = text, fail, payload, 0
        self.answers = list(answers or [])

    def get(self, url, params=None, timeout=None):
        self.calls += 1
        if self.fail:
            raise requests.ConnectionError("source down")
        if self.answers:
            return self.answers.pop(0)
        return FakeResponse(self.text, self.payload)

    def close(self):
        pass


def test_a_context_with_no_cutoff_keeps_a_page_forever(tmp_path):
    """A build from the caches: a page a year old is read, and nothing is
    asked for."""
    write_aged(tmp_path / "k.html", "cached", hours=365 * 24)
    session = FakeSession()
    pull = cache.PullContext(str(tmp_path), session=session)
    assert pull.cutoff is None
    assert cache.cached_get(pull, "u", "k", policy=INSTANT) == "cached"
    assert session.calls == 0


def test_refresh_refetches_a_page_written_before_it_began_and_rewrites_the_cache(tmp_path):
    """A refresh's cutoff is the moment it began: the page cached before it
    is fetched and rewritten, and the next pull of the same refresh reads
    the rewritten page without asking again."""
    write_aged(tmp_path / "k.html", "cached")
    session = FakeSession("new page")
    began = time.time() - 60                       # the refresh began a minute ago
    pull = cache.PullContext(str(tmp_path), session=session, cutoff=began)
    assert cache.cached_get(pull, "u", "k", policy=INSTANT) == "new page"
    assert session.calls == 1
    assert (tmp_path / "k.html").read_text(encoding="utf-8") == "new page"
    later = cache.PullContext(str(tmp_path), session=FakeSession("newer page"), cutoff=began)
    assert cache.cached_get(later, "u", "k", policy=INSTANT) == "new page"
    assert later.session.calls == 0
    # the rewritten page is stale only to a refresh that begins after it
    newest = cache.PullContext(
        str(tmp_path), session=FakeSession("newest page"), cutoff=time.time() + 60)
    assert cache.cached_get(newest, "u", "k", policy=INSTANT) == "newest page"


def test_a_write_cut_short_leaves_the_cached_copy_whole(tmp_path):
    """A page is written beside its cached copy and renamed over it once
    whole: a write that fails raises and leaves the old copy as it was,
    never a truncated page a later build reads as whole. A lone surrogate
    stands in for a full disk: it fails the write after the file opens."""
    write_aged(tmp_path / "k.html", "yesterday")
    pull = cache.PullContext(str(tmp_path), session=FakeSession("half a page \ud800"),
                             cutoff=time.time())
    with pytest.raises(UnicodeEncodeError):
        cache.cached_get(pull, "u", "k", policy=INSTANT)
    assert (tmp_path / "k.html").read_text(encoding="utf-8") == "yesterday"


def test_a_failed_refetch_keeps_the_cached_copy(tmp_path):
    """The stale copy is read, named in the pull's stale and warned of in its
    log; with nothing cached the failure surfaces and nothing is listed."""
    write_aged(tmp_path / "k.html", "yesterday")
    twice = cache.RequestPolicy(attempts=2, backoff=0, delay=0)
    lines = []
    pull = cache.PullContext(str(tmp_path), session=FakeSession(fail=True), log=lines.append,
                             cutoff=time.time())
    assert cache.cached_get(pull, "u", "k", policy=twice) == "yesterday"
    [stale] = pull.stale
    assert stale.startswith("k.html: u failed after 2 attempts") and "source down" in stale
    [line] = lines
    assert line.startswith("warning: u failed after 2 attempts")
    assert line.endswith("; keeping the cached copy from 48h ago (k.html)")
    with pytest.raises(cache.FetchError):         # nothing cached: the failure surfaces
        cache.cached_get(pull, "u", "other", policy=INSTANT)
    assert len(pull.stale) == 1


def test_each_page_served_adds_its_write_time_to_the_pulls_captured(tmp_path):
    """What a pull dates its pages by: a cached copy's write time, a fetched
    page's as the cache wrote it - the time a later build from the cache
    reads - and a stale copy's when its refetch fails."""
    write_aged(tmp_path / "kept.html", "cached", hours=48)
    write_aged(tmp_path / "stale.html", "yesterday", hours=24)
    pull = cache.PullContext(str(tmp_path), session=FakeSession())
    assert cache.cached_get(pull, "u", "kept", policy=INSTANT) == "cached"
    assert cache.cached_get(pull, "u", "fetched", policy=INSTANT) == "new page"
    down = cache.PullContext(str(tmp_path), session=FakeSession(fail=True), cutoff=time.time())
    assert cache.cached_get(down, "u", "stale", policy=INSTANT) == "yesterday"
    kept, fetched, stale = (os.path.getmtime(tmp_path / name)
                            for name in ("kept.html", "fetched.html", "stale.html"))
    assert pull.captured == [kept, fetched] and down.captured == [stale]
    assert kept < stale < fetched


def test_attempts_count_every_request_the_first_included(tmp_path):
    session = FakeSession(fail=True)
    with pytest.raises(cache.FetchError, match="after 3 attempts"):
        cache.cached_get(cache.PullContext(str(tmp_path), session=session), "u", "k",
                         policy=cache.RequestPolicy(attempts=3, backoff=0, delay=0))
    assert session.calls == 3


def test_wiki_cargo_and_wikitext_keep_stale_copies_too(tmp_path, instant_wiki):
    write_aged(tmp_path / "cargo_abilities.json", '[{"a": "1"}]')
    write_aged(tmp_path / "Ana.wikitext", "{{Infobox}}")
    down = cache.PullContext(str(tmp_path), session=FakeSession(fail=True), cutoff=time.time())
    up = cache.PullContext(
        str(tmp_path), session=FakeSession(payload={"cargoquery": [{"title": {"a": "2"}}]}),
        cutoff=time.time())
    assert wiki.cargo_query(down, "Abilities", ("a",)) == [{"a": "1"}]
    assert wiki.fetch_wikitext(down, "Ana") == "{{Infobox}}"
    assert wiki.cargo_query(up, "Abilities", ("a",)) == [{"a": "2"}]


def test_a_changed_wiki_response_shape_keeps_the_stale_copy(tmp_path, instant_wiki):
    """A 200 whose JSON lost the keys it should carry is a failure like any
    other: the stale copy serves, and with none cached it surfaces as WikiError."""
    cached, empty = tmp_path / "cached", tmp_path / "empty"
    cached.mkdir()
    empty.mkdir()
    write_aged(cached / "Ana.wikitext", "{{Infobox}}")
    write_aged(cached / "cargo_abilities.json", '[{"a": "1"}]')
    no_wikitext = FakeSession(payload={"parse": {}})
    no_title = FakeSession(payload={"cargoquery": [{"row": {}}]})
    now = time.time()
    assert wiki.fetch_wikitext(
        cache.PullContext(str(cached), session=no_wikitext, cutoff=now), "Ana") == "{{Infobox}}"
    assert wiki.cargo_query(
        cache.PullContext(str(cached), session=no_title, cutoff=now), "Abilities",
        ("a",)) == [{"a": "1"}]
    with pytest.raises(wiki.WikiError, match="no wikitext"):
        wiki.fetch_wikitext(cache.PullContext(str(empty), session=no_wikitext, cutoff=now), "Ana")
    with pytest.raises(wiki.WikiError, match="a row has no title"):
        wiki.cargo_query(
            cache.PullContext(str(empty), session=no_title, cutoff=now), "Abilities", ("a",))


CARGO_PAGE = {"cargoquery": [{"title": {"a": "1"}}]}


def test_the_wiki_retries_a_429_and_reads_the_next_answer(tmp_path, instant_wiki):
    session = FakeSession(answers=[FakeResponse(status=429), FakeResponse(payload=CARGO_PAGE)])
    pull = cache.PullContext(str(tmp_path), session=session)
    assert wiki.cargo_query(pull, "T", ["a"]) == [{"a": "1"}]
    assert session.calls == 2


def test_a_rate_limit_stated_in_the_body_is_retried(tmp_path, instant_wiki):
    limited = FakeResponse(payload={"error": {"info": "Rate limit exceeded"}})
    session = FakeSession(answers=[limited, FakeResponse(payload=CARGO_PAGE)])
    pull = cache.PullContext(str(tmp_path), session=session)
    assert wiki.cargo_query(pull, "T", ["a"]) == [{"a": "1"}]
    assert session.calls == 2


def test_an_article_that_fails_is_asked_for_once(tmp_path, instant_wiki):
    session = FakeSession(fail=True)
    with pytest.raises(cache.FetchError):
        wiki.fetch_wikitext(cache.PullContext(str(tmp_path), session=session), "Ana")
    assert session.calls == 1


def test_an_article_that_will_not_fetch_is_recorded_and_the_rest_are_read(tmp_path, instant_wiki):
    # the title goes to the cache as it is: its name folds spaces and punctuation
    (tmp_path / "King_s_Row.wikitext").write_text("{{Infobox map}}", encoding="utf-8")
    session, logged = FakeSession(fail=True), []
    pull = cache.PullContext(str(tmp_path), session=session, log=logged.append)
    articles = wiki.fetch_articles(pull, ["King's Row", "Hanaoka"])
    assert articles.found == {"King's Row": "{{Infobox map}}"}
    [line] = articles.missing
    assert line.startswith("Hanaoka: ") and "source down" in line
    assert session.calls == 1                       # the uncached one, asked for once
    assert logged == ["  %-22s %s" % ("Hanaoka", line[len("Hanaoka: "):])]
