import importlib.util
import os
import re
import sys
import time
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

import simplemma
from PySide6.QtCore import QThread, QTimer, Signal

from config import get_dictionary_settings
from item import ClipItem
from utils.general import truncate_text
from utils.html import normalize_html_for_qt

from .base import Plugin

# Vendored mdict-query helper (moved from utils/dict.py)
REPO_ROOT = Path(__file__).resolve().parent.parent
VENDOR_MDICT = REPO_ROOT / "vendors" / "mdict-query"
_DICT_CFG = get_dictionary_settings()
MDX_PATH = Path(_DICT_CFG.get("mdxPath", "")).expanduser()
# UI font (used for helper messages).
_UI_FONT = (
    get_dictionary_settings.__globals__["load_config"]()  # type: ignore
    .get("ui", {})
    .get("fontFamily")
    or "Cascadia Code"
)


def _load_mdict_module():
    if not (VENDOR_MDICT / "mdict_query.py").exists():
        raise ImportError("mdict_query.py not found in vendors/mdict-query")

    spec = importlib.util.spec_from_file_location(
        "mdict_query",
        VENDOR_MDICT / "mdict_query.py",
        submodule_search_locations=[str(VENDOR_MDICT)],
    )
    if spec is None or spec.loader is None:
        raise ImportError("Unable to load mdict_query spec")
    module = importlib.util.module_from_spec(spec)
    sys.modules["mdict_query"] = module
    spec.loader.exec_module(module)
    return module


def get_definition(word: str) -> str:
    """Lookup a word in the mdict dictionary and return its definition."""
    mdict_module = _load_mdict_module()
    IndexBuilder = mdict_module.IndexBuilder
    if not MDX_PATH:
        raise FileNotFoundError(
            "Dictionary path not configured. Set dictionary.mdxPath in config.yaml."
        )
    mdx_path_str = str(MDX_PATH)
    if not MDX_PATH.exists():
        raise FileNotFoundError(f"Dictionary file not found at {mdx_path_str}")

    d = IndexBuilder(mdx_path_str)
    if not os.path.exists(mdx_path_str + ".sqlite.db"):
        d.make_sqlite()
    result = d.mdx_lookup(word)
    return result[0]


def lookup_keys(word: str) -> list[str]:
    w = word
    if not w:
        return []

    # 1) exact first
    keys = [w]

    # 2) fallback lemma ONLY after exact fails
    lemma = simplemma.lemmatize(w, lang="en")
    if lemma and lemma != w:
        keys.append(lemma)

    # de-dupe keep order
    seen, out = set(), []
    for k in keys:
        if k and k not in seen:
            out.append(k)
            seen.add(k)
    return out


class DictLookupWorker(QThread):
    finishedLookup = Signal(str, str, object)  # word, html, err
    failedLookup = Signal(str, str)  # word, error

    def __init__(
        self, lookup_fn: Callable[[str], Tuple[str, Optional[str]]], word: str
    ):
        super().__init__()
        self._lookup_fn = lookup_fn
        self._word = (word or "").strip()

    def run(self) -> None:
        try:
            if self.isInterruptionRequested():
                return
            html, err = self._lookup_fn(self._word)
            if self.isInterruptionRequested():
                return
            self.finishedLookup.emit(self._word, html or "", err)
        except Exception as exc:  # pylint: disable=broad-except
            # If we were interrupted, silently exit instead of emitting failure.
            if self.isInterruptionRequested():
                return
            self.failedLookup.emit(self._word, str(exc))


class DictionaryPlugin(Plugin):
    plugin_id = "dictionary"
    display_name = "Dictionary"

    def __init__(
        self,
        group_id: int,
        preview_text_limit: int,
        refresh_callback: Callable[[], None],
    ) -> None:
        super().__init__(group_id)
        self._preview_text_limit = preview_text_limit
        self._refresh_callback = refresh_callback
        self._cache: Dict[str, tuple[str, Optional[str]]] = {}
        self._worker: Optional[DictLookupWorker] = None
        self._loading_word: Optional[str] = None
        self._pending_queue: list[str] = []
        self._oald_css = ""
        self._dict_cfg = get_dictionary_settings()
        self._font_family = _UI_FONT

        css_path = self._dict_cfg.get("cssPath")
        if css_path:
            try:
                self._oald_css = (
                    Path(css_path)
                    .expanduser()
                    .read_text(encoding="utf-8", errors="ignore")
                )
            except Exception:
                self._oald_css = ""

    def build_items(self, clipboard_text: str) -> list[ClipItem]:
        raw = (clipboard_text or "").strip()
        if not raw:
            note = "Copy a word or phrase to the clipboard to see dictionary results."
            return [
                self._clip_from_html(
                    "Dictionary",
                    self._style_message(
                        "<p>Clipboard is empty.</p><p>" + note + "</p>"
                    ),
                    "Plugins: Dictionary",
                    preview_blob=None,
                )
            ]

        lookup_words = self._extract_lookup_words(raw)
        if not lookup_words:
            return [
                self._clip_from_html(
                    "Dictionary",
                    self._style_message("<p>No valid words found in selection.</p>"),
                    raw,
                    preview_blob=None,
                )
            ]

        # Show only the first candidate to avoid multiple plugin rows.
        lookup_words = lookup_words

        # enqueue missing words
        self._enqueue_missing(lookup_words)

        items: list[ClipItem] = []
        for w in lookup_words:
            if w in self._cache:
                html, err = self._cache[w]
                preview_blob = html.encode("utf-8", errors="replace") if html else None
                items.append(
                    self._clip_from_html(w, html, raw, err, preview_blob=preview_blob)
                )
            elif self._loading_word == w:
                items.append(
                    self._clip_from_html(
                        w,
                        self._style_message("<p>Loading dictionary...</p>"),
                        w,
                        None,
                        preview_blob=None,
                    )
                )
            else:
                items.append(
                    self._clip_from_html(
                        w,
                        self._style_message("<p>Queued for lookup...</p>"),
                        w,
                        None,
                        preview_blob=None,
                    )
                )

        if not (self._worker and self._worker.isRunning()):
            self._start_next_pending()

        return items[:1]

    def teardown(self) -> None:
        worker = self._worker
        if worker and worker.isRunning():
            try:
                worker.requestInterruption()
                worker.quit()
                # Give the worker ample time to stop cleanly; fall back to terminate.
                if not worker.wait(1500):
                    worker.terminate()
                    worker.wait(500)
            except Exception:
                pass
        self._worker = None

    # Internal helpers -------------------------------------------------
    def _extract_lookup_words(self, raw: str) -> list[str]:
        # split on commas/newlines; take first token in each segment
        segments = re.split(r"[,\n]+", raw)
        words: list[str] = []
        for seg in segments:
            seg = seg.strip()
            if not seg:
                continue
            toks = re.findall(r"[A-Za-z][A-Za-z'\\-]*", seg) or seg.split()
            if toks:
                words.append(toks[0])
        # de-dupe keeping order; cap to 5
        seen = set()
        uniq: list[str] = []
        for w in words:
            wl = w.lower()
            if wl in seen:
                continue
            seen.add(wl)
            uniq.append(w)
        return uniq[:5]

    def _clip_from_html(
        self,
        title: str,
        html_body: str,
        plain_source: str,
        error: Optional[str] = None,
        preview_blob: Optional[bytes] = None,
    ) -> ClipItem:
        if not html_body:
            html_body = self._style_message(
                f"<p>No definition found for <b>{title}</b>.</p>"
            )
            if error:
                html_body = self._style_message(
                    f"{html_body}<p style='color:#f66; font-size:14pt'>Error: {error}</p>"
                )
        plain = re.sub(r"<[^>]+>", " ", html_body).strip()
        preview = truncate_text(plain, self._preview_text_limit)
        return ClipItem(
            id=-1000,
            content_type="html",
            content_text="",
            content_blob=html_body.encode("utf-8"),
            created_at=int(time.time()),
            pinned=False,
            pinned_at=None,
            group_id=self.group_id,
            preview_text=preview,
            preview_blob=preview_blob,
            has_full_content=True,
            content_length=len(plain),
            collapsed_height=250,
            expanded_height=250,
            render_mode="web",
            plugin_id=self.plugin_id,
            extra_actions=[],
        )

    def _lookup_definition(self, word: str) -> tuple[str, Optional[str]]:
        """Try lookup with exact word, then fall back to lemma variants via lookup_keys."""
        keys = lookup_keys(word)
        if not keys:
            return "", f"No lookup keys for '{word}'"

        last_err: Optional[str] = None
        for key in keys:
            html, err = self._lookup_single(key, 0)
            if html:
                return html, err
            last_err = err
        return "", last_err

    def _lookup_single(self, word: str, depth: int = 0) -> tuple[str, Optional[str]]:
        """Single-word lookup; follow mdict @@@LINK redirects once or twice to get real entry."""
        if depth > 2:
            return "", f"Redirect loop for {word}"
        try:
            result = get_definition(word)
            if isinstance(result, (list, tuple)):
                result = result[0] if result else ""
            if isinstance(result, bytes):
                result = result.decode("utf-8", errors="replace")
            html = str(result or "").strip()
            if html.upper().startswith("@@@LINK="):
                target = html.split("=", 1)[1].strip()
                if target:
                    return self._lookup_definition(target, depth + 1)
            return html, None
        except Exception as exc:  # pylint: disable=broad-except
            return "", str(exc)

    def _enqueue_missing(self, words: list[str]) -> None:
        for w in words:
            if not w:
                continue
            if w in self._cache or w == self._loading_word:
                continue
            if w not in self._pending_queue:
                self._pending_queue.append(w)

    def _start_next_pending(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        if self._worker:
            try:
                self._worker.finishedLookup.disconnect()
                self._worker.failedLookup.disconnect()
            except Exception:
                pass
            try:
                self._worker.deleteLater()
            except Exception:
                pass
            self._worker = None

        if not self._pending_queue:
            return
        word = self._pending_queue.pop(0)
        self._loading_word = word
        self._worker = DictLookupWorker(self._lookup_definition, word)
        self._worker.finishedLookup.connect(self._on_lookup_finished)
        self._worker.failedLookup.connect(self._on_lookup_failed)
        self._worker.start()

    def _on_lookup_finished(self, word: str, html: str, err_obj) -> None:
        if self._loading_word != word:
            return
        err = err_obj if isinstance(err_obj, str) else None
        clean_html = normalize_html_for_qt(
            html,
            ["sound", "OALD9_tab", "OALECD_trans"],
            self._oald_css,
            font_size=14,
        )
        if (not clean_html) and html:
            clean_html = html
        self._cache[word] = (
            (
                clean_html
                or self._style_message(f"<p>No definition found for <b>{word}</b>.</p>")
            ),
            err or None,
        )
        self._loading_word = None
        try:
            if self._worker:
                self._worker.deleteLater()
        except Exception:
            pass
        self._worker = None
        QTimer.singleShot(0, self._refresh_callback)
        QTimer.singleShot(0, self._start_next_pending)

    def _style_message(self, html: str) -> str:
        """Wrap helper messages with configured font-family."""
        safe_font = str(self._font_family).replace('"', "'")
        return f"<div style='font-family:{safe_font}; font-size:14pt'>{html}</div>"

    def _on_lookup_failed(self, word: str, error: str) -> None:
        if self._loading_word != word:
            return
        self._cache[word] = (
            self._style_message(f"<p>No definition found for <b>{word}</b>.</p>"),
            error or "Lookup failed",
        )
        self._loading_word = None
        try:
            if self._worker:
                self._worker.deleteLater()
        except Exception:
            pass
        self._worker = None
        QTimer.singleShot(0, self._refresh_callback)
        QTimer.singleShot(0, self._start_next_pending)
