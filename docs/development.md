# Development

See [status](status.md) for current implementation boundaries. Profile management and persisted
run inspection work. Evaluation execution is not available yet. Configuration validation
works without a daemon, API server, or database service.

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
is needed to validate the examples. Daemon, registry, comparison, and export commands still
exit 5 with `not_implemented`. Accepting a command name is not proof of evaluation execution.

To regenerate a lock in its matching platform environment:

```text
python -m piptools compile --extra dev --generate-hashes --allow-unsafe --strip-extras --no-emit-index-url --output-file requirements-cli-wsl.lock pyproject.toml
```

Change the output filename for Windows. A built wheel was also installed and exercised
outside the source directory on each platform. Recorded proof is in
[the Task 1 evidence](verification/evidence/cli-foundation.json).

## Manage local profiles and inspect history

From `backend/`, choose a separate local data directory for each operating system:

```text
asclepius --data-dir <local-directory> init
asclepius --data-dir <local-directory> targets add groq-target --config examples/groq-target.toml
asclepius --data-dir <local-directory> targets list --limit 50 --json
asclepius --data-dir <local-directory> targets show groq-target
asclepius --data-dir <local-directory> targets edit groq-target --config <updated-target.toml>
asclepius --data-dir <local-directory> runs list --json
asclepius --data-dir <local-directory> runs show <run-id> --json
asclepius --data-dir <local-directory> runs watch <run-id> --json
asclepius --data-dir <local-directory> findings list --run <run-id> --json
asclepius --data-dir <local-directory> findings show <finding-id> --json
```

`targets add` requires the argument to match `[target].name`. `edit` replaces configuration
and can rename the profile while retaining its ID. Duplicate and removed names stay reserved.
`targets remove <name-or-id>` tombstones a profile without deleting history. It prevents new
submissions and retries for that identity. Existing queued runs retain their accepted snapshots.
Ambiguous ID/name selectors fail instead of choosing another profile silently.

List commands return `items` and `next_cursor`. Pass a non-null cursor with `--cursor` to
continue. The default page size is 50 and the maximum is 500. Ordering is ascending UUID,
not newest first. `runs list --profile <profile-id>` also works for removed profiles.
Reads work while stopped. Watch prints persisted events and a terminal state, or exits 130
on keyboard interruption without cancelling the run. Active cancellation records a request;
the future coordinator must honor it before dispatching more work.

## Submit a complete plan

Submission requires a fresh ready daemon record. Task 4 has not implemented daemon startup,
so normal submission currently returns exit 4 without inserting a run. Do not modify the
database to manufacture readiness. Controlled readiness belongs only to isolated tests.

The submission interface accepts complete checks and four role prompts from a bounded,
versioned JSON file. The [custom example](../backend/examples/submission-plan.json) is synthetic
input for this interface, not a verified attack pack or proof of model evaluation.

```text
asclepius --data-dir <local-directory> run groq-target --plan examples/submission-plan.json --evaluator examples/groq-evaluator.toml --json
asclepius --data-dir <local-directory> runs cancel <run-id> --json
asclepius --data-dir <local-directory> runs retry <run-id> --json
```

Set the target and evaluator environment references before submitting. Their values never
enter snapshots. Submission checks this shell's environment, not the future daemon's
environment. Execution must resolve references again. Built-in `--pack broad-chat-v1`
returns `pack_unavailable` until Task 6 supplies the registry and prompts.
Successful submission means queued acceptance, not completed evaluation. Retry requires a
failed, cancelled, or interrupted source and an active original profile. It creates a new ID
linked to the source and preserves the saved configuration, checks, prompts, and limits.
It can incur new requests and is not exact replay.

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
