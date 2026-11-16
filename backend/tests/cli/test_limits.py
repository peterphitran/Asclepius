import asyncio
import json
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from asclepius.domain import AppError, Limits, RunState
from asclepius.limits import BudgetManager, resource_identity
from tests.cli.storage_fixtures import OWNER, REPLACEMENT, prepare, ready, run


def test_durable_reservations_do_not_refund_dispatched_or_settled_calls(tmp_path):
    async def scenario():
        repo, snapshot, _ = await prepare(tmp_path)
        with sqlite3.connect(repo.database_path) as connection:
            content = snapshot.model_dump(mode="json")
            content["profile"]["limits"]["target_calls"] = 1
            connection.execute(
                "UPDATE runs SET snapshot_json=? WHERE id=?",
                (json.dumps(content), str(snapshot.id)),
            )
        manager = BudgetManager(repo, OWNER)
        first = await manager.reserve(str(snapshot.id), "target", 4)
        await manager.release(first)
        second = await manager.reserve(str(snapshot.id), "target", 4)
        await manager.dispatch(second)
        await manager.settle(second)
        with pytest.raises(AppError):
            await manager.release(second)
        with pytest.raises(AppError) as error:
            await manager.reserve(str(snapshot.id), "target", 4)
        assert error.value.code == "budget_exhausted"
        assert (await repo.read_run(str(snapshot.id))).reason == "budget_exhausted"
        assert (await repo.events(str(snapshot.id)))[-1]["kind"] == "run.budget_exhausted"
        with pytest.raises(AppError) as error:
            await repo.finalize(str(snapshot.id), RunState.COMPLETED, None, instance_id=OWNER)
        assert error.value.code == "budget_exhausted"

    run(scenario())


def test_cancellation_rejects_dispatch_but_still_allows_release(tmp_path):
    async def scenario():
        repo, snapshot, _ = await prepare(tmp_path)
        manager = BudgetManager(repo, OWNER)
        reservation = await manager.reserve(str(snapshot.id), "target", 4)
        await repo.request_cancel(str(snapshot.id))
        with pytest.raises(AppError) as error:
            await manager.dispatch(reservation)
        assert error.value.code == "run_cancelled"
        await manager.release(reservation)
        with sqlite3.connect(repo.database_path) as connection:
            assert (
                connection.execute("SELECT state FROM budget_reservations").fetchone()[0]
                == "released"
            )

    run(scenario())


@pytest.fixture
def http_probe():
    state = {"active": 0, "peak": 0, "calls": 0}
    lock = threading.Lock()
    overlapping_request = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            with lock:
                state["active"] += 1
                state["peak"] = max(state["peak"], state["active"])
                state["calls"] += 1
                if state["calls"] >= 2:
                    overlapping_request.set()
            try:
                overlapping_request.wait(0.5)
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"ok")
            finally:
                with lock:
                    state["active"] -= 1

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


@pytest.mark.parametrize(
    "paths,expected_peak",
    [(("/same", "/same"), 1), (("/target-0", "/target-1"), 2), (("/same", "/x/../same"), 1)],
)
def test_slot_aliases_share_destination_but_distinct_targets_can_overlap(
    tmp_path, http_probe, paths, expected_peak
):
    endpoint, state = http_probe

    async def scenario():
        repo, snapshot, _ = await prepare(tmp_path)
        manager = BudgetManager(
            repo, OWNER, limits=Limits(target_concurrency=4, requests_per_minute=1000)
        )
        aliases = [
            snapshot.model_copy(
                update={
                    "profile": snapshot.profile.model_copy(
                        update={
                            "target": snapshot.profile.target.model_copy(
                                update={
                                    "resource_key": f"alias-{index}",
                                    "adapter": "ollama-chat",
                                    "base_url": endpoint + path,
                                }
                            ),
                            "limits": snapshot.profile.limits.model_copy(
                                update={"target_concurrency": 1, "requests_per_minute": 1000}
                            ),
                        }
                    )
                }
            )
            for index, path in enumerate(paths)
        ]

        async with httpx.AsyncClient(trust_env=False) as client:

            async def request(alias):
                async with manager.slot(alias, "target"):
                    response = await client.get(alias.profile.target.base_url)
                    assert response.text == "ok"

            await asyncio.gather(*(request(alias) for alias in aliases))
        assert state["calls"] == 2
        assert state["peak"] == expected_peak
        assert state["active"] == 0

    run(scenario())


def test_rate_wait_stops_promptly_on_run_cancellation(tmp_path):
    async def scenario():
        repo, snapshot, _ = await prepare(tmp_path)
        manager = BudgetManager(repo, OWNER, limits=Limits(requests_per_minute=1))
        async with manager.slot(snapshot, "target"):
            pass

        async def waiting():
            async with manager.slot(snapshot, "target"):
                raise AssertionError("Cancelled rate waiter dispatched")

        waiter = asyncio.create_task(waiting())
        await asyncio.sleep(0.1)
        await repo.request_cancel(str(snapshot.id))
        with pytest.raises(AppError) as error:
            await asyncio.wait_for(waiter, 2)
        assert error.value.code == "run_cancelled"

    run(scenario())


def test_provider_origin_rate_limit_cannot_be_split_by_credential_aliases(tmp_path):
    async def scenario():
        repo, snapshot, _ = await prepare(tmp_path)
        manager = BudgetManager(repo, OWNER, limits=Limits(requests_per_minute=1))
        async with manager.slot(snapshot, "target"):
            pass
        aliased = snapshot.model_copy(
            update={
                "profile": snapshot.profile.model_copy(
                    update={
                        "target": snapshot.profile.target.model_copy(
                            update={
                                "secret_ref": "env:OTHER_KEY",
                                "base_url": "https://api.groq.com:443/another-endpoint",
                            }
                        )
                    }
                )
            }
        )
        entered = asyncio.Event()

        async def waiting():
            async with manager.slot(aliased, "target"):
                entered.set()

        waiter = asyncio.create_task(waiting())
        try:
            await asyncio.sleep(0.1)
            assert not entered.is_set()
            await repo.request_cancel(str(snapshot.id))
            with pytest.raises(AppError) as error:
                await asyncio.wait_for(waiter, 2)
            assert error.value.code == "run_cancelled"
        finally:
            waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)

    run(scenario())


def test_one_credential_reference_shares_rate_limit_across_origins(tmp_path):
    async def scenario():
        repo, snapshot, _ = await prepare(tmp_path)
        manager = BudgetManager(repo, OWNER, limits=Limits(requests_per_minute=1))
        async with manager.slot(snapshot, "target"):
            pass
        different_origin = snapshot.model_copy(
            update={
                "profile": snapshot.profile.model_copy(
                    update={
                        "target": snapshot.profile.target.model_copy(
                            update={"base_url": "https://other.example/openai/v1"}
                        )
                    }
                )
            }
        )
        entered = asyncio.Event()

        async def waiting():
            async with manager.slot(different_origin, "target"):
                entered.set()

        waiter = asyncio.create_task(waiting())
        try:
            await asyncio.sleep(0.1)
            assert not entered.is_set()
            await repo.request_cancel(str(snapshot.id))
            with pytest.raises(AppError) as error:
                await asyncio.wait_for(waiter, 2)
            assert error.value.code == "run_cancelled"
        finally:
            waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)

    run(scenario())


def test_destination_identity_normalizes_dns_trailing_dot_default_port_and_wire_path():
    assert resource_identity("https://API.GROQ.COM.:443/x/../openai/v1/") == (
        "https://api.groq.com:443",
        "https://api.groq.com:443/openai/v1",
    )


def test_run_deadline_and_stale_owner_reject_dispatch_not_settlement(tmp_path, monkeypatch):
    async def scenario():
        repo, snapshot, _ = await prepare(tmp_path)
        manager = BudgetManager(repo, OWNER)
        reservation = await manager.reserve(str(snapshot.id), "target", 4)
        await manager.dispatch(reservation)
        pending = await manager.reserve(str(snapshot.id), "target", 4)
        from asclepius.elapsed_clock import Tick, elapsed_clock

        current = elapsed_clock.sample()

        with sqlite3.connect(repo.database_path) as connection:
            connection.execute(
                "UPDATE runs SET started_tick_ns=?",
                (current.ns,),
            )
        monkeypatch.setattr(
            elapsed_clock,
            "sample",
            lambda: Tick(current.source, current.ns + 2_700_000_000_000),
        )
        with pytest.raises(AppError) as error:
            await manager.dispatch(pending)
        assert error.value.code == "run_timeout"
        monkeypatch.setattr(elapsed_clock, "sample", lambda: current)
        await manager.settle(reservation)
        await manager.release(pending)
        await ready(repo, REPLACEMENT)
        with pytest.raises(AppError) as error:
            await manager.reserve(str(snapshot.id), "target", 4)
        assert error.value.code == "ownership"

    run(scenario())


def test_cleanup_reservations_are_explicitly_unsupported_not_charged_to_evaluation(tmp_path):
    async def scenario():
        repo, snapshot, _ = await prepare(tmp_path)
        with pytest.raises(AppError) as error:
            await BudgetManager(repo, OWNER).reserve(str(snapshot.id), "cleanup", 4)
        assert error.value.code == "unsupported_operation"
        reservation = await BudgetManager(repo, OWNER).reserve(str(snapshot.id), "target", 4)
        assert reservation.kind == "target"

    run(scenario())


@pytest.mark.parametrize(
    "runtime", [{"total_calls": 1}, {"target_calls": 1}, {"completion_tokens": 20}]
)
def test_runtime_policy_caps_each_run_allowance_in_storage(tmp_path, runtime):
    async def scenario():
        repo, snapshot, _ = await prepare(tmp_path)
        manager = BudgetManager(repo, OWNER, limits=Limits(**runtime))
        reservation = await manager.reserve(str(snapshot.id), "target", 20)
        await manager.dispatch(reservation)
        await manager.settle(reservation)
        with pytest.raises(AppError) as error:
            await manager.reserve(str(snapshot.id), "target", 20)
        assert error.value.code == "budget_exhausted"

    asyncio.run(scenario())


def test_runtime_deadline_is_checked_before_dispatch_authorization(tmp_path):
    from asclepius.elapsed_clock import elapsed_clock

    async def scenario():
        repo, snapshot, _ = await prepare(tmp_path)
        manager = BudgetManager(repo, OWNER, limits=Limits(run_timeout_seconds=1))
        reservation = await manager.reserve(str(snapshot.id), "target", 20)
        with sqlite3.connect(repo.database_path) as connection:
            connection.execute(
                "UPDATE runs SET started_tick_ns=?",
                (elapsed_clock.sample().ns - 2_000_000_000,),
            )
        with pytest.raises(AppError) as error:
            await manager.dispatch(reservation)
        assert error.value.code == "run_timeout"
        await manager.release(reservation)

    asyncio.run(scenario())


async def _blocked(manager, snapshot, kind="target", **kwargs):
    entered = asyncio.Event()

    async def waiting():
        async with manager.slot(snapshot, kind, **kwargs):
            entered.set()

    waiter = asyncio.create_task(waiting())
    try:
        await asyncio.sleep(0.2)
        return not entered.is_set()
    finally:
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)


def test_token_budget_holds_requests_that_would_exceed_tokens_per_minute(tmp_path):
    async def scenario():
        repo, snapshot, _ = await prepare(tmp_path)
        manager = BudgetManager(repo, OWNER, limits=Limits(tokens_per_minute=1000))
        async with manager.slot(snapshot, "target", tokens=600):
            pass
        assert await _blocked(manager, snapshot, tokens=500)
        async with asyncio.timeout(1):
            async with manager.slot(snapshot, "target", tokens=400):
                pass

    run(scenario())


def test_measured_usage_replaces_the_token_estimate(tmp_path):
    async def scenario():
        repo, snapshot, _ = await prepare(tmp_path)
        manager = BudgetManager(repo, OWNER, limits=Limits(tokens_per_minute=1000))
        async with manager.slot(snapshot, "target", tokens=900) as lease:
            lease.record(100)
        async with asyncio.timeout(1):
            async with manager.slot(snapshot, "target", tokens=800):
                pass
        assert await _blocked(manager, snapshot, tokens=200)

    run(scenario())


def test_unmeasured_usage_keeps_the_token_estimate(tmp_path):
    async def scenario():
        repo, snapshot, _ = await prepare(tmp_path)
        manager = BudgetManager(repo, OWNER, limits=Limits(tokens_per_minute=1000))
        async with manager.slot(snapshot, "target", tokens=900) as lease:
            lease.record(None)
        assert await _blocked(manager, snapshot, tokens=200)

    run(scenario())


def test_oversized_request_runs_alone_instead_of_waiting_forever(tmp_path):
    async def scenario():
        repo, snapshot, _ = await prepare(tmp_path)
        manager = BudgetManager(repo, OWNER, limits=Limits(tokens_per_minute=1000))
        async with asyncio.timeout(1):
            async with manager.slot(snapshot, "target", tokens=5000):
                pass
        assert await _blocked(manager, snapshot, tokens=1)

    run(scenario())


def test_token_budget_is_kept_per_model(tmp_path):
    async def scenario():
        repo, snapshot, _ = await prepare(tmp_path)
        manager = BudgetManager(repo, OWNER, limits=Limits(tokens_per_minute=1000))
        async with manager.slot(snapshot, "target", tokens=1000):
            pass
        other_model = snapshot.model_copy(
            update={
                "profile": snapshot.profile.model_copy(
                    update={"target": snapshot.profile.target.model_copy(update={"model": "other"})}
                )
            }
        )
        async with asyncio.timeout(1):
            async with manager.slot(other_model, "target", tokens=1000):
                pass
        assert await _blocked(manager, snapshot, tokens=1)

    run(scenario())


def test_pinned_profile_token_budget_applies_when_runtime_has_none(tmp_path):
    async def scenario():
        repo, snapshot, _ = await prepare(tmp_path)
        pinned = snapshot.model_copy(
            update={
                "profile": snapshot.profile.model_copy(
                    update={
                        "limits": snapshot.profile.limits.model_copy(
                            update={"tokens_per_minute": 1000}
                        )
                    }
                )
            }
        )
        manager = BudgetManager(repo, OWNER)
        async with manager.slot(pinned, "target", tokens=1000):
            pass
        assert await _blocked(manager, pinned, tokens=1)

    run(scenario())


def test_without_token_budget_token_estimates_never_block(tmp_path):
    async def scenario():
        repo, snapshot, _ = await prepare(tmp_path)
        manager = BudgetManager(repo, OWNER)
        async with asyncio.timeout(1):
            for _ in range(3):
                async with manager.slot(snapshot, "target", tokens=10**9):
                    pass

    run(scenario())


def test_token_wait_stops_promptly_on_run_cancellation(tmp_path):
    async def scenario():
        repo, snapshot, _ = await prepare(tmp_path)
        manager = BudgetManager(repo, OWNER, limits=Limits(tokens_per_minute=10))
        async with manager.slot(snapshot, "target", tokens=10):
            pass

        async def waiting():
            async with manager.slot(snapshot, "target", tokens=1):
                raise AssertionError("Cancelled token waiter dispatched")

        waiter = asyncio.create_task(waiting())
        await asyncio.sleep(0.1)
        await repo.request_cancel(str(snapshot.id))
        with pytest.raises(AppError) as error:
            await asyncio.wait_for(waiter, 2)
        assert error.value.code == "run_cancelled"

    run(scenario())


def test_runtime_token_budget_merges_with_unset_pinned_value_in_storage(tmp_path):
    async def scenario():
        repo, snapshot, _ = await prepare(tmp_path)
        manager = BudgetManager(repo, OWNER, limits=Limits(tokens_per_minute=1000))
        reservation = await manager.reserve(str(snapshot.id), "target", 20)
        await manager.dispatch(reservation)
        await manager.settle(reservation)

    run(scenario())
