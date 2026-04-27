"""Tests for CSRF middleware coverage on non-/api routes.

Verifies that CSRFMiddleware enforces CSRF protection on all
state-changing routes (not just /api/*), while exempting explicitly
listed paths.
"""

from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.core.middleware import CSRFMiddleware


def _ok_handler(request: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


def _build_app() -> Starlette:
    """Minimal Starlette app with CSRF middleware and test routes."""
    app = Starlette(
        routes=[
            Route("/api/test", _ok_handler, methods=["POST", "GET"]),
            Route("/auth/logout", _ok_handler, methods=["POST"]),
            Route("/auth/callback", _ok_handler, methods=["POST", "GET"]),
            Route("/auth/login", _ok_handler, methods=["GET"]),
            Route("/health", _ok_handler, methods=["GET"]),
            Route("/other/action", _ok_handler, methods=["POST"]),
        ],
    )
    app.add_middleware(CSRFMiddleware)
    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_build_app(), raise_server_exceptions=False)


class TestCSRFCoversNonApiRoutes:
    """CSRF must be enforced on all POST/PUT/PATCH/DELETE routes."""

    def test_post_auth_logout_rejected_without_csrf(self, client: TestClient) -> None:
        resp = client.post("/auth/logout")
        assert resp.status_code == 403
        assert "CSRF" in resp.json()["error"]

    def test_post_other_action_rejected_without_csrf(self, client: TestClient) -> None:
        resp = client.post("/other/action")
        assert resp.status_code == 403

    def test_post_api_route_rejected_without_csrf(self, client: TestClient) -> None:
        resp = client.post("/api/test")
        assert resp.status_code == 403

    def test_post_with_valid_csrf_succeeds(self, client: TestClient) -> None:
        # GET to obtain the CSRF cookie
        get_resp = client.get("/api/test")
        token = get_resp.cookies.get("csrf_token")
        assert token is not None

        client.cookies.set("csrf_token", token)
        resp = client.post(
            "/auth/logout",
            headers={"X-CSRF-Token": token},
        )
        assert resp.status_code == 200

    def test_post_with_mismatched_csrf_rejected(self, client: TestClient) -> None:
        get_resp = client.get("/api/test")
        token = get_resp.cookies.get("csrf_token")

        client.cookies.set("csrf_token", token)
        resp = client.post(
            "/auth/logout",
            headers={"X-CSRF-Token": "wrong-token"},
        )
        assert resp.status_code == 403
        assert "mismatch" in resp.json()["detail"]


class TestCSRFExemptPaths:
    """Exempt paths should bypass CSRF even for state-changing methods."""

    def test_auth_callback_post_allowed_without_csrf(self, client: TestClient) -> None:
        resp = client.post("/auth/callback")
        assert resp.status_code == 200

    def test_health_get_allowed(self, client: TestClient) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200


class TestCSRFSafeMethodsAllowed:
    """GET/HEAD/OPTIONS should not require CSRF tokens."""

    def test_get_non_api_route_allowed(self, client: TestClient) -> None:
        resp = client.get("/auth/login")
        assert resp.status_code == 200

    def test_get_api_route_allowed(self, client: TestClient) -> None:
        resp = client.get("/api/test")
        assert resp.status_code == 200
