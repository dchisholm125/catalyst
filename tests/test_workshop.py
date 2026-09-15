"""Human direction, permissions, queue diversity, history, and v1 preservation."""
import json
from pathlib import Path
import sqlite3
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from catalyst.db import connect, initialize, issue_agent, issue_human
from catalyst.models import TaskInput
from catalyst import workshop
from scripts.upgrade import upgrade
from test_catalyst import completion, queue_and_enable


def signal_data(**kw):
    return {"topic_id": "time", "title": "What recurring burdens could we remove?",
            "body": "Identify a small recurring obligation that could be removed rather than optimized.", **kw}


def make_signal(client, **kw):
    response = client.post("/api/agenda", json=signal_data(**kw))
    assert response.status_code == 201, response.text
    return response.json()["id"]


def develop(client, sid):
    response = client.post(f"/api/agenda/{sid}/develop", json={"kind": "catalyst",
        "summary": "Investigate a bounded way to remove one recurring obligation.", "reason": "A specific human question warrants development."})
    assert response.status_code == 201, response.text
    return response.json()["idea_id"]


def second_agent(site, name="Another handler"):
    _, path, app = site
    token = issue_human(path, name)
    human = TestClient(app)
    human.post("/login", data={"token": token})
    human.headers["X-CSRF-Token"] = human.get("/api/me").json()["csrf"]
    human.put("/api/me/budget", json={"share": 100, "daily_jobs": 20, "enabled": True})
    token = issue_agent(path, name, f"{name} agent")
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


def test_topics_are_twenty_starters_not_fake_human_demand(site):
    client, path, _ = site
    initialize(path)
    data = client.get("/api/agenda").json()
    assert len(data["topics"]) == 20
    assert len({t["id"] for t in data["topics"]}) == 20
    assert data["questions"] == []
    with connect(path) as con:
        assert con.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0
    for url in ["/agenda", "/agent-guide", "/agents", "/api/agent-contract"]:
        assert client.get(url).status_code == 200
    assert client.get("/agenda?topic=imaginary").status_code == 404


def test_human_signal_support_and_unsubscribe(site, human, agent):
    client, _, _ = site
    sid = make_signal(human)
    for _ in range(2):
        assert human.put(f"/api/agenda/{sid}/support", json={"supported": True}).status_code == 200
    row = client.get("/api/agenda").json()["questions"][0]
    assert row["supporters"] == 1 and row["name"] == "Contributor"
    assert agent.post("/api/agenda", json=signal_data()).status_code == 403
    assert agent.put(f"/api/agenda/{sid}/support", json={"supported": True}).status_code == 403
    assert human.put(f"/api/agenda/{sid}/support", json={"supported": False}).status_code == 200
    assert client.get("/api/agenda").json()["questions"][0]["supporters"] == 0


def test_agenda_csrf_identity_and_input_boundaries(site):
    client, _, app = site
    with TestClient(app) as anon:
        assert anon.post("/api/agenda", json=signal_data()).status_code == 401
    assert client.post("/api/agenda", json=signal_data(actor_id="forged")).status_code == 422
    assert client.post("/api/agenda", json=signal_data(topic_id="unknown")).status_code == 404
    assert client.post("/api/agenda", json=signal_data(), headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert client.post("/api/agenda", json=signal_data(body=" ")).status_code == 422


def test_signal_rate_limit_and_escaping(site):
    client, _, _ = site
    sid = make_signal(client, title='<script>alert("x")</script>', body='A <script> malicious-looking synthetic body </script>')
    text = client.get(f"/agenda/{sid}").text
    assert '<script>alert("x")</script>' not in text
    assert "&lt;script&gt;" in text
    for i in range(9):
        make_signal(client, title=f"A distinct question number {i}")
    assert client.post("/api/agenda", json=signal_data()).status_code == 409


def test_reviewer_development_preserves_origin_and_does_not_start_work(site, human, agent):
    client, path, _ = site
    sid = make_signal(human, origin_kind="collaborative", assistance="Prepared together; declared assistance.")
    payload = {"kind": "reflection", "summary": "A bounded initial formulation.", "reason": "Worth developing"}
    assert human.post(f"/api/agenda/{sid}/develop", json=payload).status_code == 403
    assert agent.post(f"/api/agenda/{sid}/develop", json=payload).status_code == 403
    idea_id = develop(client, sid)
    assert client.post(f"/api/agenda/{sid}/develop", json=payload).status_code == 409
    idea = client.get(f"/api/ideas/{idea_id}").json()
    assert "Contributor" in idea["origin"] and "Prepared together" in idea["origin"]
    assert client.get(f"/agenda/{sid}").status_code == 200
    with connect(path) as con:
        assert con.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0
        assert con.execute("SELECT origin_kind FROM idea_origins WHERE idea_id=?", (idea_id,)).fetchone()[0] == "collaborative"
    assert idea_id in client.get("/?origin=collaborative").text
    assert idea_id not in client.get("/?origin=human").text


@pytest.mark.parametrize("view", ["synthesis", "dissent", "discussion", "development", "investigations"])
def test_server_panels_and_deep_links(site, idea, view):
    from html.parser import HTMLParser
    class Panels(HTMLParser):
        def __init__(self): super().__init__(); self.panels = []; self.tabs = []
        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if "data-idea-panel" in attrs: self.panels.append(attrs)
            if "data-idea-tab" in attrs: self.tabs.append(attrs)
    client, _, _ = site
    response = client.get(f"/ideas/{idea}?view={view}")
    assert response.status_code == 200
    page = Panels(); page.feed(response.text)
    panels = page.panels
    assert len(panels) == 5
    assert [p["id"] for p in panels if "hidden" not in p] == [view]
    assert len(page.tabs) == 5


def test_filters_combine_and_reject_unknown_values(site):
    client, _, _ = site
    ids = {}
    for kind in ["reflection", "catalyst", "claim"]:
        for origin in ["human", "ai"]:
            ids[kind, origin] = client.post("/api/ideas", json={"kind": kind, "title": f"{kind} {origin} thought",
                "origin": "Synthetic origin", "origin_kind": origin, "synthesis": {"summary": "Synthetic summary"}}).json()["id"]
    text = client.get("/?kind=catalyst&origin=ai&q=thought&sort=oldest").text
    for key, ident in ids.items():
        assert (ident in text) == (key == ("catalyst", "ai"))
    for query in ["kind=garbage", "origin=pretend", "sort=popular"]:
        assert client.get("/?"+query).status_code == 422


def test_contract_roles_and_agent_authority(site, agent, idea):
    client, _, _ = site
    contract = client.get("/api/agent-contract").json()
    assert {r["id"] for r in contract["roles"]} == set(workshop.ROLE_IDS)
    assert contract["provider_connected"] is False
    assert agent.post(f"/api/ideas/{idea}/tasks", json={"question": "May I queue my own work?"}).status_code == 403
    assert agent.post("/api/tasks/claim", json={"roles": ["ruler"]}).status_code == 422
    assert agent.post("/api/tasks/claim", json={"roles": []}).status_code == 422


def test_priority_link_and_exact_duplicate_guard(site, human, idea):
    client, _, _ = site
    assert client.post(f"/api/ideas/{idea}/tasks", json={"question": "A question", "tier": 1}).status_code == 422
    assert human.post(f"/api/ideas/{idea}/tasks", json={"question": "A question", "tier": 3}).status_code == 403
    data = {"question": "Who does the hidden work?", "role": "challenger"}
    assert client.post(f"/api/ideas/{idea}/tasks", json=data).status_code == 201
    assert client.post(f"/api/ideas/{idea}/tasks", json={**data, "question": "  WHO   DOES THE HIDDEN WORK? "}).status_code == 409
    assert client.post(f"/api/ideas/{idea}/tasks", json={**data, "role": "researcher"}).status_code == 201


def test_human_agenda_priority_and_role_selection(site, agent, idea):
    client, _, _ = site
    queue_and_enable(client, idea)
    agenda_idea = develop(client, make_signal(client))
    task_id = client.post(f"/api/ideas/{agenda_idea}/tasks", json={"question": "Which burden matters?", "role": "challenger", "tier": 1}).json()["id"]
    job = agent.post("/api/tasks/claim").json()
    assert job["task_id"] == task_id
    assert job["role"] == "challenger" and job["human_agenda"]["title"] == signal_data()["title"]
    assert job["agent_history"] == [] and job["success_criteria"]


def test_different_roles_max_two_and_skip_blocked_idea(site, agent, idea):
    client, _, _ = site
    client.put("/api/me/budget", json={"share": 100, "daily_jobs": 20, "enabled": True})
    for role in ["researcher", "challenger", "summarizer"]:
        client.post(f"/api/ideas/{idea}/tasks", json={"question": f"Investigate as {role}", "role": role})
    other = second_agent(site)
    third = second_agent(site, "Third handler")
    jobs = [agent.post("/api/tasks/claim").json(), other.post("/api/tasks/claim").json()]
    assert {j["role"] for j in jobs} == {"researcher", "challenger"}
    assert third.post("/api/tasks/claim").json()["status"] == "idle"
    another_idea = develop(client, make_signal(client))
    client.post(f"/api/ideas/{another_idea}/tasks", json={"question": "Another useful question", "role": "summarizer"})
    assert third.post("/api/tasks/claim", json={"roles": ["summarizer"]}).json()["idea_id"] == another_idea
    other.close(); third.close()


def test_same_role_race_has_one_winner(site, agent, idea):
    client, _, _ = site
    queue_and_enable(client, idea, 2)
    other = second_agent(site)
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = list(pool.map(lambda c: c.post("/api/tasks/claim").json(), [agent, other]))
    assert sorted(j["status"] for j in jobs) == ["idle", "leased"]
    other.close()


def test_three_results_pause_until_human_review_and_history_is_returned(site, agent, human, idea):
    client, path, _ = site
    queue_and_enable(client, idea, 4, daily=20)
    jobs = []
    for _ in range(3):
        job = agent.post("/api/tasks/claim").json(); jobs.append(job)
        assert job["status"] == "leased"
        assert agent.post(f"/api/tasks/{job['task_id']}/complete", json=completion(job)).status_code == 200
    assert agent.post("/api/tasks/claim").json()["status"] == "idle"
    review = {"verdict": "revise", "reason": "A simulation does not answer the substantive question."}
    task_id = jobs[0]["task_id"]
    assert agent.post(f"/api/tasks/{task_id}/review", json=review).status_code == 403
    assert human.post(f"/api/tasks/{task_id}/review", json=review).status_code == 403
    assert client.post(f"/api/tasks/{task_id}/review", json=review).status_code == 200
    assert client.post(f"/api/tasks/{task_id}/review", json=review).status_code == 409
    next_job = agent.post("/api/tasks/claim").json()
    assert next_job["status"] == "leased"
    assert len(next_job["agent_history"]) == 3
    assert any(h["feedback"] == review["reason"] for h in next_job["agent_history"])
    with connect(path) as con:
        snapshot = con.execute("SELECT body FROM task_inputs WHERE task_id=?", (next_job["task_id"],)).fetchone()[0]
        assert next_job["lease_token"] not in snapshot
        assert json.loads(snapshot)["context"]["head_id"]
    actor_id = agent.get("/api/me").json()["id"]
    assert "Handler reviewed their own agent" in client.get(f"/agents/{actor_id}").text
    assert len(agent.get("/api/agents/me/history").json()["history"]) == 3


def test_review_capacity_reserves_inflight_slots(site, agent, idea):
    client, _, _ = site
    queue_and_enable(client, idea, 3, daily=20)
    for _ in range(2):
        job = agent.post("/api/tasks/claim").json()
        agent.post(f"/api/tasks/{job['task_id']}/complete", json=completion(job))
    client.post(f"/api/ideas/{idea}/tasks", json={"question": "A different angle", "role": "challenger"})
    assert agent.post("/api/tasks/claim").json()["status"] == "leased"
    other = second_agent(site)
    assert other.post("/api/tasks/claim").json()["status"] == "idle"
    other.close()


def test_unfinished_result_cannot_be_reviewed(site, idea):
    client, _, _ = site
    task_id = client.post(f"/api/ideas/{idea}/tasks", json={"question": "An unfinished question"}).json()["id"]
    assert client.post(f"/api/tasks/{task_id}/review", json={"verdict": "useful", "reason": "Premature"}).status_code == 409


def test_v1_backup_upgrade_preserves_records_and_is_idempotent(tmp_path):
    db = tmp_path / "old.db"
    with sqlite3.connect(db) as con:
        con.executescript((Path(__file__).parent / "fixtures/schema_v1.sql").read_text())
        con.execute("INSERT INTO actors(id,name,kind) VALUES ('old-human','Existing participant','human')")
        con.execute("INSERT INTO credentials VALUES ('old-digest','old-human','invite',9999999999,'')")
        con.execute("INSERT INTO ideas(id,title,kind,origin,creator_id,created) VALUES ('old-idea','Existing idea','reflection','Original text','old-human',1)")
        con.execute("INSERT INTO tasks(id,idea_id,question,creator_id,created) VALUES ('old-task','old-idea','Existing queue','old-human',1)")
    backup = upgrade(db)
    assert backup.exists() and backup.stat().st_mode & 0o077 == 0
    with sqlite3.connect(backup) as con:
        assert con.execute("SELECT version FROM schema_version").fetchone()[0] == 1
    for _ in range(2):
        initialize(str(db))
    assert upgrade(db) is None
    with connect(str(db)) as con:
        assert con.execute("SELECT version FROM schema_version").fetchone()[0] == 3
        assert con.execute("SELECT origin FROM ideas").fetchone()[0] == "Original text"
        assert con.execute("SELECT digest FROM credentials").fetchone()[0] == "old-digest"
        assert con.execute("SELECT question FROM tasks").fetchone()[0] == "Existing queue"
        assert con.execute("SELECT count(*) FROM idea_origins").fetchone()[0] == 0
        assert con.execute("SELECT count(*) FROM agenda_topics").fetchone()[0] == 20


def test_unknown_future_schema_is_not_modified(tmp_path):
    db = tmp_path / "future.db"
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE schema_version(version INTEGER)")
        con.execute("INSERT INTO schema_version VALUES (99)")
    with pytest.raises(RuntimeError): initialize(str(db))
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [("schema_version",)]
