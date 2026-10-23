import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from enum import StrEnum
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

PositiveInt = Annotated[int, Field(gt=0, strict=True)]
NonNegativeInt = Annotated[int, Field(ge=0, strict=True)]
Identity = Annotated[str, Field(min_length=1, max_length=128)]
SecretRef = Annotated[str, Field(pattern=r"^env:[A-Za-z_][A-Za-z0-9_]*$")]


def _utc_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamps require a timezone.")
    return value.astimezone(UTC)


UtcTime = Annotated[datetime, AfterValidator(_utc_timestamp)]

_HTTP_DATE = re.compile(
    r"(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun), [0-9]{2} "
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) [0-9]{4} "
    r"[0-9]{2}:[0-9]{2}:[0-9]{2} GMT|"
    r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday), [0-9]{2}-"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)-[0-9]{2} "
    r"[0-9]{2}:[0-9]{2}:[0-9]{2} GMT|"
    r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) "
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) (?:[0-9]{2}| [0-9]) "
    r"[0-9]{2}:[0-9]{2}:[0-9]{2} [0-9]{4})"
)


def _retry_after(value: str) -> str:
    if re.fullmatch(r"[0-9]+", value):
        return value
    if _HTTP_DATE.fullmatch(value):
        try:
            parsedate_to_datetime(value)
            return value
        except (ValueError, OverflowError):
            pass
    raise ValueError("Retry-After requires decimal seconds or an HTTP date.")


RetryAfter = Annotated[
    str, Field(min_length=1, max_length=128, strict=True), AfterValidator(_retry_after)
]


def _endpoint(value: str) -> str:
    if any(ord(char) < 33 or ord(char) == 127 for char in value) or "\\" in value:
        raise ValueError("Invalid endpoint URL.")
    try:
        parts = urlsplit(value)
        port = parts.port
        host = parts.hostname
        scheme_allowed = parts.scheme == "https" or (
            parts.scheme == "http" and host in {"localhost", "127.0.0.1", "::1"}
        )
        valid = (
            scheme_allowed
            and host
            and not (
                parts.username is not None
                or parts.password is not None
                or parts.query
                or parts.fragment
            )
            and (port is None or port > 0)
        )
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("Invalid endpoint URL or unsafe credentials in URL.")
    return value


Endpoint = Annotated[str, AfterValidator(_endpoint)]


class AppError(Exception):
    def __init__(self, code: str, message: str, exit_code: int = 5) -> None:
        super().__init__(message)
        self.code = code
        self.exit_code = exit_code


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class RunState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


_TRANSITIONS = {
    RunState.QUEUED: frozenset((RunState.RUNNING, RunState.CANCELLED)),
    RunState.RUNNING: frozenset(
        (RunState.COMPLETED, RunState.FAILED, RunState.CANCELLED, RunState.INTERRUPTED)
    ),
}


def allowed_transition(current: RunState, next_state: RunState) -> RunState:
    if next_state not in _TRANSITIONS.get(current, ()):
        raise AppError("invalid_transition", "Run state transition is not allowed.", 2)
    return next_state


class Limits(Contract):
    active_runs: PositiveInt = 1
    outbound_concurrency: PositiveInt = 4
    target_concurrency: PositiveInt = 2
    evaluator_concurrency: PositiveInt = 2
    target_calls: PositiveInt = 100
    evaluator_calls: PositiveInt = 220
    total_calls: PositiveInt = 300
    requests_per_minute: PositiveInt = 10
    request_timeout_seconds: PositiveInt = 60
    run_timeout_seconds: PositiveInt = 2700
    completion_tokens: PositiveInt = 500000
    target_input_bytes: PositiveInt = 16384
    evaluator_input_bytes: PositiveInt = 65536
    response_bytes: PositiveInt = 1048576


class TargetConfig(Contract):
    name: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")]
    adapter: Literal["groq-chat", "ollama-chat"] = "groq-chat"
    model: Identity
    base_url: Endpoint = "https://api.groq.com/openai/v1"
    secret_ref: SecretRef | None = None
    system_prompt: str = ""
    resource_key: Identity | None = None
    temperature: Annotated[float, Field(ge=0, le=2)] = 0
    max_completion_tokens: PositiveInt = 512
    capabilities: tuple[Literal["chat.v1"], ...] = ("chat.v1",)

    @model_validator(mode="after")
    def validate_secret(self) -> "TargetConfig":
        if self.adapter == "groq-chat" and self.secret_ref is None:
            raise ValueError("Hosted target requires a secret reference.")
        if self.adapter == "groq-chat" and urlsplit(self.base_url).scheme != "https":
            raise ValueError("Hosted endpoints require HTTPS.")
        return self


class ProfileConfig(Contract):
    schema_version: Literal[1] = 1
    target: TargetConfig
    limits: Limits = Field(default_factory=Limits)


class RoleConfig(Contract):
    provider: Literal["groq"] = "groq"
    model: Identity
    base_url: Endpoint = "https://api.groq.com/openai/v1"
    secret_ref: SecretRef
    temperature: Annotated[float, Field(ge=0, le=2)] = 0
    max_completion_tokens: PositiveInt = 2048

    @model_validator(mode="after")
    def validate_hosted_endpoint(self) -> "RoleConfig":
        if urlsplit(self.base_url).scheme != "https":
            raise ValueError("Hosted endpoints require HTTPS.")
        return self


class Roles(Contract):
    selector: RoleConfig
    generator: RoleConfig
    judge: RoleConfig
    reporter: RoleConfig


class EvaluatorConfig(Contract):
    schema_version: Literal[1] = 1
    roles: Roles


class CheckDefinition(Contract):
    id: Identity
    version: Identity
    family: Identity
    objective: Annotated[str, Field(min_length=1)]
    system_prompt: str
    strategies: Annotated[tuple[str, ...], Field(min_length=1)]
    benign_control: str
    rubric: Annotated[str, Field(min_length=1)]
    capabilities: tuple[Literal["chat.v1"], ...] = ("chat.v1",)
    severity: Literal["info", "low", "medium", "high", "critical"] = "medium"


class Selection(Contract):
    check_id: Identity
    check_version: Identity
    strategy: str
    rationale: str


class Message(Contract):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatInput(Contract):
    messages: Annotated[tuple[Message, ...], Field(min_length=1)]


class TokenUsage(Contract):
    input_tokens: NonNegativeInt | None = None
    output_tokens: NonNegativeInt | None = None


class ChatOutput(Contract):
    content: str
    response_id: str | None = None
    finish_reason: str | None = None
    usage: TokenUsage = Field(default_factory=TokenUsage)
    raw_content_bytes: NonNegativeInt | None = None
    content_redacted: bool = False


class Variant(Contract):
    id: UUID = Field(default_factory=uuid4)
    check_id: Identity
    kind: Literal["attack", "control"]
    payload: ChatInput


class OperationRequest(Contract):
    schema_version: Literal[1] = 1
    id: UUID = Field(default_factory=uuid4)
    kind: Literal["chat.v1"] = "chat.v1"
    run_id: UUID
    work_item_id: UUID
    actor: Identity = "target"
    payload: ChatInput
    provider_body_json: str | None = None


class OperationIntent(Contract):
    operation_id: UUID
    created: bool
    status: Literal["pending", "observed", "unknown"]


class Observation(Contract):
    schema_version: Literal[1] = 1
    id: UUID = Field(default_factory=uuid4)
    kind: Literal["chat.v1"] = "chat.v1"
    operation_id: UUID
    run_id: UUID
    work_item_id: UUID
    actor: Identity = "target"
    status: Literal["success", "transport_error", "unknown"]
    started_at: UtcTime
    finished_at: UtcTime | None = None
    payload: ChatOutput | None = None
    error_code: str | None = None
    retry_after: RetryAfter | None = None
    truncated: bool = False
    request_payload: ChatInput | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> "Observation":
        if self.started_at.tzinfo is None:
            raise ValueError("Observation timestamps require a timezone.")
        if self.finished_at is not None:
            if self.finished_at.tzinfo is None or self.finished_at < self.started_at:
                raise ValueError("Observation finish time must follow its start time.")
        if self.status == "success":
            if self.payload is None or self.error_code is not None or self.finished_at is None:
                raise ValueError("Successful observations require a reply and finish time.")
        elif self.payload is not None:
            raise ValueError("Failed or unknown observations cannot contain a claimed reply.")
        elif self.status == "transport_error" and not self.error_code:
            raise ValueError("Transport failures require an error code.")
        return self


class EvidenceRef(Contract):
    observation_id: UUID
    quote: Annotated[str, Field(min_length=1)]


class AssertionResult(Contract):
    name: Identity
    outcome: Literal["met", "not_met", "inconclusive"]
    rationale: str


class Metric(Contract):
    name: Identity
    value: Annotated[float, Field(allow_inf_nan=False)]
    denominator: NonNegativeInt | None = None


class Judgment(Contract):
    id: UUID = Field(default_factory=uuid4)
    variant_id: UUID
    rubric_version: Identity
    security_verdict: Literal["weakness", "pass", "inconclusive"] | None = None
    assertions: tuple[AssertionResult, ...] = ()
    metrics: tuple[Metric, ...] = ()
    evidence: tuple[EvidenceRef, ...] = ()
    rationale: str
    confidence: Annotated[float, Field(ge=0, le=1)] | None = None

    @model_validator(mode="after")
    def validate_weakness(self) -> "Judgment":
        if self.security_verdict == "weakness" and not self.evidence:
            raise ValueError("Weakness judgments require evidence.")
        return self


class Finding(Contract):
    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    variant_id: UUID
    judgment_id: UUID
    severity: Literal["info", "low", "medium", "high", "critical"]
    description: str
    reproduction: str
    recommendation: str
    evidence: Annotated[tuple[EvidenceRef, ...], Field(min_length=1)]


class SelectionOutput(Contract):
    stage: Literal["selector"] = "selector"
    selections: tuple[Selection, ...]


class GenerationOutput(Contract):
    stage: Literal["generator"] = "generator"
    variants: tuple[Variant, ...]


class JudgmentOutput(Contract):
    stage: Literal["judge"] = "judge"
    judgment: Judgment


class FindingOutput(Contract):
    stage: Literal["reporter"] = "reporter"
    finding: Finding


StageOutput = Annotated[
    SelectionOutput | GenerationOutput | JudgmentOutput | FindingOutput,
    Field(discriminator="stage"),
]


class PromptSnapshot(Contract):
    role: Literal["selector", "generator", "judge", "reporter"]
    version: Identity
    content: str


class SubmissionPlan(Contract):
    schema_version: Literal[1] = 1
    checks: Annotated[tuple[CheckDefinition, ...], Field(min_length=1)]
    prompts: tuple[PromptSnapshot, ...]

    @model_validator(mode="after")
    def validate_plan(self) -> "SubmissionPlan":
        if len({check.id for check in self.checks}) != len(self.checks):
            raise ValueError("Check identities must be unique.")
        roles = {"selector", "generator", "judge", "reporter"}
        if len(self.prompts) != 4 or {prompt.role for prompt in self.prompts} != roles:
            raise ValueError("Exactly one prompt per role is required.")
        if any(not prompt.content.strip() for prompt in self.prompts):
            raise ValueError("Prompt content cannot be blank.")
        return self


class ProfileRecord(Contract):
    id: UUID
    revision: PositiveInt
    config: ProfileConfig


class RunSummary(Contract):
    id: UUID
    profile_id: UUID
    profile_name: str
    state: RunState
    cancel_requested: bool
    created_at: UtcTime
    source_run_id: UUID | None = None


class Page[T](Contract):
    items: tuple[T, ...]
    next_cursor: str | None = None


class RunSnapshot(Contract):
    schema_version: Literal[1] = 1
    id: UUID = Field(default_factory=uuid4)
    profile_id: UUID
    profile: ProfileConfig
    evaluator: EvaluatorConfig
    checks: Annotated[tuple[CheckDefinition, ...], Field(min_length=1)]
    prompts: tuple[PromptSnapshot, ...] = ()
    source_run_id: UUID | None = None
    created_at: UtcTime = Field(default_factory=lambda: datetime.now(UTC))


class DaemonStatus(Contract):
    instance_id: UUID | None = None
    state: Literal["stopped", "starting", "ready", "draining"] = "stopped"
    pid: PositiveInt | None = None
    heartbeat_at: UtcTime | None = None
    owned: bool = False
    responsive: bool = False
    execution_available: bool = False


class BudgetReservation(Contract):
    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    kind: Literal["target", "evaluator", "cleanup"]
    max_output: PositiveInt


class RunView(Contract):
    snapshot: RunSnapshot
    state: RunState
    cancel_requested: bool = False
    reason: str | None = None
    observations: tuple[Observation, ...] = ()
    judgments: tuple[Judgment, ...] = ()
    findings: tuple[Finding, ...] = ()


class Comparison(Contract):
    schema_version: Literal[1] = 1
    runs: Annotated[tuple[RunView, ...], Field(min_length=2)]
    compatible: bool
    differences: tuple[str, ...] = ()


class ExportArtifact(Contract):
    format: Literal["json", "markdown", "html"]
    content: str
