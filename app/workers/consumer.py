"""Потребитель очереди событий осмотров Предрейса (RabbitMQ, `journal.events.outgoing`).

Запуск: `python -m app.workers.consumer`. Сообщения обрабатываются по одному (prefetch=1) в порядке
создания. Исход каждого: ACK (обработано, пропущено или сохранено в `inbox_failures`) либо
повтор позже (зависимость не синхронизирована, БД недоступна). Бесконечный повтор исключён:
после `MAX_DEPENDENCY_ATTEMPTS` попыток сообщение сохраняется в `inbox_failures`.
"""

from __future__ import annotations

import asyncio
import json
import logging
from enum import Enum

import aio_pika
from pydantic import ValidationError
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.db import get_sessionmaker
from app.core.errors import AppError
from app.core.logging import setup_logging
from app.core.storage import Storage, get_storage
from app.integrations.predreis.events import Envelope, UnmappableEventError, map_envelope
from app.modules.integration.failures import record_failure
from app.modules.integration.service import IntegrationService

logger = logging.getLogger(__name__)

MAX_DEPENDENCY_ATTEMPTS = 20


class Outcome(str, Enum):
    """Исход обработки сообщения."""

    ACK = "ack"
    REQUEUE = "requeue"


async def process_body(
    body: bytes,
    session_factory: async_sessionmaker[AsyncSession],
    storage: Storage,
    settings: Settings,
    attempts: dict[str, int] | None = None,
) -> Outcome:
    """Обрабатывает тело сообщения; не бросает исключений для «плохих» данных."""
    attempts = attempts if attempts is not None else {}
    try:
        envelope = Envelope.model_validate(json.loads(body))
    except (ValueError, ValidationError) as exc:
        async with session_factory() as session:
            await record_failure(
                session,
                message_id="?",
                event_type=None,
                reason="bad_envelope",
                detail=str(exc)[:500],
            )
        return Outcome.ACK
    try:
        event = map_envelope(envelope)
    except UnmappableEventError as exc:
        async with session_factory() as session:
            await record_failure(
                session,
                message_id=envelope.id,
                event_type=envelope.event_type,
                reason=exc.reason,
                detail=exc.detail,
                payload=envelope.payload,
            )
        return Outcome.ACK
    try:
        async with session_factory() as session:
            result = await IntegrationService(session, storage, settings).handle(event)
        logger.info("Сообщение %s: %s", envelope.id, result)
        attempts.pop(envelope.id, None)
        return Outcome.ACK
    except AppError as exc:
        if exc.code == "dependency_missing":
            attempts[envelope.id] = attempts.get(envelope.id, 0) + 1
            if attempts[envelope.id] < MAX_DEPENDENCY_ATTEMPTS:
                return Outcome.REQUEUE
        async with session_factory() as session:
            await record_failure(
                session,
                message_id=envelope.id,
                event_type=envelope.event_type,
                reason=exc.code,
                detail=exc.message,
                payload=envelope.payload,
            )
        attempts.pop(envelope.id, None)
        return Outcome.ACK
    except (DBAPIError, SQLAlchemyError, OSError) as exc:
        logger.error("Временный сбой при обработке %s: %s", envelope.id, type(exc).__name__)
        return Outcome.REQUEUE


class EventConsumer:
    """Подключение к RabbitMQ и цикл чтения очереди."""

    def __init__(self, settings: Settings) -> None:
        """Сохраняет настройки и состояние счётчиков повторов."""
        self.settings = settings
        self.attempts: dict[str, int] = {}
        self._stop = asyncio.Event()

    def stop(self) -> None:
        """Просит цикл завершиться после текущего сообщения."""
        self._stop.set()

    async def run(self) -> None:
        """Читает очередь, пока не получен сигнал остановки (соединение переподключается само)."""
        connection = await aio_pika.connect_robust(self.settings.rabbitmq_url)
        async with connection:
            channel = await connection.channel()
            await channel.set_qos(prefetch_count=1)
            queue = await channel.declare_queue(self.settings.rabbitmq_queue, passive=True)
            logger.info("Слушаю очередь %s", self.settings.rabbitmq_queue)
            async with queue.iterator() as messages:
                async for message in messages:
                    outcome = await process_body(
                        message.body,
                        get_sessionmaker(),
                        get_storage(),
                        self.settings,
                        self.attempts,
                    )
                    if outcome is Outcome.ACK:
                        await message.ack()
                    else:
                        await asyncio.sleep(self.settings.rabbitmq_requeue_delay_s)
                        await message.nack(requeue=True)
                    if self._stop.is_set():
                        break


async def main() -> None:
    """Точка входа процесса-потребителя."""
    import signal

    settings = get_settings()
    setup_logging(settings.log_level)
    consumer = EventConsumer(settings)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, consumer.stop)
    await consumer.run()


if __name__ == "__main__":
    asyncio.run(main())
