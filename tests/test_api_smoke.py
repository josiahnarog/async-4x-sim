import os
import pytest


def test_api_create_and_state_smoke():
    fastapi = pytest.importorskip("fastapi")
    pytest.importorskip("starlette")

    from fastapi.testclient import TestClient

    # Ensure app uses a temp sqlite file for this test.
    # Must be set before importing app module.
    # (pytest tmp_path fixture isn't available here, so use tmp_path_factory via env+tempdir.)
    # We'll use a simple temp file name in cwd under .pytest_tmp if available.
    os.environ["ASYNC4X_DB_PATH"] = os.path.join(os.getcwd(), ".pytest_games.db")

    from app import app

    client = TestClient(app)

    # Create a game
    r = client.post("/games")
    assert r.status_code == 200
    game_id = r.json()["game_id"]
    assert isinstance(game_id, str) and len(game_id) > 0

    # Get state
    r = client.get(f"/games/{game_id}/state?viewer=A")
    assert r.status_code == 200
    data = r.json()
    assert data["game_id"] == game_id
    assert "map_text" in data
    assert "log_tail" in data

    # Submit a pass (should be valid even with no orders)
    r = client.post(f"/games/{game_id}/command", json={"viewer": "A", "command": "pass"})
    assert r.status_code == 200
    out = r.json()
    assert "events" in out
    assert "state" in out
