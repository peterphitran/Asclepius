from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from contextlib import AsyncExitStack, asynccontextmanager
from typing import TYPE_CHECKING, Literal

import httpx

from asclepius.domain import AppError, BudgetReservation, Limits, RunSnapshot

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


class BudgetManager:
    def __init__(self, repo: Repository, instance_id: str, *, limits: Limits | None = None) -> None:
        self.repo = repo
        self.instance_id = instance_id
        self.limits = limits or Limits()
        self._leases: dict[str, list[int]] = defaultdict(list)
        self._rate: dict[str, deque[float]] = defaultdict(deque)

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

    @asynccontextmanager
    async def run_slot(self, snapshot: RunSnapshot):
        async with self._gate(
            "active-runs",
            min(self.limits.active_runs, snapshot.profile.limits.active_runs),
            snapshot,
        ):
            yield

    @asynccontextmanager
    async def slot(self, snapshot: RunSnapshot, kind: Kind, *, role: str | None = None):
        if kind not in {"target", "evaluator"}:
            raise AppError(
                "unsupported_operation", "Cleanup requires a separate budget contract.", 2
            )
        target = snapshot.profile.target
        if kind == "target":
            endpoint, secret_ref, grouping = target.base_url, target.secret_ref, target.resource_key
        else:
            if role not in {"selector", "generator", "judge", "reporter"}:
                raise AppError("arguments", "Evaluator requests require a named role.", 2)
            config = getattr(snapshot.evaluator.roles, role)
            endpoint, secret_ref, grouping = config.base_url, config.secret_ref, None
        origin, destination = resource_identity(endpoint)
        pinned = snapshot.profile.limits
        global_cap = min(self.limits.outbound_concurrency, pinned.outbound_concurrency)
        destination_cap = min(
            getattr(self.limits, f"{kind}_concurrency"), getattr(pinned, f"{kind}_concurrency")
        )
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
            cap = min(self.limits.requests_per_minute, pinned.requests_per_minute)
            while True:
                await self.checkpoint(snapshot)
                now = time.monotonic()
                for key in rate_keys:
                    while self._rate[key] and self._rate[key][0] <= now - 60:
                        self._rate[key].popleft()
                if all(len(self._rate[key]) < cap for key in rate_keys):
                    for key in rate_keys:
                        self._rate[key].append(now)
                    break
                await asyncio.sleep(0.05)
            await self.checkpoint(snapshot)
            yield
