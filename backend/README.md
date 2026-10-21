# Existing Backend

The published backend contains the initial FastAPI health endpoint and development
configuration. The project is moving toward a [personal CLI](../docs/specs/2026-10-21-personal-cli-direction.md);
its SQLite store, daemon, and evaluation engine have not been implemented.

The original development checkout has additional unpublished API, database, auth, and
lifecycle work. That work is excluded from the frontend-removal and documentation PRs.
See the [checkpoint inventory](../docs/current-state.md) before following instructions
that assume migrations or database-backed endpoints exist.

## Requirements

Python 3.12 or newer, matching `pyproject.toml`.

The published health endpoint does not need Postgres or Redis. Compose provides both
as legacy development infrastructure; it does not start the API or a worker.

## Environment setup

From the repository root, create a native Windows environment if using PowerShell:

```powershell
cd backend
python -m venv .venv-windows
.venv-windows\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

For WSL/Linux, use a Linux environment:

```bash
cd /mnt/c/Users/ptran/Downloads/Projects/Asclepius/backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

The WSL path is specific to the original checkout; substitute your backend directory.
Use a Python 3.12+ interpreter to create the environment. The original checkout's
existing `.venv` is Linux-based and should be invoked from WSL, not as
`.venv/bin/python.exe` from Windows.

Settings load from environment variables or `backend/.env`. The committed
`.env.example` describes the legacy configuration, including browser CORS origins.
See [config.py](app/config.py) for settings present in your checkpoint.

## Run the published API

From `backend/`, with the Python environment active:

```text
python -m uvicorn app.main:app --reload
```

- Process health: `http://localhost:8000/health`.
- Interactive API docs: `http://localhost:8000/docs`.

The health response reports process metadata. It does not verify database connectivity,
a running worker, or successful evaluation.

## Additional local database/API work

This section applies only to the more advanced original checkout. The published cleanup
branches do not include its Alembic files, database models, seed script, or auth routes.

Where those files and their dependencies are present, database-backed endpoints use
Postgres. From that checkout's `backend/` directory:

```text
docker compose up -d postgres
python -m alembic upgrade head
python -m alembic current
python -m uvicorn app.main:app --reload
```

Migration commands change the configured Postgres database; they do not create the
proposed SQLite CLI store. Local JWT settings also remain part of the legacy API,
not a sign-in requirement for the planned CLI.

The local command `python -m app.seed` clears domain tables and recreates clinical
demo records. Run it only against a disposable demo database. It is not normal startup
and does not generate real evaluation findings.

Redis is unused by the application execution path and is not required for the CLI direction.

## Tests and lint

From `backend/`, with the appropriate environment active:

```text
python -m pytest
python -m ruff check app tests
```

The published baseline has a health test. The additional local checkout includes
security and fake-session lifecycle tests; those do not prove live Postgres concurrency
or a complete background evaluation.

## Published layout

```text
app/api/health.py  Process health router
app/config.py     Environment configuration
app/main.py       API factory
tests/            Health test
docker-compose.yml
```

Use the [inventory](../docs/current-state.md) for additional local source paths and
the [archive](../docs/archive/web-platform/README.md) for historical plans.
