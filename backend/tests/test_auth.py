"""Tests for authentication endpoints."""

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from app.config import settings
from app.core.auth.router import _set_session_cookies
from app.main import app
from app.version import VERSION


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient) -> None:
    """Test health check endpoint."""
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "version": VERSION}


_SETUP_PAYLOAD = {
    "admin_first_name": "Admin",
    "admin_last_name": "User",
    "admin_email": "admin@example.com",
    "admin_password": "SecurePass123",
    "clinic_name": "My Clinic",
    "clinic_tax_id": "B12345678",
}
_SETUP_HEADERS = {"X-DentalPin-Setup-Token": settings.SETUP_TOKEN}


@pytest.mark.asyncio
async def test_setup_status(client: AsyncClient) -> None:
    """setup/status flips to initialized once the first account exists."""
    before = await client.get("/api/v1/auth/setup/status")
    assert before.status_code == 200
    assert before.json()["data"]["initialized"] is False

    response = await client.post("/api/v1/auth/setup", json=_SETUP_PAYLOAD, headers=_SETUP_HEADERS)
    assert response.status_code == 201

    after = await client.get("/api/v1/auth/setup/status")
    assert after.json()["data"]["initialized"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("headers", [{}, {"X-DentalPin-Setup-Token": "wrong-token"}])
async def test_setup_requires_operator_token(
    client: AsyncClient,
    headers: dict[str, str],
) -> None:
    """A network client cannot claim an uninitialized deployment without its secret."""
    response = await client.post("/api/v1/auth/setup", json=_SETUP_PAYLOAD, headers=headers)
    assert response.status_code == 403
    assert response.json()["message"] == "Invalid setup token"
    assert response.json()["errors"] == ["Invalid setup token"]


@pytest.mark.asyncio
async def test_setup_fails_closed_when_token_is_not_configured(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing or weak server configuration must disable the claim endpoint."""
    monkeypatch.setattr(settings, "SETUP_TOKEN", "")
    response = await client.post(
        "/api/v1/auth/setup",
        json=_SETUP_PAYLOAD,
        headers=_SETUP_HEADERS,
    )
    assert response.status_code == 503
    assert "SETUP_TOKEN" in response.json()["message"]


@pytest.mark.asyncio
async def test_setup_claim_is_serialized_across_requests(db_session: AsyncSession) -> None:
    """Two valid simultaneous claims create exactly one initial administrator."""
    del db_session  # The fixture creates and retains the disposable test schema.
    transport = ASGITransport(app=app)
    async with (
        AsyncClient(transport=transport, base_url="http://test") as first_client,
        AsyncClient(transport=transport, base_url="http://test") as second_client,
    ):
        first, second = await asyncio.gather(
            first_client.post(
                "/api/v1/auth/setup",
                json=_SETUP_PAYLOAD,
                headers=_SETUP_HEADERS,
            ),
            second_client.post(
                "/api/v1/auth/setup",
                json={**_SETUP_PAYLOAD, "admin_email": "second@example.com"},
                headers=_SETUP_HEADERS,
            ),
        )

    assert sorted((first.status_code, second.status_code)) == [201, 409]


@pytest.mark.asyncio
async def test_setup_creates_admin_and_clinic(client: AsyncClient) -> None:
    """First-run setup returns a working admin token tied to a new clinic."""
    response = await client.post("/api/v1/auth/setup", json=_SETUP_PAYLOAD, headers=_SETUP_HEADERS)
    assert response.status_code == 201
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" not in data
    assert data["token_type"] == "bearer"
    assert client.cookies.get("dentalpin_refresh")
    assert client.cookies.get("dentalpin_csrf")

    me = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {data['access_token']}"},
    )
    assert me.status_code == 200
    body = me.json()["data"]
    assert body["user"]["email"] == "admin@example.com"
    assert body["clinics"][0]["name"] == "My Clinic"
    assert body["clinics"][0]["role"] == "admin"


@pytest.mark.asyncio
async def test_setup_rejected_when_initialized(client: AsyncClient) -> None:
    """Once the system has an account, setup is closed (409)."""
    first = await client.post("/api/v1/auth/setup", json=_SETUP_PAYLOAD, headers=_SETUP_HEADERS)
    assert first.status_code == 201

    second = await client.post(
        "/api/v1/auth/setup",
        json={**_SETUP_PAYLOAD, "admin_email": "other@example.com"},
        headers=_SETUP_HEADERS,
    )
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_setup_weak_password(client: AsyncClient) -> None:
    """Weak admin passwords are rejected."""
    response = await client.post(
        "/api/v1/auth/setup",
        json={**_SETUP_PAYLOAD, "admin_password": "weak"},
        headers=_SETUP_HEADERS,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_login(client: AsyncClient) -> None:
    """Test user login after first-run setup."""
    await client.post("/api/v1/auth/setup", json=_SETUP_PAYLOAD, headers=_SETUP_HEADERS)

    response = await client.post(
        "/api/v1/auth/login",
        data={"username": "admin@example.com", "password": "SecurePass123"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" not in data
    assert client.cookies.get("dentalpin_refresh")
    assert client.cookies.get("dentalpin_csrf")


@pytest.mark.asyncio
async def test_refresh_uses_httponly_cookie_and_csrf_header(client: AsyncClient) -> None:
    """Refresh credentials never enter JSON and require the double-submit nonce."""
    await client.post("/api/v1/auth/setup", json=_SETUP_PAYLOAD, headers=_SETUP_HEADERS)
    csrf_token = client.cookies.get("dentalpin_csrf")
    assert csrf_token

    missing_csrf = await client.post("/api/v1/auth/refresh")
    assert missing_csrf.status_code == 403

    wrong_csrf = await client.post(
        "/api/v1/auth/refresh",
        headers={"X-DentalPin-CSRF-Token": "wrong-token"},
    )
    assert wrong_csrf.status_code == 403

    refreshed = await client.post(
        "/api/v1/auth/refresh",
        headers={"X-DentalPin-CSRF-Token": csrf_token},
    )
    assert refreshed.status_code == 200
    assert "access_token" in refreshed.json()
    assert "refresh_token" not in refreshed.json()
    assert refreshed.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_refresh_rejects_missing_session_cookie(client: AsyncClient) -> None:
    """A CSRF nonce alone is not a refresh credential."""
    response = await client.post(
        "/api/v1/auth/refresh",
        headers={"X-DentalPin-CSRF-Token": "orphan-nonce"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_logout_clears_session_cookies(client: AsyncClient) -> None:
    """Logout expires both browser session cookies after CSRF validation."""
    await client.post("/api/v1/auth/setup", json=_SETUP_PAYLOAD, headers=_SETUP_HEADERS)
    csrf_token = client.cookies.get("dentalpin_csrf")
    assert csrf_token

    response = await client.post(
        "/api/v1/auth/logout",
        headers={"X-DentalPin-CSRF-Token": csrf_token},
    )
    assert response.status_code == 204
    assert client.cookies.get("dentalpin_refresh") is None
    assert client.cookies.get("dentalpin_csrf") is None


def test_production_session_cookie_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    """The long-lived credential is Secure, HttpOnly, and SameSite=Strict."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    response = Response()
    _set_session_cookies(response, "refresh-secret", csrf_token="csrf-nonce")
    cookies = response.headers.getlist("set-cookie")
    refresh_cookie = next(item for item in cookies if item.startswith("dentalpin_refresh="))
    csrf_cookie = next(item for item in cookies if item.startswith("dentalpin_csrf="))

    assert "HttpOnly" in refresh_cookie
    assert "Secure" in refresh_cookie
    assert "SameSite=strict" in refresh_cookie
    assert "HttpOnly" not in csrf_cookie
    assert "Secure" in csrf_cookie
    assert "SameSite=strict" in csrf_cookie


@pytest.mark.asyncio
async def test_login_invalid_credentials(client: AsyncClient) -> None:
    """Test login with invalid credentials."""
    response = await client.post(
        "/api/v1/auth/login",
        data={"username": "nonexistent@example.com", "password": "wrongpass"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_endpoint(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    """Test /me endpoint returns current user wrapped in ApiResponse."""
    response = await client.get("/api/v1/auth/me", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    # Response is wrapped in ApiResponse: {data: {user, clinics, permissions}, message}
    assert data["data"]["user"]["email"] == "test@example.com"
    assert data["data"]["user"]["first_name"] == "Test"
    assert "message" in data  # message field is present (may be null)


@pytest.mark.asyncio
async def test_me_without_auth(client: AsyncClient) -> None:
    """Test /me endpoint requires authentication."""
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401
