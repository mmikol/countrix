"""The one client that calls the MCP door over HTTP: call_tool(), a
tools/call posted to the door's Streamable HTTP transport and read into a
CallReply, with the status db.web's relay map gives it - the tool's answer
200, its refusal 400, the door's 429 as it came, and 502 for the door
turning the call away otherwise, failing, or not answering. Stdlib only,
besides db.web's reader, so the board and orchestrator.py call the door
without loading a tool family.
"""

import json
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

from db.web import JsonAnswer, read_json


@dataclass(frozen=True)
class CallReply:
    """What a tools/call over HTTP came back with: the tool's text (or why
    there is none), its structured payload, and the status a relay answers
    it with by db.web's relay map - 200 for the tool's answer, 400 for its
    refusal, 429 for the door's rate limit, 502 for the door turning the
    call away otherwise, failing, or not answering."""
    text: str
    structured: dict[str, object] | None
    status: int

    @property
    def is_error(self) -> bool:
        """Whether this is anything but the tool's answer."""
        return self.status != 200


def _refused_by_door(answer: JsonAnswer) -> CallReply:
    """The door's error status, in its own words where its body gives them:
    its error, or that error's message when it is a JSON-RPC error object.
    Its 429 passes through; any other is 502."""
    status = 429 if answer.status == 429 else 502
    said = answer.body.get("error") if isinstance(answer.body, dict) else None
    if isinstance(said, dict):                       # a JSON-RPC error object
        said = said.get("message")
    if not said:
        return CallReply("the MCP server answered %d" % answer.status, None, status)
    return CallReply("the MCP server answered %d: %s" % (answer.status, said), None, status)


def _answer(reply: object) -> CallReply:
    """A JSON-RPC response to tools/call, read: its error's message, or its
    result. No response, or an error object, is the door failing: 502."""
    if not isinstance(reply, dict):
        return CallReply("the MCP server answered with no JSON-RPC response", None, 502)
    if "error" in reply:
        error = reply["error"]
        said = error.get("message", error) if isinstance(error, dict) else error
        return CallReply(str(said), None, 502)
    return _tool_result(reply.get("result"))


def _tool_result(result: object) -> CallReply:
    """A tools/call result as the door sends it (door.mcp.server.ToolResult),
    read off the wire into the record a caller gets: the text items of its
    content joined by newlines, its structured payload, and 400 when it is
    the tool's refusal, 200 otherwise. A result that is not an object says
    nothing and is no error, and content or a payload that is not what the
    door sends reads as none."""
    if not isinstance(result, dict):
        return CallReply("", None, 200)
    content = result.get("content")
    items = content if isinstance(content, list) else []
    text = "\n".join(
        str(c.get("text", "")) for c in items if isinstance(c, dict) and c.get("type") == "text")
    structured = result.get("structuredContent")
    payload = structured if isinstance(structured, dict) else None
    return CallReply(text, payload, 400 if result.get("isError") else 200)


def call_tool(
        url: str, name: str, arguments: Mapping[str, object], token: str | None = None,
        timeout: float = 60) -> CallReply:
    """One tools/call on the MCP server at `url`, with the bearer token when
    one is given: a 200 is read as the JSON-RPC response, any other status
    as the door turning the call away. A URL that is not http or https is a
    ValueError: urlopen would read a file: URL as a path."""
    if urlsplit(url).scheme not in ("http", "https"):
        raise ValueError("the MCP server's URL must be http or https, got %r" % url)
    body = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": dict(arguments)}})
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(url, data=body.encode("utf-8"), headers=headers)
    try:
        answer = read_json(request, timeout)
    except OSError as error:
        return CallReply("the MCP server is unreachable: %s" % error, None, 502)
    if answer.status == 200:
        return _answer(answer.body)
    return _refused_by_door(answer)
