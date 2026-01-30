import json
from dataclasses import dataclass
from typing import Optional, Tuple, List, Dict, Any

from PySide6.QtGui import QImage


@dataclass
class ClipItem:
    id: int
    content_type: str
    content_text: str
    content_blob: Optional[bytes]
    created_at: int
    pinned: bool
    pinned_at: Optional[int]
    group_id: int
    last_used_at: Optional[int] = None
    preview_text: str = ""
    preview_blob: Optional[bytes] = None
    has_full_content: bool = True
    content_length: int = 0
    collapsed_height: int = 0
    expanded_height: int = 0
    render_mode: str = ""  # ""| "rich" | "web"
    plugin_id: str = ""
    extra_actions: List[Dict[str, Any]] = None

    def label(self) -> str:
        text_source = self.content_text or self.preview_text
        text = (text_source or "").replace("\n", " ")
        label = text[:160]
        if len(text) > 160:
            label += "..."
        return label or "[Empty]"


@dataclass
class TextItem(ClipItem):
    pass


@dataclass
class HtmlItem(ClipItem):
    def label(self) -> str:
        text_source = self.content_text or self.preview_text
        text = (text_source or "").replace("\n", " ")
        label = text[:160] if text else "[HTML]"
        if len(text) > 160:
            label += "..."
        return "[HTML] " + label


@dataclass
class ImageItem(ClipItem):
    def label(self) -> str:
        blob = self.content_blob or self.preview_blob
        if blob:
            image = QImage.fromData(blob)
            if not image.isNull():
                return f"[IMG] {image.width()}x{image.height()}"
        return "[IMG]"


@dataclass
class SvgItem(ClipItem):
    def label(self) -> str:
        return "[SVG]"


@dataclass
class DrawioItem(ClipItem):
    def label(self) -> str:
        return "[DRAWIO]"


@dataclass
class ColorItem(ClipItem):
    def _parsed(self) -> Tuple[str, str]:
        raw = self.content_text or ""
        try:
            data = json.loads(raw)
            hex_value = str(data.get("hex") or "").strip() or "[COLOR]"
            label_text = str(data.get("text") or "").strip() or hex_value
            return hex_value, label_text
        except Exception:
            clean = raw.strip() or "[COLOR]"
            return clean, clean

    def label(self) -> str:
        hex_value, label_text = self._parsed()
        return f"[COLOR] {label_text}"


def item_from_row(row) -> ClipItem:
    content_type = row["content_type"] or "text"
    preview_text = str(row["preview_text"] or "")
    has_full = bool(row["has_full_content"]) if "has_full_content" in row.keys() else True
    base_kwargs = {
        "id": int(row["id"]),
        "content_type": content_type,
        "content_text": str(row["content_text"] or ""),
        "content_blob": row["content_blob"],
        "created_at": int(row["created_at"]),
        "pinned": bool(row["pinned"]),
        "pinned_at": int(row["pinned_at"]) if row["pinned_at"] is not None else None,
        "group_id": int(row["group_id"]),
        "last_used_at": int(row["last_used_at"]) if row["last_used_at"] is not None else None,
        "preview_text": preview_text,
        "preview_blob": row["preview_blob"] if "preview_blob" in row.keys() else None,
        "has_full_content": has_full,
        "content_length": int(row["content_length"]) if "content_length" in row.keys() else len(str(row["content_text"] or "")),
        "collapsed_height": int(row.get("collapsed_height", 0)) if hasattr(row, "get") else int(row["collapsed_height"]) if "collapsed_height" in row.keys() else 0,
        "expanded_height": int(row.get("expanded_height", 0)) if hasattr(row, "get") else int(row["expanded_height"]) if "expanded_height" in row.keys() else 0,
        "render_mode": str(row.get("render_mode", "")) if hasattr(row, "get") else str(row["render_mode"]) if "render_mode" in row.keys() else "",
        "plugin_id": str(row.get("plugin_id", "")) if hasattr(row, "get") else str(row["plugin_id"]) if "plugin_id" in row.keys() else "",
        "extra_actions": row.get("extra_actions", []) if hasattr(row, "get") else row["extra_actions"] if "extra_actions" in row.keys() else [],
    }
    if content_type == "image":
        return ImageItem(**base_kwargs)
    if content_type == "svg+xml":
        return SvgItem(**base_kwargs)
    if content_type == "drawio":
        return DrawioItem(**base_kwargs)
    if content_type == "html":
        return HtmlItem(**base_kwargs)
    if content_type == "color":
        return ColorItem(**base_kwargs)
    return TextItem(**base_kwargs)
