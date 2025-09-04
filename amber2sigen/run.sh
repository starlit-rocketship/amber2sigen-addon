#!/usr/bin/with-contenv bashio
set -euo pipefail

bashio::log.info "Starting Amber2Sigen Home Assistant Add-on"

# Read options from /data/options.json via bashio (preferred over jq)
AMBER_TOKEN="$(bashio::config 'amber_token')"
STATION_ID="$(bashio::config 'station_id')"
INTERVAL="$(bashio::config 'interval')"
TZ_OVERRIDE="$(bashio::config 'tz_override')"
ALIGN="$(bashio::config 'align')"
ADVANCED="$(bashio::config 'advanced')"
USE_CURRENT="$(bashio::config 'use_current')"
DRY_RUN="$(bashio::config 'dry_run')"

SIGEN_USER="$(bashio::config 'sigen_user')"
SIGEN_DEVICE_ID="$(bashio::config 'sigen_device_id')"
SIGEN_PASS_ENC="$(bashio::config 'sigen_pass_enc')"
SIGEN_BEARER="$(bashio::config 'sigen_bearer')"

MQTT_ENABLED="$(bashio::config 'mqtt_enabled')"
MQTT_HOST="$(bashio::config 'mqtt_host')"
MQTT_PORT="$(bashio::config 'mqtt_port')"
MQTT_USERNAME="$(bashio::config 'mqtt_username')"
MQTT_PASSWORD="$(bashio::config 'mqtt_password')"
MQTT_TOPIC_PREFIX="$(bashio::config 'mqtt_topic_prefix')"

# Basic validation
if [[ -z "${AMBER_TOKEN}" ]]; then
  bashio::log.error "Amber token is required"
  exit 2
fi
if [[ "${STATION_ID}" == "0" ]]; then
  bashio::log.error "Sigen Station ID is required"
  exit 2
fi

# Export minimal env the upstream script expects
export AMBER_TOKEN
export SIGEN_USER SIGEN_DEVICE_ID SIGEN_PASS_ENC SIGEN_BEARER
export TZ_OVERRIDE

# Helper to publish MQTT status (optional)
publish_status() {
  local state="$1"
  local message="$2"
  if [[ "${MQTT_ENABLED}" == "true" ]]; then
    python3 /opt/amber2sigen-addon/status_mqtt.py \
      --host "${MQTT_HOST}" --port "${MQTT_PORT}" \
      --username "${MQTT_USERNAME}" --password "${MQTT_PASSWORD}" \
      --prefix "${MQTT_TOPIC_PREFIX}" \
      --state "${state}" --message "${message}" || true
  fi
}

# Announce discovery (one-shot)
if [[ "${MQTT_ENABLED}" == "true" ]]; then
  python3 /opt/amber2sigen-addon/status_mqtt.py \
    --host "${MQTT_HOST}" --port "${MQTT_PORT}" \
    --username "${MQTT_USERNAME}" --password "${MQTT_PASSWORD}" \
    --prefix "${MQTT_TOPIC_PREFIX}" --announce || true
fi

# Main loop
while true; do
  bashio::log.info "Sync starting (interval=${INTERVAL}m advanced=${ADVANCED} dry_run=${DRY_RUN})"
  publish_status "running" "Sync in progress"

  # Build CLI flags for upstream script (see upstream README)
  # --station-id is required; --interval/--advanced-price/--use-current/--dry-run optional
  FLAGS=( "--station-id" "${STATION_ID}" "--interval" "${INTERVAL}" "--advanced-price" "${ADVANCED}" )
  [[ "${USE_CURRENT}" == "true" ]] && FLAGS+=( "--use-current" )
  [[ "${DRY_RUN}" == "true" ]] && FLAGS+=( "--dry-run" )

  set +e
  /usr/bin/env python3 /opt/amber2sigen/amber_to_sigen.py "${FLAGS[@]}"
  EXIT_CODE=$?
  set -e

  if [[ $EXIT_CODE -eq 0 ]]; then
    bashio::log.info "Sync complete"
    publish_status "valid" "Last sync succeeded"
  else
    bashio::log.warning "Sync failed with exit code ${EXIT_CODE}"
    publish_status "failed" "Last sync failed (exit ${EXIT_CODE})"
  fi

  # Sleep until next run; enforce min 5 minutes
  SLEEP_MIN=${INTERVAL}
  if (( SLEEP_MIN < 5 )); then SLEEP_MIN=5; fi
  sleep $(( SLEEP_MIN * 60 ))
done
