from collections.abc import Callable

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.anyio


async def test_cross_user_project_access_is_forbidden(
    client: AsyncClient,
    signup: Callable,
    create_project: Callable,
) -> None:
    owner = await signup("isolation-owner@example.com")
    other = await signup("isolation-other@example.com")
    project = await create_project(owner["headers"], "پروژه خصوصی")

    response = await client.get(f"/projects/{project['id']}", headers=other["headers"])

    assert response.status_code == 403


async def test_cross_user_natural_input_access_is_forbidden(
    client: AsyncClient,
    signup: Callable,
    create_project: Callable,
) -> None:
    owner = await signup("natural-owner@example.com")
    other = await signup("natural-other@example.com")
    project = await create_project(owner["headers"], "پردازش خصوصی")

    response = await client.post(
        f"/projects/{project['id']}/natural-input",
        json={"text": "وحید 500 میلیون ریخت به حساب"},
        headers=other["headers"],
    )

    assert response.status_code == 403
