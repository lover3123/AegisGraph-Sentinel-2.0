import os
import logging
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


def validate_environment():
    """Validate required environment variables on startup."""
    load_dotenv()

    required_vars = [
        "API_URL",
        "AEGIS_ALLOWED_ORIGINS",
    ]

    missing_vars = [var for var in required_vars if not os.getenv(var)]

    if missing_vars:
        app_env = (
            os.getenv("AEGIS_ENV")
            or os.getenv("APP_ENV")
            or os.getenv("ENVIRONMENT")
            or "development"
        ).lower()
        if app_env != "production":
            logger.warning(
                "Missing environment variables in %s mode: %s",
                app_env,
                ", ".join(missing_vars),
            )
            return
        raise ValueError(
            f"Missing required environment variables: {', '.join(missing_vars)}. "
            f"Please create a .env file based on .env.example"
        )
