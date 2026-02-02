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
    :root { color-scheme: light dark; }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      padding: 0;
      font-family: __FONT__;
      background: #0f172a;
      color: #e2e8f0;
      display: grid;
      place-items: center;
      min-height: 100vh;
    }
    .card {
      width: min(740px, 94vw);
      background: #111827;
      border: 1px solid #1f2937;
      border-radius: 14px;
      padding: 22px;
      box-shadow: 0 18px 50px rgba(0,0,0,0.35);
      text-align: center;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    h1 { margin: 0; font-size: 22px; letter-spacing: 0.3px; }
    p { margin: 0; color: #cbd5e1; line-height: 1.5; }
    button {
      cursor: pointer;
      margin-top: 8px;
      align-self: center;
      background: linear-gradient(135deg, #22d3ee, #6366f1);
      color: white;
      border: none;
      border-radius: 12px;
      padding: 12px 20px;
      font-size: 15px;
      font-weight: 600;
      min-width: 180px;
      box-shadow: 0 8px 24px rgba(99,102,241,0.35);
    }
    button:hover { filter: brightness(1.05); }
    .hint {
      font-size: 13px;
      color: #94a3b8;
    }
  </style>
</head>
<body bgcolor="#212121">
  <div class="card">
    <h1>Open ChatGPT</h1>
    <p>Loads the full chatgpt.com experience inside cl_p.<br>
       Sign in once; your session stays cached so you don't need to log in again.</p>
    <button onclick="openChat()">Go to ChatGPT</button>
    <div class="hint">If the page looks blank, your network may block chatgpt.com. Click again to retry.</div>
  </div>
  <script>
    const target = "https://chatgpt.com/";
    let navigated = false;
    function openChat() {
      if (navigated) return;
      navigated = true;
      window.location = target;
    }
    // Try automatically after a brief delay so users land in ChatGPT without extra clicks.
    setTimeout(openChat, 120);
  </script>
</body>
</html>
"""


class ChatGPTPlugin(Plugin):
    plugin_id = "chatgpt"
    display_name = "ChatGPT"
    uses_clipboard = False

    def __init__(self, group_id: int, refresh_callback: Callable[[], None]) -> None:
        super().__init__(group_id)
        self._refresh_callback = refresh_callback

    def build_items(self, clipboard_text: str) -> List[ClipItem]:
        now = int(time.time())
        html = HTML.replace("__FONT__", _font_family())
        return [
            ClipItem(
                id=-1001,
                content_type="html",
                content_text="ChatGPT",
                content_blob=html.encode("utf-8"),
                created_at=now,
                pinned=False,
                pinned_at=None,
                group_id=self.group_id,
                preview_text="ChatGPT",
                preview_blob=None,
                has_full_content=True,
                content_length=len(html),
                collapsed_height=420,
                expanded_height=760,
                render_mode="web",
                plugin_id=self.plugin_id,
                extra_actions=[],
            )
        ]

    def on_action(self, action_id: str, backend, payload=None) -> bool:
        return False
