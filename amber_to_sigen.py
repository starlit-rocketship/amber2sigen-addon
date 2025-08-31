#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Amber (5-minute or 30-minute) -> Sigen staticPricing (now -> +24h)

Version: v23
- /prices/current now requests previous=0, next=1 to prefer the “CurrentInterval”
  and the immediate next forecast row.
- Active-slot seeding preference is Current > Forecast > Actual (5-min first,
  falling back to 30-min if the 5-min endpoint returns nothing).
- BUY always uses --advanced-price (low|predicted|high) if present, otherwise perKwh.
  When reading /prices/current, BUY will fall back to perKwh if advancedPrice is missing.
- SELL uses spotPerKwh.
- Time alignment (“end” by default) and full rotate/canonicalize before override remain unchanged.
- Keeps zero-diagnostics & safety (skip POST if BUY has 0.0 unless --allow-zero-buy).
- Sigen OAuth with encrypted-password flow + token cache.

Examples:
  python3 amber_to_sigen23.py \
    --station-id 92025781200321 \
    --tz Australia/Adelaide \
    --interval 30 \
    --align end \
    --advanced-price predicted \
    --use-current \
    --dry-run
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import time
from collections import deque
from typing import Dict, List, Tuple, Optional

import requests

AMBER_BASE = "https://api.amber.com.au/v1"
SIGEN_TOKEN_URL = "https://api-aus.sigencloud.com/auth/oauth/token"
SIGEN_SAVE_URL_DEFAULT = "https://api-aus.sigencloud.com/device/stationelecsetprice/save"

# ---- Zero diagnostics buckets (BUY only) ----
ZERO_EVENTS_BUY: List[str] = []  # e.g., "forecast 22:30-23:00", "current 23:00-23:30", "postbuild 01:00-01:30"

# ---------------- Amber helpers ----------------

def get_site_id(token: str) -> str:
    """Return the first ACTIVE site id for the Amber account (fallback to first)."""
    r = requests.get(f"{AMBER_BASE}/sites", headers={"Authorization": f"Bearer {token}"}, timeout=30)
    r.raise_for_status()
    sites = r.json()
    if not sites:
        raise RuntimeError("Amber returned no sites for your token.")
    site = next((s for s in sites if s.get("status") == "ACTIVE"), sites[0])
    return site["id"]

def fetch_amber_prices(token: str, site_id: str, start_date: str, end_date: str,
                       resolution_minutes: int) -> List[dict]:
    params = {"startDate": start_date, "endDate": end_date, "resolution": str(resolution_minutes)}
    r = requests.get(f"{AMBER_BASE}/sites/{site_id}/prices", params=params,
                     headers={"Authorization": f"Bearer {token}"}, timeout=60)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict) and "intervals" in data:
        return data["intervals"]
    return data

def fetch_amber_current_triplet_prefer5(token: str, site_id: str) -> Optional[List[dict]]:
    """
    Fetch current & immediate-next rows from /prices/current.
    ALWAYS try 5-minute first (best fidelity: previous=0,next=1), then fall back to 30-minute.
    Returns a list (1–2 rows) or None.
    """
    url = f"{AMBER_BASE}/sites/{site_id}/prices/current"

    def _get(res):
        params = {"previous": "1", "next": "1", "resolution": str(res)}
        r = requests.get(url, params=params, headers={"Authorization": f"Bearer {token}"}, timeout=20)
        if r.status_code == 204:
            return None
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list) and data:
            return data
        if isinstance(data, dict) and data:
            return [data]
        return None

    trip = _get(5)
    if not trip:
        trip = _get(30)
    return trip

# ---------------- Slot building & mapping (UTC-normalized) ----------------

def floor_to_step(ts: dt.datetime, step_min: int) -> dt.datetime:
    minute = (ts.minute // step_min) * step_min
    return ts.replace(second=0, microsecond=0, minute=minute)

def build_window(now_local: dt.datetime, step_min: int,
                 total_minutes: int = 1440) -> List[Tuple[dt.datetime, dt.datetime]]:
    """Build a list of [start,end) UTC time ranges covering now -> now+24h in step_min steps."""
    start_local = floor_to_step(now_local, step_min)
    start_utc = start_local.astimezone(dt.timezone.utc)
    out: List[Tuple[dt.datetime, dt.datetime]] = []
    t = start_utc
    end = start_utc + dt.timedelta(minutes=total_minutes)
    step = dt.timedelta(minutes=step_min)
    while t < end:
        out.append((t, t + step))  # UTC
        t += step
    return out

def parse_iso_utc(s: str) -> dt.datetime:
    d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d.astimezone(dt.timezone.utc)

def index_prices_by_start_utc(amber_rows: List[dict], step_min: int) -> Dict[dt.datetime, dict]:
    m: Dict[dt.datetime, dict] = {}
    for row in amber_rows:
        st = row.get("startTime")
        if not st:
            continue
        try:
            t = parse_iso_utc(st)
            t = floor_to_step(t, step_min)  # squash any ':01Z' drift
            m[t] = row
        except Exception:
            continue
    return m

def index_prices_by_end_utc(amber_rows: List[dict], step_min: int) -> Dict[dt.datetime, dict]:
    m: Dict[dt.datetime, dict] = {}
    for row in amber_rows:
        et = row.get("endTime")
        if not et:
            continue
        try:
            t = parse_iso_utc(et)
            t = floor_to_step(t, step_min)
            m[t] = row
        except Exception:
            continue
    return m

def get_value(row: Optional[dict], key: str) -> Optional[float]:
    """Return float value for 'key'; supports dotted paths e.g. 'advancedPrice.predicted'."""
    if not row:
        return None
    try:
        if "." in key:
            outer, inner = key.split(".", 1)
            v = row.get(outer, {}).get(inner)
        else:
            v = row.get(key)
        if v is None:
            return None
        return float(v)
    except Exception:
        return None

# ---------------- Baseline / carry-forward helpers ----------------

def last_known_before(
    rows: List[dict], key: str, step_min: int, align: str, now_utc: dt.datetime
) -> Optional[float]:
    """Find the most recent available value strictly before 'now' (UTC) using chosen alignment."""
    index = index_prices_by_end_utc(rows, step_min) if align == "end" \
            else index_prices_by_start_utc(rows, step_min)
    prev_keys = [t for t in index.keys() if t < now_utc]
    if not prev_keys:
        return None
    t = max(prev_keys)
    return get_value(index[t], key)

# ---------------- Series building / rotation / labels ----------------

def build_series_for_window(
    slots_utc: List[Tuple[dt.datetime, dt.datetime]],
    tz: dt.tzinfo,
    rows: List[dict],
    key: str,
    step_min: int,
    align: str = "start",             # "start" or "end"
    initial_last: Optional[float] = None,  # baseline to avoid leading zeros / tail gaps
) -> List[Tuple[str, float]]:
    if align == "end":
        by_key = index_prices_by_end_utc(rows, step_min)
    else:
        by_key = index_prices_by_start_utc(rows, step_min)

    out: List[Tuple[str, float]] = []
    last = 0.0 if initial_last is None else float(initial_last)

    for (t0_utc, t1_utc) in slots_utc:
        anchor = t0_utc if align == "start" else t1_utc
        row = by_key.get(anchor)
        val = get_value(row, key) if row else None
        if val is not None:
            last = val
        t0_local = t0_utc.astimezone(tz)
        t1_local = t1_utc.astimezone(tz)
        out.append((f"{t0_local.strftime('%H:%M')}-{t1_local.strftime('%H:%M')}", round(last, 2)))
    return out

def rotate_series_to_midnight(series: List[Tuple[str, float]]) -> List[Tuple[str, float]]:
    prefix = "00:00-"
    idx00 = next((i for i, (tr, _) in enumerate(series) if tr.startswith(prefix)), None)
    if idx00 is None:
        return series
    return series[idx00:] + series[:idx00]

def canonicalize_series_to_day(series: List[Tuple[str, float]], step_min: int) -> List[Tuple[str, float]]:
    out: List[Tuple[str, float]] = []
    for i, (_, price) in enumerate(series):
        start_min = i * step_min
        end_min = (i + 1) * step_min
        sh, sm = divmod(start_min, 60)
        eh, em = divmod(end_min, 60)
        s_lbl = f"{sh:02d}:{sm:02d}"
        e_lbl = "24:00" if end_min == 1440 else f"{eh:02d}:{em:02d}"
        out.append((f"{s_lbl}-{e_lbl}", price))
    return out

def shift_series(series: List[Tuple[str, float]], slots: int) -> List[Tuple[str, float]]:
    """Rotate series by N slots after pricing (positive = later, negative = earlier)."""
    if not slots:
        return series
    dq = deque(series)
    dq.rotate(slots)
    return list(dq)

def _lookup_price_by_label(series: List[Tuple[str, float]], label: str) -> Optional[float]:
    """Find price by human label; robust to '-00:00' vs '-24:00' and stray spaces."""
    def _norm(s: str) -> str:
        s = s.strip()
        if s.endswith("-00:00"):
            s = s[:-5] + "-24:00"
        return s
    want = _norm(label)
    for tr, p in series:
        if _norm(tr) == want:
            return p
    want_start = want.split("-", 1)[0]
    for tr, p in series:
        if tr.split("-", 1)[0] == want_start:
            return p
    return None

# ---------------- Sigen OAuth helpers (supports SIGEN_PASS_ENC) ----------------

def cache_path_for(user: str) -> str:
    base = os.path.join(os.path.expanduser("~"), ".cache", "amber_to_sigen")
    os.makedirs(base, exist_ok=True)
    key = hashlib.sha256(user.encode("utf-8")).hexdigest()[:16]
    return os.path.join(base, f"sigen_{key}.json")

def load_cached_tokens(user: str):
    try:
        p = cache_path_for(user)
        if not os.path.exists(p):
            return None
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def save_cached_tokens(user: str, tok: dict):
    p = cache_path_for(user)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(tok, f)

def token_from_response(j: dict) -> dict:
    if not isinstance(j, dict):
        raise RuntimeError(f"Sigen token error: non-JSON/unknown body: {repr(j)[:400]}")
    data = j.get("data")
    if isinstance(data, dict) and ("access_token" in data or "token" in data):
        access = data.get("access_token") or data.get("token")
        refresh = data.get("refresh_token", "")
        ttype = data.get("token_type", "Bearer")
        expires_in = int(data.get("expires_in", 3600))
        return {"access_token": access, "refresh_token": refresh, "token_type": ttype,
                "expires_at": time.time() + expires_in - 60}
    if "access_token" in j or "token" in j:
        access = j.get("access_token") or j.get("token")
        refresh = j.get("refresh_token", "")
        ttype = j.get("token_type", "Bearer")
        expires_in = int(j.get("expires_in", 3600))
        return {"access_token": access, "refresh_token": refresh, "token_type": ttype,
                "expires_at": time.time() + expires_in - 60}
    code = j.get("code")
    msg = j.get("msg") or j.get("error_description") or j.get("error") or "unknown"
    raise RuntimeError(f"Sigen token error: code={code} msg={msg} body={json.dumps(j)[:400]}")

def sigen_password_grant_encrypted(username: str, enc_password_b64: str, user_device_id: str) -> dict:
    headers = {
        "Authorization": "Basic c2lnZW46c2lnZW4=",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    data = {
        "username": username,
        "password": enc_password_b64,
        "scope": "server",
        "grant_type": "password",
        "userDeviceId": user_device_id
    }
    r = requests.post(SIGEN_TOKEN_URL, data=data, headers=headers, timeout=30)
    r.raise_for_status()
    return token_from_response(r.json())

def sigen_refresh(refresh_token: str) -> dict:
    headers = {
        "Authorization": "Basic c2lnZW46c2lnZW4=",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    data = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    r = requests.post(SIGEN_TOKEN_URL, data=data, headers=headers, timeout=30)
    r.raise_for_status()
    return token_from_response(r.json())

def ensure_sigen_headers(user: str, user_device_id: str) -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if not user:
        raise RuntimeError("SIGEN_USER is required (env or --sigen-user).")
    cached = load_cached_tokens(user)
    now = time.time()
    if cached and cached.get("expires_at", 0) > now and cached.get("access_token"):
        headers["Authorization"] = f"{cached.get('token_type','Bearer')} {cached['access_token']}"
        return headers
    if cached and cached.get("refresh_token"):
        try:
            newtok = sigen_refresh(cached["refresh_token"])
            save_cached_tokens(user, newtok)
            headers["Authorization"] = f"{newtok.get('token_type','Bearer')} {newtok['access_token']}"
            return headers
        except Exception:
            pass
    enc_pw = os.environ.get("SIGEN_PASS_ENC")
    if enc_pw:
        newtok = sigen_password_grant_encrypted(user, enc_pw, user_device_id)
        save_cached_tokens(user, newtok)
        headers["Authorization"] = f"{newtok.get('token_type','Bearer')} {newtok['access_token']}"
        return headers
    raise RuntimeError("No way to authenticate: set SIGEN_PASS_ENC (encrypted password) and SIGEN_DEVICE_ID.")

# ---------------- Utilities ----------------

def parse_boolish_env(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")

# ---------------- Main flow ----------------

def main():
    ap = argparse.ArgumentParser(description="Amber -> Sigen staticPricing (now->+24h)")
    ap.add_argument("--amber-token", default=os.environ.get("AMBER_TOKEN"))
    ap.add_argument("--site-id")
    ap.add_argument("--tz", default="Australia/Adelaide")
    ap.add_argument("--interval", type=int, default=int(os.environ.get("INTERVAL", "30")),
                    choices=[5, 30], help="Slot size & Amber resolution (minutes)")
    ap.add_argument("--align", default="end", choices=["start", "end"],
                    help="Align Amber price rows to slot start or end when labeling (Amber app tends to be 'end').")
    ap.add_argument("--slot-shift", type=int, default=0,
                    help="Rotate series by N slots after pricing (positive=later, negative=earlier).")
    ap.add_argument("--advanced-price", choices=["low", "predicted", "high"],
                    help="Use advancedPrice.<field> instead of perKwh for BUY price.")
    # Default USE_CURRENT = True unless explicitly disabled via env or CLI
    env_use_current = parse_boolish_env("USE_CURRENT", True)
    ap.add_argument("--use-current", dest="use_current", action="store_true", default=env_use_current)
    ap.add_argument("--no-use-current", dest="use_current", action="store_false",
                    help="Disable /prices/current override of active slot.")
    ap.add_argument("--station-id", type=int, required=True)
    ap.add_argument("--plan-name", default="SAPN TOU")
    ap.add_argument("--sigen-url", default=os.environ.get("SIGEN_SAVE_URL", SIGEN_SAVE_URL_DEFAULT))
    ap.add_argument("--sigen-user", default=os.environ.get("SIGEN_USER"))
    ap.add_argument("--device-id", default=os.environ.get("SIGEN_DEVICE_ID", "1756353655250"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-zero-buy", action="store_true",
                    help="Allow POST even if final BUY contains 0.0 (unsafe).")
    args = ap.parse_args()

    if not args.amber_token:
        ap.error("Missing Amber token (env AMBER_TOKEN or --amber-token).")

    step_min = args.interval
    # Time zone
    try:
        import zoneinfo  # Python 3.9+
        tz = zoneinfo.ZoneInfo(args.tz)
    except Exception:
        tz = dt.datetime.now().astimezone().tzinfo

    now_local = dt.datetime.now(tz)
    now_utc = dt.datetime.now(dt.timezone.utc)

    # Build slots for the next 24h window from 'now'
    slots = build_window(now_local, step_min=step_min, total_minutes=1440)

    # Human label for the "active" slot from now_local
    active_start_local = floor_to_step(now_local, step_min)
    active_end_local = active_start_local + dt.timedelta(minutes=step_min)
    current_label = f"{active_start_local.strftime('%H:%M')}-{active_end_local.strftime('%H:%M')}"

    # Fetch Amber bulk prices today + tomorrow
    today = now_local.date().strftime("%Y-%m-%d")
    tomorrow = (now_local.date() + dt.timedelta(days=1)).strftime("%Y-%m-%d")

    site_id = args.site_id or get_site_id(args.amber_token)
    rows = fetch_amber_prices(args.amber_token, site_id,
                              start_date=today, end_date=tomorrow,
                              resolution_minutes=step_min)

    # Keys and baselines (carry forward if missing)
    buy_key = f"advancedPrice.{args.advanced_price}" if args.advanced_price else "perKwh"
    buy_baseline = last_known_before(rows, buy_key, step_min, args.align, now_utc)
    sell_baseline = last_known_before(rows, "spotPerKwh", step_min, args.align, now_utc)

    # Build series with baseline (prevents <nil>/0.0 at head/tail if data isn't published yet)
    buy_ranges = build_series_for_window(slots, tz, rows, key=buy_key,
                                         step_min=step_min, align=args.align,
                                         initial_last=buy_baseline)
    sell_ranges = build_series_for_window(slots, tz, rows, key="spotPerKwh",
                                          step_min=step_min, align=args.align,
                                          initial_last=sell_baseline)

    # Optional fine-tune shift (after values are picked)
    buy_ranges = shift_series(buy_ranges, args.slot_shift)
    sell_ranges = shift_series(sell_ranges, args.slot_shift)

    # Diagnostics: record any zeros from forecast build (BUY only)
    for tr, p in buy_ranges:
        if p == 0.0:
            ZERO_EVENTS_BUY.append(f"forecast {tr}")

    # ---- Compute a pending override target from /prices/current (prefer 5-min, fallback 30-min) ----
    pending_override = None  # (target_label, buy_value, sell_value)
    if args.use_current:
        trip = fetch_amber_current_triplet_prefer5(args.amber_token, site_id)

        def pick_buy(row: dict) -> Optional[float]:
            if not row:
                return None
            if args.advanced_price:
                adv = row.get("advancedPrice") or {}
                v = adv.get(args.advanced_price)
                if v is not None:
                    return float(v)
            v = row.get("perKwh")
            return float(v) if v is not None else None

        def pick_sell(row: dict) -> Optional[float]:
            if not row:
                return None
            v = row.get("spotPerKwh")
            return float(v) if v is not None else None

        def local_start_end(row: dict) -> Optional[Tuple[dt.datetime, dt.datetime, str]]:
            try:
                st_l = parse_iso_utc(row["startTime"]).astimezone(tz)
                en_l = parse_iso_utc(row["endTime"]).astimezone(tz)
                lbl = f"{st_l.strftime('%H:%M')}-{en_l.strftime('%H:%M')}"
                return st_l, en_l, lbl
            except Exception:
                return None

        # --- DEBUG: dump raw triplet key fields ---
        if trip:
            try:
                dbg_rows = []
                for r in trip:
                    t = r.get("type")
                    st = r.get("startTime")
                    en = r.get("endTime")
                    per = r.get("perKwh")
                    spot = r.get("spotPerKwh")
                    adv = r.get("advancedPrice")
                    dbg_rows.append({"type": t, "startTime": st, "endTime": en,
                                     "perKwh": per, "spotPerKwh": spot, "advancedPrice": adv})
                print("[amber2sigen] /prices/current triplet (raw key fields):", file=sys.stderr)
                print(json.dumps(dbg_rows, indent=2), file=sys.stderr)
            except Exception:
                pass

            # Rank rows: Current > Forecast > Actual (closest we’ll get to “right now”)
            def rank_type(t: str) -> int:
                if t == "CurrentInterval":
                    return 0
                if t == "ForecastInterval":
                    return 1
                return 2  # ActualInterval last

            chosen = None
            if trip:
                # If multiple rows share the same type rank, prefer the one whose START is
                # closest to the active slot’s start.
                def _dist(row):
                    try:
                        st = parse_iso_utc(row["startTime"]).astimezone(tz)
                        return abs((st - active_start_local).total_seconds())
                    except Exception:
                        return 10**9

                trip_sorted = sorted(trip, key=lambda r: (rank_type(r.get("type","")), _dist(r)))
                chosen = trip_sorted[0] if trip_sorted else None

            if chosen:
                se = local_start_end(chosen)
                chosen_buy = pick_buy(chosen)
                chosen_sell = pick_sell(chosen)

                if se:
                    st_l, en_l, lbl = se
                    if step_min == 30:
                        # Enclosing 30-min slot label for the chosen 5-min interval
                        slot_start = floor_to_step(st_l, 30)
                        slot_end = slot_start + dt.timedelta(minutes=30)
                        target_label = f"{slot_start.strftime('%H:%M')}-{slot_end.strftime('%H:%M')}"
                    else:
                        # step_min == 5 → the 5-min label itself
                        target_label = lbl

                    pending_override = (target_label, chosen_buy, chosen_sell)

                    # Human-friendly summary (with advanced→perKwh fallback for BUY)
                    labels, buy_vals, sell_vals = [], [], []
                    for r in trip:
                        try:
                            st = parse_iso_utc(r["startTime"]).astimezone(tz).strftime("%H:%M")
                            en = parse_iso_utc(r["endTime"]).astimezone(tz).strftime("%H:%M")
                            lbl2 = f"{st}-{en}"
                        except Exception:
                            lbl2 = "<unknown>"

                        # BUY: if --advanced-price use advancedPrice.<field> with fallback to perKwh
                        if args.advanced_price:
                            adv = (r.get("advancedPrice") or {})
                            b = adv.get(args.advanced_price)
                            if b is None:
                                b = r.get("perKwh")
                        else:
                            b = r.get("perKwh")

                        # SELL
                        s = r.get("spotPerKwh")

                        labels.append(lbl2)
                        buy_vals.append(None if b is None else round(float(b), 2))
                        sell_vals.append(None if s is None else round(float(s), 2))

                    print("[amber2sigen] Current window BUY slots = " +
                          ", ".join(f"{l}:{('<nil>' if b is None else b)}" for l, b in zip(labels, buy_vals)),
                          file=sys.stderr)
                    print("[amber2sigen] Current window SELL slots = " +
                          ", ".join(f"{l}:{('<nil>' if s is None else s)}" for l, s in zip(labels, sell_vals)),
                          file=sys.stderr)
                else:
                    print("[amber2sigen] /current row lacked parseable start/end; skipping override.", file=sys.stderr)
            else:
                print("[amber2sigen] No suitable /current row found for active slot override.", file=sys.stderr)

    # ---- Rotate + canonicalize to midnight day labels BEFORE applying override ----
    buy_ranges = rotate_series_to_midnight(buy_ranges)
    sell_ranges = rotate_series_to_midnight(sell_ranges)
    buy_ranges = canonicalize_series_to_day(buy_ranges, step_min)
    sell_ranges = canonicalize_series_to_day(sell_ranges, step_min)

    # ---- Apply pending override by exact label in the FINAL series ----
    if pending_override:
        target_label, chosen_buy, chosen_sell = pending_override
        # BUY
        idx = next((i for i, (tr, _) in enumerate(buy_ranges) if tr == target_label), None)
        if idx is not None:
            old = buy_ranges[idx][1]
            if chosen_buy is None or chosen_buy == 0.0:
                ZERO_EVENTS_BUY.append(f"current {target_label}")
                print(f"[amber2sigen] Skipping BUY current override (zero/missing) for {target_label}; "
                      f"keeping forecast {old}", file=sys.stderr)
            else:
                buy_ranges[idx] = (buy_ranges[idx][0], round(float(chosen_buy), 2))
                print(f"[amber2sigen] BUY current override @ {target_label}: {old} → {buy_ranges[idx][1]}",
                      file=sys.stderr)
        else:
            print(f"[amber2sigen] Could not locate BUY target label {target_label} in final series.", file=sys.stderr)

        # SELL
        idx = next((i for i, (tr, _) in enumerate(sell_ranges) if tr == target_label), None)
        if idx is not None:
            old = sell_ranges[idx][1]
            if chosen_sell is None:
                print(f"[amber2sigen] Skipping SELL current override (missing) for {target_label}; "
                      f"keeping forecast {old}", file=sys.stderr)
            else:
                sell_ranges[idx] = (sell_ranges[idx][0], round(float(chosen_sell), 2))
                print(f"[amber2sigen] SELL current override @ {target_label}: {old} → {sell_ranges[idx][1]}",
                      file=sys.stderr)
        else:
            print(f"[amber2sigen] Could not locate SELL target label {target_label} in final series.", file=sys.stderr)

    # Postbuild zero scan (final series)
    for tr, p in buy_ranges:
        if p == 0.0:
            ZERO_EVENTS_BUY.append(f"postbuild {tr}")

    # End-of-run diagnostics: active slot BUY/SELL in final series
    print(f"[amber2sigen] Active slot BUY {current_label} = "
          f"{_lookup_price_by_label(buy_ranges, current_label) or '<not found>'}", file=sys.stderr)
    print(f"[amber2sigen] Active slot SELL {current_label} = "
          f"{_lookup_price_by_label(sell_ranges, current_label) or '<not found>'}", file=sys.stderr)

    # Summarize zero events
    if ZERO_EVENTS_BUY:
        uniq = sorted(set(ZERO_EVENTS_BUY))
        print(f"[amber2sigen] BUY perKwh saw 0.0 in: {', '.join(uniq)}", file=sys.stderr)
    else:
        print("[amber2sigen] BUY perKwh: no 0.0 placeholders detected.", file=sys.stderr)

    # Build payload
    payload = {
        "stationId": args.station_id,
        "priceMode": 1,
        "buyPrice": {
            "dynamicPricing": None,
            "staticPricing": {
                "providerName": "Amber",
                "tariffCode": "",
                "tariffName": "",
                "currencyCode": "Cent",
                "subAreaName": "",
                "planName": f"{args.plan_name} {step_min}-min",
                "combinedPrices": [
                    {
                        "monthRange": "01-12",
                        "weekPrices": [
                            {
                                "weekRange": "1-7",
                                "timeRange": [{"timeRange": tr, "price": p} for tr, p in buy_ranges]
                            }
                        ]
                    }
                ]
            }
        },
        "sellPrice": {
            "dynamicPricing": None,
            "staticPricing": {
                "providerName": "Amber",
                "tariffCode": "",
                "tariffName": "",
                "currencyCode": "Cent",
                "subAreaName": "",
                "planName": f"{args.plan_name} {step_min}-min",
                "combinedPrices": [
                    {
                        "monthRange": "01-12",
                        "weekPrices": [
                            {
                                "weekRange": "1-7",
                                "timeRange": [{"timeRange": tr, "price": p} for tr, p in sell_ranges]
                            }
                        ]
                    }
                ]
            }
        }
    }

    headers = ensure_sigen_headers(args.sigen_user, args.device_id)

    # Show what we will send
    print(json.dumps(payload, indent=2))

    # Final safety: only skip POST if final BUY contains a 0.0 (unless override)
    final_has_zero = any(p == 0.0 for _, p in buy_ranges)
    if args.dry_run or (final_has_zero and not args.allow_zero_buy):
        if final_has_zero and not args.allow_zero_buy:
            print("[amber2sigen] Final BUY series still contains 0.0 → skipping POST to Sigen.", file=sys.stderr)
        else:
            print("[amber2sigen] --dry-run set → skipping POST to Sigen.", file=sys.stderr)
        return

    # POST
    r = requests.post(args.sigen_url, headers=headers, json=payload, timeout=60)
    try:
        r.raise_for_status()
    except Exception:
        print(f"Error from Sigen: HTTP {r.status_code}\n{r.text}", file=sys.stderr)
        raise
    print("Sigen response:", r.status_code, r.text)

if __name__ == "__main__":
    main()