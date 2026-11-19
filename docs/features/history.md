# History and comparisons

Status: paginated history, saved-run inspection, manual restart recovery, and labeled
comparisons are implemented. Task 9 verifies
coherent comparison reads and derived counts without provider calls.

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
Lists use ascending UUID order, not execution time. Use `compare <run-a> <run-b> [<run-c> ...]`
for side-by-side outcome counts, denominators, and configuration differences. All selected
runs come from one SQLite snapshot; a missing ID fails the whole comparison.

## Driving it with the terminal

Evaluate two targets and repeat one with a known change. Restart the tool and check
identities, relationships, and results from a new process. Compare displayed differences
against per-check records. Include empty history and unknown run IDs.

## Gotchas

- Changing checks, check execution order, evaluator settings, or target configuration can
  make runs incompatible. A target-model-only change is labeled cross-model.
- Equal pinned settings do not establish immutable remote revisions or paired generated
  inputs. Comparisons show counts without numerical deltas, causal claims, or a score.
- Selected but unrun families show zero generated cases; a family absent from the snapshot
  is not selected. Missing judgments remain separate.
- Error counts and denominators affect apparent improvements.
- Proposed first milestone: no automatic history purge. Explicit deletion/import and
  backup/restore commands need separate designs; do not copy a live SQLite file casually.
- Corpus/query versions, retrieval depth, rubric/model versions, and unknown remote
  index revisions affect comparability; see [RAG testing](../specs/rag-testing.md).
- A profile snapshot cannot freeze the remote application. A same-name rerun is not
  proof that the model, corpus, access identity, or index was unchanged.
