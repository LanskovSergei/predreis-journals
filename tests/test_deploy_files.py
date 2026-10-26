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
    """Скрипт копирования исполняемый, строгий режим bash, дамп проверяется перед использованием."""
    script = ROOT / "deploy" / "backup.sh"
    assert script.stat().st_mode & 0o111
    text = script.read_text(encoding="utf-8")
    assert "set -euo pipefail" in text and "pg_restore --list" in text and ".part" in text
