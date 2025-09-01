# Amber → Sigen Energy Controller

This project syncs real-time Amber Electric import/export prices into your Sigen Energy Controller.  
It can run every 5 or 30 minutes via systemd timer to keep your Sigen tariffs up to date.

---

## Features
- Pulls **Amber API** 5-minute or 30-minute prices (`perKwh` for buy, `spotPerKwh` for sell).
- Supports `--advanced-price {low,predicted,high}` for Amber’s `advancedPrice`.
- Seeds the **current active slot** from Amber’s `/prices/current` (optional, enabled by default).
- Authenticates to **Sigen Cloud** with either:
  - `SIGEN_USER`, `SIGEN_PASS_ENC`, `SIGEN_DEVICE_ID` (recommended), or
  - `SIGEN_BEARER` (manual bearer token).
- Dry-run mode prints JSON payload without posting to Sigen.
- Works with both `--interval 5` and `--interval 30`.
  - **Note**: Sigen only supports `--interval 30` right now.
- Supports 30 minute billing for Amber customers (Eg, Victoria?)
  - Use `--use-current 0` to force 30 minute Amber billing data (dont use 5 minute current for infill) 

---

## Requirements
- Python 3.9+
- `requests`, `pycryptodome`, `python-dateutil`

Install:
```bash
pip install -r requirements.txt
```

---

## Step 1. Create user and directory

For security, run this under a dedicated system user:

```bash
sudo useradd --system --home /opt/amber2sigen --shell /usr/sbin/nologin amber2sigen
sudo mkdir -p /opt/amber2sigen
sudo chown amber2sigen:amber2sigen /opt/amber2sigen
```

Clone or copy this repo into `/opt/amber2sigen`.
Ensure the python script and run.sh files are also owned by amber2sigen:amber2sigen

---

## Step 2. Generate `.env` file

Run the helper to create your env file:

```bash
cd /opt/amber2sigen
python3 sigen_make_env.py
```

You will be prompted for:
- **Amber API token** (`AMBER_TOKEN`)
- **Sigen username** (`SIGEN_USER`) (See Below)
- **Sigen encoded password** (`SIGEN_PASS_ENC`) (See below)
- **Sigen device ID** (`SIGEN_DEVICE_ID`) (See below)

Then move the generated env file to `/etc`:

```bash
sudo mv amber2sigen.env /etc/amber2sigen.env
sudo chown root:root /etc/amber2sigen.env
sudo chmod 600 /etc/amber2sigen.env
```

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

Copy these values exactly into the prompts.

## How to find your Sigen Station ID

The `STATION_ID` is a unique numeric ID assigned to your Sigen Energy Controller by Sigen Cloud.  
It must be included in the payload or Sigen won’t know which unit to update.

Easiest way to find it:
1. Ask SigenAI to "Tell me my StationID"

Complex Ways to find it:
1. **HAR capture**: In your browser, open the Sigen web portal, perform a tariff save, then export the HAR.  
   Look for `"stationId": <your station ID>` in the JSON payload.  
2. **App/device info**: Sometimes shown in the app under device details.  
3. Once known, add it to your `.env` file as `STATION_ID=...`.

This value is specific to your unit — not random or generated locally.

---

## Step 3. Example `/etc/amber2sigen.env`

```dotenv
AMBER_TOKEN=psk_xxxxxxxxxxxxxxxxxxxx
SIGEN_USER=your@email.com
SIGEN_DEVICE_ID=1756353655250
SIGEN_PASS_ENC="ENCRYPTED_BLOB"

# Optional tuning
INTERVAL=30
TZ_OVERRIDE=Australia/Adelaide
ALIGN=end
PLAN_NAME=Amber Live
ADVANCED=predicted
USE_CURRENT=1
STATION_ID=<Ask SigenAI for your Station ID>
```

---

## Step 4. Run manually

```bash
cd /opt/amber2sigen
sudo -u amber2sigen bash run.sh --dry-run
sudo -u amber2sigen bash run.sh
```

---

## Step 5. systemd

`/etc/systemd/system/amber2sigen.service`
```ini
[Unit]
Description=Amber -> Sigen price sync
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=/etc/amber2sigen.env
WorkingDirectory=/opt/amber2sigen
ExecStart=/bin/bash /opt/amber2sigen/run.sh
User=amber2sigen
Group=amber2sigen
```

`/etc/systemd/system/amber2sigen.timer`
```ini
[Unit]
Description=Run amber2sigen periodically at absolute 4-min marks +45s
Wants=amber2sigen.service

[Timer]
OnBootSec=2min
OnCalendar=*:0/5:20
Unit=amber2sigen.service
Persistent=true
AccuracySec=1s

[Install]
WantedBy=timers.target
```

Enable:
```bash
sudo systemctl daemon-reexec
sudo systemctl enable --now amber2sigen.timer
```

---

## Journalctl Troubleshooting

- Check last run:
  ```bash
  journalctl -u amber2sigen.service -n 200 --no-pager
  ```
- Follow logs:
  ```bash
  journalctl -u amber2sigen.service -f
  ```
- Verify timer:
  ```bash
  systemctl list-timers | grep amber2sigen
  ```
- Watch Timer:
- ```bash
watch -n 10 "systemctl list-timers | grep amber2sigen"
```

---

## CLI Flags
- `--station-id` (required)
- `--interval 5|30`
- `--advanced-price low|predicted|high`
- `--use-current`
- `--dry-run`