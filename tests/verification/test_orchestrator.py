"""orchestrator.py's verbs with docker and the network stubbed out: the
dispatch, a command past its timeout, and each verb's calls - up, status
and down. The verdict is tests/verification/test_orchestrator_verdict.py's, the HTTP
helpers test_orchestrator_http.py's."""

import pytest

import orchestrator
from tests.verification import healthy


def test_no_verb_means_up_and_a_bad_verb_prints_the_usage(monkeypatch, capsys):
    seen = []
    monkeypatch.setattr(orchestrator, "up", lambda: seen.append("up") or 0)
    monkeypatch.setattr(orchestrator, "status", lambda: seen.append("status") or 0)
    assert orchestrator.main([]) == 0 and orchestrator.main(["status"]) == 0
    assert seen == ["up", "status"]
    assert orchestrator.main(["dance"]) == 2
    assert "python orchestrator.py status" in capsys.readouterr().err


def test_sh_gives_up_on_a_command_past_its_timeout(monkeypatch):
    import subprocess
    given = []

    def overrun(argv, timeout=None):
        given.append(timeout)
        raise subprocess.TimeoutExpired(argv, timeout)
    monkeypatch.setattr(subprocess, "run", overrun)
    with pytest.raises(SystemExit, match="compose build data did not finish within 30 minutes"):
        orchestrator.sh("docker", "compose", "build", "data", timeout=30 * orchestrator.MINUTE)
    assert given == [1800]


# --- the verbs, with docker and the network stubbed out --------------------------------

@pytest.fixture()
def stubbed(monkeypatch, tmp_path):
    """Every side effect of the orchestrator recorded instead of run, in a
    checkout of its own: up() makes backups/ there, not in the repo."""
    calls = []
    monkeypatch.setattr(orchestrator, "ROOT", str(tmp_path))
    replies = healthy()
    # every command is given a timeout: a call without one raises TypeError here
    monkeypatch.setattr(orchestrator, "sh", lambda *a, timeout: calls.append(("sh", *a)) or "")
    monkeypatch.setattr(orchestrator, "wait_for", lambda url, s, what: calls.append(("wait", what)))
    monkeypatch.setattr(orchestrator, "health", lambda: replies)
    monkeypatch.setattr(orchestrator, "playbook_problem", lambda: None)
    return calls, replies


def test_up_builds_starts_waits_and_reports(stubbed, capsys):
    calls, _ = stubbed
    assert orchestrator.up() == 0
    assert ("sh", "docker", "compose", "build", "data") in calls
    assert ("wait", "the board") in calls
    assert "READY" in capsys.readouterr().out


def test_up_makes_the_backups_folder_before_the_containers_start(stubbed, monkeypatch, tmp_path):
    """Left to Docker, a Linux host makes the bind mount root's and the
    nightly dump cannot write it; a second up keeps what the folder holds."""
    folder = tmp_path / orchestrator.BACKUPS
    seen = []
    monkeypatch.setattr(orchestrator, "sh", lambda *a, timeout: seen.append(
        (a[:3], folder.is_dir())))
    assert orchestrator.up() == 0
    assert (("docker", "compose", "up"), True) in seen
    (folder / "countrix-2026-09-27.dump").write_text("kept")
    assert orchestrator.up() == 0
    assert (folder / "countrix-2026-09-27.dump").read_text() == "kept"


def test_up_stops_before_the_containers_on_a_playbook_that_does_not_load(
        stubbed, monkeypatch, tmp_path, capsys):
    """The data container refuses a rebuild over such a playbook and restarts
    until it loads, so up() says so first instead of waiting on it."""
    calls, _ = stubbed
    monkeypatch.undo()
    monkeypatch.setenv("COUNTRIX_STRATEGIES", str(tmp_path))       # a folder with no strategies
    monkeypatch.setattr(orchestrator, "sh", lambda *a, timeout: calls.append(a))
    assert orchestrator.playbook_problem().startswith("no strategies in")
    assert orchestrator.up() == 1 and calls == []
    assert "playbook: no strategies in" in capsys.readouterr().out
    monkeypatch.delenv("COUNTRIX_STRATEGIES")
    monkeypatch.setattr(orchestrator, "dotenv", dict)
    assert orchestrator.playbook_problem() is None              # the shipped playbook loads


def test_up_and_status_report_pending_drafts_and_leave_them_for_strategy(stubbed, capsys):
    """A draft waits for /strategy: up counts it and starts nothing beyond
    the stack, and status touches nothing at all."""
    calls, replies = stubbed
    replies["inference"]["pending"] = 2
    assert orchestrator.up() == 0
    assert [c[:3] for c in calls if c[0] == "sh"] == [
        ("sh", "docker", "compose"), ("sh", "docker", "compose")]
    assert "2 draft(s) awaiting /strategy" in capsys.readouterr().out
    calls.clear()
    assert orchestrator.status() == 0
    assert calls == []
    assert "2 draft(s) awaiting /strategy" in capsys.readouterr().out


def test_down_and_main_dispatch(stubbed, capsys):
    calls, _ = stubbed
    assert orchestrator.down() == 0 and ("sh", "docker", "compose", "down") in calls
    assert orchestrator.main(["up", "status"]) == 2
    assert "python orchestrator.py up" in capsys.readouterr().err
