"""Application logging: daily rotating file in ``<data>/logs`` plus stderr."""

from __future__ import annotations

import logging
import logging.handlers
import re
from pathlib import Path

LOG_FILE_NAME = "kcd-mod-manager.log"
RETAINED_DAYS = 14

_SECRET_PATTERNS = (
    re.compile(r"(apikey['\"]?\s*[:=]\s*['\"]?)([A-Za-z0-9+/=_\-]{12,})", re.IGNORECASE),
    re.compile(r"(api_key['\"]?\s*[:=]\s*['\"]?)([A-Za-z0-9+/=_\-]{12,})", re.IGNORECASE),
)


class RedactingFilter(logging.Filter):
    """Last line of defence: mask anything that looks like an API key."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = message
        for pattern in _SECRET_PATTERNS:
            redacted = pattern.sub(r"\1***", redacted)
        if redacted != message:
            record.msg, record.args = redacted, None
        return True


def configure_logging(logs_dir: Path, level: int = logging.INFO) -> Path | None:
    root = logging.getLogger()
    root.setLevel(level)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    redactor = RedactingFilter()

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.addFilter(redactor)
    root.addHandler(console)

    log_file: Path | None = logs_dir / LOG_FILE_NAME
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.TimedRotatingFileHandler(
            log_file, when="midnight", backupCount=RETAINED_DAYS, encoding="utf-8"
        )
        handler.setFormatter(formatter)
        handler.addFilter(redactor)
        root.addHandler(handler)
    except OSError as exc:
        logging.getLogger(__name__).warning("File logging disabled: %s", exc)
        log_file = None

    for noisy in ("httpx", "httpcore", "websockets", "keyring", "py7zr"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return log_file
