"""A fake Firefox DevTools server — real sockets, real framing (RULE 8).

Speaks the actual wire protocol (`<byte-length>:<json>`, the unsolicited root
greeting, `listTabs` / `getTarget`, and the two-step `evaluateJSAsync` ack +
`evaluationResult` event) so the transport and session are tested against the
protocol rather than against a mock of our own assumptions.

Knobs exist for the failure modes that actually bit this protocol: a chatty
actor that pushes an event *between* request and reply, a silent server (to
exercise the timeout-poisons-the-link rule), and split frames.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional

from app.browser.rdp.framing import decode_packets, encode_packet

GREETING = {"from": "root", "applicationType": "browser",
            "testConnectionPrefix": "server1.conn1.", "traits": {"networkMonitor": True}}


class FakeFirefox:
    """A localhost server that answers like Firefox's DevTools RDP."""

    def __init__(self, tabs: Optional[List[Dict[str, Any]]] = None):
        self.tabs = tabs if tabs is not None else [
            {"actor": "server1.conn1.tabDescriptor1", "title": "Arena",
             "url": "https://arena.ai/chat", "selected": True}]
        self.eval_answer: Any = json.dumps({"ok": True, "reason": ""})
        self.console_actor = "server1.conn1.consoleActor4"
        self.chatty = False        # push a consoleAPICall before each reply
        self.silent = False        # never answer (timeout path)
        self.split_frames = False  # write each frame in two chunks
        self.no_result_id = False  # answer evaluateJSAsync inline, no event
        self.evaluated: List[str] = []
        self.connections = 0
        self.disconnections = 0
        self._server: Optional[asyncio.AbstractServer] = None
        self.port = 0

    async def start(self) -> int:
        self._server = await asyncio.start_server(self._serve, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]
        return self.port

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _write(self, writer: asyncio.StreamWriter, packet: Dict[str, Any]) -> None:
        raw = encode_packet(packet)
        if self.split_frames and len(raw) > 4:
            writer.write(raw[:3])
            await writer.drain()
            await asyncio.sleep(0)
            raw = raw[3:]
        writer.write(raw)
        await writer.drain()

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.connections += 1
        await self._write(writer, GREETING)
        buffer = b""
        try:
            while True:
                chunk = await reader.read(65536)
                if not chunk:
                    break
                buffer += chunk
                packets, buffer = decode_packets(buffer)
                for packet in packets:
                    await self._dispatch(writer, packet)
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            self.disconnections += 1
            writer.close()

    async def _dispatch(self, writer: asyncio.StreamWriter, packet: Dict[str, Any]) -> None:
        if self.silent:
            return
        actor, kind = str(packet.get("to", "")), packet.get("type")
        if self.chatty:  # an event from the very actor we are about to hear from
            await self._write(writer, {"from": actor, "type": "consoleAPICall",
                                       "message": {"level": "log"}})
        if kind == "listTabs":
            await self._write(writer, {"from": "root", "tabs": self.tabs})
        elif kind == "getTarget":
            await self._write(writer, {"from": actor,
                                       "frame": {"actor": "server1.conn1.target3",
                                                 "consoleActor": self.console_actor}})
        elif kind == "evaluateJSAsync":
            await self._eval(writer, actor, str(packet.get("text", "")))
        else:
            await self._write(writer, {"from": actor})

    async def _eval(self, writer: asyncio.StreamWriter, actor: str, text: str) -> None:
        self.evaluated.append(text)
        if self.no_result_id:
            await self._write(writer, {"from": actor, "result": self.eval_answer})
            return
        result_id = f"r{len(self.evaluated)}"
        await self._write(writer, {"from": actor, "resultID": result_id})
        await self._write(writer, {"from": actor, "type": "evaluationResult",
                                   "resultID": result_id, "result": self.eval_answer})
