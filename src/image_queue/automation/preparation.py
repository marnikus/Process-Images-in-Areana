"""Fresh byte/selection checks and immutable prompt construction for offline attempts."""

from dataclasses import asdict
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from image_queue.automation.ports import FixtureAdapter, Observation
from image_queue.domain.presets import loads_preset
from image_queue.domain.validation import ContractError
from image_queue.scanning.images import image_metadata, read_source
from image_queue.workspace.variables import render_prompt


def source_bytes(source: dict[str, Any], limit: int) -> bytes:
    raw, _ = read_source(Path(source["path"]), limit)
    if image_metadata(raw)["sha256"] != source["sha256"]:
        raise ContractError("Selected source bytes changed; rescan and review")
    return raw


def selected_source(state: dict[str, Any], identifier: str) -> dict[str, Any]:
    source = state["jobs"].get("sources", {}).get(identifier)
    choice = state["workspace"]["selection"].get(identifier, {})
    if source is None or source["status"] not in ("available", "changed"):
        raise ContractError("Source unavailable; rescan")
    if choice.get("decision") != "selected" or choice.get("sha256") != source["sha256"]:
        raise ContractError("Source is not explicitly selected at its current fingerprint")
    source_bytes(source, state["workspace"]["scan_options"]["max_bytes"])
    return {
        "id": identifier,
        "path": source["path"],
        "sha256": source["sha256"],
        "name": Path(source["path"]).name,
    }


async def choose_row(
    adapter: FixtureAdapter, workspace: dict[str, Any], cursor: int
) -> tuple[str, Observation, int]:
    rows = loads_preset(workspace["connection"]).urls
    for offset in range(len(rows)):
        index = (cursor + offset) % len(rows)
        row = rows[index]
        if not row.enabled:
            continue
        if not (urlsplit(row.exact_url).hostname or "").endswith(".invalid"):
            raise ContractError("Offline execution permits reserved .invalid fixture URLs only")
        observed = await adapter.observe(row.exact_url)
        if observed.url == row.exact_url and observed.blocker == "none" and observed.empty:
            return row.row_id, observed, (index + 1) % len(rows)
    raise ContractError("No freshly ready, empty fixture row; nothing uploaded")


def build_inputs(
    source: dict[str, Any], workspace: dict[str, Any], row: tuple[str, Observation, int]
) -> dict[str, Any]:
    rendered = render_prompt(workspace["prompt"], workspace["variables"], workspace["prompt_mode"])
    if not rendered["ok"]:
        raise ContractError("Resolve all template warnings before preparation")
    identifier = uuid4().hex
    row_id, observed, _ = row
    return {
        "id": identifier,
        "source": source,
        "row_id": row_id,
        "url": observed.url,
        "raw_prompt": workspace["prompt"],
        "variables": workspace["variables"],
        "mode": workspace["prompt_mode"],
        "highlight": asdict(loads_preset(workspace["connection"]).highlight),
        "text": f"[JOB-ID:{identifier}]\n" + rendered["text"],
        "baseline": {
            "target": observed.target,
            "context": observed.context,
            "messages": list(observed.messages),
            "responses": list(observed.responses),
        },
    }
