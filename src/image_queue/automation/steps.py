"""Fixture action/effect contracts; never selects a production site element."""

import asyncio
import hashlib
from typing import Any

from image_queue.automation.ledger import AttemptLedger
from image_queue.automation.ports import FixtureAdapter, PageBlocked
from image_queue.automation.preparation import source_bytes
from image_queue.automation.visual import find_and_click
from image_queue.domain.settings import HighlightSettings
from image_queue.domain.validation import ContractError


class FixtureSteps:
    def __init__(self, adapter: FixtureAdapter, ledger: AttemptLedger) -> None:
        self.adapter, self.ledger = adapter, ledger

    async def ready(self, inputs: dict[str, Any], empty: bool = False) -> None:
        observed = await self.adapter.observe(inputs["url"])
        baseline = inputs["baseline"]
        if observed.blocker != "none":
            raise PageBlocked("Manual page action required; no blocker interaction performed")
        if (
            observed.url != inputs["url"]
            or observed.target != baseline["target"]
            or observed.context != baseline["context"]
            or (empty and not observed.empty)
        ):
            raise ContractError("Page changed or requires manual action; no side effect authorized")

    async def upload(self, inputs: dict[str, Any]) -> None:
        content = source_bytes(inputs["source"], 64 * 1024 * 1024)
        self.ledger.move(inputs["id"], "upload_intent")
        await self.adapter.upload(content, inputs["source"]["name"])
        token = await self._attachment(inputs)
        self.ledger.move(inputs["id"], "uploaded", {"attachment": token})

    async def _attachment(self, inputs: dict[str, Any]) -> str:
        items = await self.adapter.attachments()
        source = inputs["source"]
        if len(items) != 1 or not items[0].token:
            raise ContractError("A unique verified attachment is required")
        if items[0].sha256 != source["sha256"] or items[0].name != source["name"]:
            raise ContractError("Attachment does not match the immutable source")
        tokens = [
            event["evidence"]["attachment"]
            for event in self.ledger.attempt(inputs["id"])["events"]
            if event["phase"] == "uploaded"
        ]
        if tokens and items[0].token != tokens[-1]:
            raise ContractError("Attachment identity changed")
        return items[0].token

    async def prompt(self, inputs: dict[str, Any]) -> None:
        await self._attachment(inputs)
        if self.ledger.read()["paused"]:
            return
        self.ledger.move(inputs["id"], "prompt_intent")
        await self.adapter.fill_prompt(inputs["text"])
        if await self.adapter.read_prompt() != inputs["text"]:
            raise ContractError("Prompt readback differs from exact immutable text")
        self.ledger.move(
            inputs["id"],
            "ready_to_submit",
            {"prompt_sha256": hashlib.sha256(inputs["text"].encode()).hexdigest()},
        )

    async def submit(self, inputs: dict[str, Any]) -> None:
        await self._attachment(inputs)
        if await self.adapter.read_prompt() != inputs["text"]:
            raise ContractError("Prompt changed before submission")
        await self.ready(inputs)
        if self.ledger.read()["paused"]:
            return
        self.ledger.move(inputs["id"], "submit_intent")
        await find_and_click(
            self.adapter.evaluate,
            self.adapter.submit_selector,
            HighlightSettings(**inputs["highlight"]),
        )
        message = await self.adapter.marked_message(inputs["text"])
        if not message or message in inputs["baseline"]["messages"]:
            raise ContractError("Submission not confirmed; never retry Send automatically")
        self.ledger.move(inputs["id"], "submitted", {"message_id": message})

    async def wait(self, inputs: dict[str, Any]) -> None:
        confirmed = self.ledger.attempt(inputs["id"])["events"][-1]["evidence"]["message_id"]
        while True:
            await self.ready(inputs)
            message = await self.adapter.marked_message(inputs["text"])
            if not message or message in inputs["baseline"]["messages"]:
                raise ContractError("Lost marked-message correlation")
            if message != confirmed:
                raise ContractError("Marked message identity changed")
            response = await self.adapter.response_after(message)
            if response is None:
                await asyncio.sleep(0.05)
                continue
            if not response or response in inputs["baseline"]["responses"]:
                raise ContractError("New owned response not proven; review, never resubmit")
            self.ledger.move(inputs["id"], "output_observed", {"response_id": response})
            return
