from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from asclepius.domain import AppError, NonNegativeInt


class WireModel(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, hide_input_in_errors=True)


class _Message(WireModel):
    role: Literal["assistant"]
    content: str
    tool_calls: list[dict] | None = None


class _Reply(WireModel):
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
