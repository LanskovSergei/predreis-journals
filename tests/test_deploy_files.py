"""Файлы развёртывания не «гниют»: ключевые настройки безопасности и состав проверяются тестом."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str) -> dict:
    """Читает YAML из корня репозитория."""
    return yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))


def test_production_compose_is_safe_and_complete() -> None:
    """Боевой compose: пароль БД из .env, доверие к прокси, проверка готовности, ротация логов."""
    compose = _load("docker-compose.yml")
    services = compose["services"]
    assert set(services) == {"postgres", "redis", "migrate", "api", "worker", "consumer"}
    assert "${POSTGRES_PASSWORD:?" in services["postgres"]["environment"]["POSTGRES_PASSWORD"]
    api = services["api"]
    # Без доверия к X-Forwarded-For все клиенты выглядят одним адресом прокси (защита входа по адресу).
    assert "--proxy-headers" in api["command"] and "--forwarded-allow-ips=*" in api["command"]
    assert api["ports"] == [
        "127.0.0.1:8000:8000"
    ]  # доверие «*» допустимо только при такой привязке
    assert "healthcheck" in api
    for name, svc in services.items():
        assert svc.get("logging", {}).get("options", {}).get("max-size"), (
            f"{name}: нет ротации логов"
        )
    published = [p for s in services.values() for p in s.get("ports", [])]
    assert all(p.startswith("127.0.0.1:") for p in published)


def test_dev_compose_publishes_only_to_localhost() -> None:
    """Стенд разработчика не открывает порты наружу."""
    services = _load("docker-compose.dev.yml")["services"]
    published = [p for s in services.values() for p in s.get("ports", [])]
    assert published and all(p.startswith("127.0.0.1:") for p in published)


def test_proxy_templates_hide_metrics_and_limit_body() -> None:
    """Шаблоны прокси закрывают /metrics снаружи и ограничивают размер запроса."""
    caddy = (ROOT / "deploy" / "Caddyfile").read_text(encoding="utf-8")
    nginx = (ROOT / "deploy" / "nginx.conf").read_text(encoding="utf-8")
    assert "/metrics" in caddy and "respond @metrics 404" in caddy and "max_size" in caddy
    assert (
        "location /metrics" in nginx and "return 404" in nginx and "client_max_body_size" in nginx
    )
    assert "Strict-Transport-Security" in caddy and "Strict-Transport-Security" in nginx


def test_alert_rules_reference_existing_metrics() -> None:
    """Правила оповещений ссылаются на метрики, которые сервис действительно отдаёт."""
    alerts = _load("deploy/alerts.yml")
    exprs = " ".join(r["expr"] for g in alerts["groups"] for r in g["rules"])
    source = (ROOT / "app" / "modules" / "metrics.py").read_text(encoding="utf-8") + (
        ROOT / "app" / "core" / "observability.py"
    ).read_text(encoding="utf-8")
    for metric in (
        "journals_http_request_seconds",
        "journals_sign_jobs",
        "journals_sign_job_oldest_active_age_seconds",
        "journals_catalog_sync_age_seconds",
        "journals_inbox_failures",
    ):
        assert metric in exprs and metric in source, metric


def test_backup_script_is_executable_and_safe() -> None:
    """Скрипт копирования исполняемый (по индексу Git), строгий режим bash, дамп проверяется."""
    import subprocess

    text = (ROOT / "deploy" / "backup.sh").read_text(encoding="utf-8")
    assert "set -euo pipefail" in text and "pg_restore --list" in text and ".part" in text
    # Режим файла берём из индекса Git: на Windows файловая система флага исполняемости не хранит.
    listed = subprocess.run(
        ["git", "ls-files", "-s", "deploy/backup.sh"], cwd=ROOT, capture_output=True, text=True
    )
    if listed.returncode == 0 and listed.stdout.strip():
        assert listed.stdout.startswith("100755"), "deploy/backup.sh должен быть исполняемым в Git"


def test_uvicorn_access_log_is_disabled_everywhere() -> None:
    """Журнал Uvicorn пишет строку запроса (в поиске бывают фамилии), поэтому он выключен."""
    api = _load("docker-compose.yml")["services"]["api"]
    assert "--no-access-log" in api["command"]
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    cmd = next(line for line in dockerfile.splitlines() if line.startswith("CMD"))
    assert "--no-access-log" in cmd
    assert '"--no-access-log"' in (ROOT / "tools" / "dev_stack.py").read_text(encoding="utf-8")


def _size(value: str) -> int:
    """Размер вида «1g», «256m» в мегабайтах."""
    num, unit = int(value[:-1]), value[-1].lower()
    return num * 1024 if unit == "g" else num


def test_platform_compose_keeps_journals_separate() -> None:
    """Набор для сервера платформы: своя база вне сети платформы, уникальные имена, порты не открыты."""
    compose = _load("docker-compose.platform.yml")
    services = compose["services"]
    assert all(
        name.startswith("journals-") for name in services
    )  # не перепутать с postgres/redis платформы
    assert services["journals-db"]["networks"] == [
        "journals"
    ]  # медицинские данные недоступны контейнерам платформы
    assert services["journals-redis"]["networks"] == ["journals"]
    for name in ("journals-api", "journals-worker", "journals-consumer"):
        assert "predreis_net" in services[name]["networks"], name
    assert compose["networks"]["predreis_net"]["external"] is True
    assert all(
        "ports" not in svc for svc in services.values()
    )  # снаружи только через nginx платформы
    api = services["journals-api"]
    assert api["container_name"] == "journals_api" and "--port=8000" in api["command"]
    assert "--no-access-log" in api["command"]
    assert "--root-path=/journals" in api["command"]


def test_platform_compose_fits_the_agreed_memory_limit() -> None:
    """У каждого постоянного сервиса предел памяти без подкачки; в сумме не больше согласованных 3,5 ГБ."""
    services = _load("docker-compose.platform.yml")["services"]
    total = 0
    for name, svc in services.items():
        assert svc["mem_limit"] == svc["memswap_limit"], name
        if name != "journals-migrate":  # миграции отрабатывают и завершаются
            total += _size(svc["mem_limit"])
    assert total <= 3584, total


def test_platform_nginx_snippet_cannot_take_the_platform_down() -> None:
    """Фрагмент nginx: адрес через resolver и переменную (nginx платформы не упадёт без журналов),
    префикс срезается, метрики наружу не отдаются."""
    conf = (ROOT / "deploy" / "platform" / "nginx-journals.conf").read_text(encoding="utf-8")
    assert (
        "resolver 127.0.0.11" in conf
        and "set $journals_upstream http://journals_api:8000;" in conf
    )
    assert (
        "proxy_pass $journals_upstream;" in conf and "rewrite ^/journals/(.*)$ /$1 break;" in conf
    )
    assert "location ^~ /journals/metrics" in conf
    backup = (ROOT / "deploy" / "platform" / "backup.sh").read_text(encoding="utf-8")
    assert "set -euo pipefail" in backup and "pg_restore --list" in backup and ".part" in backup
