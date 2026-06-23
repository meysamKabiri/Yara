from typing import Any

from fastapi.testclient import TestClient


def submit_natural_input(
    client: TestClient,
    project_id: int,
    text: str,
    *,
    headers: dict[str, str] | None = None,
) -> dict:
    response = client.post(
        f"/projects/{project_id}/natural-input",
        json={"text": text},
        headers=headers,
    )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "PENDING"
    assert "job_id" in body
    return body


def natural_input_result(
    client: TestClient,
    project_id: int,
    text: str,
    *,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    job = submit_natural_input(client, project_id, text, headers=headers)
    response = client.get(f"/natural-input-jobs/{job['job_id']}")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "DONE"
    assert body["result"] is not None
    return body["result"]


def natural_input_interpretations(
    client: TestClient,
    project_id: int,
    text: str,
    *,
    headers: dict[str, str] | None = None,
) -> list[dict]:
    result = natural_input_result(client, project_id, text, headers=headers)
    interpretations = result["interpretations"]
    assert interpretations
    return interpretations


def natural_input_interpretation(
    client: TestClient,
    project_id: int,
    text: str,
    *,
    headers: dict[str, str] | None = None,
) -> dict:
    return natural_input_interpretations(client, project_id, text, headers=headers)[0]
