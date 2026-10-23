import json
from dataclasses import dataclass
from urllib.parse import unquote
from uuid import UUID

from jsonschema import Draft202012Validator, SchemaError
from jsonschema import ValidationError as SchemaValidationError
from pydantic import BaseModel, ValidationError
from referencing import Registry
from referencing.exceptions import Unresolvable

from asclepius.adapters.chat import ROLES, GroqConnection, PreparedCall
from asclepius.domain import AppError, ChatInput, Message, Observation, OperationRequest


@dataclass(frozen=True)
class PreparedEvaluation:
    call: PreparedCall
    output_type: type[BaseModel]


@dataclass(frozen=True)
class EvaluationResult:
    call: PreparedCall
    observation: Observation
    output: BaseModel | None = None
    error_code: str | None = None


class ModelCallError(AppError):
    def __init__(self, result: EvaluationResult) -> None:
        super().__init__(result.error_code or "evaluator_failure", "Evaluator invocation failed.")
        self.result = result


def strict_schema(output_type: type[BaseModel]) -> dict:
    try:
        schema = output_type.model_json_schema()
    except (TypeError, ValueError):
        raise AppError("unsupported_schema", "Cannot encode evaluator output schema.", 2) from None

    def normalize(node):
        if isinstance(node, list):
            for child in node:
                normalize(child)
        elif isinstance(node, dict):
            unsupported = {
                "$id",
                "$dynamicRef",
                "$dynamicAnchor",
                "$recursiveRef",
                "$anchor",
                "if",
                "then",
                "else",
                "dependentSchemas",
                "patternProperties",
                "propertyNames",
                "contains",
                "unevaluatedProperties",
                "unevaluatedItems",
                "contentSchema",
                "definitions",
                "additionalItems",
            }
            if unsupported & node.keys():
                raise AppError("unsupported_schema", "Unsupported evaluator schema keyword.", 2)
            if "$ref" in node:
                reference = node["$ref"]
                if not isinstance(reference, str) or not reference.startswith("#/"):
                    raise AppError(
                        "unsupported_schema", "Only local schema references are supported.", 2
                    )
                target = schema
                try:
                    for part in unquote(reference[2:]).split("/"):
                        key = part.replace("~1", "/").replace("~0", "~")
                        target = target[int(key)] if isinstance(target, list) else target[key]
                except (KeyError, IndexError, ValueError, TypeError):
                    raise AppError(
                        "unsupported_schema", "Unresolved evaluator schema reference.", 2
                    ) from None
                if not isinstance(target, (dict, bool)):
                    raise AppError("unsupported_schema", "Invalid evaluator schema reference.", 2)
            if "prefixItems" in node:
                raise AppError(
                    "unsupported_schema", "Fixed tuples are unsupported by this gateway.", 2
                )
            if node.get("type") == "object":
                if node.get("additionalProperties") is not False:
                    raise AppError(
                        "unsupported_schema",
                        "Evaluator object schemas must explicitly forbid extra fields.",
                        2,
                    )
                node["additionalProperties"] = False
                node["required"] = list(node.get("properties", {}))
            node.pop("default", None)
            for keyword in ("properties", "$defs"):
                for child in node.get(keyword, {}).values():
                    normalize(child)
            for keyword in ("items", "anyOf", "oneOf", "allOf", "not"):
                if keyword in node:
                    normalize(node[keyword])

    normalize(schema)
    if schema.get("type") != "object":
        raise AppError("unsupported_schema", "Evaluator output must be an object.", 2)
    try:
        Draft202012Validator.check_schema(schema)
    except (SchemaError, RecursionError):
        raise AppError("unsupported_schema", "Invalid evaluator output schema.", 2) from None
    return schema


def _invalid_constant(value):
    raise ValueError("Non-finite JSON constant")


class ModelGateway:
    def __init__(self, connection: GroqConnection, *, work_item_id: UUID) -> None:
        self.connection = connection
        self.work_item_id = work_item_id

    def prepare(self, role: str, payload: dict, output_type: type[BaseModel]) -> PreparedEvaluation:
        if role not in ROLES:
            raise AppError("arguments", "Unknown evaluator role.", 2)
        prompts = [item for item in self.connection.snapshot.prompts if item.role == role]
        if len(prompts) != 1 or not prompts[0].content.strip():
            raise AppError("missing_prompt", "Exactly one pinned evaluator prompt is required.", 2)
        schema = strict_schema(output_type)
        try:
            content = json.dumps(
                self.connection.redact_value(payload), ensure_ascii=False, allow_nan=False
            )
        except (ValueError, TypeError, RecursionError):
            raise AppError("invalid_input", "Cannot encode evaluator input.", 2) from None
        request = OperationRequest(
            run_id=self.connection.snapshot.id,
            work_item_id=self.work_item_id,
            actor=role,
            payload=ChatInput(
                messages=(
                    Message(role="system", content=prompts[0].content),
                    Message(role="user", content=content),
                )
            ),
        )
        call = self.connection.prepare(
            request,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": role + "_output",
                    "strict": True,
                    "schema": schema,
                },
            },
        )
        return PreparedEvaluation(call, output_type)

    async def execute(self, prepared: PreparedEvaluation) -> EvaluationResult:
        if (
            prepared.call.request.actor not in ROLES
            or prepared.call.request.work_item_id != self.work_item_id
        ):
            raise AppError("operation_identity", "Gateway requires an evaluator operation.", 2)
        observation = await self.connection.execute(prepared.call)
        code = observation.error_code
        output = None
        if code is None and observation.truncated:
            code = "evaluator_truncated"
        if code is None:
            try:
                raw = json.loads(observation.payload.content, parse_constant=_invalid_constant)
                schema = json.loads(prepared.call.body_json)["response_format"]["json_schema"][
                    "schema"
                ]
                Draft202012Validator(schema, registry=Registry()).validate(raw)
                output = prepared.output_type.model_validate_json(
                    observation.payload.content, strict=True
                )
            except (
                ValidationError,
                SchemaValidationError,
                ValueError,
                RecursionError,
                Unresolvable,
            ):
                code = "evaluator_invalid_output"
        return EvaluationResult(prepared.call, observation, output, code)

    async def generate(self, role: str, payload: dict, output_type: type[BaseModel]) -> BaseModel:
        result = await self.execute(self.prepare(role, payload, output_type))
        if result.error_code is not None:
            raise ModelCallError(result)
        return result.output
