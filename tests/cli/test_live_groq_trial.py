import json

import pytest


def synthetic_trial_view():
    limits = {
        "target_calls": 100,
        "evaluator_calls": 220,
        "total_calls": 300,
        "completion_tokens": 500000,
    }
    actor_config = {"model": "requested", "max_completion_tokens": 2048}
    variants = [
        {"id": str(n), "check_id": str(n // 4), "kind": "control" if n % 4 == 0 else "attack"}
        for n in range(80)
    ]
    view = {
        "state": "completed",
        "snapshot": {
            "id": "trial",
            "profile": {
                "limits": limits,
                "target": {
                    "model": "requested",
                    "max_completion_tokens": 512,
                },
            },
            "checks": [{"id": str(n), "family": str(n // 4)} for n in range(20)],
            "evaluator": {
                "roles": {
                    role: actor_config for role in ("selector", "generator", "judge", "reporter")
                }
            },
        },
        "variants": variants,
        "judgments": [
            {
                "variant_id": v["id"],
                "security_verdict": "pass",
                "control_outcome": "answered" if v["kind"] == "control" else None,
            }
            for v in variants
        ],
        "observations": [],
    }
    actors = [(actor, str(n)) for n in range(80) for actor in ("target", "judge")]
    actors += [("selector", "selection")]
    actors += [("generator", "generation-" + str(n)) for n in range(20)]
    for index, (actor, work) in enumerate(actors):
        view["observations"].append(
            {
                "id": str(index),
                "work_item_id": work,
                "actor": actor,
                "status": "success",
                "payload": {
                    "response_id": "response-" + str(index),
                    "provider_model": "reported",
                    "usage": {"input_tokens": 100000, "output_tokens": 1},
                    **({"content": "reply"} if actor == "target" else {}),
                },
            }
        )
    return view, limits


def skip_empty_reply(view, index):
    from scripts.live_groq_fixture import EMPTY_REPLY_RATIONALE

    variant = view["variants"][index]
    for observation in view["observations"]:
        if observation["work_item_id"] == variant["id"] and observation["actor"] == "target":
            observation["payload"]["content"] = ""
    view["observations"] = [
        o
        for o in view["observations"]
        if not (o["work_item_id"] == variant["id"] and o["actor"] == "judge")
    ]
    judgment = view["judgments"][index]
    judgment.update(
        security_verdict="inconclusive",
        rationale=EMPTY_REPLY_RATIONALE,
        evidence=[],
        control_outcome="inconclusive" if variant["kind"] == "control" else None,
    )


def test_empty_reply_rationale_matches_product():
    from asclepius.agents import EMPTY_REPLY_RATIONALE as product
    from scripts.live_groq_fixture import EMPTY_REPLY_RATIONALE as fixture

    assert fixture == product


def test_trial_accepts_skipped_judge_for_empty_reply():
    from scripts.live_groq_fixture import verify_trial

    view, limits = synthetic_trial_view()
    skip_empty_reply(view, 0)
    skip_empty_reply(view, 1)
    result = verify_trial(view, limits)
    assert result["token_usage"]["output_tokens"] == 179


@pytest.mark.parametrize(
    "damage", ["judge_kept", "verdict", "rationale", "control_outcome", "evidence"]
)
def test_trial_rejects_invalid_empty_reply_skip(damage):
    from scripts.live_groq_fixture import WorkflowFailure, verify_trial

    view, limits = synthetic_trial_view()
    observations = list(view["observations"])
    skip_empty_reply(view, 0)
    judgment = view["judgments"][0]
    if damage == "judge_kept":
        view["observations"] = observations
    elif damage == "verdict":
        judgment["security_verdict"] = "pass"
    elif damage == "rationale":
        judgment["rationale"] = "Looks fine"
    elif damage == "control_outcome":
        judgment["control_outcome"] = "answered"
    else:
        judgment["evidence"] = [{"quote": "x"}]
    with pytest.raises(WorkflowFailure):
        verify_trial(view, limits)


def test_trial_rejects_missing_judge_for_nonempty_reply():
    from scripts.live_groq_fixture import WorkflowFailure, verify_trial

    view, limits = synthetic_trial_view()
    view["observations"] = [
        o for o in view["observations"] if not (o["work_item_id"] == "1" and o["actor"] == "judge")
    ]
    with pytest.raises(WorkflowFailure, match="case_observation_links_missing"):
        verify_trial(view, limits)


def test_input_usage_does_not_consume_completion_reservation_budget():
    from scripts.live_groq_fixture import verify_trial

    view, limits = synthetic_trial_view()
    result = verify_trial(view, limits)
    assert result["token_usage"] == {"input_tokens": 18100000, "output_tokens": 181}
    assert result["reserved_completion_tokens"] == 247808
    assert {(sample["family"], sample["kind"]) for sample in result["review_samples"]} == {
        (str(family), kind) for family in range(5) for kind in ("attack", "control")
    }


@pytest.mark.parametrize("excluded_checks", [[4], list(range(12, 20))])
def test_trial_rejects_uneven_check_kind_distribution(excluded_checks):
    from scripts.live_groq_fixture import WorkflowFailure, verify_trial

    view, limits = synthetic_trial_view()
    for check in excluded_checks:
        view["variants"][check * 4]["kind"] = "attack"
    for check in range(len(excluded_checks)):
        view["variants"][check * 4 + 1]["kind"] = "control"
    for variant, judgment in zip(view["variants"], view["judgments"], strict=True):
        judgment["control_outcome"] = "answered" if variant["kind"] == "control" else None
    assert len({v["id"] for v in view["variants"]}) == 80
    assert len({v["check_id"] for v in view["variants"]}) == 20
    assert sum(v["kind"] == "attack" for v in view["variants"]) == 60
    assert sum(v["kind"] == "control" for v in view["variants"]) == 20
    with pytest.raises(WorkflowFailure, match="case_partition_invalid"):
        verify_trial(view, limits)


def test_trial_rejects_duplicate_check_identity():
    from scripts.live_groq_fixture import WorkflowFailure, verify_trial

    view, limits = synthetic_trial_view()
    view["snapshot"]["checks"][-1]["id"] = "0"
    with pytest.raises(WorkflowFailure, match="pack_shape_invalid"):
        verify_trial(view, limits)


def test_redaction_preserves_case_distinct_text_and_removes_exact_escaped_key():
    from scripts.live_groq_fixture import redact

    secret = "AbCz123"
    content = {
        "direct": "abcz123 ABCZ123 AbCz123",
        "nested": json.dumps(
            {"plain": "abcz123", "escaped": r"\u0041\u0062\u0043\u007a\u0031\u0032\u0033"}
        ),
        "hex_upper": r"\u0041\u0062\u0043\u007A\u0031\u0032\u0033",
        "hex_lower": r"\u0041\u0062\u0043\u007a\u0031\u0032\u0033",
        "mixed": r"Ab\u0043z123 and abcz123",
    }
    cleaned = json.loads(redact(json.dumps(content), (secret,)))
    assert cleaned["direct"] == "abcz123 ABCZ123 [REDACTED]"
    assert json.loads(cleaned["nested"]) == {"plain": "abcz123", "escaped": "[REDACTED]"}
    assert cleaned["hex_upper"] == "[REDACTED]"
    assert cleaned["hex_lower"] == "[REDACTED]"
    assert cleaned["mixed"] == "[REDACTED] and abcz123"


@pytest.mark.parametrize(
    "content",
    [
        ' { "answer" : "Boundary maintained" }\n',
        ' \tplain\n"quoted" \\ café 雪 ',
        '{ "escaped" : "\\u96ea", "line" : "a\\nb" }\n',
        ' [  "nested", { "value": " { \\"answer\\" : \\"OK\\" } " } ] ',
    ],
)
def test_redaction_preserves_nonsecret_response_strings(content):
    import json

    from scripts.live_groq_fixture import redact

    retained = json.loads(redact(json.dumps({"content": content}), ("UNUSED_SYNTHETIC_KEY",)))
    assert retained["content"] == content


def test_redaction_excessive_nesting_fails_explicitly():
    import json

    from scripts.live_groq_fixture import WorkflowFailure, redact

    content = "safe text"
    for _ in range(9):
        content = json.dumps(content)
    with pytest.raises(WorkflowFailure, match="redaction_nesting_limit"):
        redact(json.dumps({"content": content}), ("UNUSED_SYNTHETIC_KEY",))
