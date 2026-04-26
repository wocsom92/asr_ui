#!/usr/bin/env bash
set -euo pipefail

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required." >&2
  exit 1
fi

docker compose up -d --build
echo "ASR UI is starting."
echo "Frontend: http://localhost:${FRONTEND_PORT:-8824}"
echo "Backend:  http://localhost:${BACKEND_PORT:-8825}"
