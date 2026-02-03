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
        base = -1000 - (len(self._plugins) * 100)
        setattr(plugin, "_id_base", base)
        self._plugins.append(plugin)

    def on_clipboard_changed(self, clipboard_text: str) -> None:
        for plugin in self._plugins:
            try:
                plugin.on_clipboard_changed(clipboard_text)
            except Exception:
                continue

    @property
    def plugins(self) -> list[Plugin]:
        return list(self._plugins)

    def build_items(self) -> List[ClipItem]:
        clipboard_text_cache = None
        items: list[ClipItem] = []
        for plugin in self._plugins:
            clip_txt = ""
            if getattr(plugin, "uses_clipboard", True):
                if clipboard_text_cache is None:
                    clipboard_text_cache = self._clipboard_text_provider() or ""
                clip_txt = clipboard_text_cache
            plugin_items = plugin.build_items(clip_txt)
            base = getattr(plugin, "_id_base", -1000)
            for idx, item in enumerate(plugin_items):
                try:
                    item.id = int(base - idx)
                except Exception:
                    pass
            items.extend(plugin_items)
        return items

    def build_items_for(self, plugin_id: str) -> List[ClipItem]:
        """
        Build items only for the specified plugin_id; falls back to [] on failure.
        """
        clipboard_text_cache = None
        out: list[ClipItem] = []
        for plugin in self._plugins:
            if getattr(plugin, "plugin_id", None) != plugin_id:
                continue
            clip_txt = ""
            if getattr(plugin, "uses_clipboard", True):
                if clipboard_text_cache is None:
                    clipboard_text_cache = self._clipboard_text_provider() or ""
                clip_txt = clipboard_text_cache
            try:
                plugin_items = plugin.build_items(clip_txt)
            except Exception:
                plugin_items = []
            base = getattr(plugin, "_id_base", -1000)
            for idx, item in enumerate(plugin_items):
                try:
                    item.id = int(base - idx)
                except Exception:
                    pass
            out.extend(plugin_items)
        return out

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
