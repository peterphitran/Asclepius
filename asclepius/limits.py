from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from contextlib import AsyncExitStack, asynccontextmanager
from typing import TYPE_CHECKING, Literal

import httpx

from asclepius.domain import ROLES, AppError, BudgetReservation, Limits, RunSnapshot

if TYPE_CHECKING:
    from asclepius.storage import Repository

Kind = Literal["target", "evaluator"]


def resource_identity(endpoint: str) -> tuple[str, str]:
    parts = httpx.URL(endpoint)
    host = parts.raw_host.decode("ascii").rstrip(".")
    if ":" in host:
        host = f"[{host}]"
    port = parts.port or (443 if parts.scheme == "https" else 80)
    origin = f"{parts.scheme.lower()}://{host}:{port}"
    return origin, origin + (parts.raw_path.decode("ascii").rstrip("/") or "/")


class TokenLease:
    def __init__(self, entries: list[list[float]]) -> None:
        self._entries = entries

    def record(self, tokens: int | None) -> None:
        if tokens is not None:
            for entry in self._entries:
                entry[1] = tokens


class BudgetManager:
    def __init__(self, repo: Repository, instance_id: str, *, limits: Limits | None = None) -> None:
        self.repo = repo
        self.instance_id = instance_id
        self.limits = limits or Limits()
        self._leases: dict[str, list[int]] = defaultdict(list)
        self._rate: dict[str, deque[float]] = defaultdict(deque)
        self._tokens: dict[str, deque[list[float]]] = defaultdict(deque)

    async def reserve(self, run_id: str, kind: str, max_output: int) -> BudgetReservation:
        reservation = BudgetReservation(run_id=run_id, kind=kind, max_output=max_output)
        await self.repo.reserve_budget(reservation, self.instance_id, runtime_limits=self.limits)
        return reservation

    async def dispatch(self, reservation: BudgetReservation) -> None:
        await self.repo.change_reservation(
            reservation, "dispatched", self.instance_id, runtime_limits=self.limits
        )

    async def settle(self, reservation: BudgetReservation) -> None:
        await self.repo.change_reservation(reservation, "settled", self.instance_id)

    async def release(self, reservation: BudgetReservation) -> None:
        await self.repo.change_reservation(reservation, "released", self.instance_id)

    async def checkpoint(self, snapshot: RunSnapshot) -> None:
        await self.repo.execution_checkpoint(
            str(snapshot.id), self.instance_id, runtime_limits=self.limits
        )

    @asynccontextmanager
    async def _gate(self, key: str, limit: int, snapshot: RunSnapshot):
        leases = self._leases[key]
        while True:
            await self.checkpoint(snapshot)
            if len(leases) < min([limit, *leases]):
                leases.append(limit)
                break
            await asyncio.sleep(0.05)
        try:
            yield
        finally:
            leases.remove(limit)

    def _fits_token_window(self, key: str, tokens: int, cap: int) -> bool:
        window = self._tokens[key]
        idle_window_admits_any_size = not window
        return idle_window_admits_any_size or sum(e[1] for e in window) + tokens <= cap

    @asynccontextmanager
    async def slot(
        self, snapshot: RunSnapshot, kind: Kind, *, role: str | None = None, tokens: int = 0
    ):
        if kind not in {"target", "evaluator"}:
            raise AppError(
                "unsupported_operation", "Cleanup requires a separate budget contract.", 2
            )
        target = snapshot.profile.target
        if kind == "target":
            endpoint, secret_ref, grouping = target.base_url, target.secret_ref, target.resource_key
            model = target.model
        else:
            if role not in ROLES:
                raise AppError("arguments", "Evaluator requests require a named role.", 2)
            config = getattr(snapshot.evaluator.roles, role)
            endpoint, secret_ref, grouping = config.base_url, config.secret_ref, None
            model = config.model
        origin, destination = resource_identity(endpoint)
        effective = snapshot.profile.limits.tightened(self.limits)
        global_cap = effective.outbound_concurrency
        destination_cap = getattr(effective, f"{kind}_concurrency")
        async with AsyncExitStack() as stack:
            gates = {
                "global": global_cap,
                f"kind:{kind}": getattr(self.limits, f"{kind}_concurrency"),
                f"destination:{destination}": destination_cap,
                f"origin:{origin}": global_cap,
            }
            if grouping:
                gates[f"group:{grouping}"] = destination_cap
            if secret_ref:
                gates[f"account:{secret_ref}"] = global_cap
            for key, limit in sorted(gates.items()):
                await stack.enter_async_context(self._gate(key, limit, snapshot))
            rate_keys = [f"origin:{origin}"]
            if secret_ref:
                rate_keys.append(f"account:{secret_ref}")
            cap = effective.requests_per_minute
            # Providers such as Groq meter tokens per model, so token windows are per model.
            token_cap = effective.tokens_per_minute
            token_keys = [f"{key}|model:{model}" for key in rate_keys] if token_cap else []
            entries: list[list[float]] = []
            while True:
                await self.checkpoint(snapshot)
                now = time.monotonic()
                for key in rate_keys:
                    while self._rate[key] and self._rate[key][0] <= now - 60:
                        self._rate[key].popleft()
                for key in token_keys:
                    while self._tokens[key] and self._tokens[key][0][0] <= now - 60:
                        self._tokens[key].popleft()
                if all(len(self._rate[key]) < cap for key in rate_keys) and all(
                    self._fits_token_window(key, tokens, token_cap) for key in token_keys
                ):
                    for key in rate_keys:
                        self._rate[key].append(now)
                    for key in token_keys:
                        entries.append([now, tokens])
                        self._tokens[key].append(entries[-1])
                    break
                await asyncio.sleep(0.05)
            await self.checkpoint(snapshot)
            yield TokenLease(entries)
