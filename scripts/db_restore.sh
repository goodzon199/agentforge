#!/usr/bin/env bash
#
# db_restore.sh — restore a backup into a throwaway database to verify it,
# or into the live database when RESTORE_TARGET=live is given explicitly.
#
# Verification mode (default, safe):
#   ./db_restore.sh backups/agentos_<ts>.dump
#   -> restores into agentos_restore_check, lists tables, then drops it.
#
# Live restore (destructive — only when asked explicitly):
#   RESTORE_TARGET=live ./db_restore.sh backups/agentos_<ts>.dump
#
# All work runs inside the DB container (binary-safe on Windows).
# Env: DB_CONTAINER (agentos-db), PG_USER (agentos), PG_DB (agentos)
set -euo pipefail
export MSYS_NO_PATHCONV=1

DUMP="${1:?usage: db_restore.sh <path-to-dump>}"
[ -f "${DUMP}" ] || { echo "[restore] no such file: ${DUMP}" >&2; exit 1; }

DB_CONTAINER="${DB_CONTAINER:-agentos-db}"
PG_USER="${PG_USER:-agentos}"
PG_DB="${PG_DB:-agentos}"
RESTORE_TARGET="${RESTORE_TARGET:-verify}"

WIN_DUMP="$(cygpath -w "$(readlink -f "${DUMP}")")"
SRC_IN_CONTAINER="/tmp/agentos_restore_src_$$.dump"

copy_in() {
  docker cp "${WIN_DUMP}" "${DB_CONTAINER}:${SRC_IN_CONTAINER}"
}
cleanup() {
  docker exec "${DB_CONTAINER}" rm -f "${SRC_IN_CONTAINER}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

if [ "${RESTORE_TARGET}" = "live" ]; then
  echo "[restore] WARNING: restoring into LIVE database ${PG_DB} ..."
  copy_in
  docker exec "${DB_CONTAINER}" pg_restore -U "${PG_USER}" -d "${PG_DB}" \
    --no-owner --no-privileges --clean --if-exists "${SRC_IN_CONTAINER}"
  echo "[restore] live restore finished"
  exit 0
fi

CHECK_DB="${PG_DB}_restore_check"
echo "[restore] verification target: ${CHECK_DB}"

docker exec "${DB_CONTAINER}" psql -U "${PG_USER}" -d "${PG_DB}" \
  -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS ${CHECK_DB}" >/dev/null
docker exec "${DB_CONTAINER}" psql -U "${PG_USER}" -d "${PG_DB}" \
  -v ON_ERROR_STOP=1 -c "CREATE DATABASE ${CHECK_DB}" >/dev/null

drop_check() {
  docker exec "${DB_CONTAINER}" psql -U "${PG_USER}" -d "${PG_DB}" \
    -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS ${CHECK_DB}" >/dev/null 2>&1 || true
}
trap 'drop_check; cleanup' EXIT

echo "[restore] restoring ${DUMP} into ${CHECK_DB} ..."
copy_in
docker exec "${DB_CONTAINER}" pg_restore -U "${PG_USER}" -d "${CHECK_DB}" \
  --no-owner --no-privileges "${SRC_IN_CONTAINER}"

echo "[restore] verifying: tables in ${CHECK_DB} ..."
docker exec "${DB_CONTAINER}" psql -U "${PG_USER}" -d "${CHECK_DB}" -c \
  "SELECT count(*) AS tables FROM information_schema.tables WHERE table_schema='public';"
docker exec "${DB_CONTAINER}" psql -U "${PG_USER}" -d "${CHECK_DB}" -c \
  "SELECT count(*) AS users FROM users;" && \
  echo "[restore] OK: archive restores cleanly"

echo "[restore] verification complete (${CHECK_DB} dropped)"
