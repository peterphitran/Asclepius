# Findings

Status: paginated saved-finding reads and full finding inspection are implemented.
The persisted pipeline produces findings. [Task 9](../verification/evidence/cli-results.json)
verifies joined input/reply/judgment/check context and cursor reads on saved evidence.

## Sub-features

- `finding-list`: browse results for a run or application.
- `finding-detail`: inspect input, reply, judgment, severity, and reproduction context.
- `finding-linkage`: retain the originating run/check/target identity.
- Manual accept/reject review is a design candidate, not a required team workflow.

## How to get to it (user POV)

Choose a run, inspect its findings, and open the evidence for a selected result.
Use `findings list --run <run-id>` and `findings show <finding-id>`. These reads work
while the daemon is stopped. Lists have the shared `--limit` and `--cursor` options.
Detail retains the original Finding fields and adds saved context. Legacy cases with no
variant payload remain visible with explicit unknown-kind context and saved request data.

## Driving it with the terminal

Evaluate a known-response target and inspect its finding through the CLI. Match the
evidence to fixture requests and replies, then inspect it after restart. Include no
findings, missing IDs, partial failures, and multiple runs of the same target.

## Gotchas

- Execution errors must remain distinguishable from findings.
- Evidence can contain target content and credentials.
- Generic finding contracts retain severity, judgment identity, and evidence. Independent
  manual review semantics remain undecided.
- Cite document/chunk identities, corpus version, query, retrieved ranks, and answer
  evidence when applicable. A citation label alone does not establish grounding.
- Redact configured secrets before persistence and display evidence as untrusted text.
  Redaction cannot guarantee arbitrary target content is safe to share.
- Preserve evidence limits/truncation metadata. Missing necessary evidence means
  inconclusive, not an invented reproduction or confident finding.
