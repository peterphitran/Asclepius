# Development

See [status](status.md) for current implementation boundaries. CLI execution is not available
yet. Configuration validation works without a daemon, API server, or database service.

## CLI foundation

From `backend/` in a separate active Python environment, choose the matching hashed lock:

```text
python -m pip install --require-hashes -r requirements-cli-wsl.lock
python -m pip install --no-deps -e .
asclepius --help
asclepius config validate examples/groq-target.toml --json
asclepius config validate examples/groq-evaluator.toml --kind evaluator --json
python -m pytest
python -m ruff check asclepius tests/cli
```

Use `requirements-cli-windows.lock` on native Windows. Locks were resolved with Python
3.12 on WSL and Python 3.13 on Windows. They currently include legacy dependencies too.
Do not apply them to an unrelated environment or replace the original checkout's `.venv`.
Validation checks secret references, not secret values or provider availability. No key
is needed to validate the examples. Operational commands currently exit 5 with
`not_implemented`; accepting a command name is not proof that its feature works.

To regenerate a lock in its matching platform environment:

```text
python -m piptools compile --extra dev --generate-hashes --allow-unsafe --strip-extras --no-emit-index-url --output-file requirements-cli-wsl.lock pyproject.toml
```

Change the output filename for Windows. A built wheel was also installed and exercised
outside the source directory on each platform. Recorded proof is in
[the Task 1 evidence](verification/evidence/cli-foundation.json).

## Python environment

Use Python 3.12 or newer and an environment compatible with the operating system.

For a fresh checkout without an existing environment, run from `backend/`:

```text
python -m venv .venv
```

Activate with `source .venv/bin/activate` on Linux/WSL, or
`.venv\Scripts\Activate.ps1` in native Windows PowerShell. The existing environment
in the original checkout is Linux-based: use it through WSL, not as a Windows executable.
Do not replace it merely to run from another shell.

From `backend/`, with the chosen environment active:

```text
python -m pip install -e ".[dev]"
```

Settings load from environment variables or `backend/.env`; inspect
[config.py](../backend/app/config.py) and [.env.example](../backend/.env.example).
The latter still reflects the existing API configuration.

## Start and inspect the API

```text
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

From another terminal:

```bash
curl --fail-with-body http://127.0.0.1:8000/health
curl --fail-with-body http://127.0.0.1:8000/openapi.json
```

Interactive API docs are at `http://127.0.0.1:8000/docs`. Stop an instance you launched
with Ctrl+C. API health does not check database or evaluation readiness.

## Database-backed paths

From `backend/`, using a disposable development Postgres database:

```text
docker compose up -d postgres
python -m alembic upgrade head
python -m alembic current
```

These commands change the database selected by `DATABASE_URL`. They do not create
the future SQLite store. API data routes require a matching schema and authenticated
fixture user. Redis does not need to be started for current application execution.

`python -m app.seed` clears domain tables and inserts demo records. It is optional,
destructive to those records, and unsuitable for a database containing work to keep.

## Checks

```text
python -m pytest
python -m ruff check app tests
```

Use the [verification guide](verification.md) to distinguish source checks, unit tests,
API behavior, and a future complete CLI evaluation.
