from datetime import datetime, timezone

from item import ClipItem

from .base import Plugin


class DateTimePlugin(Plugin):
    plugin_id = "datetime"
    display_name = "Date & Time"

    def __init__(self, group_id: int) -> None:
        super().__init__(group_id)

    def build_items(self, clipboard_text: str) -> list[ClipItem]:
        now = datetime.now().astimezone()
        iso_stamp = now.isoformat(timespec="seconds")
        friendly = now.strftime("%A, %B %d %Y · %I:%M:%S %p %Z")
        date_only = now.strftime("%Y-%m-%d")
        ts = now.strftime("%Y-%m-%d %H:%M:%S")
        html_body = f"""
            <html>
            <body bgcolor="#7FC962">
            <p align="center" style="font-size:8.5pt"><b>{friendly}</b></p>
            <p align="center" style="font-size:9pt"><tt>{iso_stamp}</tt></p>
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
                collapsed_height=100,
                expanded_height=100,
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
            print("Pasting date to foreground window...")
            backend.plugin_set_clipboard_and_paste(now.strftime("%Y-%m-%d"))
            return True
        if action_id == "paste-ts":
            backend.plugin_set_clipboard_and_paste(now.strftime("%Y-%m-%d %H:%M:%S"))
            return True
        return False
