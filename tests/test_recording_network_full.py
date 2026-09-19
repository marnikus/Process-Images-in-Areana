"""D5 mutation triage: NetworkCollector, branch-complete.

Targets _response (39), _body (39), _request (34), _record (17),
on_event (3), close (2), __init__ (2).
"""

import asyncio
import base64

from app.services.captcha_recording.network import NetworkCollector


class FakeCDP:
    def __init__(self, reply=None, raises=None):
        self.reply = reply
        self.raises = raises
        self.calls = []

    async def send(self, method, params, timeout=5):
        self.calls.append((method, params, timeout))
        if self.raises:
            raise self.raises
        return self.reply or {}


def collector(cdp=None, body_limit=1000):
    calls = []

    async def sink(kind, payload, network):
        calls.append((kind, payload, network))

    cdp = cdp or FakeCDP()
    truncated = []
    c = NetworkCollector(cdp, sink, body_limit, truncated.append)
    return c, calls, truncated


def ev(method, **params):
    return {"method": method, "params": params}


class TestOnEventAndClose:
    def test_ignores_non_network(self):
        c, calls, _ = collector()
        c.on_event({"method": "Page.loadEventFired", "params": {}})
        asyncio.run(c.drain())
        assert calls == []

    def test_queues_network_events(self):
        c, calls, _ = collector()
        c.on_event(ev("Network.requestWillBeSent", requestId="1", type="Fetch",
                      request={"url": "https://x.test", "method": "GET"}))
        asyncio.run(c.drain())
        assert calls[0][0] == "network_request"

    def test_closed_counts_dropped(self):
        c, _, _ = collector()
        c.close()
        c.on_event(ev("Network.requestWillBeSent", requestId="1"))
        c.on_event({"method": "Page.x"})  # non-network: not counted
        assert c.dropped_events == 1

    def test_close_counts_undrained(self):
        c, _, _ = collector()
        c.on_event(ev("Network.requestWillBeSent", requestId="1"))
        c.on_event(ev("Network.requestWillBeSent", requestId="2"))
        c.close()
        assert c.dropped_events == 2
        asyncio.run(c.drain())  # empty queue

    def test_double_close_no_double_count(self):
        c, _, _ = collector()
        c.on_event(ev("Network.requestWillBeSent", requestId="1"))
        c.close()
        c.close()
        assert c.dropped_events == 1


class TestRequest:
    def test_payload(self):
        c, calls, _ = collector()
        c.on_event(ev("Network.requestWillBeSent", requestId="r1", type="XHR",
                      request={"url": "https://x.test/api?token=SECRET", "method": "POST"}))
        asyncio.run(c.drain())
        kind, payload, network = calls[0]
        assert kind == "network_request"
        assert network is True
        assert payload["request_id"] == "r1"
        assert payload["url"] == "https://x.test/api"
        assert payload["method"] == "POST"
        assert payload["resource_type"] == "XHR"

    def test_missing_request(self):
        c, calls, _ = collector()
        c.on_event(ev("Network.requestWillBeSent", requestId="r1"))
        asyncio.run(c.drain())
        kind, payload, _ = calls[0]
        assert payload["url"] == ""
        assert payload["method"] == ""
        assert payload["resource_type"] == ""


class TestResponse:
    def test_payload_and_registry(self):
        c, calls, _ = collector()
        c.on_event(ev("Network.responseReceived", requestId="r1", type="Fetch",
                      response={"url": "https://x.test/a?k=v", "status": 200,
                                "mimeType": "application/json", "fromDiskCache": True}))
        asyncio.run(c.drain())
        kind, payload, network = calls[0]
        assert kind == "network_response"
        assert network is True
        assert payload["url"] == "https://x.test/a"
        assert payload["status"] == 200
        assert payload["mime"] == "application/json"
        assert payload["from_cache"] is True
        assert c.responses["r1"] is payload

    def test_missing_response(self):
        c, calls, _ = collector()
        c.on_event(ev("Network.responseReceived", requestId="r1"))
        asyncio.run(c.drain())
        kind, payload, _ = calls[0]
        assert payload["status"] is None
        assert payload["mime"] == ""
        assert payload["from_cache"] is False


class TestFailure:
    def test_payload(self):
        c, calls, _ = collector()
        c.on_event(ev("Network.loadingFailed", requestId="r1",
                      errorText="net::ERR_FAILED long " + "T" * 90,
                      canceled=True, type="Fetch"))
        asyncio.run(c.drain())
        kind, payload, network = calls[0]
        assert kind == "network_failure"
        assert network is True
        assert "net::ERR_FAILED" in payload["error"]
        assert "T" * 90 not in payload["error"]
        assert payload["canceled"] is True
        assert payload["resource_type"] == "Fetch"

    def test_missing_params(self):
        c, calls, _ = collector()
        c.on_event(ev("Network.loadingFailed", requestId="r1"))
        asyncio.run(c.drain())
        kind, payload, _ = calls[0]
        assert payload["error"] == ""
        assert payload["canceled"] is False


class TestBody:
    def test_no_response_meta(self):
        c, calls, _ = collector()
        c.on_event(ev("Network.loadingFinished", requestId="ghost"))
        asyncio.run(c.drain())
        assert calls == []

    def test_non_textual_skipped(self):
        c, calls, _ = collector()
        c.on_event(ev("Network.responseReceived", requestId="r1",
                      response={"url": "u", "status": 200, "mimeType": "image/png"}))
        c.on_event(ev("Network.loadingFinished", requestId="r1"))
        asyncio.run(c.drain())
        assert [k for k, _, _ in calls] == ["network_response"]
        assert "r1" not in c.responses

    def test_json_body(self):
        cdp = FakeCDP(reply={"result": {"body": '{"ok": true}', "base64Encoded": False}})
        c, calls, _ = collector(cdp=cdp)
        c.on_event(ev("Network.responseReceived", requestId="r1",
                      response={"url": "u", "status": 200, "mimeType": "application/json"}))
        c.on_event(ev("Network.loadingFinished", requestId="r1"))
        asyncio.run(c.drain())
        kinds = [k for k, _, _ in calls]
        assert kinds == ["network_response", "response_body"]
        payload = calls[1][1]
        assert payload["body"] == '{"ok": true}'
        assert payload["truncated"] is False
        assert cdp.calls[0][0] == "Network.getResponseBody"
        assert cdp.calls[0][1] == {"requestId": "r1"}
        assert cdp.calls[0][2] == 5

    def test_base64_body(self):
        raw = "hello world".encode()
        cdp = FakeCDP(reply={"result": {"body": base64.b64encode(raw).decode(),
                                        "base64Encoded": True}})
        c, calls, _ = collector(cdp=cdp)
        c.on_event(ev("Network.responseReceived", requestId="r1",
                      response={"url": "u", "status": 200, "mimeType": "text/html"}))
        c.on_event(ev("Network.loadingFinished", requestId="r1"))
        asyncio.run(c.drain())
        assert calls[1][1]["body"] == "hello world"

    def test_truncated_marks(self):
        cdp = FakeCDP(reply={"result": {"body": "x" * 50, "base64Encoded": False}})
        c, calls, truncated = collector(cdp=cdp, body_limit=10)
        c.on_event(ev("Network.responseReceived", requestId="r1",
                      response={"url": "u", "status": 200, "mimeType": "text/plain"}))
        c.on_event(ev("Network.loadingFinished", requestId="r1"))
        asyncio.run(c.drain())
        payload = calls[1][1]
        assert payload["truncated"] is True
        assert len(payload["body"]) == 10
        assert truncated == ["response_bodies"]

    def test_send_error_warns(self):
        cdp = FakeCDP(raises=OSError("conn reset"))
        c, calls, _ = collector(cdp=cdp)
        c.on_event(ev("Network.responseReceived", requestId="r1",
                      response={"url": "u", "status": 200, "mimeType": "text/plain"}))
        c.on_event(ev("Network.loadingFinished", requestId="r1"))
        asyncio.run(c.drain())
        kind, payload, _ = calls[1]
        assert kind == "warning"
        assert "response body unavailable: OSError" == payload["message"]

    def test_empty_result(self):
        cdp = FakeCDP(reply={})
        c, calls, _ = collector(cdp=cdp)
        c.on_event(ev("Network.responseReceived", requestId="r1",
                      response={"url": "u", "status": 200, "mimeType": "text/plain"}))
        c.on_event(ev("Network.loadingFinished", requestId="r1"))
        asyncio.run(c.drain())
        payload = calls[1][1]
        assert payload["body"] == ""
        assert payload["truncated"] is False


class TestRecordDispatch:
    def test_unknown_method_ignored(self):
        c, calls, _ = collector()
        c.on_event(ev("Network.foo", requestId="1"))
        asyncio.run(c.drain())
        assert calls == []

    def test_missing_method_ignored(self):
        c, calls, _ = collector()
        c.on_event({"params": {}})
        asyncio.run(c.drain())
        assert calls == []

    def test_params_default(self):
        c, calls, _ = collector()
        c.on_event({"method": "Network.requestWillBeSent"})
        asyncio.run(c.drain())
        assert calls[0][1]["request_id"] == ""
