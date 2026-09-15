import asyncio
import hashlib
import json
from copy import deepcopy
from dataclasses import replace

import pytest
from PIL import Image

from image_queue.automation.engine import OfflineExecution
from image_queue.automation.ledger import AttemptLedger
from image_queue.automation.ports import Attachment, Observation, PageBlocked
from image_queue.domain.presets import dumps_preset
from image_queue.domain.settings import ConnectionPreset, HighlightSettings
from image_queue.domain.urls import UrlRow
from image_queue.domain.validation import ContractError, PersistenceFault
from image_queue.persistence.store import SnapshotStore
from image_queue.scanning.scanner import FolderScanner
from image_queue.workspace.execution import phase, preserve_evidence, validate_execution
from image_queue.workspace.history import initial_state
from image_queue.workspace.service import WorkspaceService


class Fixture:
    test_only = True
    submit_selector = '#fixture [data-testid="send"]'

    def __init__(self):
        self.observation = Observation(
            "https://page.invalid/one",
            "target",
            "context",
            messages=("old-message",),
            responses=("old-response",),
        )
        self.items = ()
        self.text = ""
        self.uploads = 0
        self.sends = 0
        self.message = "new-message"
        self.response = "new-response"
        self.fail = ""
        self.hook = None

    async def observe(self, url):
        if self.hook:
            await self.hook()
        return replace(self.observation, url=url)

    async def upload(self, content, name):
        self.uploads += 1
        self.items = (Attachment(name, hashlib.sha256(content).hexdigest(), "new-attachment"),)
        self.observation = replace(self.observation, empty=False)
        if self.fail == "upload":
            raise OSError("private wire details")

    async def attachments(self):
        return self.items

    async def fill_prompt(self, text):
        self.text = text if self.fail != "prompt" else "wrong"

    async def read_prompt(self):
        return self.text

    async def evaluate(self, script):
        if "var doClick = true;" in script:
            self.sends += 1
            if self.fail == "send":
                raise OSError("lost ack after send")
            return json.dumps({"clicked": True})
        return json.dumps({"clickable": True, "cleared": True})

    async def marked_message(self, text):
        return self.message

    async def response_after(self, message):
        return self.response


@pytest.fixture
def execution(tmp_path, workspace):
    folder = tmp_path / "images"
    folder.mkdir()
    Image.new("RGB", (8, 8), "red").save(folder / "source.png")
    workspace["folder"] = str(folder)
    workspace["prompt"] = "keep {tone}\r\n"
    workspace["variables"] = {"tone": "literal"}
    workspace["connection"] = dumps_preset(
        ConnectionPreset(
            highlight=HighlightSettings(False),
            urls=(
                UrlRow("one", "https://page.invalid/one"),
                UrlRow("two", "https://page.invalid/two"),
            ),
        )
    )
    state = initial_state(workspace)
    state["jobs"]["sources"] = FolderScanner().scan(str(folder), workspace["scan_options"])
    key = next(iter(state["jobs"]["sources"]))
    state["workspace"]["selection"][key] = {
        "sha256": state["jobs"]["sources"][key]["sha256"],
        "decision": "selected",
    }
    store = SnapshotStore(tmp_path / "state")
    store.save(state)
    service = WorkspaceService(state, store)
    adapter = Fixture()
    engine = OfflineExecution(service, adapter)
    yield engine, adapter, key, store
    store.close()


def test_prepare_upload_prompt_send_and_correlated_wait(execution):
    engine, adapter, key, store = execution

    async def run():
        identifier = await engine.prepare(key)
        inputs = engine.ledger.attempt(identifier)["inputs"]
        assert inputs["text"] == f"[JOB-ID:{identifier}]\nkeep {{tone}}\r\n"
        assert inputs["highlight"]["highlight_enabled"] is False
        assert engine.ledger.read()["cursor"] == 1
        with pytest.raises(ContractError):
            await engine.prepare(key)
        with pytest.raises(ContractError):
            engine.service.execute(
                {"kind": "undo", "revision": engine.service.snapshot()["revision"]}
            )
        for expected in ("uploaded", "ready_to_submit", "submitted", "output_observed"):
            await engine.advance(identifier)
            assert phase(engine.ledger.attempt(identifier)) == expected
        assert adapter.sends == 1 and adapter.uploads == 1
        assert engine.ledger.attempt(identifier)["inputs"] == inputs
        assert engine.ledger.attempt(identifier)["events"][-1]["evidence"] == {
            "response_id": "new-response"
        }
        with pytest.raises(ContractError):
            await engine.advance(identifier)
        assert adapter.sends == 1
        persisted = store.load({})
        assert persisted["jobs"]["execution"] == engine.ledger.read()
        assert persisted["history"] == []

    asyncio.run(run())


@pytest.mark.parametrize(
    "failure,steps,expected_sends",
    [
        ("upload", 1, 0),
        ("prompt", 2, 0),
        ("send", 3, 1),
        ("missing_message", 3, 1),
        ("old_response", 4, 1),
    ],
)
def test_ambiguous_failures_never_retry(execution, failure, steps, expected_sends):
    engine, adapter, key, store = execution

    async def run():
        identifier = await engine.prepare(key)
        adapter.fail = failure
        if failure == "missing_message":
            adapter.message = None
        if failure == "old_response":
            adapter.response = "old-response"
        for _ in range(steps - 1):
            await engine.advance(identifier)
        with pytest.raises((OSError, ContractError)):
            await engine.advance(identifier)
        assert phase(engine.ledger.attempt(identifier)) == "needs_review"
        assert adapter.sends == expected_sends
        restarted = WorkspaceService(store.load({}), store)
        ledger = AttemptLedger(restarted)
        ledger.recover()
        assert phase(ledger.attempt(identifier)) == "needs_review"
        with pytest.raises(ContractError):
            await OfflineExecution(restarted, adapter).advance(identifier)
        assert adapter.sends == expected_sends

    asyncio.run(run())


def test_deselected_changed_unready_live_and_template_gates(execution):
    engine, adapter, key, _ = execution

    async def run():
        state = engine.service.snapshot()
        change = deepcopy(state["workspace"])
        change["selection"][key]["decision"] = "skipped"
        engine.service.execute(
            {"kind": "edit", "workspace": change, "revision": state["revision"], "label": "Skip"}
        )
        with pytest.raises(ContractError):
            await engine.prepare(key)
        engine.service.execute({"kind": "undo", "revision": engine.service.snapshot()["revision"]})
        adapter.observation = replace(adapter.observation, blocker="security")
        with pytest.raises(ContractError):
            await engine.prepare(key)
        adapter.observation = replace(adapter.observation, blocker="none")
        change = engine.service.snapshot()["workspace"]
        change["prompt_mode"] = "template"
        change["prompt"] = "{missing}"
        engine.service.execute(
            {
                "kind": "edit",
                "workspace": change,
                "revision": engine.service.snapshot()["revision"],
                "label": "Template",
            }
        )
        with pytest.raises(ContractError):
            await engine.prepare(key)
        change["connection"] = dumps_preset(
            ConnectionPreset(urls=(UrlRow("live", "https://arena.ai/c/not-authorized"),))
        )
        engine.service.execute(
            {
                "kind": "edit",
                "workspace": change,
                "revision": engine.service.snapshot()["revision"],
                "label": "Live blocked",
            }
        )
        with pytest.raises(ContractError, match="fixture"):
            await engine.prepare(key)
        assert adapter.uploads == 0 and adapter.sends == 0

    asyncio.run(run())
    adapter.test_only = False
    with pytest.raises(ContractError):
        OfflineExecution(engine.service, adapter)


def test_pause_manual_security_resolution_cancel_and_round_robin(execution):
    engine, adapter, key, _ = execution

    async def run():
        identifier = await engine.prepare(key)
        engine.ledger.controls(True, False)
        await engine.advance(identifier)
        assert adapter.uploads == 0
        engine.ledger.controls(False, False)
        adapter.observation = replace(adapter.observation, blocker="security")
        with pytest.raises(PageBlocked):
            await engine.advance(identifier)
        assert (
            engine.ledger.read()["paused"]
            and phase(engine.ledger.attempt(identifier)) == "prepared"
        )
        adapter.observation = replace(adapter.observation, blocker="none")
        engine.ledger.controls(False, False)
        engine.cancel(identifier)
        assert phase(engine.ledger.attempt(identifier)) == "cancelled"
        second = await engine.prepare(key)
        assert engine.ledger.attempt(second)["inputs"]["row_id"] == "two"
        engine.ledger.controls(False, True)
        engine.cancel(second)
        with pytest.raises(ContractError):
            await engine.prepare(key)

    asyncio.run(run())


@pytest.mark.parametrize(
    "status,expected",
    [
        ("prepared", "interrupted"),
        ("upload_intent", "needs_review"),
        ("uploaded", "interrupted"),
        ("prompt_intent", "needs_review"),
        ("ready_to_submit", "interrupted"),
        ("submit_intent", "needs_review"),
        ("submitted", "needs_review"),
    ],
)
def test_restart_at_every_durable_boundary(execution, status, expected):
    engine, adapter, key, store = execution

    async def run():
        identifier = await engine.prepare(key)
        transitions = [
            ("upload_intent", {}),
            ("uploaded", {"attachment": "a"}),
            ("prompt_intent", {}),
            ("ready_to_submit", {"prompt_sha256": "hash"}),
            ("submit_intent", {}),
            ("submitted", {"message_id": "m"}),
        ]
        for next_phase, evidence in transitions:
            if phase(engine.ledger.attempt(identifier)) == status:
                break
            engine.ledger.move(identifier, next_phase, evidence)
        fresh = WorkspaceService(store.load({}), store)
        ledger = AttemptLedger(fresh)
        ledger.recover()
        ledger.recover()
        assert phase(ledger.attempt(identifier)) == expected
        assert adapter.sends == 0 and adapter.uploads == 0
        assert fresh.snapshot()["history"] == []

    asyncio.run(run())


def test_failed_intent_write_prevents_send(execution, monkeypatch):
    engine, adapter, key, store = execution

    async def run():
        identifier = await engine.prepare(key)
        await engine.advance(identifier)
        await engine.advance(identifier)
        before = engine.service.snapshot()

        def fail(_):
            raise PersistenceFault("simulated disk fault")

        monkeypatch.setattr(store, "save", fail)
        with pytest.raises(PersistenceFault):
            await engine.advance(identifier)
        assert adapter.sends == 0 and engine.service.snapshot() == before

    asyncio.run(run())


def test_ledger_cannot_erase_inputs_events_or_fabricate_completion(execution):
    engine, _, key, _ = execution
    identifier = asyncio.run(engine.prepare(key))
    original = engine.ledger.read()
    for mutate in [
        lambda x: x["attempts"].clear(),
        lambda x: x["attempts"][identifier]["inputs"].update(raw_prompt="changed"),
        lambda x: x["attempts"][identifier]["events"].clear(),
        lambda x: x["attempts"][identifier]["events"].append(
            {"phase": "completed", "code": "completed", "evidence": {}}
        ),
    ]:
        changed = deepcopy(original)
        mutate(changed)
        with pytest.raises(ContractError):
            preserve_evidence(original, changed)
    with pytest.raises(ContractError):
        engine.ledger.attempt("missing")
    invalid = deepcopy(original)
    invalid["paused"] = 1
    with pytest.raises(ContractError):
        validate_execution(invalid)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "wrong_name",
        "changed_token",
        "changed_prompt",
        "changed_context",
        "wrong_message",
    ],
)
def test_revalidation_before_send_and_wait(execution, mutation):
    engine, adapter, key, _ = execution

    async def run():
        identifier = await engine.prepare(key)
        await engine.advance(identifier)
        await engine.advance(identifier)
        if mutation == "missing":
            adapter.items = ()
        if mutation == "wrong_name":
            adapter.items = (replace(adapter.items[0], name="other.png"),)
        if mutation == "changed_token":
            adapter.items = (replace(adapter.items[0], token="different"),)
        if mutation == "changed_prompt":
            adapter.text = "user edited prompt"
        if mutation == "changed_context":
            adapter.observation = replace(adapter.observation, context="different")
        if mutation == "wrong_message":
            await engine.advance(identifier)
            adapter.message = "another-new-message"
        with pytest.raises(ContractError):
            await engine.advance(identifier)
        assert adapter.sends == (1 if mutation == "wrong_message" else 0)

    asyncio.run(run())


def test_changed_missing_source_and_disabled_row(execution):
    from pathlib import Path

    engine, adapter, key, _ = execution

    async def run():
        with pytest.raises(ContractError):
            await engine.prepare("not-a-source")
        current = engine.service.snapshot()
        path = Path(current["jobs"]["sources"][key]["path"])
        before = path.read_bytes()
        Image.new("RGB", (8, 8), "blue").save(path)
        with pytest.raises(ContractError, match="changed"):
            await engine.prepare(key)
        path.write_bytes(before)
        workspace = engine.service.snapshot()["workspace"]
        workspace["connection"] = dumps_preset(
            ConnectionPreset(
                highlight=HighlightSettings(False),
                urls=(
                    UrlRow("off", "https://page.invalid/off", False),
                    UrlRow("on", "https://page.invalid/on"),
                ),
            )
        )
        engine.service.execute(
            {
                "kind": "edit",
                "workspace": workspace,
                "label": "Rows",
                "revision": engine.service.snapshot()["revision"],
            }
        )
        identifier = await engine.prepare(key)
        assert engine.ledger.attempt(identifier)["inputs"]["row_id"] == "on"

    asyncio.run(run())


def test_pause_while_observing_and_exclusion(execution):
    engine, adapter, key, _ = execution

    async def run():
        identifier = await engine.prepare(key)

        async def during_observe():
            with pytest.raises(ContractError):
                await engine.advance(identifier)
            with pytest.raises(ContractError):
                engine.cancel(identifier)
            engine.ledger.controls(True, False)

        adapter.hook = during_observe
        await engine.advance(identifier)
        assert adapter.uploads == 0
        adapter.hook = None
        engine.ledger.controls(False, False)
        await engine.advance(identifier)
        await engine.advance(identifier)
        await engine.advance(identifier)
        adapter.observation = replace(adapter.observation, blocker="auth")
        with pytest.raises(PageBlocked):
            await engine.advance(identifier)
        assert phase(engine.ledger.attempt(identifier)) == "needs_review"

    asyncio.run(run())


def test_pause_at_attachment_and_submit_final_check(execution):
    engine, adapter, key, _ = execution

    async def run():
        identifier = await engine.prepare(key)
        await engine.advance(identifier)
        original = adapter.attachments

        async def paused():
            engine.ledger.controls(True, False)
            return await original()

        adapter.attachments = paused
        await engine.advance(identifier)
        assert adapter.text == "" and phase(engine.ledger.attempt(identifier)) == "uploaded"
        adapter.attachments = original
        engine.ledger.controls(False, False)
        await engine.advance(identifier)
        checks = 0

        async def last_check():
            nonlocal checks
            checks += 1
            if checks == 2:
                engine.ledger.controls(True, False)

        adapter.hook = last_check
        await engine.advance(identifier)
        assert adapter.sends == 0 and phase(engine.ledger.attempt(identifier)) == "ready_to_submit"

    asyncio.run(run())


def test_lost_confirmation_write_cannot_replay_send(execution, monkeypatch):
    engine, adapter, key, store = execution

    async def run():
        identifier = await engine.prepare(key)
        await engine.advance(identifier)
        await engine.advance(identifier)
        real_save = store.save

        def fail_after_publication(state):
            real_save(state)
            if phase(state["jobs"]["execution"]["attempts"][identifier]) == "submitted":
                raise PersistenceFault("lost readback after published confirmation")

        monkeypatch.setattr(store, "save", fail_after_publication)
        with pytest.raises(PersistenceFault):
            await engine.advance(identifier)
        assert adapter.sends == 1 and phase(engine.ledger.attempt(identifier)) == "submit_intent"
        monkeypatch.setattr(store, "save", real_save)
        restarted = WorkspaceService(store.load({}), store)
        assert restarted.busy
        AttemptLedger(restarted).recover()
        with pytest.raises(ContractError):
            await OfflineExecution(restarted, adapter).advance(identifier)
        assert adapter.sends == 1

    asyncio.run(run())


def test_cancel_task_after_upload_intent_is_review_not_reupload(execution):
    engine, adapter, key, _ = execution

    async def run():
        identifier = await engine.prepare(key)
        entered = asyncio.Event()

        async def upload(*args):
            entered.set()
            await asyncio.Event().wait()

        adapter.upload = upload
        task = asyncio.create_task(engine.advance(identifier))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert phase(engine.ledger.attempt(identifier)) == "needs_review"
        assert not engine.running

    asyncio.run(run())


def test_invalid_ledger_shapes_and_input_changes(execution):
    from image_queue.workspace.attempt_inputs import validate_inputs

    engine, _, key, _ = execution
    identifier = asyncio.run(engine.prepare(key))
    original = engine.ledger.read()
    variants = [
        lambda x: x.update(attempts=[]),
        lambda x: x["attempts"][identifier].update(events=[]),
        lambda x: x["attempts"][identifier]["inputs"].update(id="wrong"),
        lambda x: x["attempts"][identifier]["events"][0].update(phase=[]),
        lambda x: x["attempts"][identifier]["events"][0].update(
            evidence={"private": "not permitted"}
        ),
    ]
    for mutate in variants:
        changed = deepcopy(original)
        mutate(changed)
        with pytest.raises(ContractError):
            validate_execution(changed)
    source = original["attempts"][identifier]["inputs"]
    variants = [
        lambda x: x.update(id="bad"),
        lambda x: x["source"].update(sha256="bad"),
        lambda x: x["source"].update(path="\x00"),
        lambda x: x["baseline"].update(context=""),
        lambda x: x["baseline"].update(messages="bad"),
        lambda x: x["baseline"].update(messages=[None]),
        lambda x: x["baseline"].update(messages=["a", "a"]),
    ]
    for mutate in variants:
        changed = deepcopy(source)
        mutate(changed)
        with pytest.raises(ContractError):
            validate_inputs(changed)
    copied = deepcopy(source)
    copied["id"] = "a" * 32
    copied["text"] = copied["text"].replace(identifier, copied["id"])
    changed = deepcopy(original)
    changed["attempts"][copied["id"]] = {
        "inputs": copied,
        "events": [{"phase": "prepared", "code": "prepared", "evidence": {}}],
    }
    with pytest.raises(ContractError):
        validate_execution(changed)
    engine.ledger.move(identifier, "upload_intent")
    prior = engine.ledger.read()
    with pytest.raises(ContractError):
        preserve_evidence(prior, original)
    with pytest.raises(ContractError):
        engine.ledger.move(identifier, "uploaded", {"attachment": ""})


def test_real_process_exit_after_send_intent_never_replays(execution, tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path

    engine, adapter, key, store = execution
    directory = store.path.parent
    store.close()
    counter = tmp_path / "synthetic-send-count"
    script = """
import os,sys,asyncio,json
from pathlib import Path
from test_execution import Fixture
from image_queue.persistence.store import SnapshotStore
from image_queue.workspace.service import WorkspaceService
from image_queue.automation.engine import OfflineExecution
store=SnapshotStore(Path(sys.argv[1]));service=WorkspaceService(store.load({}),store)
class Crash(Fixture):
 async def evaluate(self,script):
  if 'var doClick = true;' in script:
   identifier=next(iter(service.snapshot()['jobs']['execution']['attempts']))
   Path(sys.argv[3]).write_text(json.dumps({'id':identifier,'sends':1}))
   os._exit(17)
  return await super().evaluate(script)
async def run():
 adapter=Crash();engine=OfflineExecution(service,adapter)
 identifier=await engine.prepare(sys.argv[2])
 await engine.advance(identifier)
 await engine.advance(identifier)
 await engine.advance(identifier)
asyncio.run(run())
"""
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).parent))
    child = subprocess.run(
        [sys.executable, "-c", script, str(directory), key, str(counter)],
        env=env,
        timeout=15,
        capture_output=True,
    )
    assert child.returncode == 17, child.stderr.decode()
    identifier = json.loads(counter.read_text())["id"]
    reopened = SnapshotStore(directory)
    try:
        service = WorkspaceService(reopened.load({}), reopened)
        assert (
            phase(service.snapshot()["jobs"]["execution"]["attempts"][identifier])
            == "submit_intent"
        )
        restored = OfflineExecution(service, adapter)
        restored.recover()
        with pytest.raises(ContractError):
            asyncio.run(restored.advance(identifier))
        assert json.loads(counter.read_text())["sends"] == 1 and adapter.sends == 0
    finally:
        reopened.close()


def test_pending_wait_is_observation_only_and_timeout_requires_review(execution):
    engine, adapter, key, _ = execution

    async def run():
        identifier = await engine.prepare(key)
        for _ in range(3):
            await engine.advance(identifier)
        polls = 0

        async def poll(message):
            nonlocal polls
            polls += 1
            if polls == 1:
                return None
            raise TimeoutError("fixture response deadline")

        adapter.response_after = poll
        engine.ledger.controls(True, True)
        with pytest.raises(TimeoutError):
            await engine.advance(identifier)
        assert polls == 2 and adapter.sends == 1
        assert phase(engine.ledger.attempt(identifier)) == "needs_review"

    asyncio.run(run())


def test_restored_ready_attempt_requires_explicit_recovery(execution):
    engine, adapter, key, store = execution

    async def run():
        identifier = await engine.prepare(key)
        for _ in range(2):
            await engine.advance(identifier)
        restored = OfflineExecution(WorkspaceService(store.load({}), store), adapter)
        with pytest.raises(ContractError, match="recovery"):
            await restored.advance(identifier)
        restored.recover()
        assert phase(restored.ledger.attempt(identifier)) == "interrupted"
        assert adapter.sends == 0
        with pytest.raises(ContractError):
            await restored.advance(identifier)

    asyncio.run(run())


def test_lifecycle_dispatches_actual_retained_dom_click_only_after_durable_intent(execution):
    from test_visual import DOM

    engine, adapter, key, store = execution

    async def run():
        dom = await DOM().start()
        try:
            identifier = await engine.prepare(key)

            async def evaluate(script):
                if "var doClick = true;" in script:
                    persisted = store.load({})["jobs"]["execution"]["attempts"][identifier]
                    assert phase(persisted) == "submit_intent"
                return await dom.evaluate(script)

            adapter.evaluate = evaluate
            for _ in range(4):
                await engine.advance(identifier)
            assert dom.events[-1]["clicks"] == 1
            with pytest.raises(ContractError):
                await engine.advance(identifier)
            assert dom.events[-1]["clicks"] == 1
        finally:
            await dom.close()

    asyncio.run(run())
