"""Local Ollama target over its native, non-streaming /api/chat endpoint.

Only the wire format lives here. Budgets, limits, redaction and saved observations come from
the shared connection, so a local target behaves like a hosted one everywhere else. This
module never pulls models or starts a server; a missing model is reported, not fixed.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from asclepius.adapters.chat import ChatAdapter, PreparedCall
from asclepius.domain import AppError, NonNegativeInt, Observation, OperationRequest

ADAPTER = "ollama-chat"


class _WireModel(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, hide_input_in_errors=True)


class _Message(_WireModel):
    role: Literal["assistant"]
    content: str
    tool_calls: list[dict] | None = None


class _Reply(_WireModel):
    model: str | None = None
    message: _Message
    done: Literal[True]
    done_reason: str | None = None
    prompt_eval_count: NonNegativeInt | None = None
    eval_count: NonNegativeInt | None = None


def chat_url(base_url: str) -> str:
    return base_url.rstrip("/") + "/api/chat"


def request_body(config, messages: list[dict]) -> dict:
    return {
        "model": config.model,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": config.temperature,
            "num_predict": config.max_completion_tokens,
        },
    }


def as_chat_completion(data: dict) -> dict:
    """Restate a native reply in the chat-completion shape the shared parser checks."""
    try:
        reply = _Reply.model_validate(data)
    except ValidationError:
        raise AppError("provider_response", "Invalid Ollama chat response.") from None
    message = reply.message
    finish = "tool_calls" if message.tool_calls else reply.done_reason or "stop"
    return {
        "id": None,
        "model": reply.model,
        "choices": [
            {
                "index": 0,
                "finish_reason": finish,
                "message": {
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": message.tool_calls,
                },
            }
        ],
        "usage": {
            "prompt_tokens": reply.prompt_eval_count,
            "completion_tokens": reply.eval_count,
        },
    }


class OllamaAdapter(ChatAdapter):
    """Target adapter for a user-run local Ollama server and an already installed model."""

    def _require_local(self) -> None:
        if self.connection.snapshot.profile.target.adapter != ADAPTER:
            raise AppError("unsupported_adapter", "This adapter requires an Ollama target.", 2)

    def prepare(self, request: OperationRequest) -> PreparedCall:
        self._require_local()
        return super().prepare(request)

    async def execute_prepared(self, call: PreparedCall) -> Observation:
        self._require_local()
        return await super().execute_prepared(call)
