"""Fixture-only correlated save and explicit local recovery. No remote downloads."""

from dataclasses import dataclass
from pathlib import Path

from image_queue.automation.ledger import AttemptLedger
from image_queue.automation.output_files import destination, inspect_output, publish, verify_file
from image_queue.domain.validation import ContractError, PersistenceFault
from image_queue.persistence.atomic import sync_directory
from image_queue.workspace.execution import phase


@dataclass(frozen=True)
class FixtureOutput:
    message_id: str
    response_id: str
    content: bytes
    permitted_original: bool = False
    test_only: bool = True


class OutputSaver:
    def __init__(self, ledger: AttemptLedger) -> None:
        self.ledger = ledger

    def save(self, identifier: str, output: FixtureOutput, folder: Path) -> Path:
        attempt = self.ledger.attempt(identifier)
        if phase(attempt) != "output_observed":
            raise ContractError("Only a newly correlated response can be saved")
        if output.test_only is not True or output.permitted_original is not True:
            raise ContractError("Only explicitly permitted fixture original bytes are supported")
        events = {event["phase"]: event["evidence"] for event in attempt["events"]}
        if (
            output.message_id != events["submitted"]["message_id"]
            or output.response_id != events["output_observed"]["response_id"]
        ):
            raise ContractError("Output ownership differs from confirmed message/response")
        extension, digest = inspect_output(output.content)
        path = destination(folder, Path(attempt["inputs"]["source"]["path"]), extension)
        evidence = {"path": str(path), "sha256": digest, "response_id": output.response_id}
        self.ledger.move(identifier, "save_intent", evidence)
        try:
            publish(path, output.content, digest)
            self.ledger.move(identifier, "saved", evidence)
        except PersistenceFault:
            raise
        except (OSError, ContractError):
            self.ledger.move(identifier, "needs_review")
            raise
        self.ledger.service.busy = self.ledger.unresolved()
        return path

    def verify_saved(self, identifier: str) -> Path:
        attempt = self.ledger.attempt(identifier)
        intents = [e["evidence"] for e in attempt["events"] if e["phase"] == "save_intent"]
        if phase(attempt) not in ("save_intent", "needs_review") or len(intents) != 1:
            raise ContractError("No ambiguous local publication to verify")
        evidence = intents[0]
        path = Path(evidence["path"])
        verify_file(path, evidence["sha256"])
        sync_directory(path.parent)
        self.ledger.move(identifier, "saved", evidence)
        self.ledger.service.busy = self.ledger.unresolved()
        return path
