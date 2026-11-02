#!/usr/bin/env bash
# Резервная копия журналов на сервере платформы: база в контейнере journals_db (снаружи недоступна),
# файлы — в каталоге хоста. Порядок тот же, что в deploy/backup.sh: сначала дамп, потом файлы
# (файлы подписанных документов неизменяемы, поэтому копия файлов после дампа содержит всё, что в нём есть).
#
# Переменные окружения:
#   BACKUP_DIR      куда класть копии (обязательно; лучше на отдельный диск, копию — ещё и вне сервера)
#   STORAGE_DIR     каталог файлов на хосте (по умолчанию /opt/journals/storage)
#   KEEP_DAYS       сколько дней хранить дампы (по умолчанию 14)
# Пример cron (раз в сутки в 03:30): 30 3 * * * /opt/journals/deploy/platform/backup.sh >> /var/log/journals-backup.log 2>&1
set -euo pipefail

: "${BACKUP_DIR:?задайте BACKUP_DIR}"
STORAGE_DIR="${STORAGE_DIR:-/opt/journals/storage}"
KEEP_DAYS="${KEEP_DAYS:-14}"
DB_CONTAINER="${DB_CONTAINER:-journals_db}"

stamp="$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR/db" "$BACKUP_DIR/files"
dump="$BACKUP_DIR/db/journals-$stamp.dump"

echo "[$(date -Is)] дамп БД из $DB_CONTAINER -> $dump"
docker exec "$DB_CONTAINER" pg_dump --format=custom --no-owner -U journals journals > "$dump.part"
# дамп должен читаться: pg_restore --list разбирает оглавление и падает на повреждённом файле
docker exec -i "$DB_CONTAINER" pg_restore --list < "$dump.part" >/dev/null
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
