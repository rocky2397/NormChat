from config import settings


def test_protected_route_allowed_when_auth_not_configured(client):
    assert not settings.auth_username
    assert not settings.auth_password
    response = client.get("/api/projects")
    assert response.status_code == 200


def test_login_and_protected_route_with_credentials(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_username", "collab")
    monkeypatch.setattr(settings, "auth_password", "secret123")

    unauthenticated = client.get("/api/projects")
    assert unauthenticated.status_code == 401

    bad_login = client.post(
        "/api/auth/login", json={"username": "collab", "password": "wrong"}
    )
    assert bad_login.status_code == 401

    good_login = client.post(
        "/api/auth/login", json={"username": "collab", "password": "secret123"}
    )
    assert good_login.status_code == 200
    assert good_login.json() == {"ok": True}

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json() == {"authenticated": True}

    authenticated = client.get("/api/projects")
    assert authenticated.status_code == 200

    logout = client.post("/api/auth/logout")
    assert logout.status_code == 200

    after_logout = client.get("/api/projects")
    assert after_logout.status_code == 401
