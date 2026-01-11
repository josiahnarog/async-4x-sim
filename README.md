# Async 4X Sim (MVP)

Text-first, turn-based 4X prototype engine with a minimal web UI.

## Run locally (venv)

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

Run:

```powershell
python -m uvicorn app:app --reload
```

Open:
- http://127.0.0.1:8000/
- http://127.0.0.1:8000/health

### DB location

The server stores state in SQLite. By default it uses a stable path in the project (or you can override):

```powershell
$env:ASYNC4X_DB_PATH = "C:\path\to\games.db"
python -m uvicorn app:app --reload
```

## Run with Docker (recommended for deployment parity)

Build:

```powershell
docker build -t async4x .
```

Run with persistent storage:

```powershell
docker run --rm -p 8000:8000 -v ${PWD}\data:/data async4x
```

This mounts `./data` into the container at `/data`, so SQLite persists across restarts.

## Multiplayer MVP rule

Only the active player can submit state-changing commands. Other viewers can observe.
