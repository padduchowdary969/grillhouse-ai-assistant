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
