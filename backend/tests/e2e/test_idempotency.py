from collections.abc import Callable

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.anyio


async def test_duplicate_natural_input_reuses_existing_job(
    client: AsyncClient,
    signup: Callable,
    create_project: Callable,
) -> None:
    user = await signup("idempotency@example.com")
    project = await create_project(user["headers"], "تکرار مالی")
    payload = {
        "text": "وحید 500 میلیون ریخت به حساب",
        "idempotency_key": "same-natural-input",
    }

    first = await client.post(
        f"/projects/{project['id']}/natural-input",
        json=payload,
        headers=user["headers"],
    )
    second = await client.post(
        f"/projects/{project['id']}/natural-input",
        json=payload,
        headers=user["headers"],
    )

    assert first.status_code == 202
    assert second.status_code in {202, 409}
    if second.status_code == 202:
        assert second.json()["job_id"] == first.json()["job_id"]
