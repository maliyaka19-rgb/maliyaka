"""Tests for project / filesystem management endpoints (create, delete, recent)."""
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import fs_routes
import project_routes


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(fs_routes, "RECENT_FILE", str(tmp_path / "recent.json"))
    monkeypatch.setattr(fs_routes, "_current_workdir", str(tmp_path))
    monkeypatch.setattr(fs_routes, "_project_open", True)
    monkeypatch.setattr(project_routes, "WORKING_DIR", str(tmp_path))

    app = FastAPI()
    app.include_router(fs_routes.router)
    app.include_router(project_routes.router)
    return TestClient(app)


def test_create_project_ok(client, tmp_path):
    r = client.post("/api/v1/fs/create-project", json={"path": str(tmp_path), "name": "myproj"})
    assert r.status_code == 200
    assert r.json()["success"] is True
    assert (tmp_path / "myproj").is_dir()


def test_create_project_conflict_and_bad_name(client, tmp_path):
    (tmp_path / "exists").mkdir()
    assert client.post("/api/v1/fs/create-project",
                       json={"path": str(tmp_path), "name": "exists"}).status_code == 409
    assert client.post("/api/v1/fs/create-project",
                       json={"path": str(tmp_path), "name": "bad/name"}).status_code == 400
    assert client.post("/api/v1/fs/create-project",
                       json={"path": str(tmp_path), "name": "   "}).status_code == 400


def test_delete_project_ok(client, tmp_path):
    p = tmp_path / "delme"
    p.mkdir()
    (p / "f.txt").write_text("x", encoding="utf-8")
    r = client.delete("/api/v1/fs/project", params={"path": str(p)})
    assert r.status_code == 200
    assert not p.exists()


def test_delete_project_missing_and_protected(client, tmp_path):
    assert client.delete("/api/v1/fs/project",
                         params={"path": str(tmp_path / "nope")}).status_code == 404
    home = os.path.abspath(os.path.expanduser("~"))
    assert client.delete("/api/v1/fs/project", params={"path": home}).status_code == 403


def test_recent_single_removal(client, tmp_path):
    fs_routes._save_recent([
        {"name": "a", "path": str(tmp_path / "a")},
        {"name": "b", "path": str(tmp_path / "b")},
    ])
    r = client.delete("/api/v1/fs/recent-projects", params={"path": str(tmp_path / "a")})
    assert r.status_code == 200 and r.json()["removed"] == 1
    remaining = fs_routes._load_recent()
    assert len(remaining) == 1 and remaining[0]["name"] == "b"


def test_recent_clear_all(client, tmp_path):
    fs_routes._save_recent([{"name": "a", "path": str(tmp_path / "a")}])
    r = client.delete("/api/v1/fs/recent-projects")
    assert r.status_code == 200 and fs_routes._load_recent() == []


def test_path_traversal_rejected(client):
    r = client.get("/api/v1/project/file", params={"path": "../../../../etc/passwd"})
    assert r.status_code in (403, 404)


def test_delete_project_root_refused(client):
    r = client.delete("/api/v1/project/file", params={"path": "."})
    assert r.status_code == 403
