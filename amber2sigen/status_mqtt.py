#!/usr/bin/env python3
import argparse, json, time
from datetime import datetime, timezone
import paho.mqtt.client as mqtt  # type: ignore

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", required=True)
    p.add_argument("--port", type=int, default=1883)
    p.add_argument("--username", default="")
    p.add_argument("--password", default="")
    p.add_argument("--prefix", default="amber2sigen")
    p.add_argument("--announce", action="store_true")
    p.add_argument("--state", default="")
    p.add_argument("--message", default="")
    args = p.parse_args()

    client = mqtt.Client()
    if args.username:
        client.username_pw_set(args.username, args.password)
    client.connect(args.host, args.port, 30)

    base = f"{args.prefix}/status"
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if args.announce:
        # Basic discovery-like config for a status sensor
        disc_topic = f"homeassistant/sensor/amber2sigen_status/config"
        cfg = {
            "name": "Amber2Sigen Status",
            "uniq_id": "amber2sigen_status",
            "stat_t": f"{base}",
            "json_attr_t": f"{base}",
            "ic": "mdi:transmission-tower",
        }
        client.publish(disc_topic, json.dumps(cfg), retain=True)

    if args.state:
        payload = {
            "state": args.state,
            "message": args.message,
            "ts": now
        }
        client.publish(base, json.dumps(payload), retain=True)

    client.disconnect()

if __name__ == "__main__":
    main()
