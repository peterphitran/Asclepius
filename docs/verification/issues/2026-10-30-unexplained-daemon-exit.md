# Clock reversal interrupts durable reply persistence

Status: confirmed clock fault corrected; broader live acceptance remains pending. Recorded on 2026-10-30 America/Chicago
during Task 10 preparation. Not every historical exit has an established cause.

A focused run on October 29 failed in both the new two-trial workflow and the existing
full-pack pipeline test. Their daemon logs reported `daemon_failed`. Public snapshots
remained `running` after the daemon stopped. The new workflow waited for its polling
deadline; the existing test waited for its fixture deadline.

A later read of the two stores observed these records:

| Scenario | Run ID | Operations | Observations | Judgments | Pending operations |
| --- | --- | --- | --- | --- | --- |
| Two-trial workflow, first trial | `fa34d529-a4fa-4a5c-890c-fc35a25bb046` | 172 | 171 | 75 | 1 |
| Existing pipeline test | `cc8e5c95-4ed0-4e50-b955-9068e78de1af` | 15 | 14 | 5 | 1 |

The stores were in pytest's temporary directory and were no longer present after later
pytest runs. They are not durable evidence. Failed test output and the diagnostic
SQL output in the agent transcript survive. The preparation evidence record retains those
observations and their provenance. It does not claim to retain either original database.

Individual and combined diagnostic reruns passed with temporary, fixture-only traceback
logging. No underlying exception was captured. That instrumentation was restored before
final checks. Passing reruns do not explain or fix the earlier exits.

A later traced controlled run, retained outside pytest's rotating directories, captured
`Observation` validation rejecting `finished_at < started_at`. Both values came from actual
UTC samples around a received provider reply. The uncaught validation error stopped the
daemon before the observation was saved. A parent-run verified HTTPS regression reproduces
the same failure with two reversed UTC samples. This establishes the received-reply loss
mechanism. It does not prove that every prior failure had that cause.

A separate archive recorded a backwards UTC event jump while the daemon still held the
same ready generation. The workflow helper had interpreted freshness-derived flags as
process death. Its active polling now checks ownership, generation, and ready state directly;
stale responsiveness alone does not claim the owner stopped.

The correction must retain the actual UTC instants, including a reversed pair. Readiness
freshness and run duration need an elapsed-time source with valid owner/epoch boundaries.
Clamping timestamps would fabricate evidence; raising timeouts would leave the cause intact.
The correction is committed as `3552f20`, following the failing regression commit
`6ccd911`. It retains actual UTC samples, uses private elapsed samples with current-generation
lock validity for freshness and run limits, and recovers only precisely classified expired
self-heartbeats during claim or startup admission. Explicit stopped migration to schema 4
preserves existing history. The [clock evidence record](../evidence/cli-clock-correction.json)
retains the original failure, a later review-discovered pause window, their regressions,
independent reviews, both platform suites and installed HTTPS/migration proof. This does not
assign that cause to every earlier exit.

The workflow helper now detects loss of its recorded daemon generation promptly, preserves
partial inspection, cancels owned work, and attempts bounded shutdown. This addresses the
helper's response to a stopped daemon. It does not itself fix the observation validation fault.

To investigate a recurrence, retain the failed store outside pytest's rotating temporary
directories and capture the actual exception in an isolated synthetic-provider run. Do not
log raw provider data or credentials in shared diagnostics. Identify the failing operation
and demonstrate a regression before changing runtime behavior. Do not raise deadlines or
claim reliability from a later pass.

Real Groq execution, semantic assessment, and terminal-close acceptance remain unverified.
