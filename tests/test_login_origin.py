"""Login policy regressions; HTTP tests do not emulate browser header generation."""
import pytest
from fastapi.testclient import TestClient

from catalyst.app import Settings, create_app
from catalyst.db import issue_human


@pytest.mark.parametrize("base_url", ["http://127.0.0.1:8000", "http://localhost:8000"])
def test_login_page_preserves_same_origin_form_metadata(tmp_path, base_url):
    path = str(tmp_path / "login.db")
    app = create_app(Settings(database=path))
    with TestClient(app, base_url=base_url) as client:
        page = client.get("/login")
        assert page.status_code == 200
        # no-referrer causes a browser's native form POST to send Origin: null.
        # same-origin preserves that header locally without disclosing referrers
        # to external sites. TestClient itself does not implement this policy.
        assert page.headers["referrer-policy"] == "same-origin"
        assert "form-action 'self'" in page.headers["content-security-policy"]
        invitation = issue_human(path, "Local reviewer", reviewer=True)
        result = client.post("/login", data={"token": invitation},
                             headers={"Origin": base_url}, follow_redirects=False)
        assert result.status_code == 303
        assert result.headers["location"] == "/"
        assert "HttpOnly" in result.headers["set-cookie"]
        assert "SameSite=strict" in result.headers["set-cookie"]
        identity = client.get("/api/me")
        assert identity.status_code == 200
        assert identity.json()["name"] == "Local reviewer"
        assert identity.json()["reviewer"] == 1
        assert client.post("/login", data={"token": invitation},
                           headers={"Origin": base_url}).status_code == 401


@pytest.mark.parametrize("origin", [
    "null",
    "https://foreign.example",
    "http://localhost:8000",       # Different host, even on the same machine.
    "http://127.0.0.1:8001",       # Different port.
    "https://127.0.0.1:8000",      # Different scheme.
    "http://127.0.0.1.evil.example:8000",
])
def test_rejected_origin_does_not_consume_invitation(tmp_path, origin):
    path = str(tmp_path / "login.db")
    base_url = "http://127.0.0.1:8000"
    app = create_app(Settings(database=path))
    with TestClient(app, base_url=base_url) as client:
        invitation = issue_human(path, "Invited reader")
        rejected = client.post("/login", data={"token": invitation},
                               headers={"Origin": origin}, follow_redirects=False)
        assert rejected.status_code == 403
        assert rejected.json() == {"detail": "Cross-origin sign-in rejected"}
        assert "set-cookie" not in rejected.headers
        assert client.get("/api/me").status_code == 401
        # An origin rejection must leave the invitation available for retry.
        accepted = client.post("/login", data={"token": invitation},
                               headers={"Origin": base_url}, follow_redirects=False)
        assert accepted.status_code == 303
        assert client.get("/api/me").json()["name"] == "Invited reader"
