# Development

See [status](status.md) for current implementation boundaries. Profile management, manual
daemon control, and persisted run inspection work. Queued evaluations execute through the coordinator.
Configuration validation
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
is needed to validate the examples. Comparison and export commands still
exit 5 with `not_implemented`. Accepting a command name is not proof of evaluation execution.

To regenerate a lock in its matching platform environment:

```text
python -m piptools compile --extra dev --generate-hashes --allow-unsafe --strip-extras --no-emit-index-url --output-file requirements-cli-wsl.lock pyproject.toml
```

Change the output filename for Windows. A built wheel was also installed and exercised
outside the source directory on each platform. Recorded proof is in
[the Task 1 evidence](verification/evidence/cli-foundation.json).

## Installed provider-boundary proof

See the [Task 5 verification record](verification/evidence/cli-groq-components.json) for
platform results, source hashes, and installed-package observations.

After building and installing a wheel in the matching test environment, run from outside
the checkout with absolute paths:

```text
python <checkout>/backend/scripts/verify_groq.py <checkout>/backend/tests/cli/fixtures
```

The script asserts a `site-packages` import, runs two real loopback HTTPS requests using
synthetic credentials, validates an evaluator reply, and persists both observations with
real SQLite budgets. It checks provider-reported target and evaluator model names that
differ from requested names, then retains them through saved reads and all three report
formats. It removes its temporary store and closes its server. The checked-in
localhost key is public test material. No real API key, production trust change, live Groq
response, queued CLI execution, or four-agent pipeline is involved.

## Inspect the built-in pack

```text
asclepius checks list --pack broad-chat-v1 --json
```

Listing reads installed resources without credentials, a store, or a daemon. The pack
contains 20 checks across five families. Generation produces three attacks and one fixed
benign control per check, for 80 cases. This count describes the pinned coverage; it does
not establish model judgment accuracy.

## Installed execution proof

Build and install the final wheel into a separate environment, then run outside the
checkout using absolute paths:

```text
python <checkout>/backend/scripts/verify_pipeline.py --certificates <checkout>/backend/tests/cli/fixtures
```

The driver asserts a `site-packages` import. It starts real detached daemons and uses
verified loopback HTTPS, SQLite, and deterministic provider replies. Its sibling
`pipeline_fixture.py` must remain beside it. It checks two concurrent full-pack runs and
technical failure paths, stops its daemons, and removes its temporary stores. It does
not contact hosted models or establish semantic judgment accuracy.

## Installed cancellation and recovery proof

After installing the final wheel, run outside the checkout:

```text
python <checkout>/backend/scripts/verify_recovery.py --certificates <checkout>/backend/tests/cli/fixtures
```

Keep `recovery_fixture.py` and `pipeline_fixture.py` beside the driver. It requires the
package inside the executing environment's `site-packages`. It drives cancellation,
drain, OS watcher interruption, three owned-daemon crash points, manual restart, and
linked retry through real CLI/HTTPS/SQLite. It terminates only retained owned daemon
handles. On Windows it sends Ctrl+C only in a dedicated watcher console after checking
its exact process membership. These checks use synthetic credentials and deterministic
replies. The driver closes its servers, stops owned daemons, and removes temporary stores.
Physical keyboard and terminal-close acceptance remain Task 10.

## Compare and export saved evidence

Use the same explicit `--data-dir` as submission. These commands work with the daemon
stopped and do not require provider credentials:

```text
asclepius compare <run-a> <run-b> --json
asclepius findings list --run <run-id> --limit 50
asclepius findings show <finding-id> --json
asclepius report <run-id> --format html --output <existing-directory>/run.html
asclepius report <run-a> <run-b> --format markdown --output <existing-directory>/comparison.md
asclepius report <run-id> --format json --output <existing-directory>/run.json
```

Comparison returns derived counts directly, alongside source views and a settings
assessment. Same pinned settings, model-only changes, and incompatible settings have
separate labels. Check content compatibility and execution check order are distinct.
Remote revisions and generated input matching remain unestablished. Counts keep attacks,
controls, delivery errors, missing judgments, and unknown-kind legacy cases separate.
They do not become a combined score or numerical improvement claim.

Reports refuse an existing destination by default. Add `--overwrite` explicitly. The
writer requires an existing user-controlled local directory, serializes cooperating
writers with a persistent sibling lock, and publishes a complete file atomically. It
refuses unsafe existing destinations. Default publication also resists a creator that
ignores the lock. A precommit failure preserves the previous file; a postcommit durability
error states that the new file may already be present. Shared lock files remain in place.

Reports include potentially sensitive saved prompts and replies. HTML and Markdown keep
untrusted content inert; escaping does not make the evidence safe for public disclosure.
JSON preserves exact escaped text. A live/partial report is a labeled read snapshot.
Historical planned totals and absent usage counters remain unknown rather than zero.

## Installed results proof

After installing the final wheel, run outside the checkout with a new artifact directory:

```text
python <checkout>/backend/scripts/verify_results.py --certificates <checkout>/backend/tests/cli/fixtures --artifacts <owned-artifact-directory>
```

The driver asserts installed imports, creates isolated stores, and drives public CLI,
detached daemon, verified loopback HTTPS and SQLite. It checks exact fixture counts,
finding context, comparison labels, and repeated three-format exports with the daemon
stopped. It verifies no provider calls or logical database changes during those reads.
The driver stops owned daemons, closes servers, and removes temporary stores while
retaining reports for browser inspection. Fixture replies and credentials are synthetic.

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
the coordinator checks it before dispatching more work.

## Submit a complete plan

Submission requires a fresh persisted ready record from a manually started daemon. Stopped,
draining, or stale readiness returns exit 4 without inserting a run. A hard crash can leave
that record fresh for up to ten seconds, during which queued acceptance can still succeed.
That work waits for a manual restart; submission is not a synchronous OS-liveness guarantee.
Do not modify the database to manufacture readiness.
The daemon claims accepted work within runtime and pinned active-run bounds. Its status
reports execution capability for the actual owning generation. Starting the daemon remains
explicit; submission does not launch it.

The submission interface accepts complete checks and four role prompts from a bounded,
versioned JSON file. The [custom example](../backend/examples/submission-plan.json) is synthetic
input for this interface, not a verified attack pack or proof of model evaluation.

```text
asclepius --data-dir <local-directory> run groq-target --pack broad-chat-v1 --evaluator examples/groq-evaluator.toml --json
asclepius --data-dir <local-directory> run groq-target --plan examples/submission-plan.json --evaluator examples/groq-evaluator.toml --json
asclepius --data-dir <local-directory> runs cancel <run-id> --json
asclepius --data-dir <local-directory> runs retry <run-id> --json
```

Set the target and evaluator environment references before submitting. Their values never
enter snapshots. Submission checks this shell's environment, not the future daemon's
environment. Execution must resolve references again. Built-in `--pack broad-chat-v1`
pins the bundled checks and four role prompts through the same service as `--plan`.
Legacy custom plans still read and queue. The new role runner requires exactly three
strategies per check; the earlier one-strategy custom example demonstrates submission only.
Successful submission acknowledges background acceptance. Inspect `runs show` or `runs watch`
for the current state and persisted phases/counts. Retry requires a
failed, cancelled, or interrupted source and an active original profile. It creates a new ID
linked to the source and preserves the saved configuration, checks, prompts, and limits.
It can incur new requests and is not exact replay.

## Control the local daemon

```text
asclepius --data-dir <local-directory> daemon start --json
asclepius --data-dir <local-directory> daemon status --json
asclepius --data-dir <local-directory> daemon stop --timeout 15 --json
```

An optional strict policy file configures the daemon instance:

```text
asclepius --data-dir <local-directory> daemon start --config <daemon.toml> --json
```

```toml
ca_bundle = "/absolute/path/to/private-ca.pem"
[limits]
active_runs = 2
requests_per_minute = 60
```

The CA bundle is optional and adds trust while preserving certificate and hostname
verification. Relative CA paths resolve beside the policy file. Policy is frozen at startup;
changing it requires stopping and starting the daemon. Active-run admission honors both
runtime and pinned profile caps; set both to two when permitting two active runs.
Concurrency and rate state is shared across runs and
aliases. Runtime call, completion-token, and deadline limits are ceilings on each pinned
run, rather than a lifetime daemon spending quota. Submission-client credentials do not
supply keys to an already-running daemon; configure its environment before starting it.

Start is always explicit. The child detaches with redirected streams; duplicate starts
identify the existing owner. Status reports persisted identity/PID, OS ownership, heartbeat
responsiveness, and execution availability separately. PID alone is not ownership.
A generation-specific readiness lock prevents a restarted child from borrowing an old
instance's ready record while waiting on SQLite.

Stop records drain intent, rejects new submissions/claims, and waits for active work owned
by that instance. A timeout reports `daemon_draining` without killing it. Queued work remains
queued. Startup/stop wait options accept positive values up to 60 seconds. Startup timeout
does not kill a child that might still become ready; inspect status before trying again.
Logs live under `<local-directory>/logs/daemon-<instance-id>.log`. Lock files remain as
diagnostic artifacts; do not remove them to bypass an owner. OS locks release on process exit.
Automated creator-process-exit checks are not physical terminal-close or shutdown acceptance.

Native Windows defaults to `%LOCALAPPDATA%/Asclepius`. WSL/Linux uses
`$XDG_DATA_HOME/asclepius` or `~/.local/share/asclepius`. Use separate native stores.
UNC paths, mapped network drives, known remote filesystems, and Windows-mounted WSL
storage are rejected, including symlinks resolving to those locations. Test data on WSL
belongs under Linux storage such as `/tmp`, not the Windows checkout.

## Upgrade existing local storage

New stores use SQLite schema version 3. Existing version-1 and version-2 stores require an explicit,
stopped upgrade before reads or daemon start:

```text
asclepius --data-dir <local-directory> storage migrate --json
```

Migration acquires exclusive instance and maintenance locks. It adds PID diagnostics and
preserves saved profiles/runs. Unsupported versions fail without reset. `init` never upgrades
an existing store, and ordinary commands do not migrate implicitly. JSON output envelopes
still use schema version 1; that is separate from the SQLite schema version.

The shared `BudgetManager` has tested global, kind, destination, grouping, origin, and
credential-reference gates plus durable call/completion reservations. It is connected
to daemon execution through one shared manager across all runs. Cleanup operations remain unsupported until a separate budget contract
exists. Cancellation while waiting for a slot releases unused allowance. Dispatched calls
and uncertain authorization outcomes retain their reservations.

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
