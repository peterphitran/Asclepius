# Unresolved storage access failure during controlled workflow

Status: open investigation. The committed clock correction is a separate verified unit.

The combined source suite on WSL reported one failure among 539 selected tests. The positive
two-trial workflow completed its first run, then found the daemon stopped during its second
run. The daemon log contained `storage_busy`. Its last recorded work was a successful judge
observation; the corresponding stage did not finish. The second run remained running in
the store after process loss. The helper preserved partial evidence and confirmed that its recorded generation
was stopped. Native Windows passed 535 tests with four platform skips; one live test was deselected
on both platforms.

A separate first installed WSL attempt received exit 5 from `runs show` during its second
trial. That error payload was not retained, so it cannot be named as a storage contention
error. The daemon log later contained `storage_busy`; cleanup cancelled the run. Both failed
stores were retained outside pytest's working directories. Read-only checks found schema 4,
WAL mode and a successful SQLite `quick_check`. These checks do not establish a lock source
or prove every stored semantic relationship.

Later installed attempts passed two full trials on WSL and native Windows. Four instrumented
public workflow repeats also passed. A bounded 16,000-transaction concurrent Repository
experiment and 250 last-close/open cycles captured no native error. Those results do not
explain or fix the failures. Short-lived WAL connection cleanup and a writer exceeding the
busy timeout remain hypotheses. No busy timeout, retry policy, positive assertion or skip
was changed to make the result pass.

The daemon's final cleanup can supersede an earlier exception. Its one-line final error
therefore does not identify the first failed operation. A separately reviewed diagnostic
records allowlisted native error metadata and causal context on a future recurrence; it is
observability, not a storage fix. Capture the native SQLite code, trusted stack location,
read/write phase and preceding cleanup errors before choosing a runtime correction.

Keep the original WSL run recorded as failed. Record later checks separately and do not
close this issue from a clean rerun alone. Live Groq execution, semantic assessment, physical terminal
application closure and host-sleep acceptance remain unverified.
