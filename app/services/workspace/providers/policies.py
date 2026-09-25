"""Policy providers — domains that appear in every manifest but are never exported.

`captcha_keys` is a secret (RULE 20 / I-29: raw keys never leave the
machine; redacted presence metadata only — encrypted export is a separate
opt-in capability, explicitly out of scope). `captcha_recordings` is
page-derived evidence, default-excluded (opt-in copy is a documented
future capability). Both refuse apply with a precise, actionable error.
"""

from __future__ import annotations

from app.persistence.workspace.errors import WorkspaceError
from app.services.workspace.provider import ApplyOutcome, CaptureResult, StateProvider

KEYS_EXCLUDED = "secret: redacted presence metadata only — raw keys never leave the machine (RULE 20)"
RECORDINGS_EXCLUDED = ("default-excluded: page-derived captcha evidence; an opt-in copy is a "
                       "documented future capability (design §D.3)")
KEYS_REAPPLY = "Re-enter the API key in the Captcha window (keys are never restored from a workspace)."


def _masked_presence(bridge) -> dict:
    """{provider_id: {present, masked}} — the same masking the Captcha window shows."""
    from app.services.captcha.key_store import CaptchaKeyStore
    settings = CaptchaKeyStore(str(getattr(bridge.config, "dir", "config"))).load()
    presence = {}
    for provider_id, key in (settings.keys or {}).items():
        presence[provider_id] = {"present": bool(key),
                                 "masked": CaptchaKeyStore.mask(key) if key else None}
    return {"providers": presence, "solve_timeout_sec": settings.solve_timeout_sec}


class CaptchaKeysProvider(StateProvider):
    """Captcha solver keys — presence metadata only, never the secrets themselves."""

    domain_id = "captcha_keys"
    display_name = "Captcha Solver Keys"
    native_rel_path = ""
    schema_version = "1"
    sensitivity = "secret"

    def capture(self, bridge) -> CaptureResult:
        return CaptureResult(ok=True, doc=_masked_presence(bridge), excluded=True,
                             excluded_reason=KEYS_EXCLUDED)

    def apply(self, bridge, doc) -> ApplyOutcome:
        raise WorkspaceError(self.domain_id, "apply", KEYS_REAPPLY)


class RecordingsProvider(StateProvider):
    """Captcha session recordings — excluded by default (bounded local evidence)."""

    domain_id = "captcha_recordings"
    display_name = "Captcha Session Recordings"
    native_rel_path = ""
    schema_version = "1"
    sensitivity = "personal"

    def capture(self, bridge) -> CaptureResult:
        return CaptureResult(ok=True, doc={"root": "config/captcha_recordings/"}, excluded=True,
                             excluded_reason=RECORDINGS_EXCLUDED)

    def apply(self, bridge, doc) -> ApplyOutcome:
        raise WorkspaceError(self.domain_id, "apply",
                             "recordings are excluded from workspace snapshots by policy")
