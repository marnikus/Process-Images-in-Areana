"""Test CDP websocket connection directly — helps debug Chrome remote debugging.
Run: python test_cdp_connect.py --port 9223 --host 127.0.0.1
"""
import argparse
import json
import socket
import urllib.request
import sys

def fetch_tabs(host, port):
    url = f"http://{host}:{port}/json/list"
    print(f"Fetching {url} ...")
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            data = json.loads(r.read().decode())
            print(f"Found {len(data)} tabs:")
            for t in data[:5]:
                print(f"  - id={t.get('id')} title={t.get('title')[:60]} url={t.get('url')} ws={t.get('webSocketDebuggerUrl')}")
            return data
    except Exception as e:
        print(f"Failed to fetch {url}: {e}")
        return []

async def try_connect(ws_url):
    import websockets
    print(f"\nTrying websockets.connect to {ws_url[:120]} ...")
    try:
        ws = await websockets.connect(
            ws_url,
            max_size=50*1024*1024,
            open_timeout=10,
            close_timeout=5,
            ping_interval=None,
            ping_timeout=None,
        )
        print(f"✅ Connected to {ws_url[:80]}")
        # Try to send a simple command
        import json
        await ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": "1+1"}}))
        resp = await ws.recv()
        print(f"Received: {resp[:200]}")
        await ws.close()
        print("Closed OK")
        return True
    except Exception as e:
        import traceback
        print(f"❌ Connect failed for {ws_url}: {e}")
        traceback.print_exc()
        return False

async def main_async(host, port):
    tabs = fetch_tabs(host, port)
    if not tabs:
        print("No tabs, trying localhost fallback")
        if host != "localhost":
            tabs = fetch_tabs("localhost", port)
        if not tabs and host != "127.0.0.1":
            tabs = fetch_tabs("127.0.0.1", port)
    if not tabs:
        print("No tabs found — is Chrome running with --remote-debugging-port?")
        return
    # Try each tab's ws_url and variants
    import re
    for tab in tabs[:3]:
        ws_url = tab.get("webSocketDebuggerUrl")
        if not ws_url:
            continue
        print(f"\n=== Testing tab {tab.get('id')} {tab.get('title')[:50]} ===")
        # Original
        await try_connect(ws_url)
        # Normalized to host
        norm = re.sub(r'ws://[^:/]+(?::\d+)?/', f'ws://{host}:{port}/', ws_url)
        if norm != ws_url:
            await try_connect(norm)
        # localhost variant
        if "127.0.0.1" in ws_url:
            await try_connect(ws_url.replace("127.0.0.1", "localhost"))
        if "localhost" in ws_url:
            await try_connect(ws_url.replace("localhost", "127.0.0.1"))
        # Constructed
        m = re.search(r'/devtools/page/([^/]+)$', ws_url)
        if m:
            tid = m.group(1)
            for h in [host, "127.0.0.1", "localhost"]:
                await try_connect(f"ws://{h}:{port}/devtools/page/{tid}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9222)
    args = parser.parse_args()
    # Check port open
    print(f"Checking if port {args.port} open on {args.host} ...")
    try:
        with socket.create_connection((args.host, args.port), timeout=2):
            print(f"Port {args.port} open on {args.host}")
    except Exception as e:
        print(f"Port {args.port} NOT open on {args.host}: {e}")
    # Try async
    try:
        import asyncio
        asyncio.run(main_async(args.host, args.port))
    except ImportError as e:
        print(f"Missing dependency: {e} — pip install websockets aiohttp")
        sys.exit(1)

if __name__ == "__main__":
    main()
