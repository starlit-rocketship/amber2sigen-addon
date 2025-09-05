#!/opt/venv/bin/python3
import os, sys, json
import requests
from typing import List, Dict, Tuple, Optional
from dateutil import tz, parser as dtparse

SUPERVISOR = "http://supervisor/core/api"
TOKEN = os.environ.get("SUPERVISOR_TOKEN")  # provided when homeassistant_api: true

def _ha_get_state(entity_id: str) -> dict:
    if not TOKEN:
        raise RuntimeError("SUPERVISOR_TOKEN missing. Enable homeassistant_api: true in config.yaml.")
    url = f"{SUPERVISOR}/states/{entity_id}"
    r = requests.get(url, headers={"Authorization": f"Bearer {TOKEN}"}, timeout=10)
    r.raise_for_status()
    return r.json()

def _extract_forecasts(entity: dict) -> List[dict]:
    attrs = entity.get("attributes") or {}
    f = attrs.get("forecasts")
    if not isinstance(f, list):
        raise ValueError(f"No forecasts[] on entity {entity.get('entity_id')}")
    return f

def _to_local_timerange(start_iso: str, end_iso: str, tz_override: Optional[str]) -> str:
    start = dtparse.isoparse(start_iso)
    end = dtparse.isoparse(end_iso)
    if tz_override:
        tzinfo = tz.gettz(tz_override)
        start = start.astimezone(tzinfo)
        end = end.astimezone(tzinfo)
    else:
        start = start.astimezone()
        end = end.astimezone()
    return f"{start.strftime('%H:%M')}-{end.strftime('%H:%M')}"

def build_buy_sell_from_entities(
    import_entity_id: str,
    export_entity_id: Optional[str],
    tz_override: Optional[str],
) -> Tuple[List[Dict], List[Dict]]:
    imp = _ha_get_state(import_entity_id)
    imp_fc = _extract_forecasts(imp)

    exp_fc: Optional[List[dict]] = None
    if export_entity_id:
        try:
            exp = _ha_get_state(export_entity_id)
            exp_fc = _extract_forecasts(exp)
        except Exception as e:
            print(f"[ha_entities] WARN: export entity fetch failed ({e}), fallback to import.spot_per_kwh", file=sys.stderr)
            exp_fc = None

    buy_ranges: List[Dict] = []
    sell_ranges: List[Dict] = []

    exp_index = {}
    if exp_fc:
        for row in exp_fc:
            tr = _to_local_timerange(row["start_time"], row["end_time"], tz_override)
            exp_index[tr] = row

    for row in imp_fc:
        tr = _to_local_timerange(row["start_time"], row["end_time"], tz_override)

        # entity units are $/kWh → convert to cents/kWh
        per_kwh = float(row.get("per_kwh")) * 100.0
        spot = float(row.get("spot_per_kwh")) * 100.0

        buy_ranges.append({"timeRange": tr, "price": round(per_kwh, 2)})

        if exp_index and tr in exp_index:
            sell_cents = float(exp_index[tr].get("per_kwh")) * 100.0
        else:
            sell_cents = spot
        sell_ranges.append({"timeRange": tr, "price": round(sell_cents, 2)})

    return buy_ranges, sell_ranges

def main():
    use = os.environ.get("USE_HA_ENTITIES") == "1"
    if not use:
        print("[ha_entities] Not enabled (USE_HA_ENTITIES!=1).", file=sys.stderr)
        sys.exit(2)

    imp = os.environ.get("HA_IMPORT_ENTITY")
    exp = os.environ.get("HA_EXPORT_ENTITY") or None
    tz_override = os.environ.get("TZ_OVERRIDE") or None
    plan_name = os.environ.get("PLAN_NAME", "Amber (HA Entities)")

    if not imp:
        print("[ha_entities] HA_IMPORT_ENTITY is required when USE_HA_ENTITIES=1.", file=sys.stderr)
        sys.exit(2)

    buy, sell = build_buy_sell_from_entities(imp, exp, tz_override)

    common = {
        "providerName": "Amber",
        "tariffCode": "",
        "tariffName": "",
        "currencyCode": "Cent",
        "subAreaName": "",
        "planName": plan_name,
    }

    plan = {
        "buyPrice": {
            "dynamicPricing": None,
            "staticPricing": {
                **common,
                "combinedPrices": [
                    {"monthRange": "01-12", "weekPrices": [{"weekRange": "1-7", "timeRange": buy}]}
                ],
            },
        },
        "sellPrice": {
            "dynamicPricing": None,
            "staticPricing": {
                **common,
                "combinedPrices": [
                    {"monthRange": "01-12", "weekPrices": [{"weekRange": "1-7", "timeRange": sell}]}
                ],
            },
        },
    }

    print(json.dumps(plan))

if __name__ == "__main__":
    main()
