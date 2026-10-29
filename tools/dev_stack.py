"""Локальный стенд: подставной ПРЕДРЕЙС + API + воркер + потребитель очереди (реальные процессы).

Нужны запущенные PostgreSQL, Redis и RabbitMQ. Запуск: `python -m tools.dev_stack` (Ctrl+C — остановка).
Параметры: JOURNALS_DEV_DB (по умолчанию journals_dev, должна существовать и быть пустой/тестовой).
Тестовые пользователи и пароль (password) — в выводе и на http://127.0.0.1:9000/_dev/users.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
FAKE_PORT, API_PORT = 9000, 8000


class DevStack:
    """Управляет процессами стенда и их журналами."""

    def __init__(self, db_name: str = "journals_dev", *, sign_delay: float = 3.0) -> None:
        """db_name — база PostgreSQL; sign_delay — задержка подписи у подставного ПРЕДРЕЙСа, с."""
        self.db_name = db_name
        self.workdir = Path(tempfile.mkdtemp(prefix="journals-stack-"))
        self.procs: dict[str, subprocess.Popen[bytes]] = {}
        self.env = {
            **os.environ,
            "FAKE_SIGN_DELAY": str(sign_delay),
            "FAKE_CLIENT_SECRET": "dev-secret",
            "JOURNALS_DATABASE_URL": f"postgresql+asyncpg://journals:journals@127.0.0.1:5432/{db_name}",
            "JOURNALS_REDIS_URL": "redis://127.0.0.1:6379/0",
            "JOURNALS_STORAGE_DIR": str(self.workdir / "storage"),
            "JOURNALS_PREDREIS_BASE_URL": f"http://127.0.0.1:{FAKE_PORT}",
            "JOURNALS_PREDREIS_CLIENT_SECRET": "dev-secret",
            "JOURNALS_RABBITMQ_URL": "amqp://guest:guest@127.0.0.1:5672/",
            "JOURNALS_RABBITMQ_REQUEUE_DELAY_S": "2",
            "JOURNALS_LOG_LEVEL": "INFO",
            "PYTHONPATH": str(ROOT),
        }

    def _spawn(self, name: str, *cmd: str) -> None:
        """Запускает процесс в отдельной группе, вывод — в файл журнала."""
        log = (self.workdir / f"{name}.log").open("wb")
        self.procs[name] = subprocess.Popen(
            cmd,
            cwd=ROOT,
            env=self.env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    def log(self, name: str, tail: int = 25) -> str:
        """Последние строки журнала процесса."""
        path = self.workdir / f"{name}.log"
        return (
            "\n".join(path.read_text("utf-8", "replace").splitlines()[-tail:])
            if path.exists()
            else ""
        )

    def wait_for(self, what: str, check: Callable[[], bool], timeout: float = 60.0) -> None:
        """Ждёт выполнения условия; при провале показывает журналы процессов."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if check():
                    return
            except (httpx.HTTPError, OSError, KeyError, ValueError):
                pass
            for name, proc in self.procs.items():
                if proc.poll() is not None:
                    raise RuntimeError(
                        f"Процесс {name} завершился ({proc.returncode}):\n{self.log(name)}"
                    )
            time.sleep(0.5)
        logs = "\n".join(f"--- {n} ---\n{self.log(n)}" for n in self.procs)
        raise TimeoutError(f"Не дождались: {what}\n{logs}")

    def start(self) -> None:
        """Применяет миграции, очищает данные и поднимает процессы."""
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=ROOT,
            env=self.env,
            check=True,
        )
        self._reset_data()
        py = sys.executable
        self._spawn(
            "fake", py, "-m", "uvicorn", "tools.fake_predreis.app:app", "--port", str(FAKE_PORT)
        )
        self.wait_for(
            "подставной Предрейс",
            lambda: httpx.get(f"http://127.0.0.1:{FAKE_PORT}/_dev/users").status_code == 200,
        )
        self._spawn(
            "api", py, "-m", "uvicorn", "app.main:app", "--port", str(API_PORT), "--no-access-log"
        )
        self._spawn("worker", py, "-m", "arq", "app.workers.settings.WorkerSettings")
        self._spawn("consumer", py, "-m", "app.workers.consumer")
        self.wait_for(
            "API", lambda: httpx.get(f"http://127.0.0.1:{API_PORT}/ready").status_code == 200
        )
        self.wait_for("потребитель очереди", lambda: "Слушаю очередь" in self.log("consumer", 200))

    def _reset_data(self) -> None:
        """Очищает таблицы и очередь, чтобы стенд стартовал с нуля."""
        import asyncio

        import aio_pika
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        from app.models import Base

        async def run() -> None:
            """Очистка БД и очереди."""
            engine = create_async_engine(self.env["JOURNALS_DATABASE_URL"])
            tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
            async with engine.begin() as conn:
                await conn.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))
            await engine.dispose()
            connection = await aio_pika.connect_robust(self.env["JOURNALS_RABBITMQ_URL"])
            async with connection:
                channel = await connection.channel()
                queue = await channel.declare_queue("journal.events.outgoing", durable=True)
                await queue.purge()

        asyncio.run(run())

    def stop(self) -> None:
        """Останавливает процессы и удаляет рабочий каталог."""
        for proc in self.procs.values():
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
        for proc in self.procs.values():
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
        shutil.rmtree(self.workdir, ignore_errors=True)


def main() -> None:
    """Поднимает стенд и держит его до Ctrl+C."""
    stack = DevStack(os.environ.get("JOURNALS_DEV_DB", "journals_dev"), sign_delay=3.0)
    try:
        stack.start()
        print(
            f"\nСтенд готов:\n  API журналов   http://127.0.0.1:{API_PORT}/docs\n"
            f"  подставной ПРЕДРЕЙС   http://127.0.0.1:{FAKE_PORT}/_dev/users (пароль: password)\n"
            f"  опубликовать осмотры:  curl -X POST http://127.0.0.1:{FAKE_PORT}/_dev/publish "
            "-H 'content-type: application/json' -d '{\"waybills\": 3}'\n  Ctrl+C — остановить"
        )
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        stack.stop()


if __name__ == "__main__":
    main()
