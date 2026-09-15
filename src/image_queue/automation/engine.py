"""Sequential fixture-only execution: observe -> intent -> one action -> verify -> persist.

No production adapter exists. Methods are not registered with the desktop bridge.
"""

import asyncio

from image_queue.automation.ledger import AttemptLedger
from image_queue.automation.ports import FixtureAdapter, PageBlocked
from image_queue.automation.preparation import (
    build_inputs,
    choose_row,
    selected_source,
)
from image_queue.automation.steps import FixtureSteps
from image_queue.domain.validation import ContractError, PersistenceFault
from image_queue.workspace.execution import phase
from image_queue.workspace.service import WorkspaceService


class OfflineExecution:
    def __init__(self, service: WorkspaceService, adapter: FixtureAdapter) -> None:
        if adapter.test_only is not True:
            raise ContractError("Live execution is disabled pending reviewed adapter evidence")
        self.service, self.adapter = service, adapter
        self.ledger = AttemptLedger(service)
        self.steps = FixtureSteps(adapter, self.ledger)
        self.running = False
        self.recovery_required = self.ledger.unresolved()

    async def prepare(self, source_id: str) -> str:
        if self.service.busy or self.ledger.unresolved():
            raise ContractError("Another attempt owns the sequential session")
        self.service.busy = True
        try:
            state = self.service.snapshot()
            source = selected_source(state, source_id)
            self._not_saved(source_id, source["sha256"])
            async with asyncio.timeout(10):
                row = await choose_row(
                    self.adapter, state["workspace"], self.ledger.read()["cursor"]
                )
            inputs = build_inputs(source, state["workspace"], row)
            return self.ledger.add(inputs, row[2])
        finally:
            self.service.busy = self.ledger.unresolved()

    async def advance(self, identifier: str) -> None:
        if self.recovery_required:
            raise ContractError("Explicit recovery is required before advancing a restored attempt")
        if self.running:
            raise ContractError("One operation at a time; no concurrent replay")
        self.running = True
        self.service.busy = True
        try:
            async with asyncio.timeout(75):
                await self._advance(identifier)
        except PageBlocked:
            self._blocked(identifier)
            raise
        except PersistenceFault:
            raise  # writer has latched; do not try to overwrite ambiguous disk state
        except (OSError, ContractError, TimeoutError, asyncio.CancelledError):
            self._failed(identifier)
            raise
        finally:
            self.running = False
            self.service.busy = self.ledger.unresolved()

    async def _advance(self, identifier: str) -> None:
        attempt = self.ledger.attempt(identifier)
        status, inputs = phase(attempt), attempt["inputs"]
        if self.ledger.read()["paused"] and status != "submitted":
            return
        actions = {
            "prepared": self.steps.upload,
            "uploaded": self.steps.prompt,
            "ready_to_submit": self.steps.submit,
            "submitted": self.steps.wait,
        }
        action = actions.get(status)
        if action is None:
            raise ContractError("Attempt cannot advance or replay; inspect durable evidence")
        await self.steps.ready(inputs, status == "prepared")
        if not self.ledger.read()["paused"] or status == "submitted":
            await action(inputs)

    def cancel(self, identifier: str) -> None:
        if self.running:
            raise ContractError("Cancel the running task and await it before changing controls")
        status = phase(self.ledger.attempt(identifier))
        next_status = (
            "cancelled" if status in ("prepared", "uploaded", "ready_to_submit") else "needs_review"
        )
        self.ledger.move(identifier, next_status)
        self.service.busy = self.ledger.unresolved()

    def _failed(self, identifier: str) -> None:
        status = phase(self.ledger.attempt(identifier))
        if status in ("prepared", "uploaded", "ready_to_submit"):
            self.ledger.move(identifier, "failed")
        elif status in ("upload_intent", "prompt_intent", "submit_intent", "submitted"):
            self.ledger.move(identifier, "needs_review")

    def _blocked(self, identifier: str) -> None:
        status = phase(self.ledger.attempt(identifier))
        if status in ("prepared", "uploaded", "ready_to_submit"):
            self.ledger.controls(True, self.ledger.read()["stop_after"])
        else:
            self._failed(identifier)

    def recover(self) -> None:
        if self.running:
            raise ContractError("Stop the active operation before recovery")
        self.ledger.recover()
        self.recovery_required = False

    def _not_saved(self, source_id: str, digest: str) -> None:
        for attempt in self.ledger.read()["attempts"].values():
            source = attempt["inputs"]["source"]
            if (
                phase(attempt) == "saved"
                and source["id"] == source_id
                and source["sha256"] == digest
            ):
                raise ContractError("This source fingerprint already has a saved output")
