from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from api.main import app
from src import config
from src.auth import create_token
from src.db import Conversation, Document, SessionLocal, Tenant, User, ensure_tenant, seed_documents
from src.ingest import collection_for

OTHER = "acme-isolation-test"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_rate_limit():
    from api.deps import _HITS

    _HITS.clear()
    yield
    _HITS.clear()


@pytest.fixture(scope="module")
def tenants(client):
    with SessionLocal() as s:
        home = ensure_tenant(s, config.DEFAULT_TENANT, config.DEFAULT_TENANT_NAME)
        away = ensure_tenant(s, OTHER, "Acme Isolation Test")
        return {"home": home.slug, "away": away.slug, "home_id": home.id, "away_id": away.id}


def signup(client, tenant: str, email: str) -> dict:
    res = client.post(
        "/api/auth/signup",
        json={"name": "Isolation", "email": email, "password": "correct-horse"},
        headers={"X-Tenant": tenant},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    return {"email": email, "token": body["token"], "tenant": body["tenant"],
            "headers": {"Authorization": f"Bearer {body['token']}"}}


def test_unknown_tenant_is_rejected(client):
    res = client.post(
        "/api/auth/signup",
        json={"name": "Nobody", "email": "nobody@example.com", "password": "correct-horse"},
        headers={"X-Tenant": "no-such-organisation"},
    )
    assert res.status_code == 404


def test_one_email_can_exist_in_two_tenants(client, tenants):
    email = f"{uuid.uuid4().hex[:12]}@example.com"
    home = signup(client, tenants["home"], email)
    away = signup(client, tenants["away"], email)
    assert home["tenant"] == tenants["home"]
    assert away["tenant"] == tenants["away"]

    with SessionLocal() as s:
        rows = s.scalars(select(User).where(User.email == email)).all()
        assert {r.tenant_id for r in rows} == {tenants["home_id"], tenants["away_id"]}


def test_a_duplicate_email_inside_one_tenant_is_still_rejected(client, tenants):
    email = f"{uuid.uuid4().hex[:12]}@example.com"
    signup(client, tenants["home"], email)
    res = client.post(
        "/api/auth/signup",
        json={"name": "Isolation", "email": email, "password": "correct-horse"},
        headers={"X-Tenant": tenants["home"]},
    )
    assert res.status_code == 409


def test_login_in_the_wrong_tenant_fails(client, tenants):
    email = f"{uuid.uuid4().hex[:12]}@example.com"
    signup(client, tenants["home"], email)
    res = client.post(
        "/api/auth/login",
        json={"email": email, "password": "correct-horse"},
        headers={"X-Tenant": tenants["away"]},
    )
    assert res.status_code == 401


def test_a_conversation_is_invisible_to_the_other_tenant(client, tenants):
    owner = signup(client, tenants["home"], f"{uuid.uuid4().hex[:12]}@example.com")
    intruder = signup(client, tenants["away"], f"{uuid.uuid4().hex[:12]}@example.com")

    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.email == owner["email"]))
        convo = Conversation(tenant_id=user.tenant_id, user_id=user.id, title="Private")
        s.add(convo)
        s.commit()
        convo_id = convo.id

    assert client.get(f"/api/conversations/{convo_id}", headers=owner["headers"]).status_code == 200
    assert client.get(f"/api/conversations/{convo_id}", headers=intruder["headers"]).status_code == 404
    assert client.delete(f"/api/conversations/{convo_id}", headers=intruder["headers"]).status_code == 404
    assert client.get("/api/conversations", headers=intruder["headers"]).json() == []


def test_a_token_cannot_be_moved_to_another_tenant(client, tenants):
    owner = signup(client, tenants["home"], f"{uuid.uuid4().hex[:12]}@example.com")
    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.email == owner["email"]))
        forged = create_token(user.id, user.email, tenants["away_id"])
    res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert res.status_code == 401


def test_documents_do_not_cross_tenants(tenants):
    with SessionLocal() as s:
        written = seed_documents(s, tenants["away_id"])
        assert written >= 0
        home = s.scalars(select(Document).where(Document.tenant_id == tenants["home_id"])).all()
        away = s.scalars(select(Document).where(Document.tenant_id == tenants["away_id"])).all()
        assert home and away
        assert {d.id for d in home}.isdisjoint({d.id for d in away})


def test_each_tenant_gets_its_own_vector_collection(tenants):
    assert collection_for(tenants["home"]) != collection_for(tenants["away"])
    assert collection_for(tenants["away"]).endswith("acme_isolation_test")


def test_a_tenant_slug_is_unique():
    with SessionLocal() as s:
        first = ensure_tenant(s, OTHER)
        again = ensure_tenant(s, OTHER.upper())
        assert first.id == again.id
        assert s.scalar(select(Tenant).where(Tenant.slug == OTHER.upper())) is None
