import ast
import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from image_queue.automation.diagnostics import diagnostic_summary
from image_queue.automation.visual import CLEAR, PROBES, build_probe, find_and_click
from image_queue.domain.settings import HighlightSettings
from image_queue.domain.validation import ContractError

ROOT = Path(__file__).parents[2]
SELECTOR = '#fixture [data-testid="send"]'


class DOM:
    async def start(self):
        self.process = await asyncio.create_subprocess_exec(
            "node",
            str(ROOT / "tools/visual_fixture.cjs"),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
        )
        self.events = []
        return self

    async def evaluate(self, script):
        self.process.stdin.write((json.dumps({"script": script}) + "\n").encode())
        await self.process.stdin.drain()
        response = json.loads(await self.process.stdout.readline())
        self.events.append(response)
        return response["result"]

    async def close(self):
        self.process.stdin.close()
        await self.process.wait()


def test_actual_retained_probe_fragments_have_provenance():
    manifest = json.loads((ROOT / "src/image_queue/ui/visual/provenance.json").read_text())
    assert (
        hashlib.sha256((ROOT / manifest["source"]).read_bytes()).hexdigest() == manifest["sha256"]
    )
    tree = ast.parse((ROOT / manifest["source"]).read_text())
    assignments = {
        target.id: node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    extracted = {key: ast.literal_eval(assignments[key]) for key in ("_PROBE_JS", "_CLICK_BODY")}
    helpers = assignments["_HELPERS_JS"]
    assert isinstance(helpers, ast.Call) and helpers.func.attr == "replace"
    extracted["_HELPERS_JS"] = ast.literal_eval(helpers.func.value).replace(
        ast.literal_eval(helpers.args[0]), ast.literal_eval(assignments[helpers.args[1].id])
    )
    find = assignments["_FIND_BODY"]
    assert isinstance(find, ast.Call) and find.func.id == "_splice"
    extracted["_FIND_BODY"] = ast.literal_eval(find.args[0])
    for keyword in find.keywords:
        extracted["_FIND_BODY"] = extracted["_FIND_BODY"].replace(
            "__" + keyword.arg.upper() + "__",
            ast.literal_eval(assignments[keyword.value.id]).strip("\n"),
        )
    base = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_base_out_js"
    )
    returned = next(node for node in base.body if isinstance(node, ast.Return))
    extracted["out"] = ast.literal_eval(returned.value)
    assert extracted == PROBES
    for key, value in PROBES.items():
        assert hashlib.sha256(value.encode()).hexdigest() == manifest["fragments"][key]
    assert "target.click(); out.clicked = true;" in PROBES["_CLICK_BODY"]


def test_actual_dom_red_orange_same_target_click_and_expiry():
    async def run():
        dom = await DOM().start()
        try:
            settings = HighlightSettings(True, 0, 400)
            await find_and_click(dom.evaluate, SELECTOR, settings)
            assert dom.events[0]["clicks"] == 0 and len(dom.events[0]["outlines"]) == 1
            assert dom.events[1]["clicks"] == 0 and len(dom.events[1]["outlines"]) == 2
            assert "#ff2d2d" in dom.events[0]["outlines"][0]
            assert "#ff9500" in dom.events[1]["outlines"][-1]
            assert dom.events[-1]["clicks"] == 1 and not dom.events[-1]["stash"]
            assert dom.events[-1]["outlines"]  # success must not truncate requested lifetime
            await asyncio.sleep(0.45)
            await dom.evaluate("JSON.stringify({ok:true})")
            assert dom.events[-1]["outlines"] == []
        finally:
            await dom.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "mutation",
    [
        "document.querySelector('#fixture').appendChild(document.querySelector('button').cloneNode(true))",
        "document.querySelector('#fixture').style.display='none'",
        "document.querySelector('button').setAttribute('aria-disabled','true')",
        "document.querySelector('button').remove()",
    ],
)
def test_ambiguous_hidden_disabled_missing_never_click(mutation):
    async def run():
        dom = await DOM().start()
        try:
            await dom.evaluate(f"JSON.stringify((()=>{{{mutation};return {{ok:true}};}})())")
            with pytest.raises(ContractError):
                await find_and_click(dom.evaluate, SELECTOR, HighlightSettings(False))
            assert dom.events[-1]["clicks"] == 0 and not dom.events[-1]["stash"]
        finally:
            await dom.close()

    asyncio.run(run())


def test_detached_or_replaced_stash_between_phases_is_refused():
    async def run():
        for change in ["window.__cfStash.remove()", "window.__cfStash=document.body"]:
            dom = await DOM().start()
            try:
                await dom.evaluate(build_probe(SELECTOR, "find", HighlightSettings(False)))
                await dom.evaluate("JSON.stringify((()=>{" + change + ";return {};})())")
                result = json.loads(
                    await dom.evaluate(build_probe(SELECTOR, "click", HighlightSettings(False)))
                )
                assert result["error"] and not result["clicked"] and dom.events[-1]["clicks"] == 0
            finally:
                await dom.close()

    asyncio.run(run())


def test_cancel_during_confirmation_cleans_up_without_click():
    async def run():
        dom = await DOM().start()
        found = asyncio.Event()

        async def evaluate(script):
            result = await dom.evaluate(script)
            if json.loads(result).get("phase") == "find":
                found.set()
            return result

        try:
            task = asyncio.create_task(
                find_and_click(evaluate, SELECTOR, HighlightSettings(True, 1000, 1200))
            )
            await found.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert dom.events[-1]["clicks"] == 0 and dom.events[-1]["outlines"] == []
        finally:
            await dom.close()

    asyncio.run(run())


def test_zero_duration_does_not_fall_back_to_legacy_1200ms():
    async def run():
        dom = await DOM().start()
        try:
            await find_and_click(dom.evaluate, SELECTOR, HighlightSettings(True, 1000, 0))
            assert all(not event["outlines"] for event in dom.events)
            assert dom.events[-1]["clicks"] == 1
        finally:
            await dom.close()

    asyncio.run(run())


def test_probe_failure_and_cleanup_failure_never_replay():
    async def run():
        for raw in ["not-json", "[]", '{"error":"private-page-value"}']:
            calls = []

            async def evaluate(script, calls=calls, raw=raw):
                calls.append(script)
                if script == CLEAR:
                    raise OSError("cleanup unavailable")
                return raw

            with pytest.raises(ContractError):
                await find_and_click(evaluate, SELECTOR, HighlightSettings(False))
            assert len(calls) == 2

    asyncio.run(run())
    for selector, kind in [("", "find"), ("x", "unknown")]:
        with pytest.raises(ContractError):
            build_probe(selector, kind, HighlightSettings())
    assert diagnostic_summary(False, {"cookies": "private"}) == {}
    assert diagnostic_summary(
        True, {"phase": "submitted", "url": "private", "cookies": "secret"}
    ) == {"phase": "submitted", "live_adapter_enabled": False}
    assert diagnostic_summary(True, {"phase": []})["phase"] == "unknown"
