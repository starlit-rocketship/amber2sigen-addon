#!/usr/bin/with-contenv bashio
# shellcheck shell=bash
set -euo pipefail

# -----------------------------
# Helper: redaction & logging
# -----------------------------
redact() {
  local s="${1:-}"
  if [[ -z "$s" ]]; then echo "<empty>"; return; fi
  # keep first 4 and last 3 chars if long
  if (( ${#s} > 10 )); then
    echo "${s:0:4}…${s: -3}"
  else
    echo "****"
  fi
}

log_banner() {
  bashio::log.info "Starting Amber2Sigen Add-on"
  bashio::log.info "interval=${INTERVAL}m mode=${ADVANCED_PRICE:-<default>} align=${ALIGN:-<none>} plan=\"${PLAN_NAME:-<none>}\" auth=${AUTH_MODE} mqtt=${MQTT_ENABLED}"
}

# -----------------------------
# Read config
# -----------------------------
AMBER_TOKEN="$(bashio::config 'amber_token' || true)"
SIGEN_USER="$(bashio::config 'sigen_user' || true)"
SIGEN_PASS_ENC="$(bashio::config 'sigen_pass_enc' || true)"
SIGEN_BEARER="$(bashio::config 'sigen_bearer' || true)"
SIGEN_DEVICE_ID="$(bashio::config 'sigen_device_id' || true)"  # optional
STATION_ID="$(bashio::config 'station_id' || true)"
INTERVAL="$(bashio::config 'interval' || true)"                 # 5 or 30 (minutes)
ADVANCED_PRICE="$(bashio::config 'advanced_price' || true)"     # e.g. predicted|low|high
USE_CURRENT="$(bashio::config 'use_current' || false)"          # bool
DRY_RUN="$(bashio::config 'dry_run' || false)"                  # bool
ALIGN="$(bashio::config 'align' || true)"                       # optional: start|end
TZ_OVERRIDE="$(bashio::config 'tz_override' || true)"           # optional
PLAN_NAME="$(bashio::config 'plan_name' || true)"               # NEW

# MQTT (optional status sensor)
MQTT_ENABLED="$(bashio::config 'mqtt.enabled' || false)"
MQTT_HOST="$(bashio::config 'mqtt.host' || true)"
MQTT_PORT="$(bashio::config 'mqtt.port' || true)"
MQTT_USERNAME="$(bashio::config 'mqtt.username' || true)"
MQTT_PASSWORD="$(bashio::config 'mqtt.password' || true)"
MQTT_PREFIX="$(bashio::config 'mqtt.prefix' || 'amber2sigen/status')"

# -----------------------------
# Validate essentials
# -----------------------------
if [[ -z "${AMBER_TOKEN:-}" ]]; then
  bashio::log.error "Amber token is required (amber_token)."
  exit 1
fi

if [[ -z "${STATION_ID:-}" ]]; then
  bashio::log.error "Sigen station ID is required (station_id)."
  exit 1
fi

# Auth mode selection: prefer bearer, then pass_enc. Raw password is not supported.
AUTH_MODE="none"
if [[ -n "${SIGEN_BEARER:-}" ]]; then
  AUTH_MODE="bearer"
elif [[ -n "${SIGEN_PASS_ENC:-}" ]]; then
  AUTH_MODE="pass_enc"
elif [[ -n "${SIGEN_USER:-}" ]] || [[ -n "${SIGEN_DEVICE_ID:-}" ]]; then
  bashio::log.error "Raw email/password login is NOT supported by this add-on. Provide sigen_pass_enc or sigen_bearer."
  exit 1
else
  bashio::log.error "No Sigen credentials provided. Provide sigen_pass_enc or sigen_bearer."
  exit 1
fi

# Interval sanity
if [[ "${INTERVAL}" != "5" && "${INTERVAL}" != "30" ]]; then
  bashio::log.warning "interval=${INTERVAL} is not in {5,30}; defaulting to 30."
  INTERVAL="30"
fi

# Apply TZ override (optional)
if [[ -n "${TZ_OVERRIDE:-}" ]]; then
  export TZ="${TZ_OVERRIDE}"
  bashio::log.info "Timezone override active: TZ=${TZ}"
fi

# -----------------------------
# MQTT status publishing helper
# -----------------------------
publish_status() {
  local state="$1"       # running|valid|failed
  local message="$2"     # free text
  if [[ "${MQTT_ENABLED}" != "true" ]]; then
    return 0
  fi

  # status_mqtt.py expects env/args; keep secrets out of logs
  /opt/venv/bin/python /opt/amber2sigen/status_mqtt.py \
    --host "${MQTT_HOST}" \
    --port "${MQTT_PORT:-1883}" \
    ${MQTT_USERNAME:+--username "${MQTT_USERNAME}"} \
    ${MQTT_PASSWORD:+--password "${MQTT_PASSWORD}"} \
    --prefix "${MQTT_PREFIX}" \
    --state "${state}" \
    --attr "station_id=${STATION_ID}" \
    --attr "device_id_present=$([[ -n "${SIGEN_DEVICE_ID:-}" ]] && echo true || echo false)" \
    --attr "auth_mode=${AUTH_MODE}" \
    --message "${message}" \
  || bashio::log.warning "MQTT publish failed (state=${state})."
}

# Ensure we go offline on stop
_graceful_exit() {
  publish_status "failed" "stopped"
  exit 0
}
trap _graceful_exit SIGTERM SIGINT

# -----------------------------
# Banner (with redaction)
# -----------------------------
bashio::log.info "AMBER_TOKEN=$(redact "${AMBER_TOKEN}")"
bashio::log.info "SIGEN_USER=$(redact "${SIGEN_USER}")"
bashio::log.info "SIGEN_PASS_ENC=$(redact "${SIGEN_PASS_ENC}")"
bashio::log.info "SIGEN_BEARER=$(redact "${SIGEN_BEARER}")"
bashio::log.info "SIGEN_DEVICE_ID=$(redact "${SIGEN_DEVICE_ID}")"
log_banner

# -----------------------------
# Main loop
# -----------------------------
while true; do
  publish_status "running" "cycle start"

  # Build CLI flags for upstream script
  CLI_ARGS=( "--station-id" "${STATION_ID}" "--interval" "${INTERVAL}" )

  if [[ -n "${ADVANCED_PRICE:-}" ]]; then
    CLI_ARGS+=( "--advanced-price" "${ADVANCED_PRICE}" )
  fi

  if [[ "${USE_CURRENT}" == "true" ]]; then
    CLI_ARGS+=( "--use-current" )
  fi

  if [[ "${DRY_RUN}" == "true" ]]; then
    CLI_ARGS+=( "--dry-run" )
  fi

  if [[ -n "${ALIGN:-}" ]]; then
    CLI_ARGS+=( "--align" "${ALIGN}" )
  fi

  if [[ -n "${PLAN_NAME:-}" ]]; then
    CLI_ARGS+=( "--plan-name" "${PLAN_NAME}" )
  fi

  # Export env the upstream reads (tokens/ids) without echoing them
  export AMBER_TOKEN
  export SIGEN_USER
  export SIGEN_PASS_ENC
  export SIGEN_BEARER
  export SIGEN_DEVICE_ID

  bashio::log.info "Executing amber_to_sigen.py with args: ${CLI_ARGS[*]//${AMBER_TOKEN}/****}"

  if /opt/venv/bin/python /opt/amber2sigen/amber_to_sigen.py "${CLI_ARGS[@]}"; then
    bashio::log.info "Run complete: valid"
    publish_status "valid" "ok"
  else
    rc=$?
    bashio::log.error "Run failed with exit code ${rc}"
    publish_status "failed" "exit=${rc}"
  fi

  # Sleep until next cycle
  bashio::log.info "Sleeping ${INTERVAL} minutes…"
  sleep "$(( INTERVAL * 60 ))"
done
