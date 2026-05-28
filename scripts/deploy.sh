#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────
# ASR UI — deploy to Raspberry Pi 5 (or any Linux host)
# ──────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG_FILE_DEFAULT="${SCRIPT_DIR}/deploy.targets.env"

usage() {
  cat <<'EOF'
Usage:
  scripts/deploy.sh --target <name> [options]

Target modes:
  remote                   Upload repo to a remote Docker host and run the full stack.
  local-worker             Rebuild/restart only the local worker profile.

Options:
  --target <name>            Target name from config file (required).
  --config <path>            Path to targets config (default: scripts/deploy.targets.env).
  --source <path>            Source repo root to deploy (default: current repo root).
  --auth <mode>              Auth mode: key | password (default: target value or key).
  --password <value>         SSH password (optional; prompts when auth=password and not provided).
  --key-path <path>          SSH private key path (optional; can come from config).
  --purge-mode <mode>        Cleanup mode: managed | full (default: target value or managed).
  --verbose                  Show extra SSH/SFTP diagnostics.
  --yes                      Non-interactive mode; skip confirmation prompt.
  -h, --help                 Show this help.
EOF
}

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

die() {
  echo "Error: $*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

CONFIG_FILE="${CONFIG_FILE_DEFAULT}"
TARGET=""
SOURCE_ROOT="${REPO_ROOT}"
AUTH_MODE=""
PASSWORD=""
KEY_PATH=""
ASSUME_YES=0
VERBOSE=0
PURGE_MODE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target) TARGET="${2:-}"; shift 2 ;;
    --config) CONFIG_FILE="${2:-}"; shift 2 ;;
    --source) SOURCE_ROOT="${2:-}"; shift 2 ;;
    --auth) AUTH_MODE="${2:-}"; shift 2 ;;
    --password) PASSWORD="${2:-}"; shift 2 ;;
    --key-path) KEY_PATH="${2:-}"; shift 2 ;;
    --purge-mode) PURGE_MODE="${2:-}"; shift 2 ;;
    --yes) ASSUME_YES=1; shift ;;
    --verbose) VERBOSE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown argument: $1" ;;
  esac
done

[[ -n "${TARGET}" ]] || die "--target is required"
[[ -f "${CONFIG_FILE}" ]] || die "Config file not found: ${CONFIG_FILE}"
[[ -d "${SOURCE_ROOT}" ]] || die "Source root not found: ${SOURCE_ROOT}"

# shellcheck source=/dev/null
source "${CONFIG_FILE}"

target_key="TARGET_${TARGET}_"
get_target_var() {
  local var_name="${target_key}$1"
  printf '%s' "${!var_name:-}"
}

HOST="$(get_target_var HOST)"
PORT="$(get_target_var PORT)"
USER_NAME="$(get_target_var USER)"
DEPLOY_PATH="$(get_target_var DEPLOY_PATH)"
TARGET_AUTH="$(get_target_var AUTH)"
TARGET_KEY_PATH="$(get_target_var KEY_PATH)"
TARGET_PASSWORD="$(get_target_var PASSWORD)"
TARGET_ENV_FILE="$(get_target_var ENV_FILE)"
TARGET_REMOTE_ENV_NAME="$(get_target_var REMOTE_ENV_NAME)"
TARGET_DOCKER_USE_SUDO="$(get_target_var DOCKER_USE_SUDO)"
TARGET_PURGE_MODE="$(get_target_var PURGE_MODE)"
TARGET_WORKER_NAME="$(get_target_var WORKER_NAME)"
TARGET_MODE="$(get_target_var MODE)"
TARGET_SERVER_URL="$(get_target_var SERVER_URL)"
TARGET_GIGAAM_TORCH_THREADS="$(get_target_var GIGAAM_TORCH_THREADS)"
TARGET_GIGAAM_TORCH_INTEROP_THREADS="$(get_target_var GIGAAM_TORCH_INTEROP_THREADS)"

TARGET_MODE="${TARGET_MODE:-remote}"
case "${TARGET_MODE}" in remote|local-worker) ;; *) die "Invalid TARGET_${TARGET}_MODE '${TARGET_MODE}'" ;; esac

PORT="${PORT:-22}"
AUTH_MODE="${AUTH_MODE:-${TARGET_AUTH:-key}}"
KEY_PATH="${KEY_PATH:-${TARGET_KEY_PATH:-}}"
PASSWORD="${PASSWORD:-${TARGET_PASSWORD:-}}"
TARGET_REMOTE_ENV_NAME="${TARGET_REMOTE_ENV_NAME:-.env}"
TARGET_DOCKER_USE_SUDO="${TARGET_DOCKER_USE_SUDO:-true}"
TARGET_PURGE_MODE="${PURGE_MODE:-${TARGET_PURGE_MODE:-managed}}"

case "${AUTH_MODE}" in key|password) ;; *) die "Invalid --auth '${AUTH_MODE}'" ;; esac
case "${TARGET_DOCKER_USE_SUDO}" in true|false) ;; *) die "Invalid DOCKER_USE_SUDO value '${TARGET_DOCKER_USE_SUDO}'" ;; esac
case "${TARGET_PURGE_MODE}" in managed|full) ;; *) die "Invalid purge mode '${TARGET_PURGE_MODE}'" ;; esac

if [[ "${TARGET_MODE}" == "local-worker" ]]; then
  require_cmd docker
  [[ -f "${SOURCE_ROOT}/docker-compose.yml" ]] || die "docker-compose.yml not found in ${SOURCE_ROOT}"

  if [[ -n "${TARGET_ENV_FILE}" ]]; then
    if [[ "${TARGET_ENV_FILE}" = /* ]]; then
      LOCAL_ENV_FILE="${TARGET_ENV_FILE}"
    else
      LOCAL_ENV_FILE="${SOURCE_ROOT}/${TARGET_ENV_FILE}"
    fi
    [[ -f "${LOCAL_ENV_FILE}" ]] || die "Configured env file not found: ${LOCAL_ENV_FILE}"
  fi

  if [[ "${ASSUME_YES}" -ne 1 ]]; then
    echo ""
    echo "  ASR UI Local Worker Deploy"
    echo "  ─────────────────────────────────────"
    echo "  Target:       ${TARGET}"
    echo "  Source root:  ${SOURCE_ROOT}"
    if [[ -n "${TARGET_WORKER_NAME}" ]]; then echo "  Worker name:  ${TARGET_WORKER_NAME}"; fi
    if [[ -n "${TARGET_SERVER_URL}" ]]; then echo "  Server URL:   ${TARGET_SERVER_URL}"; fi
    if [[ -n "${TARGET_ENV_FILE}" ]]; then echo "  Env file:     ${LOCAL_ENV_FILE}"; fi
    echo ""
    read -r -p "  Continue? [y/N] " confirm
    [[ "${confirm}" =~ ^[Yy]$ ]] || die "Aborted by user."
    echo ""
  fi

  log "Rebuilding and restarting local worker..."
  (
    cd "${SOURCE_ROOT}"
    if [[ -n "${TARGET_WORKER_NAME}" ]]; then export ASR_WORKER_NAME="${TARGET_WORKER_NAME}"; fi
    if [[ -n "${TARGET_SERVER_URL}" ]]; then export ASR_SERVER_URL="${TARGET_SERVER_URL}"; fi
    if [[ -n "${TARGET_GIGAAM_TORCH_THREADS}" ]]; then export GIGAAM_TORCH_THREADS="${TARGET_GIGAAM_TORCH_THREADS}"; fi
    if [[ -n "${TARGET_GIGAAM_TORCH_INTEROP_THREADS}" ]]; then export GIGAAM_TORCH_INTEROP_THREADS="${TARGET_GIGAAM_TORCH_INTEROP_THREADS}"; fi
    docker compose --profile worker up -d --build worker
  )
  log "Worker status:"
  (cd "${SOURCE_ROOT}" && docker compose ps worker)
  log "──────────────────────────────────────────"
  log "Local worker deploy to ${TARGET} completed successfully."
  log "Logs: cd \"${SOURCE_ROOT}\" && docker compose logs -f worker"
  log "──────────────────────────────────────────"
  exit 0
fi

[[ -n "${HOST}" ]] || die "Missing TARGET_${TARGET}_HOST in ${CONFIG_FILE}"
[[ -n "${USER_NAME}" ]] || die "Missing TARGET_${TARGET}_USER in ${CONFIG_FILE}"
[[ -n "${DEPLOY_PATH}" ]] || die "Missing TARGET_${TARGET}_DEPLOY_PATH in ${CONFIG_FILE}"
[[ "${DEPLOY_PATH}" = /* ]] || die "DEPLOY_PATH must be absolute: ${DEPLOY_PATH}"

case "${DEPLOY_PATH}" in
  "/"|"/home"|"/root"|"/var"|"/usr"|"/opt"|"/tmp"|"/etc")
    die "Refusing dangerous DEPLOY_PATH: ${DEPLOY_PATH}" ;;
esac

if [[ "${AUTH_MODE}" == "key" ]]; then
  [[ -n "${KEY_PATH}" ]] || KEY_PATH="${HOME}/.ssh/id_rsa"
  [[ -f "${KEY_PATH}" ]] || die "SSH key not found: ${KEY_PATH}"
fi
if [[ "${AUTH_MODE}" == "password" && -z "${PASSWORD}" ]]; then
  read -r -s -p "SSH password for ${USER_NAME}@${HOST}: " PASSWORD
  echo
fi

LOCAL_ENV_FILE=""
if [[ -n "${TARGET_ENV_FILE}" ]]; then
  if [[ "${TARGET_ENV_FILE}" = /* ]]; then
    LOCAL_ENV_FILE="${TARGET_ENV_FILE}"
  else
    LOCAL_ENV_FILE="${SOURCE_ROOT}/${TARGET_ENV_FILE}"
  fi
  [[ -f "${LOCAL_ENV_FILE}" ]] || die "Configured env file not found: ${LOCAL_ENV_FILE}"
fi

require_cmd ssh
require_cmd sftp
require_cmd rsync
if [[ "${AUTH_MODE}" == "password" ]]; then require_cmd sshpass; fi

SSH_BASE_OPTS=(-p "${PORT}" -o BatchMode=no -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 -o ServerAliveInterval=10 -o ServerAliveCountMax=3)
if [[ "${AUTH_MODE}" == "key" ]]; then SSH_BASE_OPTS+=(-i "${KEY_PATH}"); fi
if [[ "${VERBOSE}" -eq 1 ]]; then SSH_BASE_OPTS+=(-v); fi

run_ssh() {
  local remote_cmd="$1"
  log "SSH >>> ${remote_cmd}"
  if [[ "${AUTH_MODE}" == "password" ]]; then
    SSHPASS="${PASSWORD}" sshpass -e ssh "${SSH_BASE_OPTS[@]}" "${USER_NAME}@${HOST}" "${remote_cmd}"
  else
    ssh "${SSH_BASE_OPTS[@]}" "${USER_NAME}@${HOST}" "${remote_cmd}"
  fi
}

run_sftp_batch() {
  local batch_file="$1"
  log "SFTP upload ($(wc -l < "${batch_file}") commands)"
  local sftp_opts=(-P "${PORT}" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 -o BatchMode=no)
  if [[ "${AUTH_MODE}" == "password" ]]; then
    sftp_opts+=(-o PreferredAuthentications=password -o PubkeyAuthentication=no)
  fi
  if [[ "${VERBOSE}" -eq 1 ]]; then sftp_opts+=(-v); fi
  if [[ "${AUTH_MODE}" == "password" ]]; then
    SSHPASS="${PASSWORD}" sshpass -e sftp "${sftp_opts[@]}" -b "${batch_file}" "${USER_NAME}@${HOST}"
  else
    sftp "${sftp_opts[@]}" -i "${KEY_PATH}" -b "${batch_file}" "${USER_NAME}@${HOST}"
  fi
}

DEPLOY_ITEMS=(backend frontend scripts/post_deploy_check.sh docker-compose.yml .dockerignore README.md)
for item in "${DEPLOY_ITEMS[@]}"; do
  [[ -e "${SOURCE_ROOT}/${item}" ]] || die "Required source item missing: ${SOURCE_ROOT}/${item}"
done

if [[ "${ASSUME_YES}" -ne 1 ]]; then
  echo ""
  echo "  ASR UI Deploy"
  echo "  ─────────────────────────────────────"
  echo "  Target:       ${TARGET} (${USER_NAME}@${HOST}:${PORT})"
  echo "  Deploy path:  ${DEPLOY_PATH}"
  echo "  Purge mode:   ${TARGET_PURGE_MODE}"
  echo "  Auth:         ${AUTH_MODE}"
  echo "  Docker sudo:  ${TARGET_DOCKER_USE_SUDO}"
  if [[ -n "${LOCAL_ENV_FILE}" ]]; then echo "  Env file:     ${LOCAL_ENV_FILE} -> ${TARGET_REMOTE_ENV_NAME}"; fi
  echo ""
  read -r -p "  Continue? [y/N] " confirm
  [[ "${confirm}" =~ ^[Yy]$ ]] || die "Aborted by user."
  echo ""
fi

stage_dir="$(mktemp -d)"
batch_file="$(mktemp)"
cleanup() { rm -rf "${stage_dir}" "${batch_file}"; }
trap cleanup EXIT

copy_into_stage() {
  local rel_path="$1"
  local src="${SOURCE_ROOT}/${rel_path}"
  local dst="${stage_dir}/${rel_path}"
  if [[ -d "${src}" ]]; then
    mkdir -p "${dst}"
    rsync -a --exclude ".git/" --exclude "__pycache__/" --exclude ".pytest_cache/" --exclude ".venv/" --exclude "node_modules/" --exclude "dist/" --exclude ".tsbuildinfo" "${src}/" "${dst}/"
  else
    mkdir -p "$(dirname "${dst}")"
    cp "${src}" "${dst}"
  fi
}

set_env_value() {
  local env_file="$1"
  local key="$2"
  local value="$3"
  local tmp_file="${env_file}.tmp"
  if [[ -f "${env_file}" ]] && grep -q "^${key}=" "${env_file}"; then
    awk -v key="${key}" -v value="${value}" 'BEGIN { done = 0 } $0 ~ "^" key "=" { print key "=" value; done = 1; next } { print } END { if (!done) print key "=" value }' "${env_file}" > "${tmp_file}"
    mv "${tmp_file}" "${env_file}"
  else
    printf '%s=%s\n' "${key}" "${value}" >> "${env_file}"
  fi
}

log "Preparing staging directory..."
for item in "${DEPLOY_ITEMS[@]}"; do
  log "  staging: ${item}"
  copy_into_stage "${item}"
done
if [[ -n "${LOCAL_ENV_FILE}" ]]; then
  cp "${LOCAL_ENV_FILE}" "${stage_dir}/${TARGET_REMOTE_ENV_NAME}"
  if [[ -n "${TARGET_WORKER_NAME}" ]]; then
    set_env_value "${stage_dir}/${TARGET_REMOTE_ENV_NAME}" "ASR_WORKER_NAME" "${TARGET_WORKER_NAME}"
  fi
  if [[ -n "${TARGET_GIGAAM_TORCH_THREADS}" ]]; then
    set_env_value "${stage_dir}/${TARGET_REMOTE_ENV_NAME}" "GIGAAM_TORCH_THREADS" "${TARGET_GIGAAM_TORCH_THREADS}"
  fi
  if [[ -n "${TARGET_GIGAAM_TORCH_INTEROP_THREADS}" ]]; then
    set_env_value "${stage_dir}/${TARGET_REMOTE_ENV_NAME}" "GIGAAM_TORCH_INTEROP_THREADS" "${TARGET_GIGAAM_TORCH_INTEROP_THREADS}"
  fi
fi

log "Checking SSH connectivity..."
run_ssh "echo 'connected to:' \$(hostname) '(arch:' \$(uname -m) ')'"

docker_prefix="docker"
if [[ "${TARGET_DOCKER_USE_SUDO}" == "true" ]]; then docker_prefix="sudo docker"; fi

log "Verifying Docker access..."
if ! docker_check_output="$(run_ssh "${docker_prefix} info --format '{{.Architecture}}' 2>&1" 2>&1)"; then
  die "Remote Docker access failed. Details: ${docker_check_output}"
fi
log "  remote Docker arch: ${docker_check_output}"

if [[ "${TARGET_PURGE_MODE}" == "full" ]]; then
  log "Cleaning remote (full purge): ${DEPLOY_PATH}"
  run_ssh "rm -rf \"${DEPLOY_PATH}\" && mkdir -p \"${DEPLOY_PATH}\""
else
  log "Cleaning remote managed items..."
  cleanup_items=("${DEPLOY_ITEMS[@]}")
  if [[ -n "${LOCAL_ENV_FILE}" ]]; then cleanup_items+=("${TARGET_REMOTE_ENV_NAME}"); fi
  cleanup_cmd="mkdir -p \"${DEPLOY_PATH}\" && cd \"${DEPLOY_PATH}\""
  for item in "${cleanup_items[@]}"; do cleanup_cmd="${cleanup_cmd} && rm -rf \"${item}\""; done
  run_ssh "${cleanup_cmd}"
fi

run_ssh "cd \"${DEPLOY_PATH}\" && mkdir -p scripts"

log "Uploading files..."
{
  for item in "${DEPLOY_ITEMS[@]}"; do
    local_item="${stage_dir}/${item}"
    if [[ -d "${local_item}" ]]; then
      echo "put -r ${local_item} ${DEPLOY_PATH}"
    else
      echo "put ${local_item} ${DEPLOY_PATH}/${item}"
    fi
  done
  if [[ -n "${LOCAL_ENV_FILE}" ]]; then
    echo "put ${stage_dir}/${TARGET_REMOTE_ENV_NAME} ${DEPLOY_PATH}/${TARGET_REMOTE_ENV_NAME}"
  fi
} > "${batch_file}"
run_sftp_batch "${batch_file}"

log "Stopping existing containers..."
run_ssh "cd \"${DEPLOY_PATH}\" && ${docker_prefix} compose down --remove-orphans 2>/dev/null || true"

log "Building and starting services..."
run_ssh "cd \"${DEPLOY_PATH}\" && ${docker_prefix} compose up -d --build"

log "Waiting for services..."
sleep 8

log "Running post-deploy checks..."
run_ssh "cd \"${DEPLOY_PATH}\" && chmod +x scripts/post_deploy_check.sh && ./scripts/post_deploy_check.sh --env-file \"${TARGET_REMOTE_ENV_NAME}\" --docker-cmd \"${docker_prefix}\""

log "Pruning unused Docker resources..."
run_ssh "${docker_prefix} system prune -f" || true

log "──────────────────────────────────────────"
log "Deploy to ${TARGET} completed successfully."
log "Frontend: http://${HOST}:8824"
log "Backend:  http://${HOST}:8825"
log "──────────────────────────────────────────"
