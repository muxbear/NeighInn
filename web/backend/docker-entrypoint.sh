#!/bin/sh
# 生产容器入口：先执行 Alembic 迁移，再启动应用。
# APP_ENV != dev 时应用不会自动建表，因此新库必须依赖这里的迁移。
set -eu

if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
    attempt=1
    max_attempts="${DB_MIGRATION_ATTEMPTS:-30}"
    until alembic upgrade head; do
        if [ "$attempt" -ge "$max_attempts" ]; then
            echo "alembic upgrade head failed after ${attempt} attempts" >&2
            exit 1
        fi
        echo "database not ready, retrying alembic (${attempt}/${max_attempts})..." >&2
        attempt=$((attempt + 1))
        sleep 2
    done
fi

exec "$@"
