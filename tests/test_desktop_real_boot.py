from __future__ import annotations

import os

from PySide6.QtWidgets import QApplication

from sandbox.desktop.main_window import MainWindow
from sandbox.desktop.state import DesktopState


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_real_desktop_bootstrap_does_not_crash() -> None:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])

    state = DesktopState()
    window = MainWindow(state)
    state.bootstrap()

    window.close()
    state.shutdown()
    app.processEvents()
