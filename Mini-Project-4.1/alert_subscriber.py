#!/usr/bin/env python3
"""Mini Project 4.1, Part A - threshold alerting subscriber.

Subscribes at QoS 1 to a wildcard (default factory/+/temperature) and prints an ALERT line only when a numeric reading
exceeds the threshold (default 90.0). Non-numeric payloads such as the status messages "online"/"offline" are ignored, so
the subscription can be widened to factory/line3/+ (lab task 1) without touching the threshold logic.
"""
import argparse
import sys
import threading
import time

import paho.mqtt.client as mqtt


def stamp():
    t = time.time()
    return time.strftime("%H:%M:%S", time.localtime(t)) + f".{int((t % 1) * 1000):03d}"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--broker", default="localhost")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--client-id", default="alert-subscriber")
    ap.add_argument("--topic", default="factory/+/temperature")
    ap.add_argument("--threshold", type=float, default=90.0)
    ap.add_argument("--duration", type=float, default=0)
    a = ap.parse_args()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=a.client_id)
    stats = {"readings": 0, "alerts": 0}

    def on_connect(c, userdata, flags, reason_code, properties):
        print(f"[{stamp()}] ALERTER   connected ({reason_code}); subscribing '{a.topic}' at QoS 1, threshold {a.threshold}", flush=True)
        c.subscribe(a.topic, qos=1)

    def on_message(c, userdata, msg):
        try:
            value = float(msg.payload.decode())
        except ValueError:
            return                                                # status text, not a reading
        stats["readings"] += 1
        if value > a.threshold:
            stats["alerts"] += 1
            print(f"[{stamp()}] ALERT     {msg.topic} = {value} exceeds {a.threshold}", flush=True)

    client.on_connect, client.on_message = on_connect, on_message
    try:
        client.connect(a.broker, a.port, keepalive=60)
    except OSError as e:
        sys.exit(f"cannot reach broker {a.broker}:{a.port}: {e}")
    client.loop_start()
    try:
        time.sleep(a.duration) if a.duration else threading.Event().wait()
    except KeyboardInterrupt:
        pass
    client.loop_stop()
    client.disconnect()
    print(f"[{stamp()}] ALERTER   stopped; {stats['readings']} numeric readings seen, {stats['alerts']} alerts", flush=True)


if __name__ == "__main__":
    main()
