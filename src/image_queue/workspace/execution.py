"""Append-only attempt evidence; never part of editable undo or browser authorization."""

import re
from copy import deepcopy
from typing import Any

from image_queue.domain.validation import ContractError, require_fields, require_integer, same_json
from image_queue.workspace.attempt_inputs import validate_inputs
from image_queue.workspace.libraries import bounded_json

TRANSITIONS = {
    "prepared": {"upload_intent", "cancelled", "failed", "interrupted"},
    "upload_intent": {"uploaded", "needs_review", "interrupted"},
    "uploaded": {"prompt_intent", "cancelled", "failed", "interrupted"},
    "prompt_intent": {"ready_to_submit", "needs_review", "interrupted"},
    "ready_to_submit": {"submit_intent", "cancelled", "failed", "interrupted"},
    "submit_intent": {"submitted", "needs_review"},
    "submitted": {"output_observed", "needs_review"},
    "cancelled": set(),
    "failed": set(),
    "interrupted": set(),
    "needs_review": {"saved"},
    "output_observed": {"save_intent"},
    "save_intent": {"saved", "needs_review"},
    "saved": set(),
}
RELEASED = {"cancelled", "failed", "interrupted", "saved"}


def empty_execution() -> dict[str, Any]:
    return {"version": 1, "attempts": {}, "cursor": 0, "paused": False, "stop_after": False}


def phase(attempt: dict[str, Any]) -> str:
    return str(attempt["events"][-1]["phase"])


def validate_execution(value: Any) -> None:
    data = require_fields(value, set(empty_execution()), "execution ledger")
    require_integer(data["version"], (1, 1), "execution version")
    require_integer(data["cursor"], (0, 10000), "scheduler cursor")
    if type(data["paused"]) is not bool or type(data["stop_after"]) is not bool:
        raise ContractError("Invalid run control flags")
    attempts = data["attempts"]
    if not isinstance(attempts, dict) or len(attempts) > 100:
        raise ContractError("Attempt ledger limit reached")
    for identifier, attempt in attempts.items():
        _validate_attempt(identifier, attempt)
    if sum(phase(item) not in RELEASED for item in attempts.values()) > 1:
        raise ContractError("Only one unresolved attempt may own the session")
    bounded_json(value)


def _validate_attempt(identifier: Any, attempt: Any) -> None:
    require_fields(attempt, {"inputs", "events"}, "attempt")
    inputs = require_fields(
        attempt["inputs"],
        {
            "id",
            "source",
            "row_id",
            "url",
            "raw_prompt",
            "variables",
            "mode",
            "text",
            "baseline",
            "highlight",
        },
        "attempt inputs",
    )
    if not isinstance(identifier, str) or inputs["id"] != identifier:
        raise ContractError("Attempt identity mismatch")
    validate_inputs(dict(inputs))
    events = attempt["events"]
    if not isinstance(events, list) or not 1 <= len(events) <= 20:
        raise ContractError("Invalid attempt event count")
    _events(events)


def _events(events: list[dict[str, Any]]) -> None:
    previous = None
    evidence_by_phase: dict[str, Any] = {}
    for event in events:
        require_fields(event, {"phase", "code", "evidence"}, "attempt event")
        _evidence(event)
        current = event["phase"]
        allowed = {"prepared"} if previous is None else TRANSITIONS[previous]
        if not isinstance(current, str) or current not in allowed or event["code"] != current:
            raise ContractError("Invalid attempt transition; completion cannot be fabricated")
        _save_evidence(event, evidence_by_phase)
        evidence_by_phase[current] = event["evidence"]
        previous = current


def preserve_evidence(previous: dict[str, Any], current: dict[str, Any]) -> None:
    validate_execution(current)
    for identifier, old in previous["attempts"].items():
        new = current["attempts"].get(identifier)
        if new is None or not same_json(old["inputs"], new["inputs"]):
            raise ContractError("Attempt inputs cannot be removed or rewritten")
        if not same_json(old["events"], new["events"][: len(old["events"])]):
            raise ContractError("Attempt evidence cannot be removed or rewritten")


def append_phase(
    execution: dict[str, Any], identifier: str, status: str, evidence: dict[str, str] | None = None
) -> dict[str, Any]:
    result = deepcopy(execution)
    result["attempts"][identifier]["events"].append(
        {"phase": status, "code": status, "evidence": evidence or {}}
    )
    preserve_evidence(execution, result)
    return result


def _evidence(event: dict[str, Any]) -> None:
    names = {
        "uploaded": {"attachment"},
        "ready_to_submit": {"prompt_sha256"},
        "submitted": {"message_id"},
        "output_observed": {"response_id"},
        "save_intent": {"path", "sha256", "response_id"},
        "saved": {"path", "sha256", "response_id"},
    }
    if not isinstance(event["phase"], str):
        raise ContractError("Invalid evidence phase")
    evidence = require_fields(event["evidence"], names.get(event["phase"], set()), "phase evidence")
    if any(
        not isinstance(value, str) or not value or len(value) > (4096 if key == "path" else 160)
        for key, value in evidence.items()
    ):
        raise ContractError("Invalid phase evidence identifier")


def has_unresolved(execution: dict[str, Any]) -> bool:
    return any(phase(attempt) not in RELEASED for attempt in execution["attempts"].values())


def _save_evidence(event: dict[str, Any], previous: dict[str, Any]) -> None:
    status, evidence = event["phase"], event["evidence"]
    if status == "save_intent":
        if evidence["response_id"] != previous["output_observed"]["response_id"]:
            raise ContractError("Save response ownership changed")
        if not re.fullmatch(r"[0-9a-f]{64}", evidence["sha256"]) or "\x00" in evidence["path"]:
            raise ContractError("Invalid output digest or path")
    if status == "saved" and evidence != previous.get("save_intent"):
        raise ContractError("Saved evidence requires the identical durable save intent")
