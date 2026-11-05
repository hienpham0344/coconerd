import json
import logging
from datetime import UTC, datetime


class JsonFormatter(logging.Formatter):
    _fields = (
        "request_id",
        "guild_id",
        "message_id",
        "topic_id",
        "agent_name",
        "task_route",
        "model_id",
        "latency_ms",
        "status",
        "error_type",
        "status_code",
    )

    def format(self, record: logging.LogRecord) -> str:
        event: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in self._fields:
            value = getattr(record, field, None)
            if value is not None:
                event[field] = value
        if record.exc_info:
            event["exception"] = self.formatException(record.exc_info)
        return json.dumps(event, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
