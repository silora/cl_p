import time
from typing import Callable, List

from config import load_config
from item import ClipItem

from .base import Plugin


def _font_family() -> str:
    return (
        load_config()
        .get("ui", {})
        .get("fontFamily")
        or "Cascadia Code, 'Segoe UI', sans-serif"
    )


HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <style>
    :root { color-scheme: light dark; }
    body { margin: 0; padding: 0; font-family: __FONT__; background: #0f0f0f; color: #e6edf3; }
    .wrap { padding: 14px; display: flex; flex-direction: column; gap: 12px; }
    .title { font-size: 18px; font-weight: 700; }
    .bar {
      display: flex;
      gap: 8px;
      align-items: center;
      background: #1c1c1c;
      border: 1px solid #30363d;
      border-radius: 10px;
      padding: 8px 10px;
    }
    input {
      flex: 1;
      background: transparent;
      border: none;
      outline: none;
      color: #e6edf3;
      font-size: 14pt;
      font-family: inherit;
    }
    button {
      background: #238636;
      color: white;
      border: 1px solid #2ea043;
      border-radius: 8px;
      padding: 8px 12px;
      font-size: 13px;
      cursor: pointer;
    }
    iframe {
      width: 100%;
      height: 540px;
      border: 1px solid #30363d;
      border-radius: 12px;
      background: white;
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="title">Search (DDG Lite)</div>
    <div class="bar">
      <input id="q" type="text" placeholder="Search..." autofocus />
      <button onclick="search()">Search</button>
    </div>
    <iframe id="view" src="https://lite.duckduckgo.com/lite/" sandbox="allow-same-origin allow-scripts allow-forms allow-popups"></iframe>
  </div>
  <script>
    const q = document.getElementById('q');
    const view = document.getElementById('view');
    function search() {
      const term = (q.value || '').trim();
      const url = term ? 'https://lite.duckduckgo.com/lite/?q=' + encodeURIComponent(term) : 'https://lite.duckduckgo.com/lite/';
      view.src = url;
    }
    q.addEventListener('keydown', (e)=>{
      if (e.key === 'Enter') {
        e.preventDefault();
        search();
      }
    });
  </script>
</body>
</html>
"""


class GooglePlugin(Plugin):
    plugin_id = "google"
    display_name = "Google"

    def __init__(
        self,
        group_id: int,
        refresh_callback: Callable[[], None],
    ) -> None:
        super().__init__(group_id)
        self._refresh_callback = refresh_callback

    def build_items(self, clipboard_text: str) -> List[ClipItem]:
        now = int(time.time())
        font = _font_family()
        html = HTML.replace("__FONT__", font)
        return [
            ClipItem(
                id=-1000,
                content_type="html",
                content_text="Google Search",
                content_blob=html.encode("utf-8"),
                created_at=now,
                pinned=False,
                pinned_at=None,
                group_id=self.group_id,
                preview_text="Google Search",
                preview_blob=None,
                has_full_content=True,
                content_length=len(html),
                collapsed_height=360,
                expanded_height=640,
                render_mode="web",
                plugin_id=self.plugin_id,
                extra_actions=[],
            )
        ]

    def on_action(self, action_id: str, backend, payload=None) -> bool:
        return False
