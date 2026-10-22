# Электронные журналы предрейсовых осмотров

Сервис ведёт **журнал медицинских осмотров** и **журнал технического контроля**, формирует отчётные PDF
и электронные журналы (ZIP, подписанный УКЭП организации). Работает на отдельном домене и сервере,
обменивается данными с **Предрейс ONLINE**. ТЗ: «Электронные журналы предрейсовых осмотров».

Принцип: **точка опоры — Предрейс** (пользователи, организации, водители, ТС, подпись, ЭПЛ).
Журналы хранят реплики справочников и снимок реквизитов в каждой записи; криптографии в сервисе нет.

## Быстрый старт

```bash
cp .env.example .env            # заполнить секреты (JOURNALS_PREDREIS_*)
docker compose up -d --build    # postgres, redis, миграции, api (127.0.0.1:8000), worker
open http://127.0.0.1:8000/docs
```

Локально:

```bash
python -m venv .venv && . .venv/bin/activate
make install                    # pip install -e ".[dev]"
alembic upgrade head
make run                        # uvicorn с автоперезагрузкой
make worker                     # ARQ: outbox и сверка справочников
```

Для WeasyPrint нужны системные библиотеки (`libpango-1.0-0`, `libpangoft2-1.0-0`) и шрифты с кириллицей
(`fonts-dejavu-core`). В Docker-образе они уже есть.

## Тесты

```bash
pytest -q                                   # юнит-тесты, интеграционные пропускаются
export JOURNALS_TEST_DATABASE_URL=postgresql+asyncpg://journals:journals@localhost:5432/journals_test
pytest -q                                   # + интеграционные на реальном PostgreSQL
make lint typecheck
```

## Состояние реализации

| Область | Статус |
|---|---|
| Архив: создание, список, фильтры, правка, удаление, «снять примечание», доступные действия | ✅ |
| FSM записи А → Б → В, триггеры БД, неизменяемость | ✅ |
| Матрица прав (сверена с ТЗ тестом) | ✅ |
| Маскирование медданных (API и PDF, 323-ФЗ) | ✅ |
| Подпись записи / массовая подпись через Предрейс | ✅ (клиент по контракту, проверено на заглушке) |
| Отчётные PDF «Выгрузка» (медосмотры, техконтроль) | ✅ |
| Приём ЭПЛ Т2/Т3/Т6 и справочников (HMAC, идемпотентность) | ✅ |
| Запросы на удаление, подтверждение Админ/СА | ✅ |
| Audit log (хеш-цепочка, append-only) | ✅ |
| Статистика стартовой страницы | ✅ |
| Outbox → Предрейс, ночная сверка справочников | ✅ (ждёт эндпоинтов Предрейса) |
| Электронный журнал: статусы, резервирование, подпись/отклонение СА | ✅ |
| Электронный журнал: сборка ZIP, `journal.xml`/`manifest.xml`, audit log, PDF с плашкой, самопроверка | ✅ |
| **OCR сканов** (`ocr/service.py`, клиент Yandex Vision готов) | ⏳ заглушка |
| Создание записей на период (диапазон дат) | ⏳ не реализовано, вопрос к ТЗ |
| XSD для XML записи и журнала | ⏳ схема-черновик |

Допущения и открытые вопросы — в [docs/ASSUMPTIONS.md](docs/ASSUMPTIONS.md).

## Документы

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — архитектура, модель данных, FSM, безопасность
- [docs/integration-contract.md](docs/integration-contract.md) — контракт с Предрейсом и список его доработок
- [docs/xml-schema.md](docs/xml-schema.md) — форматы XML (XSD) и образцы
- [docs/container-format.md](docs/container-format.md) — состав ZIP-контейнера журнала и порядок его проверки
- [docs/openapi.json](docs/openapi.json) — контракт API для фронтенда (`make openapi`)

## Структура

```
app/
  core/            конфиг, БД, ошибки, JWT/JWKS, хранилище, время
  domain/          enum'ы, права, FSM, маскирование, валидаторы (чистая логика)
  models/          SQLAlchemy 2 (async)
  modules/         medical, technical, catalog, signing, reports, ejournal,
                   deletion, ocr, stats, audit, integration — router/service/schemas
  integrations/    predreis (клиент, схемы событий), yandex_vision
  workers/         ARQ: outbox, сверка справочников
  templates/pdf/   Jinja2-шаблоны отчётов
alembic/           0001 схема, 0002 триггеры неизменяемости
tests/             юнит и интеграционные (PostgreSQL)
```
