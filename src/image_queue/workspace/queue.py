"""Selection is editable; scan observations are not undoable completion evidence."""

from copy import deepcopy
from typing import Any

from image_queue.domain.validation import ContractError


def select_sources(
    workspace: dict[str, Any], sources: dict[str, Any], request: dict[str, Any]
) -> dict[str, Any]:
    identifiers, decision = request.get("ids"), request.get("decision")
    if not isinstance(identifiers, list) or not identifiers or len(identifiers) > 2000:
        raise ContractError("Choose 1–2000 source rows")
    if decision not in ("selected", "skipped", "review"):
        raise ContractError("Selection cannot fabricate completion or reset attempts")
    result = deepcopy(workspace)
    for identifier in identifiers:
        source = sources.get(identifier) if isinstance(identifier, str) else None
        if source is None or source["status"] not in ("available", "changed"):
            raise ContractError("Missing/invalid sources cannot be selected; rescan")
        result["selection"][identifier] = {"sha256": source["sha256"], "decision": decision}
    return result


def queue_rows(sources: dict[str, Any], selection: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for key, source in sources.items():
        choice = selection.get(key, {})
        current = choice.get("sha256") == source["sha256"] and bool(source["sha256"])
        decision = choice.get("decision", "review") if current else "review"
        available = source["status"] in ("available", "changed")
        rows.append(
            {
                **deepcopy(source),
                "id": key,
                "decision": decision,
                "selected": available and decision == "selected",
                "needs_review": not current or decision == "review",
            }
        )
    return rows
