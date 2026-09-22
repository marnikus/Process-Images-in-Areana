"""Fake Firefox DevTools server (RDP) — real TCP, `length:JSON`, no browser.

Its framing is written independently of the client under test (its own UTF-16
counting), and it can misbehave on purpose: no greeting, byte-counted prefixes,
actors that expire, a socket that never answers, or a console actor that only
`attach` reveals — the shapes a real Firefox has shown across versions.

Real-server facts this stub mirrors (see the round-8 design §2):
* on connect the server sends the root form (`from:"root"`, `applicationType`,
  `testConnectionPrefix`, `traits`);
* `listTabs` answers tab **descriptors** carrying `browsingContextID` /
  `outerWindowID` / `traits.watcher` (never a console actor);
* `getTarget` on a descriptor answers the target form with `consoleActor`;
* commands to a dead actor answer `{"error":"noSuchActor"}`;
* a big value comes back as a `longString` grip, fetched with `substring`;
* actor ids change per connection (`server1.connN.…`), `browsingContextID` does not.
"""
from __future__ import annotations

import json
import socketserver
import threading

LONG_THRESHOLD = 32

STUB_TABS = [
    {"title": "Arena", "url": "https://arena.ai/c/1"},
    {"title": "Проверка 🚀", "url": "https://arena.ai/c/2"},
]


def utf16_len(text: str) -> int:
    """Firefox's prefix counts UTF-16 code units, not bytes."""
    return sum(1 if ord(ch) <= 0xFFFF else 2 for ch in text)


def frame(payload: dict, byte_prefixed: bool = False) -> bytes:
    """One server packet: `<length>:<json>` (UTF-8 body)."""
    text = json.dumps(payload, ensure_ascii=False)
    body = text.encode("utf-8")
    size = len(body) if byte_prefixed else utf16_len(text)
    return f"{size}:{text}".encode("utf-8")


class ClientFramer:
    """Server-side framing: exactly what the prefix promises, leftovers kept.

    A naive `recv(4096)` per packet swallows a second packet that arrived in the
    same TCP read — which is how two back-to-back client packets disappear.
    """

    def __init__(self, conn) -> None:
        self._conn = conn
        self._pending = b""

    def _read(self, size: int) -> bytes:
        out, self._pending = self._pending[:size], self._pending[size:]
        while len(out) < size:
            chunk = self._conn.recv(size - len(out))
            if not chunk:
                return b"" if not out else out
            out += chunk
        return out

    def _decode(self, raw: bytes):
        """The JSON of one body; a few extra bytes for a multibyte cut are fine."""
        decoder = json.JSONDecoder()
        while True:
            text = raw.decode("utf-8", errors="ignore")
            try:
                packet, end = decoder.raw_decode(text)
            except ValueError:
                extra = self._conn.recv(1)
                if not extra:
                    raise
                raw += extra
                continue
            self._pending = text[end:].encode("utf-8") + self._pending
            return packet

    def packet(self):
        """One client packet, or None at EOF; ValueError on a non-RDP prefix."""
        head = b""
        while not head.endswith(b":"):
            byte = self._read(1)
            if not byte:
                return None
            head += byte
        declared = int(head[:-1])
        body = self._read(declared)
        return self._decode(body) if body else None


class _Session:
    """Per-connection actor tree (ids rotate, browsingContextIDs do not)."""

    def __init__(self, server, conn_no: int):
        self.server = server
        self.conn_no = conn_no
        self.prefix = f"server1.conn{conn_no}."
        self.descriptors = []
        for index, tab in enumerate(server.tabs):
            self.descriptors.append({
                "actor": f"{self.prefix}tabDescriptor{index + 1}",
                "browserId": 2, "browsingContextID": 3 + index, "outerWindowID": 6 + index,
                "isZombieTab": False, "selected": index == 0,
                "title": tab["title"], "url": tab["url"],
                "traits": {"watcher": True, "supportsReloadDescriptor": True},
            })
        # one console actor per tab, as a real Firefox has: `getTarget` on a descriptor
        # answers *that* tab's console actor, which is how a client's JS lands in the tab
        # it asked for (round 9 — the pool join of ctx-4 must not evaluate in ctx-3)
        self.console_actors = {desc["actor"]: f"{self.prefix}consoleActor{index + 1}"
                               for index, desc in enumerate(self.descriptors)}
        self.tab_index = {desc["actor"]: index for index, desc in enumerate(self.descriptors)}
        self.console_actor = self.console_actors[self.descriptors[0]["actor"]]
        self.evals = 0
        self.stale_left = max(0, int(server.stale_evals))
        self.long_strings = {}
        self.long_seq = 0

    def greeting(self) -> dict:
        return {"from": "root", "applicationType": "browser",
                "testConnectionPrefix": self.prefix,
                "traits": {"watcher": True, "networkMonitor": True}}

    def handle(self, packet: dict) -> list:
        """Replies for one request ([] when the actor is gone)."""
        target, kind = str(packet.get("to", "")), str(packet.get("type", ""))
        if kind == "listTabs":
            return [{"from": "root", "tabs": self.descriptors}]
        if kind == "getTarget":
            return [self._target_form(target)]
        if kind == "attach":
            return [{"from": target, "type": "tabAttached", "threadActor": f"{self.prefix}threadActor1",
                     "consoleActor": self.console_actor}]
        if kind == "requestTypes":
            return [{"from": target, "types": self._types()}]
        if kind == "substring":
            return [self._substring(packet)]
        if kind == "evaluateJS":
            return [self._evaluate(packet, async_reply=False)]
        if kind == "evaluateJSAsync":
            reply = self._evaluate(packet, async_reply=True)
            if "resultID" in reply:
                return [reply, dict(reply, type="evaluationResult")]
            return [reply]
        return [{"from": target, "error": "unrecognizedPacketType", "message": f"{kind} is not served"}]

    def _types(self) -> list:
        base = ["getTarget", "attach", "startListeners", "evaluateJS", "requestTypes", "substring"]
        return base + (["evaluateJSAsync"] if self.server.async_eval else [])

    def _substring(self, packet: dict) -> dict:
        """The registered long string's slice (a LongStringActor is per value)."""
        target = str(packet.get("to", ""))
        text = self.long_strings.get(target)
        if text is None:
            return {"from": target, "error": "noSuchActor", "message": f"no such long string {target}"}
        start = int(packet.get("start") or 0)
        end = int(packet.get("end") or len(text))
        return {"from": target, "substring": text[start:end], "start": start, "end": end}

    def _target_form(self, descriptor_actor: str) -> dict:
        """The target form; without `consoleActor` when the stub wants `attach`."""
        form = {"actor": f"{self.prefix}target1", "browsingContextID": 3,
                "traits": {"isBrowsingContext": True, "watcher": True},
                "screenshotActor": f"{self.prefix}screenshotActor1"}
        if not self.server.legacy_attach:
            form["consoleActor"] = self.console_actors.get(descriptor_actor, self.console_actor)
            form["frame"] = {"actor": f"{self.prefix}windowGlobal1"}
        return {"from": descriptor_actor, "form": form}

    def _expired(self, actor: str) -> bool:
        """True when the console actor should answer `noSuchActor` now.

        Real Firefox renames actors on navigation and drops them with the
        connection; `stale_evals` reproduces the first case (the client must
        re-resolve and retry once) and `expire_hard` the second (no actor ever
        works — the call must fail by name, not loop).
        """
        if actor not in self.console_actors.values():
            return True
        if self.server.expire_hard:
            return True
        if self.stale_left <= 0:
            return False
        self.stale_left -= 1
        self._rename_console(actor)
        return True

    def _rename_console(self, actor: str) -> None:
        """Rename this tab's console actor (what a navigation does to the real server)."""
        fresh = f"{self.prefix}consoleActor{self.stale_left + 2}"
        for descriptor, console in list(self.console_actors.items()):
            if console == actor:
                self.console_actors[descriptor] = fresh
                if descriptor == self.descriptors[0]["actor"]:
                    self.console_actor = fresh
                return

    def _tab_of(self, actor: str) -> dict:
        """The tab whose console actor this is (tab 0 when the actor is not a console)."""
        for descriptor, console in self.console_actors.items():
            if console == actor:
                return self.server.tabs[self.tab_index[descriptor]]
        return self.server.tabs[0]

    def _evaluate(self, packet: dict, async_reply: bool) -> dict:
        actor = str(packet.get("to", ""))
        if self._expired(actor):
            return {"from": actor, "error": "noSuchActor", "message": f"no such actor {actor}"}
        self.evals += 1
        reply = {"from": actor, "input": packet.get("text", ""), "timestamp": 1}
        if async_reply:
            reply["resultID"] = f"result-{self.evals}"
        if "boom" in str(packet.get("text", "")):
            return dict(reply, result={"type": "undefined"},
                        exceptionMessage="Error: boom", exception={"type": "undefined"})
        reply["result"] = self._grip(self._value(str(packet.get("text", "")), self._tab_of(actor)))
        return reply

    def _value(self, expression: str, tab: dict = None):
        tab = tab or self.server.tabs[0]
        if ".click()" in expression:
            found = self.server.click_found
            return json.dumps({"ok": found, "why": "clicked" if found else "not found"})
        if "navigator.webdriver" in expression:
            return json.dumps({"webdriver": False, "plugins": 5, "languages": "en-US",
                               "headless": False,
                               "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:141.0) "
                                     "Gecko/20100101 Firefox/141.0"})
        if "document.title" in expression and "JSON.stringify" in expression:
            return json.dumps(tab["title"])
        if "1+1" in expression:
            return 2
        if "longString" in expression:
            return self.server.long_text
        if "JSON.stringify" in expression:
            return json.dumps({"echo": expression})
        return None

    def _grip(self, value) -> dict:
        """A value grip; big strings become long strings, as Firefox sends them."""
        if value is None:
            return {"type": "undefined"}
        if isinstance(value, bool):
            return {"type": "boolean", "value": value}
        if isinstance(value, (int, float)):
            return {"type": "number", "value": value}
        if isinstance(value, str) and len(value) > LONG_THRESHOLD:
            self.long_seq += 1
            actor = f"{self.prefix}longString{self.long_seq}"
            self.long_strings[actor] = value
            return {"type": "longString", "actor": actor, "length": len(value),
                    "initial": value[:LONG_THRESHOLD]}
        return {"type": "string", "value": value}


class _Recorder:
    """A socket that records what the client sends.

    Round 9 needs to prove a negative — that no HTTP request is ever spoken to a
    DevTools socket ("CDP error: URLError http://localhost:9224/json/list") — and
    the only honest way to test that is to keep the bytes the client sent.
    """

    def __init__(self, conn, sink, lock) -> None:
        self._conn, self._sink, self._lock = conn, sink, lock

    def recv(self, size):
        chunk = self._conn.recv(size)
        with self._lock:
            self._sink.append(chunk)
        return chunk

    def sendall(self, data):
        return self._conn.sendall(data)


class RdpStubServer:
    """A fake Firefox on 127.0.0.1:ephemeral — start/close from any test."""

    def __init__(self, tabs=None, greet: bool = True, byte_prefixed: bool = False,
                 async_eval: bool = True, legacy_attach: bool = False, stale_evals: int = 0,
                 expire_hard: bool = False, silent: bool = False, click_found: bool = True):
        self.tabs = [dict(t) for t in (tabs if tabs is not None else STUB_TABS)]
        self.greet, self.byte_prefixed, self.async_eval = greet, byte_prefixed, async_eval
        self.legacy_attach, self.stale_evals, self.expire_hard = legacy_attach, stale_evals, expire_hard
        self.silent, self.click_found = silent, click_found
        self.long_text = "Z" * 80
        self.received: list = []
        self.raw: list = []          # every byte the client sent (round 9)
        self.connections = 0
        self._lock = threading.Lock()
        stub = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                stub._serve(self.request)

        self._server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._server.allow_reuse_address = True
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        kwargs={"poll_interval": 0.05}, daemon=True)
        self._thread.start()

    def _serve(self, conn):
        with self._lock:
            self.connections += 1
            conn_no = self.connections
        session = _Session(self, conn_no)
        watched = _Recorder(conn, self.raw, self._lock)
        try:
            if self.greet and not self.silent:
                conn.sendall(frame(session.greeting(), self.byte_prefixed))
            if self.silent:
                while watched.recv(4096):
                    pass
                return
            framer = ClientFramer(watched)
            while True:
                try:
                    packet = framer.packet()
                except ValueError:
                    return     # garbage on an RDP port (a CDP probe, say) — dropped, like Firefox does
                if packet is None:
                    return
                with self._lock:
                    self.received.append(packet)
                for reply in session.handle(packet):
                    conn.sendall(frame(reply, self.byte_prefixed))
        except OSError:
            return

    def close(self):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    def raw_text(self) -> str:
        """Everything the client sent us this far, as text (never-HTTP proof)."""
        with self._lock:
            chunks = list(self.raw)
        return b"".join(c for c in chunks if c).decode("utf-8", errors="ignore")

    def was_sent(self, kind: str) -> bool:
        """Did the client ask for this packet type?"""
        return any(str(p.get("type")) == kind for p in self.received)
