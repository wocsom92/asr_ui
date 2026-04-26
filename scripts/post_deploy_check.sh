#!/usr/bin/env bash
set -euo pipefail

ENV_FILE=".env"
DOCKER_CMD="docker"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file) ENV_FILE="${2:-}"; shift 2 ;;
    --docker-cmd) DOCKER_CMD="${2:-}"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

if [[ -f "${ENV_FILE}" ]]; then
  # shellcheck source=/dev/null
  source "${ENV_FILE}"
fi

FRONTEND_PORT="${FRONTEND_PORT:-8824}"
BACKEND_PORT="${BACKEND_PORT:-8825}"

echo "--- docker compose ps"
${DOCKER_CMD} compose ps

echo "--- backend health"
curl -fsS "http://127.0.0.1:${BACKEND_PORT}/api/v1/system/health"
echo

echo "--- frontend root"
curl -fsS "http://127.0.0.1:${FRONTEND_PORT}/" >/dev/null
echo "frontend ok"

echo "--- frontend proxied health"
curl -fsS "http://127.0.0.1:${FRONTEND_PORT}/api/v1/system/health"
echo

echo "--- volumes"
${DOCKER_CMD} compose exec -T backend sh -lc 'test -d /data/uploads && test -d /data/transcripts && test -d /models && echo "volume directories ok"'
