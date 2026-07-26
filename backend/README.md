# Asclepius Backend

FastAPI service and (later) LangGraph agent pipeline for adversarially testing clinical LLMs.
Multi-tenant API that powers the Asclepius dashboard.

## Requirements
- Python 3.12+
- Docker (for Postgres + Redis)

## Setup (Windows PowerShell)
```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```
On macOS/Linux use `source .venv/bin/activate`.

## Run
```powershell
docker compose up -d          # Postgres + Redis
uvicorn app.main:app --reload # API on http://localhost:8000
```
- Health check: http://localhost:8000/health
- Interactive docs: http://localhost:8000/docs

## Test & lint
```powershell
pytest
ruff check .
```

## Layout
```
app/
  main.py        # FastAPI app factory
  config.py      # pydantic-settings
  api/           # routers (health now; targets/campaigns/sweeps/findings/... later)
tests/
docker-compose.yml
```
