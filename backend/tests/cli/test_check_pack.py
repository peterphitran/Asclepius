import pytest

from asclepius.checks import load_pack, load_pack_plan
from asclepius.cli import main
from asclepius.domain import AppError


def test_pack_complete():
    checks = load_pack("broad-chat-v1")
    assert len(checks) == len({c.id for c in checks}) == 20
    assert len({c.family for c in checks}) == 5
    for c in checks:
        assert len(set(c.strategies)) == 3
        assert c.system_prompt and c.benign_control and c.rubric and c.evidence_criteria
        assert c.severity_rule and c.capabilities == ("chat.v1",)
    assert len(load_pack_plan("broad-chat-v1").prompts) == 4


def test_unknown_pack():
    with pytest.raises(AppError) as error:
        load_pack("../../secrets")
    assert error.value.code == "pack_unavailable"


def test_list_without_store(tmp_path, capsys):
    assert (
        main(
            [
                "--data-dir",
                str(tmp_path / "absent"),
                "--json",
                "checks",
                "list",
                "--pack",
                "broad-chat-v1",
            ]
        )
        == 0
    )
    assert "priority.override" in capsys.readouterr().out
    assert not (tmp_path / "absent").exists()


@pytest.mark.parametrize(
    "schema",
    [
        "{",
        "null",
        '{"type":"invalid"}',
        '{"type":"object"}',
        '{"$ref":"https://example.invalid/schema"}',
    ],
)
def test_invalid_local_schema_is_typed(schema):
    from asclepius.checks import local_schema

    with pytest.raises(AppError) as error:
        local_schema(schema)
    assert error.value.code == "invalid_check"


def test_missing_resource_is_typed(monkeypatch):
    from asclepius import checks

    class Missing:
        def joinpath(self, path):
            return self

        def read_text(self, **kwargs):
            raise FileNotFoundError("hidden-path")

    monkeypatch.setattr(checks, "files", lambda package: Missing())
    with pytest.raises(AppError) as error:
        load_pack("broad-chat-v1")
    assert error.value.code == "invalid_pack"
    assert "hidden-path" not in str(error.value)


def test_empty_assertion_rejected_at_execution_boundary():
    from asclepius.checks import validate_assertions
    from asclepius.domain import DeterministicAssertion

    check = load_pack("broad-chat-v1")[0].model_copy(
        update={
            "deterministic_assertions": (
                DeterministicAssertion(kind="exact_canary", name="empty", value=""),
            )
        }
    )
    with pytest.raises(AppError) as error:
        validate_assertions(check)
    assert error.value.code == "invalid_check"


def test_pack_queue_uses_pinned_plan(tmp_path, monkeypatch, capsys):
    import asyncio

    from asclepius.domain import ProfileConfig, TargetConfig
    from asclepius.storage import Repository
    from tests.cli.test_cli_profiles import evaluator_file

    async def setup():
        repo = Repository(tmp_path / "data")
        await repo.initialize()
        await repo.save_profile(
            ProfileConfig(
                target=TargetConfig(name="target", model="target", secret_ref="env:CLI_TEST_KEY")
            )
        )
        await repo.set_ready("test-owner")
        return repo

    repo = asyncio.run(setup())
    monkeypatch.setenv("CLI_TEST_KEY", "synthetic-key-only")
    assert (
        main(
            [
                "--data-dir",
                str(repo.data_dir),
                "--json",
                "run",
                "target",
                "--pack",
                "broad-chat-v1",
                "--evaluator",
                str(evaluator_file(tmp_path)),
            ]
        )
        == 0
    )
    import json

    identity = json.loads(capsys.readouterr().out)["data"]["id"]
    view = asyncio.run(repo.read_run(identity))
    assert view.state == "queued"
    plan = load_pack_plan("broad-chat-v1")
    assert view.snapshot.checks == plan.checks and view.snapshot.prompts == plan.prompts
