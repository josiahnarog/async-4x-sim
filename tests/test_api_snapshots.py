import os
import pytest


def test_api_save_and_load_snapshot_smoke(tmp_path):
    pytest.importorskip("fastapi")
    pytest.importorskip("starlette")

    os.environ["ASYNC4X_DB_PATH"] = str(tmp_path / "games.db")

    from fastapi.testclient import TestClient
    from app import app

    client = TestClient(app)

    r = client.post("/games")
    assert r.status_code == 200
    game_id = r.json()["game_id"]

    # Save a snapshot
    r = client.post(f"/games/{game_id}/command", json={"viewer": "A", "command": "save s1"})
    assert r.status_code == 200
    assert "Saved snapshot" in "\n".join(r.json()["events"])

    # Make a state change (pass)
    r = client.post(f"/games/{game_id}/command", json={"viewer": "A", "command": "pass"})
    assert r.status_code == 200

    # After passing, active player should be B; snapshot load is state-mutating and must be done by active.
    r = client.post(f"/games/{game_id}/command", json={"viewer": "B", "command": "load s1"})
    assert r.status_code == 200
    assert "Loaded snapshot" in "\n".join(r.json()["events"])
