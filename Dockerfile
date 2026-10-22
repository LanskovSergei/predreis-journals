FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Библиотеки для WeasyPrint и шрифты с кириллицей для PDF
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b shared-mime-info \
        fonts-dejavu-core fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install .

COPY alembic.ini ./
COPY alembic ./alembic

RUN useradd --create-home --uid 10001 journals \
    && mkdir -p /var/lib/journals/storage \
    && chown -R journals:journals /var/lib/journals
USER journals

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
