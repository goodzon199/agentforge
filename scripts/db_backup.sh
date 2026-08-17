#!/usr/bin/env bash
#
# db_backup.sh — create a logical backup of the pilot Postgres database.
#
# Usage:   ./db_backup.sh [keep N]
# Env:     DB_CONTAINER (default agentos-db), PG_USER (agentos), PG_DB (agentos)
# Output:  backups/agentos_<timestamp>.dump  (PostgreSQL custom format)
#
# The dump and its integrity check run INSIDE the container (binary-safe);
# the archive is then copied out with `docker cp` and pruned to the newest N.
set -euo pipefail
export MSYS_NO_PATHCONV=1

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="${HERE}/backups"
mkdir -p "${OUT_DIR}"
WIN_OUT="$(cygpath -w "${OUT_DIR}")"

DB_CONTAINER="${DB_CONTAINER:-agentos-db}"
PG_USER="${PG_USER:-agentos}"
PG_DB="${PG_DB:-agentos}"
KEEP="${1:-14}"

STAMP="$(date +%Y%m%d_%H%M%S)"
DUMP_NAME="agentos_${STAMP}.dump"
TMP_IN_CONTAINER="/tmp/${DUMP_NAME}"

echo "[backup] dumping ${PG_DB}@${DB_CONTAINER} ..."
docker exec "${DB_CONTAINER}" pg_dump -U "${PG_USER}" -d "${PG_DB}" \
    --format=custom --no-owner --no-privileges \
    --file="${TMP_IN_CONTAINER}"

echo "[backup] verifying archive integrity ..."
if ! docker exec "${DB_CONTAINER}" pg_restore --list "${TMP_IN_CONTAINER}" >/dev/null 2>&1; then
  echo "[backup] ERROR: archive verification failed" >&2
  docker exec "${DB_CONTAINER}" rm -f "${TMP_IN_CONTAINER}" || true
  exit 1
fi

echo "[backup] copying archive out of the container ..."
docker cp "${DB_CONTAINER}:${TMP_IN_CONTAINER}" "${WIN_OUT}\\${DUMP_NAME}"
docker exec "${DB_CONTAINER}" rm -f "${TMP_IN_CONTAINER}"

# Keep only the newest KEEP archives.
ls -1t "${OUT_DIR}"/agentos_*.dump 2>/dev/null | tail -n +"$((KEEP + 1))" | while read -r old; do
  rm -f "${old}"
done

echo "[backup] OK: ${OUT_DIR}/${DUMP_NAME}"
echo "[backup] kept newest ${KEEP} archives in ${OUT_DIR}"