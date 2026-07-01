from collections.abc import Callable

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.anyio


async def test_signup_login_and_me(
    client: AsyncClient,
    auth_headers: Callable[[str], dict[str, str]],
    user_payload: Callable[[str], dict[str, str]],
) -> None:
    payload = user_payload("auth-flow@example.com")

    signup = await client.post("/auth/signup", json=payload)
    assert signup.status_code == 201
    signup_body = signup.json()
    assert signup_body["access_token"]
    assert signup_body["user"]["email"] == payload["email"]

    login = await client.post("/auth/login", json=payload)
    assert login.status_code == 200
    login_body = login.json()
    assert login_body["access_token"]

    me = await client.get("/auth/me", headers=auth_headers(login_body["access_token"]))
    assert me.status_code == 200
    assert me.json()["email"] == payload["email"]


async def test_missing_token_returns_401(client: AsyncClient) -> None:
    response = await client.get("/projects")

    assert response.status_code == 401


async def test_invalid_token_returns_401(client: AsyncClient) -> None:
    response = await client.get("/projects", headers={"Authorization": "Bearer invalid-token"})

    assert response.status_code == 401
