# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.

"""Tests for the local request guard and the static path containment."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from assistant.security import LocalRequestGuard, safe_join


def _client(monkeypatch, bind_host="localhost", allowed=""):
    monkeypatch.setenv("DESKAGENT_BIND_HOST", bind_host)
    monkeypatch.setenv("DESKAGENT_ALLOWED_HOSTS", allowed)
    app = FastAPI()

    @app.get("/data")
    def data():
        return {"ok": True}

    @app.post("/shutdown")
    def shutdown():
        return {"ok": True}

    app.add_middleware(LocalRequestGuard)
    return TestClient(app)


# region safe_join

def test_safe_join_inside_base_returns_path(tmp_path):
    (tmp_path / "js").mkdir()
    (tmp_path / "js" / "app.js").write_text("x")
    assert safe_join(tmp_path / "js", "app.js") == (tmp_path / "js" / "app.js").resolve()


@pytest.mark.parametrize("name", ["../secret.txt", "../../etc/passwd", "sub/../../secret.txt"])
def test_safe_join_traversal_returns_none(tmp_path, name):
    (tmp_path / "js").mkdir()
    (tmp_path / "secret.txt").write_text("x")
    assert safe_join(tmp_path / "js", name) is None


def test_safe_join_absolute_path_returns_none(tmp_path):
    (tmp_path / "js").mkdir()
    assert safe_join(tmp_path / "js", str(tmp_path / "secret.txt")) is None

# endregion


# region host check

@pytest.mark.parametrize("host", ["localhost:8765", "127.0.0.1:8765", "[::1]:8765", "localhost"])
def test_loopback_host_allowed(monkeypatch, host):
    client = _client(monkeypatch)
    assert client.get("/data", headers={"Host": host}).status_code == 200


def test_rebinding_host_rejected(monkeypatch):
    client = _client(monkeypatch)
    assert client.get("/data", headers={"Host": "attacker.example:8765"}).status_code == 403


def test_network_mode_without_list_skips_host_check(monkeypatch):
    client = _client(monkeypatch, bind_host="0.0.0.0")
    assert client.get("/data", headers={"Host": "deskagent.example.com"}).status_code == 200


def test_network_mode_with_list_enforces_it(monkeypatch):
    client = _client(monkeypatch, bind_host="0.0.0.0", allowed="deskagent.example.com")
    assert client.get("/data", headers={"Host": "deskagent.example.com"}).status_code == 200
    assert client.get("/data", headers={"Host": "attacker.example"}).status_code == 403

# endregion


# region origin check

def test_post_without_origin_allowed(monkeypatch):
    client = _client(monkeypatch)
    assert client.post("/shutdown", headers={"Host": "localhost:8765"}).status_code == 200


def test_post_from_local_ui_allowed(monkeypatch):
    client = _client(monkeypatch)
    r = client.post("/shutdown", headers={"Host": "localhost:8765", "Origin": "http://localhost:8765"})
    assert r.status_code == 200


@pytest.mark.parametrize("origin", ["https://attacker.example", "null"])
def test_cross_site_post_rejected(monkeypatch, origin):
    client = _client(monkeypatch)
    r = client.post("/shutdown", headers={"Host": "localhost:8765", "Origin": origin})
    assert r.status_code == 403


def test_cross_site_get_with_origin_not_blocked_by_origin_check(monkeypatch):
    # Reads are protected by the Host check and CORS, not the Origin check.
    client = _client(monkeypatch)
    r = client.get("/data", headers={"Host": "localhost:8765", "Origin": "https://attacker.example"})
    assert r.status_code == 200


def test_network_mode_same_origin_post_allowed(monkeypatch):
    client = _client(monkeypatch, bind_host="0.0.0.0")
    r = client.post("/shutdown", headers={"Host": "deskagent.example.com",
                                          "Origin": "https://deskagent.example.com"})
    assert r.status_code == 200

# endregion
