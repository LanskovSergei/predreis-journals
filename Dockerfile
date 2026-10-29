FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# PDF рисует ReportLab со шрифтом из репозитория: системные библиотеки и шрифты не нужны.

WORKDIR /srv

# Зависимости ставятся строго из блокировки (версии и контрольные суммы зафиксированы), затем сам пакет.
# Для стенда разработчика сборка получает LOCK=requirements-dev.txt (см. docker-compose.dev.yml).
ARG LOCK=requirements.txt
COPY ${LOCK} ./requirements.txt
RUN pip install --require-hashes -r requirements.txt

COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install --no-deps .

COPY alembic.ini ./
COPY alembic ./alembic

RUN useradd --create-home --uid 10001 journals \
    && mkdir -p /var/lib/journals/storage \
    && chown -R journals:journals /var/lib/journals
USER journals

EXPOSE 8000
# --no-access-log: журнал Uvicorn пишет строку запроса (в поиске бывают фамилии); свой журнал обращений
# приложения пишет только шаблон маршрута (app/core/observability.py).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--no-access-log"]
