"""Real loopback HTTP/WebSocket transport against a scripted CDP peer, not live Chrome."""

import asyncio
import json
from contextlib import asynccontextmanager

import pytest
from aiohttp import web

from image_queue.browser.controller import ChromeController
from image_queue.browser.discovery import fetch_tabs, socket_url, validate_tabs
from image_queue.browser.lease import CdpLease
from image_queue.browser.session import ChromeSession
from image_queue.browser.transport import CDPClient
from image_queue.domain.presets import dumps_preset
from image_queue.domain.settings import ChromeEndpoint, ConnectionPreset
from image_queue.domain.urls import UrlRow
from image_queue.domain.validation import ContractError
from image_queue.operations import Operations
from image_queue.workspace.service import WorkspaceService

URL = "https://arena.ai/c/exact?keep=Case#fragment"


class Peer:
    def __init__(self):
        self.tabs = [("one", URL), ("two", URL), ("other", URL + "/other")]
        self.commands = []
        self.connections = []
        self.location = URL
        self.state = "complete"
        self.info_id = None
        self.endpoint = None
        self.mode = ""
        self.discovery_status = 200
        self.sockets = []

    async def discover(self, _):
        return web.json_response(
            [
                {
                    "id": key,
                    "url": url,
                    "title": "<private>&title",
                    "type": "page",
                    "webSocketDebuggerUrl": f"ws://127.0.0.1:{self.endpoint.port}/devtools/page/{key}",
                }
                for key, url in self.tabs
            ],
            status=self.discovery_status,
        )

    async def socket(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.sockets.append(ws)
        key = request.match_info["target"]
        self.connections.append(key)
        async for message in ws:
            if message.type != web.WSMsgType.TEXT:
                continue
            frame = json.loads(message.data)
            self.commands.append(frame)
            method = frame["method"]
            if self.mode == "disconnect":
                await ws.close()
                break
            if self.mode == "timeout":
                continue
            if self.mode == "malformed":
                await ws.send_str("[]")
                continue
            if self.mode == "error":
                await ws.send_json({"id": frame["id"], "error": {"message": "private error"}})
                continue
            result = {}
            if method == "Target.getTargetInfo":
                result = {"targetInfo": {"targetId": self.info_id or key, "url": self.location}}
            if method == "Runtime.evaluate":
                result = {"result": {"value": {"url": self.location, "state": self.state}}}
                if self.mode == "exception":
                    result["exceptionDetails"] = {"private": "not logged"}
                if self.mode == "navigation":
                    await ws.send_json({"method": "Runtime.executionContextsCleared", "params": {}})
            await ws.send_json({"id": frame["id"], "result": result})
        return ws


@asynccontextmanager
async def peer_server():
    peer = Peer()
    app = web.Application()
    app.router.add_get("/json/list", peer.discover)
    app.router.add_get("/devtools/page/{target}", peer.socket)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    peer.endpoint = ChromeEndpoint(port=site._server.sockets[0].getsockname()[1])
    try:
        yield peer
    finally:
        for ws in peer.sockets:
            await ws.close()
        await runner.cleanup()


def preset(peer):
    return ConnectionPreset(
        endpoint=peer.endpoint,
        urls=(
            UrlRow("row", URL, True),
            UrlRow("disabled", URL, False),
            UrlRow("missing", URL + "!", True),
        ),
    )


def test_exact_discovery_duplicate_choice_liveness_and_navigation():
    async def run():
        async with peer_server() as peer:
            session = ChromeSession(preset(peer))
            status = await session.discover()
            assert status["row"]["discovery"] == "choose_tab"
            assert status["disabled"]["discovery"] == "disabled"
            assert status["missing"]["discovery"] == "page_not_open"
            assert peer.commands == [] and peer.connections == []
            assert "webSocketDebuggerUrl" not in json.dumps(status)
            for row, target in [
                ("row", ""),
                ("disabled", "one"),
                ("missing", "one"),
                ("row", "other"),
            ]:
                with pytest.raises(ContractError):
                    await session.check(row, target)
            assert peer.connections == []
            status = await session.check("row", "two")
            assert peer.connections == ["two"]
            assert status["row"]["connection"] == "connected"
            assert status["row"]["readiness"] == "adapter_not_verified"
            assert [frame["method"] for frame in peer.commands] == [
                "Page.enable",
                "Runtime.enable",
                "Target.getTargetInfo",
                "Runtime.evaluate",
            ]
            await peer.sockets[-1].send_json({"method": "Page.frameNavigated", "params": {}})
            await asyncio.sleep(0.03)
            assert session.active is None
            assert session.status["row"]["connection"] == "disconnected"
            before = len(peer.commands)
            await session.close()
            assert len(peer.commands) == before  # never Browser.close/Target.closeTarget

    asyncio.run(run())


@pytest.mark.parametrize(
    "mode",
    [
        "redirect",
        "loading",
        "identity",
        "exception",
        "navigation",
        "disconnect",
        "malformed",
        "error",
        "timeout",
    ],
)
def test_failed_roundtrip_never_connected_or_replayed(mode):
    async def run():
        async with peer_server() as peer:
            session = ChromeSession(preset(peer))
            peer.mode = mode
            if mode == "redirect":
                peer.location = URL + "changed"
            if mode == "loading":
                peer.state = "loading"
            if mode == "identity":
                peer.info_id = "wrong"
            with pytest.raises(ContractError):
                await session.check("row", "one")
            assert session.active is None
            assert session.client._pending == {}
            assert peer.connections == ["one"]
            assert "connected" not in [v["connection"] for v in session.status.values()]
            await session.close()

    asyncio.run(run())


def test_no_redirect_discovery_and_remote_socket_rejection():
    async def run():
        async with peer_server() as peer:
            peer.discovery_status = 302
            with pytest.raises(ContractError):
                await fetch_tabs(peer.endpoint)

    asyncio.run(run())
    endpoint = ChromeEndpoint()
    for url in [
        None,
        "ws://evil.test:9222/devtools/page/id",
        "ws://127.0.0.1:99/devtools/page/id",
        "ws://user:secret@127.0.0.1:9222/devtools/page/id",
        "ws://127.0.0.1:9222/devtools/page/id?token=x",
        "ws://127.0.0.1:bad/devtools/page/id",
        "http://127.0.0.1:9222/devtools/page/id",
        "ws://127.0.0.1:9222/devtools/browser/id",
    ]:
        with pytest.raises(ContractError):
            socket_url(url, endpoint)
    good = {
        "id": "one",
        "type": "page",
        "url": URL,
        "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/one",
    }
    for value in [{}, [None], [good, good], [{**good, "id": ""}], [{**good, "url": 5}]]:
        with pytest.raises(ContractError):
            validate_tabs(value, endpoint)
    assert validate_tabs([{"type": "worker"}], endpoint) == []


def test_transport_disconnected_unknown_ids_pending_cancellation():
    async def run():
        client = CDPClient(ChromeEndpoint())
        with pytest.raises(ContractError):
            await client.send("Page.enable")
        client._dispatch({"id": 999, "result": {}})
        client._dispatch({"id": True})
        with pytest.raises(ValueError):
            client._dispatch([])
        async with peer_server() as peer:
            client = CDPClient(peer.endpoint)
            await client.connect(f"ws://127.0.0.1:{peer.endpoint.port}/devtools/page/one")
            peer.mode = "timeout"
            task = asyncio.create_task(client.send("Runtime.evaluate"))
            await asyncio.sleep(0.01)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert client._pending == {}
            await client.disconnect()

    asyncio.run(run())


def test_lease_fifo_cancellation_and_exclusion():
    async def run():
        lease = CdpLease()
        order = []

        async def acquire(index):
            async with lease:
                assert lease.busy
                order.append(index)
                await asyncio.sleep(0)

        await lease.__aenter__()
        first = asyncio.create_task(acquire(1))
        second = asyncio.create_task(acquire(2))
        await asyncio.sleep(0)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        lease.release()
        await second
        assert order == [2] and not lease.busy
        # cancellation after ownership has already been handed over must release it
        await lease.__aenter__()
        task = asyncio.create_task(acquire(3))
        await asyncio.sleep(0)
        lease.release()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not lease.busy

    asyncio.run(run())


def test_persistent_loop_controller_settings_reconnect_and_operations(state):
    async def run():
        async with peer_server() as peer:
            controller = ChromeController()
            connection = dumps_preset(preset(peer))

            async def command(kind, **kwargs):
                return await asyncio.to_thread(
                    controller.execute, {"kind": kind, **kwargs}, connection
                )

            try:
                assert await command("chrome_status") == {}
                await command("chrome_discover")
                await command("chrome_check", row_id="row", target_id="one")
                assert (await command("chrome_status"))["row"]["connection"] == "connected"
                await command("chrome_disconnect")
                assert (await command("chrome_status"))["row"]["connection"] == "disconnected"
                with pytest.raises(ContractError):
                    await command("chrome_unknown")
                connection = dumps_preset(ConnectionPreset(endpoint=peer.endpoint))
                assert await command("chrome_status") == {}
            finally:
                await asyncio.to_thread(controller.close)
            assert not controller.thread.is_alive()

            class Writer:
                def save(self, _):
                    pass

            service = WorkspaceService(state, Writer())
            ops = Operations(service)
            try:
                assert ops.execute({"kind": "chrome_status", "revision": 0})["result"] == {}
                with pytest.raises(ContractError):
                    ops.execute({"kind": "chrome_check", "revision": 0, "row_id": "r"})
                assert ops.execute({"kind": "chrome_disconnect", "revision": 0})["result"] == {}
            finally:
                ops.close()

    asyncio.run(run())


def test_streamed_discovery_limit_and_malformed_page_result():
    from image_queue.browser.discovery import _payload
    from image_queue.browser.session import _object

    class Content:
        def __init__(self, chunks):
            self.chunks = chunks

        async def iter_chunked(self, _):
            for chunk in self.chunks:
                yield chunk

    class Response:
        def __init__(self, chunks):
            self.content = Content(chunks)

    async def run():
        assert await _payload(Response([b'[{"x":', b"1}]"])) == [{"x": 1}]
        with pytest.raises(ContractError):
            await _payload(Response([b" " * 65536] * 16))

    asyncio.run(run())
    for data in [{"result": []}, {"result": {"targetInfo": None}}]:
        with pytest.raises(ContractError):
            _object(data, ("result", "targetInfo"))


def test_controller_timeout_cancels_without_replay(monkeypatch):
    controller = ChromeController()

    class Expired:
        cancelled = False

        def result(self, timeout):
            raise TimeoutError()

        def cancel(self):
            self.cancelled = True

    expired = Expired()

    def timeout(coroutine, loop):
        coroutine.close()
        return expired

    monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", timeout)
    try:
        with pytest.raises(ContractError, match="timed out"):
            controller.execute({"kind": "chrome_status"}, dumps_preset(ConnectionPreset()))
        assert expired.cancelled
    finally:
        controller.close()


def test_spa_navigation_invalidates_live_check():
    async def run():
        async with peer_server() as peer:
            session = ChromeSession(preset(peer))
            await session.check("row", "one")
            assert session.status["row"]["verified_at"]
            session._event({"method": "Runtime.consoleAPICalled"})
            assert session.active == "row"
            session._event({"method": "Page.navigatedWithinDocument"})
            assert session.active is None
            assert session.status["row"]["connection"] == "disconnected"
            await session.close()

    asyncio.run(run())
