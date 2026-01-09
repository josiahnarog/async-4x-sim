import os
import pytest


def test_non_active_player_cannot_pass(tmp_path):
    pytest.importorskip("fastapi")
    pytest.importorskip("starlette")

    os.environ["ASYNC4X_DB_PATH"] = str(tmp_path / "games.db")

    from fastapi.testclient import TestClient
    from app import app

    client = TestClient(app)

    # Create a game; scenario starts with active player A.
    r = client.post("/games")
    assert r.status_code == 200
    game_id = r.json()["game_id"]

    # Viewer B tries to mutate state (pass) while A is active -> forbidden.
    r = client.post(f"/games/{game_id}/command", json={"viewer": "B", "command": "pass"})
    assert r.status_code == 403
    assert "Not your turn" in r.text
