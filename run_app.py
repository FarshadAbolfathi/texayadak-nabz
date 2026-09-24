"""نقطهٔ ورود اجرایی برنامه (برای اجرا و برای بسته‌بندی با PyInstaller)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from nabz.ui.app import main  # noqa: E402

if __name__ == "__main__":
    main()
