"""Exact destination policy, replacing permissive chat matching; pure logic only."""

import re
from dataclasses import dataclass
from ipaddress import IPv6Address
from urllib.parse import SplitResult, urlsplit

from image_queue.domain.validation import ContractError, require_boolean, require_text

_BAD_ESCAPE = re.compile(r"%(?![0-9a-fA-F]{2})")


def validate_url(value: object) -> str:
    """Validate without normalizing; literal spelling remains the authorization boundary."""
    raw = require_text(value, "URL")
    _validate_characters(raw)
    parsed = _parse_address(raw)
    _validate_hostname(parsed.hostname or "")
    return raw


def _validate_characters(raw: str) -> None:
    try:
        raw.encode("utf-8")
    except UnicodeError as exc:
        raise ContractError("URL: invalid Unicode text") from exc
    if not raw or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in raw):
        raise ContractError("URL: empty text, whitespace or control characters are not allowed")
    if any(char in raw for char in '\\<>"{}|^`') or _BAD_ESCAPE.search(raw):
        raise ContractError("URL: forbidden characters or malformed percent escapes")


def _parse_address(raw: str) -> SplitResult:
    try:
        parsed = urlsplit(raw)
        port = parsed.port
        hostname = parsed.hostname
    except ValueError as exc:
        raise ContractError("URL: invalid host or port") from exc
    if parsed.scheme not in {"http", "https"} or not hostname:
        raise ContractError("URL: an absolute HTTP(S) address with a host is required")
    if parsed.username is not None or parsed.password is not None:
        raise ContractError("URL: embedded credentials are not allowed")
    if port == 0 or parsed.netloc.endswith(":"):
        raise ContractError("URL: invalid port")
    return parsed


def _validate_hostname(host: str) -> None:
    """Check syntax only, without DNS or rewriting international host spelling."""
    try:
        if ":" in host:
            IPv6Address(host)
            return
        ascii_host = host.encode("idna").decode("ascii").removesuffix(".")
    except (ValueError, UnicodeError) as exc:
        raise ContractError("URL: invalid hostname") from exc
    labels = ascii_host.split(".")
    label_pattern = r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    if len(ascii_host) > 253 or any(not re.fullmatch(label_pattern, label) for label in labels):
        raise ContractError("URL: invalid hostname")


@dataclass(frozen=True, slots=True)
class UrlRow:
    """An independent URL row; duplicates retain their own stable caller-supplied IDs."""

    row_id: str
    exact_url: str
    enabled: bool = True

    def __post_init__(self) -> None:
        row_id = require_text(self.row_id, "row_id")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", row_id):
            raise ContractError("row_id: use 1–80 letters, digits, underscores or hyphens")
        validate_url(self.exact_url)
        require_boolean(self.enabled, "enabled")
