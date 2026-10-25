"""Конфигурация сервиса «Электронные журналы»."""

from __future__ import annotations

import uuid
from datetime import date
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки приложения. Читаются из переменных окружения с префиксом JOURNALS_."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="JOURNALS_", extra="ignore")

    app_name: str = "Электронные журналы"
    env: str = "dev"
    log_level: str = "INFO"
    business_timezone: str = "Europe/Moscow"
    cors_origins: list[str] = Field(default_factory=list)

    database_url: str = "postgresql+asyncpg://journals:journals@localhost:5432/journals"
    redis_url: str = "redis://localhost:6379/0"

    # --- Интеграция с Предрейс ONLINE ---
    predreis_base_url: str = "https://predreis-online.ru"
    predreis_timeout_s: float = 20.0
    # Сервисный клиент (client credentials). Секрет хранить только в .env на сервере.
    predreis_client_id: str = "journals"
    predreis_client_secret: str = ""
    # Вход пользователей: токен выдаёт Предрейс, журналы только спрашивают, действителен ли он.
    predreis_user_login_path: str = "/api/v1/auth/login"  # уточнить у Предрейса
    auth_cache_ttl_s: int = 30
    auth_negative_cache_ttl_s: int = 5
    auth_cache_max: int = 10_000
    login_max_attempts: int = 10
    login_window_s: int = 300

    # --- Очередь событий осмотров (RabbitMQ Предрейса) ---
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"
    rabbitmq_queue: str = "journal.events.outgoing"
    rabbitmq_requeue_delay_s: float = 30.0
    # Осмотры раньше этой даты не импортируются (журнал ведётся «с даты»); None — всё.
    epl_import_from: date | None = None

    # --- Асинхронная подпись через Предрейс ---
    sign_poll_batch: int = 20
    sign_submit_max_attempts: int = 10
    sign_pending_timeout_s: int = 3600
    journal_sign_document_type: str = "journal.ejournal"
    # Чей сертификат подписывает журнал; пусто — сертификат СА, нажавшего «Подписать».
    org_signer_user_id: uuid.UUID | None = None

    # --- Синхронизация справочников ---
    catalog_page_size: int = 500
    catalog_sync_overlap_s: int = 5
    # Предрейс не имеет API уведомлений; включать, когда он появится.
    predreis_notify_enabled: bool = False

    # --- Хранилище файлов ---
    storage_dir: Path = Path("./var/storage")

    # --- Yandex Vision OCR ---
    yandex_vision_api_key: str = ""
    yandex_vision_folder_id: str = ""
    yandex_vision_url: str = "https://ocr.api.cloud.yandex.net/ocr/v1/recognizeText"

    # --- Пагинация и лимиты ---
    page_size_default: int = 10
    page_size_max: int = 100
    mass_sign_max_batch: int = 50
    export_max_rows: int = 5000

    # --- Реквизиты исполнителя для отчётных PDF (ТЗ, стр. 19-20) ---
    executor_name: str = "ООО «ПРЕДРЕЙС»"
    executor_inn: str = "5027236147"
    executor_address: str = (
        "140032, Московская область, г. Люберцы, пгт. Малаховка, "
        "ул. Шоссейная, д. 40, этаж 1, пом.19,20"
    )
    executor_license: str = (
        "№ Л041-01162-50/00331687 от 23.05.2019 выдана Министерством "
        "здравоохранения Московской области"
    )
    executor_phone: str = "+7 (925) 028-87-55"
    executor_email: str = "predreis@predreis.online"


@lru_cache
def get_settings() -> Settings:
    """Возвращает закэшированный экземпляр настроек."""
    return Settings()
