"""Structured logging: кожен запис логу -- JSON-обʼєкт з окремими полями,
а не рядок для regex-парсингу. Легко фільтрувати/агрегувати машиною
(напр. "усі виклики check_return_policy довші за 2с").

Ті самі tool/duration/call_id, що писалися в AuditLog у 010 --
тут вони йдуть паралельно і в лог, structured-форматером.
"""

import json
import logging
from datetime import datetime, timezone


class StructuredFormatter(logging.Formatter):
    """Форматер, що конвертує кожен LogRecord у рядок JSON."""

    EXTRA_FIELDS = ("tool", "duration", "attempt", "call_id")

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in self.EXTRA_FIELDS:
            if hasattr(record, key):
                log_data[key] = getattr(record, key)
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_data, ensure_ascii=False)


def make_logger() -> logging.Logger:
    handler = logging.StreamHandler()
    handler.setFormatter(StructuredFormatter())
    logger = logging.getLogger("agent.tools.structured_demo")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    return logger


if __name__ == "__main__":
    logger = make_logger()

    logger.info(
        "Спроба 1/3",
        extra={"tool": "check_return_policy", "call_id": "check_return_policy_001", "attempt": 1},
    )
    logger.info(
        "Успіх за 0.342s",
        extra={"tool": "check_return_policy", "call_id": "check_return_policy_001", "duration": 0.342},
    )
    try:
        1 / 0
    except ZeroDivisionError:
        logger.error("Критична помилка в інструменті", exc_info=True, extra={"tool": "check_return_policy"})
