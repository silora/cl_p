import time
from typing import Callable, List

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
    :root { color-scheme: light; }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      padding: 0;
      font-family: __FONT__;
      background: #f7f8fb;
      color: #0f172a;
      display: grid;
      place-items: center;
      min-height: 100vh;
    }
    .card {
      width: min(820px, 96vw);
      background: #ffffff;
      border: 1px solid #e5e7eb;
      border-radius: 16px;
      padding: 18px;
      box-shadow: 0 18px 48px rgba(15, 23, 42, 0.12);
      display: flex;
      flex-direction: column;
      gap: 12px;
      text-align: center;
    }
    h1 { margin: 0; font-size: 22px; letter-spacing: 0.2px; }
    p  { margin: 0; color: #475569; line-height: 1.6; }
    .actions { display: flex; gap: 10px; justify-content: center; flex-wrap: wrap; }
    button {
      cursor: pointer;
      border: none;
      border-radius: 12px;
      padding: 12px 18px;
      font-size: 15px;
      font-weight: 600;
      background: linear-gradient(135deg, #10b981, #14b8a6);
      color: white;
      box-shadow: 0 10px 24px rgba(20,184,166,0.32);
      transition: transform 90ms ease, filter 90ms ease;
    }
    button:hover { filter: brightness(1.05); }
    button:active { transform: translateY(1px); }
    .hint { font-size: 13px; color: #64748b; }
  </style>
</head>
<body bgcolor="#0a152f">
  <div class="card">
    <h1>Flaticon Search</h1>
    <p>Browse icons from <strong>flaticon.com</strong> without leaving cl_p.</p>
    <div class="actions">
      <button onclick="openSearch()">Open Flaticon</button>
    </div>
    <div class="hint" id="hint"></div>
  </div>
  <script>
    const query = "__QUERY__";
    const hint = document.getElementById("hint");
    function targetUrl() {
      if (!query) return "https://www.flaticon.com/";
      return "https://www.flaticon.com/search?word=" + encodeURIComponent(query);
    }
    function openSearch() {
      window.location = targetUrl();
    }
    if (query) {
      hint.textContent = "Searching for: " + query;
      setTimeout(openSearch, 80);
    } else {
      hint.textContent = "Click to open Flaticon home, or use the context action to search selected text.";
    }
  </script>
</body>
</html>
"""


class FlaticonPlugin(Plugin):
    plugin_id = "flaticon"
    display_name = "Flaticon"
    uses_clipboard = False

    def __init__(
        self,
        group_id: int,
        refresh_callback: Callable[[], None],
    ) -> None:
        super().__init__(group_id)
        self._refresh_callback = refresh_callback
        self._pending_query: str | None = None

    def build_items(self, clipboard_text: str) -> List[ClipItem]:
        now = int(time.time())
        font = _font_family()
        query = (self._pending_query or "").strip()
        html = HTML.replace("__FONT__", font).replace(
            "__QUERY__", query.replace('"', '\\"')
        )
        preview = f"Flaticon · {query}" if query else "Flaticon"
        return [
            ClipItem(
                id=-1000,
                content_type="html",
                content_text="Flaticon",
                content_blob=html.encode("utf-8"),
                created_at=now,
                pinned=False,
                pinned_at=None,
                group_id=self.group_id,
                preview_text=preview,
                preview_blob=None,
                has_full_content=True,
                content_length=len(html),
                collapsed_height=495,
                expanded_height=495,
                render_mode="web",
                plugin_id=self.plugin_id,
                extra_actions=[
                    {"id": "search_clip", "text": "Search clip text"},
                ],
            )
        ]

    def on_action(self, action_id: str, backend, payload=None) -> bool:
        if action_id == "search_clip":
            try:
                getter = getattr(backend, "_clipboard_text_for_plugins", None)
                clip_txt = getter() if callable(getter) else ""
            except Exception:
                clip_txt = ""
            query = (clip_txt or "").strip()
            if not query:
                return False
            self._pending_query = query[:200]
            try:
                if hasattr(backend, "refresh_single_plugin"):
                    backend.refresh_single_plugin(self.plugin_id)
                else:
                    self._refresh_callback(clipboard_only=False, full=False)
            except Exception:
                pass
            return True
        return False
