"""Persistent one-operation undo for local recording folder deletion."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Iterable


class RecordingDeletionUndo:
    """Stage recording folders outside the visible history and restore once."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.trash = self.root / ".delete_undo"
        self.operation = self.trash / "operation.json"

    def stage(self, session_ids: Iterable[str]) -> int:
        sources = self._sources(session_ids)
        if not sources:
            return 0
        self._purge()
        self.trash.mkdir(parents=True, exist_ok=True)
        moved: list[tuple[Path, Path]] = []
        try:
            for source in sources:
                target = self.trash / source.name
                os.replace(source, target)
                moved.append((source, target))
            self.operation.write_text(
                json.dumps({"session_ids": [source.name for source in sources]}), encoding="utf-8")
        except Exception:
            self._rollback(moved)
            raise
        return len(moved)

    def undo(self) -> int:
        session_ids = self._operation_ids()
        if not session_ids:
            return 0
        targets = [(self.trash / session_id, self.root / session_id) for session_id in session_ids]
        if any(not source.is_dir() or source.is_symlink() for source, _ in targets):
            raise FileNotFoundError("undo recording not found")
        if any(target.exists() for _, target in targets):
            raise FileExistsError("recording already exists; undo refused")
        moved: list[tuple[Path, Path]] = []
        try:
            for source, target in targets:
                os.replace(source, target)
                moved.append((source, target))
        except Exception:
            self._rollback(moved)
            raise
        self._purge()
        return len(moved)

    def _sources(self, session_ids: Iterable[str]) -> list[Path]:
        unique = list(dict.fromkeys(str(value) for value in session_ids))
        sources = [self._session_folder(session_id) for session_id in unique]
        if any(not source.is_dir() or source.is_symlink() for source in sources):
            raise FileNotFoundError("recording not found")
        return sources

    def _session_folder(self, session_id: str) -> Path:
        if not session_id or Path(session_id).name != session_id or session_id.startswith("."):
            raise ValueError("invalid session id")
        return self.root / session_id

    def _operation_ids(self) -> list[str]:
        if not self.operation.is_file():
            return []
        data = json.loads(self.operation.read_text(encoding="utf-8"))
        values = data.get("session_ids", []) if isinstance(data, dict) else []
        return [self._session_folder(str(value)).name for value in values]

    def _purge(self) -> None:
        if self.trash.exists():
            shutil.rmtree(self.trash)

    @staticmethod
    def _rollback(moved: list[tuple[Path, Path]]) -> None:
        for original, current in reversed(moved):
            if current.exists() and not original.exists():
                os.replace(current, original)
