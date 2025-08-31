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

## Step 1. Generate `.env` file

```bash
python3 sigen_make_env.py   --user "your@email.com"   --password "your-plaintext-password"   --env-path amber2sigen.env   --overwrite
```

This creates `amber2sigen.env` with `SIGEN_PASS_ENC`. 

Add your **Amber API token** manually.

Add your **Sigen Station ID** manually.

---

## Step 2. Example `.env`

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

## Step 3. Run manually

```bash
bash run.sh --dry-run
bash run.sh
```

---

## Step 4. systemd

`/etc/systemd/system/amber2sigen.service`
```ini
[Unit]
Description=Update Sigen tariffs from Amber
After=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/bin/env bash /home/youruser/amber2sig/run.sh
WorkingDirectory=/home/youruser/amber2sig
Environment=PYTHONUNBUFFERED=1
```

`/etc/systemd/system/amber2sigen.timer`
```ini
[Unit]
Description=Run amber2sigen periodically

[Timer]
OnBootSec=2min
OnCalendar=*:0/5:45
AccuracySec=1s
Unit=amber2sigen.service

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

---

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

## CLI Flags
- `--station-id` (required)
- `--interval 5|30`
- `--advanced-price low|predicted|high`
- `--use-current`
- `--dry-run`
