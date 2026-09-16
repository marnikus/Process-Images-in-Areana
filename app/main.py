"""Main entry point for Arena Image Processor."""
import sys
import asyncio
from pathlib import Path

from PySide6.QtWidgets import QApplication
from qasync import QEventLoop

from .ui.main_window import MainWindow
from .utils.logging import setup_logger

def main() -> int:
    app = QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    logger = setup_logger()
    logger.info("Starting Arena Image Processor")

    window = MainWindow(state_path=Path("config/app_state.json"))
    window.show()

    with loop:
        loop.run_forever()

    logger.info("Application exited cleanly")
    return 0

if __name__ == "__main__":
    sys.exit(main())
