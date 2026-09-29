from __future__ import annotations
import logging

log = logging.getLogger("arena")

def _note_eval_error(transport, kind: str, text: str) -> None:
    transport.last_error_kind = kind
    transport.last_error = text[:300]
    low = text.lower()
    if kind == "transport" and ("not connected" in low or "disconnected" in low or "connection" in low):
        log.debug(f"evaluate {kind} error: {transport.last_error}")
    else:
        log.warning(f"evaluate {kind} error: {transport.last_error}")

def _decode_reply(r) -> tuple:
    reply = r if isinstance(r, dict) else {}
    err = reply.get("error")
    if err:
        return "protocol", _protocol_text(err), None
    res = reply.get("result", {}) or {}
    if res.get("exceptionDetails"):
        return "js", _exception_text(res.get("exceptionDetails")), None
    return "", "", res.get("result", {}).get("value")

def _exc_text(exc: BaseException) -> str:
    text = str(exc)
    name = type(exc).__name__
    return f"{name}: {text}" if text else name

def _protocol_text(err) -> str:
    if isinstance(err, dict):
        return str(err.get("message") or err)
    return str(err)

def _exception_text(details) -> str:
    try:
        exc = details.get("exception") or {}
        return str(exc.get("description") or details.get("text") or exc.get("value") or details)
    except Exception:
        return str(details)
