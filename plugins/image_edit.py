import time
from typing import Callable, List, Optional

from config import load_config
from item import ClipItem

from .base import Plugin


def _font_family() -> str:
    return (
        load_config().get("ui", {}).get("fontFamily")
        or "Cascadia Code, 'Segoe UI', sans-serif"
    )


HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <style>
    :root { color-scheme: light dark; }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      padding: 0;
      font-family: __FONT__;
      background: linear-gradient(145deg, #0f172a, #111827 55%, #0b1223);
      color: #e2e8f0;
      min-height: 100vh;
      display: grid;
      place-items: center;
    }
    .card {
      width: min(640px, 94vw);
      background: rgba(15, 23, 42, 0.88);
      border: 1px solid #1e293b;
      border-radius: 14px;
      padding: 22px;
      box-shadow: 0 16px 50px rgba(0,0,0,0.35);
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    h1 { margin: 0; font-size: 20px; letter-spacing: 0.25px; }
    p { margin: 0; line-height: 1.5; color: #cbd5e1; }
    ul { margin: 8px 0 0 18px; padding: 0; color: #cbd5e1; }
    li { margin-bottom: 6px; }
    .pill {
      display: inline-block;
      padding: 6px 12px;
      border-radius: 999px;
      background: #1e293b;
      color: #cbd5e1;
      font-size: 13px;
      letter-spacing: 0.4px;
    }
  </style>
</head>
<body>
  <div class="card">
    <div class="pill">Image Edit</div>
    <h1>Edit clipboard image in your system editor</h1>
    <p>Send the current clipboard image to Paint (or your OS default image editor). When you close the editor, the edited image is copied back to the clipboard.</p>
    <ul>
      <li>Works best when an image is already in the clipboard.</li>
      <li>If no image is present, the action will show a status message.</li>
      <li>Temporary files are stored in your temp folder during editing.</li>
    </ul>
  </div>
</body>
</html>
"""


class ImageEditPlugin(Plugin):
    plugin_id = "image_edit"
    display_name = "Image Edit"
    uses_clipboard = False

    def __init__(
        self,
        group_id: int,
        refresh_callback: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(group_id)
        self._refresh_callback = refresh_callback

    def build_items(self, clipboard_text: str) -> List[ClipItem]:
        now = int(time.time())
        html = HTML.replace("__FONT__", _font_family())
        return [
            ClipItem(
                id=-1000,
                content_type="html",
                content_text="Image Edit",
                content_blob=html.encode("utf-8"),
                created_at=now,
                pinned=False,
                pinned_at=None,
                group_id=self.group_id,
                preview_text="Image Edit",
                preview_blob=None,
                has_full_content=True,
                content_length=len(html),
                collapsed_height=220,
                expanded_height=220,
                render_mode="web",
                plugin_id=self.plugin_id,
                extra_actions=[
                    {"id": "edit_clipboard", "text": "Edit image from clipboard"},
                ],
            )
        ]

    def on_action(self, action_id: str, backend, payload=None) -> bool:
        if action_id == "edit_clipboard":
            try:
                return bool(backend.plugin_edit_clipboard_image())
            except Exception:
                return False
        return False
