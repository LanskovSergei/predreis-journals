#!/usr/bin/env bash
# Резервная копия электронных журналов: БД (pg_dump) + файлы хранилища.
#
# БД и файлы копируются согласованно: сначала дамп, затем файлы (файлы подписанных документов
# неизменяемы, поэтому копия файлов, сделанная после дампа, всегда содержит всё, что в нём упомянуто).
#
# Переменные окружения:
#   BACKUP_DIR            куда класть копии (обязательно)
#   DATABASE_URL          строка подключения libpq: postgresql://пользователь:пароль@хост:5432/база
#                         (или JOURNALS_DATABASE_URL с postgresql+asyncpg:// — суффикс уберём)
#   STORAGE_DIR           каталог хранилища файлов (обязательно)
#   KEEP_DAYS             сколько дней хранить дампы БД (по умолчанию 14)
# Пример cron (раз в сутки в 03:15): 15 3 * * * /opt/journals/deploy/backup.sh >> /var/log/journals-backup.log 2>&1
set -euo pipefail

: "${BACKUP_DIR:?задайте BACKUP_DIR}"
: "${STORAGE_DIR:?задайте STORAGE_DIR}"
DATABASE_URL="${DATABASE_URL:-${JOURNALS_DATABASE_URL:-}}"
: "${DATABASE_URL:?задайте DATABASE_URL}"
DATABASE_URL="${DATABASE_URL/+asyncpg/}"
KEEP_DAYS="${KEEP_DAYS:-14}"

stamp="$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR/db" "$BACKUP_DIR/files"
dump="$BACKUP_DIR/db/journals-$stamp.dump"

echo "[$(date -Is)] дамп БД -> $dump"
pg_dump --format=custom --no-owner --file="$dump.part" "$DATABASE_URL"
# дамп должен читаться: pg_restore --list разбирает оглавление и падает на повреждённом файле
pg_restore --list "$dump.part" >/dev/null
mv "$dump.part" "$dump"

echo "[$(date -Is)] файлы хранилища -> $BACKUP_DIR/files"
if command -v rsync >/dev/null 2>&1; then
    rsync -a "$STORAGE_DIR"/ "$BACKUP_DIR/files"/
else
    cp -a -u "$STORAGE_DIR"/. "$BACKUP_DIR/files"/
fi

echo "[$(date -Is)] удаляю дампы старше $KEEP_DAYS дн."
find "$BACKUP_DIR/db" -name 'journals-*.dump' -mtime "+$KEEP_DAYS" -delete

size="$(du -sh "$dump" | cut -f1)"
echo "[$(date -Is)] готово: дамп $size, файлов $(find "$BACKUP_DIR/files" -type f | wc -l)"
