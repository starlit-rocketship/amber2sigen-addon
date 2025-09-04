> **Current add-on version:** 1.0.2

# Amber2Sigen (Home Assistant Add-on)

Sync real-time Amber Electric import/export prices into your Sigen Energy Controller tariff plan, every 5–30 minutes, running as a Home Assistant add-on.

**Upstream:** Based on [Talie5in/amber2sigen](https://github.com/Talie5in/amber2sigen) (we call the upstream script inside this add-on).  
**Amber API:** Official; generate tokens in Amber’s web app under Developers.

## Install (as a custom add-on repository)

1. In Home Assistant: _Settings → Add-ons → Add-on Store → … (3 dots) → Repositories_
2. Add: `https://github.com/starlit-rocketship/amber2sigen-addon`
3. Find **Amber2Sigen** and click **Install**.

### How to find SIGEN_PASS_ENC and SIGEN_DEVICE_ID

1. Open the Sigen web portal in your browser (https://app-aus.sigencloud.com/)
2. Open Developer Tools → **Network** tab.
3. Log in normally.
4. Look for a request to:
   ```
   https://api-aus.sigencloud.com/auth/oauth/token
   ```
5. In the request payload you will see:
   - `password` → this is the **encoded password** (copy into `SIGEN_PASS_ENC`).
   - `userDeviceId` → this is the **device ID** (copy into `SIGEN_DEVICE_ID`).

## Configure

- **Amber API Token**: Paste your token from Amber developers page.
- **Station ID**: Your Sigen Station ID (ask Sigen AI or capture from portal).
- **Sigen Auth**: Preferred: `sigen_user` + `sigen_pass_enc` + `sigen_device_id`, or provide `sigen_bearer`.
- **Interval**: Default 30 min (Sigen currently supports 30 min; 5-min is sent but may be ignored).
- **Advanced**: `low` | `predicted` | `high` for Amber’s advanced price flavor.
- **Use current**: Fill the first slot from Amber `/prices/current` (matches upstream defaults).
- **MQTT (optional)**: Enable to publish a status sensor.

> The add-on reads options from `/data/options.json` (standard for HA add-ons).

## What it does

- Fetches Amber prices and formats Sigen tariff payloads (delegated to upstream script).
- Authenticates to Sigen using your encrypted password + device ID, or a bearer token.
- Posts prices to Sigen, logs results with timestamps.
- Optionally publishes a status sensor via MQTT.

## Status sensor (MQTT)

If enabled, the add-on publishes discovery and state to:

- `homeassistant/sensor/amber2sigen_status/config`
- `amber2sigen/status` with JSON `{ state, message, ts }`

States: `running`, `valid` (success), `failed`.

## Security

- Secrets are read from HA options; we redact tokens in logs.
- Don’t paste secrets in GitHub issues or logs.

## Troubleshooting

- **No add-on options?** Ensure you saved the configuration—HA writes to `/data/options.json`.
- **Station ID?** Ask Sigen AI for your Station ID or check browser dev tools for API payloads.
- **Amber token?** See Amber’s “Do you have an API?” page → Developers → Generate token.
- **Intervals**: Upstream supports 5 or 30; Sigen typically accepts 30-minute plans currently.

## Differences vs upstream

- Runs inside HA add-on container with S6 overlay.
- Adds optional MQTT status publishing.
- Uses HA options schema & bashio to read configuration.

## License

Upstream license applies to its code; this repository adds HA wrapper logic and metadata only.
