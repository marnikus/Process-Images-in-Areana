"""Real local images/files/writer and synthetic remote ownership; never a live download."""

import asyncio
import hashlib
import io
from dataclasses import replace
from pathlib import Path

import pytest
import test_execution
from PIL import Image

from image_queue.automation import output_files
from image_queue.automation.engine import OfflineExecution
from image_queue.automation.output import FixtureOutput, OutputSaver
from image_queue.domain.validation import ContractError, PersistenceFault
from image_queue.persistence.store import SnapshotStore
from image_queue.workspace.execution import append_phase, phase
from image_queue.workspace.service import WorkspaceService

execution = test_execution.execution


def image_bytes(fmt="PNG"):
    buffer = io.BytesIO()
    Image.new("RGB", (8, 9), "blue").save(buffer, format=fmt)
    return buffer.getvalue()


def observed(execution):
    engine, adapter, key, store = execution

    async def run():
        identifier = await engine.prepare(key)
        for _ in range(4):
            await engine.advance(identifier)
        return identifier

    identifier = asyncio.run(run())
    payload = FixtureOutput(adapter.message, adapter.response, image_bytes(), True)
    return engine, identifier, payload, store


@pytest.mark.parametrize(
    "fmt,extension",
    [("PNG", ".png"), ("JPEG", ".jpg"), ("WEBP", ".webp"), ("BMP", ".bmp"), ("TIFF", ".tiff")],
)
def test_correlated_original_save_actual_extension_and_no_repeat(
    execution, tmp_path, fmt, extension
):
    engine, identifier, payload, store = observed(execution)
    payload = replace(payload, content=image_bytes(fmt))
    source = Path(engine.ledger.attempt(identifier)["inputs"]["source"]["path"])
    before = source.read_bytes()
    history = engine.service.snapshot()["history"]
    path = OutputSaver(engine.ledger).save(identifier, payload, tmp_path)
    assert path.name == "source_AI" + extension
    assert path.read_bytes() == payload.content and source.read_bytes() == before
    persisted = store.load({})["jobs"]["execution"]["attempts"][identifier]
    assert phase(persisted) == "saved" and not engine.service.busy
    assert engine.service.snapshot()["history"] == history
    assert (
        persisted["events"][-1]["evidence"]["sha256"] == hashlib.sha256(payload.content).hexdigest()
    )
    with pytest.raises(ContractError):
        OutputSaver(engine.ledger).save(identifier, payload, tmp_path)
    with pytest.raises(ContractError, match="already"):
        asyncio.run(engine.prepare(execution[2]))
    assert not list(tmp_path.glob("*.partial"))


@pytest.mark.parametrize(
    "change",
    [
        dict(message_id="old-message"),
        dict(response_id="old-response"),
        dict(permitted_original=False),
        dict(test_only=False),
        dict(content=b"<html>not an image</html>"),
        dict(content=b""),
    ],
)
def test_invalid_ownership_permission_bytes_never_publish(execution, tmp_path, change):
    engine, identifier, payload, _ = observed(execution)
    with pytest.raises(ContractError):
        OutputSaver(engine.ledger).save(identifier, replace(payload, **change), tmp_path)
    assert phase(engine.ledger.attempt(identifier)) == "output_observed"
    assert not list(tmp_path.glob("*_AI*"))


def test_collisions_and_links_are_not_overwritten(execution, tmp_path):
    engine, identifier, payload, _ = observed(execution)
    first = tmp_path / "source_AI.png"
    first.write_bytes(b"keep")
    (tmp_path / "source_AI_2.png").symlink_to(tmp_path / "absent")
    path = OutputSaver(engine.ledger).save(identifier, payload, tmp_path)
    assert path.name == "source_AI_3.png" and first.read_bytes() == b"keep"
    assert (tmp_path / "source_AI_2.png").is_symlink()


def test_publication_race_is_no_clobber_and_requires_review(execution, tmp_path, monkeypatch):
    engine, identifier, payload, _ = observed(execution)
    original = output_files.os.link

    def race(source, destination):
        assert phase(engine.ledger.attempt(identifier)) == "save_intent"
        Path(destination).write_bytes(b"other publisher")
        original(source, destination)

    monkeypatch.setattr(output_files.os, "link", race)
    with pytest.raises(FileExistsError):
        OutputSaver(engine.ledger).save(identifier, payload, tmp_path)
    assert (tmp_path / "source_AI.png").read_bytes() == b"other publisher"
    assert phase(engine.ledger.attempt(identifier)) == "needs_review"
    with pytest.raises(ContractError):
        OutputSaver(engine.ledger).verify_saved(identifier)
    assert not list(tmp_path.glob("*.partial"))


@pytest.mark.parametrize("when", ["save_intent", "saved"])
def test_save_writer_failure_never_claims_completion(execution, tmp_path, monkeypatch, when):
    engine, identifier, payload, store = observed(execution)
    original = store.save

    def fail(state):
        if phase(state["jobs"]["execution"]["attempts"][identifier]) == when:
            raise PersistenceFault("injected writer fault")
        original(state)

    monkeypatch.setattr(store, "save", fail)
    with pytest.raises(PersistenceFault):
        OutputSaver(engine.ledger).save(identifier, payload, tmp_path)
    assert phase(engine.ledger.attempt(identifier)) == (
        "output_observed" if when == "save_intent" else "save_intent"
    )
    assert (tmp_path / "source_AI.png").exists() == (when == "saved")
    monkeypatch.setattr(store, "save", original)
    if when == "saved":
        engine.recover()
        assert phase(engine.ledger.attempt(identifier)) == "needs_review"
        assert OutputSaver(engine.ledger).verify_saved(identifier).read_bytes() == payload.content


def test_failed_file_flush_retains_review_and_cleans_partial(execution, tmp_path, monkeypatch):
    engine, identifier, payload, _ = observed(execution)

    # Fail the publication boundary, not the snapshot writer's own fsync.
    def fail(_directory):
        raise OSError("injected directory flush failure")

    monkeypatch.setattr(output_files, "sync_directory", fail)
    with pytest.raises(OSError):
        OutputSaver(engine.ledger).save(identifier, payload, tmp_path)
    assert phase(engine.ledger.attempt(identifier)) == "needs_review"
    assert not list(tmp_path.glob("*.partial"))


def test_output_path_and_evidence_rejection(execution, tmp_path, monkeypatch):
    engine, identifier, payload, _ = observed(execution)
    saver = OutputSaver(engine.ledger)
    with pytest.raises(ContractError):
        saver.verify_saved(identifier)
    with pytest.raises(ContractError):
        saver.save(identifier, payload, tmp_path / "missing")
    link = tmp_path / "linked"
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ContractError):
        saver.save(identifier, payload, link)
    for evidence in [
        dict(path="/x", sha256="a" * 64, response_id="wrong"),
        dict(path="/x", sha256="bad", response_id=payload.response_id),
        dict(path="\x00", sha256="a" * 64, response_id=payload.response_id),
    ]:
        with pytest.raises(ContractError):
            engine.ledger.move(identifier, "save_intent", evidence)
    monkeypatch.setattr(output_files, "LIMIT", 2)
    with pytest.raises(ContractError):
        output_files.inspect_output(b"123")
    monkeypatch.setattr(output_files.os.path, "lexists", lambda _: True)
    with pytest.raises(ContractError):
        output_files.destination(tmp_path, Path("source.png"), ".png")


def test_verification_detects_changed_bytes_extension_and_links(tmp_path):
    content = image_bytes()
    digest = hashlib.sha256(content).hexdigest()
    path = tmp_path / "file.png"
    path.write_bytes(content)
    with pytest.raises(ContractError):
        output_files.verify_file(path, "0" * 64)
    wrong = tmp_path / "file.jpg"
    wrong.write_bytes(content)
    with pytest.raises(ContractError):
        output_files.verify_file(wrong, digest)
    link = tmp_path / "link.png"
    link.symlink_to(path)
    with pytest.raises(ContractError):
        output_files.verify_file(link, digest)


def test_review_cannot_fabricate_saved_without_save_intent(execution):
    engine, adapter, key, _ = execution

    async def run():
        identifier = await engine.prepare(key)
        for _ in range(2):
            await engine.advance(identifier)
        adapter.fail = "send"
        with pytest.raises(OSError):
            await engine.advance(identifier)
        evidence = dict(path="/x.png", sha256="a" * 64, response_id="x")
        with pytest.raises(ContractError):
            append_phase(engine.ledger.read(), identifier, "saved", evidence)
        with pytest.raises(ContractError):
            OutputSaver(engine.ledger).verify_saved(identifier)

    asyncio.run(run())


def test_process_crash_after_publication_recovers_without_republish(execution, tmp_path):
    import os
    import subprocess
    import sys

    engine, identifier, payload, store = observed(execution)
    directory = store.path.parent
    store.close()
    raw = tmp_path / "fixture-original"
    raw.write_bytes(payload.content)
    script = """
import os,sys
from pathlib import Path
from image_queue.persistence.store import SnapshotStore
from image_queue.workspace.service import WorkspaceService
from image_queue.automation.ledger import AttemptLedger
from image_queue.automation.output import OutputSaver,FixtureOutput
store=SnapshotStore(Path(sys.argv[1]))
ledger=AttemptLedger(WorkspaceService(store.load({}),store))
original=ledger.move
def crash(identifier,status,evidence=None):
 if status=='saved':os._exit(23)
 original(identifier,status,evidence)
ledger.move=crash
OutputSaver(ledger).save(sys.argv[2],FixtureOutput('new-message','new-response',Path(sys.argv[3]).read_bytes(),True),Path(sys.argv[3]).parent)
"""
    child = subprocess.run(
        [sys.executable, "-c", script, str(directory), identifier, str(raw)],
        capture_output=True,
        timeout=15,
        env=dict(os.environ),
    )
    assert child.returncode == 23, child.stderr.decode()
    reopened = SnapshotStore(directory)
    try:
        service = WorkspaceService(reopened.load({}), reopened)
        restored = OfflineExecution(service, execution[1])
        restored.recover()
        assert phase(restored.ledger.attempt(identifier)) == "needs_review"
        path = OutputSaver(restored.ledger).verify_saved(identifier)
        assert path.read_bytes() == payload.content and not service.busy
        assert len(list(tmp_path.glob("*_AI*"))) == 1
        with pytest.raises(ContractError):
            OutputSaver(restored.ledger).verify_saved(identifier)
    finally:
        reopened.close()


def test_two_file_offline_lifecycle_preserves_history_and_round_robin(execution, tmp_path):
    from image_queue.scanning.scanner import FolderScanner

    engine, adapter, key, store = execution
    state = engine.service.snapshot()
    source_folder = Path(state["workspace"]["folder"])
    (source_folder / "second.png").write_bytes(image_bytes())
    sources = FolderScanner().scan(str(source_folder), state["workspace"]["scan_options"])
    state = engine.service.record_sources(sources, state["revision"])
    state["workspace"]["selection"] = {
        k: {"decision": "selected", "sha256": v["sha256"]} for k, v in sources.items()
    }
    engine.service.execute(
        dict(
            kind="edit",
            revision=state["revision"],
            workspace=state["workspace"],
            label="Select batch",
        )
    )

    async def run():
        rows = []
        for index, source_id in enumerate(sources):
            adapter.observation = replace(adapter.observation, empty=True)
            adapter.items = ()
            adapter.message = f"message-{index}"
            adapter.response = f"response-{index}"
            identifier = await engine.prepare(source_id)
            rows.append(engine.ledger.attempt(identifier)["inputs"]["row_id"])
            for _ in range(4):
                await engine.advance(identifier)
            OutputSaver(engine.ledger).save(
                identifier,
                FixtureOutput(adapter.message, adapter.response, image_bytes(), True),
                tmp_path,
            )
        assert rows == ["one", "two"] and adapter.sends == 2

    asyncio.run(run())
    persisted = store.load({})
    assert all(phase(a) == "saved" for a in persisted["jobs"]["execution"]["attempts"].values())
    # Global undo changes selection only; it cannot erase completed external evidence.
    engine.service.execute(dict(kind="undo", revision=persisted["revision"]))
    assert engine.service.snapshot()["jobs"] == persisted["jobs"]
    restored = WorkspaceService(store.load({}), store)
    assert not restored.busy


def test_reparse_directory_and_non_bytes_are_rejected(tmp_path, monkeypatch):
    from types import SimpleNamespace

    original = Path.lstat
    monkeypatch.setattr(
        Path,
        "lstat",
        lambda path: SimpleNamespace(st_file_attributes=0x400)
        if path == tmp_path
        else original(path),
    )
    # is_symlink also uses lstat; retain a normal mode while modelling Windows flags.
    monkeypatch.setattr(Path, "is_symlink", lambda path: False)
    with pytest.raises(ContractError):
        output_files.destination(tmp_path, Path("source.png"), ".png")
    with pytest.raises(ContractError):
        output_files.inspect_output("not bytes")


def test_publisher_never_replaces_existing_destination(tmp_path):
    path = tmp_path / "existing.png"
    path.write_bytes(b"preserve existing bytes")
    content = image_bytes()
    with pytest.raises(FileExistsError):
        output_files.publish(path, content, hashlib.sha256(content).hexdigest())
    assert path.read_bytes() == b"preserve existing bytes"
    assert not list(tmp_path.glob("*.partial"))
