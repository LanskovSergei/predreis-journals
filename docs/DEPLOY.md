# Развёртывание

Руководство для первого запуска на сервере и последующих обновлений. Шаблоны в каталоге `deploy/`.
**Что проверено, а что нет:** скрипт копирования (`deploy/backup.sh`) выполнен и восстановлен в тестовую БД; правила
оповещений разобраны как YAML; конфигурации Caddy, nginx и `docker-compose.dev.yml` в моей среде проверить нечем
(там нет Docker, Caddy и nginx), поэтому после первого запуска сверьте их по разделу «Проверка после запуска».

## 1. Что нужно

| Компонент | Требование |
|---|---|
| Сервер | Linux, 2 ядра и 4 ГБ памяти для начала (PDF-выгрузка на 5000 строк занимает около 330 МБ), диск с запасом под файлы (около 50-100 КБ на запись) |
| ПО | Docker и Docker Compose v2, `git`, для копий `pg_dump` (клиент PostgreSQL 16), `rsync`; образ собирается строго из `requirements.txt` (версии и хеши зафиксированы) |
| Сеть | входящие 80 и 443; **исходящие** до Предрейса по HTTPS и до RabbitMQ Предрейса (порт 5672 или 5671 для TLS) |
| Имя | DNS-запись домена журналов на этот сервер |
| Время | включена синхронизация времени (NTP): подписи, метки времени и срок токена зависят от часов |

PostgreSQL, Redis и RabbitMQ Предрейса наружу не публикуются: внутри docker-сети журналы видят только свои PostgreSQL и Redis.

## 2. Первый запуск

```bash
git clone https://github.com/LanskovSergei/predreis-journals.git /opt/journals && cd /opt/journals
cp .env.example .env && chmod 600 .env
```

Заполните `.env` (обязательное):

| Переменная | Что указать |
|---|---|
| `POSTGRES_PASSWORD` | длинный случайный пароль (`openssl rand -base64 24`); тот же пароль в `JOURNALS_DATABASE_URL` |
| `JOURNALS_PREDREIS_BASE_URL` | адрес Предрейса |
| `JOURNALS_PREDREIS_CLIENT_SECRET` | секрет сервисного клиента, выданный Предрейсом (новый, перевыпущенный) |
| `JOURNALS_RABBITMQ_URL` | `amqp://пользователь:пароль@хост:5672/` (пользователь с правом чтения очереди `journal.events.outgoing`) |
| `JOURNALS_CORS_ORIGINS` | список адресов фронтенда в формате JSON, например `["https://journals-app.example.ru"]` |
| `JOURNALS_EPL_IMPORT_FROM` | дата запуска журналов (`ГГГГ-ММ-ДД`): осмотры раньше неё не импортируются |
| `JOURNALS_ORG_SIGNER_USER_ID` | **обязательно:** пользователь Предрейса, чей сертификат это УКЭП ООО «ПРЕДРЕЙС» (им подписываются электронные журналы). Без него журнал не подписывается. `JOURNALS_JOURNAL_SIGN_WITH_REQUESTER` в боевом режиме оставьте `false` |
| `JOURNALS_METRICS_TOKEN` | случайная строка для сбора метрик (если нужны) |

```bash
docker compose up -d --build           # миграции выполняются автоматически перед запуском сервисов
docker compose ps                      # все сервисы Up/healthy, migrate — Exited (0)
curl -s http://127.0.0.1:8000/ready    # {"status":"ready"}
docker compose logs --tail=20 consumer # «Слушаю очередь journal.events.outgoing»
```

Если `consumer` пишет, что очереди нет или нет доступа, проверьте имя очереди у Предрейса (`JOURNALS_RABBITMQ_QUEUE`),
пользователя и файрвол. Очередь потребитель только читает; создаёт её Предрейс.

## 3. Обратный прокси и TLS

Рекомендуется Caddy: сертификат Let's Encrypt выпускается и продлевается сам.

```bash
sudo apt install caddy
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile      # заменить journals.example.ru
sudo caddy validate --config /etc/caddy/Caddyfile && sudo systemctl reload caddy
```

Вместо Caddy можно использовать nginx: `deploy/nginx.conf` (дополнительно ограничивает частоту входа).

Обязательно для обоих:

- `/metrics` снаружи закрыт (шаблоны возвращают 404); Prometheus ходит на `127.0.0.1:8000/metrics` с токеном.
- Порт API опубликован только на `127.0.0.1:8000`, поэтому в `docker-compose.yml` для API задано
  `--forwarded-allow-ips=*`: адрес клиента берётся из `X-Forwarded-For`. **Без этого все пользователи выглядят для защиты
  входа одним адресом прокси.** Если прокси окажется на другом хосте или порт API будет открыт наружу, замените `*`
  на адрес прокси.
- Таймаут ответа не меньше 120 с (выгрузка PDF и просмотр журнала).

## 4. Обновление

```bash
cd /opt/journals
deploy/backup.sh                       # копия перед обновлением (раздел 5)
git pull
docker compose up -d --build           # пересборка, миграции, перезапуск
docker compose ps && curl -s http://127.0.0.1:8000/ready
```

Миграции не удаляют данные и рассчитаны на повторный запуск. **Откат:** вернитесь на прежний коммит
(`git checkout <коммит>` и `docker compose up -d --build`). Откатывать *схему* БД (`alembic downgrade`) не нужно:
следующая версия остаётся совместимой с предыдущим кодом, а при несовместимости проще восстановиться из копии (раздел 5).

## 5. Резервные копии и восстановление

Копия состоит из дампа БД и файлов хранилища. `deploy/backup.sh` делает их согласованно, проверяет, что дамп читается,
и удаляет старые дампы:

```bash
export BACKUP_DIR=/var/backups/journals STORAGE_DIR=<каталог тома storage> \
       DATABASE_URL=postgresql://journals:<пароль>@127.0.0.1:5432/journals
# по расписанию, раз в сутки:
15 3 * * * /opt/journals/deploy/backup.sh >> /var/log/journals-backup.log 2>&1
```

Каталог тома `storage` узнайте так: `docker volume inspect journals_storage`. Для доступа к БД с хоста временно
опубликуйте порт на `127.0.0.1` или запускайте `pg_dump` внутри контейнера (`docker compose exec postgres pg_dump ...`).
**Храните копию вне сервера** (другой хост или объектное хранилище): копия на том же диске не защищает от его потери.

Восстановление на новом сервере:

```bash
docker compose up -d postgres
docker compose exec -T postgres pg_restore --no-owner -U journals -d journals < journals-ГГГГММДД-ЧЧММСС.dump
# файлы: скопировать содержимое BACKUP_DIR/files в том storage
docker compose up -d --build
# проверка целостности после восстановления:
docker compose exec api python -m app.maintenance.verify_storage          # файлы и контрольные суммы
docker compose exec api python -m app.maintenance.verify_audit            # хеш-цепочка журнала аудита
```

Расхождения `verify_storage` означают, что копия БД и копия файлов сделаны не одновременно или файл повреждён.
Проверку копий стоит выполнять **регулярно** (например, раз в месяц развернуть последнюю копию на тестовом сервере).

## 6. Мониторинг

- Живость: `GET /health`, готовность (с проверкой БД): `GET /ready`; `docker compose ps` показывает состояние `api`.
- Метрики: `GET /metrics` (Bearer-токен). Пример сбора в `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: journals
    metrics_path: /metrics
    authorization: {type: Bearer, credentials: "<JOURNALS_METRICS_TOKEN>"}
    static_configs: [{targets: ["127.0.0.1:8000"]}]
```

- Оповещения: `deploy/alerts.yml` (недоступность, ошибки 5xx, медленные запросы, зависшая подпись, остановка синхронизации
  справочников, накопление сообщений `inbox_failures`, рост очереди RabbitMQ).
- Логи: `docker compose logs -f api worker consumer`; ротация настроена (20 МБ × 5 файлов на службу). В логах есть
  идентификатор запроса `[...]` (его же возвращает заголовок `X-Request-ID`), пароли, токены и строки запросов не пишутся.
- Раз в сутки/неделю: `verify_audit` и `verify_storage --sample 1000` (быстрая выборочная проверка).

## 7. Безопасность: чек-лист

- [ ] `.env` с правами `600`, в репозиторий не попадает; секрет Предрейса перевыпущен и нигде не пересылался в открытом виде
- [ ] Открыты только 80 и 443 (и SSH только с доверенных адресов); PostgreSQL, Redis, порт 8000 снаружи недоступны
- [ ] `POSTGRES_PASSWORD` задан и не равен `journals`
- [ ] `JOURNALS_ORG_SIGNER_USER_ID` задан, сертификат этого пользователя виден в `GET /api/v1/service/certificates` и действует; `JOURNALS_JOURNAL_SIGN_WITH_REQUESTER=false`
- [ ] `/metrics` снаружи отдаёт 404; `JOURNALS_METRICS_TOKEN` длинный случайный
- [ ] TLS работает, HTTP перенаправляется на HTTPS, включён HSTS
- [ ] Сервис работает от обычного пользователя в контейнере (в образе так и есть: uid 10001)
- [ ] Резервные копии делаются, хранятся вне сервера, восстановление проверено
- [ ] Автоматические обновления ОС включены, перезагрузки ожидаемы (контейнеры имеют `restart: unless-stopped`)

## 8. Проверка после запуска

1. `docker compose ps`: `api` healthy, `worker`, `consumer` работают, `migrate` завершён с кодом 0.
2. `GET https://<домен>/ready` отвечает `ready`; `GET https://<домен>/metrics` отвечает 404.
3. Вход тестовым пользователем с включённым доступом (`POST /api/v1/auth/login`): токен и список прав.
4. Через 5 минут в таблице `organizations` есть записи (воркер подтянул справочники): иначе смотрите `docker compose logs worker`.
5. После первого осмотра в Предрейсе (с QR) в архиве журналов появляется запись типа Б; если нет, смотрите `inbox_failures`.
6. Подпись тестовой записи медиком: статус сменился на «подписана», сертификат виден; журнал за период собирается, СА подписывает,
   ZIP скачивается.
7. С одного адреса несколько раз подряд зайти успешно: не должно быть `429` (проверка, что адрес клиента определяется верно).
