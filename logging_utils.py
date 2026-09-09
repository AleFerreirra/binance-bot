import json
import logging
import re
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Any, Dict


SECRET_PATTERNS = [
    re.compile(r"(BINANCE_API_KEY=)[^\s]+", re.IGNORECASE),
    re.compile(r"(BINANCE_API_SECRET=)[^\s]+", re.IGNORECASE),
    re.compile(r"([A-Za-z0-9_-]{20,})"),
]


def mask_secret(value: Any) -> Any:
    if value is None:
        return None
    text = str(value)
    for pattern in SECRET_PATTERNS:
        def repl(match):
            token = match.group(0)
            if "=" in token:
                prefix, secret = token.split("=", 1)
                return f"{prefix}={secret[:4]}...{secret[-4:]}" if len(secret) > 8 else f"{prefix}=***"
            if len(token) >= 20:
                return f"{token[:4]}...{token[-4:]}"
            return token
        text = pattern.sub(repl, text)
    return text


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": mask_secret(record.getMessage()),
        }
        if record.exc_info:
            payload["exception"] = mask_secret(self.formatException(record.exc_info))
        for key, value in record.__dict__.items():
            if key.startswith("_") or key in {
                "args", "asctime", "created", "exc_info", "exc_text", "filename",
                "funcName", "levelname", "levelno", "lineno", "module", "msecs",
                "message", "msg", "name", "pathname", "process", "processName",
                "relativeCreated", "stack_info", "thread", "threadName",
            }:
                continue
            payload[key] = mask_secret(value)
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging(config) -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()

    formatter = JsonFormatter()
    file_handler = RotatingFileHandler(
        config.LOG_FILE,
        maxBytes=config.LOG_MAX_BYTES,
        backupCount=config.LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)

    root.addHandler(file_handler)
    root.addHandler(console_handler)
