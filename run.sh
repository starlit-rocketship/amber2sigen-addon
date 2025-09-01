#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -f ./amber2sigen.env ]]; then
  echo "[run.sh] Missing ./amber2sigen.env"; exit 1
fi
source ./amber2sigen.env

: "${AMBER_TOKEN:?}"
: "${STATION_ID:?}"
: "${SIGEN_USER:?}"
: "${SIGEN_DEVICE_ID:?}"
: "${SIGEN_PASS_ENC:?}"

PY=python3
ARGS=(
  "--station-id" "${STATION_ID}"
  "--amber-token" "${AMBER_TOKEN}"
  "--interval" "${INTERVAL:-30}"
  "--tz" "${TZ_OVERRIDE:-Australia/Adelaide}"
  "--align" "${ALIGN:-end}"
  "--plan-name" "${PLAN_NAME:-Amber Live}"
  "--advanced-price" "${ADVANCED:-predicted}"
  "--sigen-user" "${SIGEN_USER}"
  "--sigen-pass-enc" "${SIGEN_PASS_ENC}"
  "--device-id" "${SIGEN_DEVICE_ID}"
)

[[ "${USE_CURRENT:-1}" == "1" ]] && ARGS+=("--use-current")
[[ "${1:-}" == "--dry-run" ]] && ARGS+=("--dry-run")

echo "[run.sh] Exec: ${PY} amber_to_sigen.py ${ARGS[*]}"
exec "${PY}" amber_to_sigen.py "${ARGS[@]}"