def test_health_check(client) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("ok", "degraded")
    assert data["database"] in ("ok", "unavailable")
    assert data["redis"] in ("ok", "unavailable")
    assert data["ollama"] in ("ok", "unavailable")
