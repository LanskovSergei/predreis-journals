# Форматы XML электронных документов

Схемы — `app/xmlschemas/*.xsd` (XSD 1.0). Статус: **черновик, ждёт утверждения**.
Образцы — `docs/examples/*.xml`; они генерируются кодом (`python scripts/gen_examples.py`) и проверяются
тестом: устаревший образец роняет CI.

| Документ | Схема | Пространство имён | Где используется |
|---|---|---|---|
| Электронная запись | `record.xsd` | `urn:predreis:journals:record:1.0` | `record.xml` — подписывается УКЭП специалиста (документ типа 1) |
| Электронный журнал | `journal.xsd` | `urn:predreis:journals:journal:1.0` | `journal.xml` — подписывается УКЭП организации (документ типа 2) |
| Манифест контейнера | `manifest.xsd` | `urn:predreis:journals:manifest:1.0` | `manifest.xml` — реестр файлов ZIP (размер, SHA-256, назначение) |

## Правила

- **Версия формата** — в пространстве имён и в атрибуте `version` (зафиксирован `1.0`). Несовместимое
  изменение = новое пространство имён (`…:2.0`) и новый XSD; старые документы остаются проверяемыми.
- **Проверка перед подписью.** Каждый XML проверяется по XSD сразу после генерации. Запись с некорректными
  данными не подписывается: массовая подпись вернёт по ней ошибку `record_xml_invalid` с причиной.
- **Детерминированность.** Порядок элементов и форматирование фиксированы: один вход → побайтово один XML
  (важно для хешей и подписей).
- **Время** — только с часовым поясом (`2026-10-14T08:20:00+03:00`), даты — `ГГГГ-ММ-ДД`.
- **Идентификаторы** — UUID строчными буквами; **SHA-256** — 64 строчных hex-символа.
- **Безопасность разбора.** Парсер без DTD, сущностей и сети; `DOCTYPE` и `ENTITY` отклоняются сразу.
- **Пути в манифесте и журнале** — относительные, без `..`, `.`, пустых сегментов и `\`. XSD отсекает только
  абсолютные пути и начало с точки, остальное проверяет код (`safe_archive_path`).

## Запись (`record.xsd`)

Корень `ElectronicRecord @id`. Порядок: `Source`, `Waybill`?, `Organization`, `PerformedAt`, `Specialist @userId`,
затем **одно** из `MedicalExamination` / `TechnicalInspection`, затем `Note`?.

- `Organization` — реквизиты **на момент осмотра** (из `snapshot` записи): `INN`, `KPP`?, `OGRN`?, `Name`,
  `ShortName`?, `LegalAddress`?.
- `Waybill` (`Number`, `GisUid`, `Title` = `T2|T3|T6`) — только у записей из ЭПЛ.
- `Note` — только если примечание не пусто. У записей, подписанных специалистом, его нет: запись с
  примечанием подписать нельзя. У записей из ЭПЛ оно может быть.
- `MedicalExamination`: `Phase` (`pre|post`), `Driver`, `Complaints`, `BloodPressure/Systolic|Diastolic`,
  `Pulse`, `Temperature`, `Alcohol`, `HarmfulFactors`? (`absent|detected`; опускается, если признак не определялся, например при автоматическом осмотре «Водителя+»), `HarmfulFactorsNote`?, `Result`.
- `TechnicalInspection`: `Vehicle` (`Brand`, `Model`, `Type`?, `Plate`), `Driver`?, `Odometer`, `Result`.
- Диапазоны значений совпадают с валидацией API: АД 50–300 / 30–200, пульс 20–250, температура 30–45 (один
  знак), алкоголь 0–5 (два знака).

## Журнал (`journal.xsd`)

`ElectronicJournal @id @kind`: `Issuer`, `Organization`, `Period`, `CreatedAt`, `AuditLog` (`@path @sha256 @entries @chainHead` — хеш выгрузки аудита входит в подписанный документ), `Records @count` с
`Record @id @source @performedAt @result`, внутри ссылки `Xml`, `Pdf`?, `Signature`? (`@certSerial @signer`),
`Timestamp`? — каждая с `@path` и `@sha256`. Записи упорядочены по времени осмотра. Журнал без записей
недопустим.

## Манифест (`manifest.xsd`)

`Manifest @containerId @createdAt @generator` → `Files/File @path @role @size @sha256 @recordId? @signedFile?`.
`@signedFile` связывает подпись с подписанным файлом («какая подпись к какой записи»).
Роли: `journal-xml|pdf|signature|timestamp`, `record-xml|pdf|signature|timestamp`, `audit-log`, `certificates`,
`readme`.

## Открытые вопросы к схеме

1. **Единицы алкоголя** (`Alcohol`): mg/L или ‰. Меняется описание типа, а не структура; фиксируем до утверждения.
2. **Подпись записи из ЭПЛ** покрывает титул ЭПЛ, а не `record.xml`. Предложение: для таких записей в
   манифесте `record-signature` без `signedFile`. Нужно подтвердить, и нужна ли подпись титула в ZIP вообще.
3. **Нужна ли в `record.xml` информация из `epl_details`** (`critical_flag`, `brakes_ok`, `lighting_ok`,
   `tires_ok`, `released`, данные лицензии медика). Сейчас не включена.
4. **Реквизиты исполнителя** (`Issuer`) в `journal.xml`: достаточно ИНН и наименования или нужна лицензия.
