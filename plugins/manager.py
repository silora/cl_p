from typing import Callable, List

from item import ClipItem

from .base import Plugin


class PluginManager:
    """Registry/dispatcher for plugins rendered in the Plugins group."""

    def __init__(self, group_id: int, clipboard_text_provider: Callable[[], str]) -> None:
        self.group_id = group_id
        self._clipboard_text_provider = clipboard_text_provider
        self._plugins: list[Plugin] = []

    def register(self, plugin: Plugin) -> None:
        self._plugins.append(plugin)

    def build_items(self) -> List[ClipItem]:
        clipboard_text = self._clipboard_text_provider() or ""
        items: list[ClipItem] = []
        for plugin in self._plugins:
            items.extend(plugin.build_items(clipboard_text))
        return items

    def dispatch_action(self, plugin_id: str, action_id: str, backend, payload=None) -> bool:
        for plugin in self._plugins:
            if getattr(plugin, "plugin_id", None) == plugin_id:
                try:
                    return bool(plugin.on_action(action_id, backend, payload))
                except Exception:
                    return False
        return False

    def teardown(self) -> None:
        for plugin in self._plugins:
            try:
                plugin.teardown()
            except Exception:
                # Best-effort cleanup; avoid hard failure during shutdown.
                pass
