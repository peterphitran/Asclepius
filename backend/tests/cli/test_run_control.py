from pathlib import Path

import pytest

from scripts.recovery_fixture import (
    cancel_scenario,
    drain_scenario,
    queued_cancel_scenario,
    rate_cancel_scenario,
    watch_scenario,
)

CERTIFICATES = Path(__file__).parent / "fixtures"


def test_watch_os_interrupt_does_not_cancel_run(tmp_path):
    result = watch_scenario(tmp_path, CERTIFICATES)
    assert result["exit_code"] == 130


@pytest.mark.parametrize("actor", ["selector", "target"])
def test_cancel_issued_reply_retains_evidence_and_stops_dispatch(tmp_path, actor):
    cancel_scenario(tmp_path, CERTIFICATES, actor)


def test_queued_cancel_has_no_operations_or_receipts(tmp_path):
    queued_cancel_scenario(tmp_path, CERTIFICATES)


def test_rate_wait_cancel_releases_unused_allowance(tmp_path):
    rate_cancel_scenario(tmp_path, CERTIFICATES)


def test_stop_drains_active_preserves_queue_and_submission_race(tmp_path):
    drain_scenario(tmp_path, CERTIFICATES)


def test_drain_committed_between_ready_read_and_claim_exits_cleanly(tmp_path, monkeypatch):
    import asyncio

    from asclepius import daemon
    from asclepius.storage import Repository

    class DrainBeforeClaim(Repository):
        async def claim_next(self, instance_id, **kwargs):
            await self.request_stop(instance_id)
            return await super().claim_next(instance_id, **kwargs)

    async def scenario():
        repo = DrainBeforeClaim(tmp_path)
        await repo.initialize()
        monkeypatch.setattr(daemon, "Repository", lambda _: repo)
        await daemon.serve(tmp_path, instance_id="747ccfe6-a4a9-4536-a4ed-c8befd037e14")
        assert (await repo.control()).state == "stopped"

    asyncio.run(scenario())


@pytest.mark.parametrize("code", ["storage_error", "daemon_unavailable"])
def test_claim_failure_without_same_generation_drain_propagates(tmp_path, monkeypatch, code):
    import asyncio

    from asclepius import daemon
    from asclepius.domain import AppError
    from asclepius.storage import Repository

    class FailingClaim(Repository):
        async def claim_next(self, instance_id, **kwargs):
            raise AppError(code, "Claim failed")

    async def scenario():
        repo = FailingClaim(tmp_path)
        await repo.initialize()
        monkeypatch.setattr(daemon, "Repository", lambda _: repo)
        with pytest.raises(AppError) as caught:
            await daemon.serve(tmp_path, instance_id="747ccfe6-a4a9-4536-a4ed-c8befd037e14")
        assert caught.value.code == code

    asyncio.run(scenario())
