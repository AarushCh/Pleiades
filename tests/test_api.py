from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from api.main import app
from src import config
from src.auth import create_token, hash_password, validate_credentials, verify_password


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _no_carried_cookies(client):
    client.cookies.clear()


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


def test_client_ip_is_the_one_the_proxies_saw_not_the_one_the_client_wrote(monkeypatch):
    from starlette.requests import Request

    from api.deps import client_ip

    def seen(forwarded: str) -> str:
        headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
        return client_ip(Request({"type": "http", "headers": headers, "client": ("10.0.0.9", 443)}))

    monkeypatch.setattr(config, "PROXY_HOPS", 2)
    assert seen("203.0.113.7, 10.0.0.1") == "203.0.113.7"
    assert seen("6.6.6.6, 203.0.113.7, 10.0.0.1") == "203.0.113.7"
    assert seen("203.0.113.7") == "203.0.113.7"
    monkeypatch.setattr(config, "PROXY_HOPS", 0)
    assert seen("6.6.6.6, 203.0.113.7, 10.0.0.1") == "10.0.0.9"


def test_signup_is_rate_limited(client):
    from api.deps import _HITS

    _HITS.clear()
    codes = [
        client.post(
            "/api/auth/signup",
            json={"name": "X", "email": "not-an-email", "password": "correct-horse"},
        ).status_code
        for _ in range(12)
    ]
    _HITS.clear()
    assert codes[0] == 422
    assert 429 in codes


def test_token_roundtrip():
    from src.auth import decode_token

    payload = decode_token(create_token(7, "a@b.co", 3))
    assert payload["sub"] == "7"
    assert payload["tid"] == "3"
    assert decode_token("garbage") is None


def test_health_is_public(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["chunks"] > 0
    assert len(body["documents"]) == 5
    assert client.head("/api/health").status_code == 200


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
    events, meta, done = [], None, None
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
            elif line.startswith("data:") and pending == "done":
                done = json.loads(line.split(":", 1)[1].strip())

    assert events[0] == "meta"
    assert "token" in events
    assert events[-1] == "done"
    assert done["outcome"] in {"answered", "escalated"}
    assert done["attempts"] >= 1
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


@pytest.fixture
def promote():
    from src.db import grant_admin

    promoted = []

    def grant(email: str) -> None:
        assert grant_admin(email)
        promoted.append(email)

    yield grant
    for email in promoted:
        grant_admin(email, on=False)


def test_admin_comes_from_the_account_not_the_email(client, account, promote):
    assert client.get("/api/auth/me", headers=account["headers"]).json()["admin"] is False
    promote(account["email"])
    assert client.get("/api/auth/me", headers=account["headers"]).json()["admin"] is True


def test_reseed_requires_an_admin(client, account):
    res = client.post("/api/admin/reseed", headers=account["headers"])
    assert res.status_code == 403


def test_reseed_rebuilds_the_live_assistant(client, account, promote):
    import api.main as main

    promote(account["email"])
    before = main.STATE["bots"][config.DEFAULT_TENANT]

    res = client.post("/api/admin/reseed", headers=account["headers"])
    assert res.status_code == 200, res.text

    body = res.json()
    assert body["chunks"] > 0
    after = main.STATE["bots"][config.DEFAULT_TENANT]
    assert after is not before
    assert len(after.chunks) == body["chunks"]


def test_daily_chat_quota(client, monkeypatch):
    other = client.post(
        "/api/auth/signup",
        json={"name": "Quota", "email": f"{uuid.uuid4().hex[:12]}@example.com", "password": "correct-horse"},
    ).json()
    headers = {"Authorization": f"Bearer {other['token']}"}
    monkeypatch.setattr(config, "CHAT_DAILY_LIMIT", 1)

    def ask() -> int:
        with client.stream("POST", "/api/chat", json={"question": "What does the RX-900 cost?"},
                           headers=headers) as res:
            res.read()
            return res.status_code

    assert ask() == 200
    assert ask() == 429


def test_sign_in_sets_a_session_cookie_scripts_cannot_read(client, account):
    res = client.post("/api/auth/login", json={"email": account["email"], "password": "correct-horse"})
    cookie = res.headers["set-cookie"].lower()
    for part in ("pleiades_session=", "httponly", "samesite=strict", "path=/api"):
        assert part in cookie


def test_sign_out_revokes_the_cookie_and_every_earlier_token(client):
    body = client.post(
        "/api/auth/signup",
        json={"name": "Out", "email": f"{uuid.uuid4().hex[:12]}@example.com", "password": "correct-horse"},
    ).json()
    earlier = {"Authorization": f"Bearer {body['token']}"}
    assert client.get("/api/auth/me").status_code == 200
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers=earlier).status_code == 401


def ask(client, headers, question="What does the RX-900 cost?") -> dict:
    done, pending = None, None
    with client.stream("POST", "/api/chat", json={"question": question}, headers=headers) as res:
        for line in res.iter_lines():
            if line.startswith("event:"):
                pending = line.split(":", 1)[1].strip()
            elif line.startswith("data:") and pending == "done":
                done = json.loads(line.split(":", 1)[1].strip())
    return done


def test_answers_can_be_rated_and_complaints_reach_triage(client, account, promote):
    done = ask(client, account["headers"])
    target = f"/api/messages/{done['message_id']}/feedback"
    assert client.post(target, json={"rating": 0}, headers=account["headers"]).status_code == 422
    res = client.post(target, json={"rating": -1, "reason": "Wrong price"}, headers=account["headers"])
    assert res.status_code == 200

    stored = client.get(f"/api/conversations/{done['conversation_id']}", headers=account["headers"]).json()
    assert stored[-1]["id"] == done["message_id"]
    assert stored[-1]["rating"] == -1

    assert client.get("/api/admin/feedback", headers=account["headers"]).status_code == 403
    promote(account["email"])
    [newest, *_] = client.get("/api/admin/feedback", headers=account["headers"]).json()
    assert newest["id"] == done["message_id"]
    assert newest["reason"] == "Wrong price"
    assert newest["question"] == "What does the RX-900 cost?"


def test_only_the_owner_can_rate_an_answer(client, account):
    done = ask(client, account["headers"])
    other = client.post(
        "/api/auth/signup",
        json={"name": "Rater", "email": f"{uuid.uuid4().hex[:12]}@example.com", "password": "correct-horse"},
    ).json()
    res = client.post(f"/api/messages/{done['message_id']}/feedback", json={"rating": 1},
                      headers={"Authorization": f"Bearer {other['token']}"})
    assert res.status_code == 404


def test_health_reports_the_schema_revision(client):
    from src import db

    assert client.get("/api/health").json()["schema_revision"] == db.head()


def test_a_failing_answer_does_not_leak_internals(client, account, monkeypatch, capsys):
    import api.main as main

    def explode(*_args, **_kwargs):
        raise RuntimeError("password=hunter2 at db.internal:5432")

    monkeypatch.setattr(main.STATE["bots"][config.DEFAULT_TENANT].graph, "stream", explode)
    with client.stream("POST", "/api/chat", json={"question": "hello"}, headers=account["headers"]) as res:
        body = "".join(res.iter_text())
    assert "event: error" in body
    assert "hunter2" not in body and "db.internal" not in body
    assert "hunter2" in capsys.readouterr().err


def test_pages_and_api_carry_security_headers(client):
    for path in ("/api/health", "/"):
        headers = client.get(path).headers
        policy = headers["content-security-policy"]
        assert "frame-ancestors 'none'" in policy and "unsafe-inline" not in policy.split("style-src")[0]
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["strict-transport-security"].startswith("max-age=")
