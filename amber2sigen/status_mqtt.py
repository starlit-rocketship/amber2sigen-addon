#!/opt/venv/bin/python3
import argparse
import json
import socket
import time
from paho.mqtt import client as mqtt

DISCOVERY_COMPONENT = "sensor"
DISCOVERY_DEVICE_CLASS = None  # plain sensor
DISCOVERY_STATE_CLASS = None
AVAIL_TOPIC_SUFFIX = "availability"
STATE_TOPIC_SUFFIX = "state"
ATTR_TOPIC_SUFFIX = "attributes"

def make_client(host, port, username=None, password=None, client_id="amber2sigen-addon"):
    # Use Callback API v2 to avoid the deprecation warning in paho-mqtt >=2.0
    client = mqtt.Client(
        client_id=client_id,
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        clean_session=True,
    )
    if username or password:
        client.username_pw_set(username or "", password or "")
    client.connect(host, int(port), keepalive=60)
    return client

def discovery_payload(node_id, name, state_topic, availability_topic, attr_topic, uniq_id):
    p = {
        "name": name,
        "uniq_id": uniq_id,
        "stat_t": state_topic,
        "avty_t": availability_topic,
        "json_attr_t": attr_topic,
        "qos": 0,
        "device": {
            "identifiers": [node_id],
            "manufacturer": "starlit-rocketship",
            "model": "Amber2Sigen Add-on",
            "name": "Amber2Sigen",
        },
    }
    if DISCOVERY_DEVICE_CLASS:
        p["dev_cla"] = DISCOVERY_DEVICE_CLASS
    if DISCOVERY_STATE_CLASS:
        p["stat_cla"] = DISCOVERY_STATE_CLASS
    return p

def announce(broker, prefix, username=None, password=None, port=1883):
    node_id = f"{prefix}_node"
    base = f"homeassistant/{DISCOVERY_COMPONENT}/{prefix}"
    state_topic = f"{prefix}/{STATE_TOPIC_SUFFIX}"
    availability_topic = f"{prefix}/{AVAIL_TOPIC_SUFFIX}"
    attr_topic = f"{prefix}/{ATTR_TOPIC_SUFFIX}"
    uniq_id = f"{prefix}_status"

    client = make_client(broker, port, username, password)
    topic = f"{base}/config"
    payload = discovery_payload(
        node_id=node_id,
        name="Amber2Sigen Status",
        state_topic=state_topic,
        availability_topic=availability_topic,
        attr_topic=attr_topic,
        uniq_id=uniq_id,
    )
    client.publish(topic, json.dumps(payload), retain=True)
    client.publish(availability_topic, "online", retain=True)
    client.disconnect()

def publish_state(broker, prefix, state, message, username=None, password=None, port=1883):
    state_topic = f"{prefix}/{STATE_TOPIC_SUFFIX}"
    availability_topic = f"{prefix}/{AVAIL_TOPIC_SUFFIX}"
    attr_topic = f"{prefix}/{ATTR_TOPIC_SUFFIX}"

    attrs = {
        "message": message,
        "hostname": socket.gethostname(),
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    client = make_client(broker, port, username, password)
    client.publish(state_topic, state, retain=True)
    client.publish(attr_topic, json.dumps(attrs), retain=True)
    client.publish(availability_topic, "online", retain=True)
    client.disconnect()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", default=1883, type=int)
    ap.add_argument("--username", default="")
    ap.add_argument("--password", default="")
    ap.add_argument("--prefix", default="amber2sigen")
    ap.add_argument("--announce", action="store_true")
    ap.add_argument("--state", choices=["running", "valid", "failed"])
    ap.add_argument("--message", default="")
    args = ap.parse_args()

    if args.announce:
        announce(args.host, args.prefix, args.username, args.password, args.port)
    else:
        publish_state(args.host, args.prefix, args.state, args.message, args.username, args.password, args.port)

if __name__ == "__main__":
    main()
