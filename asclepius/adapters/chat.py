import asyncio
import json
import os
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from asclepius.domain import (
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
from asclepius.transport import JsonTransport, ProviderHttpError

ROLES = frozenset({"selector", "generator", "judge", "reporter"})


class PreparedCall(Contract):
    request: OperationRequest

    @property
    def body_json(self) -> str:
        if self.request.provider_body_json is None:
            raise AppError("unprepared_call", "Provider call has not been prepared.", 2)
        return self.request.provider_body_json


class _WireModel(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, hide_input_in_errors=True)


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
    """A local Ollama target: no credential, native wire format, same budgets and limits."""
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
            from asclepius.adapters import ollama

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
        kind = "target" if request.actor == "target" else "evaluator"
        cap = min(
            getattr(self.snapshot.profile.limits, f"{kind}_input_bytes"),
            getattr(self.budgets.limits, f"{kind}_input_bytes"),
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
            secret = self._secrets.get(config.secret_ref)
            if not secret:
                raise AppError("secret_missing", "Selected provider credential is unavailable.", 2)
            if any(ord(char) < 33 or ord(char) > 126 for char in secret):
                raise AppError("secret_invalid", "Selected provider credential is invalid.", 2)

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
            secret = None
            if not local:
                secret = self._secrets.get(config.secret_ref)
                if not secret:
                    raise AppError(
                        "secret_missing", "Selected provider credential is unavailable.", 2
                    )
                if any(ord(char) < 33 or ord(char) > 126 for char in secret):
                    raise AppError("secret_invalid", "Selected provider credential is invalid.", 2)
            body = json.loads(call.body_json)
            kind = "target" if request.actor == "target" else "evaluator"
            role = None if kind == "target" else request.actor
            pinned = self.snapshot.profile.limits
            deadline = min(
                pinned.request_timeout_seconds, self.budgets.limits.request_timeout_seconds
            )
            cap = min(pinned.response_bytes, self.budgets.limits.response_bytes)
            reservation = await self.budgets.reserve(
                str(request.run_id), kind, config.max_completion_tokens
            )
            # Rough upper bound for the tokens-per-minute budget: about 4 bytes per input
            # token plus the full output cap. Measured usage replaces it after the reply.
            estimate = -(-len(call.body_json.encode("utf-8")) // 4) + config.max_completion_tokens
            async with self.budgets.slot(self.snapshot, kind, role=role, tokens=estimate) as lease:
                phase = "authorizing"
                await self.budgets.dispatch(reservation)
                phase = "dispatched"
                try:
                    if local:
                        from asclepius.adapters import ollama

                        url = ollama.chat_url(config.base_url)
                    else:
                        url = config.base_url.rstrip("/") + "/chat/completions"
                    try:
                        data = await self.transport.post(
                            url,
                            body,
                            secret=secret,
                            deadline_seconds=deadline,
                            response_bytes=cap,
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


class ChatAdapter:
    def __init__(self, connection: GroqConnection) -> None:
        self.connection = connection

    def prepare(self, request: OperationRequest) -> PreparedCall:
        if request.actor != "target":
            raise AppError("operation_identity", "Target adapter requires a target operation.", 2)
        system = self.connection.snapshot.profile.target.system_prompt
        messages = request.payload.messages
        if system:
            messages = (Message(role="system", content=system), *messages)
        return self.connection.prepare(
            request.model_copy(update={"payload": ChatInput(messages=messages)})
        )

    async def execute_prepared(self, call: PreparedCall) -> Observation:
        if call.request.actor != "target":
            raise AppError("operation_identity", "Target adapter requires a target operation.", 2)
        return await self.connection.execute(call)

    async def execute(self, request: OperationRequest) -> Observation:
        return await self.execute_prepared(self.prepare(request))
