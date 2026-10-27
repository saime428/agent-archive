"""Native desktop window for the Workbench (optional `desktop` extra: pywebview)."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from typing import Any

TITLE = "Agent Workbench"
# The Files editor blocks unload with a beforeunload handler while a tab has unsaved edits.
# Closing the host window skips beforeunload, so ask the page the same question directly.
PAGE_BLOCKS_UNLOAD_JS = (
    "(() => { const e = new Event('beforeunload', { cancelable: true });"
    " window.dispatchEvent(e); return e.defaultPrevented; })()"
)
# A page that has not answered by then is treated as having unsaved edits, so the user decides.
PAGE_ANSWER_SECONDS = 5.0


class DesktopUnavailable(RuntimeError):
    pass


def load_desktop_window() -> Callable[[str], None]:
    """Return a function that shows a Workbench URL in a native window until the user closes it."""
    try:
        import webview

        if os.name == "nt":
            from webview.platforms import winforms
    except ImportError as exc:
        raise DesktopUnavailable('Desktop window needs pywebview: pip install -e ".[desktop]"') from exc
    # Without WebView2, pywebview silently falls back to Internet Explorer, which renders a blank page.
    if os.name == "nt" and winforms.renderer != "edgechromium":
        raise DesktopUnavailable("Desktop window needs the Microsoft Edge WebView2 Runtime.")

    def open_window(url: str) -> None:
        window = webview.create_window(TITLE, url, width=1280, height=820, text_select=True, zoomable=True)
        guard_unsaved_close(window)
        # Persistent storage keeps the Workbench's localStorage (theme, panel toggles) across launches.
        webview.start(private_mode=False)

    return open_window


def guard_unsaved_close(window: Any) -> None:
    """Ask before closing while the page reports unsaved edits.

    The closing handler runs on the GUI thread, where waiting for JavaScript would deadlock,
    so the first close is cancelled and re-issued from a worker thread once the page answers.
    """
    confirmed = threading.Event()
    # One question at a time: repeated close clicks, or pywebview re-closing every 500ms after
    # Ctrl+C, must not stack confirmation dialogs.
    asking = threading.Lock()

    def on_closing() -> bool:
        if confirmed.is_set():
            return True
        if asking.acquire(blocking=False):
            threading.Thread(target=confirm_then_close, daemon=True).start()
        return False

    def confirm_then_close() -> None:
        try:
            if page_has_unsaved_edits() and not window.create_confirmation_dialog(
                TITLE, "有未保存的文件修改，仍要关闭窗口吗？"
            ):
                return
            confirmed.set()
            window.destroy()
        finally:
            asking.release()

    def page_has_unsaved_edits() -> bool:
        # A page that never loaded has no edits; evaluate_js would otherwise wait 20s for it.
        if not window.events.loaded.is_set():
            return False
        answer: list[bool] = []

        def ask_page() -> None:
            try:
                answer.append(bool(window.evaluate_js(PAGE_BLOCKS_UNLOAD_JS)))
            except Exception:  # noqa: BLE001 - an unreadable page must not silently drop edits
                answer.append(True)

        # evaluate_js has no timeout, so a hung renderer would otherwise make the window unclosable.
        probe = threading.Thread(target=ask_page, daemon=True)
        probe.start()
        probe.join(PAGE_ANSWER_SECONDS)
        return answer[0] if answer else True

    window.events.closing += on_closing
