from collections.abc import Callable

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.anyio


async def test_natural_input_requires_jwt(
    client: AsyncClient,
    signup: Callable,
    create_project: Callable,
) -> None:
    user = await signup("natural-auth@example.com")
    project = await create_project(user["headers"], "احراز هویت ورودی")

    missing_token = await client.post(
        f"/projects/{project['id']}/natural-input",
        json={"text": "وحید 500 میلیون ریخت به حساب"},
    )
    invalid_token = await client.post(
        f"/projects/{project['id']}/natural-input",
        json={"text": "وحید 500 میلیون ریخت به حساب"},
        headers={"Authorization": "Bearer invalid-token"},
    )

    assert missing_token.status_code == 401
    assert invalid_token.status_code == 401


async def test_natural_input_job_status_is_readable_by_owner(
    client: AsyncClient,
    signup: Callable,
    create_project: Callable,
) -> None:
    user = await signup("natural-status@example.com")
    project = await create_project(user["headers"], "وضعیت پردازش")
    submitted = await client.post(
        f"/projects/{project['id']}/natural-input",
        json={
            "text": "وحید 500 میلیون ریخت به حساب",
            "idempotency_key": "status-critical-path",
        },
        headers=user["headers"],
    )
    assert submitted.status_code == 202

    status = await client.get(
        f"/natural-input-jobs/{submitted.json()['job_id']}",
        headers=user["headers"],
    )

    assert status.status_code == 200
    assert status.json()["status"] in {"PENDING", "DONE"}
