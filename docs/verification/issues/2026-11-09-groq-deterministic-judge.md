# Deterministic judge disagreement

Status: correction verified with controlled installed workflows. Hosted acceptance remains pending.

The hosted workflow `live-groq-tpm-flat-20261109T192208Z` stopped after 53 saved
judgments. The next target response was a complete refusal containing no protected
literal. Code computed a met deterministic assertion, but the judge proposed
`inconclusive`. The request schema accepted that proposal and the role guard rejected
its disagreement with the required `pass`. The run failed with `invalid_role_output`
and its daemon stopped cleanly. This was separate from the earlier connection failure.

For a complete, unredacted deterministic reply whose assertions are all met, code now
owns the passing verdict. A valid differing proposal receives an explicit product
rationale and no model confidence. Raw provider observations and validated quotes
remain unchanged. Invalid proposals, unsupported evidence, actual deterministic
failures, incomplete replies, semantic assessments, and reporter checks retain their
existing rules. The request schema and pinned prompts do not change.

The test-only regression commit precedes the correction. Both affected source suites
passed 226 tests. Fresh installed workflows on WSL and native Windows each completed
two full controlled trials, including the captured refusal and differing proposal,
then verified exports and stopped reads. These are fixture responses, not new hosted
acceptance or a semantic accuracy claim.

See [the correction evidence](../evidence/cli-groq-deterministic-judge.json).
Two complete hosted trials, semantic review, and physical lifecycle acceptance remain
separate Task 10 requirements.
