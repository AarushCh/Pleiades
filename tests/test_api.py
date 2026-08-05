from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.sessions import SessionStore


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health_reports_index_and_backend(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["chunks"] > 0
    assert body["top_k"] >= 1
    assert len(body["documents"]) == 5


def test_search_returns_scored_sources(client):
    res = client.post("/api/search", json={"query": "how do I factory reset the router"})
    assert res.status_code == 200
    body = res.json()
    assert body["sources"]
    assert body["elapsed_ms"] > 0
    for s in body["sources"]:
        assert s["retriever"] in {"vector", "keyword"}
        assert s["excerpt"]


def test_search_respects_top_k(client):
    body = client.post("/api/search", json={"query": "billing", "top_k": 2}).json()
    assert len(body["sources"]) <= 2


def test_search_rejects_empty_query(client):
    assert client.post("/api/search", json={"query": ""}).status_code == 422


def test_chat_streams_meta_tokens_and_done(client):
    with client.stream("POST", "/api/chat", json={"question": "How do I factory reset?"}) as res:
        assert res.status_code == 200
        events = []
        for line in res.iter_lines():
            if line.startswith("event:"):
                events.append(line.split(":", 1)[1].strip())
    assert events[0] == "meta"
    assert "token" in events
    assert events[-1] == "done"


def test_chat_meta_carries_sources_and_session(client):
    with client.stream("POST", "/api/chat", json={"question": "What is the RX-900 price?"}) as res:
        meta = None
        pending = None
        for line in res.iter_lines():
            if line.startswith("event:"):
                pending = line.split(":", 1)[1].strip()
            elif line.startswith("data:") and pending == "meta":
                meta = json.loads(line.split(":", 1)[1].strip())
                break
    assert meta["session_id"]
    assert meta["sources"]
    assert meta["prompt_tokens"] > 0


def test_session_reset_clears_turns(client):
    sid = "pytest-session"
    client.post("/api/chat", json={"question": "hello", "session_id": sid}).read()
    body = client.post(f"/api/session/{sid}/reset").json()
    assert body["turns"] == 0


def test_session_store_isolates_conversations():
    store = SessionStore()
    a = store.get(None)
    b = store.get(None)
    a.history.append(("q", "a"))
    assert a.id != b.id
    assert b.history == []
    assert store.get(a.id).history == [("q", "a")]


def test_session_store_reset_is_idempotent():
    store = SessionStore()
    s = store.get("abc")
    s.history.append(("q", "a"))
    assert store.reset("abc").history == []
    assert store.reset("never-seen").history == []
