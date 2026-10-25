from pathlib import Path

import pytest

from asclepius.config import load_evaluator, load_target
from asclepius.domain import AppError

TARGET = """schema_version = 1
[target]
name = "test-model"
adapter = "groq-chat"
model = "target-model"
base_url = "https://api.groq.com/openai/v1"
secret_ref = "env:GROQ_API_KEY"
system_prompt = "Follow the supplied test contract."
"""


def write_config(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(content, encoding="utf-8")
    return path


def test_target_and_evaluator_are_independent(tmp_path: Path) -> None:
    target = load_target(write_config(tmp_path, TARGET))
    evaluator_text = "schema_version = 1\n" + "\n".join(
        f"""[roles.{role}]
provider = "groq"
model = "evaluator-{role}"
secret_ref = "env:EVALUATOR_KEY"
"""
        for role in ("selector", "generator", "judge", "reporter")
    )
    evaluator = load_evaluator(write_config(tmp_path, evaluator_text))
    assert target.target.model == "target-model"
    assert target.target.max_completion_tokens == 512
    assert evaluator.roles.judge.model == "evaluator-judge"
    assert evaluator.roles.judge.secret_ref == "env:EVALUATOR_KEY"
    assert evaluator.roles.judge.max_completion_tokens == 2048
    assert target.target.secret_ref == "env:GROQ_API_KEY"


@pytest.mark.parametrize("extra", ['api_key = "do-not-echo-this-secret"', "unknown = 1"])
def test_reject_unknown_fields_without_echoing_values(tmp_path: Path, extra: str) -> None:
    with pytest.raises(AppError) as error:
        load_target(write_config(tmp_path, TARGET + extra))
    assert error.value.exit_code == 2
    assert "do-not-echo-this-secret" not in str(error.value)


def test_reject_secret_literal(tmp_path: Path) -> None:
    with pytest.raises(AppError) as error:
        load_target(write_config(tmp_path, TARGET.replace("env:GROQ_API_KEY", "actual-secret")))
    assert "actual-secret" not in str(error.value)


@pytest.mark.parametrize(
    "url",
    [
        "http://api.groq.com/v1",
        "https://user:secret@example.com/v1",
        "https://example.com/v1?token=secret",
        "file:///tmp/model",
        "https://example.com/#key",
    ],
)
def test_reject_unsafe_hosted_url(tmp_path: Path, url: str) -> None:
    with pytest.raises(AppError):
        load_target(write_config(tmp_path, TARGET.replace("https://api.groq.com/openai/v1", url)))


@pytest.mark.parametrize("value", ["0", "-1", "true", "1.5"])
def test_reject_invalid_numeric_limits(tmp_path: Path, value: str) -> None:
    with pytest.raises(AppError):
        load_target(write_config(tmp_path, TARGET + f"\n[limits]\nactive_runs = {value}\n"))


def test_config_parsing_does_not_resolve_or_serialize_credentials(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "configured-secret-value")
    config = load_target(write_config(tmp_path, TARGET))
    assert "configured-secret-value" not in config.model_dump_json()
    assert "env:GROQ_API_KEY" in config.model_dump_json()


def test_missing_and_malformed_config_are_actionable(tmp_path: Path) -> None:
    with pytest.raises(AppError, match="Cannot read configuration"):
        load_target(tmp_path / "missing.toml")
    with pytest.raises(AppError, match="Invalid TOML") as error:
        load_target(write_config(tmp_path, 'api_key = "never-display-me'))
    assert "never-display-me" not in str(error.value)


def test_missing_role_is_not_inherited_from_target(tmp_path: Path) -> None:
    with pytest.raises(AppError):
        load_evaluator(write_config(tmp_path, "schema_version = 1\n[roles]\n"))


def test_configuration_read_is_bounded() -> None:
    class Source:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, size: int):
            assert size == 1048577
            return b"x" * size

    class OversizedPath:
        def read_bytes(self):
            raise AssertionError("Configuration read must request a bounded byte count")

        def open(self, mode: str):
            assert mode == "rb"
            return Source()

    with pytest.raises(AppError) as error:
        load_target(OversizedPath())
    assert error.value.code == "config_size"


@pytest.mark.parametrize(
    "text",
    [
        "unexpected = true",
        "[limits]\nactive_runs = 0",
        'ca_bundle = "missing.pem"',
        '[limits]\ncompletion_tokens = "100"',
    ],
)
def test_daemon_policy_rejects_unknown_invalid_or_untrusted_configuration(tmp_path, text):
    from asclepius.config import load_daemon

    path = tmp_path / "daemon.toml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(AppError) as caught:
        load_daemon(path)
    assert caught.value.code == "daemon_config"


def test_daemon_policy_resolves_relative_ca_and_pins_limits(tmp_path):
    import shutil
    from pathlib import Path

    from asclepius.config import load_daemon

    shutil.copyfile(Path(__file__).parent / "fixtures" / "localhost-cert.pem", tmp_path / "ca.pem")
    path = tmp_path / "daemon.toml"
    path.write_text(
        'ca_bundle = "ca.pem"\n[limits]\nactive_runs = 2\ntotal_calls = 50', encoding="utf-8"
    )
    policy = load_daemon(path)
    assert policy.ca_bundle == str((tmp_path / "ca.pem").resolve())
    assert policy.limits.active_runs == 2 and policy.limits.total_calls == 50
