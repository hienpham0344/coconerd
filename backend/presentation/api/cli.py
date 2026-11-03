import uvicorn

from backend.config import get_settings
from backend.logging_config import configure_logging


def main() -> None:
    settings = get_settings()
    configure_logging("DEBUG" if settings.debug else "INFO")
    uvicorn.run(
        "backend.presentation.api.app:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
