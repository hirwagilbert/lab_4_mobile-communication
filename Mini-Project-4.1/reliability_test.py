#!/usr/bin/env python3
"""Mini Project 4.1 lab tasks 2 and 3 - what do the QoS levels actually buy you?

Task 2  Crash the publisher immediately after publishing its last reading (SIGKILL, no DISCONNECT), 30 trials per QoS level,
        in two variants: crash at once, and crash 50 ms later (after the packet has left the process).
Task 3  Intentionally unreliable network: the broker is stopped for 2 s in the middle of a 150-message run
        (publisher 20 msg/s, subscriber with a persistent QoS 1 session). Count lost readings at QoS 0 versus QoS 1.

Writes reliability_output.txt.   Run:  python reliability_test.py
"""
import os
import subprocess
import sys
import threading
import time

import paho.mqtt.client as mqtt

from broker_utils import Broker

HERE = os.path.dirname(os.path.abspath(__file__))
TOPIC = "factory/line3/temperature"
OUT = []


def say(msg=""):
    print(msg, flush=True)
    OUT.append(msg)


# ---------------------------------------------------------------- task 2
def task2(port=18834, trials=30):
    broker = Broker(port).start()
    got = {"n": 0}
    rx = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="rx2")
    rx.on_connect = lambda c, u, f, rc, p: c.subscribe(TOPIC, qos=2)
    rx.on_message = lambda c, u, m: got.__setitem__("n", got["n"] + 1)
    rx.connect("127.0.0.1", port)
    rx.loop_start()
    time.sleep(0.5)
    say("Task 2: publisher is SIGKILLed right after its last publish() call, 30 trials per cell")
    say(f"{'QoS':<5}{'crash immediately after publish()':>36}{'crash 50 ms after publish()':>32}")
    res = {}
    for qos in (0, 1, 2):
        row = []
        for grace in (0, 50):
            ok = 0
            for t in range(trials):
                before = got["n"]
                p = subprocess.run([sys.executable, os.path.join(HERE, "sensor_publisher.py"), "--port", str(port), "--qos", str(qos),
                                    "--crash-after", "1", "--crash-grace-ms", str(grace), "--seed", str(t)],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                assert p.returncode == -9, p.returncode
                time.sleep(0.12)
                ok += got["n"] > before
            row.append(ok)
        res[qos] = row
        say(f"{qos:<5}{f'{row[0]}/{trials} delivered':>36}{f'{row[1]}/{trials} delivered':>32}")
    rx.loop_stop(); rx.disconnect(); broker.cleanup()
    return res


# ---------------------------------------------------------------- task 3
def task3(qos, port=18835, n_msgs=150, rate=20.0, down_at=2.0, down_for=2.0):
    broker = Broker(port, persistence=True).start()
    seen, deliveries = set(), {"n": 0}

    rx = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="rx3", clean_session=False)
    rx.reconnect_delay_set(0.2, 0.5)
    rx.on_connect = lambda c, u, f, rc, p: c.subscribe(TOPIC, qos=1)
    def on_msg(c, u, m):
        deliveries["n"] += 1
        seen.add(int(m.payload))
    rx.on_message = on_msg
    rx.connect("127.0.0.1", port, keepalive=5)
    rx.loop_start()

    tx = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="tx3")
    tx.reconnect_delay_set(0.2, 0.5)
    tx.connect("127.0.0.1", port, keepalive=5)
    tx.loop_start()
    time.sleep(0.6)

    def outage():
        time.sleep(down_at)
        broker.stop(graceful=True)
        time.sleep(down_for)
        broker.start()
    threading.Thread(target=outage, daemon=True).start()

    refused = 0
    t0 = time.time()
    for seq in range(1, n_msgs + 1):
        info = tx.publish(TOPIC, str(seq), qos=qos)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            refused += 1                                   # client is offline: a QoS 0 message is dropped on the spot
        time.sleep(max(0, t0 + seq / rate - time.time()))
    time.sleep(4.0)                                        # let queued QoS 1 messages drain after reconnection
    lost = n_msgs - len(seen)
    tx.loop_stop(); tx.disconnect(); rx.loop_stop(); rx.disconnect(); broker.cleanup()
    return dict(qos=qos, sent=n_msgs, received=len(seen), lost=lost, dup=deliveries["n"] - len(seen), refused=refused)


if __name__ == "__main__":
    t2 = task2()
    say()
    say("Task 3: broker down for 2 s in the middle of a 150-message run (20 msg/s)")
    say(f"{'QoS':<5}{'sent':>6}{'received':>10}{'lost':>6}{'duplicates':>12}{'publish() said offline':>30}")
    for q in (0, 1):
        r = task3(q)
        say(f"{r['qos']:<5}{r['sent']:>6}{r['received']:>10}{r['lost']:>6}{r['dup']:>12}{r['refused']:>30}")
    with open(os.path.join(HERE, "reliability_output.txt"), "w") as f:
        f.write("\n".join(OUT) + "\n")
