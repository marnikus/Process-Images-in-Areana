"""Cooperative free-page queue and batch lifecycle; UI is a callback port.

One worker owns each page through job execution AND observed browser completion.
Only the coordinator owns global run state. No worker swaps bridge.cdp.
"""

import asyncio
from collections import deque

from app.browser.page_availability import observe_availability
from app.services.page_sessions import PageSessions


class PageDispatcher:
    """Workers share an event-loop-local deque; claims contain no await."""

    def __init__(self, bridge, sessions, poll_interval=1.0):
        self.bridge = bridge
        self.sessions = sessions
        self.poll_interval = poll_interval
        self.pending = deque(bridge._get_selected_images())

    def stopping(self):
        return self.bridge._cancel_requested or self.bridge._stop_after

    async def wait_steady(self, page):
        idle_checks = 0
        while not self.bridge._cancel_requested:
            if page.image is None and (self.bridge._stop_after or not self.pending):
                return False
            status = await observe_availability(page.controller)
            idle_checks = idle_checks + 1 if status == 'steady' else 0
            if idle_checks >= 2:
                self.sessions.status(page.row, 'steady')
                return True
            self.sessions.status(page.row, 'checking' if status == 'steady' else status)
            await asyncio.sleep(self.poll_interval)
        return False

    async def worker(self, page):
        try:
            await self.process_queue(page)
        except asyncio.CancelledError:
            self.fail_active_image(page, 'Cancelled by user')
            self.sessions.status(page.row, 'unchecked', 'Cancelled; browser may still be processing')
            raise
        except Exception as exc:
            self.fail_active_image(page, str(exc))
            self.sessions.status(page.row, 'unavailable', str(exc))
            self.bridge._log(f'Page worker stopped: {page.row.url}: {exc}', 'error')

    def fail_active_image(self, page, error):
        if page.image is None or page.image.status != 'processing':
            return
        page.image.status, page.image.error = 'failed', error
        self.bridge.state.recalculate_progress()
        self.bridge._save_arena()

    async def process_queue(self, page):
        while self.pending and not self.stopping():
            if not await self.wait_steady(page):
                return
            if self.stopping():
                return
            if self.bridge._pause_requested:
                await asyncio.sleep(self.poll_interval)
                continue
            if not self.pending:
                return
            page.image = self.pending.popleft()
            self.sessions.status(page.row, 'busy')
            await self.bridge._do_run_batch(page)
            if not await self.wait_steady(page):
                return
            page.image = None

    async def run(self, pages):
        if not pages:
            self.bridge._log('No connected eligible pages; pending images unchanged', 'warn')
            return
        tasks = [asyncio.create_task(self.worker(page)) for page in pages]
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        self.bridge._log(f'Batch ended; {len(self.pending)} images remain unassigned',
                         'warn' if self.pending else 'info')


async def run_page_batch(bridge):
    """Own lifetime so a worker finishing never makes other workers look idle.

    ideal-size: resource lifetime uses one try/finally for all exit paths.
    """
    sessions = PageSessions(bridge)
    try:
        dispatcher = PageDispatcher(bridge, sessions)
        if not dispatcher.pending:
            bridge._log('No selected pending images', 'warn')
            return
        pages = await sessions.open()
        await dispatcher.run(pages)
    except asyncio.CancelledError:
        bridge._log('Batch cancelled; page readiness will be checked again next run', 'warn')
        raise
    except Exception as exc:
        bridge._log(f'Batch failed: {exc}', 'error')
    finally:
        await sessions.close()
        bridge._run_state = 'idle'
        bridge._emit_arena_state()
