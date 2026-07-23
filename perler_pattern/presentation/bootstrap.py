from __future__ import annotations

import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from perler_pattern.logging_setup import configure_logging
from perler_pattern.paths import icon_path
from perler_pattern.presentation.main_window import MainWindow
from perler_pattern.presentation.style import OFFICE_STYLESHEET


def run_application() -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    application = QApplication(sys.argv)
    configure_logging()
    application.setApplicationName("拼豆图纸生成器")
    application.setApplicationVersion("2.0.0")
    application.setOrganizationName("PBPG")
    application.setWindowIcon(QIcon(str(icon_path("app_logo.svg"))))
    application.setStyleSheet(OFFICE_STYLESHEET)
    window = MainWindow()
    window.show()
    if "--smoke-test" in sys.argv:
        def finish_smoke_test() -> None:
            window.project.dirty = False
            window.close()
            application.quit()

        QTimer.singleShot(800, finish_smoke_test)
    return application.exec()
