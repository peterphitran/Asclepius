# History and Comparisons

Status: paginated run history and full saved-run inspection are implemented. Comparisons
and actual daemon restart verification remain planned.

## Sub-features

- `history-list`: browse runs and their target/status.
- `history-detail`: inspect configuration, timestamps, and results.
- `history-persist`: retain data across daemon restarts.
- `history-compare`: explain changes between selected runs.
- `history-snapshots`: preserve profile/check settings as used.

## How to get to it (user POV)

List prior runs, choose one for details, or select a pair for comparison.
The [backend design](../specs/backend-design.md) defines immutable run snapshots and
linked retries. Use `runs list --limit <1-500> --cursor <next-cursor>` and
`runs show <run-id>`. Filter by stable identity with `runs list --profile <profile-id>`.
Lists use ascending UUID order, not execution time. Comparisons remain unimplemented.

## Driving it with the terminal

Evaluate two targets and repeat one with a known change. Restart the tool and check
identities, relationships, and results from a new process. Compare displayed differences
against per-check records. Include empty history and unknown run IDs.

## Gotchas

- Changing checks or target configuration can make runs incomparable.
- Error counts and denominators affect apparent improvements.
- Proposed first milestone: no automatic history purge. Explicit deletion/import and
  backup/restore commands need separate designs; do not copy a live SQLite file casually.
- Corpus/query versions, retrieval depth, rubric/model versions, and unknown remote
  index revisions affect comparability; see [RAG testing](../specs/rag-testing.md).
- A profile snapshot cannot freeze the remote application. A same-name rerun is not
  proof that the model, corpus, access identity, or index was unchanged.
