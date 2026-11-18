import asyncio
from dataclasses import dataclass
from uuid import UUID

from asclepius.adapters.chat import ChatAdapter, DispatchFailure, GroqConnection, PreparedCall
from asclepius.adapters.ollama import OllamaAdapter
from asclepius.agents import AgentRunner, check_work_item, selector_work_item
from asclepius.domain import (
    AppError,
    FindingOutput,
    GenerationOutput,
    JudgmentOutput,
    Observation,
    OperationRequest,
    RunSnapshot,
    RunState,
    SelectionOutput,
    StageAttempt,
    StageOutput,
    Variant,
)
from asclepius.limits import BudgetManager
from asclepius.models import EvaluationResult, ModelGateway, PreparedEvaluation
from asclepius.storage import Repository
from asclepius.transport import JsonTransport

_FATAL = frozenset(
    {
        "ownership",
        "storage_busy",
        "storage_error",
        "storage_corrupt",
        "schema_version",
        "storage_missing",
    }
)


_RUN_STOPPING_TARGET_ERRORS = frozenset(
    {
        "local_model_missing",
        "provider_http_401",
        "provider_http_403",
        "provider_http_404",
        "secret_invalid",
        "transport_config",
    }
)


@dataclass(frozen=True)
class _RunSession:
    repo: Repository
    budgets: BudgetManager
    connection: GroqConnection

    @property
    def snapshot(self) -> RunSnapshot:
        return self.connection.snapshot

    async def checkpoint(self) -> None:
        await self.budgets.checkpoint(self.snapshot)

    def role(self, work: UUID, stage: str) -> "_Invocation":
        return _Invocation(self, work, stage)

    async def intent(self, call: PreparedCall) -> None:
        await self.checkpoint()
        intent = await self.repo.begin_operation(call.request, instance_id=self.budgets.instance_id)
        if not intent.created:
            raise AppError(
                "operation_exists", "An existing intent does not authorize retransmission."
            )

    async def save(self, observation: Observation) -> None:
        await self.repo.save_observation(observation, instance_id=self.budgets.instance_id)

    async def target(self, variant: Variant) -> Observation:
        local = self.snapshot.profile.target.adapter == "ollama-chat"
        adapter = OllamaAdapter if local else ChatAdapter
        call = adapter(self.connection).prepare(
            OperationRequest(
                run_id=self.snapshot.id, work_item_id=variant.id, payload=variant.payload
            )
        )
        await self.intent(call)
        try:
            observation = await self.connection.execute(call)
        except DispatchFailure as error:
            await self.save(error.observation)
            raise
        await self.save(observation)
        if observation.error_code in _RUN_STOPPING_TARGET_ERRORS:
            raise AppError(observation.error_code, "Target request failed.")
        return observation


class _Invocation:
    def __init__(self, session: _RunSession, work: UUID, stage: str):
        self.session = session
        self.work = work
        self.stage = stage
        self.attempt: StageAttempt | None = None
        self.completed = False

    @property
    def agents(self) -> AgentRunner:
        return AgentRunner(self.session.connection, dispatch=self.dispatch)

    async def __aenter__(self):
        await self.session.checkpoint()
        self.attempt = await self.session.repo.begin_stage(
            str(self.session.snapshot.id),
            str(self.work),
            self.stage,
            instance_id=self.session.budgets.instance_id,
        )
        return self

    async def dispatch(
        self, gateway: ModelGateway, prepared: PreparedEvaluation
    ) -> EvaluationResult:
        request = prepared.call.request
        if (request.actor, request.work_item_id, request.run_id) != (
            self.attempt.stage,
            self.attempt.work_item_id,
            self.attempt.run_id,
        ):
            raise AppError("operation_identity", "Prepared invocation does not match its stage.")
        await self.session.intent(prepared.call)
        try:
            result = await gateway.execute(prepared)
        except DispatchFailure as error:
            await self.session.save(error.observation)
            raise
        await self.session.save(result.observation)
        return result

    async def complete(self, output: StageOutput) -> None:
        await self.session.repo.commit_stage(
            str(self.session.snapshot.id),
            str(self.work),
            self.stage,
            output,
            instance_id=self.session.budgets.instance_id,
        )
        self.completed = True

    async def __aexit__(self, kind, error, traceback):
        if not self.completed:
            code = (
                error.code
                if isinstance(error, AppError)
                else "execution_cancelled"
                if isinstance(error, asyncio.CancelledError)
                else "execution_failed"
                if kind
                else "stage_incomplete"
            )
            if code not in _FATAL and not (
                isinstance(error, DispatchFailure) and error.settlement_failed
            ):
                await self.session.repo.fail_stage(
                    self.attempt, code, instance_id=self.session.budgets.instance_id
                )
        return False


class Coordinator:
    def __init__(
        self, repo: Repository, budgets: BudgetManager, *, transport: JsonTransport | None = None
    ):
        self.repo = repo
        self.budgets = budgets
        self.transport = transport or JsonTransport()

    async def execute(self, snapshot: RunSnapshot) -> None:
        state, reason = RunState.COMPLETED, None
        try:
            await self.repo.phase(
                str(snapshot.id), "preflight", instance_id=self.budgets.instance_id
            )
            connection = GroqConnection(snapshot, self.budgets, transport=self.transport)
            connection.validate_credentials()
            session = _RunSession(self.repo, self.budgets, connection)
            await self.repo.phase(
                str(snapshot.id), "selecting", instance_id=self.budgets.instance_id
            )
            work = selector_work_item(snapshot)
            await self.repo.register_work_item(
                str(snapshot.id),
                str(work),
                snapshot.checks[0].id,
                instance_id=self.budgets.instance_id,
            )
            async with session.role(work, "selector") as invocation:
                selections = await invocation.agents.select(snapshot)
                await invocation.complete(SelectionOutput(selections=tuple(selections)))
            checks = {check.id: check for check in snapshot.checks}
            await self.repo.phase(
                str(snapshot.id), "evaluating", instance_id=self.budgets.instance_id
            )
            for selection in selections:
                check = checks[selection.check_id]
                work = check_work_item(snapshot, check)
                await self.repo.register_work_item(
                    str(snapshot.id), str(work), check.id, instance_id=self.budgets.instance_id
                )
                async with session.role(work, "generator") as invocation:
                    variants = await invocation.agents.generate(selection)
                    await invocation.complete(GenerationOutput(variants=tuple(variants)))
                for variant in variants:
                    observation = await session.target(variant)
                    async with session.role(variant.id, "judge") as invocation:
                        judgment = await invocation.agents.judge(check, variant, observation)
                        await invocation.complete(JudgmentOutput(judgment=judgment))
                    if judgment.security_verdict == "weakness":
                        async with session.role(variant.id, "reporter") as invocation:
                            finding = await invocation.agents.report(judgment, observation)
                            await invocation.complete(FindingOutput(finding=finding))
            await session.checkpoint()
        except AppError as error:
            if error.code in _FATAL or (
                isinstance(error, DispatchFailure) and error.settlement_failed
            ):
                raise
            state = RunState.CANCELLED if error.code == "run_cancelled" else RunState.FAILED
            reason = error.code
        await self.repo.phase(str(snapshot.id), "settling", instance_id=self.budgets.instance_id)
        try:
            await self.repo.finalize(
                str(snapshot.id), state, reason, instance_id=self.budgets.instance_id
            )
        except AppError as error:
            if state != RunState.COMPLETED or error.code != "run_cancelled":
                raise
            await self.repo.finalize(
                str(snapshot.id),
                RunState.CANCELLED,
                "run_cancelled",
                instance_id=self.budgets.instance_id,
            )
