#!/usr/bin/with-contenv bashio
# shellcheck shell=bash
set -euo pipefail

bashio::log.info "Starting Amber2Sigen Home Assistant Add-on"

# ---- Read options ----
AMBER_TOKEN="$(bashio::config 'amber_token')"
STATION_ID="$(bashio::config 'station_id')"
INTERVAL="$(bashio::config 'interval')"            # schema restricts to 5|30
TZ_OVERRIDE="$(bashio::config 'tz_override')"
ALIGN="$(bashio::config 'align')"                  # start|end (optional passthrough)
ADVANCED="$(bashio::config 'advanced')"            # low|predicted|high
USE_CURRENT="$(bashio::config 'use_current')"
DRY_RUN="$(bashio::config 'dry_run')"
PLAN_NAME="$(bashio::config 'plan_name')"          # optional plan name override

SIGEN_USER="$(bashio::config 'sigen_user')"
SIGEN_PASSWORD="$(bashio::config 'sigen_password')"  # currently not used to derive bearer
SIGEN_DEVICE_ID="$(bashio::config 'sigen_device_id')"
SIGEN_PASS_ENC="$(bashio::config 'sigen_pass_enc')"
SIGEN_BEARER="$(bashio::config 'sigen_bearer')"

MQTT_ENABLED="$(bashio::config 'mqtt_enabled')"
MQTT_HOST="$(bashio::config 'mqtt_host')"
MQTT_PORT="$(bashio::config 'mqtt_port')"
MQTT_USERNAME="$(bashio::config 'mqtt_username')"
MQTT_PASSWORD_MQTT="$(bashio::config 'mqtt_password')"
MQTT_TOPIC_PREFIX="$(bashio::config 'mqtt_topic_prefix')"

# ---- Basic validation ----
if [[ -z "${AMBER_TOKEN}" ]]; then
  bashio::log.error "Amber token is required"
  exit 2
fi
if [[ -z "${STATION_ID}" || "${STATION_ID}" == "0" ]]; then
  bashio::log.error "Sigen Station ID is required"
  exit 2
fi
if [[ "${INTERVAL}" != "5" && "${INTERVAL}" != "30" ]]; then
  bashio::log.warning "Invalid interval '${INTERVAL}', forcing to 30"
  INTERVAL="30"
fi

# ---- Determine auth mode ----
if [[ -n "${SIGEN_BEARER}" ]]; then
  bashio::log.info "Auth mode: Sigen bearer token"
elif [[ -n "${SIGEN_PASS_ENC}" ]]; then
  bashio::log.info "Auth mode: Sigen encrypted password"
elif [[ -n "${SIGEN_USER}" && -n "${SIGEN_PASSWORD}" ]]; then
  bashio::log.warning "Raw Sigen credentials provided, but no on-start login helper is implemented. Please provide 'sigen_pass_enc' or 'sigen_bearer'."
  exit 2
else
  bashio::log.error "No Sigen credentials provided. Set 'sigen_pass_enc' or 'sigen_bearer'."
  exit 2
fi

# ---- Export env for upstream script ----
export AMBER_TOKEN
export SIGEN_USER SIGEN_DEVICE_ID SIGEN_PASS_ENC SIGEN_BEARER
export TZ_OVERRIDE

# ---- MQTT status helper ----
publish_status() {
  local state="$1"
  local message="$2"
  if [[ "${MQTT_ENABLED}" == "true" ]]; then
    /opt/venv/bin/python3 /opt/amber2sigen-addon/status_mqtt.py \
      --host "${MQTT_HOST}" --port "${MQTT_PORT}" \
      --username "${MQTT_USERNAME}" --password "${MQTT_PASSWORD_MQTT}" \
      --prefix "${MQTT_TOPIC_PREFIX}" \
      --state "${state}" --message "${message}" || true
  fi
}

# One-shot discovery announce
if [[ "${MQTT_ENABLED}" == "true" ]]; then
  /opt/venv/bin/python3 /opt/amber2sigen-addon/status_mqtt.py \
    --host "${MQTT_HOST}" --port "${MQTT_PORT}" \
    --username "${MQTT_USERNAME}" --password "${MQTT_PASSWORD_MQTT}" \
    --prefix "${MQTT_TOPIC_PREFIX}" --announce || true
fi

# ---- Build upstream CLI flags (passthrough) ----
# Required:
BASE_FLAGS=( "--station-id" "${STATION_ID}" "--interval" "${INTERVAL}" "--advanced-price" "${ADVANCED}" )

# Optional:
[[ "${USE_CURRENT}" == "true" ]] && BASE_FLAGS+=( "--use-current" )
[[ "${DRY_RUN}" == "true" ]] && BASE_FLAGS+=( "--dry-run" )
# ALIGN is passed only if set and non-empty (upstream may ignore if unsupported)
if [[ -n "${ALIGN}" && "${ALIGN}" != "null" ]]; then
  BASE_FLAGS+=( "--align" "${ALIGN}" )
fi
# PLAN_NAME is passed only if set and non-empty
if [[ -n "${PLAN_NAME}" && "${PLAN_NAME}" != "null" ]]; then
  bashio::log.info "Using plan name: ${PLAN_NAME}"
  BASE_FLAGS+=( "--plan-name" "${PLAN_NAME}" )
fi

# ---- Main loop ----
while true; do
  bashio::log.info "Sync starting (interval=${INTERVAL}m, advanced=${ADVANCED}, dry_run=${DRY_RUN})"
  publish_status "running" "Sync in progress"

  set +e
  # Use venv python (PATH already points to /opt/venv/bin from Dockerfile)
  python3 /opt/amber2sigen/amber_to_sigen.py "${BASE_FLAGS[@]}"
  EXIT_CODE=$?
  set -e

  if [[ $EXIT_CODE -eq 0 ]]; then
    bashio::log.info "Sync complete"
    publish_status "valid" "Last sync succeeded"
  else
    bashio::log.warning "Sync failed with exit code ${EXIT_CODE}"
    publish_status "failed" "Last sync failed (exit ${EXIT_CODE})"
  fi

  # Sleep until next run; schema already enforces 5|30
  sleep $(( INTERVAL * 60 ))
done