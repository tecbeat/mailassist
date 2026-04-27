"""Tests for RequestSizeLimitMiddleware.

Verifies that oversized request bodies are rejected with 413, both when
Content-Length is present and when the body is chunked (no Content-Length).
"""

from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.core.middleware import RequestSizeLimitMiddleware, _MAX_REQUEST_BODY_BYTES


async def _echo_handler(request: Request) -> JSONResponse:
    body = await request.body()
    return JSONResponse({"size": len(body)})


def _build_app() -> Starlette:
    app = Starlette(
        routes=[
            Route("/upload", _echo_handler, methods=["POST"]),
        ],
    )
    app.add_middleware(RequestSizeLimitMiddleware)
    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_build_app(), raise_server_exceptions=False)


class TestContentLengthPresent:
    """Requests that declare Content-Length up front."""

    def test_small_body_allowed(self, client: TestClient) -> None:
        resp = client.post("/upload", content=b"hello")
        assert resp.status_code == 200
        assert resp.json()["size"] == 5

    def test_exact_limit_allowed(self, client: TestClient) -> None:
        body = b"x" * _MAX_REQUEST_BODY_BYTES
        resp = client.post("/upload", content=body)
        assert resp.status_code == 200

    def test_over_limit_rejected(self, client: TestClient) -> None:
        body = b"x" * (_MAX_REQUEST_BODY_BYTES + 1)
        resp = client.post("/upload", content=body)
        assert resp.status_code == 413
        assert "too large" in resp.json()["error"]


class TestChunkedBody:
    """Requests without Content-Length (chunked/streaming)."""

    def test_small_chunked_body_allowed(self, client: TestClient) -> None:
        def gen():
            yield b"hello"

        resp = client.post("/upload", content=gen())
        assert resp.status_code == 200
        assert resp.json()["size"] == 5

    def test_chunked_body_over_limit_rejected(self, client: TestClient) -> None:
        """Body exceeding the limit should be rejected before full buffering."""
        chunk_size = 64 * 1024  # 64 KB chunks
        total = _MAX_REQUEST_BODY_BYTES + chunk_size

        def gen():
            sent = 0
            while sent < total:
                size = min(chunk_size, total - sent)
                yield b"x" * size
                sent += size

        resp = client.post("/upload", content=gen())
        assert resp.status_code == 413
        assert "too large" in resp.json()["error"]

    def test_chunked_body_at_limit_allowed(self, client: TestClient) -> None:
        """Body exactly at the limit should pass."""

        def gen():
            yield b"x" * _MAX_REQUEST_BODY_BYTES

        resp = client.post("/upload", content=gen())
        assert resp.status_code == 200


class TestGetRequestsIgnored:
    """GET requests should not be subject to body size checks."""

    def test_get_request_passes_through(self, client: TestClient) -> None:
        resp = client.get("/upload")
        # Route only accepts POST, so expect 405 — not 413
        assert resp.status_code == 405
