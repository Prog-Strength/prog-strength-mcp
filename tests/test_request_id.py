"""Tests for the per-request correlation id wiring.

Covers the request_id module's primitives (id format, ContextVar, log
filter) and its end-to-end behavior through the FastMCP HTTP app: every
response carries the X-Request-ID header and /health echoes it in the
body. An inbound X-Request-ID is honored so a trace can span the
agent → MCP → API hops.
"""

from __future__ import annotations

import logging
import re

import pytest
from starlette.middleware import Middleware
from starlette.testclient import TestClient

from prog_strength_mcp.request_id import (
    HEADER_NAME,
    RequestIDLogFilter,
    RequestIDMiddleware,
    _request_id,
    current_request_id,
    new_request_id,
)
from prog_strength_mcp.server import mcp
from prog_strength_mcp.version import SERVICE

_HEX32 = re.compile(r"\A[0-9a-f]{32}\Z")


@pytest.fixture
def client() -> TestClient:
    app = mcp.http_app(transport="http", middleware=[Middleware(RequestIDMiddleware)])
    return TestClient(app)


# --- module primitives ----------------------------------------------------


def test_new_request_id_is_32_char_hex():
    """Matches the Go API's id.New shape (16 random bytes hex-encoded),
    not a dashed uuid4."""
    rid = new_request_id()
    assert _HEX32.match(rid), rid


def test_new_request_id_is_unique():
    assert new_request_id() != new_request_id()


def test_current_request_id_defaults_empty_outside_request():
    assert current_request_id() == ""


def test_log_filter_stamps_current_id():
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "msg", None, None)
    token = _request_id.set("abc123")
    try:
        assert RequestIDLogFilter().filter(record) is True
        assert record.request_id == "abc123"
    finally:
        _request_id.reset(token)


def test_log_filter_stamps_dash_when_no_context():
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "msg", None, None)
    assert RequestIDLogFilter().filter(record) is True
    assert record.request_id == "-"


# --- end-to-end through the app -------------------------------------------


def test_health_response_header_present_and_hex(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    rid = resp.headers[HEADER_NAME]
    assert _HEX32.match(rid), rid


def test_health_body_request_id_matches_header(client):
    resp = client.get("/health")
    body = resp.json()
    assert body["service"] == SERVICE
    assert body["message"] == "service is healthy"
    # Body id and header id are the same minted value.
    assert body["request_id"] == resp.headers[HEADER_NAME]
    assert _HEX32.match(body["request_id"])


def test_each_request_gets_a_distinct_id(client):
    first = client.get("/health").json()["request_id"]
    second = client.get("/health").json()["request_id"]
    assert first != second


def test_inbound_request_id_is_honored(client):
    """A caller-supplied X-Request-ID rides through so a trace can span
    the agent → MCP → API hops."""
    supplied = "deadbeefdeadbeefdeadbeefdeadbeef"
    resp = client.get("/health", headers={HEADER_NAME: supplied})
    assert resp.headers[HEADER_NAME] == supplied
    assert resp.json()["request_id"] == supplied


def test_unknown_route_still_carries_request_id_header(client):
    """Even a 404 gets the correlation header so failed probes are
    traceable."""
    resp = client.get("/no-such-route")
    assert resp.status_code == 404
    assert _HEX32.match(resp.headers[HEADER_NAME])
