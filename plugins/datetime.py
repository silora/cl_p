from datetime import datetime, timezone

from item import ClipItem

from .base import Plugin


class DateTimePlugin(Plugin):
    plugin_id = "datetime"
    display_name = "Date & Time"
    uses_clipboard = False

    def __init__(self, group_id: int) -> None:
        super().__init__(group_id)

    def build_items(self, clipboard_text: str) -> list[ClipItem]:
        now = datetime.now().astimezone()
        iso_stamp = now.isoformat(timespec="seconds")
        friendly = now.strftime("%A, %B %d, %Y %I:%M:%S %p %Z")
        date_only = now.strftime("%Y-%m-%d")
        ts = now.strftime("%Y-%m-%d %H:%M:%S")
        html_body = f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <style>
    :root {{ color-scheme: light dark; }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      padding: 0;
      font-family: "Segoe UI", system-ui, -apple-system, sans-serif;
      background: radial-gradient(circle at 20% 20%, #e0f7ff, #f5fff3 55%);
      color: #0f1b2d;
      min-height: 100vh;
      display: grid;
      place-items: center;
    }}
    .card {{
      width: min(420px, 92vw);
      background: #ffffffcc;
      backdrop-filter: blur(6px);
      border: 1px solid #c8e4ff;
      border-radius: 18px;
      box-shadow: 0 12px 28px rgba(15,27,45,0.16);
      padding: 16px 18px;
      display: grid;
      gap: 8px;
    }}
    .headline {{
      font-size: 18px;
      font-weight: 700;
      letter-spacing: 0.2px;
      text-align: center;
    }}
    .sub {{
      font-family: "JetBrains Mono", "Cascadia Code", Consolas, monospace;
      font-size: 13px;
      text-align: center;
      color: #304463;
      word-break: break-all;
    }}
    .row {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      font-size: 13px;
      color: #304463;
    }}
    .label {{ font-weight: 600; color: #123; }}
    .value {{ font-family: "JetBrains Mono", "Cascadia Code", Consolas, monospace; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="headline">{friendly}</div>
    <div class="sub">{iso_stamp}</div>
    <div class="row">
      <div class="label">Date</div>
      <div class="value">{date_only}</div>
    </div>
    <div class="row">
      <div class="label">Timestamp</div>
      <div class="value">{ts}</div>
    </div>
  </div>
</body>
</html>
        """
        return [
            ClipItem(
                id=-1001,
                content_type="html",
                content_text=friendly,
                content_blob=html_body.encode("utf-8"),
                created_at=int(now.timestamp()),
                pinned=False,
                pinned_at=None,
                group_id=self.group_id,
                preview_text=friendly,
                preview_blob=html_body.encode("utf-8"),
                has_full_content=True,
                content_length=len(friendly),
                collapsed_height=140,
                expanded_height=160,
                render_mode="rich",
                plugin_id=self.plugin_id,
                extra_actions=[
                    {"id": "paste-date", "text": "Paste as date"},
                    {"id": "paste-ts", "text": "Paste as timestamp"},
                ],
            )
        ]

    def on_action(self, action_id: str, backend, payload=None) -> bool:
        now = datetime.now().astimezone()
        if action_id == "paste-date":
            backend.plugin_set_clipboard_and_paste(now.strftime("%Y-%m-%d"))
            return True
        if action_id == "paste-ts":
            backend.plugin_set_clipboard_and_paste(now.strftime("%Y-%m-%d %H:%M:%S"))
            return True
        return False
