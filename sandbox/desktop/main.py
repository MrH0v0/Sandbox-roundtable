from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from sandbox.desktop.main_window import MainWindow
from sandbox.desktop.state import DesktopState
from sandbox.desktop.theme import apply_theme


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Sandbox Roundtable Desktop")
    app.setOrganizationName("sandbox")
    apply_theme(app)

    state = DesktopState()
    window = MainWindow(state)
    state.bootstrap()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
