import functools
import html as _html
import re
import time
from pathlib import Path
from typing import Iterable, Optional, Tuple

from PySide6.QtCore import Property, QPoint, QSize, Qt, QTimer, Signal, Slot
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QPainter,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextOption,
)
from PySide6.QtQuick import QQuickPaintedItem, QQuickWindow


def timer(func):
    """Decorator to measure the execution time of a function."""

    @functools.wraps(func)
    def wrapper_timer(*args, **kwargs):
        start_time = time.perf_counter()  # Record the start time
        result = func(*args, **kwargs)  # Execute the function
        end_time = time.perf_counter()  # Record the end time
        run_time = end_time - start_time
        print(f"Function {func.__name__!r} took {run_time:.4f} seconds to execute.")
        return result  # Return the function's result

    return wrapper_timer


class SuperRichTextItem(QQuickPaintedItem):
    """
    QQuickPaintedItem that mirrors the legacy SuperQLabel behavior:
    - Single cached QTextDocument
    - Plain/Rich text with collapsed/full variants
    - Wrap-anywhere, hover auto-pan for overflow
    - Implicit height updates based on width ("height-for-width" semantics)
    """

    collapsedChanged = Signal()
    hoverPanEnabledChanged = Signal()
    wrapAnywhereChanged = Signal()
    wordWrapChanged = Signal()
    contentChanged = Signal()
    colorChanged = Signal()
    textColorChanged = Signal()
    naturalHeightChanged = Signal()
    naturalCollapsedHeightChanged = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # Use an image render target so paint runs on the GUI thread and QTextDocument
        # is never mutated from the scene graph thread. FramebufferObject rendering
        # would push paint into the QSG render thread, which triggers cross-thread
        # warnings/crashes when QTextDocument creates internal children.
        self.setRenderTarget(QQuickPaintedItem.RenderTarget.Image)

        self._font = QFont()

        self._cached_width = -1
        self._cached_size = QSize(0, 0)
        self._cached_font_key = None
        self._cached_fmt_rich = False
        self._cached_text = ""
        self._cached_text_color: Optional[str] = None

        self._full_text = ""
        self._collapsed_text: Optional[str] = None
        self._full_html: Optional[str] = None
        self._collapsed_html: Optional[str] = None
        self._collapsed_state = False

        self._wrap_anywhere = True
        self._word_wrap = True
        self._color: str = ""
        self._text_color: str = ""
        self._natural_full_h: int = 0
        # self._natural_collapsed_h: int = 0

        self._pan = QPoint(0, 0)
        self._hover_pan_enabled = True
        self._hover_pos = None
        self._edge_zone = 28
        self._max_speed = 18
        self._pan_timer = QTimer(self)  # keep Python ref and parent for lifetime
        # self._pan_timer.setParent(self)
        self._pan_timer.setTimerType(Qt.PreciseTimer)
        self._pan_timer.setInterval(16)
        self._pan_timer.timeout.connect(self._on_hover_pan_tick)

        # gui_thread = QGuiApplication.instance().thread()
        # if self._pan_timer.thread() is not gui_thread:
        #     self._pan_timer.moveToThread(gui_thread)
        # # Debug: prove timer stays alive
        # self._pan_timer.timeout.connect(lambda: None)

        self.setAcceptHoverEvents(True)
        self._normalized_html_cache: dict[tuple, str] = {}
        self.widthChanged.connect(self._on_width_changed)
        self._strip_classes: list[str] = []
        self._skip_normalize: bool = True

    # -------------------------
    # QML Properties
    # -------------------------
    def getCollapsed(self) -> bool:
        return self._collapsed_state

    def setCollapsed(self, v: bool) -> None:
        v = bool(v)
        if v == self._collapsed_state and self._cached_size.height() > 0:
            return
        self._collapsed_state = v
        self._invalidate_layout(full=True)
        self.collapsedChanged.emit()
        self._update_implicit_height()
        self.update()

    collapsed = Property(bool, getCollapsed, setCollapsed, notify=collapsedChanged)

    def getHoverPanEnabled(self) -> bool:
        return self._hover_pan_enabled

    def setHoverPanEnabled(self, v: bool) -> None:
        # print(
        #     "hover",
        #     v,
        #     "for",
        #     repr(self._full_html[:30]) if self._full_html else "(no html)",
        # )
        v = bool(v)
        if v == self._hover_pan_enabled:
            return
        self._hover_pan_enabled = v
        if not v:
            # print("hover pan disabled, resetting pan")
            self._hover_pos = None
            self._pan = QPoint(0, 0)
            if self._pan_timer.isActive():
                self._pan_timer.stop()
        self.hoverPanEnabledChanged.emit()
        self.update()

    hoverPanEnabled = Property(
        bool, getHoverPanEnabled, setHoverPanEnabled, notify=hoverPanEnabledChanged
    )

    def getStripClasses(self):
        return list(self._strip_classes)

    def setStripClasses(self, classes) -> None:
        new_list: list[str] = []
        try:
            for c in classes or []:
                s = str(c).strip()
                if s:
                    new_list.append(s)
        except Exception:
            new_list = []
        if new_list == self._strip_classes:
            return
        self._strip_classes = new_list
        self._normalized_html_cache.clear()
        self._invalidate_layout(full=True)
        self.contentChanged.emit()
        self._update_natural_heights()
        self._update_implicit_height()
        self.update()

    stripClasses = Property(
        "QVariantList", getStripClasses, setStripClasses, notify=contentChanged
    )

    def getSkipNormalize(self) -> bool:
        return self._skip_normalize

    def setSkipNormalize(self, v: bool) -> None:
        v = bool(v)
        if v == self._skip_normalize:
            return
        self._skip_normalize = v
        self._normalized_html_cache.clear()
        self._invalidate_layout(full=True)
        self.contentChanged.emit()
        self._update_natural_heights()
        self._update_implicit_height()
        self.update()

    skipNormalize = Property(
        bool, getSkipNormalize, setSkipNormalize, notify=contentChanged
    )

    def getColor(self) -> str:
        return self._color

    def setColor(self, value: str) -> None:
        value = value or ""
        if value == self._color:
            return
        self._color = value
        self.colorChanged.emit()
        self.update()

    color = Property(str, getColor, setColor, notify=colorChanged)

    def getTextColor(self) -> str:
        return self._text_color

    def setTextColor(self, value: str) -> None:
        value = value or ""
        if value == self._text_color:
            return
        self._text_color = value
        self._cached_text_color = None
        self._invalidate_layout(full=True)
        self._update_natural_heights()
        self._update_implicit_height()
        self.textColorChanged.emit()
        self.update()

    textColor = Property(str, getTextColor, setTextColor, notify=textColorChanged)

    def getFontPointSize(self) -> float:
        # Prefer point size; fall back to pixelSize if point size is unset.
        ps = self._font.pointSizeF()
        if ps <= 0 and self._font.pixelSize() > 0:
            return float(self._font.pixelSize())
        return float(ps if ps > 0 else 12.0)

    def setFontPointSize(self, v: float) -> None:
        try:
            size = float(v)
        except Exception:
            return
        if size <= 0:
            return
        if abs(self._font.pointSizeF() - size) < 0.01:
            return
        self._font.setPointSizeF(size)
        self._invalidate_layout(full=True)
        self._update_natural_heights()
        self._update_implicit_height()
        self.update()

    fontPointSize = Property(float, getFontPointSize, setFontPointSize)

    def getWrapAnywhere(self) -> bool:
        return self._wrap_anywhere

    def setWrapAnywhere(self, v: bool) -> None:
        v = bool(v)
        if v == self._wrap_anywhere:
            return
        self._wrap_anywhere = v
        self._invalidate_layout(full=False)
        self.wrapAnywhereChanged.emit()
        self._update_natural_heights()
        self._update_implicit_height()
        self.update()

    wrapAnywhere = Property(
        bool, getWrapAnywhere, setWrapAnywhere, notify=wrapAnywhereChanged
    )

    def getNaturalHeight(self) -> int:
        return int(self._natural_full_h or 0)

    naturalHeight = Property(int, getNaturalHeight, notify=naturalHeightChanged)

    # def getNaturalCollapsedHeight(self) -> int:
    #     return int(self._natural_collapsed_h or 0)

    # naturalCollapsedHeight = Property(
    #     int, getNaturalCollapsedHeight, notify=naturalCollapsedHeightChanged
    # )

    def getWordWrap(self) -> bool:
        return self._word_wrap

    def setWordWrap(self, v: bool) -> None:
        v = bool(v)
        if v == self._word_wrap:
            return
        self._word_wrap = v
        self._invalidate_layout(full=False)
        self.wordWrapChanged.emit()
        self._update_natural_heights()
        self._update_implicit_height()
        self.update()

    wordWrap = Property(bool, getWordWrap, setWordWrap, notify=wordWrapChanged)

    def getFullText(self) -> str:
        return self._full_text

    def setFullText(self, text: str) -> None:
        self._full_text = text or ""
        self._apply_content_variants()

    fullText = Property(str, getFullText, setFullText, notify=contentChanged)

    def getCollapsedText(self) -> str:
        return self._collapsed_text or ""

    def setCollapsedText(self, text: str) -> None:
        self._collapsed_text = text or None
        self._apply_content_variants()

    collapsedText = Property(
        str, getCollapsedText, setCollapsedText, notify=contentChanged
    )

    def getFullHtml(self) -> str:
        return self._full_html or ""

    def setFullHtml(self, html: str) -> None:
        self._full_html = html or None
        self._apply_content_variants()

    fullHtml = Property(str, getFullHtml, setFullHtml, notify=contentChanged)

    def getCollapsedHtml(self) -> str:
        return self._collapsed_html or ""

    def setCollapsedHtml(self, html: str) -> None:
        self._collapsed_html = html or None
        self._apply_content_variants()

    collapsedHtml = Property(
        str, getCollapsedHtml, setCollapsedHtml, notify=contentChanged
    )

    # -------------------------
    # Public API
    # -------------------------
    def set_content_variants(
        self,
        full_text: str = "",
        collapsed_text: Optional[str] = None,
        full_html: Optional[str] = None,
        collapsed_html: Optional[str] = None,
    ) -> None:
        changed = (
            (full_text or "") != self._full_text
            or collapsed_text != self._collapsed_text
            or full_html != self._full_html
            or collapsed_html != self._collapsed_html
        )
        self._full_text = full_text or ""
        self._collapsed_text = collapsed_text
        self._full_html = full_html
        self._collapsed_html = collapsed_html
        if changed:
            self._normalized_html_cache.clear()
            self._invalidate_layout(full=True)
            self.contentChanged.emit()
            self._update_natural_heights()
            self._update_implicit_height()
            self.update()

    def setText(self, text: str) -> None:
        self.set_content_variants(full_text=text or "", collapsed_text=text or "")

    def setHtml(self, html: str, strip_classes: Optional[Iterable[str]] = None) -> None:
        if strip_classes is not None:
            self.setStripClasses(strip_classes)
        self.set_content_variants(full_html=html or "", collapsed_html=html or "")

    def setStyledHtml(
        self,
        html: str,
        css: str = "",
        strip_classes: Optional[Iterable[str]] = None,
    ) -> None:
        """Set HTML with optional CSS that will be inlined ahead of the content."""
        if strip_classes is not None:
            self.setStripClasses(strip_classes)
        css = css or ""
        if css.strip():
            css_block = f"<style>{css}</style>"
            if "<body" in html:
                combined = re.sub(
                    r"(?is)<\s*body\b[^>]*>",
                    lambda m: m.group(0) + css_block,
                    html,
                    count=1,
                )
            else:
                combined = css_block + html
        else:
            combined = html
        self.set_content_variants(
            full_html=combined or "", collapsed_html=combined or ""
        )

    # -------------------------
    # Internals
    # -------------------------
    def _apply_content_variants(self) -> None:
        self.set_content_variants(
            full_text=self._full_text,
            collapsed_text=self._collapsed_text,
            full_html=self._full_html,
            collapsed_html=self._collapsed_html,
        )

    def _font_key(self) -> Tuple:
        f: QFont = self._font
        return (
            f.family(),
            f.pointSizeF(),
            f.pixelSize(),
            f.weight(),
            f.italic(),
            f.underline(),
            f.strikeOut(),
        )

    def _content_for_state(self, collapsed: bool) -> Tuple[bool, str]:
        target_html = self._collapsed_html if collapsed else self._full_html
        target_text = self._collapsed_text if collapsed else self._full_text
        if target_html is None and target_text is None:
            target_text = ""
        use_html = target_html is not None
        payload = target_html if use_html else (target_text or "")
        return use_html, payload

    def _normalized_html(self, raw_html: str) -> str:
        if raw_html is None:
            return ""
        if self._skip_normalize:
            return raw_html
        cache_key = (raw_html, tuple(self._strip_classes))
        cached = self._normalized_html_cache.get(cache_key)
        if cached is not None:
            return cached
        normalized = self.normalize_html_for_qlabel(raw_html, self._strip_classes)
        normalized = self.clean_font_size(normalized)
        self._normalized_html_cache[cache_key] = normalized
        return normalized

    def _invalidate_layout(self, full: bool) -> None:
        self._cached_width = -1
        self._cached_size = QSize(0, 0)
        if full:
            self._cached_text = ""
        self._clamp_pan_to_bounds()

    def _effective_width(self) -> int:
        """Choose a reasonable width for measurement when width is not yet set."""
        candidates = [
            int(self.width()),
            int(self.implicitWidth()),
            int(self.parentItem().width()) if self.parentItem() else 0,
            int(self._cached_width if self._cached_width > 0 else 0),
        ]
        best = max((c for c in candidates if c and c > 0), default=0)
        return max(1, best)

    def _build_document(
        self, width: int, use_html: bool, payload: str
    ) -> QTextDocument:
        doc = QTextDocument()
        doc.setDocumentMargin(0)
        doc.setDefaultFont(self._font)

        opt = doc.defaultTextOption()
        opt.setWrapMode(
            QTextOption.WrapAnywhere if self._wrap_anywhere else QTextOption.WordWrap
        )
        doc.setDefaultTextOption(opt)

        if self._text_color:
            doc.setDefaultStyleSheet(f"* {{ color: {self._text_color}; }}")

        if use_html:
            payload = self.wrap_html_with_default_color(payload, self._text_color)
            doc.setHtml(payload)
        else:
            doc.setPlainText(payload)
            if self._text_color:
                cursor = QTextCursor(doc)
                cursor.select(QTextCursor.Document)
                fmt = QTextCharFormat()
                fmt.setForeground(QColor(self._text_color))
                cursor.mergeCharFormat(fmt)

        doc.setTextWidth(width if self._word_wrap else -1)
        return doc

    def _sync_doc_if_needed(
        self, width: int, need_doc: bool = False
    ) -> Optional[QTextDocument]:
        width = max(1, int(width))

        font_key = self._font_key()
        use_html, payload = self._content_for_state(self._collapsed_state)

        fmt_rich = bool(use_html)
        text = payload if not fmt_rich else self._normalized_html(payload)
        text_color_changed = self._text_color != self._cached_text_color

        font_changed = font_key != self._cached_font_key
        width_changed = width != self._cached_width
        fmt_changed = fmt_rich != self._cached_fmt_rich
        text_changed = text != self._cached_text

        # Always create a fresh document on the current thread when painting to
        # avoid cross-thread QObject warnings.
        if (
            need_doc
            or font_changed
            or width_changed
            or fmt_changed
            or text_changed
            or text_color_changed
        ):
            doc = self._build_document(width, fmt_rich, text)
            self._cached_font_key = font_key
            self._cached_width = width
            self._cached_fmt_rich = fmt_rich
            self._cached_text = text
            self._cached_text_color = self._text_color
            self._cached_size = doc.documentLayout().documentSize().toSize()
            self._clamp_pan_to_bounds()
            return doc

        return None

    def _pan_bounds(self):
        vp_w = max(0, int(self.width()))
        vp_h = max(0, int(self.height()))
        doc = self._cached_size
        extra_x = max(0, doc.width() - vp_w)
        extra_y = max(0, doc.height() - vp_h)
        return 0, extra_x, 0, extra_y

    def _clamp_pan_to_bounds(self):
        if self._cached_size.isEmpty():
            self._pan = QPoint(0, 0)
            return
        min_x, max_x, min_y, max_y = self._pan_bounds()
        x = min(max(self._pan.x(), min_x), max_x)
        y = min(max(self._pan.y(), min_y), max_y)
        self._pan = QPoint(x, y)

    def _update_implicit_height(self):
        w = self._effective_width()
        self._sync_doc_if_needed(w, need_doc=False)
        h = max(1, self._cached_size.height())
        self.setImplicitHeight(h)
        self.setImplicitWidth(max(1, self._cached_size.width()))

    def _on_width_changed(self):
        self._invalidate_layout(full=False)
        self._update_natural_heights()
        self._update_implicit_height()
        self.update()

    @Slot()
    def refreshLayout(self) -> None:
        """Force re-measure and implicit size update (useful when width set from QML)."""
        self._update_natural_heights()
        self._update_implicit_height()
        self.update()

    def _measure_height_for(self, width: int, collapsed: bool) -> int:
        width = max(1, int(width))
        use_html, payload = self._content_for_state(collapsed)
        if use_html:
            payload = self._normalized_html(payload)
        doc = self._build_document(width, use_html, payload)
        return max(1, int(doc.documentLayout().documentSize().height()))

    def _update_natural_heights(self) -> None:
        w = self._effective_width()
        full_h = self._measure_height_for(w, collapsed=False)
        # col_h = self._measure_height_for(w, collapsed=True)

        if full_h != self._natural_full_h:
            self._natural_full_h = full_h
            self.naturalHeightChanged.emit()
        # if col_h != self._natural_collapsed_h:
        #     self._natural_collapsed_h = col_h
        #     self.naturalCollapsedHeightChanged.emit()

    # -------------------------
    # QQuickPaintedItem
    # -------------------------
    def paint(self, painter: QPainter) -> None:
        w = max(1, int(self.width()))
        h = max(1, int(self.height()))
        doc = self._sync_doc_if_needed(w, need_doc=True)
        if doc is None:
            use_html, payload = self._content_for_state(self._collapsed_state)
            doc = self._build_document(w, use_html, payload)
            self._cached_size = doc.documentLayout().documentSize().toSize()
            self._clamp_pan_to_bounds()
        painter.save()
        painter.setClipRect(0, 0, w, h)
        if self._color:
            try:
                painter.fillRect(0, 0, w, h, QColor(self._color))
            except Exception:
                pass
        painter.translate(-self._pan.x(), -self._pan.y())
        doc.drawContents(painter)
        painter.restore()

    # -------------------------
    # Hover auto-pan
    # -------------------------
    def hoverMoveEvent(self, event) -> None:
        self._hover_pos = event.position().toPoint()
        if self._hover_pan_enabled and not self._pan_timer.isActive():
            # print("starting hover pan from hoverMoveEvent")
            self._pan_timer.start()
        self.update()
        event.accept()

    def hoverEnterEvent(self, event) -> None:
        self._hover_pos = event.position().toPoint()
        if self._hover_pan_enabled and not self._pan_timer.isActive():
            # print("starting hover pan from hoverEnterEvent")
            self._pan_timer.start()
        self.update()
        event.accept()

    def hoverLeaveEvent(self, event) -> None:
        self._hover_pos = None
        # print("stopping hover pan from hoverLeaveEvent")
        if self._pan_timer.isActive():
            self._pan_timer.stop()
        self._pan = QPoint(0, 0)
        self.update()
        event.accept()

    @Slot("QPointF")
    def feedPointer(self, p):
        """Allow QML overlay to drive hover-pan while a button is held."""
        # from PySide6.QtCore import QThread

        # print(
        #     "feedPointer thread =",
        #     QThread.currentThread(),
        #     "timer thread =",
        #     self._pan_timer.thread(),
        #     "item thread =",
        #     self.thread(),
        # )

        try:
            self._hover_pos = QPoint(int(p.x()), int(p.y()))
        except Exception:
            return
        if self._hover_pan_enabled and not self._pan_timer.isActive():
            # print("starting hover pan timer from feedPointer")
            self._pan_timer.start()
            QTimer.singleShot(0, lambda: self._on_hover_pan_tick())
        # print(
        #     "timer active after start:",
        #     self._pan_timer.isActive(),
        #     "remaining:",
        #     self._pan_timer.remainingTime(),
        #     "interval:",
        #     self._pan_timer.interval(),
        # )

        self.update()

    @Slot()
    def endPointer(self) -> None:
        """Stop hover-pan and reset when long press ends."""
        self._hover_pos = None
        # print("stopping hover pan from endPointer")
        if self._pan_timer.isActive():
            self._pan_timer.stop()
        self._pan = QPoint(0, 0)
        self.update()

    def _edge_speed_1d(self, pos: int, length: int) -> int:
        z = self._edge_zone
        if length <= 0:
            return 0
        if pos < z:
            t = 1.0 - (pos / max(1, z))
            return int(round(-self._max_speed * (t * t)))
        if pos > length - z:
            d = length - pos
            t = 1.0 - (d / max(1, z))
            return int(round(self._max_speed * (t * t)))
        return 0

    def _on_hover_pan_tick(self) -> None:
        # print("hover pan tick")
        if not self._hover_pan_enabled or self._hover_pos is None:
            if self._pan_timer.isActive():
                self._pan_timer.stop()
            return

        QTimer.singleShot(16, lambda: self._on_hover_pan_tick())

        w = int(self.width())
        h = int(self.height())
        if w <= 0 or h <= 0:
            return

        self._sync_doc_if_needed(max(1, w))
        min_x, max_x, min_y, max_y = self._pan_bounds()
        if max_x == 0 and max_y == 0:
            return

        vx = self._edge_speed_1d(self._hover_pos.x(), w) if max_x > 0 else 0
        vy = self._edge_speed_1d(self._hover_pos.y(), h) if max_y > 0 else 0
        # print(
        #     "position:",
        #     self._hover_pos,
        #     w,
        #     h,
        #     "hover pan speed:",
        #     self._edge_speed_1d(self._hover_pos.x(), w),
        #     self._edge_speed_1d(self._hover_pos.y(), h),
        # )
        if vx == 0 and vy == 0:
            return

        self._pan = QPoint(self._pan.x() + vx, self._pan.y() + vy)
        self._clamp_pan_to_bounds()
        self.update()
        win = self.window()
        if win:
            win.requestUpdate()

    # -------------------------
    # HTML normalization
    # -------------------------
    @staticmethod
    def normalize_html_for_qlabel(
        raw_html: str, strip_classes: Optional[Iterable[str]] = None
    ) -> str:
        _t0 = time.perf_counter()
        if not raw_html:
            return ""

        s = raw_html.strip()

        # Plain text -> safe HTML
        if not s.lstrip().startswith("<"):
            return f"<html><body><span>{_html.escape(s)}</span></body></html>"

        # 1) Extract StartFragment..EndFragment if present (clipboard HTML)
        m = re.search(
            r"(?is)<!--\s*StartFragment\s*-->(.*?)<!--\s*EndFragment\s*-->", s
        )
        if m:
            s = m.group(1).strip()

        # 2) Extract styles from <head> (including embedded <style> and local links) then drop wrappers
        head_styles: list[str] = []
        for match in re.finditer(r"(?is)<\s*style\b[^>]*>(.*?)</\s*style\s*>", s):
            head_styles.append(match.group(1))
        for match in re.finditer(
            r'(?is)<\s*link\b[^>]*rel\s*=\s*"(?:stylesheet|style)"[^>]*href\s*=\s*"([^"]+)"[^>]*>',
            s,
        ):
            href = (match.group(1) or "").strip()
            if href:
                p = Path(href)
                if p.is_file():
                    try:
                        head_styles.append(
                            p.read_text(encoding="utf-8", errors="ignore")
                        )
                    except Exception:
                        pass
        # Drop all link tags entirely
        s = re.sub(r"(?is)<\s*link\b[^>]*>", "", s)
        s = re.sub(r"(?is)<\s*/?\s*html\b[^>]*>", "", s)
        s = re.sub(r"(?is)<\s*/?\s*body\b[^>]*>", "", s)
        s = re.sub(r"(?is)<\s*head\b[^>]*>.*?</\s*head\s*>", "", s)

        # 3) Normalize breaks and nbsp
        s = re.sub(r"(?is)<\s*br\s*/?\s*>", "<br>", s)
        s = s.replace("&#160;", "&nbsp;")

        # 4) Fix white-space: pre -> pre-wrap in inline styles
        def _fix_whitespace_in_style(match: re.Match) -> str:
            style = match.group(1)

            style2 = re.sub(
                r"(?is)(^|;)\s*white-space\s*:\s*pre\s*(;|$)",
                r"\1 white-space: pre-wrap\2",
                style,
            )

            # cleanup: remove double semicolons and trim
            style2 = re.sub(r";{2,}", ";", style2).strip(" ;")
            return f'style="{style2}"' if style2 else ""

        s = re.sub(r'(?is)\bstyle\s*=\s*"([^"]*)"', _fix_whitespace_in_style, s)

        # 5) Optional: collapse insane <br><br><br> spam (but keep structure)
        s = re.sub(r"(?is)(<br>\s*){4,}", "<br><br>", s)
        s = re.sub(r"(?is)^\s*(<br>\s*)+", "", s)
        s = re.sub(r"(?is)(<br>\s*)+\s*$", "", s)

        # 5b) Remove href attributes to avoid external navigation
        s = re.sub(r'(?is)\s*href\s*=\s*"[^"]*"', "", s)
        s = re.sub(r"(?is)\s*href\s*=\s*'[^']*'", "", s)

        # 5c) Strip any tags containing specified classes (remove tag and its contents)
        cls_list = [c.strip() for c in (strip_classes or []) if c and str(c).strip()]
        if cls_list:
            for cls in cls_list:
                pattern = rf"(?is)<([a-z0-9]+)([^>]*\bclass\s*=\s*\"[^\"]*\b{re.escape(cls)}\b[^\"]*\"[^>]*)>.*?</\1\s*>"
                s = re.sub(pattern, "", s)
                pattern_single = rf"(?is)<([a-z0-9]+)([^>]*\bclass\s*=\s*\"[^\"]*\b{re.escape(cls)}\b[^\"]*\"[^>]*)\s*/>"
                s = re.sub(pattern_single, "", s)

        # 6) Ensure we return a valid single document with body.
        #    Keep the fragment as-is (including <p>, <div>, <pre>, etc.)
        #    If fragment is "bare text" at top-level, wrap in <div> so Qt renders it consistently.
        if not re.search(r"(?is)<\s*(div|p|pre|table|ul|ol|h[1-6]|blockquote)\b", s):
            s = f"<div>{s}</div>"
        style_block = f"<style>{' '.join(head_styles)}</style>" if head_styles else ""
        result = f"<html><body>{style_block}{s}</body></html>"
        _dt = (time.perf_counter() - _t0) * 1000.0
        try:
            print(f"[SuperRichTextItem] normalize_html_for_qlabel took {_dt:.2f} ms")
        except Exception:
            pass
        return result

    @staticmethod
    def clean_font_size(html: str):
        ### remove all text font size setting in html
        if not html:
            return html

        # Drop CSS font-size declarations (inline or <style> blocks).
        cleaned = re.sub(
            r"(?is)font-size\s*:\s*[0-9]*\.?[0-9]+\s*(px|pt|em|rem|%)?\s*;?",
            "",
            html,
        )

        # Strip size attribute on legacy <font> tags.
        cleaned = re.sub(
            r'(?is)(<\s*font\b[^>]*?)\s*size\s*=\s*"?.*?"?([^>]*>)',
            r"\1\2",
            cleaned,
        )

        # Remove empty style attributes left behind.
        cleaned = re.sub(r'(?is)\s*style\s*=\s*([\'"])\s*\1', "", cleaned)
        return cleaned

    @staticmethod
    def set_base_font_size(html: str, point_size: float) -> str:
        ### first search all font size in html, calculate the min and max, scale it to point_size, point_size + 5
        if not html or point_size <= 0:
            return html

        pattern = re.compile(
            r"(?is)font-size\s*:\s*([0-9]*\.?[0-9]+)\s*(px|pt|em|rem|%)?"
        )
        sizes = [float(m[0]) for m in pattern.findall(html)]
        if not sizes:
            return html

        min_size = min(sizes)
        max_size = max(sizes)
        target_min = float(point_size)
        target_max = target_min + 5.0

        def _scale(match: re.Match) -> str:
            val = float(match.group(1))
            unit = match.group(2) or "pt"
            if max_size == min_size:
                new_val = target_min
            else:
                t = (val - min_size) / (max_size - min_size)
                new_val = target_min + t * (target_max - target_min)
            return f"font-size: {new_val:.2f}{unit}"

        return pattern.sub(_scale, html)

    @staticmethod
    def wrap_html_with_default_color(html: str, color: str) -> str:
        if not color:
            return html
        ## if has <head><style>, skip
        style = (
            "<style>"
            f"body {{ color: {color}; }}"
            f'p:not([style*="color"]),'
            f'span:not([style*="color"]),'
            f'li:not([style*="color"]),'
            f'div:not([style*="color"]),'
            f'code:not([style*="color"]),'
            f'pre:not([style*="color"]) {{ color: {color}; }}'
            "</style>"
        )
        head_match = re.search(r"(?is)<\s*head\s*>(.*?)<\s*/\s*head\s*>", html)
        if head_match:
            style_match = re.search(
                r"(?is)<\s*style\b[^>]*>(.*?)<\s*/\s*style\s*>", head_match.group(1)
            )
            if style_match:
                return html
            ## insert <style> in <head> if exists
            head_content = head_match.group(1)
            new_head_content = f"{head_content}" f"{style}"
            return re.sub(
                r"(?is)(<\s*head\s*>)(.*?)(<\s*/\s*head\s*>)",
                lambda m: f"{m.group(1)}{new_head_content}{m.group(3)}",
                html,
                1,
            )
        ## else, insert <head><style></head> after <html> or at start
        html_match = re.search(r"(?is)<\s*html\b[^>]*>", html)
        if html_match:
            insert_pos = html_match.end()
            return f"{html[:insert_pos]}<head>{style}</head>{html[insert_pos:]}"
        return f"<head>{style}</head>{html}"


### test
if __name__ == "__main__":
    import sys

    app = QGuiApplication(sys.argv)

    window = QQuickWindow()
    window.setWidth(360)
    window.setHeight(260)
    window.setTitle("SuperRichTextItem Test")

    root = window.contentItem()
    item = SuperRichTextItem(root)
    item.setParentItem(root)
    item.setWidth(340)
    item.setHeight(220)
    item.setX(10)
    item.setY(10)
    item.setTextColor("#ff0000")
    item.setColor("#ffff00")
    item.setStyledHtml(
        """
        <div style='font-family: Segoe UI, sans-serif; color: #e9ecef;'><h2 style='margin:0 0 8px 0; font-size:22px;'>Dictionary · truncate</h2><div class="OALD9_online" style="clear:both;"><link rel="stylesheet" type="text/css" href="oald9.css"><div id="entryContent" class="oald"><div class="entry" id="truncate"><div class="h-g" id="truncate__1"><div class="top-container"><div class="top-g" id="truncate__2"> <div class="webtop-g"><span class="z"> </span><h2 class="h">truncate</h2><span class="z"> </span><span class="pos">verb</span><button class="OALECD_trans" onclick="toggle_chn();">TRANS</button></div><span class="pos-g" id="truncate__4"><span class="pos" id="truncate__5">verb</span></span> <div class="pron-gs ei-g"><span class="pron-g" id="truncate__7" geo="br"><span class="prefix"><span class="blue">BrE</span></span> <span class="phon"><span class="bre">BrE</span><span class="separator">/</span><span class="wrap">/</span>trʌŋˈkeɪt<span class="wrap">/</span><span class="separator">/</span></span><a href="sound://uk_pron/t/tru/trunc/truncate__gb_1.mp3" class="sound audio_play_button pron-uk icon-audio" title=" pronunciation English" style="cursor: pointer" valign="top">  </a></span><span class="sep">;</span> <span class="pron-g" id="truncate__9" geo="n_am" suppression_override="y"><span class="prefix"><span class="red">NAmE</span></span> <span class="phon"><span class="name">NAmE</span><span class="separator">/</span><span class="wrap">/</span>ˈtrʌŋkeɪt<span class="wrap">/</span><span class="separator">/</span></span><a href="sound://us_pron/t/tru/trunc/truncate__us_1.mp3" class="sound audio_play_button pron-us icon-audio" title=" pronunciation American" style="cursor: pointer" valign="top">  </a></span></div><span class="collapse" title="Verb Forms"><span class="unbox" id="truncate__16"><span class="heading" onclick="toggle_active(this);">Verb Forms</span><span class="body"><span class="vp-g" id="truncate__17" form="root"><span class="vp" id="truncate__18"> <span class="prefix">present simple I / you / we / they</span> truncate</span> <div class="pron-gs ei-g"><span class="pron-g" geo="br" id="truncate__20"><span class="prefix"><span class="blue">BrE</span></span> <span class="phon"><span class="bre">BrE</span><span class="separator">/</span><span class="wrap">/</span>trʌŋˈkeɪt<span class="wrap">/</span><span class="separator">/</span></span><a href="sound://uk_pron/t/tru/trunc/truncate__gb_1.mp3" class="sound audio_play_button pron-uk icon-audio" title=" pronunciation English" style="cursor: pointer" valign="top">  </a></span><span class="sep">;</span> <span class="pron-g" suppression_override="y" id="truncate__22" geo="n_am"><span class="prefix"><span class="red">NAmE</span></span> <span class="phon"><span class="name">NAmE</span><span class="separator">/</span><span class="wrap">/</span>ˈtrʌŋkeɪt<span class="wrap">/</span><span class="separator">/</span></span><a href="sound://us_pron/t/tru/trunc/truncate__us_1.mp3" class="sound audio_play_button pron-us icon-audio" title=" pronunciation American" style="cursor: pointer" valign="top">  </a></span></div></span><span class="vp-g" form="thirdps" id="truncate__24"><span class="vp" id="truncate__25"> <span class="prefix">he / she / it</span> truncates</span> <div class="pron-gs ei-g"><span class="pron-g" id="truncate__27" geo="br"><span class="prefix"><span class="blue">BrE</span></span> <span class="phon"><span class="bre">BrE</span><span class="separator">/</span><span class="wrap">/</span>trʌŋˈkeɪts<span class="wrap">/</span><span class="separator">/</span></span><a href="sound://uk_pron/t/tru/trunc/truncates__gb_1.mp3" class="sound audio_play_button pron-uk icon-audio" title=" pronunciation English" style="cursor: pointer" valign="top">  </a></span><span class="sep">;</span> <span class="pron-g" id="truncate__29" geo="n_am"><span class="prefix"><span class="red">NAmE</span></span> <span class="phon"><span class="name">NAmE</span><span class="separator">/</span><span class="wrap">/</span>ˈtrʌŋkeɪts<span class="wrap">/</span><span class="separator">/</span></span><a href="sound://us_pron/t/tru/trunc/truncates__us_1.mp3" class="sound audio_play_button pron-us icon-audio" title=" pronunciation American" style="cursor: pointer" valign="top">  </a></span></div></span><span class="vp-g" form="past" id="truncate__31"><span class="vp" id="truncate__32"> <span class="prefix">past simple</span> truncated</span> <div class="pron-gs ei-g"><span class="pron-g" id="truncate__34" geo="br"><span class="prefix"><span class="blue">BrE</span></span> <span class="phon"><span class="bre">BrE</span><span class="separator">/</span><span class="wrap">/</span>trʌŋˈkeɪtɪd<span class="wrap">/</span><span class="separator">/</span></span><a href="sound://uk_pron/t/tru/trunc/truncated__gb_1.mp3" class="sound audio_play_button pron-uk icon-audio" title=" pronunciation English" style="cursor: pointer" valign="top">  </a></span><span class="sep">;</span> <span class="pron-g" id="truncate__36" geo="n_am"><span class="prefix"><span class="red">NAmE</span></span> <span class="phon"><span class="name">NAmE</span><span class="separator">/</span><span class="wrap">/</span>ˈtrʌŋkeɪtɪd<span class="wrap">/</span><span class="separator">/</span></span><a href="sound://us_pron/t/tru/trunc/truncated__us_1.mp3" class="sound audio_play_button pron-us icon-audio" title=" pronunciation American" style="cursor: pointer" valign="top">  </a></span></div></span><span class="vp-g" form="pastpart" id="truncate__38"><span class="vp" id="truncate__39"> <span class="prefix">past participle</span> truncated</span> <div class="pron-gs ei-g"><span class="pron-g" geo="br" id="truncate__41"><span class="prefix"><span class="blue">BrE</span></span> <span class="phon"><span class="bre">BrE</span><span class="separator">/</span><span class="wrap">/</span>trʌŋˈkeɪtɪd<span class="wrap">/</span><span class="separator">/</span></span><a href="sound://uk_pron/t/tru/trunc/truncated__gb_1.mp3" class="sound audio_play_button pron-uk icon-audio" title=" pronunciation English" style="cursor: pointer" valign="top">  </a></span><span class="sep">;</span> <span class="pron-g" id="truncate__43" geo="n_am"><span class="prefix"><span class="red">NAmE</span></span> <span class="phon"><span class="name">NAmE</span><span class="separator">/</span><span class="wrap">/</span>ˈtrʌŋkeɪtɪd<span class="wrap">/</span><span class="separator">/</span></span><a href="sound://us_pron/t/tru/trunc/truncated__us_1.mp3" class="sound audio_play_button pron-us icon-audio" title=" pronunciation American" style="cursor: pointer" valign="top">  </a></span></div></span><span class="vp-g" form="prespart" id="truncate__45"><span class="vp" id="truncate__46"> <span class="prefix">-ing form</span> truncating</span> <div class="pron-gs ei-g"><span class="pron-g" id="truncate__48" geo="br"><span class="prefix"><span class="blue">BrE</span></span> <span class="phon"><span class="bre">BrE</span><span class="separator">/</span><span class="wrap">/</span>trʌŋˈkeɪtɪŋ<span class="wrap">/</span><span class="separator">/</span></span><a href="sound://uk_pron/t/tru/trunc/truncating__gb_1.mp3" class="sound audio_play_button pron-uk icon-audio" title=" pronunciation English" style="cursor: pointer" valign="top">  </a></span><span class="sep">;</span> <span class="pron-g" id="truncate__50" geo="n_am"><span class="prefix"><span class="red">NAmE</span></span> <span class="phon"><span class="name">NAmE</span><span class="separator">/</span><span class="wrap">/</span>ˈtrʌŋkeɪtɪŋ<span class="wrap">/</span><span class="separator">/</span></span><a href="sound://us_pron/t/tru/trunc/truncating__us_1.mp3" class="sound audio_play_button pron-us icon-audio" title=" pronunciation American" style="cursor: pointer" valign="top">  </a></span></div></span></span></span></span><div class="clear"> </div> </div></div><span class="sn-gs" id="truncate__52"><span class="sn-g" id="truncate__53"><span class="gram-g" id="truncate__54"><span class="wrap">[</span><span class="gram" id="truncate__55">usually passive</span><span class="wrap">]</span></span> <span class="cf" id="truncate__56"><span class="exp" id="truncate__57">truncate</span> something</span> <span class="label-g" id="truncate__58"><span class="wrap">(</span><span class="reg" id="truncate__59">formal</span><span class="wrap">)</span></span> <span class="def" id="truncate__60">to make something shorter, especially by cutting off the top or end<span class="OALECD_chn O9E">截短，缩短，删节（尤指掐头或去尾）</span> </span><span class="x-gs" id="truncate__61"><span class="x-g" id="truncate__62"> <span class="x" id="truncate__63">My article was published in truncated form.</span><span class="OALECD_audio"> <a href="sound://_truncate__gbs_1.mp3" class="sound pron-uk" title="pronunciation English" style="cursor: pointer">🔊</a> <a href="sound://_truncate__uss_1.mp3" class="sound pron-us" title="pronunciation American" style="cursor: pointer">🔊</a> </span> <span class="OALECD_tx O9E">我的文章以节录的形式发表了。</span> </span><span class="x-g" id="truncate__66"> <span class="x" id="truncate__67">a truncated pyramid</span></span><span class="x-g" id="truncate__68"> <span class="x" id="truncate__69">Further discussion was truncated by the arrival of tea.</span></span></span></span></span><span class="res-g"><span class="collapse" title="Word Origin"><span class="unbox" id="truncate__72"> <span class="heading" onclick="toggle_active(this);">Word Origin</span><span class="body" id="truncate__73"><span class="p" id="truncate__74">late 15th cent...</span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></div></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></div></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></div></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></div></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></div></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></span></div></span></span></span></span></span></div></div></div></div></div></div></link></div></div>
        """,
        open("OALD9.css", "r", encoding="utf-8").read(-1),
        strip_classes=["sound", "pron-gs"],
    )
    item.setCollapsed(False)

    window.show()
    sys.exit(app.exec())
