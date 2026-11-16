#!/usr/bin/env python3
"""Mini Project 4.3 - a subscriber that joins late, to show retained messages.

It subscribes to the same wildcard, prints every message with its retain flag, and exits after --duration seconds.
Messages that arrive at once with [RETAINED] were stored by the broker before this client connected."""
import argparse
import time
from datetime import datetime

import paho.mqtt.client as mqtt

ap = argparse.ArgumentParser()
ap.add_argument("--broker", default="127.0.0.1")
ap.add_argument("--port", type=int, default=1883)
ap.add_argument("--filter", default="plant1/+/+")
ap.add_argument("--duration", type=float, default=1.5)
a = ap.parse_args()
ts = lambda: datetime.now().strftime("%H:%M:%S.%f")[:-3]
t_conn = {}
count = {"retained": 0, "live": 0}


def on_msg(c, u, m):
    kind = "RETAINED" if m.retain else "live"
    count["retained" if m.retain else "live"] += 1
    print(f"[{ts()}] LATE-JOINER got {m.topic} = {m.payload.decode()}  [{kind}] +{(time.time() - t_conn['t']) * 1000:.0f} ms after connect", flush=True)


c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="late-joiner")
c.on_message = on_msg
c.on_connect = lambda cl, u, f, rc, p: cl.subscribe(a.filter, qos=1)
t_conn["t"] = time.time()
c.connect(a.broker, a.port, 60)
c.loop_start()
time.sleep(a.duration)
c.loop_stop()
c.disconnect()
print(f"[{ts()}] late joiner done: {count['retained']} retained, {count['live']} live", flush=True)
