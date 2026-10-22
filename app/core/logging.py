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
                "default": {"format": "%(asctime)s %(levelname)-7s %(name)s: %(message)s"},
            },
            "handlers": {
                "console": {"class": "logging.StreamHandler", "formatter": "default"},
            },
            "root": {"level": level.upper(), "handlers": ["console"]},
        }
    )
