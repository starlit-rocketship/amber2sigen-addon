#!/opt/venv/bin/python3
"""
Push a prepared buy/sell plan JSON to Sigen.

Usage:
  sigen_push.py --station-id 1020... --plan-json /tmp/ha_plan.json [--sigen-bearer ...] [--sigen-pass-enc ...] [--sigen-url ...]
Auth priority:
  1) --sigen-bearer (or env SIGEN_BEARER)
  2) --sigen-pass-enc (or env SIGEN_PASS_ENC) -> exchanged for a bearer
"""

import argparse, json, os, sys, time
import requests

DEFAULT_BASE = os.environ.get("SIGEN_URL", "https://app.sigenenergy.com")
AUTH_PATH = "/app/api/account/passEncLogin"   # may vary by region; adjust if needed
PLAN_PATH = "/app/api/station/price/set"      # POST price plan

def log(msg): print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)

def get_bearer_from_passenc(base, pass_enc):
    url = base + AUTH_PATH
    payload = {"passEnc": pass_enc}
    r = requests.post(url, json=payload, timeout=15)
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(f"passEnc login failed: {data}")
    token = data.get("data", {}).get("token") or data.get("data", {}).get("accessToken")
    if not token:
        raise RuntimeError("No token in passEnc login response")
    return token

def push_plan(base, station_id, bearer, plan_json):
    url = base + PLAN_PATH
    headers = {"Authorization": f"Bearer {bearer}"}
    payload = {"stationId": int(station_id), "priceMode": 1, **plan_json}
    r = requests.post(url, json=payload, headers=headers, timeout=20)
    try:
        data = r.json()
    except Exception:
        r.raise_for_status()
        raise
    if data.get("code") != 0:
        raise RuntimeError(f"Sigen returned error: {data}")
    return True

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--station-id", required=True)
    ap.add_argument("--plan-json", required=True)
    ap.add_argument("--sigen-bearer", default=os.environ.get("SIGEN_BEARER"))
    ap.add_argument("--sigen-pass-enc", default=os.environ.get("SIGEN_PASS_ENC"))
    ap.add_argument("--sigen-url", default=DEFAULT_BASE)
    args = ap.parse_args()

    if not os.path.exists(args.plan_json):
        log(f"plan file not found: {args.plan_json}")
        return 2

    with open(args.plan_json, "r", encoding="utf-8") as f:
        plan = json.load(f)

    bearer = args.sigen_bearer
    if not bearer and args.sigen_pass_enc:
        log("No bearer provided; exchanging pass_enc for a bearer…")
        bearer = get_bearer_from_passenc(args.sigen_url, args.sigen_pass_enc)

    if not bearer:
        log("No bearer or pass_enc available.")
        return 2

    log("Pushing plan to Sigen…")
    ok = push_plan(args.sigen_url, args.station_id, bearer, plan)
    if ok:
        log('Sigen response: 200 {"code":0,"msg":"success","data":true}')
        return 0
    return 1

if __name__ == "__main__":
    try:
        sys.exit(main())
    except requests.RequestException as e:
        log(f"HTTP error: {e}")
        sys.exit(2)
    except Exception as e:
        log(f"Fatal: {e}")
        sys.exit(2)
