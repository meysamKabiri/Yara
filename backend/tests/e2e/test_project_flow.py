from collections.abc import Callable

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.anyio


async def test_create_project_and_list_owned_projects(
    client: AsyncClient,
    signup: Callable,
    create_project: Callable,
) -> None:
    owner = await signup("project-owner@example.com")
    other = await signup("project-other@example.com")

    owner_project = await create_project(owner["headers"], "پروژه مالک")
    other_project = await create_project(other["headers"], "پروژه دیگر")

    owner_projects = await client.get("/projects", headers=owner["headers"])
    other_projects = await client.get("/projects", headers=other["headers"])

    assert owner_projects.status_code == 200
    assert other_projects.status_code == 200
    assert [project["id"] for project in owner_projects.json()] == [owner_project["id"]]
    assert [project["id"] for project in other_projects.json()] == [other_project["id"]]
