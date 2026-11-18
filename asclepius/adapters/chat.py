import asyncio
import json
import os
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, ValidationError

from asclepius.adapters import ollama
from asclepius.adapters.ollama import _WireModel
from asclepius.domain import (
    ROLES,
    AppError,
    ChatInput,
    ChatOutput,
    Contract,
    Message,
    NonNegativeInt,
    Observation,
    OperationRequest,
    RunSnapshot,
    TokenUsage,
)
from asclepius.limits import BudgetManager
from asclepius.transport import JsonTransport, ProviderHttpError, valid_secret


class PreparedCall(Contract):
    request: OperationRequest

    @property
    def body_json(self) -> str:
        if self.request.provider_body_json is None:
            raise AppError("unprepared_call", "Provider call has not been prepared.", 2)
        return self.request.provider_body_json


BYTES_PER_INPUT_TOKEN = 4


def token_upper_bound(body_json: str, max_completion_tokens: int) -> int:
    input_tokens = -(-len(body_json.encode("utf-8")) // BYTES_PER_INPUT_TOKEN)
    return input_tokens + max_completion_tokens


class _Usage(_WireModel):
    prompt_tokens: NonNegativeInt | None = None
    completion_tokens: NonNegativeInt | None = None


class _ReplyMessage(_WireModel):
    role: Literal["assistant"]
    content: str | None = None
    refusal: str | None = None
    tool_calls: list[dict] | None = None
    function_call: dict | None = None


class _Choice(_WireModel):
    index: Literal[0] = 0
    finish_reason: str
    message: _ReplyMessage


class _Reply(_WireModel):
    id: str | None = None
    model: str | None = None
    choices: list[_Choice] = Field(min_length=1, max_length=1)
    usage: _Usage | None = None


def _is_local(actor: str, config) -> bool:
    return actor == "target" and config.adapter == "ollama-chat"


class DispatchFailure(AppError):
    def __init__(
        self, code: str, observation: Observation, *, settlement_failed: bool = False
    ) -> None:
        super().__init__(code, "Provider dispatch could not complete durably.")
        self.observation = observation
        self.settlement_failed = settlement_failed


class GroqConnection:
    def __init__(
        self,
        snapshot: RunSnapshot,
        budgets: BudgetManager,
        *,
        transport: JsonTransport | None = None,
    ) -> None:
        self.snapshot = snapshot
        self.budgets = budgets
        self.transport = transport or JsonTransport()
        refs = {snapshot.profile.target.secret_ref}
        refs.update(getattr(snapshot.evaluator.roles, role).secret_ref for role in ROLES)
        self._secrets = {ref: os.environ.get(ref[4:]) for ref in refs if ref}
        self._redactions = tuple(
            sorted({value for value in self._secrets.values() if value}, key=len, reverse=True)
        )

    def redact(self, text: str) -> str:
        for secret in self._redactions:
            text = text.replace(secret, "[REDACTED]")
        return text

    def redact_value(self, value, *, depth: int = 0):
        if depth >= 64:
            raise AppError(
                "redaction_limit", "Content exceeds the safe redaction nesting limit.", 2
            )
        if isinstance(value, str):
            return self.redact_content(value, depth=depth + 1)
        if isinstance(value, dict):
            return {
                self.redact_content(key, depth=depth + 1)
                if isinstance(key, str)
                else key: self.redact_value(item, depth=depth + 1)
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [self.redact_value(item, depth=depth + 1) for item in value]
        return value

    def redact_content(self, text: str, *, depth: int = 0) -> str:
        if depth >= 64:
            raise AppError(
                "redaction_limit", "Content exceeds the safe redaction nesting limit.", 2
            )
        redacted = self.redact(text)
        try:
            value = json.loads(text)
        except ValueError:
            return redacted
        except RecursionError:
            raise AppError(
                "redaction_limit", "Content exceeds the safe redaction nesting limit.", 2
            ) from None
        clean = self.redact_value(value, depth=depth + 1)
        if clean != value:
            return json.dumps(clean, ensure_ascii=False, separators=(",", ":"))
        return redacted

    def _config(self, actor: str):
        if actor == "target":
            config = self.snapshot.profile.target
            if config.adapter not in {"groq-chat", "ollama-chat"}:
                raise AppError("unsupported_adapter", "Unsupported target adapter.", 2)
            return config
        if actor not in ROLES:
            raise AppError("arguments", "Unknown evaluator role.", 2)
        return getattr(self.snapshot.evaluator.roles, actor)

    def prepare_target(self, work_item_id: UUID, payload: ChatInput) -> PreparedCall:
        system = self.snapshot.profile.target.system_prompt
        messages = payload.messages
        if system:
            messages = (Message(role="system", content=system), *messages)
        return self.prepare(
            OperationRequest(
                run_id=self.snapshot.id,
                work_item_id=work_item_id,
                payload=ChatInput(messages=messages),
            )
        )

    def prepare(
        self, request: OperationRequest, *, response_format: dict | None = None
    ) -> PreparedCall:
        if request.run_id != self.snapshot.id:
            raise AppError("operation_identity", "Operation belongs to another run.", 2)
        config = self._config(request.actor)
        if request.provider_body_json is not None:
            raise AppError("prepared_call", "Use the explicit prepared-call execution path.", 2)
        messages = tuple(
            Message(role=item.role, content=self.redact_content(item.content))
            for item in request.payload.messages
        )
        payload = ChatInput(messages=messages)
        wire_messages = payload.model_dump(mode="json")["messages"]
        if _is_local(request.actor, config):
            body = ollama.request_body(config, wire_messages)
        else:
            body = {
                "model": config.model,
                "messages": wire_messages,
                "temperature": config.temperature,
                "max_completion_tokens": config.max_completion_tokens,
                "stream": False,
            }
        reasoning_effort = getattr(config, "reasoning_effort", None)
        if reasoning_effort is not None:
            body["reasoning_effort"] = reasoning_effort
        if response_format is not None:
            body["response_format"] = response_format
        try:
            body_json = json.dumps(body, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            body_bytes = len(body_json.encode("utf-8"))
        except (ValueError, TypeError, RecursionError, UnicodeError):
            raise AppError("invalid_input", "Cannot encode provider request.", 2) from None
        limits = self.snapshot.profile.limits.tightened(self.budgets.limits)
        cap = (
            limits.target_input_bytes if request.actor == "target" else limits.evaluator_input_bytes
        )
        if body_bytes > cap:
            raise AppError("input_too_large", "Provider request exceeds the byte limit.", 2)
        return PreparedCall(
            request=request.model_copy(
                update={
                    "payload": payload,
                    "provider_body_json": body_json,
                }
            )
        )

    def validate_credentials(self) -> None:
        for actor in ("target", *sorted(ROLES)):
            config = self._config(actor)
            if _is_local(actor, config):
                continue
            self._secret(config)

    def _secret(self, config) -> str:
        secret = self._secrets.get(config.secret_ref)
        if not secret:
            raise AppError("secret_missing", "Selected provider credential is unavailable.", 2)
        if not valid_secret(secret):
            raise AppError("secret_invalid", "Selected provider credential is invalid.", 2)
        return secret

    async def execute(self, call: PreparedCall) -> Observation:
        request = call.request
        if request.run_id != self.snapshot.id:
            raise AppError("operation_identity", "Operation belongs to another run.", 2)
        config = self._config(request.actor)
        local = _is_local(request.actor, config)
        started = datetime.now(UTC)
        phase: Literal["reserved", "authorizing", "dispatched"] = "reserved"
        reservation = None
        observation = None
        try:
            secret = None if local else self._secret(config)
            body = json.loads(call.body_json)
            kind = "target" if request.actor == "target" else "evaluator"
            role = None if kind == "target" else request.actor
            limits = self.snapshot.profile.limits.tightened(self.budgets.limits)
            reservation = await self.budgets.reserve(
                str(request.run_id), kind, config.max_completion_tokens
            )
            estimate = token_upper_bound(call.body_json, config.max_completion_tokens)
            async with self.budgets.slot(self.snapshot, kind, role=role, tokens=estimate) as lease:
                phase = "authorizing"
                await self.budgets.dispatch(reservation)
                phase = "dispatched"
                try:
                    if local:
                        url = ollama.chat_url(config.base_url)
                    else:
                        url = config.base_url.rstrip("/") + "/chat/completions"
                    try:
                        data = await self.transport.post(
                            url,
                            body,
                            secret=secret,
                            deadline_seconds=limits.request_timeout_seconds,
                            response_bytes=limits.response_bytes,
                        )
                    except ProviderHttpError as error:
                        # Ollama answers 404 for a model that is not installed locally.
                        if local and error.status_code == 404:
                            raise AppError(
                                "local_model_missing",
                                "The selected model is not installed in the local Ollama server.",
                            ) from None
                        raise
                    if local:
                        data = ollama.as_chat_completion(data)
                    payload, truncated = self._parse(data)
                    used = payload.usage
                    if used.input_tokens is not None and used.output_tokens is not None:
                        lease.record(used.input_tokens + used.output_tokens)
                    observation = self._observation(
                        request, started, payload=payload, truncated=truncated
                    )
                except AppError as error:
                    retry_after = (
                        error.retry_after if isinstance(error, ProviderHttpError) else None
                    )
                    if retry_after is not None and self.redact(retry_after) != retry_after:
                        retry_after = None
                    observation = self._observation(
                        request,
                        started,
                        error_code=error.code,
                        retry_after=retry_after,
                        unknown=error.code in {"provider_timeout", "provider_connection"},
                        truncated=error.code == "response_too_large",
                    )
            await self.budgets.settle(reservation)
            return observation
        except asyncio.CancelledError:
            if reservation is not None:
                if phase == "reserved":
                    await self.budgets.release(reservation)
                elif phase == "dispatched":
                    await self.budgets.settle(reservation)
            raise
        except AppError as dispatch_error:
            code = dispatch_error.code
            settlement_failed = phase == "dispatched" and observation is not None
            if reservation is not None and phase != "dispatched":
                try:
                    await self.budgets.release(reservation)
                except AppError as cleanup_error:
                    settlement_failed = True
                    code = cleanup_error.code
            if observation is None:
                observation = self._observation(
                    request, started, error_code=code, unknown=phase != "reserved"
                )
                observation = observation.model_copy(
                    update={
                        "dispatch_status": "not_dispatched" if phase == "reserved" else "unknown"
                    }
                )
            raise DispatchFailure(code, observation, settlement_failed=settlement_failed) from None

    def _parse(self, data: dict) -> tuple[ChatOutput, bool]:
        try:
            reply = _Reply.model_validate(data)
        except ValidationError:
            raise AppError("provider_response", "Invalid chat completion response.") from None
        choice = reply.choices[0]
        message = choice.message
        if message.refusal or choice.finish_reason == "content_filter":
            raise AppError("provider_refusal", "Provider explicitly refused the request.")
        if (
            message.tool_calls
            or message.function_call
            or choice.finish_reason in {"tool_calls", "function_call"}
        ):
            raise AppError("provider_tools", "Provider returned unsupported tool actions.")
        if choice.finish_reason not in {"stop", "length"} or (
            choice.finish_reason == "stop" and not message.content
        ):
            raise AppError("provider_response", "Provider returned no complete chat reply.")
        raw_content = message.content or ""
        usage = reply.usage or _Usage()
        try:
            raw_content_bytes = len(raw_content.encode("utf-8"))
            if reply.id:
                reply.id.encode("utf-8")
            if reply.model:
                reply.model.encode("utf-8")
        except UnicodeError:
            raise AppError("provider_response", "Invalid Unicode in provider response.") from None
        content = self.redact_content(raw_content)
        provider_model = self.redact_content(reply.model) if reply.model else None
        try:
            if provider_model:
                provider_model.encode("utf-8")
        except UnicodeError:
            raise AppError("provider_response", "Invalid Unicode in provider response.") from None
        return ChatOutput(
            content=content,
            provider_model=provider_model,
            response_id=self.redact(reply.id) if reply.id else None,
            finish_reason=choice.finish_reason,
            usage=TokenUsage(
                input_tokens=usage.prompt_tokens, output_tokens=usage.completion_tokens
            ),
            raw_content_bytes=raw_content_bytes,
            content_redacted=content != raw_content,
        ), choice.finish_reason == "length"

    @staticmethod
    def _observation(
        request,
        started,
        *,
        payload=None,
        error_code=None,
        retry_after=None,
        unknown=False,
        truncated=False,
    ):
        return Observation(
            operation_id=request.id,
            run_id=request.run_id,
            work_item_id=request.work_item_id,
            actor=request.actor,
            started_at=started,
            finished_at=datetime.now(UTC),
            status="unknown" if unknown else "transport_error" if error_code else "success",
            payload=payload,
            error_code=error_code,
            retry_after=retry_after,
            truncated=truncated,
            request_payload=request.payload,
            dispatch_status="attempted",
        )
