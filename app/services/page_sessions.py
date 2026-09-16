"""Own exact-URL page connections for a batch; imports browser, never Qt UI."""

from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from app.browser.cdp_arena import CDPArenaController
from app.browser.cdp_client import CDPClient


def exact_url(url):
    """Normalize origin casing and fragments, preserving conversation/query case."""
    parts = urlsplit(url.strip())
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(),
                      parts.path or '/', parts.query, ''))


@dataclass
class PageSession:
    row: object
    controller: object
    image: object = None


class PageSessions:
    """Dedicated sockets and one worker per actual Chrome target ID."""

    def __init__(self, bridge, client_factory=CDPClient):
        self.bridge = bridge
        self.client_factory = client_factory
        self.clients = []

    def status(self, row, status, error=None):
        if (row.last_status, row.error) == (status, error):
            return
        row.last_status, row.error = status, error
        self.bridge._log(f'Page {row.url}: {status}' + (f' — {error}' if error else ''))
        self.bridge._save_arena()
        self.bridge._emit_arena_state()

    async def open(self):
        tabs = await self.bridge.cdp.fetch_tabs()
        used = set()
        pages = []
        for row in self.bridge._get_enabled_urls():
            tab = next((t for t in tabs if exact_url(t.url) == exact_url(row.url)), None)
            if tab is None:
                self.status(row, 'unavailable', 'No exact matching open Chrome tab')
                continue
            if tab.id in used:
                self.status(row, 'unavailable', 'Duplicate Chrome target already scheduled')
                continue
            used.add(tab.id)
            page = await self.connect(row, tab)
            if page:
                pages.append(page)
        return pages

    async def connect(self, row, tab):
        self.status(row, 'checking')
        client = self.client_factory(*self.bridge.cdp.get_host_port())
        self.clients.append(client)
        try:
            if not await client.connect(tab.ws_url):
                raise RuntimeError('CDP connection failed')
            controller = CDPArenaController(client, log_callback=self.bridge._log)
            return PageSession(row, controller)
        except Exception as exc:
            self.status(row, 'unavailable', str(exc))
            return None

    async def close(self):
        for client in self.clients:
            try:
                await client.disconnect()
            except Exception as exc:
                self.bridge._log(f'Page disconnect failed: {exc}', 'warn')
        self.clients.clear()
