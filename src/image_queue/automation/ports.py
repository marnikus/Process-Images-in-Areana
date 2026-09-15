"""Offline adapter contracts. No Arena implementation, selectors or browser launcher."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Observation:
    url: str
    target: str
    context: str
    blocker: str = "none"
    empty: bool = True
    messages: tuple[str, ...] = ()
    responses: tuple[str, ...] = ()


@dataclass(frozen=True)
class Attachment:
    name: str
    sha256: str
    token: str


class FixtureAdapter(Protocol):
    test_only: bool

    async def observe(self, url: str) -> Observation: ...
    async def upload(self, content: bytes, name: str) -> None: ...
    async def attachments(self) -> tuple[Attachment, ...]: ...
    async def fill_prompt(self, text: str) -> None: ...
    async def read_prompt(self) -> str: ...

    submit_selector: str

    async def evaluate(self, script: str) -> str: ...
    async def marked_message(self, text: str) -> str | None: ...
    async def response_after(self, message: str) -> str | None: ...


class PageBlocked(Exception):
    """Manual authentication/security action required; never automate the blocker."""
