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
    assert "resolver 127.0.0.11" in conf
    assert "set $journals_upstream http://journals_api:8000;" in conf
    assert "proxy_pass $journals_upstream;" in conf
    assert "set $journals_frontend http://journals_frontend:80;" in conf
    assert "proxy_pass $journals_frontend;" in conf
    assert "rewrite ^/journals/(.*)$ /$1 break;" in conf  # у API префикс срезается
    assert "location ^~ /journals/api/" in conf and "location ^~ /journals/ {" in conf
    for exact in ("docs", "openapi.json", "health", "ready"):
        assert f"location = /journals/{exact}" in conf
    # при ^~ nginx не проверяет регулярные выражения: в журнальном фрагменте их быть не должно
    assert "location ~" not in conf
    assert "location ^~ /journals/metrics" in conf
    backup = (ROOT / "deploy" / "platform" / "backup.sh").read_text(encoding="utf-8")
    assert "set -euo pipefail" in backup and "pg_restore --list" in backup and ".part" in backup


def test_platform_compose_gives_way_to_the_platform_on_cpu() -> None:
    """На сервере платформы 2 ядра: журналы не больше ядра на контейнер и с половинным приоритетом."""
    compose = _load("docker-compose.platform.yml")
    for name, svc in compose["services"].items():
        assert float(svc["cpus"]) <= 1.0, name
        assert svc["cpu_shares"] < 1024, name  # 1024 — вес контейнеров платформы по умолчанию
    assert compose["networks"]["predreis_net"]["name"] == "${PREDREIS_NETWORK:-predreis_net}"


def test_env_example_has_no_duplicate_keys() -> None:
    """В примере настроек каждый ключ один раз: иначе неясно, какое значение победит."""
    lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    keys = [ln.split("=", 1)[0] for ln in lines if ln and not ln.startswith("#") and "=" in ln]
    assert len(keys) == len(set(keys)), sorted({k for k in keys if keys.count(k) > 1})


def test_settings_load_from_the_env_example_as_is(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Пример настроек читается целиком, включая пустые значения: пустое значение — «не задано».

    На сервере пустая строка JOURNALS_EPL_IMPORT_FROM= уронила миграции ошибкой разбора даты.
    """
    import os

    from app.core.config import Settings

    for key in [k for k in os.environ if k.startswith("JOURNALS_")]:
        monkeypatch.delenv(key)
    lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    for line in lines:
        if line and not line.startswith("#") and "=" in line and line.startswith("JOURNALS_"):
            key, value = line.split("=", 1)
            monkeypatch.setenv(key, value)
    settings = Settings(_env_file=None)
    assert settings.epl_import_from is None and settings.metrics_token is None


def test_frontend_container_serves_only_static_files() -> None:
    """Контейнер фронтенда: только в сети платформы (базе и API он не нужен), с пределами ресурсов;
    сборка из зафиксированных зависимостей (package-lock.json, npm ci)."""
    svc = _load("docker-compose.platform.yml")["services"]["journals-frontend"]
    assert svc["container_name"] == "journals_frontend" and svc["networks"] == ["predreis_net"]
    assert "ports" not in svc
    dockerfile = (ROOT / "frontend" / "Dockerfile").read_text(encoding="utf-8")
    assert "npm ci" in dockerfile and (ROOT / "frontend" / "package-lock.json").exists()
    conf = (ROOT / "frontend" / "nginx.conf").read_text(encoding="utf-8")
    assert "try_files $uri /journals/index.html;" in conf  # маршруты приложения отдают index.html
