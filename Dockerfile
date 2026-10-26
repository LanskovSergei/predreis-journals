FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# PDF рисует ReportLab со шрифтом из репозитория: системные библиотеки и шрифты не нужны.

WORKDIR /srv
COPY pyproject.toml README.md ./
COPY app ./app
# EXTRAS="[dev]" ставит и инструменты разработки (нужны подставному ПРЕДРЕЙСу в docker-compose.dev.yml)
ARG EXTRAS=""
RUN pip install ".${EXTRAS}"

COPY alembic.ini ./
COPY alembic ./alembic

RUN useradd --create-home --uid 10001 journals \
    && mkdir -p /var/lib/journals/storage \
    && chown -R journals:journals /var/lib/journals
USER journals

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
