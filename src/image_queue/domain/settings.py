"""Typed connection/highlight defaults inherited from old CDP and ClickRequest contracts."""

from dataclasses import dataclass, field

from image_queue.domain.urls import UrlRow
from image_queue.domain.validation import ContractError, require_boolean, require_integer


@dataclass(frozen=True, slots=True)
class ChromeEndpoint:
    """Only explicit loopback hosts; never DNS-resolve arbitrary user hostnames."""

    host: str = "127.0.0.1"
    port: int = 9222

    def __post_init__(self) -> None:
        if self.host not in ("127.0.0.1", "::1", "localhost"):
            raise ContractError("Chrome host: only loopback addresses are supported")
        require_integer(self.port, (1, 65535), "Chrome port")

    @property
    def discovery_origin(self) -> str:
        host = "[::1]" if self.host == "::1" else self.host
        return f"http://{host}:{self.port}"


@dataclass(frozen=True, slots=True)
class HighlightSettings:
    """Preserve legacy parameter names/units; duration does not use speed scaling."""

    highlight_enabled: bool = True
    confirm_pause_ms: int = 700
    highlight_ms: int = 1200

    def __post_init__(self) -> None:
        require_boolean(self.highlight_enabled, "highlight_enabled")
        require_integer(self.confirm_pause_ms, (0, 30000), "confirm_pause_ms")
        require_integer(self.highlight_ms, (0, 30000), "highlight_ms")


@dataclass(frozen=True, slots=True)
class ConnectionPreset:
    """Foundation subset, not a replacement for full workspace/template preset libraries."""

    endpoint: ChromeEndpoint = field(default_factory=ChromeEndpoint)
    highlight: HighlightSettings = field(default_factory=HighlightSettings)
    urls: tuple[UrlRow, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.endpoint, ChromeEndpoint):
            raise ContractError("endpoint: expected ChromeEndpoint")
        if not isinstance(self.highlight, HighlightSettings):
            raise ContractError("highlight: expected HighlightSettings")
        if type(self.urls) is not tuple or any(not isinstance(row, UrlRow) for row in self.urls):
            raise ContractError("urls: expected an immutable tuple of URL rows")
        ids = [row.row_id for row in self.urls]
        if len(ids) != len(set(ids)):
            raise ContractError("urls: row IDs must be unique")
