# Live judge returns a control outcome for an attack

Status: open. The separate access-preflight correction passed both live model checks.

The first subsequent live trial failed with `invalid_role_output`. Selector, generator,
target and judge each returned a successful, stop-finished provider response. The judge
classified the first attack as `pass` but supplied `control_outcome: "answered"`.
The existing local role contract requires this field to be null for attacks and non-null
for controls, so it correctly rejected the proposal before saving a judgment. One trial
started; neither full trial completed. The driver preserved the failed run and stopped
its owned daemon. No request was retried and no second trial was submitted.

The pinned input identifies the case as an attack. The judge prompt explains allowed
control outcomes but does not explicitly state that attacks require null. The output
schema permits both null and control outcomes regardless of case kind. These are design
constraints for the correction; a successful HTTP response alone does not establish a
valid judgment. Preserve the validator and do not coerce the invalid value or replay the
paid request automatically.

The [preflight correction record](../evidence/cli-groq-preflight-correction.json) retains
the separate live access proof and subsequent failure summary. Full live-provider,
semantic, terminal-close and Task10 acceptance remain incomplete. The earlier storage
investigation is also still open.
