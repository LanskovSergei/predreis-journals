# Электронные журналы предрейсовых осмотров

Сервис ведёт **журнал медицинских осмотров** и **журнал технического контроля**, формирует отчётные PDF
и электронные журналы (ZIP, подписанный УКЭП организации). Работает на отдельном домене и сервере,
обменивается данными с **Предрейс ONLINE**. ТЗ: «Электронные журналы предрейсовых осмотров».

Принцип: **точка опоры — Предрейс** (пользователи, организации, водители, ТС, подпись, ЭПЛ).
Журналы хранят реплики справочников и снимок реквизитов в каждой записи; криптографии в сервисе нет.

## Быстрый старт

```bash
cp .env.example .env            # заполнить JOURNALS_PREDREIS_CLIENT_SECRET и JOURNALS_RABBITMQ_URL
docker compose up -d --build    # postgres, redis, миграции, api (127.0.0.1:8000), worker, consumer
open http://127.0.0.1:8000/docs
```

Локально:

```bash
python -m venv .venv && . .venv/bin/activate
make install                    # pip install -e ".[dev]"
alembic upgrade head
make run                        # uvicorn с автоперезагрузкой
make worker                     # ARQ: справочники и задачи подписи
python -m app.workers.consumer  # потребитель очереди осмотров (RabbitMQ)
python -m app.workers.replay    # повторная обработка отказов из inbox_failures
```

PDF формируется ReportLab; шрифт DejaVu лежит в репозитории (`app/assets/fonts`), системные библиотеки не нужны.

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
| Асинхронная подпись записей и журнала через Предрейс (задачи, опрос, отказ, таймаут) | ✅ |
| Отчётные PDF «Выгрузка» (медосмотры, техконтроль) | ✅ |
| Приём осмотров из очереди RabbitMQ (идемпотентно, привязка по реквизитам, `inbox_failures`) | ✅ (формат сообщений сверяется по образцам) |
| Запросы на удаление, подтверждение Админ/СА | ✅ |
| Audit log (хеш-цепочка, append-only) | ✅ |
| Статистика стартовой страницы | ✅ |
| Вход пользователей: те же почта и пароль, токен проверяет Предрейс, ограничение попыток | ✅ (путь входа Предрейса уточняется) |
| Синхронизация справочников из Предрейса (инкрементально) | ✅ (формат ответа сверяется по образцу) |
| Электронный журнал: статусы, резервирование, подпись/отклонение СА | ✅ |
| Электронный журнал: сборка ZIP, `journal.xml`/`manifest.xml`, audit log, PDF с плашкой, самопроверка | ✅ |
| **OCR сканов** (`ocr/service.py`, клиент Yandex Vision готов) | ⏳ заглушка |
| Создание записей на период (диапазон дат) | ⏳ не реализовано, вопрос к ТЗ |
| XSD для XML записи и журнала | ⏳ схема-черновик |

Допущения и открытые вопросы — в [docs/ASSUMPTIONS.md](docs/ASSUMPTIONS.md).

## Документы

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — архитектура, модель данных, FSM, безопасность
- [docs/xml-schema.md](docs/xml-schema.md) — форматы XML (XSD) и образцы
- [docs/predreis-integration.md](docs/predreis-integration.md) — интеграция с Предрейсом: справочники, очередь, подпись, разбор сбоев
- [docs/container-format.md](docs/container-format.md) — состав ZIP-контейнера журнала и порядок его проверки
- [docs/FRONTEND.md](docs/FRONTEND.md) — руководство для разработчика фронтенда (вход, статусы, подпись, ошибки)
- [docs/DEPLOY.md](docs/DEPLOY.md) — развёртывание на сервере: прокси и TLS, обновление, копии, мониторинг, чек-лист
- [docs/OPERATIONS.md](docs/OPERATIONS.md) — эксплуатация: процессы, мониторинг, команды обслуживания, производительность
- [docs/openapi.json](docs/openapi.json) и [docs/frontend/api.d.ts](docs/frontend/api.d.ts) — контракт API и TypeScript-типы (`make types`)

## Структура

```
app/
  core/            конфиг, БД, ошибки, проверка токенов, хранилище, время
  domain/          enum'ы, права, FSM, маскирование, валидаторы (чистая логика)
  models/          SQLAlchemy 2 (async)
  modules/         medical, technical, catalog, signing, reports, ejournal,
                   deletion, ocr, stats, audit, integration — router/service/schemas
  integrations/    predreis (клиент, схемы, сообщения очереди, разбор CMS), yandex_vision
  workers/         ARQ (справочники, подпись) и потребитель очереди
  assets/fonts/    шрифт DejaVu для PDF
alembic/           0001 схема, 0002 триггеры неизменяемости
tests/             юнит и интеграционные (PostgreSQL)
```

## Разработка и проверка

```bash
make dev-stack      # локальный стенд: подставной ПРЕДРЕЙС + API + воркер + потребитель (нужны PostgreSQL, Redis, RabbitMQ)
docker compose -f docker-compose.dev.yml up --build   # то же самое в Docker (файл не проверялся в Docker)
make e2e            # сквозной тест на настоящих процессах (JOURNALS_E2E=1)
make load-seed bench   # нагрузочные замеры на отдельной тестовой БД
make audit-check    # проверка хеш-цепочки журнала аудита
make lock           # пересобрать requirements*.txt (версии и хеши) из pyproject.toml; make audit — проверка уязвимостей
```

Подставной ПРЕДРЕЙС (`tools/fake_predreis`) повторяет контракт сервисного API; тестовые пользователи и управление
(`/_dev/...`) описаны в [docs/FRONTEND.md](docs/FRONTEND.md), раздел 12.

