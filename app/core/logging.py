"""Настройка стандартного логирования."""

from __future__ import annotations

import logging.config


def setup_logging(level: str = "INFO") -> None:
    """Настраивает формат и уровень логов для всего приложения."""
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": "%(asctime)s %(levelname)-7s [%(request_id)s] %(name)s: %(message)s"
                },
            },
            "filters": {"request_id": {"()": "app.core.observability.RequestIdFilter"}},
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                    "filters": ["request_id"],
                },
            },
            "root": {"level": level.upper(), "handlers": ["console"]},
        }
    )
