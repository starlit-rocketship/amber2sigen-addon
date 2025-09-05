#!/usr/bin/with-contenv bashio
# shellcheck shell=bash

set -eo pipefail

# ---------- helpers ----------
redact() {
  local s="${1:-}"
  if [[ -z "$s" ]]; then echo "<empty>"; return; fi
  (( ${#s} > 10 )) && { echo "${s:0:4}…${s: -3}"; return; }
  echo "****"
}

publish_status() {
  local state="$1"   # running|valid|failed
  local message="$2" # free text

  if bashio::config.true 'mqtt.enabled'; then
    local host port user pass prefix
    host="$(bashio::config 'mqtt.host' || echo 'localhost')"
    port="$(bashio::config 'mqtt.port' || echo '1883')"
    user="$(bashio::config 'mqtt.username' || true)"
    pass="$(bashio::config 'mqtt.password' || true)"
    prefix="$(bashio::config 'mqtt.prefix' || echo 'amber2sigen/status')"

    python3 /opt/amber2sigen/status_mqtt.py \
      --host "${host}" \
      --port "${port}" \
      ${user:+--username "${user}"} \
      ${pass:+--password "${pass}"} \
      --prefix "${prefix}" \
      --state "${state}" \
      --attr "station_id=${STATION_ID}" \
      --attr "device_id_present=$([[ -n "${SIGEN_DEVICE_ID:-}" ]] && echo true || echo false)" \
      --attr "auth_mode=${AUTH_MODE}" \
      --message "${message}" \
      || bashio::log.warning "MQTT publish failed (state=${state})."
  fi
}

graceful_exit() {
  publish_status "failed" "stopped"
  exit 0
}
trap graceful_exit SIGTERM SIGINT

# ---------- read required config ----------
AMBER_TOKEN="$(bashio::config 'amber_token' || true)"
STATION_ID="$(bashio::config 'station_id' || true)"
INTERVAL="$(bashio::config 'interval' || echo '30')"

if [[ -z "${AMBER_TOKEN:-}" ]]; then
  bashio::log.error "Amber token is required (amber_token)."
  exit 1
fi
if [[ -z "${STATION_ID:-}" ]]; then
  bashio::log.error "Sigen station ID is required (station_id)."
  exit 1
fi
if [[ "${INTERVAL}" != "5" && "${INTERVAL}" != "30" ]]; then
  bashio::log.warning "interval=${INTERVAL} not in {5,30}; defaulting to 30."
  INTERVAL="30"
fi

# ---------- optional config ----------
SIGEN_DEVICE_ID="$(bashio::config 'sigen_device_id' || true)"
SIGEN_USER="$(bashio::config 'sigen_user' || true)"
SIGEN_PASS_ENC="$(bashio::config 'sigen_pass_enc' || true)"
SIGEN_BEARER="$(bashio::config 'sigen_bearer' || true)"

ADVANCED_PRICE=""
bashio::config.has 'advanced_price' && ADVANCED_PRICE="$(bashio::config 'advanced_price')"

ALIGN=""
bashio::config.has 'align' && ALIGN="$(bashio::config 'align')"

PLAN_NAME=""
bashio::config.has 'plan_name' && PLAN_NAME="$(bashio::config 'plan_name')"

USE_CURRENT=false
bashio::config.true 'use_current' && USE_CURRENT=true

DRY_RUN=false
bashio::config.true 'dry_run' && DRY_RUN=true

if bashio::config.has 'tz_override'; then
  export TZ="$(bashio::config 'tz_override')"
  bashio::log.info "Timezone override active: TZ=${TZ}"
fi

# ---------- auth preference (bearer > pass_enc) ----------
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

# ---------- banner (redacted) ----------
bashio::log.info "AMBER_TOKEN=$(redact "${AMBER_TOKEN}")"
bashio::log.info "SIGEN_USER=$(redact "${SIGEN_USER}")"
bashio::log.info "SIGEN_PASS_ENC=$(redact "${SIGEN_PASS_ENC}")"
bashio::log.info "SIGEN_BEARER=$(redact "${SIGEN_BEARER}")"
bashio::log.info "SIGEN_DEVICE_ID=$(redact "${SIGEN_DEVICE_ID}")"

mode_str="${ADVANCED_PRICE:-<default>}"
align_str="${ALIGN:-<none>}"
plan_str="${PLAN_NAME:-<none>}"
mqtt_str=$([[ "$(bashio::config 'mqtt.enabled' || echo false)" == "true" ]] && echo "enabled" || echo "disabled")
bashio::log.info "Starting Amber2Sigen Add-on"
bashio::log.info "interval=${INTERVAL}m mode=${mode_str} align=${align_str} plan=\"${plan_str}\" auth=${AUTH_MODE} mqtt=${mqtt_str}"

# ---------- main loop ----------
while true; do
  publish_status "running" "cycle start"

  # Build CLI args for upstream
  CLI_ARGS=( "--station-id" "${STATION_ID}" "--interval" "${INTERVAL}" )

  [[ -n "${ADVANCED_PRICE}" ]] && CLI_ARGS+=( "--advanced-price" "${ADVANCED_PRICE}" )
  $USE_CURRENT && CLI_ARGS+=( "--use-current" )
  $DRY_RUN && CLI_ARGS+=( "--dry-run" )
  [[ -n "${ALIGN}" ]] && CLI_ARGS+=( "--align" "${ALIGN}" )
  [[ -n "${PLAN_NAME}" ]] && CLI_ARGS+=( "--plan-name" "${PLAN_NAME}" )
  [[ -n "${SIGEN_DEVICE_ID}" ]] && CLI_ARGS+=( "--device-id" "${SIGEN_DEVICE_ID}" )

  # Export env used by upstream (don’t echo)
  export AMBER_TOKEN SIGEN_USER SIGEN_PASS_ENC SIGEN_BEARER SIGEN_DEVICE_ID

  bashio::log.info "Executing amber_to_sigen.py with args: ${CLI_ARGS[*]}"
  if python3 /opt/amber2sigen/amber_to_sigen.py "${CLI_ARGS[@]}"; then
    bashio::log.info "Run complete: valid"
    publish_status "valid" "ok"
  else
    rc=$?
    bashio::log.error "Run failed with exit code ${rc}"
    publish_status "failed" "exit=${rc}"
  fi

  bashio::log.info "Sleeping ${INTERVAL} minutes…"
  sleep "$(( INTERVAL * 60 ))"
done
