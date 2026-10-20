"""API behaviour that doesn't need a model: auth, roles, rate limits, logging. Database tests skip if it's down."""

import json

import jwt
import psycopg
import pytest
from fastapi.testclient import TestClient

from app import api
from app.config import db_url

OWNER, STAFF = "owner-password-123", "staff-password-123"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "ROLE_PASSWORDS", {"owner": OWNER, "staff": STAFF})
    monkeypatch.setattr(api, "JWT_SECRET", "test-secret")
    monkeypatch.setattr(api, "LOG", tmp_path / "requests.jsonl")
    api.recent_requests.clear()
    return TestClient(api.app)


def token(client, password):
    response = client.post("/auth/token", json={"password": password})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_wrong_password_is_rejected(client):
    assert client.post("/auth/token", json={"password": "nope-nope"}).status_code == 401


def test_token_carries_the_role(client):
    body = client.post("/auth/token", json={"password": STAFF}).json()
    assert body["role"] == "staff"
    assert jwt.decode(body["access_token"], "test-secret", algorithms=["HS256"])["role"] == "staff"


def test_endpoints_need_a_token(client):
    assert client.post("/search", json={"question": "halal?"}).status_code == 401
    assert client.post("/search", json={"question": "halal?"}, headers={"Authorization": "Bearer forged"}).status_code == 401


def test_raw_sql_is_owners_only(client):
    assert client.post("/sql", json={"sql": "SELECT 1"}, headers=token(client, STAFF)).status_code == 403


def test_rate_limit(client, monkeypatch):
    monkeypatch.setattr(api, "RATE_LIMIT", 2)
    monkeypatch.setattr(api, "ask", lambda q: (_ for _ in ()).throw(AssertionError("model must not run")))
    headers = token(client, OWNER)
    user = {"sub": "owner", "role": "owner"}
    api.rate_limited(user)
    api.rate_limited(user)
    with pytest.raises(api.HTTPException) as err:
        api.rate_limited(user)
    assert err.value.status_code == 429
    assert client.post("/ask/sql", json={"question": "busiest night?"}, headers=headers).status_code == 429


def test_requests_are_logged(client):
    client.post("/auth/token", json={"password": "nope-nope"})
    entry = json.loads(api.LOG.read_text().splitlines()[-1])
    assert entry["path"] == "/auth/token" and entry["status"] == 401 and "latency_ms" in entry


@pytest.fixture
def database():
    try:
        psycopg.connect(db_url(readonly=True), connect_timeout=3).close()
    except psycopg.OperationalError:
        pytest.skip("database not running (docker compose up -d db)")


def test_owner_can_run_validated_sql(client, database):
    headers = token(client, OWNER)
    ok = client.post("/sql", json={"sql": "SELECT count(*) AS nights FROM daily_sales"}, headers=headers).json()
    assert ok["error"] is None and ok["rows"][0][0] > 0
    bad = client.post("/sql", json={"sql": "DROP TABLE orders"}, headers=headers).json()
    assert bad["error"].startswith("rejected")


def test_search_returns_citations(client, database):
    hits = client.post("/search", json={"question": "Is the chicken halal?"}, headers=token(client, OWNER)).json()["hits"]
    assert hits[0]["citation"] == "policies.md › Halal"


# ---------- phone app ----------

def test_phone_app_cookie_sign_in(client):
    assert client.get("/session").status_code == 401
    response = client.post("/login", json={"password": OWNER})
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie.replace("samesite", "SameSite")
    assert client.get("/session").json() == {"role": "owner"}


def test_lockout_after_repeated_wrong_passwords(client, monkeypatch):
    monkeypatch.setitem(api.failed_logins, "count", 0)
    monkeypatch.setattr(api, "MAX_FAILED_LOGINS", 3)
    for _ in range(3):
        assert client.post("/login", json={"password": "wrong-guess"}).status_code == 401
    assert client.post("/login", json={"password": OWNER}).status_code == 429  # even the right one, until restart


def test_chat_streams_and_keeps_history_per_session(client, monkeypatch):
    def fake_answer(question, retriever, history, stream_to):
        stream_to.write("Saturday ")
        stream_to.write("is busiest.")
        history.append(question)

    monkeypatch.setattr(api.chatbot, "answer", fake_answer)
    monkeypatch.setattr(api, "retriever", lambda: None)
    client.post("/login", json={"password": OWNER})
    assert client.post("/chat", json={"question": "Which night is busiest?"}).text == "Saturday is busiest."
    assert list(api.chat_histories.values())[-1] == ["Which night is busiest?"]


def test_app_files_are_served(client):
    assert "Grill House Assistant" in client.get("/").text
    assert client.get("/manifest.webmanifest").json()["short_name"] == "Grill House"
    assert client.get("/static/icon-192.png").headers["content-type"] == "image/png"
    assert client.get("/static/..%2Fapi.py").status_code == 404
    assert client.get("/static/index.html").status_code == 404  # only icons from /static


def test_private_network_mode(client, monkeypatch):
    import ipaddress
    monkeypatch.setattr(api, "ALLOWED_NETWORKS", [ipaddress.ip_network("100.64.0.0/10")])
    assert client.get("/").status_code == 403  # TestClient's address isn't on the allowlist
    monkeypatch.setattr(api, "ALLOWED_NETWORKS", [])  # public mode: any network
    assert client.get("/").status_code == 200
