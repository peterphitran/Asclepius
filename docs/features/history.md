# History and Comparisons

Status: planned. Inspect several applications and repeated runs across terminal sessions.

## Sub-features

- `history-list`: browse runs and their target/status.
- `history-detail`: inspect configuration, timestamps, and results.
- `history-persist`: retain data across daemon restarts.
- `history-compare`: explain changes between selected runs.
- `history-snapshots` (proposed): preserve profile/check settings as used.

## How to get to it (user POV)

List prior runs, choose one for details, or select a pair for comparison.
Filtering, comparison syntax, and snapshot storage need design.

## Driving it with the terminal

Evaluate two targets and repeat one with a known change. Restart the tool and check
identities, relationships, and results from a new process. Compare displayed differences
against per-check records. Include empty history and unknown run IDs.

## Gotchas

- Changing checks or target configuration can make runs incomparable.
- Error counts and denominators affect apparent improvements.
- Retention, imports, migrations, and backup behavior are undecided.
