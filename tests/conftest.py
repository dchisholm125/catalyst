import pytest
from fastapi.testclient import TestClient
from catalyst.app import Settings, create_app
from catalyst.db import issue_agent, issue_human


@pytest.fixture
def site(tmp_path):
    path = str(tmp_path / "test.db")
    app = create_app(Settings(database=path, cadence_seconds=0, mutation_limit=10000))
    with TestClient(app) as client:
        invite = issue_human(path, "Reviewer", reviewer=True)
        assert client.post("/login", data={"token": invite}).status_code == 200
        client.headers["X-CSRF-Token"] = client.get("/api/me").json()["csrf"]
        yield client, path, app


@pytest.fixture
def human(site):
    _, path, app = site
    with TestClient(app) as client:
        client.post("/login", data={"token": issue_human(path, "Contributor")})
        client.headers["X-CSRF-Token"] = client.get("/api/me").json()["csrf"]
        yield client


@pytest.fixture
def agent(site):
    _, path, app = site
    token = issue_agent(path, "Reviewer", "Research agent")
    with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as client:
        yield client


@pytest.fixture
def idea(site):
    client, _, _ = site
    response = client.post("/api/ideas", json={"title": "Share equipment without hidden labor", "kind": "catalyst",
        "origin": "An initial question, preserved for posterity.", "synthesis": {
            "summary": "A neighborhood shares equipment with transparent access and explicit responsibilities.",
            "principles": ["Small inventory", "Clear availability", "Condition records", "Fair access", "Easy exit"]}})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def proposed(client, idea_id, summary="A revised account that includes explicit maintenance duties."):
    current = client.get(f"/api/ideas/{idea_id}").json()
    body = current["draft_template"]
    body["summary"] = summary
    body["principles"].append("Coordination and maintenance are explicit contributions, not invisible obligations.")
    return {"base_id": current["head_id"], "reason": "Make previously hidden work explicit", "synthesis": body}
