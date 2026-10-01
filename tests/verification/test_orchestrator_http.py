"""orchestrator.py's helpers over the network and the host: the .env file,
a reply read off a dead endpoint, and a wait that gives up. urllib is not
stubbed: nothing listens on port 9."""

import pytest

import orchestrator


def test_dotenv_and_the_http_helpers(tmp_path, monkeypatch):
    monkeypatch.setattr(orchestrator, "ROOT", str(tmp_path))
    assert orchestrator.dotenv() == {}
    (tmp_path / ".env").write_text("# a comment\nCOUNTRIX_STRATEGIES='tests/x'\nX=1\n")
    assert orchestrator.dotenv() == {"COUNTRIX_STRATEGIES": "tests/x", "X": "1"}
    (tmp_path / ".env").unlink()
    (tmp_path / ".env").mkdir()                   # there, and unreadable: said, not skipped
    with pytest.raises(IsADirectoryError):
        orchestrator.dotenv()
    # get_json swallows a dead endpoint; wait_for gives up loudly
    assert orchestrator.get_json("http://127.0.0.1:9/never", timeout=1) is None
    monkeypatch.setattr(orchestrator.time, "sleep", lambda s: None)
    with pytest.raises(SystemExit):
        orchestrator.wait_for("http://127.0.0.1:9/never", 0, "nothing")
