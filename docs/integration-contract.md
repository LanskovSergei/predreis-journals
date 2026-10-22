# Контракт интеграции Предрейс ↔ журналы (черновик v0)

Имена ролей и полей `epl_details.inspection` нужно сверить с кодом Предрейса.
Схемы событий: `app/integrations/predreis/schemas.py`.

## 1. Вход пользователя (Предрейс = провайдер входа)

Журналы принимают `Authorization: Bearer <JWT>`:

- подпись RS256, ключи по `GET {PREDREIS}/.well-known/jwks.json` (поле `kid` обязательно);
- claims: `iss=predreis-online`, `aud=journals`, `exp`, `sub` (UUID пользователя), `role`
  (`client|dispatcher|medic|mechanic|predreis|admin|superadmin`), `journals_access` (bool),
  `org_id` (для клиента/диспетчера), `name`, `sid` (необязательно).
- Фронтенд журналов получает токен через редирект/обмен кода с Предрейса (способ согласовать).

## 2. Предрейс → журналы: события

`POST {JOURNALS}/integration/v1/events`, заголовки:
`X-Timestamp` (unix, ±300 с) и `X-Signature = hex(HMAC_SHA256(secret, "<timestamp>." + <тело>))`.
Ответ: `200 {"status": "processed" | "duplicate"}`; `409 dependency_missing` — повторить позже
(справочники ещё не синхронизированы); `422` — событие не соответствует контракту.
Доставку делает outbox Предрейса с ретраями. Идемпотентность по `event_id`, а также по паре
`(waybill_id, титул)`: повтор с новым `event_id` запись не дублирует.

Справочники: `organization.upserted`, `driver.upserted`, `vehicle.upserted`, `user.upserted`
(формат — `*Payload` в `app/integrations/predreis/schemas.py`).
**Справочники должны быть доставлены раньше ЭПЛ-событий**: ЭПЛ-событие не создаёт и не меняет реплики.

### 2.1. Событие ЭПЛ: `event_type` = `T2` | `T3` | `T6`

Отправляется **только после получения QR** (`qr_issued=true`). Формат плоский, лишние поля игнорируются.
Эталонный пример — `tests/factories.py::epl_event`.

**Общая часть (Т2, Т3, Т6)**

| Поле | Примечание |
|---|---|
| `event_type` | `T2` / `T3` / `T6` |
| `waybill_id`, `waybill_number`, `gis_uid` | рейс, номер и УИД ГИС ЭПД |
| `qr_issued` | должно быть `true` |
| `org_inn`, `org_name`, `org_address` | реквизиты **на момент осмотра**; `org_kpp`, `org_ogrn` — необязательны (у ИП КПП нет) |
| `driver_last_name`, `driver_first_name`, `driver_middle_name`, `driver_birth_date` | `middle_name` необязателен |
| `driver_license_series`, `driver_license_number` | |
| `driver_gender` | `M` / `F`; **необязательно, пока Предрейс не добавит пол** |
| `specialist_user_id` | UUID медика/механика, **не nullable**; роль должна совпадать с титулом (Т2/Т6 — медик, Т3 — механик) |
| `specialist_last_name`, `specialist_first_name`, `specialist_middle_name` | |
| `exam_datetime`, `exam_tz_offset` | время без пояса дополняется смещением: `"+03:00"`, `"+0300"` или целое число минут |
| `signature_serial`, `signature_owner`, `signature_valid_from`, `signature_valid_to` | сертификат подписанта |
| `notes` | необязательно → «Примечание» записи |
| `source` | `epl` |

**Дополнения к списку полей (нужны от Предрейса)**

| Поле | Зачем |
|---|---|
| `organization_id`, `driver_id` (и `vehicle_id` для Т3) | идентификаторы Предрейса — привязка к репликам справочников |
| `event_id` (UUID) | идемпотентность; если не присылать — выводится из `waybill_id` + `event_type` |
| `signature_b64`, `tsp_b64` (необязательно) | откреплённая подпись титула и метка времени для включения в ZIP электронного журнала |

**Только медосмотр (Т2, Т6)** — обязательны `blood_pressure_systolic`, `blood_pressure_diastolic`, `pulse`,
`temperature`, `alcohol_ppm`, `harmful_factors_detected`, `approved`. Остальные поля сохраняются в
`epl_details`: `alcohol_detected`, `harmful_factors`, `critical_flag`, `recorded_at`, `medic_license_*`,
`medic_org_name`, `vid_mo`, `is_pre_trip` / `is_post_trip`; `complaints` по умолчанию «отсутствуют».

**Только техконтроль (Т3)** — обязательны `vehicle_id`, `vehicle_plate`, `vehicle_brand`, `vehicle_model`,
`odometer`, `approved`. В `epl_details`: `vehicle_type`, `brakes_ok`, `lighting_ok`, `tires_ok`, `released`,
`mechanic_position`, `recorded_at`.

### 2.2. Соответствие полей

| Событие | Запись журнала |
|---|---|
| `T2` / `T6` | медосмотр, `phase` = предрейсовый / послерейсовый |
| `exam_datetime` + `exam_tz_offset` | `performed_at` (с часовым поясом) |
| `approved` | `result`: допущен / не допущен (для Т3 — пройден / не пройден) |
| `blood_pressure_*`, `pulse`, `temperature`, `complaints` | одноимённые показатели |
| `alcohol_ppm` | `alcohol_mgl` (значение как есть; единицы уточняются) |
| `harmful_factors_detected` / `harmful_factors` | признак и текстовое примечание к нему |
| `org_*`, `driver_*`, `vehicle_*`, `specialist_*` | `snapshot` (реквизиты на момент осмотра) |
| `gis_uid`, `waybill_number` | одноимённые колонки |
| `signature_*` | электронный документ записи (серийный номер, владелец, срок действия) |
| остальные поля титула | `epl_details` (JSONB) |

Запись ЭПЛ создаётся сразу в статусе Б, неизменяема и неудаляема для всех ролей.

## 3. Журналы → Предрейс: вызовы

Заголовок `Authorization: Bearer <сервисный токен>`.

| Метод | Назначение |
|---|---|
| `POST /integration/v1/sign` | подпись файла. Тело: `{kind: personal\|organization, signer_user_id, filename, content_b64}`; заголовок `X-On-Behalf-Of: <JWT пользователя>` — Предрейс обязан проверить, что `sub` токена совпадает с `signer_user_id` и что у пользователя есть действующий сертификат. Ответ: `{signature_b64, tsp_b64?, certificate{serial,subject,valid_from,valid_to}, ocsp_status?, signed_at}` |
| `POST /integration/v1/notify` | уведомления из outbox: `deletion.requested`, `deletion.resolved`, `ejournal.submitted`, `ejournal.signed`, `ejournal.rejected` |
| `GET /integration/v1/{organizations\|users\|drivers\|vehicles}?cursor&limit` | сверка: `{items: [...], next_cursor}` в формате `*Payload` |
| `POST /integration/v1/{organizations\|drivers\|vehicles}` | создание «бумажных» сущностей (источник истины — Предрейс); организацию Предрейс заполняет по ИНН |
| `GET /integration/v1/certificates?user_id` | статусы сертификатов медиков и механиков для плашек |

## 4. Что нужно доработать в Предрейсе

1. Флаг `journals_access` и его включение суперадмином; раздел «Электронные журналы» в ЛК.
2. Провайдер входа: JWKS и выдача токена для фронтенда журналов.
3. Outbox отправки `*.upserted` и ЭПЛ-событий `T2/T3/T6` (после QR) с ретраями; в ЭПЛ-события добавить `organization_id`, `driver_id`, `vehicle_id`, `event_id`.
4. API справочников (чтение с курсором, создание «бумажных» организаций/водителей/ТС).
5. `POST /integration/v1/sign` (личная подпись пользователя и подпись организации + TSP + OCSP).
6. Приём `notify`, выдача `certificates`.
7. Поле «пол» у водителя (`driver_gender`).
8. Парсинг по ИНН и ежемесячная сверка реквизитов остаются в Предрейсе; журналы получают `organization.upserted`.
