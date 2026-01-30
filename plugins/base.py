from abc import ABC, abstractmethod
from typing import List

from item import ClipItem


class Plugin(ABC):
    """Minimal interface for pluggable features shown in the Plugins group."""

    plugin_id: str
    display_name: str

    def __init__(self, group_id: int) -> None:
        self.group_id = group_id

    @abstractmethod
    def build_items(self, clipboard_text: str) -> List[ClipItem]:
        """Return virtual ClipItem rows to render for this plugin."""
        raise NotImplementedError

    def on_action(self, action_id: str, backend, payload=None) -> bool:
        """Handle a context-menu action. Return True if handled."""
        return False

    def teardown(self) -> None:
        """Optional cleanup hook."""
        # Default no-op so subclasses can opt-in.
        return
