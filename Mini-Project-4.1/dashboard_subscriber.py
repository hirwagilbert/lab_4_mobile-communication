#!/usr/bin/env python3
"""Mini Project 4.1, Part A - operator dashboard: prints a timestamped line for every event.

Subscribes (QoS 1) to factory/line3/temperature and factory/line3/status. Messages delivered from the broker's
retained store are labelled RETAINED, so a late joiner is easy to recognise in the log.
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
    ap.add_argument("--client-id", default="dashboard")
    ap.add_argument("--topics", nargs="+", default=["factory/line3/temperature", "factory/line3/status"])
    ap.add_argument("--duration", type=float, default=0, help="exit after N seconds (0 = run until Ctrl-C)")
    a = ap.parse_args()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=a.client_id)
    received = {"n": 0}

    def on_connect(c, userdata, flags, reason_code, properties):
        print(f"[{stamp()}] DASHBOARD connected ({reason_code}); subscribing {a.topics} at QoS 1", flush=True)
        c.subscribe([(t, 1) for t in a.topics])

    def on_message(c, userdata, msg):
        received["n"] += 1
        tag = "  [RETAINED]" if msg.retain else ""
        print(f"[{stamp()}] DASHBOARD {msg.topic:<30} {msg.payload.decode():<8} qos={msg.qos}{tag}", flush=True)

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
    print(f"[{stamp()}] DASHBOARD stopped; {received['n']} messages received", flush=True)


if __name__ == "__main__":
    main()
