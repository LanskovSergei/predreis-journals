"""Заполняет БД реалистичным объёмом для нагрузочных замеров (только для тестовой базы!).

Запуск: JOURNALS_DATABASE_URL=... python scripts/load_seed.py [медосмотров] [техконтролей]
По умолчанию 500 000 и 300 000 записей (около трёх лет при ~1000 записей в сутки), 20 организаций,
200 водителей и 200 ТС. ~97% записей подписаны или в журнале, ~2% ждут подписи.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings

SURNAMES = "'Иванов','Петров','Сидоров','Кузнецов','Смирнов','Попов','Васильев','Соколов','Михайлов','Новиков','Фёдоров','Морозов','Волков','Алексеев','Лебедев','Семёнов','Егоров','Павлов','Козлов','Степанов'"
NAMES = "'Александр','Сергей','Андрей','Дмитрий','Алексей','Михаил','Иван','Николай','Евгений','Владимир'"
PATRONYMICS = "'Александрович','Сергеевич','Андреевич','Дмитриевич','Алексеевич'"

PREP = [
    "TRUNCATE medical_records, technical_records, record_documents, drivers, vehicles, users, organizations CASCADE",
    """INSERT INTO organizations (id, inn, name, short_name, legal_address, work_format, is_active)
       SELECT gen_random_uuid(), (7700000000 + n)::text, 'ООО «Организация ' || n || '»', 'Орг ' || n,
              'г. Москва, ул. Тестовая, ' || n, 'epl', true FROM generate_series(1, 20) n""",
    """INSERT INTO users (id, role, full_name, journals_access, is_active)
       SELECT gen_random_uuid(), r.role, r.role || ' ' || n, true, true
       FROM (VALUES ('medic', 6), ('mechanic', 4), ('predreis', 3)) r(role, cnt), generate_series(1, 6) n
       WHERE n <= r.cnt""",
    f"""INSERT INTO drivers (id, organization_id, full_name, gender, birth_date, is_active)
       SELECT gen_random_uuid(), o.id,
              (ARRAY[{SURNAMES}])[1 + (n % 20)] || ' ' || (ARRAY[{NAMES}])[1 + (n % 10)] || ' ' ||
              (ARRAY[{PATRONYMICS}])[1 + (n % 5)] || ' ' || n,
              CASE WHEN n % 3 = 0 THEN NULL ELSE 'M' END, date '1960-01-01' + (n * 37 % 9000), true
       FROM (SELECT id, row_number() OVER (ORDER BY id) rn FROM organizations) o, generate_series(1, 10) n""",
    """INSERT INTO vehicles (id, organization_id, brand, model, vehicle_type, plate, is_active)
       SELECT gen_random_uuid(), o.id, 'КАМАЗ', '65115', 'грузовой',
              'А' || lpad((o.rn * 10 + n)::text, 3, '0') || 'ВС77', true
       FROM (SELECT id, row_number() OVER (ORDER BY id) rn FROM organizations) o, generate_series(1, 10) n""",
]

MEDICAL = """
INSERT INTO medical_records (id, status, source, performed_at, snapshot, deletion_pending, organization_id,
    specialist_user_id, phase, driver_id, complaints, bp_systolic, bp_diastolic, pulse, temperature,
    alcohol_mgl, harmful_factors, result)
SELECT gen_random_uuid(),
       CASE WHEN g % 100 < 2 THEN 'unsigned' WHEN g % 100 < 10 THEN 'signed' ELSE 'in_journal' END,
       'manual', now() - (g * interval '3 minutes'),
       jsonb_build_object('organization', jsonb_build_object('inn', o.inn, 'name', o.name),
                          'driver', jsonb_build_object('full_name', d.full_name,
                                    'birth_date', d.birth_date::text, 'gender', d.gender),
                          'specialist', jsonb_build_object('full_name', m.full_name)),
       false, d.organization_id, m.id, CASE WHEN g % 2 = 0 THEN 'pre' ELSE 'post' END, d.id,
       'отсутствуют', 110 + g % 30, 70 + g % 20, 60 + g % 30, 36.6, 0, 'absent', 'admitted'
FROM generate_series(1, :n) g
JOIN (SELECT row_number() OVER (ORDER BY id) rn, * FROM drivers) d ON d.rn = 1 + g % (SELECT count(*) FROM drivers)
JOIN organizations o ON o.id = d.organization_id
JOIN (SELECT row_number() OVER (ORDER BY id) rn, * FROM users WHERE role = 'medic') m
  ON m.rn = 1 + g % (SELECT count(*) FROM users WHERE role = 'medic')
"""

TECHNICAL = """
INSERT INTO technical_records (id, status, source, performed_at, snapshot, deletion_pending, organization_id,
    specialist_user_id, vehicle_id, driver_id, odometer, result)
SELECT gen_random_uuid(),
       CASE WHEN g % 100 < 2 THEN 'unsigned' WHEN g % 100 < 10 THEN 'signed' ELSE 'in_journal' END,
       'manual', now() - (g * interval '5 minutes'),
       jsonb_build_object('organization', jsonb_build_object('inn', o.inn, 'name', o.name),
                          'vehicle', jsonb_build_object('brand', v.brand, 'model', v.model, 'plate', v.plate),
                          'specialist', jsonb_build_object('full_name', m.full_name)),
       false, v.organization_id, m.id, v.id, NULL, 10000 + g, 'admitted'
FROM generate_series(1, :n) g
JOIN (SELECT row_number() OVER (ORDER BY id) rn, * FROM vehicles) v ON v.rn = 1 + g % (SELECT count(*) FROM vehicles)
JOIN organizations o ON o.id = v.organization_id
JOIN (SELECT row_number() OVER (ORDER BY id) rn, * FROM users WHERE role = 'mechanic') m
  ON m.rn = 1 + g % (SELECT count(*) FROM users WHERE role = 'mechanic')
"""

DOCS = """
INSERT INTO record_documents (id, record_kind, record_id, cert_serial, cert_subject, signed_at, xml_key, sig_key)
SELECT gen_random_uuid(), :kind, id, 'f18dd73747eccc4ab0d2b1ee00d4040e', 'Абдуллаева Гульзана Абутдиновна',
       performed_at, 'x/' || id::text, 'x/' || id::text || '.sig'
FROM {table} WHERE status <> 'unsigned'
"""


async def main() -> None:
    """Заполняет базу и печатает размеры таблиц."""
    n_med = int(sys.argv[1]) if len(sys.argv) > 1 else 500_000
    n_tech = int(sys.argv[2]) if len(sys.argv) > 2 else 300_000
    engine = create_async_engine(get_settings().database_url)
    t0 = time.perf_counter()
    async with engine.begin() as conn:
        for sql in PREP:
            await conn.execute(text(sql))
        await conn.execute(text(MEDICAL), {"n": n_med})
        await conn.execute(text(TECHNICAL), {"n": n_tech})
        await conn.execute(text(DOCS.format(table="medical_records")), {"kind": "medical"})
        await conn.execute(text(DOCS.format(table="technical_records")), {"kind": "technical"})
        await conn.execute(text("ANALYZE"))
    print(f"Готово за {time.perf_counter() - t0:.0f} с")
    async with engine.connect() as conn:
        for table in (
            "medical_records",
            "technical_records",
            "record_documents",
            "drivers",
            "vehicles",
        ):
            row = (
                await conn.execute(
                    text(
                        f"SELECT count(*), pg_size_pretty(pg_total_relation_size('{table}')) FROM {table}"
                    )
                )
            ).one()
            print(f"  {table:20} {row[0]:>9} строк, {row[1]}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
