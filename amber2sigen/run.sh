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

null_to_empty() { local v="$1"; [[ "${!v:-}" == "null" ]] && printf -v "$v" ""; }

publish_status() {
  local state="$1"   # running|valid|failed
  local message="$2" # free text

  if [[ "${MQTT_ENABLED}" == "true" ]]; then
    python3 /opt/amber2sigen/status_mqtt.py \
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
  bashio::log.error "Amber token is required (amber_token)."; exit 1
fi
if [[ -z "${STATION_ID:-}" ]]; then
  bashio::log.error "Sigen station ID is required (station_id)."; exit 1
fi
if [[ "${INTERVAL}" != "5" && "${INTERVAL}" != "30" ]]; then
  bashio::log.warning "interval=${INTERVAL} not in {5,30}; defaulting to 30."
  INTERVAL="30"
fi

# ---------- optional config (read directly, then normalize "null") ----------
SIGEN_DEVICE_ID="$(bashio::config 'sigen_device_id' || true)"
SIGEN_USER="$(bashio::config 'sigen_user' || true)"
SIGEN_PASS_ENC="$(bashio::config 'sigen_pass_enc' || true)"
SIGEN_BEARER="$(bashio::config 'sigen_bearer' || true)"

ADVANCED_PRICE="$(bashio::config 'advanced_price' || true)"
ALIGN="$(bashio::config 'align' || true)"
PLAN_NAME="$(bashio::config 'plan_name' || true)"

USE_CURRENT="$(bashio::config 'use_current' || echo 'false')"
DRY_RUN="$(bashio::config 'dry_run' || echo 'false')"

TZ_OVERRIDE="$(bashio::config 'tz_override' || true)"

MQTT_ENABLED="$(bashio::config 'mqtt.enabled' || echo 'false')"
MQTT_HOST="$(bashio::config 'mqtt.host' || true)"
MQTT_PORT="$(bashio::config 'mqtt.port' || echo '1883')"
MQTT_USERNAME="$(bashio::config 'mqtt.username' || true)"
MQTT_PASSWORD="$(bashio::config 'mqtt.password' || true)"
MQTT_PREFIX="$(bashio::config 'mqtt.prefix' || echo 'amber2sigen/status')"

# normalize "null" to empty/false
for key in ADVANCED_PRICE ALIGN PLAN_NAME TZ_OVERRIDE MQTT_HOST MQTT_PORT MQTT_USERNAME MQTT_PASSWORD MQTT_PREFIX SIGEN_DEVICE_ID SIGEN_USER SIGEN_PASS_ENC SIGEN_BEARER; do
  null_to_empty "$key"
done
[[ "${MQTT_ENABLED}" == "null" ]] && MQTT_ENABLED="false"
[[ "${USE_CURRENT}"  == "null" ]] && USE_CURRENT="false"
[[ "${DRY_RUN}"      == "null" ]] && DRY_RUN="false"

# ---------- TZ override ----------
if [[ -n "${TZ_OVERRIDE:-}" ]]; then
  export TZ="${TZ_OVERRIDE}"
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
mqtt_str=$([[ "${MQTT_ENABLED}" == "true" ]] && echo "enabled" || echo "disabled")
bashio::log.info "Starting Amber2Sigen Add-on"
bashio::log.info "interval=${INTERVAL}m mode=${mode_str} align=${align_str} plan=\"${plan_str}\" auth=${AUTH_MODE} mqtt=${mqtt_str}"

# (Optional) debug certain read-back values (comment out after verifying)
# bashio::log.info "DEBUG: options snapshot: $(jq -c '{advanced_price:.advanced_price,align:.align,plan_name:.plan_name,mqtt:.mqtt}' /data/options.json)"

# ---------- main loop ----------
while true; do
  publish_status "running" "cycle start"

  CLI_ARGS=( "--station-id" "${STATION_ID}" "--interval" "${INTERVAL}" )
  [[ -n "${ADVANCED_PRICE}" ]] && CLI_ARGS+=( "--advanced-price" "${ADVANCED_PRICE}" )
  [[ "${USE_CURRENT}" == "true" ]] && CLI_ARGS+=( "--use-current" )
  [[ "${DRY_RUN}" == "true" ]] && CLI_ARGS+=( "--dry-run" )
  [[ -n "${ALIGN}" ]] && CLI_ARGS+=( "--align" "${ALIGN}" )
  [[ -n "${PLAN_NAME}" ]] && CLI_ARGS+=( "--plan-name" "${PLAN_NAME}" )
  [[ -n "${SIGEN_DEVICE_ID}" ]] && CLI_ARGS+=( "--device-id" "${SIGEN_DEVICE_ID}" )

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
