# ClipX (CopyQ-lite)

Minimal CopyQ-style clipboard manager for Windows rewritten with PySide6 + Qt Quick (QML).

## Features
- Clipboard history (text, images, HTML)
- Groups (All + custom), pin/unpin, delete
- Local shortcuts (`Ctrl+Enter` paste selected, `Ctrl+Shift+V` toggle)
- Optional global toggle hotkey via `keyboard` on Windows
- Tray icon with show/hide + quit

## Setup
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

## Notes
- Global hotkeys use the `keyboard` package. If not installed or blocked by the OS, the local shortcuts still work when the window is focused.
- Images are stored as PNG bytes; rich text is stored as HTML with a plain-text search fallback.

## Todos
- [ ] add a horizontal scroll bar for group tab
- [ ] remove x button for group tab, context menu for delete / rename
- [ ] prettier scroll bar
- [ ] icon for note
- [ ] subitem deletion
- [ ] allow duplication for note
- [ ] better highlight for pinned / hovered / selected
- [ ] file path processing