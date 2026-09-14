import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from catalyst.app import Settings, create_app
from catalyst.db import connect, digest, issue_agent, issue_human
from catalyst.cli import seed
from conftest import proposed


def test_health_and_public_pages(site):
    client, path, _ = site
    assert client.get("/healthz").json()["provider_connected"] is False
    seed(path)
    for route in ["/", "/contribute", "/about", "/login", "/docs", "/openapi.json"]:
        assert client.get(route).status_code == 200
    for item in client.get("/api/ideas").json():
        assert client.get(f"/ideas/{item['id']}").status_code == 200
        assert client.get(f"/revisions/{item['head_id']}").status_code == 200


def test_seed_is_idempotent_and_labeled(site):
    client, path, _ = site
    seed(path); seed(path)
    assert len(client.get("/api/ideas").json()) == 3
    assert all(i["demo"] == 1 for i in client.get("/api/ideas").json())
    assert "Illustrative example" in client.get("/").text


def test_origin_and_revision_content_immutable(site, idea):
    client, path, _ = site
    current = client.get(f"/api/ideas/{idea}").json()
    with pytest.raises(sqlite3.IntegrityError), connect(path, True) as con:
        con.execute("UPDATE ideas SET origin='rewritten' WHERE id=?", (idea,))
    with pytest.raises(sqlite3.IntegrityError), connect(path, True) as con:
        con.execute("UPDATE revisions SET body='{}' WHERE id=?", (current["head_id"],))
    with pytest.raises(sqlite3.IntegrityError), connect(path, True) as con:
        con.execute("UPDATE revisions SET review_note='rewritten' WHERE id=?", (current["head_id"],))


def test_full_five_to_six_principle_cycle(site, human, agent, idea):
    client, _, _ = site
    before = client.get(f"/api/ideas/{idea}").json()
    objection = human.post(f"/api/ideas/{idea}/contributions", json={"kind": "objection", "body": "Who performs the unpaid maintenance?"}).json()["id"]
    response = agent.post(f"/api/ideas/{idea}/contributions", json={"kind": "response", "body": "Treat maintenance as an explicit contribution.", "parent_id": objection})
    assert response.status_code == 201
    assert client.post(f"/api/contributions/{response.json()['id']}/recognize", json={"reason": "A human constraint led to a concrete agent revision."}).status_code == 200
    draft = agent.post(f"/api/ideas/{idea}/drafts", json=proposed(client, idea))
    assert draft.status_code == 201, draft.text
    revision_id = draft.json()["id"]
    assert client.get(f"/api/ideas/{idea}").json()["head_id"] == before["head_id"]
    assert agent.post(f"/api/revisions/{revision_id}/review", json={"decision": "publish", "reason": "I approve"}).status_code == 403
    result = client.post(f"/api/revisions/{revision_id}/review", json={"decision": "publish", "reason": "Reviewed the retained objection and revised principle."})
    assert result.status_code == 200, result.text
    after = client.get(f"/api/ideas/{idea}").json()
    assert len(after["synthesis"]["principles"]) == 6
    assert after["origin"] == before["origin"]
    assert after["synthesis"]["dissent"][0]["contribution_id"] == objection
    assert after["metrics"]["meaningful_exchanges"] == 1
    assert client.get(f"/revisions/{before['head_id']}").status_code == 200


def test_cannot_erase_or_invent_dissent(site, human, idea):
    client, _, _ = site
    human.post(f"/api/ideas/{idea}/contributions", json={"kind": "objection", "body": "A minority concern that deserves an answer."})
    data = proposed(client, idea)
    data["synthesis"]["dissent"] = []
    assert client.post(f"/api/ideas/{idea}/drafts", json=data).status_code == 422
    data = proposed(client, idea)
    data["synthesis"]["dissent"][0]["contribution_id"] = "invented"
    assert client.post(f"/api/ideas/{idea}/drafts", json=data).status_code == 422


def test_duplicate_dissent_rejected(site, human, idea):
    client, _, _ = site
    human.post(f"/api/ideas/{idea}/contributions", json={"kind": "objection", "body": "A concern"})
    data = proposed(client, idea)
    data["synthesis"]["dissent"] *= 2
    assert client.post(f"/api/ideas/{idea}/drafts", json=data).status_code == 422


@pytest.mark.parametrize("change", ["discussion", "vote", "head"])
def test_stale_draft_cannot_publish(site, human, idea, change):
    client, _, _ = site
    draft = client.post(f"/api/ideas/{idea}/drafts", json=proposed(client, idea)).json()["id"]
    current = client.get(f"/api/ideas/{idea}").json()
    if change == "discussion":
        human.post(f"/api/ideas/{idea}/contributions", json={"kind": "observation", "body": "New input"})
    elif change == "vote":
        human.put(f"/api/ideas/{idea}/reaction", json={"revision_id": current["head_id"], "worth": 1, "stance": "disagree", "explore": True})
    else:
        other = client.post(f"/api/ideas/{idea}/drafts", json=proposed(client, idea, "An alternative revision.")).json()["id"]
        assert client.post(f"/api/revisions/{other}/review", json={"decision": "publish", "reason": "Reviewed alternative"}).status_code == 200
    assert client.post(f"/api/revisions/{draft}/review", json={"decision": "publish", "reason": "Review"}).status_code == 409


def test_draft_base_conflict_and_queue_cap(site, idea):
    client, _, _ = site
    data = proposed(client, idea); data["base_id"] = "wrong"
    assert client.post(f"/api/ideas/{idea}/drafts", json=data).status_code == 409
    for _ in range(5):
        assert client.post(f"/api/ideas/{idea}/drafts", json=proposed(client, idea)).status_code == 201
    assert client.post(f"/api/ideas/{idea}/drafts", json=proposed(client, idea)).status_code == 409


def test_rejected_draft_is_not_head(site, idea):
    client, _, _ = site
    before = client.get(f"/api/ideas/{idea}").json()["head_id"]
    draft = client.post(f"/api/ideas/{idea}/drafts", json=proposed(client, idea)).json()["id"]
    assert client.post(f"/api/revisions/{draft}/review", json={"decision": "reject", "reason": "Insufficient support"}).status_code == 200
    assert client.get(f"/api/ideas/{idea}").json()["head_id"] == before
    assert client.post(f"/api/revisions/{draft}/review", json={"decision": "publish", "reason": "Changed mind"}).status_code == 409


def test_reactions_are_per_revision_and_upsert(site, human, idea):
    client, _, _ = site
    head = client.get(f"/api/ideas/{idea}").json()["head_id"]
    reaction = {"revision_id": head, "worth": 1, "stance": "disagree", "explore": True}
    for _ in range(3):
        response = human.put(f"/api/ideas/{idea}/reaction", json=reaction)
        assert response.status_code == 200
    assert response.json()["worth"] == 1 and response.json()["voters"] == 1
    draft = client.post(f"/api/ideas/{idea}/drafts", json=proposed(client, idea)).json()["id"]
    client.post(f"/api/revisions/{draft}/review", json={"decision": "publish", "reason": "Reviewed"})
    assert client.get(f"/api/ideas/{idea}").json()["metrics"]["voters"] == 0
    assert human.put(f"/api/ideas/{idea}/reaction", json=reaction).status_code == 409


def test_agent_cannot_vote_or_create_published_idea(site, agent, idea):
    client, _, _ = site
    head = client.get(f"/api/ideas/{idea}").json()["head_id"]
    assert agent.put(f"/api/ideas/{idea}/reaction", json={"revision_id": head, "worth": 1, "stance": "agree", "explore": True}).status_code == 403
    assert agent.post("/api/ideas", json={}).status_code == 403
    assert agent.put("/api/me/budget", json={"share": 100, "daily_jobs": 20, "enabled": True}).status_code == 403


def test_nonreviewer_cannot_publish_or_create(site, human, idea):
    client, _, _ = site
    draft = human.post(f"/api/ideas/{idea}/drafts", json=proposed(client, idea)).json()["id"]
    assert human.post(f"/api/revisions/{draft}/review", json={"decision": "publish", "reason": "Review"}).status_code == 403
    assert human.post("/api/ideas", json={}).status_code == 403


def test_forged_actor_field_rejected(agent, idea):
    assert agent.post(f"/api/ideas/{idea}/contributions", json={"kind": "observation", "body": "Test", "actor_kind": "human"}).status_code == 422


def test_reply_must_be_on_same_idea(site, idea):
    client, _, _ = site
    parent = client.post(f"/api/ideas/{idea}/contributions", json={"kind": "observation", "body": "First"}).json()["id"]
    other = client.post("/api/ideas", json={"title": "A different living idea", "kind": "claim", "origin": "Origin", "synthesis": {"summary": "Summary"}}).json()["id"]
    assert client.post(f"/api/ideas/{other}/contributions", json={"kind": "response", "body": "Wrong thread", "parent_id": parent}).status_code == 422


def test_own_agent_exchange_not_independent(site, agent, idea):
    client, _, _ = site
    parent = client.post(f"/api/ideas/{idea}/contributions", json={"kind": "question", "body": "A question"}).json()["id"]
    reply = agent.post(f"/api/ideas/{idea}/contributions", json={"kind": "response", "body": "Answer", "parent_id": parent}).json()["id"]
    assert client.post(f"/api/contributions/{reply}/recognize", json={"reason": "Claimed meaningful"}).status_code == 422


def test_exchange_cannot_be_counted_twice(site, human, agent, idea):
    client, _, _ = site
    parent = human.post(f"/api/ideas/{idea}/contributions", json={"kind": "question", "body": "Question"}).json()["id"]
    reply = agent.post(f"/api/ideas/{idea}/contributions", json={"kind": "response", "body": "Answer", "parent_id": parent}).json()["id"]
    assert client.post(f"/api/contributions/{reply}/recognize", json={"reason": "Resolved a question"}).status_code == 200
    assert client.post(f"/api/contributions/{reply}/recognize", json={"reason": "Again"}).status_code == 409


def test_cookies_csrf_and_logout(site, idea):
    client, _, _ = site
    csrf = client.headers.pop("X-CSRF-Token")
    assert client.post(f"/api/ideas/{idea}/contributions", json={"kind": "observation", "body": "No CSRF"}).status_code == 403
    client.headers["X-CSRF-Token"] = csrf
    assert client.post("/api/logout", json={}).status_code == 200
    assert client.get("/api/me").status_code == 401


def test_invites_are_single_use_and_agent_is_not_human(site):
    _, path, app = site
    invite = issue_human(path, "Invited")
    with TestClient(app) as other:
        response = other.post("/login", data={"token": invite}, follow_redirects=False)
        assert response.status_code == 303
        assert "HttpOnly" in response.headers["set-cookie"]
        assert "SameSite=strict" in response.headers["set-cookie"]
        assert other.post("/login", data={"token": invite}).status_code == 401
        token = issue_agent(path, "Reviewer", "Second agent")
        assert other.post("/login", data={"token": token}).status_code == 401


def test_expired_invite_and_cross_origin_login(site):
    _, path, app = site
    token = issue_human(path, "Expired")
    with connect(path, True) as con:
        con.execute("UPDATE credentials SET expires=0 WHERE digest=?", (digest(token),))
    with TestClient(app) as client:
        assert client.post("/login", data={"token": token}).status_code == 401
        assert client.post("/login", data={"token": "anything"}, headers={"Origin": "https://evil.example"}).status_code == 403


def test_xss_is_escaped_and_csp_present(site, idea):
    client, _, _ = site
    text = '<script>alert("not executed")</script>'
    client.post(f"/api/ideas/{idea}/contributions", json={"kind": "observation", "body": text})
    result = client.get(f"/ideas/{idea}")
    assert text not in result.text
    assert "&lt;script&gt;" in result.text
    assert "frame-ancestors 'none'" in result.headers["content-security-policy"]
    assert result.headers["cache-control"] == "no-store"


def test_public_cannot_mutate(site, idea):
    _, _, app = site
    with TestClient(app) as public:
        assert public.get(f"/ideas/{idea}").status_code == 200
        assert public.post(f"/api/ideas/{idea}/contributions", json={"kind": "observation", "body": "Anon"}).status_code == 401


def test_body_limit(site):
    client, _, _ = site
    assert client.post("/api/feedback", content=b"x" * 65537).status_code == 413


def test_bad_host_rejected(site):
    client, _, _ = site
    assert client.get("/", headers={"Host": "attacker.example"}).status_code == 400


@pytest.mark.parametrize("share,daily,cap", [(0, 4, 0), (25, 4, 1), (50, 5, 2), (100, 20, 20)])
def test_budget_units_and_floor(site, share, daily, cap):
    client, _, _ = site
    value = client.put("/api/me/budget", json={"share": share, "daily_jobs": daily, "enabled": True}).json()
    assert value["effective_daily_jobs"] == cap
    assert value["provider_usage"] is None and value["telemetry"] == "unavailable"


@pytest.mark.parametrize("share,daily", [(-1, 4), (101, 4), (50, 21), (50, -1)])
def test_budget_rejects_invalid_values(site, share, daily):
    client, _, _ = site
    assert client.put("/api/me/budget", json={"share": share, "daily_jobs": daily, "enabled": True}).status_code == 422


def queue_and_enable(client, idea, count=1, daily=4):
    client.put("/api/me/budget", json={"share": 100, "daily_jobs": daily, "enabled": True})
    for i in range(count):
        assert client.post(f"/api/ideas/{idea}/tasks", json={"question": f"Investigate bounded question {i}"}).status_code == 201


def completion(job):
    return {"lease_token": job["lease_token"], "contribution": {"kind": "observation", "body": "A labeled simulation result.", "provenance": "Test fixture"}}


def test_default_worker_is_paused(site, agent, idea):
    assert agent.post("/api/tasks/claim").json()["status"] == "paused"


def test_worker_idle_with_empty_queue(site, agent):
    client, _, _ = site
    client.put("/api/me/budget", json={"share": 100, "daily_jobs": 4, "enabled": True})
    assert agent.post("/api/tasks/claim").json()["status"] == "idle"


def test_task_complete_idempotency_and_daily_cap(site, agent, idea):
    client, _, _ = site
    queue_and_enable(client, idea, count=2, daily=1)
    job = agent.post("/api/tasks/claim").json()
    assert job["status"] == "leased"
    result = agent.post(f"/api/tasks/{job['task_id']}/complete", json=completion(job))
    assert result.status_code == 200, result.text
    repeat = agent.post(f"/api/tasks/{job['task_id']}/complete", json=completion(job))
    assert repeat.json()["duplicate"] is True
    assert repeat.json()["contribution_id"] == result.json()["contribution_id"]
    altered = completion(job); altered["contribution"]["body"] = "Different payload"
    assert agent.post(f"/api/tasks/{job['task_id']}/complete", json=altered).status_code == 409
    assert agent.post("/api/tasks/claim").json()["status"] == "paused"
    assert client.get("/api/me/budget").json()["claimed_today"] == 1


def test_only_one_inflight_across_owner_agents(site, agent, idea):
    client, path, app = site
    queue_and_enable(client, idea, 2)
    token = issue_agent(path, "Reviewer", "Sibling agent")
    with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as sibling:
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = list(pool.map(lambda c: c.post("/api/tasks/claim").json(), [agent, sibling]))
        assert sorted(j["status"] for j in jobs) == ["busy", "leased"]
    assert client.get("/api/me/budget").json()["claimed_today"] == 1


def test_pause_invalidates_outstanding_lease(site, agent, idea):
    client, _, _ = site
    queue_and_enable(client, idea)
    job = agent.post("/api/tasks/claim").json()
    client.put("/api/me/budget", json={"share": 100, "daily_jobs": 4, "enabled": False})
    assert agent.post(f"/api/tasks/{job['task_id']}/complete", json=completion(job)).status_code == 409
    assert agent.post("/api/tasks/claim").json()["status"] == "paused"
    assert client.get("/api/me/budget").json()["claimed_today"] == 1


def test_expired_lease_rejected_and_retry_counts(site, agent, idea):
    client, path, _ = site
    queue_and_enable(client, idea)
    job = agent.post("/api/tasks/claim").json()
    with connect(path, True) as con:
        con.execute("UPDATE tasks SET lease_until=0 WHERE id=?", (job["task_id"],))
    assert agent.post(f"/api/tasks/{job['task_id']}/complete", json=completion(job)).status_code == 409
    second = agent.post("/api/tasks/claim").json()
    assert second["status"] == "leased"
    assert second["lease_token"] != job["lease_token"]
    assert client.get("/api/me/budget").json()["claimed_today"] == 2


def test_cancellation_stops_result_acceptance(site, agent, idea):
    client, _, _ = site
    queue_and_enable(client, idea)
    job = agent.post("/api/tasks/claim").json()
    assert client.post(f"/api/tasks/{job['task_id']}/cancel").status_code == 200
    assert agent.post(f"/api/tasks/{job['task_id']}/complete", json=completion(job)).status_code == 409


def test_task_result_requires_owned_lease(site, agent, idea):
    client, _, _ = site
    queue_and_enable(client, idea)
    job = agent.post("/api/tasks/claim").json()
    value = completion(job); value["lease_token"] = "wrong" * 8
    assert agent.post(f"/api/tasks/{job['task_id']}/complete", json=value).status_code == 409


def test_revoked_owner_blocks_agent(site, agent):
    _, path, _ = site
    with connect(path, True) as con:
        con.execute("UPDATE actors SET active=0 WHERE name='Reviewer'")
    assert agent.post("/api/tasks/claim").status_code == 401


def test_separate_feedback_channels(site, agent, human):
    client, _, _ = site
    assert human.post("/api/feedback", json={"category": "human-ux", "body": "A clearer revision diff would help."}).status_code == 201
    assert agent.post("/api/feedback", json={"category": "agent-ux", "body": "Please expose a change cursor."}).status_code == 201
    assert agent.post("/api/feedback", json={"category": "human-ux", "body": "Pretend to be human"}).status_code == 403
    result = client.get("/api/feedback").json()
    assert {f["actor_kind"] for f in result} == {"human", "agent"}
    assert human.get("/api/feedback").status_code == 403


def test_cadence_enforced(site, idea):
    client, path, _ = site
    draft = client.post(f"/api/ideas/{idea}/drafts", json=proposed(client, idea)).json()["id"]
    app = create_app(Settings(database=path, cadence_seconds=3600))
    with TestClient(app) as reviewer:
        reviewer.post("/login", data={"token": issue_human(path, "Reviewer", True)})
        reviewer.headers["X-CSRF-Token"] = reviewer.get("/api/me").json()["csrf"]
        assert reviewer.post(f"/api/revisions/{draft}/review", json={"decision": "publish", "reason": "Too soon"}).status_code == 409


def test_token_rotation_invalidates_previous_token(site):
    _, path, app = site
    first = issue_agent(path, "Reviewer", "Rotating agent")
    second = issue_agent(path, "Reviewer", "Rotating agent")
    with TestClient(app) as client:
        assert client.get("/api/me", headers={"Authorization": f"Bearer {first}"}).status_code == 401
        assert client.get("/api/me", headers={"Authorization": f"Bearer {second}"}).status_code == 200
