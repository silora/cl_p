import atexit
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from PySide6.QtCore import (
    Property,
    QAbstractListModel,
    QBuffer,
    QByteArray,
    QIODevice,
    QMetaObject,
    QMimeData,
    QModelIndex,
    QObject,
    Qt,
    QThread,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QImage, QPainter

from item import ClipItem, item_from_row
from operations.llm import run_task
from plugins.calculator import CalculatorPlugin
from plugins.chatgpt import ChatGPTPlugin
from plugins.colorpicker import ColorPickerPlugin
from plugins.datetime import DateTimePlugin
from plugins.dictionary import DictionaryPlugin
from plugins.google import GooglePlugin
from plugins.flaticon import FlaticonPlugin
from plugins.manager import PluginManager
from plugins.trex import TrexPlugin
from storage import Storage
from utils.drawio import is_drawio_payload, url_to_png
from utils.general import normalize_url, parse_color_text, truncate_text
from utils.html import normalize_html_for_qt, truncate_html

try:
    import keyboard  # type: ignore
except Exception:
    keyboard = None

PRINT_COUNTER = 3
PLUGIN_BASE_COLORS: dict[str, str] = {}
PREVIEW_TEXT_LIMIT = 800
PREVIEW_HTML_LIMIT = 1200
PREVIEW_IMAGE_MAX_DIM = 300
PLUGIN_GROUP_ID = -99
PLUGIN_CLIP_ID = -1000


@dataclass
class GroupEntry:
    id: int
    name: str
    is_special: bool = False
    is_plugin: bool = False


class GroupListModel(QAbstractListModel):
    IdRole = Qt.UserRole + 1
    NameRole = Qt.UserRole + 2
    SpecialRole = Qt.UserRole + 3
    PluginRole = Qt.UserRole + 4

    def __init__(self, groups: Optional[list[GroupEntry]] = None, parent=None) -> None:
        super().__init__(parent)
        self._groups: list[GroupEntry] = groups or []

    def rowCount(self, parent=QModelIndex()) -> int:  # type: ignore[override]
        if parent.isValid():
            return 0
        return len(self._groups)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):  # type: ignore[override]
        if not index.isValid():
            return None
        row = index.row()
        if row < 0 or row >= len(self._groups):
            return None
        group = self._groups[row]
        if role == self.IdRole:
            return int(group.id)
        if role == self.NameRole:
            return group.name
        if role == self.SpecialRole:
            return bool(group.is_special)
        if role == self.PluginRole:
            return bool(getattr(group, "is_plugin", False))
        return None

    def roleNames(self) -> dict[int, bytes]:  # type: ignore[override]
        return {
            self.IdRole: b"id",
            self.NameRole: b"name",
            self.SpecialRole: b"isSpecial",
            self.PluginRole: b"isPlugin",
        }

    def set_groups(self, groups: Iterable[GroupEntry]) -> None:
        groups_list = list(groups)
        self.beginResetModel()
        self._groups = groups_list
        self.endResetModel()

    def move_group(self, from_row: int, to_row: int) -> bool:
        if from_row == to_row:
            return False
        if from_row < 0 or to_row < 0:
            return False
        if from_row >= len(self._groups) or to_row >= len(self._groups):
            return False
        # disallow moving special groups (All/Default) and disallow dropping before first user group
        first_user = 0
        while first_user < len(self._groups) and self._groups[first_user].is_special:
            first_user += 1
        if from_row < first_user or to_row < first_user:
            return False
        self.beginMoveRows(
            QModelIndex(),
            from_row,
            from_row,
            QModelIndex(),
            to_row + (1 if to_row > from_row else 0),
        )
        item = self._groups.pop(from_row)
        self._groups.insert(to_row, item)
        self.endMoveRows()
        return True

    @Slot(int, result=int)
    def idAt(self, row: int) -> int:
        if 0 <= row < len(self._groups):
            return int(self._groups[row].id)
        return -1

    @Slot(int, result="QVariantMap")
    def entryAt(self, row: int):
        if 0 <= row < len(self._groups):
            g = self._groups[row]
            return {
                "id": int(g.id),
                "name": g.name,
                "isSpecial": bool(g.is_special),
                "isPlugin": bool(getattr(g, "is_plugin", False)),
            }
        return {}

    def snapshot(self) -> list[GroupEntry]:
        return list(self._groups)

    @Slot(result=int)
    def specialCount(self) -> int:
        return sum(1 for g in self._groups if getattr(g, "is_special", False))


class ClipListModel(QAbstractListModel):
    IdRole = Qt.UserRole + 1
    LabelRole = Qt.UserRole + 2
    TypeRole = Qt.UserRole + 3
    ContentRole = Qt.UserRole + 4
    CreatedRole = Qt.UserRole + 5
    PinnedRole = Qt.UserRole + 6
    GroupRole = Qt.UserRole + 7
    PreviewRole = Qt.UserRole + 8
    SubitemsRole = Qt.UserRole + 9
    TooltipRole = Qt.UserRole + 10
    ContentBlobRole = Qt.UserRole + 11
    HtmlRole = Qt.UserRole + 12
    ColorHexRole = Qt.UserRole + 13
    ColorTextRole = Qt.UserRole + 14
    BaseColorRole = Qt.UserRole + 15
    PreviewTextRole = Qt.UserRole + 16
    HasFullRole = Qt.UserRole + 17
    ContentLengthRole = Qt.UserRole + 18
    CollapsedHeightRole = Qt.UserRole + 19
    ExpandedHeightRole = Qt.UserRole + 20
    RenderModeRole = Qt.UserRole + 21
    PluginIdRole = Qt.UserRole + 22
    ExtraActionsRole = Qt.UserRole + 23
    LastUsedRole = Qt.UserRole + 24

    def __init__(self, clips: Optional[list[ClipItem]] = None, parent=None) -> None:
        super().__init__(parent)
        self._clips: list[ClipItem] = clips or []
        self._clip_by_id: dict[int, ClipItem] = {
            int(c.id): c for c in (clips or []) if getattr(c, "id", None) is not None
        }
        self._row_by_id: dict[int, int] = {
            int(c.id): idx
            for idx, c in enumerate(clips or [])
            if getattr(c, "id", None) is not None
        }
        self._subitems: dict[int, list[dict]] = {}
        self._tooltips: dict[int, str] = {}

    def rowCount(self, parent=QModelIndex()) -> int:  # type: ignore[override]
        if parent.isValid():
            return 0
        return len(self._clips)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):  # type: ignore[override]
        if not index.isValid():
            return None
        row = index.row()
        if row < 0 or row >= len(self._clips):
            return None
        clip = self._clips[row]
        if role == self.IdRole:
            return int(clip.id)
        if role == self.LabelRole:
            return clip.label()
        if role == self.TypeRole:
            return clip.content_type
        if role == self.ContentRole:
            return clip.content_text if clip.has_full_content else clip.preview_text
        if role == self.CreatedRole:
            return int(clip.created_at) * 1000  # QML expects ms
        if role == self.LastUsedRole:
            return (
                int(clip.last_used_at) * 1000 if clip.last_used_at is not None else None
            )
        if role == self.PinnedRole:
            return bool(clip.pinned)
        if role == self.GroupRole:
            return int(clip.group_id)
        if role == self.PreviewRole:
            return self._preview_url(clip)
        if role == self.SubitemsRole:
            return self._subitems.get(int(clip.id), [])
        if role == self.TooltipRole:
            return self._tooltips.get(int(clip.id), "")
        if role == self.ContentBlobRole:
            return self._html_content(clip)
        if role == self.HtmlRole:
            return self._html_content(clip)
        if role == self.ColorHexRole:
            return self._color_data(clip)[0]
        if role == self.ColorTextRole:
            return self._color_data(clip)[1]
        if role == self.BaseColorRole:
            return self._extract_global_bg_color(clip) or ""
        if role == self.PreviewTextRole:
            return clip.preview_text
        if role == self.HasFullRole:
            return bool(getattr(clip, "has_full_content", True))
        if role == self.ContentLengthRole:
            return int(getattr(clip, "content_length", 0))
        if role == self.CollapsedHeightRole:
            return int(getattr(clip, "collapsed_height", 0) or 0)
        if role == self.ExpandedHeightRole:
            return int(getattr(clip, "expanded_height", 0) or 0)
        if role == self.RenderModeRole:
            return str(getattr(clip, "render_mode", "") or "")
        if role == self.PluginIdRole:
            return str(getattr(clip, "plugin_id", "") or "")
        if role == self.ExtraActionsRole:
            return getattr(clip, "extra_actions", []) or []
        return None

    def roleNames(self) -> dict[int, bytes]:  # type: ignore[override]
        return {
            self.IdRole: b"id",
            self.LabelRole: b"label",
            self.TypeRole: b"contentType",
            self.ContentRole: b"contentText",
            self.CreatedRole: b"createdAt",
            self.PinnedRole: b"pinned",
            self.GroupRole: b"groupId",
            self.PreviewRole: b"preview",
            self.SubitemsRole: b"subitems",
            self.TooltipRole: b"tooltip",
            self.ContentBlobRole: b"contentBlob",
            self.HtmlRole: b"htmlContent",
            self.ColorHexRole: b"colorHex",
            self.ColorTextRole: b"colorText",
            self.BaseColorRole: b"baseColor",
            self.PreviewTextRole: b"previewText",
            self.HasFullRole: b"hasFullContent",
            self.ContentLengthRole: b"contentLength",
            self.CollapsedHeightRole: b"collapsedHeight",
            self.ExpandedHeightRole: b"expandedHeight",
            self.RenderModeRole: b"renderMode",
            self.PluginIdRole: b"pluginId",
            self.ExtraActionsRole: b"extraActions",
            self.LastUsedRole: b"lastUsedAt",
        }

    def set_clips(
        self,
        clips: list[ClipItem],
        subitems: Optional[dict[int, list[dict]]] = None,
        tooltips: Optional[dict[int, str]] = None,
    ) -> None:
        self.beginResetModel()
        self._clips = clips
        self._clip_by_id = {
            int(c.id): c for c in clips if getattr(c, "id", None) is not None
        }
        self._row_by_id = {
            int(c.id): idx
            for idx, c in enumerate(clips)
            if getattr(c, "id", None) is not None
        }
        self._subitems = subitems or {}
        self._tooltips = tooltips or {}
        self.endResetModel()

    def clip_for_id(self, cid: int) -> Optional[ClipItem]:
        return self._clip_by_id.get(int(cid))

    @Slot(int, result=int)
    def idAt(self, row: int) -> int:
        if 0 <= row < len(self._clips):
            return int(self._clips[row].id)
        return -1

    @Slot(int, result=int)
    def rowForId(self, cid: int) -> int:
        return int(self._row_by_id.get(int(cid), -1))

    @Slot(int, result=int)
    def indexOfId(self, cid: int) -> int:
        return int(self._row_by_id.get(int(cid), -1))

    def update_clip(self, clip: ClipItem) -> None:
        cid = int(getattr(clip, "id", -1))
        if cid == -1:
            print("invalid clip id, cannot update", cid)
            return
        row = self._row_by_id.get(cid)
        if row is None:
            print("clip id not found in model, cannot update")
            return
        existing = self._clips[row]
        if not getattr(clip, "preview_text", None):
            clip.preview_text = getattr(existing, "preview_text", "")
        if getattr(clip, "preview_blob", None) is None:
            clip.preview_blob = getattr(existing, "preview_blob", None)
        self._clips[row] = clip
        self._clip_by_id[cid] = clip
        self._row_by_id[cid] = row
        idx = self.index(row, 0)
        roles = [
            self.LabelRole,
            self.TypeRole,
            self.ContentRole,
            self.ContentBlobRole,
            self.HtmlRole,
            self.PreviewRole,
            self.PreviewTextRole,
            self.TooltipRole,
            self.BaseColorRole,
            self.ColorHexRole,
            self.ColorTextRole,
            self.HasFullRole,
            self.ContentLengthRole,
            self.CollapsedHeightRole,
            self.ExpandedHeightRole,
            self.RenderModeRole,
            self.PluginIdRole,
            self.ExtraActionsRole,
        ]
        self.dataChanged.emit(idx, idx, roles)

    def _preview_url(self, clip: ClipItem) -> str:
        if clip.content_type not in ("image", "svg+xml", "drawio"):
            return ""
        data: Optional[bytes] = None
        mime = "image/png"
        if clip.content_type == "drawio":
            if clip.preview_blob:
                data = clip.preview_blob
            elif clip.content_blob:
                data = clip.content_blob
            mime = "image/png"
        elif clip.preview_blob:
            data = clip.preview_blob
            mime = "image/png"
        elif clip.content_type == "svg+xml" and clip.content_blob:
            data = clip.content_blob
            mime = "image/svg+xml"
        elif clip.content_type == "image" and clip.content_blob:
            data = clip.content_blob
            mime = "image/png"
        if not data:
            return ""
        try:
            encoded = base64.b64encode(data).decode("ascii")
            return f"data:{mime};base64,{encoded}"
        except Exception:
            return ""

    @staticmethod
    def _html_content(clip: ClipItem) -> str:
        if clip.content_type not in ("html", "color"):
            return ""
        # Prefer preview_blob (already normalized/stripped) before falling back to raw content_blob.
        blob = clip.preview_blob or clip.content_blob
        # if clip.preview_blob is None and clip.content_type == "html":
        #     print("Warning: returning raw HTML content_blob instead of preview_blob")
        if not blob:
            return ""
        try:
            return blob.decode("utf-8", errors="replace")
        except Exception:
            return ""

    @staticmethod
    def _color_data(clip: ClipItem) -> tuple[str, str]:
        if clip.content_type != "color":
            return "", ""
        raw_text = str(clip.content_text or "").strip()
        hex_value = ""
        # Attempt to derive from preview HTML (body bgcolor).
        blob = clip.content_blob or getattr(clip, "preview_blob", None)
        if blob:
            try:
                html = blob.decode("utf-8", errors="replace")
                m = re.search(r"<body[^>]*bgcolor=[\"']([^\"'>]+)", html, re.IGNORECASE)
                if m:
                    hex_value = m.group(1).strip()
            except Exception:
                pass
        return hex_value, raw_text or hex_value

    @staticmethod
    def _extract_global_bg_color(clip: ClipItem) -> Optional[str]:
        pid = str(getattr(clip, "plugin_id", "") or "")
        if pid and pid in PLUGIN_BASE_COLORS:
            return PLUGIN_BASE_COLORS[pid]
        # Allow plugins to drive base color via plain text (fallback if map not set).
        if pid:
            txt_color = parse_color_text(str(clip.content_text or ""))
            if txt_color:
                return txt_color.upper()

        if clip.content_type == "html":
            blob = clip.content_blob
            if not blob:
                return None
            try:
                html = blob.decode("utf-8", errors="replace")
            except Exception:
                return None
            body_match = re.search(
                r"<body[^>]*style=[\"'][^\"']*background(?:-color)?\s*:\s*([^;\"'>]+)",
                html,
                re.IGNORECASE,
            )
            if body_match:
                return body_match.group(1).strip()
            body_bg = re.search(
                r"<body[^>]*bgcolor=[\"']([^\"'>]+)", html, re.IGNORECASE
            )
            if body_bg:
                return body_bg.group(1).strip()
            fragment_match = re.search(
                r"<!--StartFragment-->\s*<div[^>]*style=[\"'][^\"']*background(?:-color)?\s*:\s*([^;\"'>]+)",
                html,
                re.IGNORECASE | re.S,
            )
            if fragment_match:
                return fragment_match.group(1).strip()
            return None
        if clip.content_type == "color":
            hex_value, _ = ClipListModel._color_data(clip)
            return hex_value or None
        return None


class OperationWorker(QThread):
    finishedTask = Signal(int, str, str)  # item_id, task, text
    failedTask = Signal(int, str, str)  # item_id, task, error

    def __init__(
        self, item_id: int, task: str, text: str = "", image: Optional[bytes] = None
    ) -> None:
        super().__init__()
        self._item_id = int(item_id)
        self._task = task
        self._text = text
        self._image = image

    def run(self) -> None:
        try:
            output = run_task(self._image, self._text, self._task)
            self.finishedTask.emit(self._item_id, self._task, output or "")
        except Exception as exc:
            self.failedTask.emit(self._item_id, self._task, str(exc))


class Backend(QObject):
    statusMessage = Signal(str)
    currentGroupChanged = Signal()
    destinationGroupChanged = Signal()
    searchChanged = Signal()
    itemAdded = Signal(int, int)  # item_id, row
    operationRunningChanged = Signal(bool)
    clipboardExtracted = Signal(object)

    def __init__(self, storage: Storage, parent=None) -> None:
        super().__init__(parent)
        self.storage = storage
        self.group_model = GroupListModel()
        self.clip_model = ClipListModel()
        self.plugin_clip_model = ClipListModel()
        self._current_group_id: Optional[int] = None
        self._search_text: str = ""
        self._search_regex: bool = False
        self._search_ignore_case: bool = True
        self._search_filter: int = 0  # 0=all,1=raw text,2=rich,3=url,4=color,5=image
        self._destination_group_id: int = -1
        self._search_pin_filter: int = 0  # 0=all,1=pinned only,2=unpinned only
        self._current_operation: Optional[str] = None
        self._last_clip_text: Optional[str] = None
        self._ignore_next_clip = False
        self._pending_focus_id: Optional[int] = None
        self._window = None
        self._hotkey_handle = None
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self.refresh_items)
        self._clipboard = QGuiApplication.clipboard()
        self._clipboard.dataChanged.connect(self._on_clipboard_changed)
        self.clipboardExtracted.connect(self._handle_clip_future)
        self._op_worker: Optional[OperationWorker] = None
        self._op_running: bool = False
        self._default_group_id: int = self._get_default_group_id()
        self._destination_group_id = self._load_destination_group()
        self._current_group_id = self._load_current_group()
        self._preview_executor = ThreadPoolExecutor(max_workers=2)
        self._preview_jobs: set[int] = set()
        atexit.register(self._preview_executor.shutdown, wait=False)
        self._drawio_preview_jobs: set[int] = set()
        self._drawio_preview_lock = threading.Lock()
        self._plugin_initialized: bool = False
        self._plugin_base_colors: dict[str, str] = {}
        self.plugin_manager = PluginManager(
            group_id=PLUGIN_GROUP_ID,
            clipboard_text_provider=self._clipboard_text_for_plugins,
        )
        self.plugin_manager.register(
            DictionaryPlugin(
                group_id=PLUGIN_GROUP_ID,
                preview_text_limit=PREVIEW_TEXT_LIMIT,
                refresh_callback=self._refresh_plugins,
            )
        )
        self.plugin_manager.register(
            ColorPickerPlugin(
                group_id=PLUGIN_GROUP_ID,
                refresh_callback=self._refresh_plugins,
            )
        )
        self.plugin_manager.register(
            ChatGPTPlugin(
                group_id=PLUGIN_GROUP_ID,
                refresh_callback=self._refresh_plugins,
            )
        )
        self.plugin_manager.register(
            CalculatorPlugin(
                group_id=PLUGIN_GROUP_ID,
                refresh_callback=self._refresh_plugins,
            )
        )
        # self.plugin_manager.register(
        #     TrexPlugin(
        #         group_id=PLUGIN_GROUP_ID,
        #         refresh_callback=self._refresh_plugins,
        #     )
        # )
        self.plugin_manager.register(
            GooglePlugin(
                group_id=PLUGIN_GROUP_ID,
                refresh_callback=self._refresh_plugins,
            )
        )
        self.plugin_manager.register(
            FlaticonPlugin(
                group_id=PLUGIN_GROUP_ID,
                refresh_callback=self._refresh_plugins,
            )
        )
        self.plugin_manager.register(DateTimePlugin(group_id=PLUGIN_GROUP_ID))
        self.refresh_groups()
        self.refresh_items()

    @Property(int, notify=currentGroupChanged)
    def currentGroupId(self) -> int:
        return self._current_group_id if self._current_group_id is not None else -1

    @Property(int, notify=destinationGroupChanged)
    def destinationGroupId(self) -> int:
        return int(self._destination_group_id)

    @Property(str, notify=searchChanged)
    def searchText(self) -> str:
        return self._search_text

    @Property(bool, notify=operationRunningChanged)
    def operationRunning(self) -> bool:
        return self._op_running

    @Property(int, constant=True)
    def pluginsGroupId(self) -> int:
        return int(PLUGIN_GROUP_ID)

    @Property(QObject, constant=True)
    def pluginClipModel(self) -> QObject:
        return self.plugin_clip_model

    @Slot(QObject)
    def setWindow(self, window: QObject) -> None:
        self._window = window
        self._register_hotkeys()

    @Slot()
    def toggleWindow(self) -> None:
        if not self._window:
            return
        self.setWindowVisible(not self._is_window_visible())

    @Slot()
    def showWindow(self) -> None:
        self.setWindowVisible(True)
        try:
            QMetaObject.invokeMethod(self._window, "focusPopup", Qt.QueuedConnection)
        except Exception:
            pass

    @Slot()
    def hideWindow(self) -> None:
        self.setWindowVisible(False)

    @Slot(bool)
    def setWindowVisible(self, on: bool) -> None:
        """Single entrypoint for visibility changes."""
        if not self._window:
            return

        on = bool(on)
        if on == self._is_window_visible():
            return
        if on:
            self._position_window_near_cursor()
            self._apply_visible(True)
            self._bring_to_front()
            self._focus_window()
        else:
            self._apply_visible(False)

    def _clipboard_text_for_plugins(self) -> str:
        txt = ""
        try:
            txt = self._clipboard.text() or ""
        except Exception:
            txt = ""
        if not txt:
            txt = self._last_clip_text or ""
        return txt.strip()

    def refresh_plugin_items(
        self, full: bool = False, clipboard_only: bool = False
    ) -> tuple[list[ClipItem], dict[int, str]]:
        """
        Build/refresh plugin-rendered items.
        - full=True: rebuild everything (resets model).
        - clipboard_only=True: refresh only plugins that depend on clipboard text.
        """
        print(
            "refreshing for",
            "full" if full else "incremental",
            "clipboard only" if clipboard_only else "all plugins",
        )

        def _build_all() -> tuple[list[ClipItem], dict[int, str]]:
            clips_all = self.plugin_manager.build_items()
            tips_all = {
                int(c.id): self._build_tooltip(c.content_text)
                for c in clips_all
                if getattr(c, "id", None) is not None
            }
            self.plugin_clip_model.set_clips(clips_all, subitems={}, tooltips=tips_all)
            return clips_all, tips_all

        # Initial or forced full rebuild.
        if full or self.plugin_clip_model.rowCount() == 0:
            clips, tips = _build_all()
            if self._current_group_id == PLUGIN_GROUP_ID:
                self.clip_model.set_clips(clips, subitems={}, tooltips=tips)
            return clips, tips

        # Incremental refresh: update only needed plugins to avoid destroying alive WebEngineViews.
        clipboard_cache = None
        changed = False
        updated_items: list[ClipItem] = []
        for plugin in self.plugin_manager.plugins:
            uses_clip = getattr(plugin, "uses_clipboard", True)
            if clipboard_only and not uses_clip:
                continue
            clip_txt = ""
            if uses_clip:
                if clipboard_cache is None:
                    clipboard_cache = self._clipboard_text_for_plugins()
                clip_txt = clipboard_cache
            try:
                items = plugin.build_items(clip_txt)
            except Exception:
                continue
            for item in items:
                print(
                    "Updating item from plugin:",
                    plugin.plugin_id,
                    "Item ID:",
                    getattr(item, "id", None),
                )
                cid = int(getattr(item, "id", -1))
                self.plugin_clip_model._tooltips[cid] = self._build_tooltip(
                    item.content_text
                )
                if self.plugin_clip_model.clip_for_id(cid):
                    self.plugin_clip_model.update_clip(item)
                    updated_items.append(item)
                else:
                    changed = True

        # If any item was missing (new plugin etc.), fall back to full rebuild.
        if changed:
            clips, tips = _build_all()
        else:
            clips = self.plugin_clip_model._clips  # type: ignore[attr-defined]
            tips = self.plugin_clip_model._tooltips  # type: ignore[attr-defined]

        # Keep legacy clip_model in sync while plugins group is active.
        if self._current_group_id == PLUGIN_GROUP_ID:
            for item in updated_items:
                cid = int(getattr(item, "id", -1))
                self.clip_model._tooltips[cid] = self.plugin_clip_model._tooltips.get(
                    cid, ""
                )
                if self.clip_model.clip_for_id(cid):
                    self.clip_model.update_clip(item)
                else:
                    changed = True
            if changed:
                self.clip_model.set_clips(clips, subitems={}, tooltips=tips)

        return clips, tips

    def _refresh_plugins(self, clipboard_only: bool = True, full: bool = False) -> None:
        """Rebuild plugin rows; defaults to updating only clipboard-driven plugins."""
        clips, tooltips = self.refresh_plugin_items(
            full=full, clipboard_only=clipboard_only
        )
        if self._current_group_id == PLUGIN_GROUP_ID:
            # Keep the main clip model in sync while the Plugins tab is active.
            self.clip_model.set_clips(clips, subitems={}, tooltips=tooltips)

    @Slot(str, str)
    def pluginAction(self, plugin_id: str, action_id: str) -> None:
        """Dispatch a plugin-specific context action."""
        self.plugin_manager.dispatch_action(plugin_id, action_id, self, None)

    @Slot(str, str, "QVariant")
    def pluginActionWithPayload(self, plugin_id: str, action_id: str, payload) -> None:
        """Dispatch a plugin-specific context action with optional payload."""
        self.plugin_manager.dispatch_action(plugin_id, action_id, self, payload)

    def refresh_single_plugin(self, plugin_id: str) -> None:
        """
        Rebuild only one plugin's items and patch both models.
        """
        try:
            items = self.plugin_manager.build_items_for(plugin_id)
        except Exception:
            return
        if not items:
            return
        for item in items:
            cid = int(getattr(item, "id", -1))
            self.plugin_clip_model._tooltips[cid] = self._build_tooltip(
                item.content_text
            )
            if self.plugin_clip_model.clip_for_id(cid):
                self.plugin_clip_model.update_clip(item)
            else:
                # If missing, fall back to full refresh for safety.
                self.refresh_plugin_items(full=True)
                return
            if self._current_group_id == PLUGIN_GROUP_ID:
                if self.clip_model.clip_for_id(cid):
                    self.clip_model.update_clip(item)
                else:
                    self.clip_model.set_clips(
                        self.plugin_clip_model._clips,  # type: ignore[attr-defined]
                        subitems={},
                        tooltips=self.plugin_clip_model._tooltips,  # type: ignore[attr-defined]
                    )

    def plugin_set_clipboard_and_paste(self, text: str) -> None:
        """Helper for plugins to push text and paste."""
        try:
            self._clipboard.setText(text or "")
            self._last_clip_text = text or ""
        except Exception:
            pass
        # Hide first so the keystroke targets the previous foreground window.
        # self.setWindowVisible(False)
        # QTimer.singleShot(60, self._paste_to_foreground)
        print("Pasting to foreground window...", text)
        QTimer.singleShot(0, self._paste_to_foreground)
        self.setWindowVisible(False)

    def refresh_groups(self) -> None:
        default_id = self._get_default_group_id()
        special_groups = [GroupEntry(id=-1, name="All", is_special=True)]
        user_groups: list[GroupEntry] = []
        for row in self.storage.list_groups():
            gid = int(row["id"])
            name = str(row["name"])
            is_default = gid == default_id or name.lower() == "default"
            entry = GroupEntry(
                id=gid, name=name, is_special=is_default, is_plugin=False
            )
            if entry.is_special:
                special_groups.append(entry)
            else:
                user_groups.append(entry)
        plugin_group = GroupEntry(
            id=PLUGIN_GROUP_ID, name="Plugins", is_special=True, is_plugin=True
        )
        # Place Plugins before "All" to make it the first tab.
        groups = [plugin_group] + special_groups + user_groups
        self.group_model.set_groups(groups)
        self.currentGroupChanged.emit()
        if not self.storage.group_exists(self._destination_group_id):
            self._destination_group_id = self._get_default_group_id()
            self._persist_destination_group(self._destination_group_id)
        self.destinationGroupChanged.emit()

    def refresh_items(self) -> None:
        if self._current_group_id == PLUGIN_GROUP_ID and not self._plugin_initialized:
            # First entry gets a full build; later refreshes update clipboard-driven plugins only.
            clips, tooltips = self.refresh_plugin_items(
                full=not self._plugin_initialized,
                clipboard_only=self._plugin_initialized,
            )
            self._plugin_initialized = True
            # Maintain clip_model for legacy bindings while plugin list is shown.
            self.clip_model.set_clips(clips, subitems={}, tooltips=tooltips)
            return
        rows = self.storage.list_items(self._current_group_id, None, previews_only=True)
        clips = [item_from_row(row) for row in rows]
        self._maybe_backfill_previews(clips)
        # optional filter by type
        if self._search_filter == 1:  # raw text
            clips = [c for c in clips if c.content_type == "text"]
        elif self._search_filter == 2:  # rich/html
            clips = [c for c in clips if c.content_type == "html"]
        elif self._search_filter == 3:  # url subitems or content containing url
            url_re = re.compile(r"https?://|www\\.", re.IGNORECASE)
            clips = [c for c in clips if url_re.search(c.content_text or "")]
        elif self._search_filter == 4:  # color
            clips = [c for c in clips if c.content_type == "color"]
        elif self._search_filter == 5:  # image
            clips = [
                c for c in clips if c.content_type in ("image", "svg+xml", "drawio")
            ]
        elif self._search_filter == 6:  # vector (svg / drawio)
            clips = [c for c in clips if c.content_type in ("svg+xml", "drawio")]

        if self._search_pin_filter == 1:  # pinned only
            clips = [c for c in clips if c.pinned]
        elif self._search_pin_filter == 2:  # unpinned only
            clips = [c for c in clips if not c.pinned]

        if self._search_text:
            txt = self._search_text
            if self._search_regex:
                flags = re.IGNORECASE if self._search_ignore_case else 0
                try:
                    pattern = re.compile(txt, flags)
                    clips = [c for c in clips if pattern.search(c.content_text or "")]
                except re.error:
                    pass
            else:
                if self._search_ignore_case:
                    tnorm = txt.lower()
                    clips = [
                        c for c in clips if tnorm in (c.content_text or "").lower()
                    ]
                else:
                    clips = [c for c in clips if txt in (c.content_text or "")]

        subitems = self._subitems_map(clips)
        tooltips = {
            int(c.id): self._build_tooltip(c.content_text)
            for c in clips
            if getattr(c, "id", None) is not None
        }
        self.clip_model.set_clips(clips, subitems=subitems, tooltips=tooltips)
        if self._pending_focus_id is not None:
            row = self.clip_model.rowForId(int(self._pending_focus_id))
            self.itemAdded.emit(int(self._pending_focus_id), int(row))
            self._pending_focus_id = None

    @Slot(int)
    def selectGroup(self, group_id: int) -> None:
        if int(group_id) == PLUGIN_GROUP_ID:
            new_gid = PLUGIN_GROUP_ID
        elif group_id < 0:
            new_gid = None
        else:
            new_gid = int(group_id)
        if new_gid == self._current_group_id:
            return
        # If leaving the plugins group, ensure plugin workers are stopped.
        if self._current_group_id == PLUGIN_GROUP_ID and new_gid != PLUGIN_GROUP_ID:
            try:
                self.plugin_manager.teardown()
            except Exception:
                pass
        self._current_group_id = new_gid
        self._persist_current_group(new_gid)
        self.currentGroupChanged.emit()
        self.refresh_items()

    @Slot(int)
    def setDestinationGroup(self, group_id: int) -> None:
        gid = int(group_id)
        if gid < 0:
            return
        if not self.storage.group_exists(gid):
            self.statusMessage.emit("Destination group no longer exists.")
            return
        if gid == self._destination_group_id:
            return
        self._destination_group_id = gid
        self._persist_destination_group(gid)
        self.destinationGroupChanged.emit()

    @Slot(str, bool, bool, int, int)
    def setSearch(
        self,
        text: str,
        regex: bool = False,
        ignore_case: bool = True,
        filter_type: int = 0,
        pinned_filter: int = 0,
    ) -> None:
        self._search_text = text.strip()
        self._search_regex = bool(regex)
        self._search_ignore_case = bool(ignore_case)
        self._search_filter = int(filter_type)
        self._search_pin_filter = int(pinned_filter)
        self.searchChanged.emit()
        self._search_timer.start(120)

    @Slot(str, str)
    def pluginSetBaseColor(self, plugin_id: str, color_hex: str) -> None:
        norm = parse_color_text(color_hex or "")
        if not norm:
            return
        PLUGIN_BASE_COLORS[str(plugin_id or "")] = norm.upper()
        if self._current_group_id == PLUGIN_GROUP_ID:
            self.refresh_items()

    @Slot(str, result=str)
    def getPluginBaseColor(self, plugin_id: str) -> str:
        return PLUGIN_BASE_COLORS.get(str(plugin_id or ""), "") or ""

    @Slot(int, result="QVariantList")
    def subitemsFor(self, item_id: int):
        return self._subitems_for_item(int(item_id))

    @Slot(int, str)
    @Slot(int, str, bool)
    def activateSubitem(self, item_id: int, text: str, paste: bool = False) -> None:
        content = (text or "").strip()
        if not content:
            return
        # If it's a file path, open it directly instead of copying.
        path = Path(content)
        if path.is_absolute() and path.exists():
            self.openFilePath(content)
            return

        self._ignore_next_clip = True
        self._clipboard.setText(content)
        self._last_clip_text = content
        try:
            self.storage.touch_item_last_used(int(item_id))
        except Exception:
            pass
        if paste:
            QTimer.singleShot(0, self._paste_to_foreground)
            self.setWindowVisible(False)

    @Slot(int, str)
    def promoteSubitem(self, item_id: int, text: str) -> None:
        content = (text or "").strip()
        if not content:
            return
        group_id = self._current_group_id or self._get_default_group_id()
        preview_text, preview_blob = self._build_previews("text", content, None)
        new_id = self.storage.add_item(
            "text",
            content,
            None,
            preview_text,
            preview_blob,
            int(time.time()),
            group_id,
        )
        self._pending_focus_id = new_id
        self.refresh_items()

    @Slot(str, int, result=str)
    def truncateText(
        self, text: str, limit: int = 800
    ) -> str:  # pragma: no cover - utility
        return truncate_text(text, limit)

    @Slot(str)
    def openFilePath(self, path_str: str) -> None:
        """Open a file path using the OS default handler."""
        p_raw = (path_str or "").strip().strip('"').strip("'")
        if not p_raw:
            return
        p = Path(p_raw)
        if not p.is_absolute():
            p = Path.cwd() / p
        try:
            if sys.platform == "win32":
                os.startfile(str(p))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(p)])
            else:
                subprocess.Popen(["xdg-open", str(p)])
        except Exception as exc:
            print(f"Failed to open file {p}: {exc}")

    @Slot(str, int, result=str)
    def truncateHtml(
        self, html: str, limit: int = 800
    ) -> str:  # pragma: no cover - utility
        return truncate_html(html, limit)

    @Slot(int, str)
    def runOperation(self, item_id: int, task: str) -> None:
        clip = self._ensure_full_clip(item_id)
        if not clip:
            return
        if self._op_worker and self._op_worker.isRunning():
            return
        self._current_operation = (task or "").strip() or None
        if self._current_operation:
            self.statusMessage.emit(f"Running {self._current_operation}...")
        self._set_op_running(True)
        text_payload = clip.content_text or ""
        image_blob: Optional[bytes] = None
        if clip.content_type == "image":
            image_blob = clip.content_blob
            text_payload = None
        self._op_worker = OperationWorker(
            int(item_id), task, text=text_payload, image=image_blob
        )
        self._op_worker.finishedTask.connect(self._on_operation_finished)
        self._op_worker.failedTask.connect(self._on_operation_failed)
        self._op_worker.start()

    @Slot(str)
    def createGroup(self, name: str) -> None:
        cleaned = name.strip()
        if not cleaned:
            return
        try:
            self.storage.create_group(cleaned)
        except Exception:
            self.statusMessage.emit("Group already exists.")
        self.refresh_groups()

    @Slot(int, str)
    def renameGroup(self, group_id: int, name: str) -> None:
        if group_id < 0:
            return
        cleaned = name.strip()
        if not cleaned:
            return
        self.storage.rename_group(int(group_id), cleaned)
        self.refresh_groups()

    @Slot(int)
    def deleteGroup(self, group_id: int) -> None:
        if group_id < 0:
            return
        # Do not delete default group to avoid wiping everything accidentally.
        if self._is_default_group(group_id):
            self.statusMessage.emit("Default group cannot be deleted.")
            return
        self.storage.delete_group(int(group_id))
        if self._current_group_id == int(group_id):
            self._current_group_id = None
        if self._destination_group_id == int(group_id):
            self._destination_group_id = self._get_default_group_id()
            self._persist_destination_group(self._destination_group_id)
            self.destinationGroupChanged.emit()
        self.refresh_groups()
        self.refresh_items()

    @Slot(int, int)
    def reorderGroups(self, from_row: int, to_row: int) -> None:
        if from_row < 0 or to_row < 0:
            return
        moved = self.group_model.move_group(int(from_row), int(to_row))
        if not moved:
            return
        ordered_ids = [
            int(g.id)
            for g in self.group_model.snapshot()
            if int(getattr(g, "id", -1)) >= 0
        ]
        try:
            self.storage.update_group_positions(ordered_ids)
        except Exception:
            pass
        self.refresh_groups()

    @Slot(int)
    def togglePin(self, item_id: int) -> None:
        clip = self.clip_model.clip_for_id(item_id)
        if not clip:
            return
        new_val = not bool(clip.pinned)
        self.storage.set_pinned(int(item_id), new_val)
        self._pending_focus_id = int(item_id)
        self.refresh_items()

    @Slot(int)
    def deleteItem(self, item_id: int) -> None:
        self.storage.delete_item(int(item_id))
        self.refresh_items()

    @Slot(int)
    def addSubitemExample(self, item_id: int) -> None:
        if item_id is None or item_id < 0:
            return
        sample = {
            "tag": "example",
            "text": "Example subitem",
            "icons": [],
        }
        self._replace_subitem(int(item_id), sample["text"], sample["tag"])
        self._pending_focus_id = int(item_id)
        self.refresh_items()

    @Slot(int, str)
    def addNoteSubitem(self, item_id: int, text: str) -> None:
        if item_id is None or item_id < 0:
            return
        note = (text or "").strip()
        if not note:
            return
        # Allow multiple notes: append instead of replacing existing ones.
        try:
            self.storage.add_subitem(int(item_id), note, icons=None, tag="note")
        except Exception:
            return
        self._pending_focus_id = int(item_id)
        self.refresh_items()

    @Slot(int)
    def loadItemContent(self, item_id: int) -> None:
        self._ensure_full_clip(int(item_id))

    @Slot(int, bool)
    def activateItem(self, item_id: int, paste: bool = False) -> None:
        clip = self._ensure_full_clip(item_id)
        if not clip:
            return
        self._push_to_clipboard(clip)
        if paste:
            QTimer.singleShot(0, self._paste_to_foreground)
            self.setWindowVisible(False)

    @Slot(int)
    def pasteHtmlAsText(self, item_id: int) -> None:
        clip = self._ensure_full_clip(item_id)
        if not clip:
            return
        if clip.content_type != "html":
            return
        text = clip.content_text or ""
        self._ignore_next_clip = True
        self._clipboard.setText(text)
        self._last_clip_text = text
        try:
            if getattr(clip, "id", None) is not None:
                self.storage.touch_item_last_used(int(clip.id))
        except Exception:
            pass
        QTimer.singleShot(0, self._paste_to_foreground)
        self.setWindowVisible(False)

    @Slot(int)
    def pasteHtmlRaw(self, item_id: int) -> None:
        clip = self._ensure_full_clip(item_id)
        if not clip:
            return
        if clip.content_type != "html":
            return
        if not clip.content_blob:
            return
        html = clip.content_blob.decode("utf-8", errors="replace")
        mime = QMimeData()
        mime.setText(html)
        # text = str(clip.content_text or "")
        # if text:
        #     mime.setText(text)
        self._ignore_next_clip = True
        self._clipboard.setMimeData(mime)
        self._last_clip_text = html
        try:
            if getattr(clip, "id", None) is not None:
                self.storage.touch_item_last_used(int(clip.id))
        except Exception:
            pass
        QTimer.singleShot(0, self._paste_to_foreground)
        self.setWindowVisible(False)

    @staticmethod
    def _color_formats(hex_value: str) -> dict[str, str]:
        hv = (hex_value or "").strip()
        if not hv.startswith("#"):
            hv = "#" + hv
        hv = hv.upper()
        if len(hv) == 4:  # #RGB -> #RRGGBB
            hv = "#" + "".join(ch * 2 for ch in hv[1:])
        if len(hv) not in (7, 9):
            return {"hex": hv}
        try:
            r = int(hv[1:3], 16)
            g = int(hv[3:5], 16)
            b = int(hv[5:7], 16)
        except Exception:
            return {"hex": hv}
        try:
            import colorsys

            h, l, s = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
            h_deg = round(h * 360)
            s_pct = round(s * 100)
            l_pct = round(l * 100)
            hsl = f"hsl({h_deg}, {s_pct}%, {l_pct}%)"
        except Exception:
            hsl = ""
        rgb = f"rgb({r}, {g}, {b})"
        return {"hex": hv, "rgb": rgb, "hsl": hsl}

    @Slot(int, str)
    def pasteColor(self, item_id: int, fmt: str) -> None:
        clip = self._ensure_full_clip(item_id)
        if not clip or clip.content_type != "color":
            return
        hex_value, _ = ClipListModel._color_data(clip)
        formats = self._color_formats(hex_value)
        key = (fmt or "").lower()
        text = formats.get(key) or formats.get("hex") or hex_value
        text = text or hex_value
        if not text:
            return
        self._ignore_next_clip = True
        self._clipboard.setText(text)
        self._last_clip_text = text
        try:
            if getattr(clip, "id", None) is not None:
                self.storage.touch_item_last_used(int(clip.id))
        except Exception:
            pass
        QTimer.singleShot(0, self._paste_to_foreground)
        self.setWindowVisible(False)

    @Slot(int)
    def copyScaledImage(self, item_id: int) -> None:
        clip = self._ensure_full_clip(item_id)
        if not clip:
            return
        if clip.content_type != "image" or not clip.content_blob:
            return
        image = QImage.fromData(clip.content_blob)
        if image.isNull():
            return
        max_dim = 300
        if image.width() > max_dim or image.height() > max_dim:
            image = image.scaled(
                max_dim, max_dim, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        self._ignore_next_clip = True
        self._clipboard.setImage(image)
        QTimer.singleShot(0, self._paste_to_foreground)
        self.setWindowVisible(False)

    @Slot(int)
    def pasteDrawio(self, item_id: int) -> None:
        """Copy draw.io SVG preview to clipboard; keep original text untouched."""
        clip = self._ensure_full_clip(item_id)
        if not clip:
            return
        if clip.content_type != "drawio":
            return
        data = self._drawio_preview_png_bytes(clip)
        if not data:
            return
        mime = QMimeData()
        img = QImage.fromData(data)
        if img.isNull():
            return
        mime.setImageData(img)
        self._ignore_next_clip = True
        self._clipboard.setMimeData(mime)
        QTimer.singleShot(0, self._paste_to_foreground)
        self.setWindowVisible(False)

    @Slot(int)
    def pasteVectorPng(self, item_id: int) -> None:
        """Convert draw.io or svg+xml to PNG via draw.io CLI and copy/paste."""
        clip = self._ensure_full_clip(item_id)
        if not clip:
            return
        if clip.content_type not in ("drawio", "svg+xml"):
            return
        payload = (clip.content_text or "").strip()
        if not payload:
            return
        try:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            tmp.close()
            png_path = Path(tmp.name)
        except Exception:
            return

        try:
            if clip.content_type == "drawio":
                url_to_png(payload, output_png=str(png_path))
            else:
                # For SVG content, render directly.
                img = QImage.fromData(clip.content_blob or b"")
                if not img.isNull():
                    img.save(str(png_path), "PNG")
                else:
                    return
            img = QImage(str(png_path))
            if img.isNull():
                return
            self._ignore_next_clip = True
            self._clipboard.setImage(img)
            QTimer.singleShot(0, self._paste_to_foreground)
            self.setWindowVisible(False)
        except Exception:
            return
        finally:
            try:
                png_path.unlink(missing_ok=True)  # type: ignore[arg-type]
            except Exception:
                pass

    @Slot(int, int)
    def moveItemToGroup(self, item_id: int, group_id: int) -> None:
        if group_id < 0:
            return
        self.storage.move_item_to_group(int(item_id), int(group_id))
        self.refresh_items()

    @Slot(int, int)
    def deleteSubitem(self, item_id: int, subitem_id: int) -> None:
        if subitem_id is None or subitem_id < 0:
            return
        self.storage.delete_subitem(int(subitem_id))
        # refresh to update subitems map and UI
        self._pending_focus_id = int(item_id)
        self.refresh_items()

    def _build_move_targets(self, source_group_id: Optional[int]) -> list[dict]:
        current = -1 if source_group_id is None else int(source_group_id)
        targets: list[dict] = []
        for g in self.group_model.snapshot():
            gid = int(getattr(g, "id", -1))
            if gid < 0:
                continue
            is_current = current >= 0 and gid == current
            targets.append(
                {
                    "id": gid,
                    "name": getattr(g, "name", ""),
                    "isSpecial": bool(getattr(g, "is_special", False)),
                    "isCurrent": is_current,
                    "tags": ["current-item-group"] if is_current else [],
                }
            )
        return targets

    @Slot(result="QVariantList")
    def moveTargetsForCurrentGroup(self):
        current = self._current_group_id if self._current_group_id is not None else -1
        return self._build_move_targets(current)

    @Slot(int, result="QVariantList")
    def moveTargetsForItem(self, item_id: int):
        source_group = -1
        clip = self.clip_model.clip_for_id(int(item_id))
        if clip:
            source_group = int(getattr(clip, "group_id", -1))
        return self._build_move_targets(source_group)

    def _load_destination_group(self) -> int:
        raw = self.storage.get_setting("destination_group_id")
        default_gid = self._get_default_group_id()
        try:
            gid = int(raw) if raw is not None else default_gid
        except Exception:
            gid = default_gid
        if not self.storage.group_exists(gid):
            gid = default_gid
        self.storage.set_setting("destination_group_id", str(gid))
        return gid

    def _persist_destination_group(self, gid: int) -> None:
        self.storage.set_setting("destination_group_id", str(int(gid)))

    def _get_destination_group_id(self) -> int:
        gid = self._destination_group_id
        if gid is None or gid < 0 or not self.storage.group_exists(gid):
            gid = self._get_default_group_id()
            self._destination_group_id = gid
            self._persist_destination_group(gid)
            self.destinationGroupChanged.emit()
        return int(gid)

    def _load_current_group(self) -> Optional[int]:
        raw = self.storage.get_setting("current_group_id")
        try:
            gid = int(raw) if raw is not None and str(raw).strip() != "" else None
        except Exception:
            gid = None
        if gid is not None and not self.storage.group_exists(gid):
            gid = None
        return gid

    def _persist_current_group(self, gid: Optional[int]) -> None:
        if gid is None:
            self.storage.set_setting("current_group_id", "")
        else:
            self.storage.set_setting("current_group_id", str(int(gid)))

    def _is_default_group(self, group_id: int) -> bool:
        group = self.storage.get_group_by_name("Default")
        return bool(group and int(group["id"]) == int(group_id))

    def _register_hotkeys(self) -> None:
        if not keyboard:
            return
        try:
            if self._hotkey_handle is not None:
                try:
                    keyboard.remove_hotkey(self._hotkey_handle)
                except Exception:
                    pass

            def _show_from_hotkey() -> None:
                # Schedule on the Qt thread to avoid cross-thread UI calls.
                try:
                    QMetaObject.invokeMethod(self, "showWindow", Qt.QueuedConnection)
                except Exception:
                    QTimer.singleShot(0, self.showWindow)
                try:
                    # Release Alt so Windows doesn't keep menu focus in other apps.
                    keyboard.release("alt")
                except Exception:
                    pass

            # suppress=True ensures we intercept Alt+V even if another app registers it.
            self._hotkey_handle = keyboard.add_hotkey(
                "alt+v", _show_from_hotkey, suppress=True
            )
        except Exception:
            self._hotkey_handle = None

    def _subitems_for_item(self, item_id: int) -> list[dict]:
        results: list[dict] = []
        try:
            for row in self.storage.list_subitems(int(item_id)):
                try:
                    icons = json.loads(row["icons"] or "[]")
                except Exception:
                    icons = []
                results.append(
                    {
                        "id": int(row["id"]),
                        "text": str(row["text"] or ""),
                        "tag": row["tag"] or "",
                        "icons": icons,
                    }
                )
        except Exception:
            pass
        return results

    def _subitems_map(self, clips: list[ClipItem]) -> dict[int, list[dict]]:
        mapping: dict[int, list[dict]] = {}
        for clip in clips:
            if getattr(clip, "id", None) is None:
                continue
            mapping[int(clip.id)] = self._subitems_for_item(int(clip.id))
        return mapping

    def _on_operation_finished(self, item_id: int, task: str, text: str) -> None:
        worker = self._op_worker
        self._op_worker = None
        if worker:
            worker.deleteLater()
        content = (text or "").strip()
        if content:
            tag = (task or "").lower() or None
            try:
                if tag:
                    self._replace_subitem(int(item_id), content, tag)
                else:
                    self.storage.add_subitem(int(item_id), content, icons=None, tag=tag)
                # if task.lower() != "url":
                #     self._add_url_subitems(int(item_id), content)
            except Exception:
                pass
            self._pending_focus_id = int(item_id)
        self.refresh_items()
        if self._current_operation:
            self.statusMessage.emit(f"{self._current_operation} finished.")
        self._set_op_running(False)

    def _on_operation_failed(self, item_id: int, task: str, err: str) -> None:
        worker = self._op_worker
        self._op_worker = None
        if worker:
            worker.deleteLater()
        self.statusMessage.emit(f"{task} failed: {err}")
        self._set_op_running(False)

    def _set_op_running(self, val: bool) -> None:
        val = bool(val)
        if self._op_running == val:
            return
        self._op_running = val
        self.operationRunningChanged.emit(self._op_running)
        if not val:
            self._current_operation = None

    def _add_url_subitems(self, item_id: int, text: str) -> None:
        if not text:
            return
        url_pattern = re.compile(
            r"(?:(?:https?://)|(?:www\.))" r"[\w\-._~:/?#\[\]@!$&'()*+,;=%]+",
            re.IGNORECASE,
        )

        try:
            existing = self.storage.list_subitems(int(item_id))
            existing_urls = {
                normalize_url(str(s["text"]))
                for s in existing
                if str(s.get("tag") or "").lower() == "url"
            }
        except Exception:
            existing_urls = set()

        urls: list[str] = []
        seen: set[str] = set()
        for m in url_pattern.finditer(text):
            url = m.group(0)
            url_norm = normalize_url(url)
            if not url_norm:
                continue
            if url_norm in seen:
                continue
            seen.add(url_norm)
            urls.append(url_norm)
            if len(urls) >= 20:
                break
        if not urls:
            return
        try:
            for u in urls:
                if u in existing_urls:
                    continue
                self.storage.add_subitem(int(item_id), u, icons=[], tag="url")
        except Exception:
            pass

    def _add_file_subitems(self, item_id: int, text: str) -> None:
        """Detect file paths in text and add as subitems (tag=file)."""
        if not text:
            return

        # Matches Windows drive paths, UNC paths, or absolute *nix paths; stops at whitespace/punctuation.
        path_pattern = re.compile(
            r"(?<![A-Za-z])"  # no letter immediately before
            r"(?P<path>[A-Z]:[\\/]"  # CAPITAL drive root only
            r"[^\s<>\"|*?:]+"  # first segment
            r"(?:[\\/][^\s<>\"|*?:]+)*)"  # more segments
            r"(?=(?::\d+(?::\d+)?)?(?::)?(?:\s|$))",  # stop before :line(:col):
            re.UNICODE,
        )

        try:
            existing = self.storage.list_subitems(int(item_id))
            existing_paths = {
                str(s["text"]).strip()
                for s in existing
                if str(s.get("tag") or "").lower() == "file"
            }
        except Exception:
            existing_paths = set()

        paths: list[str] = []
        seen: set[str] = set()
        for m in path_pattern.finditer(text):
            path_txt = m.group(0).strip().strip('"').strip("'")
            if not path_txt or path_txt.lower().startswith(("http://", "https://")):
                continue
            # Avoid trailing punctuation
            path_txt = path_txt.rstrip(".,;)")
            if path_txt in seen:
                continue
            seen.add(path_txt)
            paths.append(path_txt)
            if len(paths) >= 20:
                break
        if not paths:
            return

        try:
            for p in paths:
                if p in existing_paths:
                    continue
                self.storage.add_subitem(int(item_id), p, icons=[], tag="file")
        except Exception:
            pass

    def _replace_subitem(self, item_id: int, text: str, tag: Optional[str]) -> None:
        if not tag:
            return
        try:
            self.storage.delete_subitems_by_tag(int(item_id), tag)
            self.storage.add_subitem(int(item_id), text, icons=None, tag=tag)
        except Exception:
            pass

    @staticmethod
    def _build_tooltip(text: str) -> str:
        tooltip_text = text or ""
        tooltip_text = tooltip_text.strip()
        if not tooltip_text:
            return ""
        lines = tooltip_text.splitlines()
        if len(lines) > 20:
            tooltip_text = "\\n".join(lines[:20]) + "\\n..."
        if len(tooltip_text) > 2000:
            tooltip_text = tooltip_text[:2000] + "..."
        return tooltip_text

    def _build_previews(
        self, content_type: str, content_text: str, content_blob: Optional[bytes]
    ) -> tuple[str, Optional[bytes]]:
        ctype = content_type or "text"
        if ctype == "text":
            return truncate_text(content_text or "", PREVIEW_TEXT_LIMIT), None
        if ctype == "color":
            preview_text = truncate_text(content_text or "", PREVIEW_TEXT_LIMIT)
            normalized = parse_color_text(content_text or "")
            preview_blob = None
            if normalized:
                color_css = normalized
                r = g = b = 0
                try:
                    if normalized.startswith("#"):
                        hexv = normalized.upper()
                        color_css = hexv
                        r = int(hexv[1:3], 16)
                        g = int(hexv[3:5], 16)
                        b = int(hexv[5:7], 16)
                    else:
                        # rgb or rgba
                        nums = [
                            int(float(x)) for x in re.findall(r"[\d.]+", normalized)[:3]
                        ]
                        if len(nums) == 3:
                            r, g, b = nums
                except Exception:
                    r = g = b = 0
                lum = 0.299 * r + 0.587 * g + 0.114 * b
                text_color = "#000000" if lum > 128 else "#ffffff"
                color_html = (
                    f"<body bgcolor='{color_css}' style='display:flex;align-items:center;"
                    f"justify-content:center;min-height:140px;text-align:center;"
                    f"color:{text_color};'>"
                    f"<div>{content_text}</div></body>"
                )
                preview_blob = color_html.encode("utf-8", errors="replace")
            return preview_text, preview_blob
        if ctype == "html":
            preview_text = truncate_text(content_text or "", PREVIEW_TEXT_LIMIT)
            html_str = ""
            if content_blob:
                try:
                    html_str = content_blob.decode("utf-8", errors="replace")
                except Exception:
                    html_str = ""
            normalized = normalize_html_for_qt(html_str, strip_classes=None)
            preview_blob = (
                normalized.encode("utf-8", errors="replace") if normalized else None
            )
            return preview_text, preview_blob
        if ctype in ("image", "svg+xml", "drawio"):
            png_bytes = self._build_image_preview(ctype, content_text, content_blob)
            return "", png_bytes
        return truncate_text(content_text or "", PREVIEW_TEXT_LIMIT), None

    def _build_image_preview(
        self,
        content_type: str,
        content_text: str,
        content_blob: Optional[bytes],
    ) -> Optional[bytes]:
        if content_type == "drawio":
            return None  # draw.io previews are generated asynchronously
        blob = content_blob
        if not blob:
            return None
        image = QImage.fromData(blob)
        if image.isNull():
            return None
        if (
            image.width() > PREVIEW_IMAGE_MAX_DIM
            or image.height() > PREVIEW_IMAGE_MAX_DIM
        ):
            image = image.scaled(
                PREVIEW_IMAGE_MAX_DIM,
                PREVIEW_IMAGE_MAX_DIM,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
        return self._image_to_bytes(image)

    def _schedule_preview_build(
        self,
        item_id: int,
        content_type: str,
        content_text: str,
        content_blob: Optional[bytes],
        preview_blob: Optional[bytes] = None,
    ) -> None:
        if item_id is None:
            return
        if content_type == "drawio":
            return  # draw.io previews are handled separately
        if content_type in ("image", "svg+xml") and not content_blob:
            return
        if item_id in self._preview_jobs:
            return

        def worker() -> tuple[str, Optional[bytes]]:
            return self._build_previews(content_type, content_text, content_blob)

        self._preview_jobs.add(int(item_id))
        future = self._preview_executor.submit(worker)

        def handle_future(fut) -> None:
            try:
                preview_text, preview_blob = fut.result()
            except Exception:
                preview_text, preview_blob = None, None

            def apply() -> None:
                self._preview_jobs.discard(int(item_id))
                if preview_text is None and preview_blob is None:
                    return
                self._apply_preview_result(int(item_id), preview_text, preview_blob)

            QTimer.singleShot(0, apply)
            # apply()

        future.add_done_callback(handle_future)

    def _apply_preview_result(
        self, clip_id: int, preview_text: Optional[str], preview_blob: Optional[bytes]
    ) -> None:
        clip = self.clip_model.clip_for_id(int(clip_id))
        if clip:
            changed = False
            if preview_text is not None and preview_text != clip.preview_text:
                clip.preview_text = preview_text
                changed = True
            if preview_blob is not None and preview_blob != clip.preview_blob:
                clip.preview_blob = preview_blob
                changed = True
            if changed:
                self.clip_model.update_clip(clip)
        try:
            if "xxx" in preview_text:
                print("Updating preview for item", clip_id)
            self.storage.update_preview(int(clip_id), preview_text, preview_blob)
        except Exception:
            pass

    def _drawio_preview_png_bytes(self, clip: ClipItem) -> Optional[bytes]:
        payload = (clip.content_text or "").strip()
        return self._drawio_png_from_payload(payload, clip.content_blob)

    def _schedule_drawio_preview(self, clip: ClipItem) -> None:
        cid = getattr(clip, "id", None)
        payload = (clip.content_text or "").strip()
        if cid is None or not payload:
            return
        with self._drawio_preview_lock:
            if cid in self._drawio_preview_jobs:
                return
            self._drawio_preview_jobs.add(int(cid))
        existing_blob = clip.content_blob

        def worker() -> None:
            data = self._drawio_png_from_payload(payload, existing_blob)

            def apply() -> None:
                try:
                    self._apply_drawio_preview(int(cid), data)
                finally:
                    with self._drawio_preview_lock:
                        self._drawio_preview_jobs.discard(int(cid))

            QTimer.singleShot(0, apply)

        threading.Thread(target=worker, daemon=True).start()

    def _drawio_png_from_payload(
        self, payload: str, existing_blob: Optional[bytes]
    ) -> Optional[bytes]:
        if existing_blob:
            img = QImage.fromData(existing_blob)
            if not img.isNull():
                return existing_blob
        clean = (payload or "").strip()
        if not clean:
            return None

        tmp_png: Optional[tempfile.NamedTemporaryFile] = None
        try:
            tmp_png = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            tmp_png.close()
            png_path = Path(tmp_png.name)
        except Exception:
            return None

        try:
            url_to_png(clean, output_png=str(png_path))
            return png_path.read_bytes()
        except Exception:
            return self._drawio_placeholder_png(clean)
        finally:
            if tmp_png:
                try:
                    Path(tmp_png.name).unlink(missing_ok=True)  # type: ignore[arg-type]
                except Exception:
                    pass

    def _apply_drawio_preview(self, clip_id: int, data: Optional[bytes]) -> None:
        if not data:
            return
        clip = self.clip_model.clip_for_id(int(clip_id))
        if not clip:
            return
        clip.preview_blob = data
        self.clip_model.update_clip(clip)
        try:
            self.storage.update_preview(int(clip_id), clip.preview_text, data)
        except Exception:
            pass

    def _drawio_placeholder_png(self, payload: str) -> Optional[bytes]:
        """Fallback PNG when CLI export fails or is unavailable."""
        img = QImage(420, 260, QImage.Format_ARGB32)
        img.fill(QColor("#1f2428"))
        painter = QPainter(img)
        try:
            painter.setRenderHint(QPainter.TextAntialiasing, True)
            painter.setPen(QColor("#c9d1d9"))
            title_font = QFont("Consolas", 16, QFont.Bold)
            painter.setFont(title_font)
            painter.drawText(16, 28, "DRAW.IO")
            painter.setPen(QColor("#8b949e"))
            body_font = QFont("Consolas", 11)
            painter.setFont(body_font)
            painter.drawText(16, 52, "Preview unavailable")
            snippet = (payload or "").replace("\n", " ")
            if len(snippet) > 120:
                snippet = snippet[:117] + "..."
            painter.drawText(16, 76, snippet)
        finally:
            painter.end()
        return self._image_to_bytes(img)

    def _maybe_backfill_previews(self, clips: list[ClipItem]) -> None:
        for clip in clips:
            cid = getattr(clip, "id", None)
            if cid is None:
                continue
            if clip.content_type in ("text", "html", "color"):
                needs_text = not clip.preview_text
                needs_html = clip.content_type == "html" and clip.preview_blob is None
                if needs_text or needs_html:
                    full_blob = clip.content_blob
                    full_text = clip.content_text
                    # For previews_only rows, content_blob may be empty; fetch full record.
                    if needs_html and not full_blob:
                        row = self.storage.get_item(int(cid))
                        if row:
                            full_blob = row["content_blob"]
                            full_text = str(row["content_text"] or "")
                    # For html, we can build immediately without async since cost is low; but reuse async builder to keep code uniform.
                    self._schedule_preview_build(
                        int(cid),
                        clip.content_type,
                        full_text,
                        full_blob,
                    )
            elif clip.content_type in ("image", "svg+xml", "drawio"):
                if clip.content_type == "drawio":
                    if clip.preview_blob is None:
                        self._schedule_drawio_preview(clip)
                elif clip.preview_blob is None and clip.content_blob:
                    self._schedule_preview_build(
                        int(cid),
                        clip.content_type,
                        clip.content_text,
                        clip.content_blob,
                    )

    def _ensure_full_clip(self, item_id: int) -> Optional[ClipItem]:
        clip = self.clip_model.clip_for_id(item_id)
        if clip and getattr(clip, "has_full_content", True):
            return clip
        row = self.storage.get_item(int(item_id))
        if not row:
            return None
        full_clip = item_from_row(row)
        if clip:
            self.clip_model._tooltips[int(full_clip.id)] = self._build_tooltip(
                full_clip.content_text
            )
            self.clip_model.update_clip(full_clip)
        else:
            # If clip was not present in the list (should not happen for visible items),
            # refresh the entire model as a fallback.
            self.refresh_items()
        return full_clip

    def _on_clipboard_changed(self) -> None:
        if self._ignore_next_clip:
            self._ignore_next_clip = False
            print("Ignoring clipboard change")
            return
        print("Clipboard changed")
        snapshot = self._clipboard_snapshot()
        if snapshot is None:
            print("Clipboard snapshot failed")
            return

        def worker():
            ret = self._extract_clip_snapshot(snapshot)
            return ret

        future = self._preview_executor.submit(worker)
        future.add_done_callback(lambda fut: self.clipboardExtracted.emit(fut))

    def _extract_clip(
        self, mime: QMimeData
    ) -> tuple[Optional[str], str, Optional[bytes]]:
        content_type: Optional[str] = None
        content_text = ""
        content_blob: Optional[bytes] = None
        if mime.hasFormat("image/svg+xml"):
            try:
                data = bytes(mime.data("image/svg+xml"))
            except Exception:
                data = None
            if data:
                content_type = "svg+xml"
                content_blob = data
                content_text = "[SVG]"
                return content_type, content_text, content_blob
        if mime.hasImage():
            image = self._clipboard.image()
            if not image.isNull():
                content_type = "image"
                content_blob = self._image_to_bytes(image)
                content_text = f"[Image {image.width()}x{image.height()}]"
            return content_type, content_text, content_blob
        if mime.hasHtml():
            html = mime.html()
            if html:
                txt = mime.text() or html
                if is_drawio_payload(txt):
                    png_blob = self._drawio_png_from_payload(txt, None)
                    return "drawio", txt, png_blob
                normalized_color = parse_color_text(txt)
                if normalized_color:
                    content_type = "color"
                    content_text = json.dumps({"hex": normalized_color, "text": txt})
                    return (
                        content_type,
                        content_text,
                        html.encode("utf-8", errors="replace"),
                    )
                content_type = "html"
                content_text = mime.text() or "[HTML]"
                content_blob = html.encode("utf-8", errors="replace")
                return content_type, content_text, content_blob
        if mime.hasText():
            text = self._clipboard.text()
            if text:
                if is_drawio_payload(text):
                    png_blob = self._drawio_png_from_payload(text, None)
                    return "drawio", text, png_blob
                normalized_color = parse_color_text(text)
                if normalized_color:
                    content_type = "color"
                    content_text = json.dumps({"hex": normalized_color, "text": text})
                else:
                    content_type = "text"
                    content_text = text
        return content_type, content_text, content_blob

    def _clipboard_snapshot(self) -> Optional[dict]:
        """Copy clipboard data into plain Python objects so heavy work can be threaded."""
        try:
            mime = self._clipboard.mimeData()
        except Exception:
            return None
        if not mime:
            return None
        snap: dict[str, object] = {
            "svg_bytes": None,
            "image_bytes": None,
            "image_size": None,
            "html": "",
            "text": "",
        }
        if mime.hasFormat("image/svg+xml"):
            try:
                data = bytes(mime.data("image/svg+xml"))
                snap["svg_bytes"] = data if data else None
            except Exception:
                pass
        if mime.hasImage():
            img = self._clipboard.image()
            if not img.isNull():
                snap["image_bytes"] = self._image_to_bytes(img)
                snap["image_size"] = (img.width(), img.height())
        if mime.hasHtml():
            try:
                snap["html"] = mime.html() or ""
            except Exception:
                snap["html"] = ""
        if mime.hasText():
            try:
                snap["text"] = self._clipboard.text() or ""
            except Exception:
                snap["text"] = ""
        return snap

    def _extract_clip_snapshot(
        self, snap: dict
    ) -> tuple[Optional[str], str, Optional[bytes], Optional[bytes]]:
        svg_bytes = snap.get("svg_bytes")
        if svg_bytes:
            return "svg+xml", "[SVG]", svg_bytes, None  # type: ignore[return-value]
        image_bytes = snap.get("image_bytes")
        if image_bytes:
            size = snap.get("image_size") or (0, 0)
            try:
                w, h = int(size[0]), int(size[1])
            except Exception:
                w = h = 0
            label = f"[Image {w}x{h}]" if w and h else "[Image]"
            return "image", label, image_bytes, None  # type: ignore[return-value]
        html = snap.get("html") or ""
        text = snap.get("text") or ""
        if html:
            txt = text or html
            if is_drawio_payload(txt):
                png_blob = self._drawio_png_from_payload(txt, None)
                return "drawio", txt, png_blob, None
            normalized_color = parse_color_text(txt)
            if normalized_color:
                # Keep original text; preview_html will be built later.
                return "color", txt, None, None
            return (
                "html",
                text or "[HTML]",
                html.encode("utf-8", errors="replace"),
                None,
            )
        if text:
            if is_drawio_payload(text):
                png_blob = self._drawio_png_from_payload(text, None)
                return "drawio", text, png_blob, None
            normalized_color = parse_color_text(text)
            if normalized_color:
                return "color", text, None, None
            return "text", text, None, None
        return None, "", None, None

    def _process_clip(
        self,
        content_type: Optional[str],
        content_text: str,
        content_blob: Optional[bytes],
        preview_blob: Optional[bytes] = None,
    ) -> None:
        print("Processing new clipboard content")
        if not content_type:
            print("No content type detected")
            return
        if content_type in ("text", "color") and content_text == self._last_clip_text:
            print("Duplicate text content; ignoring")
            return
        if content_type in ("text", "color"):
            self._last_clip_text = content_text
        group_id = self._get_destination_group_id()
        print(f"Storing new clipboard item of type {content_type} in group {group_id}")
        latest_row = self.storage.get_latest_item(group_id)
        if latest_row:
            print("Checking for duplicate with latest item")
            latest_item = item_from_row(latest_row)
            if (
                latest_item.content_type == content_type
                and latest_item.content_text == (content_text or "")
                and latest_item.content_blob == content_blob
            ):
                if latest_item.pinned:
                    print
                    return
                self.storage.delete_item(latest_item.id)
        print("Adding new item to storage")
        preview_text: Optional[str] = None
        if content_type in ("text", "color"):
            preview_text, built_preview_blob = self._build_previews(
                content_type or "", content_text or "", content_blob
            )
            if preview_blob is None:
                preview_blob = built_preview_blob
        elif content_type == "html":
            preview_text, preview_blob = self._build_previews(
                "html", content_text or "", content_blob
            )
        new_id = self.storage.add_item(
            content_type,
            content_text or "",
            content_blob,
            preview_text,
            preview_blob,
            int(time.time()),
            group_id,
        )
        self._add_url_subitems(new_id, content_text or "")
        self._add_file_subitems(new_id, content_text or "")
        self._pending_focus_id = new_id
        print("refresh")
        # Persist preview for html immediately to avoid UI fallback to raw blob.
        if content_type == "html":
            try:
                self.storage.update_preview(int(new_id), preview_text, preview_blob)
            except Exception:
                pass
        self.refresh_items()
        if content_type in ("image", "svg+xml", "drawio"):
            self._schedule_preview_build(
                int(new_id), content_type, content_text or "", content_blob
            )

    @Slot(object)
    def _handle_clip_future(self, fut) -> None:
        try:
            content_type, content_text, content_blob, preview_blob = fut.result()
        except Exception as exc:
            print(f"Clipboard extraction failed: {exc}")
            return
        self._process_clip(content_type, content_text, content_blob, preview_blob)
        try:
            # Notify plugins that depend on clipboard text.
            self.plugin_manager.on_clipboard_changed(self._clipboard_text_for_plugins())
        except Exception:
            pass
        # Refresh clipboard-driven plugins (e.g., Dictionary) without disturbing others.
        try:
            self._refresh_plugins(clipboard_only=True, full=False)
        except Exception:
            pass

    def _push_to_clipboard(self, clip: ClipItem) -> None:
        content_type = clip.content_type or "text"
        touched = False
        try:
            cid = int(getattr(clip, "id", -1))
            if cid > 0:
                self.storage.touch_item_last_used(cid)
                # ensure selection stays on this item after resort
                self._pending_focus_id = cid
                touched = True
        except Exception:
            pass
        if touched:
            # Re-sort list so the used item jumps to the front for the current view.
            self.refresh_items()
        self._ignore_next_clip = True
        if content_type == "image" and clip.content_blob:
            image = QImage.fromData(clip.content_blob)
            if not image.isNull():
                self._clipboard.setImage(image)
            return
        if content_type == "html" and clip.content_blob:
            html = clip.content_blob.decode("utf-8", errors="replace")
            mime = QMimeData()
            mime.setHtml(html)
            text = str(clip.content_text or "")
            if text:
                mime.setText(text)
            self._clipboard.setMimeData(mime)
            return
        if content_type == "svg+xml" and clip.content_blob:
            mime = QMimeData()
            try:
                mime.setData("image/svg+xml", QByteArray(clip.content_blob))
            except Exception:
                mime.setData("image/svg+xml", clip.content_blob)
            text = str(clip.content_text or "")
            if text:
                mime.setText(text)
            self._clipboard.setMimeData(mime)
            return
        if content_type == "color":
            blob = clip.content_blob or clip.preview_blob
            if blob:
                mime = QMimeData()
                mime.setHtml(blob.decode("utf-8", errors="replace"))
                text = str(clip.content_text or "")
                if text:
                    mime.setText(text)
                self._clipboard.setMimeData(mime)
                return
            try:
                data = json.loads(clip.content_text or "")
                text = str(data.get("text", ""))
            except Exception:
                text = str(clip.content_text or "")
            self._clipboard.setText(text)
            self._last_clip_text = text
            return
        text = str(clip.content_text or "")
        self._clipboard.setText(text)
        self._last_clip_text = text

    def _paste_to_foreground(self) -> None:
        if not keyboard:
            print("Keyboard module not available; cannot paste")
            return
        try:
            print("Pasting to foreground window")
            keyboard.press_and_release("ctrl+v")
            self.setWindowVisible(False)
        except Exception:
            pass

    def _is_window_visible(self) -> bool:
        w = self._window
        if not w:
            return False
        try:
            return bool(w.property("visible"))
        except Exception:
            return False

    def _apply_visible(self, on: bool) -> None:
        w = self._window
        if not w:
            return
        try:
            if on:
                w.show()  # type: ignore[attr-defined]
            else:
                w.hide()  # type: ignore[attr-defined]
        except Exception:
            pass

    def _position_window_near_cursor(self) -> None:
        """Move the popup close to the current cursor location while keeping it on-screen."""
        w = self._window
        if not w:
            return

        try:
            cursor_pos = QCursor.pos()
            screen = (
                QGuiApplication.screenAt(cursor_pos) or QGuiApplication.primaryScreen()
            )
            if not screen:
                return
            geom = screen.availableGeometry()

            width = int(float(w.property("width") or 0))
            height = int(float(w.property("height") or 0))
            if width <= 0:
                width = 600
            if height <= 0:
                height = 800
            margin = 12
            # Prefer bottom-right of cursor; fall back to keeping on screen.
            target_x = cursor_pos.x() + margin
            target_y = cursor_pos.y() + margin

            min_x = geom.left() + margin
            min_y = geom.top() + margin
            max_x = geom.left() + max(0, geom.width() - width - margin)
            max_y = geom.top() + max(0, geom.height() - height - margin)

            target_x = max(min_x, min(target_x, max_x))
            target_y = max(min_y, min(target_y, max_y))

            w.setProperty("x", target_x)
            w.setProperty("y", target_y)
        except Exception:
            pass

    def _bring_to_front(self) -> None:
        w = self._window
        if not w:
            return

        def _do():
            try:
                if hasattr(w, "raise_"):
                    w.raise_()  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                if hasattr(w, "requestActivate"):
                    w.requestActivate()  # type: ignore[attr-defined]
            except Exception:
                pass

        _do()
        QTimer.singleShot(0, _do)

    def _focus_window(self) -> None:
        """Ensure the popup grabs focus and keyboard input."""
        w = self._window
        if not w:
            return

        def _do() -> None:
            try:
                if hasattr(w, "focusPopup"):
                    QMetaObject.invokeMethod(w, "focusPopup", Qt.QueuedConnection)
            except Exception:
                pass
            try:
                if hasattr(w, "requestActivate"):
                    w.requestActivate()  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                if hasattr(w, "raise_"):
                    w.raise_()  # type: ignore[attr-defined]
            except Exception:
                pass

        _do()
        QTimer.singleShot(0, _do)
        QTimer.singleShot(120, _do)
        self._force_foreground_windows()

    def _force_foreground_windows(self) -> None:
        """On Windows, explicitly request foreground activation using Win32 APIs."""
        if sys.platform != "win32":
            return
        w = self._window
        if not w:
            return
        try:
            import ctypes

            user32 = ctypes.windll.user32  # type: ignore[attr-defined]
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            # Allow this process to set the foreground window.
            try:
                user32.AllowSetForegroundWindow(-1)
            except Exception:
                pass
            hwnd = int(w.winId())  # type: ignore[attr-defined]
            if hwnd:
                fg = user32.GetForegroundWindow()
                fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0
                this_thread = kernel32.GetCurrentThreadId()
                attached = False
                try:
                    if fg_thread and fg_thread != this_thread:
                        attached = bool(
                            user32.AttachThreadInput(this_thread, fg_thread, True)
                        )
                    # SW_SHOW = 5
                    user32.ShowWindow(hwnd, 5)
                    user32.SetForegroundWindow(hwnd)
                    user32.BringWindowToTop(hwnd)
                finally:
                    if attached:
                        user32.AttachThreadInput(this_thread, fg_thread, False)
        except Exception:
            pass

    def _get_default_group_id(self) -> int:
        group = self.storage.get_group_by_name("Default")
        if group:
            return int(group["id"])
        return self.storage.create_group("Default")

    def _image_to_bytes(self, image: QImage) -> bytes:
        buffer = QBuffer()
        buffer.open(QIODevice.WriteOnly)
        image.save(buffer, "PNG")
        return bytes(buffer.data())

    def _drawio_preview_bytes(self, clip: ClipItem) -> Optional[bytes]:
        # Backward-compatible wrapper; now always returns PNG bytes.
        return self._drawio_preview_png_bytes(clip)

    def _generate_drawio_svg(self, payload: str) -> Optional[bytes]:
        """Backcompat shim: return PNG bytes instead of SVG."""
        return self._drawio_png_from_payload(payload or "", None)
