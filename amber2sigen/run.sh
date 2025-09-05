#!/usr/bin/with-contenv bashio
# shellcheck shell=bash
set -euo pipefail

bashio::log.info "Starting Amber2Sigen Home Assistant Add-on"

# -------- options --------
AMBER_TOKEN="$(bashio::config 'amber_token')"
STATION_ID="$(bashio::config 'station_id')"

INTERVAL="$(bashio::config 'interval')"            # allowed: 5|30
TZ_OVERRIDE="$(bashio::config 'tz_override')"
ALIGN="$(bashio::config 'align')"                  # start|end (optional)
ADVANCED="$(bashio::config 'advanced')"            # low|predicted|high
USE_CURRENT="$(bashio::config 'use_current')"
DRY_RUN="$(bashio::config 'dry_run')"

SIGEN_USER="$(bashio::config 'sigen_user')"
SIGEN_PASSWORD="$(bashio::config 'sigen_password')"  # not used unless you add a login helper
SIGEN_DEVICE_ID="$(bashio::config 'sigen_device_id')"
SIGEN_PASS_ENC="$(bashio::config 'sigen_pass_enc')"
SIGEN_BEARER="$(bashio::config 'sigen_bearer')"

PLAN_NAME="$(bashio::config 'plan_name')"

MQTT_ENABLED="$(bashio::config 'mqtt_enabled')"
MQTT_HOST="$(bashio::config 'mqtt_host')"
MQTT_PORT="$(bashio::config 'mqtt_port')"
MQTT_USERNAME="$(bashio::config 'mqtt_username')"
MQTT_PASSWORD_MQTT="$(bashio::config 'mqtt_password')"
MQTT_TOPIC_PREFIX="$(bashio::config 'mqtt_topic_prefix')"

USE_HA_ENTITIES="$(bashio::config 'use_ha_entities')"
HA_IMPORT_ENTITY="$(bashio::config 'ha_import_entity')"
HA_EXPORT_ENTITY="$(bashio::config 'ha_export_entity')"

# -------- basic validation --------
if [[ -z "${STATION_ID}" || "${STATION_ID}" == "0" ]]; then
  bashio::log.error "Sigen Station ID is required"
  exit 2
fi

if [[ "${INTERVAL}" != "5" && "${INTERVAL}" != "30" ]]; then
  bashio::log.warning "Invalid interval '${INTERVAL}', forcing to 30"
  INTERVAL="30"
fi

# Auth summary (we fail later only if the chosen mode needs auth and it's missing)
if [[ -n "${SIGEN_BEARER}" ]]; then
  bashio::log.info "Auth mode available: Sigen bearer"
elif [[ -n "${SIGEN_PASS_ENC}" ]]; then
  bashio::log.info "Auth mode available: Sigen encrypted password"
elif [[ -n "${SIGEN_USER}" && -n "${SIGEN_PASSWORD}" ]]; then
  bashio::log.warning "Raw Sigen credentials provided, but no login helper is enabled. Provide sigen_pass_enc or sigen_bearer."
else
  bashio::log.warning "No Sigen credentials set yet."
fi

# When NOT using HA entities, Amber token is required for API fetches
if [[ "${USE_HA_ENTITIES}" != "true" && "${USE_HA_ENTITIES}" != "1" ]]; then
  if [[ -z "${AMBER_TOKEN}" ]]; then
    bashio::log.error "Amber API token is required (or enable entity mode via use_ha_entities)."
    exit 2
  fi
fi

# -------- exports for called scripts --------
export AMBER_TOKEN
export SIGEN_USER SIGEN_DEVICE_ID SIGEN_PASS_ENC SIGEN_BEARER
export TZ_OVERRIDE

# -------- MQTT helper --------
mqtt_status() {
  local state="$1"   # running|valid|failed
  local message="$2"
  if [[ "${MQTT_ENABLED}" == "true" ]]; then
    /opt/venv/bin/python3 /opt/amber2sigen-addon/status_mqtt.py \
      --host "${MQTT_HOST}" --port "${MQTT_PORT}" \
      --username "${MQTT_USERNAME}" --password "${MQTT_PASSWORD_MQTT}" \
      --prefix "${MQTT_TOPIC_PREFIX}" \
      --state "${state}" --message "${message}" || true
  fi
}

# One-time MQTT discovery
if [[ "${MQTT_ENABLED}" == "true" ]]; then
  /opt/venv/bin/python3 /opt/amber2sigen-addon/status_mqtt.py \
    --host "${MQTT_HOST}" --port "${MQTT_PORT}" \
    --username "${MQTT_USERNAME}" --password "${MQTT_PASSWORD_MQTT}" \
    --prefix "${MQTT_TOPIC_PREFIX}" --announce || true
fi

# -------- build common flags for upstream (API mode) --------
BASE_FLAGS=( "--station-id" "${STATION_ID}" "--interval" "${INTERVAL}" "--advanced-price" "${ADVANCED}" )
[[ "${USE_CURRENT}" == "true" ]] && BASE_FLAGS+=( "--use-current" )
[[ "${DRY_RUN}" == "true" ]] && BASE_FLAGS+=( "--dry-run" )
if [[ -n "${ALIGN}" && "${ALIGN}" != "null" ]]; then
  BASE_FLAGS+=( "--align" "${ALIGN}" )
fi
# plan name (if upstream supports it)
if [[ -n "${PLAN_NAME}" && "${PLAN_NAME}" != "null" ]]; then
  BASE_FLAGS+=( "--plan-name" "${PLAN_NAME}" )
fi

# -------- helper: ensure Sigen auth present --------
require_sigen_auth_or_die() {
  if [[ -n "${SIGEN_BEARER}" || -n "${SIGEN_PASS_ENC}" ]]; then
    return 0
  fi
  bashio::log.error "No Sigen credentials provided. Set 'sigen_pass_enc' or 'sigen_bearer'."
  exit 2
}

# -------- main loop --------
while true; do
  bashio::log.info "Sync starting (interval=${INTERVAL}m, advanced=${ADVANCED}, mode=$([[ "${USE_HA_ENTITIES}" == "true" || "${USE_HA_ENTITIES}" == "1" ]] && echo 'HA entities' || echo 'Amber API'))"
  mqtt_status "running" "Sync in progress"

  EXIT_CODE=1

  if [[ "${USE_HA_ENTITIES}" == "true" || "${USE_HA_ENTITIES}" == "1" ]]; then
    # ---------- ENTITY MODE ----------
    # Validate entity inputs
    if [[ -z "${HA_IMPORT_ENTITY}" || "${HA_IMPORT_ENTITY}" == "null" ]]; then
      bashio::log.error "Entity mode enabled but 'ha_import_entity' is empty."
      EXIT_CODE=2
    else
      require_sigen_auth_or_die

      # Provide env for the builder
      export USE_HA_ENTITIES=1
      export HA_IMPORT_ENTITY HA_EXPORT_ENTITY PLAN_NAME

      # Build plan JSON from HA entities
      if ! PLAN_JSON="$(/opt/venv/bin/python3 /opt/amber2sigen-addon/ha_entities_source.py)"; then
        bashio::log.error "Failed to build plan from HA entities."
        EXIT_CODE=3
      else
        echo "${PLAN_JSON}" > /tmp/ha_plan.json

        # Prefer sigen_push.py if present; else try ha_wrapper.py --plan-json
        if [[ -x "/opt/amber2sigen-addon/sigen_push.py" ]]; then
          bashio::log.info "Pushing plan via sigen_push.py"
          set +e
          /opt/venv/bin/python3 /opt/amber2sigen-addon/sigen_push.py \
            --station-id "${STATION_ID}" \
            --plan-json /tmp/ha_plan.json \
            $( [[ -n "${SIGEN_BEARER}" ]] && echo --sigen-bearer "${SIGEN_BEARER}" ) \
            $( [[ -n "${SIGEN_PASS_ENC}" ]] && echo --sigen-pass-enc "${SIGEN_PASS_ENC}" )
          EXIT_CODE=$?
          set -e
        else
          bashio::log.info "sigen_push.py not found; trying ha_wrapper.py --plan-json"
          set +e
          /opt/venv/bin/python3 /opt/amber2sigen-addon/ha_wrapper.py \
            --station-id "${STATION_ID}" \
            --plan-json /tmp/ha_plan.json \
            $( [[ -n "${SIGEN_BEARER}" ]] && echo --sigen-bearer "${SIGEN_BEARER}" ) \
            $( [[ -n "${SIGEN_PASS_ENC}" ]] && echo --sigen-pass-enc "${SIGEN_PASS_ENC}" )
          EXIT_CODE=$?
          set -e
          if [[ $EXIT_CODE -ne 0 ]]; then
            bashio::log.error "ha_wrapper.py did not accept --plan-json (or failed). Consider adding sigen_push.py helper."
          fi
        fi
      fi
    fi

  else
    # ---------- AMBER API MODE ----------
    require_sigen_auth_or_die
    set +e
    # Upstream script should respect AMBER_TOKEN from env
    python3 /opt/amber2sigen/amber_to_sigen.py "${BASE_FLAGS[@]}"
    EXIT_CODE=$?
    set -e
  fi

  # ---------- status + sleep ----------
  if [[ $EXIT_CODE -eq 0 ]]; then
    bashio::log.info "Sync complete"
    mqtt_status "valid" "Last sync succeeded"
  else
    bashio::log.warning "Sync failed with exit code ${EXIT_CODE}"
    mqtt_status "failed" "Last sync failed (exit ${EXIT_CODE})"
  fi

  sleep $(( INTERVAL * 60 ))
done
