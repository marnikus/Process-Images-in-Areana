import logging
from pathlib import Path
from datetime import datetime

def setup_logger(log_dir: Path = Path("logs")) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{datetime.now().strftime('%Y-%m-%d')}.log"
    logger = logging.getLogger("arena_processor")
    logger.setLevel(logging.INFO)
    # Avoid duplicate handlers
    if not logger.handlers:
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setLevel(logging.INFO)
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        fh.setFormatter(formatter)
        logger.addHandler(fh)

        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        ch.setFormatter(formatter)
        logger.addHandler(ch)
    return logger

def get_logger() -> logging.Logger:
    return logging.getLogger("arena_processor")
