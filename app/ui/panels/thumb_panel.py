"""Thumb Panel — Bridge panel mixin (W1.6 split)."""

from __future__ import annotations

import json
from pathlib import Path
try:
    from PySide6.QtCore import QObject, Signal, Slot
    _qt_core = True
except ImportError:
    _qt_core = False

if not _qt_core:  # headless shim (no PySide6) — exercised by tests/test_qt_shim_fallback.py
    class QObject:
        def __init__(self, *qt_shim_args, **qt_shim_kwargs): pass

    def Signal(*sig_shim_args, **sig_shim_kwargs):
        class _Sig:
            def emit(self, *emit_shim_args, **emit_shim_kwargs): pass
            def connect(self, *connect_shim_args, **connect_shim_kwargs): pass
        return _Sig()

    def Slot(*slot_shim_args, **slot_shim_kwargs):
        def deco(fn): return fn
        return deco

try:
    from PySide6.QtWidgets import QFileDialog
except ImportError:
    QFileDialog = None




class ThumbCachePanel:

    @Slot(str, result=str)
    def get_image_thumbnail(self, img_id: str):
        """Return base64 thumbnail — non-blocking to avoid mouse freeze.

        Cache hit returns immediately; miss schedules a background thread
        and returns pending with file:// fallback, then emits thumbnail_ready.
        """
        try:
            cached = self._thumb_cached(img_id)
            if cached:
                return cached
            p, err = self._thumb_target_path(img_id)
            if err:
                return err
            if img_id in self._thumb_in_progress:
                return self._thumb_pending(img_id, p)
            if self._thumb_executor:
                return self._thumb_run_bg(img_id, p)
            return self._thumb_run_sync(img_id, p)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    def _thumb_cached(self, img_id: str):
        """Cached data_url json for img_id, else None."""
        if img_id in self._thumb_cache:
            return json.dumps({"ok": True, "id": img_id, "data_url": self._thumb_cache[img_id], "cached": True}, ensure_ascii=False)
        return None

    def _thumb_target_path(self, img_id: str):
        """(Path, None) for an existing image file, else (None, error json)."""
        target = None
        for im in self.state.images:
            if im.id == img_id:
                target = im
                break
        if not target:
            return None, json.dumps({"ok": False, "error": "not found"})
        p = Path(target.absolute_path)
        if not p.exists():
            return None, json.dumps({"ok": False, "error": "file not exists"})
        return p, None

    def _thumb_pending(self, img_id: str, p):
        """pending json with file:// fallback while a thumbnail renders."""
        return json.dumps({"ok": False, "pending": True, "id": img_id, "fallback_url": f"file://{p}"}, ensure_ascii=False)

    def _thumb_gen(self, img_id: str, p):
        """Generate one thumbnail result dict (background-safe, pure service)."""
        from .services.thumbnail_service import generate_thumbnail_data_url
        res = generate_thumbnail_data_url(p, size=96, quality=80)
        res["id"] = img_id
        return res

    def _thumb_on_done(self, img_id: str, fut):
        """Executor callback: cache + emit thumbnail_ready, always clear flag."""
        try:
            res = fut.result()
            if res.get("ok") and res.get("data_url"):
                self._thumb_cache[img_id] = res["data_url"]
                try:
                    payload = json.dumps(res, ensure_ascii=False)
                    self.thumbnail_ready.emit(img_id, payload)
                except Exception:
                    pass
            self._thumb_in_progress.discard(img_id)
        except Exception:
            self._thumb_in_progress.discard(img_id)

    def _thumb_run_bg(self, img_id: str, p):
        """Submit to executor; on submit failure fall back to inline sync."""
        self._thumb_in_progress.add(img_id)
        try:
            fut = self._thumb_executor.submit(self._thumb_gen, img_id, p)
            fut.add_done_callback(lambda f: self._thumb_on_done(img_id, f))
        except Exception:
            self._thumb_in_progress.discard(img_id)
            return self._thumb_run_sync(img_id, p)
        return self._thumb_pending(img_id, p)

    def _thumb_run_sync(self, img_id: str, p):
        """No executor: render inline, cache, return the result json."""
        res = self._thumb_gen(img_id, p)
        if res.get("ok") and res.get("data_url"):
            self._thumb_cache[img_id] = res["data_url"]
        return json.dumps(res, ensure_ascii=False)


class ClipboardPanel:

    @Slot(str, result=str)
    def reveal_in_explorer(self, path_str: str):
        """Open file in Explorer/Finder — btn to open this file in explorer (not link)."""
        try:
            p, err = self._reveal_target(path_str)
            if err:
                return err
            self._open_in_file_manager(p)
            self._log(f"📁 Revealed in Explorer: {path_str}", "info")
            return json.dumps({"ok": True})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    def _reveal_target(self, path_str: str):
        """(Path, None) for an existing path (parent fallback), else (None, err)."""
        p = Path(path_str)
        if not p.exists():
            if p.parent.exists():  # parent exists for output not yet created
                p = p.parent
            else:
                return None, json.dumps({"ok": False, "error": f"Path does not exist: {path_str}"})
        return p, None

    @staticmethod
    def _open_in_file_manager(p):
        """Platform-specific reveal (Windows explorer / macOS open -R / xdg-open)."""
        import platform, subprocess, os
        system = platform.system()
        if system == "Windows":
            if p.is_file():
                # explorer /select,"path" — need to handle spaces
                subprocess.Popen(f'explorer /select,"{p}"')
            else:
                os.startfile(str(p))  # type: ignore
        elif system == "Darwin":
            if p.is_file():
                subprocess.Popen(["open", "-R", str(p)])
            else:
                subprocess.Popen(["open", str(p)])
        else:
            # Linux: xdg-open parent or file
            if p.is_file():
                subprocess.Popen(["xdg-open", str(p.parent)])
            else:
                subprocess.Popen(["xdg-open", str(p)])
    @Slot(str, result=str)
    def copy_path_to_clipboard(self, path_str: str):
        """Copy file path to clipboard — second option copy link to file. Fixed: was not copying."""
        try:
            res = self._copy_qt(path_str)
            if res:
                return res
            return self._copy_subprocess(path_str)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e), "path": path_str})

    def _copy_qt(self, path_str: str):
        """Qt clipboard copy (most reliable in QWebEngine); None to fall through."""
        clipboard = self._qt_clipboard()
        if clipboard is None:
            return None
        try:
            from PySide6.QtGui import QClipboard
            # Windows path like F:\\Creative Cloud Files\\... with spaces must be copied verbatim
            clipboard.setText(path_str, mode=QClipboard.Clipboard)
            try:
                clipboard.setText(path_str, mode=QClipboard.Selection)
            except Exception:
                pass
            self._log(f"📋 Copied to clipboard: {path_str}", "info")
            return json.dumps({"ok": True, "path": path_str, "method": "qt"})
        except Exception as e_qt:
            # Fall through to subprocess fallback
            self._log(f"Qt clipboard failed {e_qt}, trying subprocess", "warn")
            return None

    @staticmethod
    def _qt_clipboard():
        """QApplication/QGuiApplication clipboard, else None."""
        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app is not None:
                return app.clipboard()
        except Exception:
            pass
        try:
            from PySide6.QtGui import QGuiApplication
            app2 = QGuiApplication.instance()
            if app2 is not None:
                return app2.clipboard()
        except Exception:
            pass
        return None

    def _copy_subprocess(self, path_str: str):
        """OS clipboard tool fallback (clip/powershell/pbcopy/xclip/xsel)."""
        import subprocess, platform
        system = platform.system()
        if system == "Windows":
            return self._copy_windows(path_str)
        if system == "Darwin":
            subprocess.run("pbcopy", input=path_str.encode("utf-8"), check=True)
            self._log(f"📋 Copied via pbcopy: {path_str}", "info")
            return json.dumps({"ok": True, "path": path_str, "fallback": "pbcopy"})
        return self._copy_linux(path_str)

    def _copy_windows(self, path_str: str):
        """Windows fallback: clip, then powershell Set-Clipboard."""
        import subprocess
        try:
            subprocess.run("clip", input=path_str.encode("utf-8"), check=True, shell=True)
            self._log(f"📋 Copied via clip: {path_str}", "info")
            return json.dumps({"ok": True, "path": path_str, "fallback": "clip"})
        except Exception:
            return self._copy_powershell(path_str)

    def _copy_powershell(self, path_str: str):
        """powershell Set-Clipboard — handles spaces and Unicode better."""
        import subprocess
        try:
            ps_escaped = path_str.replace("'", "''")  # escape single quotes
            ps_cmd = f"Set-Clipboard -Value '{ps_escaped}'"
            subprocess.run(["powershell", "-Command", ps_cmd], check=True)
            self._log(f"📋 Copied via powershell: {path_str}", "info")
            return json.dumps({"ok": True, "path": path_str, "fallback": "powershell"})
        except Exception as e_ps:
            return json.dumps({"ok": False, "error": f"clip/powershell failed {e_ps}", "path": path_str})

    def _copy_linux(self, path_str: str):
        """Linux fallback: xclip, then xsel."""
        import subprocess
        try:
            subprocess.run(["xclip", "-selection", "clipboard"], input=path_str.encode("utf-8"), check=True)
            self._log(f"📋 Copied via xclip: {path_str}", "info")
            return json.dumps({"ok": True, "path": path_str, "fallback": "xclip"})
        except Exception:
            return self._copy_xsel(path_str)

    def _copy_xsel(self, path_str: str):
        """Last Linux resort: xsel --clipboard --input."""
        import subprocess
        try:
            subprocess.run(["xsel", "--clipboard", "--input"], input=path_str.encode("utf-8"), check=True)
            self._log(f"📋 Copied via xsel: {path_str}", "info")
            return json.dumps({"ok": True, "path": path_str, "fallback": "xsel"})
        except Exception as e_x:
            return json.dumps({"ok": False, "error": f"xclip/xsel failed {e_x}", "path": path_str})

