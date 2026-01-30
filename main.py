import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QFont, QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterType
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWebEngineQuick import QtWebEngineQuick
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from config import get_palette_config, load_config
from qml_backend import Backend
from storage import Storage
from ui.super_rich_text_item import SuperRichTextItem

# Avoid non-integral scale factors that WebEngine rejects; override any env drift.
os.environ["QT_SCALE_FACTOR"] = "1.0"

APP_NAME = "cl_p"
DB_NAME = "cl_p.sqlite3"
# ICON_NAME = "icon_white.svg"
ICON_NAME = "icon_full.png"


def _build_tray(
    app: QApplication, backend: Backend, icon_path: Path
) -> QSystemTrayIcon:
    tray_icon = QIcon(str(icon_path))
    tray = QSystemTrayIcon(tray_icon, app)
    menu = QMenu()
    show_action = menu.addAction("Show/Hide")
    show_action.triggered.connect(backend.toggleWindow)
    quit_action = menu.addAction("Quit")
    quit_action.triggered.connect(app.quit)
    tray.setContextMenu(menu)
    tray.setToolTip(APP_NAME)

    # Left-click/double-click toggles window visibility.
    def on_tray_activated(reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            backend.showWindow()

    tray.activated.connect(on_tray_activated)
    tray.show()
    return tray


def main() -> int:
    QtWebEngineQuick.initialize()
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.RoundPreferFloor
    )
    QQuickStyle.setStyle("Basic")
    app = QApplication(sys.argv)
    # Keep tray app alive even when the popup window closes.
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName(APP_NAME)

    base_dir = Path(__file__).resolve().parent
    icon_path = base_dir / "icons" / ICON_NAME
    db_path = base_dir / DB_NAME
    qml_path = base_dir / "ui" / "main.qml"

    app_config = load_config(base_dir / "config.yaml")
    palette = get_palette_config(base_dir / "config.yaml")

    font_family = app_config.get("ui", {}).get("fontFamily") or "Cascadia Code"
    font_size = 8
    app.setFont(QFont(font_family, font_size))

    max_items = (
        app_config.get("storage", {}).get("maxItemsPerGroup")
        if isinstance(app_config, dict)
        else None
    )
    storage = Storage(
        db_path, max_items_per_group=int(max_items) if max_items else None
    )
    backend = Backend(storage)
    app.aboutToQuit.connect(storage.close)

    qmlRegisterType(SuperRichTextItem, "cl_p", 1, 0, "SuperRichText")

    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("backend", backend)
    engine.rootContext().setContextProperty("clipModel", backend.clip_model)
    engine.rootContext().setContextProperty("groupModel", backend.group_model)
    engine.rootContext().setContextProperty("appIconPath", str(icon_path))
    engine.rootContext().setContextProperty("paletteGrays", palette.get("grays"))
    engine.rootContext().setContextProperty(
        "paletteLightColors", palette.get("lightColors")
    )
    engine.rootContext().setContextProperty(
        "paletteDarkColors", palette.get("darkColors")
    )
    engine.rootContext().setContextProperty(
        "paletteHighlightColors", palette.get("highlightColors")
    )
    engine.rootContext().setContextProperty("appConfig", app_config)
    engine.load(QUrl.fromLocalFile(str(qml_path)))

    if not engine.rootObjects():
        return 1

    root = engine.rootObjects()[0]
    backend.setWindow(root)
    _build_tray(app, backend, icon_path)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
