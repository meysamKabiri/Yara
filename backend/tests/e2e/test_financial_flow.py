from collections.abc import Callable

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.anyio


async def test_financial_natural_input_returns_interpretation_job(
    client: AsyncClient,
    signup: Callable,
    create_project: Callable,
) -> None:
    user = await signup("financial-flow@example.com")
    project = await create_project(user["headers"], "جریان مالی")

    response = await client.post(
        f"/projects/{project['id']}/natural-input",
        json={
            "text": "وحید 500 میلیون ریخت به حساب",
            "idempotency_key": "financial-critical-path",
        },
        headers=user["headers"],
    )

    assert response.status_code == 202
    body = response.json()
    assert body["job_id"]
    assert body["status"] in {"PENDING", "DONE"}
    assert body["trace_id"]
