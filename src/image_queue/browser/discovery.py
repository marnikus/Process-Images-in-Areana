"""Retained aiohttp /json/list discovery, hardened: bounded, loopback, no redirect/proxy."""

import json
from typing import Any
from urllib.parse import urlsplit

import aiohttp

from image_queue.domain.settings import ChromeEndpoint
from image_queue.domain.validation import ContractError


async def fetch_tabs(endpoint: ChromeEndpoint) -> list[dict[str, Any]]:
    try:
        async with aiohttp.ClientSession(trust_env=False) as session:
            async with session.get(
                endpoint.discovery_origin + "/json/list",
                allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=4),
            ) as response:
                if response.status != 200:
                    raise ContractError("Chrome discovery failed; no redirects are followed")
                return validate_tabs(await _payload(response), endpoint)
    except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
        raise ContractError(
            "Chrome discovery unavailable or invalid; check local debug Chrome"
        ) from exc


def socket_url(value: Any, endpoint: ChromeEndpoint) -> str:
    if not isinstance(value, str):
        raise ContractError("Missing debugger socket")
    try:
        url = urlsplit(value)
        valid = (
            url.scheme == "ws"
            and url.hostname == endpoint.host
            and url.port == endpoint.port
            and not any((url.username, url.password, url.query, url.fragment))
            and url.path.startswith("/devtools/page/")
        )
    except ValueError as exc:
        raise ContractError("Invalid debugger socket") from exc
    if not valid:
        raise ContractError("Debugger socket must use the configured loopback endpoint")
    return value


def validate_tabs(data: Any, endpoint: ChromeEndpoint) -> list[dict[str, Any]]:
    if not isinstance(data, list) or len(data) > 500:
        raise ContractError("Invalid Chrome discovery list")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in data:
        if not isinstance(item, dict):
            raise ContractError("Invalid Chrome target metadata")
        if item.get("type") != "page":
            continue
        _validate_target(item, seen)
        item = {key: item.get(key, "") for key in ("id", "url", "title", "webSocketDebuggerUrl")}
        item["webSocketDebuggerUrl"] = socket_url(item["webSocketDebuggerUrl"], endpoint)
        result.append(item)
    return result


def _validate_target(item: dict[str, Any], seen: set[str]) -> None:
    if any(not isinstance(item.get(key, ""), str) for key in ("id", "url", "title")):
        raise ContractError("Invalid target text")
    identifier = item.get("id")
    if not identifier or identifier in seen:
        raise ContractError("Missing or duplicate target ID")
    seen.add(identifier)


async def _payload(response: aiohttp.ClientResponse) -> Any:
    raw = bytearray()
    async for chunk in response.content.iter_chunked(65536):
        raw.extend(chunk)
        if len(raw) > 1_000_000:
            raise ContractError("Chrome discovery response is too large")
    return json.loads(raw)
