from fastapi.testclient import TestClient


def _signup(client: TestClient, email: str) -> str:
    response = client.post(
        "/auth/signup",
        json={"email": email, "password": "password123"},
    )
    assert response.status_code == 201
    return response.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_auth_signup_login_and_me(client: TestClient) -> None:
    token = _signup(client, "owner@example.com")

    me = client.get("/auth/me", headers=_auth(token))
    login = client.post(
        "/auth/login",
        json={"email": "owner@example.com", "password": "password123"},
    )

    assert me.status_code == 200
    assert me.json()["email"] == "owner@example.com"
    assert login.status_code == 200
    assert login.json()["access_token"]


def test_invalid_token_returns_401(client: TestClient) -> None:
    response = client.get("/projects", headers={"Authorization": "Bearer invalid-token"})

    assert response.status_code == 401


def test_missing_token_returns_401(client: TestClient) -> None:
    response = client.get("/projects", headers={"Authorization": ""})

    assert response.status_code == 401


def test_project_owner_can_access_and_non_owner_cannot(client: TestClient) -> None:
    owner_token = _signup(client, "project-owner@example.com")
    other_token = _signup(client, "project-other@example.com")

    created = client.post(
        "/projects",
        json={"name": "مالکیت"},
        headers=_auth(owner_token),
    )
    project_id = created.json()["id"]
    owner_access = client.get(f"/projects/{project_id}", headers=_auth(owner_token))
    other_access = client.get(f"/projects/{project_id}", headers=_auth(other_token))

    assert created.status_code == 201
    assert owner_access.status_code == 200
    assert other_access.status_code == 403


def test_project_listing_returns_only_owned_projects(client: TestClient) -> None:
    owner_token = _signup(client, "list-owner@example.com")
    other_token = _signup(client, "list-other@example.com")

    client.post("/projects", json={"name": "پروژه مالک"}, headers=_auth(owner_token))
    client.post("/projects", json={"name": "پروژه دیگری"}, headers=_auth(other_token))

    owner_projects = client.get("/projects", headers=_auth(owner_token)).json()
    other_projects = client.get("/projects", headers=_auth(other_token)).json()

    assert [project["name"] for project in owner_projects] == ["پروژه مالک"]
    assert [project["name"] for project in other_projects] == ["پروژه دیگری"]


def test_cross_user_project_financial_endpoint_forbidden(client: TestClient) -> None:
    owner_token = _signup(client, "financial-owner@example.com")
    other_token = _signup(client, "financial-other@example.com")
    created = client.post(
        "/projects",
        json={"name": "مالی خصوصی"},
        headers=_auth(owner_token),
    )

    response = client.get(
        f"/projects/{created.json()['id']}/payments",
        headers=_auth(other_token),
    )

    assert response.status_code == 403


def test_direct_worker_id_bypass_attempt_forbidden(client: TestClient) -> None:
    owner_token = _signup(client, "worker-owner@example.com")
    other_token = _signup(client, "worker-other@example.com")
    project = client.post(
        "/projects",
        json={"name": "پروژه اشخاص"},
        headers=_auth(owner_token),
    ).json()
    worker = client.post(
        f"/projects/{project['id']}/workers",
        json={"name": "نیروی خصوصی", "type": "DAILY_WORKER"},
        headers=_auth(owner_token),
    ).json()

    response = client.patch(
        f"/workers/{worker['id']}",
        json={"name": "تغییر غیرمجاز"},
        headers=_auth(other_token),
    )

    assert response.status_code == 403


def test_cross_user_natural_input_job_access_forbidden(client: TestClient) -> None:
    owner_token = _signup(client, "job-owner@example.com")
    other_token = _signup(client, "job-other@example.com")
    project = client.post(
        "/projects",
        json={"name": "پروژه پردازش"},
        headers=_auth(owner_token),
    ).json()
    job = client.post(
        f"/projects/{project['id']}/natural-input",
        json={"text": "یادداشت محرمانه", "idempotency_key": "job-isolation"},
        headers=_auth(owner_token),
    ).json()

    response = client.get(
        f"/natural-input-jobs/{job['job_id']}",
        headers=_auth(other_token),
    )

    assert response.status_code == 403
