import json
from importlib.resources import files

from jsonschema import Draft202012Validator, SchemaError
from pydantic import TypeAdapter, ValidationError

from asclepius.domain import ROLES, AppError, CheckDefinition, PromptSnapshot, SubmissionPlan


def local_schema(text: str) -> dict:
    try:
        schema = json.loads(text)
    except (ValueError, RecursionError):
        raise AppError("invalid_check", "Invalid local assertion schema.", 2) from None
    if not isinstance(schema, dict):
        raise AppError("invalid_check", "Assertion schema must be an object.", 2)

    def validate(node):
        if isinstance(node, dict):
            if any(k in node for k in ("$id", "$ref", "$dynamicRef")):
                raise AppError("invalid_check", "Assertion schemas must be closed and local.", 2)
            if (node.get("type") == "object" or "properties" in node) and (
                node.get("additionalProperties") is not False
            ):
                raise AppError("invalid_check", "Assertion objects must be closed.", 2)
            for child in node.values():
                validate(child)
        elif isinstance(node, list):
            for child in node:
                validate(child)

    try:
        validate(schema)
        Draft202012Validator.check_schema(schema)
    except (SchemaError, RecursionError):
        raise AppError("invalid_check", "Invalid local assertion schema.", 2) from None
    return schema


def validate_assertions(check: CheckDefinition) -> None:
    if check.assessment_mode == "deterministic" and not check.deterministic_assertions:
        raise AppError("invalid_check", "Deterministic checks require assertions.", 2)
    if len({a.name for a in check.deterministic_assertions}) != len(check.deterministic_assertions):
        raise AppError("invalid_check", "Assertion names must be unique.", 2)
    for assertion in check.deterministic_assertions:
        if not assertion.value.strip():
            raise AppError("invalid_check", "Assertion values cannot be empty.", 2)
        if assertion.kind == "json_schema":
            local_schema(assertion.value)


def require_executable(check: CheckDefinition) -> None:
    if (
        len(check.strategies) != 3
        or len(set(check.strategies)) != 3
        or not all(strategy.strip() for strategy in check.strategies)
        or not check.evidence_criteria.strip()
        or check.severity_rule is None
    ):
        raise AppError(
            "plan_not_executable",
            "Each check needs three distinct strategies, evidence criteria and a severity rule.",
            2,
        )
    validate_assertions(check)


def _resource(path: str) -> str:
    try:
        return files("asclepius").joinpath(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise AppError("invalid_pack", "Built-in pack resource is unavailable.", 2) from None


def load_pack(pack_id: str) -> list[CheckDefinition]:
    if pack_id != "broad-chat-v1":
        raise AppError("pack_unavailable", "Unknown built-in check pack.", 2)
    raw = _resource("packs/broad_chat_v1.json")
    try:
        checks = TypeAdapter(list[CheckDefinition]).validate_json(raw)
    except ValidationError:
        raise AppError("invalid_pack", "Invalid built-in pack content.", 2) from None
    if len(checks) != 20 or len({c.id for c in checks}) != 20:
        raise AppError("invalid_pack", "Invalid built-in pack identities.", 2)
    for check in checks:
        if not all(
            (check.system_prompt.strip(), check.benign_control.strip(), check.rubric.strip())
        ):
            raise AppError("invalid_pack", "Incomplete built-in check.", 2)
        try:
            require_executable(check)
        except AppError as error:
            if error.code != "plan_not_executable":
                raise
            raise AppError("invalid_pack", "Incomplete built-in check.", 2) from None
    return checks


def load_pack_plan(pack_id: str) -> SubmissionPlan:
    checks = load_pack(pack_id)
    return SubmissionPlan(
        checks=tuple(checks),
        prompts=tuple(
            PromptSnapshot(
                role=role,
                version={"judge": "broad-chat-v1.3", "selector": "broad-chat-v1.2"}.get(
                    role, "broad-chat-v1.1"
                ),
                content=_resource(f"prompts/{role}.txt"),
            )
            for role in ROLES
        ),
    )
