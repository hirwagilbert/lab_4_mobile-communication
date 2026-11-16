#!/usr/bin/env python3
"""Mini Project 4.1, Part A - simulated temperature sensor (MQTT publisher).

Client ID "line3-temp-sensor" publishes a random reading (60-95) to factory/line3/temperature at QoS 1.
  * Last Will and Testament registered BEFORE connecting: factory/line3/status = "offline", QoS 1, retained.
  * Immediately after connecting it publishes "online" (retained) to the same status topic.
  * The first reading is published with retain=True (so a late subscriber sees a value at once).
    Use --retain-all to retain every reading, so a late subscriber always sees the MOST RECENT one.

Examples
    python sensor_publisher.py                                  # defaults from the manual (5 s interval, localhost:1883)
    python sensor_publisher.py --broker test.mosquitto.org      # public test broker (never send sensitive data)
    python sensor_publisher.py --topic factory/line3/humidity --client-id line3-humidity-sensor \
           --status-topic factory/line3/humidity_status --low 40 --high 85          # second sensor (lab task 1)
"""
import argparse
import os
import random
import signal
import sys
import threading
import time

import paho.mqtt.client as mqtt


def stamp():
    t = time.time()
    return time.strftime("%H:%M:%S", time.localtime(t)) + f".{int((t % 1) * 1000):03d}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--broker", default="localhost")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--client-id", default="line3-temp-sensor")
    ap.add_argument("--topic", default="factory/line3/temperature")
    ap.add_argument("--status-topic", default="factory/line3/status")
    ap.add_argument("--interval", type=float, default=5.0, help="seconds between readings (manual: 5)")
    ap.add_argument("--qos", type=int, default=1, choices=[0, 1, 2])
    ap.add_argument("--keepalive", type=int, default=60, help="MQTT keep-alive in seconds")
    ap.add_argument("--low", type=float, default=60.0)
    ap.add_argument("--high", type=float, default=95.0)
    ap.add_argument("--seed", type=int, default=None, help="fix the random sequence for repeatable runs")
    ap.add_argument("--count", type=int, default=0, help="stop cleanly after this many readings (0 = run forever)")
    ap.add_argument("--retain-all", action="store_true", help="retain every reading, not only the first")
    ap.add_argument("--crash-after", type=int, default=0, help="demo: SIGKILL this process after N readings (no disconnect)")
    ap.add_argument("--crash-grace-ms", type=int, default=0, help="demo: wait this long after the last publish before the crash")
    ap.add_argument("--offline-on-exit", action="store_true", help="publish an explicit 'offline' before a CLEAN disconnect")
    a = ap.parse_args()

    if a.seed is not None:
        random.seed(a.seed)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=a.client_id)
    connected = threading.Event()

    def on_connect(c, userdata, flags, reason_code, properties):
        print(f"[{stamp()}] connected to {a.broker}:{a.port} as '{a.client_id}' (reason: {reason_code})", flush=True)
        connected.set()

    client.on_connect = on_connect
    # Step 4: register the Last Will BEFORE connecting.
    client.will_set(a.status_topic, payload="offline", qos=1, retain=True)
    try:
        client.connect(a.broker, a.port, keepalive=a.keepalive)
    except OSError as e:
        sys.exit(f"cannot reach broker {a.broker}:{a.port}: {e}")
    client.loop_start()
    if not connected.wait(10):
        sys.exit("no CONNACK from broker within 10 s")

    # Step 4: announce 'online' (retained) right after connecting.
    client.publish(a.status_topic, "online", qos=1, retain=True).wait_for_publish()
    print(f"[{stamp()}] status  -> {a.status_topic} = online (retained)", flush=True)

    n = 0
    try:
        while True:
            n += 1
            value = round(random.uniform(a.low, a.high), 1)
            retain = a.retain_all or n == 1                       # step 5: first reading retained
            info = client.publish(a.topic, str(value), qos=a.qos, retain=retain)
            print(f"[{stamp()}] publish #{n:<3} {a.topic} = {value}  (QoS {a.qos}{', retained' if retain else ''})", flush=True)
            if a.crash_after and n >= a.crash_after:
                if a.crash_grace_ms:
                    time.sleep(a.crash_grace_ms / 1000.0)
                os.kill(os.getpid(), signal.SIGKILL)               # ungraceful: no DISCONNECT packet is sent
            if a.qos > 0:
                info.wait_for_publish(5)
            if a.count and n >= a.count:
                break
            time.sleep(a.interval)
    except KeyboardInterrupt:
        pass
    if a.offline_on_exit:
        client.publish(a.status_topic, "offline", qos=1, retain=True).wait_for_publish()
    client.disconnect()                                           # clean disconnect: the broker does NOT send the will
    client.loop_stop()
    print(f"[{stamp()}] clean disconnect after {n} readings", flush=True)


if __name__ == "__main__":
    main()
