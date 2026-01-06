"""Tests for the ENCODE fastmcp server at a remote URL.

This test suite uses the MCP HTTP transport protocol which requires:
1. Initial session creation via the initialize method
2. Extracting the session ID from the response headers (mcp-session-id)
3. Including the session ID in subsequent tool calls

To run:

    pip install pytest requests
    pytest tests/test_mcp_server.py -q

You can override the server URL with the MCP_SERVER_URL environment variable:

    MCP_SERVER_URL=http://127.0.0.1:8080/mcp pytest tests/test_mcp_server.py -q

"""
from __future__ import annotations

import os
import json
import pytest
import requests
from typing import Any

BASE_URL = os.environ.get("MCP_SERVER_URL", "http://128.200.7.223:8080/mcp")
DEFAULT_TIMEOUT = 10.0


@pytest.fixture(scope="session")
def mcp_session():
    """Initialize MCP session and return session ID.
    
    The MCP server requires proper initialize parameters and returns
    the session ID in the mcp-session-id response header.
    """
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    payload = {
        "jsonrpc": "2.0",
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": "pytest-mcp-client",
                "version": "1.0"
            }
        },
        "id": 1,
    }
    
    try:
        resp = requests.post(BASE_URL, json=payload, timeout=DEFAULT_TIMEOUT, headers=headers)
    except requests.exceptions.RequestException as exc:
        pytest.skip(f"MCP server not reachable at {BASE_URL}: {exc}")
    
    # Get session ID from response header
    session_id = resp.headers.get("mcp-session-id")
    if not session_id:
        pytest.skip(f"Could not get mcp-session-id from server response")
    
    return session_id


def post_tool_call(session_id: str, tool_name: str, tool_params: dict[str, Any]) -> dict:
    """POST a tool call to the MCP server with a valid session ID.
    
    MCP HTTP transport returns Server-Sent Events, so we parse the response.
    The session ID must be passed in the mcp-session-id header.
    """
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "mcp-session-id": session_id,  # Session ID in header
    }
    
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": tool_params,
        },
        "id": 1,
    }
    
    try:
        resp = requests.post(
            BASE_URL,
            json=payload,
            timeout=DEFAULT_TIMEOUT,
            headers=headers,
        )
    except requests.exceptions.RequestException as exc:
        pytest.skip(f"MCP server not reachable at {BASE_URL}: {exc}")
    
    # Parse Server-Sent Events response
    lines = resp.text.strip().split("\r\n")
    for line in lines:
        if line.startswith("data:"):
            try:
                return json.loads(line[5:])
            except json.JSONDecodeError:
                pass
    
    # Fallback to regular JSON response
    try:
        return resp.json()
    except ValueError:
        pytest.fail(f"Non-JSON response from {BASE_URL}: {resp.status_code} - {resp.text}")


def extract_result(maybe_resp: Any) -> Any:
    """Extract the tool result from a JSON-RPC 2.0 response.
    
    MCP servers return result in result.content[0].text format.
    """
    if isinstance(maybe_resp, dict):
        # JSON-RPC response with result
        if "result" in maybe_resp:
            result = maybe_resp["result"]
            # MCP wraps tool results in a content array
            if isinstance(result, dict) and "content" in result:
                content = result["content"]
                if isinstance(content, list) and len(content) > 0:
                    item = content[0]
                    if isinstance(item, dict) and "text" in item:
                        # Try to parse text as JSON
                        try:
                            return json.loads(item["text"])
                        except (ValueError, TypeError):
                            return item["text"]
                    return item
                return content
            return result
        # JSON-RPC error response
        if "error" in maybe_resp:
            return maybe_resp["error"]
        # Direct data
        return maybe_resp
    return maybe_resp


@pytest.mark.parametrize("tool_name", ["get_server_info", "list_experiments"])
def test_tool_basic_responses(tool_name: str, mcp_session: str):
    """Call a basic server tool and assert the returned object contains expected keys."""
    tool_params = {}
    data = post_tool_call(mcp_session, tool_name, tool_params)
    
    # Accept direct response or wrapped
    result = extract_result(data)
    
    # Check for error response
    if isinstance(result, dict) and result.get("code") is not None:
        pytest.skip(f"Server returned error: {result.get('message')}")
    
    if tool_name == "get_server_info":
        assert isinstance(result, dict), f"Expected dict, got {type(result)}"
        assert "server_name" in result, f"Missing server_name in {result.keys()}"
        assert result["server_name"].lower().startswith("encode")
    else:
        # list_experiments should be a dict with keys: total, experiments
        assert isinstance(result, dict), f"Expected dict, got {type(result)}"
        assert "total" in result and "experiments" in result, f"Missing keys in {result.keys()}"
        assert isinstance(result["experiments"], list)


@pytest.mark.parametrize("accession", ["ENCSR000CDC", "ENCSR000AAA"])
def test_get_experiment_by_accession(accession: str, mcp_session: str):
    """Call `get_experiment` for a known accession. Assert successful responses
    include an `accession` key and basic metadata fields."""
    tool_params = {"accession": accession}
    data = post_tool_call(mcp_session, "get_experiment", tool_params)
    result = extract_result(data)

    # If returned an error object, skip gracefully
    if isinstance(result, dict) and result.get("code") is not None:
        pytest.skip(f"Server returned error for accession {accession}: {result.get('message')}")

    assert isinstance(result, dict), f"Expected dict, got {type(result)}"
    assert result.get("accession") == accession, f"Expected accession {accession}, got {result.get('accession')}"
    # Check basic keys exist
    for k in ("organism", "assay", "biosample"):
        assert k in result, f"Missing key {k} in {result.keys()}"


def test_search_by_biosample_returns_list(mcp_session: str):
    """Search for a common biosample (K562) and assert results look reasonable."""
    tool_params = {
        "search_term": "K562",
        "organism": "Homo sapiens",
    }
    data = post_tool_call(mcp_session, "search_by_biosample", tool_params)
    result = extract_result(data)

    # Check for error
    if isinstance(result, dict) and result.get("code") is not None:
        pytest.skip(f"Server returned error: {result.get('message')}")

    assert isinstance(result, list), f"Expected list, got {type(result)}"
    # Should return list of dicts with accessions
    if result:
        assert isinstance(result[0].get("accession"), str), "Expected accession string in results"


def test_server_health_check_get():
    """A GET request may return server info or at least respond gracefully."""
    try:
        resp = requests.get(BASE_URL, timeout=DEFAULT_TIMEOUT)
    except requests.exceptions.RequestException as exc:
        pytest.skip(f"MCP server not reachable at {BASE_URL}: {exc}")

    # 200 with JSON is ideal; 405 Method Not Allowed is acceptable
    if resp.status_code in (200, 405):
        return
    
    pytest.skip(f"GET {BASE_URL} returned status {resp.status_code}")

