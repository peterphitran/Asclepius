# Findings

Status: planned. Inspect the evidence and reproduction context behind a potential weakness.

## Sub-features

- `finding-list`: browse results for a run or application.
- `finding-detail`: inspect input, reply, judgment, severity, and reproduction context.
- `finding-linkage`: retain the originating run/check/target identity.
- Manual accept/reject review is a design candidate, not a required team workflow.

## How to get to it (user POV)

Choose a run, inspect its findings, and open the evidence for a selected result.
Exact navigation and inspection commands remain to be designed.

## Driving it with the terminal

Evaluate a known-response target and inspect its finding through the CLI. Match the
evidence to fixture requests and replies, then inspect it after restart. Include no
findings, missing IDs, partial failures, and multiple runs of the same target.

## Gotchas

- Execution errors must remain distinguishable from findings.
- Evidence can contain target content and credentials.
- Severity, confidence, and review semantics need a generic result schema.
