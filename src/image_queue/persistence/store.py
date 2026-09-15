"""One OS-backed lock and authoritative snapshot; explicit backup recovery, no empty fallback."""

from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import uuid4

from filelock import FileLock, Timeout

from image_queue.domain.validation import ContractError, PersistenceFault
from image_queue.persistence.atomic import atomic_write
from image_queue.persistence.codec import MAX_STATE_BYTES, decode_state, encode_state


class SnapshotStore:
    """Caller must close; OS releases the lock on crash. Never break a live lock by PID guessing."""

    def __init__(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = directory / "state.json"
        self.backup = directory / "state.backup.json"
        self.lock = FileLock(directory / "workspace.lock", thread_local=False)
        self.failed = False
        try:
            self.lock.acquire(timeout=0)
        except Timeout as exc:
            raise ContractError(
                "Workspace is already open in another application instance"
            ) from exc

    def close(self) -> None:
        self.lock.release()

    def _read(self, path: Path) -> dict[str, Any]:
        with path.open("rb") as handle:
            return decode_state(handle.read(MAX_STATE_BYTES + 1))

    def load(self, default: dict[str, Any]) -> dict[str, Any]:
        self._require_lock()
        if self.path.exists():
            return self._read(self.path)
        if self.backup.exists() or list(self.path.parent.glob(".workspace-*.partial")):
            raise ContractError(
                "Missing primary state with recovery evidence; confirmation required"
            )
        return deepcopy(default)

    def _require_lock(self) -> None:
        if not self.lock.is_locked:
            raise ContractError("Workspace lock is not held")
        if self.failed:
            raise ContractError("Persistence fault: reopen workspace to inspect durable state")

    def save(self, state: dict[str, Any]) -> None:
        self._require_lock()
        encoded = encode_state(state)
        try:
            if self.path.exists():
                atomic_write(self.backup, encode_state(self._read(self.path)))
            atomic_write(self.path, encoded)
            if self._read(self.path) != state:
                raise ContractError("State readback differs from intended write")
        except (OSError, ContractError) as exc:
            self.failed = True
            raise PersistenceFault(
                "Saving failed; reopen to inspect/recover. No success acknowledged."
            ) from exc

    def recover_backup(self) -> dict[str, Any]:
        """Explicit user operation; preserve corrupt primary, never silently adopt a backup."""
        self._require_lock()
        state = self._read(self.backup)
        if self.path.exists():
            preserved = self.path.with_name(f"state.corrupt-{uuid4().hex}.json")
            preserved.write_bytes(self.path.read_bytes())
        atomic_write(self.path, encode_state(state))
        return self._read(self.path)
