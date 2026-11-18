import hashlib
import html
import ipaddress
import json
import os
import platform
import re
import ssl
import sys
import tempfile
import time
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx

try:
    from .pipeline_fixture import isolated_python
except ImportError:
    from pipeline_fixture import isolated_python

# Must equal asclepius.agents.EMPTY_REPLY_RATIONALE; the fixture does not import the product.
EMPTY_REPLY_RATIONALE = (
    "Target reply was empty; no evidence to assess, so the judge was not called."
)


class WorkflowFailure(Exception):
    pass


@dataclass(frozen=True)
class Probe:
    endpoint: str
    secret_ref: str
    model: str
    strict: bool
    max_tokens: int
    reasoning_effort: str | None = None

    @property
    def identity(self):
        url = urlsplit(self.endpoint)
        return (
            url.scheme,
            url.hostname,
            url.port or 443,
            url.path.rstrip("/"),
            self.secret_ref,
            self.model,
            self.strict,
            self.max_tokens,
            self.reasoning_effort,
        )


def require(condition, code):
    if not condition:
        raise WorkflowFailure(code)


def read_config(path):
    return capture_config(path)[0]


def capture_config(path):
    try:
        raw = Path(path).read_bytes()
        return tomllib.loads(raw.decode("utf-8")), raw
    except (OSError, ValueError):
        raise WorkflowFailure("configuration_unreadable") from None


def prerequisites(target, evaluator, environment):
    if environment.get("ASCLEPIUS_LIVE_TESTS") != "1":
        return "explicit_opt_in_missing"
    refs = [target.get("target", {}).get("secret_ref")]
    refs += [role.get("secret_ref") for role in evaluator.get("roles", {}).values()]
    if not refs or any(not isinstance(ref, str) or not ref.startswith("env:") for ref in refs):
        return "environment_credential_reference_missing"
    if any(not environment.get(ref[4:], "").strip() for ref in refs):
        return "environment_credential_missing"
    return None


def redact(text, secrets):
    replacements = []
    for secret in secrets:
        encoded_pattern = "".join(
            "(?:" + r"\\+u" + f"(?i:{ord(character):04x})" + "|" + re.escape(character) + ")"
            for character in secret
        )
        forms = {secret, html.escape(secret), html.escape(secret, quote=False)}
        escaped = secret
        for _ in range(8):
            escaped = json.dumps(escaped, ensure_ascii=True)[1:-1]
            forms.update((escaped, html.escape(escaped)))
        forms.update(html.escape(form) for form in tuple(forms))
        replacements.append((re.compile(encoded_pattern), sorted(forms, key=len, reverse=True)))
    memo = {}

    def clean(value, encoded_depth=0):
        if isinstance(value, dict):
            return {
                clean(key, encoded_depth): clean(item, encoded_depth) for key, item in value.items()
            }
        if isinstance(value, list):
            return [clean(item, encoded_depth) for item in value]
        if not isinstance(value, str):
            return value
        key = (value, encoded_depth)
        if key in memo:
            return memo[key]
        if encoded_depth >= 8:
            raise WorkflowFailure("redaction_nesting_limit")
        for pattern, forms in replacements:
            value = pattern.sub("[REDACTED]", value)
            for form in forms:
                if form:
                    value = value.replace(form, "[REDACTED]")
        try:
            parsed = json.loads(value)
        except RecursionError:
            raise WorkflowFailure("redaction_nesting_limit") from None
        except ValueError:
            memo[key] = value
            return value
        if isinstance(parsed, (dict, list, str)):
            cleaned = clean(parsed, encoded_depth + 1)
            if cleaned != parsed:
                value = json.dumps(cleaned, ensure_ascii=True)
        memo[key] = value
        return value

    try:
        parsed = json.loads(text)
    except RecursionError:
        raise WorkflowFailure("redaction_nesting_limit") from None
    except ValueError:
        return clean(text)
    return json.dumps(clean(parsed), ensure_ascii=True, indent=2)


def save(path, value, secrets):
    content = value if isinstance(value, str) else json.dumps(value, indent=2, ensure_ascii=True)
    content = redact(content, secrets)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content + "\n", encoding="utf-8")
    temporary.replace(path)


def probes(profile, evaluator):
    specs = [(profile["target"], False)] + [(role, True) for role in evaluator["roles"].values()]
    unique = {}
    for spec, strict in specs:
        endpoint = spec.get("base_url", "https://api.groq.com/openai/v1").rstrip("/")
        gpt_oss = spec["model"] in {"openai/gpt-oss-20b", "openai/gpt-oss-120b"}
        ceiling = 512 if gpt_oss else 64
        probe = Probe(
            endpoint,
            spec["secret_ref"],
            spec["model"],
            strict,
            min(ceiling, spec.get("max_completion_tokens", ceiling)),
            "low" if gpt_oss else None,
        )
        unique.setdefault(probe.identity, probe)
    return list(unique.values())


def controlled_endpoints(items, ca_bundle):
    require(ca_bundle is not None and Path(ca_bundle).is_file(), "controlled_ca_required")
    for item in items:
        url = urlsplit(item.endpoint)
        try:
            loopback = ipaddress.ip_address(url.hostname).is_loopback
        except ValueError:
            loopback = False
        require(
            url.scheme == "https" and loopback and not url.username and not url.password,
            "controlled_loopback_required",
        )


def _response_metadata(reply):
    metadata = {}
    if not isinstance(reply, dict):
        return metadata
    for source, destination in (("id", "response_id"), ("model", "reported_model")):
        value = reply.get(source)
        if isinstance(value, str) and value.strip() and len(value) <= 1024:
            metadata[destination] = value
    choices = reply.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        finish = choices[0].get("finish_reason")
        known = ("stop", "length", "content_filter", "tool_calls", "function_call")
        metadata["finish_reason"] = (
            finish if isinstance(finish, str) and finish in known else "other"
        )
    usage = reply.get("usage")
    if isinstance(usage, dict):
        counts = {
            key: usage[key]
            for key in ("prompt_tokens", "completion_tokens", "total_tokens")
            if type(usage.get(key)) is int and usage[key] >= 0
        }
        details = usage.get("completion_tokens_details")
        if isinstance(details, dict):
            reasoning = details.get("reasoning_tokens")
            if type(reasoning) is int and reasoning >= 0:
                counts["completion_tokens_details"] = {"reasoning_tokens": reasoning}
        if counts:
            metadata["usage"] = counts
    return metadata


def preflight(items, environment, report, persist, *, ca_bundle=None):
    context = ssl.create_default_context(cafile=str(ca_bundle) if ca_bundle else None)
    with httpx.Client(
        verify=context, follow_redirects=False, trust_env=False, timeout=30
    ) as client:
        for item in items:
            entry = {
                "endpoint": item.endpoint,
                "credential_reference": item.secret_ref,
                "requested_model": item.model,
                "strict": item.strict,
                "max_completion_tokens": item.max_tokens,
                "status": "attempted_unknown",
                "attempted_at": datetime.now(UTC).isoformat(),
            }
            if item.reasoning_effort is not None:
                entry["reasoning_effort"] = item.reasoning_effort
            report["preflights"].append(entry)
            persist()
            body = {
                "model": item.model,
                "max_completion_tokens": item.max_tokens,
                "temperature": 0,
                "messages": [{"role": "user", "content": "Asclepius access preflight. Reply OK."}],
            }
            if item.reasoning_effort is not None:
                body["reasoning_effort"] = item.reasoning_effort
            if item.strict:
                body["messages"][0]["content"] = (
                    'Asclepius access preflight. Reply with only {"ok":true}.'
                )
                body["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "access_check",
                        "strict": True,
                        "schema": {
                            "type": "object",
                            "properties": {"ok": {"type": "boolean"}},
                            "required": ["ok"],
                            "additionalProperties": False,
                        },
                    },
                }
            try:
                with client.stream(
                    "POST",
                    item.endpoint + "/chat/completions",
                    json=body,
                    headers={"Authorization": "Bearer " + environment[item.secret_ref[4:]]},
                ) as response:
                    entry["http_status"] = response.status_code
                    require(response.status_code == 200, "preflight_http_failure")
                    raw = bytearray()
                    for chunk in response.iter_bytes():
                        raw.extend(chunk)
                        require(len(raw) <= 65536, "preflight_response_too_large")
                reply = json.loads(raw)
                entry.update(_response_metadata(reply))
                require(isinstance(reply, dict), "preflight_response_or_transport_failure")
                require(
                    "response_id" in entry and "reported_model" in entry,
                    "preflight_identity_missing",
                )
                entry["model_mismatch"] = reply["model"] != item.model
                choices = reply.get("choices")
                require(
                    isinstance(choices, list) and choices and isinstance(choices[0], dict),
                    "preflight_response_or_transport_failure",
                )
                choice = choices[0]
                require(choice.get("finish_reason") == "stop", "preflight_incomplete")
                message = choice.get("message")
                require(isinstance(message, dict), "preflight_response_or_transport_failure")
                content = message.get("content")
                require(isinstance(content, str) and content.strip(), "preflight_content_missing")
                if item.strict:
                    output = json.loads(content)
                    require(
                        isinstance(output, dict)
                        and set(output) == {"ok"}
                        and type(output["ok"]) is bool,
                        "preflight_schema_invalid",
                    )
                usage = entry.get("usage", {})
                require(
                    all(key in usage for key in ("prompt_tokens", "completion_tokens")),
                    "preflight_usage_missing",
                )
                entry["status"] = "succeeded"
            except WorkflowFailure:
                entry["status"] = "failed"
                raise
            except Exception:
                raise WorkflowFailure("preflight_response_or_transport_failure") from None
            finally:
                entry["finished_at"] = datetime.now(UTC).isoformat()
                persist()


def verify_trial(view, limits):
    require(view["state"] == "completed", "trial_not_completed")
    require(view["snapshot"]["profile"]["limits"] == limits, "snapshot_limits_changed")
    checks = view["snapshot"]["checks"]
    variants = view["variants"]
    judgments = view["judgments"]
    require(
        len(checks) == len({c["id"] for c in checks}) == 20
        and len({c["family"] for c in checks}) == 5,
        "pack_shape_invalid",
    )
    require(len(variants) == 80 and len({v["id"] for v in variants}) == 80, "case_count_invalid")
    require(
        sum(v["kind"] == "attack" for v in variants) == 60
        and sum(v["kind"] == "control" for v in variants) == 20,
        "case_partition_invalid",
    )
    require({v["check_id"] for v in variants} == {c["id"] for c in checks}, "checks_missing")
    check_counts = {check["id"]: {"attack": 0, "control": 0} for check in checks}
    for variant in variants:
        check_counts[variant["check_id"]][variant["kind"]] += 1
    require(
        all(counts == {"attack": 3, "control": 1} for counts in check_counts.values()),
        "case_partition_invalid",
    )
    require(
        len(judgments) == 80
        and {j["variant_id"] for j in judgments} == {v["id"] for v in variants},
        "judgments_missing",
    )
    skipped = 0
    for variant in variants:
        judgment = next(j for j in judgments if j["variant_id"] == variant["id"])
        require(
            judgment["security_verdict"] in {"pass", "weakness", "inconclusive"},
            "final_verdict_missing",
        )
        if variant["kind"] == "control":
            require(
                judgment["control_outcome"] in {"answered", "over_refusal", "inconclusive"},
                "control_outcome_missing",
            )
        linked = [o for o in view["observations"] if o["work_item_id"] == variant["id"]]
        actors = [o["actor"] for o in linked]
        require(actors.count("target") == 1, "case_observation_links_missing")
        reply = next(o for o in linked if o["actor"] == "target")["payload"].get("content")
        require(isinstance(reply, str), "target_reply_missing")
        if reply.strip():
            require(actors.count("judge") == 1, "case_observation_links_missing")
        else:
            skipped += 1
            require(
                actors.count("judge") == 0
                and judgment["security_verdict"] == "inconclusive"
                and judgment.get("rationale") == EMPTY_REPLY_RATIONALE
                and not judgment.get("evidence")
                and judgment["control_outcome"]
                == ("inconclusive" if variant["kind"] == "control" else None),
                "empty_reply_judgment_invalid",
            )
    counts = {}
    identities = []
    token_usage = {"input_tokens": 0, "output_tokens": 0}
    reserved_completion_tokens = 0
    for observation in view["observations"]:
        actor = observation["actor"]
        counts[actor] = counts.get(actor, 0) + 1
        require(observation["status"] == "success", "observation_failed")
        payload = observation["payload"]
        require(
            all(
                isinstance(payload.get(key), str) and payload[key].strip()
                for key in ("response_id", "provider_model")
            ),
            "observation_identity_missing",
        )
        usage = payload["usage"]
        require(
            all(type(usage[key]) is int for key in ("input_tokens", "output_tokens")),
            "observation_usage_unknown",
        )
        for key in token_usage:
            token_usage[key] += usage[key]
        actor_config = (
            view["snapshot"]["profile"]["target"]
            if actor == "target"
            else view["snapshot"]["evaluator"]["roles"][actor]
        )
        reserved_completion_tokens += actor_config["max_completion_tokens"]
        requested = (
            view["snapshot"]["profile"]["target"]["model"]
            if actor == "target"
            else view["snapshot"]["evaluator"]["roles"][actor]["model"]
        )
        identities.append(
            {
                "observation_id": observation["id"],
                "actor": actor,
                "requested_model": requested,
                "reported_model": payload["provider_model"],
                "response_id": payload["response_id"],
                "model_mismatch": requested != payload["provider_model"],
            }
        )
    evaluator_count = sum(n for actor, n in counts.items() if actor != "target")
    require(
        counts.get("target") == 80
        and counts.get("selector") == 1
        and counts.get("generator") == 20
        and counts.get("judge", 0) == 80 - skipped
        and 101 - skipped <= evaluator_count <= 181 - skipped,
        "call_partition_invalid",
    )
    require(
        counts["target"] <= limits["target_calls"]
        and evaluator_count <= limits["evaluator_calls"]
        and sum(counts.values()) <= limits["total_calls"]
        and reserved_completion_tokens <= limits["completion_tokens"],
        "trial_budget_exceeded",
    )
    samples = []
    families = {c["id"]: c["family"] for c in checks}
    selected = set()
    for variant in variants:
        pair = (families[variant["check_id"]], variant["kind"])
        if pair in selected:
            continue
        selected.add(pair)
        judgment = next(j for j in judgments if j["variant_id"] == variant["id"])
        observations = [o for o in view["observations"] if o["work_item_id"] == variant["id"]]
        samples.append(
            {
                "family": pair[0],
                "kind": pair[1],
                "variant": variant,
                "judgment": judgment,
                "observations": observations,
            }
        )
    return {
        "run_id": view["snapshot"]["id"],
        "call_counts": counts,
        "token_usage": token_usage,
        "reserved_completion_tokens": reserved_completion_tokens,
        "identities": identities,
        "review_samples": samples,
        "limits": limits,
        "outcomes": {
            value: sum(j["security_verdict"] == value for j in judgments)
            for value in ("weakness", "pass", "inconclusive")
        },
    }


def run_workflow(
    target_path,
    evaluator_path,
    artifacts,
    *,
    interpreter=None,
    environment=None,
    controlled_ca=None,
    source_identity=None,
):
    environment = dict(os.environ if environment is None else environment)
    interpreter = str(interpreter or sys.executable)
    target_path, evaluator_path = Path(target_path).resolve(), Path(evaluator_path).resolve()
    artifacts = Path(artifacts).resolve()
    secrets = ()
    report = {
        "status": "not_run",
        "scope": "controlled_protocol" if controlled_ca else "live_groq",
        "live_groq": False,
        "manual_semantic_review": "pending",
        "preflights": [],
        "commands": [],
        "trials": [],
        "run_ids": [],
        "cleanup": [],
        "missing_proofs": ["manual_semantic_review", "physical_terminal_closure"],
        "source_identity": (
            {"verification": "unverified_caller_metadata", "claim": source_identity}
            if source_identity is not None
            else None
        ),
        "os": platform.platform(),
        "started_at": datetime.now(UTC).isoformat(),
        "interpreter": interpreter,
    }
    report["helper_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    report["missing_proofs"].append("source_checkpoint_and_diff_identity")
    artifacts.mkdir(parents=True, exist_ok=False, mode=0o700)

    def persist():
        save(artifacts / "evidence.json", report, secrets)

    def command(*arguments, timeout=30):
        argv = [
            "-m",
            "asclepius",
            "--data-dir",
            str(artifacts / "store"),
            "--json",
            *map(str, arguments),
        ]
        receipt = {"argv": [interpreter, "-I", *argv], "status": "attempted_unknown"}
        report["commands"].append(receipt)
        persist()
        try:
            result = isolated_python(
                *argv, environment=environment, interpreter=interpreter, timeout=timeout
            )
            receipt.update(status="returned", exit_code=result.returncode)
            payload = json.loads(redact(result.stdout, secrets))
            require(result.returncode == 0 and payload.get("ok"), "cli_failed")
            return payload.get("data", payload)
        except WorkflowFailure:
            raise
        except Exception:
            raise WorkflowFailure("cli_response_or_process_failure") from None
        finally:
            persist()

    started = False
    try:
        if not controlled_ca and environment.get("ASCLEPIUS_LIVE_TESTS") != "1":
            report["reason"] = "explicit_opt_in_missing"
            return report
        target_capture, evaluator_capture = (
            capture_config(target_path),
            capture_config(evaluator_path),
        )
        target, evaluator = target_capture[0], evaluator_capture[0]
        if controlled_ca:
            controlled_endpoints(probes(target, evaluator), controlled_ca)
        guard_environment = dict(environment)
        if controlled_ca:
            guard_environment["ASCLEPIUS_LIVE_TESTS"] = "1"
        reason = prerequisites(target, evaluator, guard_environment)
        if reason:
            report["reason"] = reason
            report["missing_proofs"].append("live_provider_workflow")
            return report
        refs = {
            target["target"]["secret_ref"],
            *(role["secret_ref"] for role in evaluator["roles"].values()),
        }
        secrets = tuple(environment[ref[4:]] for ref in refs)
        for config, raw in (target_capture, evaluator_capture):
            source = raw.decode("utf-8")
            if (
                redact(source, secrets) != source
                or json.loads(redact(json.dumps(config, ensure_ascii=True), secrets)) != config
            ):
                raise WorkflowFailure("configuration_contains_credential")
        target_path = artifacts / "captured-target.toml"
        evaluator_path = artifacts / "captured-evaluator.toml"
        target_path.write_bytes(target_capture[1])
        evaluator_path.write_bytes(evaluator_capture[1])
        report["status"] = "running"
        command("config", "validate", target_path)
        command("config", "validate", evaluator_path, "--kind", "evaluator")
        provenance = isolated_python(
            "-c",
            "import asclepius,json,sys; print(json.dumps({'import':asclepius.__file__,"
            "'executable':sys.executable,'version':sys.version,'prefix':sys.prefix}))",
            interpreter=interpreter,
            environment=environment,
        )
        require(provenance.returncode == 0, "interpreter_provenance_failed")
        report["python"] = json.loads(redact(provenance.stdout, secrets))
        command("init")
        alias = target["target"]["name"]
        command("targets", "add", alias, "--config", target_path)
        profile = command("targets", "show", alias)["config"]
        limits = profile["limits"]
        report["effective_limits"] = limits
        if not controlled_ca:
            require(
                all(
                    limits[key] == value
                    for key, value in {
                        "requests_per_minute": 10,
                        "run_timeout_seconds": 2700,
                        "total_calls": 300,
                        "target_calls": 100,
                        "evaluator_calls": 220,
                        "completion_tokens": 500000,
                    }.items()
                ),
                "live_limits_not_approved",
            )
        items = probes(profile, evaluator)
        if not controlled_ca:
            require(
                all(
                    urlsplit(p.endpoint).scheme == "https"
                    and urlsplit(p.endpoint).hostname == "api.groq.com"
                    and urlsplit(p.endpoint).port in (None, 443)
                    for p in items
                ),
                "live_groq_origin_required",
            )
        preflight(items, environment, report, persist, ca_bundle=controlled_ca)
        wait_seconds = 0 if controlled_ca else 61
        report["account_window"] = {
            "preflight_calls_outside_trial_budgets": len(report["preflights"]),
            "wait_seconds": wait_seconds,
            "status": "waiting",
            "reason": "Clear preflight requests from the shared 60 second account window",
        }
        persist()
        wait_started = time.monotonic()
        if wait_seconds:
            time.sleep(wait_seconds)
        report["account_window"]["elapsed_seconds"] = time.monotonic() - wait_started
        report["account_window"]["status"] = "cleared"
        daemon_arguments = []
        if controlled_ca:
            daemon_config = artifacts / "daemon.toml"
            daemon_config.write_text(
                "ca_bundle = "
                + json.dumps(str(Path(controlled_ca).resolve()))
                + "\n[limits]\n"
                + "\n".join(
                    f"{key} = {value}" for key, value in limits.items() if value is not None
                ),
                encoding="utf-8",
            )
            daemon_arguments = ["--config", daemon_config]
        started = True
        daemon = command("daemon", "start", *daemon_arguments)
        report["daemon"] = daemon
        require(daemon["owned"] and daemon["execution_available"], "daemon_not_ready")
        completed = []
        for _ in range(2):
            submitted = command(
                "run", alias, "--pack", "broad-chat-v1", "--evaluator", evaluator_path
            )
            identity = submitted["id"]
            require(identity not in report["run_ids"], "run_id_reused")
            report["run_ids"].append(identity)
            persist()
            deadline = time.monotonic() + limits["run_timeout_seconds"] + 60
            while True:
                view = command("runs", "show", identity)
                save(artifacts / f"{identity}.json", view, secrets)
                report["progress"] = {
                    "run_id": identity,
                    "state": view["state"],
                    "progress": view["progress"],
                }
                persist()
                if view["state"] not in {"queued", "running"}:
                    break
                report["last_daemon_status"] = command("daemon", "status")
                status = report["last_daemon_status"]
                require(
                    status["owned"]
                    and status["instance_id"] == daemon["instance_id"]
                    and status["state"] == "ready",
                    "daemon_stopped_during_trial",
                )
                require(time.monotonic() < deadline, "trial_poll_deadline")
                time.sleep(0.2 if controlled_ca else 5)
            trial = verify_trial(view, limits)
            resolved = probes(view["snapshot"]["profile"], view["snapshot"]["evaluator"])
            require(
                {p.identity for p in resolved} == {p.identity for p in items},
                "snapshot_provider_settings_changed",
            )
            report["trials"].append(trial)
            completed.append(view)
            persist()
        stopped = command("daemon", "stop")
        require(not stopped["owned"], "daemon_stop_failed")
        report["cleanup"].append({"daemon_stopped": True})
        restarted = command("daemon", "start", *daemon_arguments)
        report["restart"] = restarted
        for identity in report["run_ids"]:
            require(
                command("runs", "show", identity)["state"] == "completed",
                "restart_inspection_failed",
            )
        require(not command("daemon", "stop")["owned"], "daemon_stop_failed")
        started = False
        report["cleanup"].append({"daemon_stopped": True})
        reread = [command("runs", "show", identity) for identity in report["run_ids"]]
        for before, after in zip(completed, reread, strict=True):
            require(
                {k: v for k, v in before.items() if k != "captured_at"}
                == {k: v for k, v in after.items() if k != "captured_at"},
                "durable_inspection_changed",
            )
        report["durable_inspection"] = {"unchanged": True, "daemon_stopped": True}
        comparison = command("compare", *report["run_ids"])
        require(
            [s["run_id"] for s in comparison["summaries"]] == report["run_ids"],
            "comparison_ids_changed",
        )
        save(artifacts / "comparison.json", comparison, secrets)
        report["summaries"] = comparison["summaries"]
        report["exports"] = []
        for format in ("json", "markdown", "html"):
            path = artifacts / f"comparison.{format}"
            if format == "json":
                path = artifacts / "report.json"
            with tempfile.TemporaryDirectory(
                prefix="asclepius-report-", dir=artifacts.parent
            ) as stage:
                raw_path = Path(stage) / path.name
                command("report", *report["run_ids"], "--format", format, "--output", raw_path)
                save(path, raw_path.read_text(encoding="utf-8"), secrets)
            report["exports"].append(
                {
                    "format": format,
                    "path": str(path),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
        report["status"] = "succeeded"
        report["live_groq"] = controlled_ca is None
    except WorkflowFailure as error:
        report.update(status="failed", reason=str(error))
    except BaseException:
        report.update(status="failed", reason="workflow_interrupted_or_failed")
    finally:
        if started:
            report["cancelled_run_ids"] = []
            report["cancellation_failures"] = []
            try:
                owned_runs = command("runs", "list")["items"]
                for run in owned_runs:
                    if run["id"] not in report["run_ids"]:
                        report["run_ids"].append(run["id"])
                        report.setdefault("recovered_submission_ids", []).append(run["id"])
            except BaseException:
                report["missing_proofs"].append("uncertain_submission_inspection")
            for identity in report["run_ids"]:
                try:
                    view = command("runs", "show", identity)
                    if view["state"] in {"queued", "running"}:
                        command("runs", "cancel", identity)
                        report["cancelled_run_ids"].append(identity)
                except BaseException:
                    report["cancellation_failures"].append(identity)
            stopped = False
            deadline = time.monotonic() + report["effective_limits"]["request_timeout_seconds"] + 30
            while time.monotonic() < deadline:
                wait = min(60, max(1, deadline - time.monotonic()))
                try:
                    status = command("daemon", "stop", "--timeout", wait, timeout=wait + 5)
                    stopped = not status["owned"]
                    break
                except BaseException:
                    try:
                        status = command("daemon", "status")
                        if not status["owned"]:
                            stopped = True
                            break
                        if status.get("state") != "draining":
                            break
                    except BaseException:
                        break
            report["cleanup"].append({"daemon_stopped": stopped})
            if not stopped or report["cancellation_failures"]:
                report.update(status="failed", reason="daemon_cleanup_failed")
            if stopped:
                for identity in report["run_ids"]:
                    try:
                        save(
                            artifacts / f"{identity}.json",
                            command("runs", "show", identity),
                            secrets,
                        )
                    except BaseException:
                        report["missing_proofs"].append("final_partial_run_inspection")
        if controlled_ca or report["status"] != "succeeded":
            if "live_provider_workflow" not in report["missing_proofs"]:
                report["missing_proofs"].append("live_provider_workflow")
        report["artifact_hashes"] = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in artifacts.iterdir()
            if path.is_file() and path.name != "evidence.json"
        }
        report["finished_at"] = datetime.now(UTC).isoformat()
        persist()
    return json.loads(redact(json.dumps(report), secrets))
