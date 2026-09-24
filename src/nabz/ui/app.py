"""نقطهٔ ورود برنامهٔ گرافیکی تکسایدک نبض."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog

from ..config import CredentialStore
from ..db import Database
from .login import LoginDialog
from .main_window import MainWindow, default_db_path
from .theme import stylesheet


def run(db_path: str | Path | None = None) -> int:
    """برنامه را اجرا می‌کند: ورود با رمز، سپس پنجرهٔ اصلی."""
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("تکسایدک نبض")
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    app.setStyleSheet(stylesheet())

    path = Path(db_path) if db_path else default_db_path()
    db = Database(path)
    store = CredentialStore()

    login = LoginDialog(db)
    if login.exec() != QDialog.DialogCode.Accepted:
        db.close()
        return 0

    window = MainWindow(db, store)
    window.show()
    code = app.exec()
    db.close()
    return code


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
