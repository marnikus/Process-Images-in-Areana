"""2Captcha API client — payload shape, status mapping, error classification.

RULE 8: real client code against a fake aiohttp transport (no network).
Key hygiene (RULE 20): clientKey only in the POST body, never in a URL.
"""

import pytest

import app.services.captcha.api_client as api_mod
from app.services.captcha.api_client import ApiError, Captcha2Client, error_reason


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    async def json(self, content_type=None):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class FakeSession:
    def __init__(self, payloads):
        self._queue = list(payloads)
        self.posts = []  # (url, body)
        self.closed = False
        self.timeout = None

    def post(self, url, json=None):
        self.posts.append((url, json))
        payload = self._queue.pop(0) if self._queue else {}
        return FakeResponse(payload)

    async def close(self):
        self.closed = True


def install_fake(monkeypatch, payloads):
    sessions = []

    def fake_session(timeout=None):
        s = FakeSession(payloads)
        s.timeout = timeout
        sessions.append(s)
        return s

    monkeypatch.setattr(api_mod.aiohttp, "ClientSession", fake_session)
    return sessions


@pytest.mark.unit
def test_error_reason_mapping():
    assert error_reason(1) == "unavailable"
    assert error_reason(2) == "bad_key"
    assert error_reason(3) == "no_credit"
    assert error_reason(16) == "not_found"
    assert error_reason(99) == "task_error"
    assert error_reason("x") == "task_error"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_task_sends_key_in_body_not_url(monkeypatch):
    sessions = install_fake(monkeypatch, [{"errorId": 0, "taskId": 12345}])
    client = Captcha2Client("SECRETKEY")
    task_id = await client.create_task(
        {"type": "RecaptchaV2EnterpriseTaskProxyless",
         "websiteURL": "https://arena.ai/image/direct",
         "websiteKey": "6Lsitekey123"})
    await client.aclose()
    assert task_id == "12345"
    url, body = sessions[0].posts[0]
    assert url == f"{api_mod.API_BASE}/createTask"  # no query string, no key in URL
    assert "SECRETKEY" not in url
    assert body["clientKey"] == "SECRETKEY"
    assert body["task"]["type"] == "RecaptchaV2EnterpriseTaskProxyless"
    assert sessions[0].closed  # aclose closed the session


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_task_without_taskid_raises(monkeypatch):
    install_fake(monkeypatch, [{"errorId": 0}])
    client = Captcha2Client("K")
    with pytest.raises(ApiError) as e:
        await client.create_task({"type": "RecaptchaV2TaskProxyless"})
    assert e.value.reason == "task_error"
    await client.aclose()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_error_id_maps_to_reason(monkeypatch):
    install_fake(monkeypatch, [{"errorId": 3, "errorCode": "NOT_ENOUGH_CREDIT"}])
    client = Captcha2Client("K")
    with pytest.raises(ApiError) as e:
        await client.get_result("99")
    assert e.value.reason == "no_credit"
    assert e.value.error_id == 3
    await client.aclose()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_bad_key_detected(monkeypatch):
    install_fake(monkeypatch, [{"errorId": 2, "errorCode": "KEY_DOESNT_EXIST"}])
    client = Captcha2Client("WRONG")
    with pytest.raises(ApiError) as e:
        await client.get_balance()
    assert e.value.reason == "bad_key"
    await client.aclose()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_network_error_maps_to_network(monkeypatch):
    install_fake(monkeypatch, [api_mod.aiohttp.ClientError("boom")])
    client = Captcha2Client("K")
    with pytest.raises(ApiError) as e:
        await client.get_result("1")
    assert e.value.reason == "network"
    await client.aclose()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_non_json_response_maps_to_network(monkeypatch):
    install_fake(monkeypatch, ["<html>502</html>"])
    client = Captcha2Client("K")
    with pytest.raises(ApiError) as e:
        await client.get_result("1")
    assert e.value.reason == "network"
    await client.aclose()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_result_ready_returns_solution(monkeypatch):
    install_fake(monkeypatch, [{"errorId": 0, "status": "ready",
                                "solution": {"gRecaptchaResponse": "TOKEN123"}}])
    client = Captcha2Client("K")
    res = await client.get_result("7")
    await client.aclose()
    assert res["status"] == "ready"
    assert res["solution"]["gRecaptchaResponse"] == "TOKEN123"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_balance_parses_float(monkeypatch):
    install_fake(monkeypatch, [{"errorId": 0, "balance": 12.34}])
    client = Captcha2Client("K")
    assert await client.get_balance() == 12.34
    await client.aclose()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_balance_bad_value_is_zero(monkeypatch):
    install_fake(monkeypatch, [{"errorId": 0, "balance": "n/a"}])
    client = Captcha2Client("K")
    assert await client.get_balance() == 0.0
    await client.aclose()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_task_frees_credit_and_not_found_is_ok(monkeypatch):
    install_fake(monkeypatch, [
        {"errorId": 0},
        {"errorId": 16, "errorCode": "TASK_NOT_FOUND"},
    ])
    client = Captcha2Client("K")
    assert await client.delete_task("1") is True
    assert await client.delete_task("1") is True  # already gone = fine
    await client.aclose()
