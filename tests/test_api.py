from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from api.main import app
from src.auth import create_token, hash_password, validate_credentials, verify_password


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def account(client):
    email = f"{uuid.uuid4().hex[:12]}@example.com"
    res = client.post(
        "/api/auth/signup",
        json={"name": "Test User", "email": email, "password": "correct-horse"},
    )
    assert res.status_code == 200
    body = res.json()
    return {"email": email, "token": body["token"], "headers": {"Authorization": f"Bearer {body['token']}"}}


def test_password_hash_roundtrip():
    h = hash_password("correct-horse")
    assert h != "correct-horse"
    assert verify_password("correct-horse", h)
    assert not verify_password("wrong", h)


def test_credential_validation():
    assert validate_credentials("nope", "correct-horse") is not None
    assert validate_credentials("a@b.co", "short") is not None
    assert validate_credentials("a@b.co", "correct-horse") is None


def test_token_roundtrip():
    from src.auth import decode_token

    payload = decode_token(create_token(7, "a@b.co"))
    assert payload["sub"] == "7"
    assert decode_token("garbage") is None


def test_health_is_public(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["chunks"] > 0
    assert len(body["documents"]) == 5


def test_endpoints_require_authentication(client):
    assert client.post("/api/chat", json={"question": "hi"}).status_code == 401
    assert client.post("/api/search", json={"query": "hi"}).status_code == 401
    assert client.get("/api/conversations").status_code == 401
    assert client.get("/api/auth/me").status_code == 401


def test_duplicate_signup_is_rejected(client, account):
    res = client.post(
        "/api/auth/signup",
        json={"name": "Someone", "email": account["email"], "password": "correct-horse"},
    )
    assert res.status_code == 409


def test_login_rejects_wrong_password(client, account):
    res = client.post("/api/auth/login", json={"email": account["email"], "password": "nope"})
    assert res.status_code == 401


def test_login_succeeds(client, account):
    res = client.post(
        "/api/auth/login", json={"email": account["email"], "password": "correct-horse"}
    )
    assert res.status_code == 200
    assert res.json()["token"]


def test_invalid_token_is_rejected(client):
    res = client.get("/api/auth/me", headers={"Authorization": "Bearer nonsense"})
    assert res.status_code == 401


def test_search_returns_scored_sources(client, account):
    body = client.post(
        "/api/search",
        json={"query": "how do I factory reset the router"},
        headers=account["headers"],
    ).json()
    assert body["sources"]
    for s in body["sources"]:
        assert s["retriever"] in {"vector", "keyword"}


def test_search_respects_top_k(client, account):
    body = client.post(
        "/api/search", json={"query": "billing", "top_k": 2}, headers=account["headers"]
    ).json()
    assert len(body["sources"]) <= 2


def test_chat_streams_and_persists(client, account):
    events, meta = [], None
    pending = None
    with client.stream(
        "POST",
        "/api/chat",
        json={"question": "What does the RX-900 cost?"},
        headers=account["headers"],
    ) as res:
        assert res.status_code == 200
        for line in res.iter_lines():
            if line.startswith("event:"):
                pending = line.split(":", 1)[1].strip()
                events.append(pending)
            elif line.startswith("data:") and pending == "meta" and meta is None:
                meta = json.loads(line.split(":", 1)[1].strip())

    assert events[0] == "meta"
    assert "token" in events
    assert events[-1] == "done"
    assert meta["prompt_tokens"] > 0
    assert meta["sources"]

    convo_id = meta["conversation_id"]
    stored = client.get(f"/api/conversations/{convo_id}", headers=account["headers"]).json()
    assert [m["role"] for m in stored] == ["user", "assistant"]
    assert stored[1]["sources"]


def test_conversations_are_scoped_to_their_owner(client, account):
    mine = client.get("/api/conversations", headers=account["headers"]).json()
    assert mine

    other = client.post(
        "/api/auth/signup",
        json={"name": "Other", "email": f"{uuid.uuid4().hex[:12]}@example.com", "password": "correct-horse"},
    ).json()
    headers = {"Authorization": f"Bearer {other['token']}"}

    assert client.get("/api/conversations", headers=headers).json() == []
    assert client.get(f"/api/conversations/{mine[0]['id']}", headers=headers).status_code == 404


def test_conversation_delete(client, account):
    convos = client.get("/api/conversations", headers=account["headers"]).json()
    target = convos[0]["id"]
    assert client.delete(f"/api/conversations/{target}", headers=account["headers"]).status_code == 200
    assert client.get(f"/api/conversations/{target}", headers=account["headers"]).status_code == 404
