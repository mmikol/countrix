"""The one client that calls the MCP door over HTTP: a tools/call read into
a CallReply - the tool's answer, its refusal, and the door turning the call
away, with the status the relay map gives each - and the door's answer read
field by field."""

import email.message
import io
import json
import urllib.error
import urllib.request

import pytest

from door.mcp import client
from tests.db.test_web import _Answered, _door


def test_call_tool_reads_the_answer_the_refusal_and_the_door_turning_it_away():
    httpd, url = _door()
    assert client.call_tool(url, "hello", {}) == client.CallReply(
        "hello\nsecond line", {"said": "hello"}, 200)
    assert client.call_tool(url, "refuse", {}) == client.CallReply("no strategy 'x'", None, 400)
    httpd.shutdown()
    httpd, url = _door(token="s3cret")
    # the token the door refused is the relay's own, not its caller's: 502
    assert client.call_tool(url, "hello", {}) == client.CallReply(
        "the MCP server answered 401: a bearer token is required", None, 502)
    assert client.call_tool(url, "hello", {}, token="s3cret").text == "hello\nsecond line"
    httpd.shutdown()
    nobody = client.call_tool("http://127.0.0.1:9/mcp", "hello", {}, timeout=5)
    assert nobody.status == 502 and nobody.is_error and "unreachable" in nobody.text
    with pytest.raises(ValueError, match="http or https"):
        client.call_tool("file:///etc/passwd", "hello", {})


def test_the_doors_rate_limit_passes_through_and_its_other_refusals_are_502(monkeypatch):
    """The door's 429 is relayed as it came; a body too large (413), and a
    200 that is not JSON-RPC, are the door failing the call: 502."""
    def refusing(code, reason):
        def urlopen(request, timeout):
            raise urllib.error.HTTPError(request.full_url, code, "x", email.message.Message(),
                                         io.BytesIO(json.dumps({"error": reason}).encode()))
        return urlopen
    for code, reason in ((429, "too many calls; try again in a minute"),
                         (413, "request too large")):
        monkeypatch.setattr(urllib.request, "urlopen", refusing(code, reason))
        assert client.call_tool("http://door/mcp", "hello", {}) == client.CallReply(
            "the MCP server answered %d: %s" % (code, reason), None, 429 if code == 429 else 502)
    monkeypatch.setattr(urllib.request, "urlopen", lambda request, timeout: _Answered(b"<html>"))
    assert client.call_tool("http://door/mcp", "hello", {}) == client.CallReply(
        "the MCP server answered with no JSON-RPC response", None, 502)


def test_a_tools_call_response_is_read_field_by_field():
    """The client reads each field of the door's answer for its type: a
    response with no result says nothing and is no error, content that is not
    a list and a payload that is not an object read as none, and content
    items that are not text are left out. The tool's refusal is 400; a
    JSON-RPC error, or no response, is the door failing: 502."""
    nothing = client.CallReply("", None, 200)
    assert client._answer({"jsonrpc": "2.0", "id": 1}) == nothing
    assert client._answer({"jsonrpc": "2.0", "id": 1, "result": [1]}) == nothing
    assert client._answer({"result": {"content": 5, "structuredContent": [1]}}) == nothing
    items = [{"type": "image"}, {"type": "text", "text": "a"}, "b", {"type": "text", "text": "c"}]
    assert client._answer({"result": {"content": items, "isError": True}}) == client.CallReply(
        "a\nc", None, 400)
    assert client._answer({"error": {"code": -32602, "message": "no tool named 'x'"}}) == (
        client.CallReply("no tool named 'x'", None, 502))
    assert client._answer([]) == client.CallReply(
        "the MCP server answered with no JSON-RPC response", None, 502)
    assert not nothing.is_error and client._answer([]).is_error
