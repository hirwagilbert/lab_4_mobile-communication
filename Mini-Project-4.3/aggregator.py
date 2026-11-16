#!/usr/bin/env python3
"""Mini Project 4.3 - aggregator / logger / alert subscriber.

ONE wildcard subscription (default "plant1/+/+") receives every reading and every status message of the plant.
  * every message is timestamped, printed and appended to a CSV log
  * the latest value, count, min and max are kept per topic in a dict that is updated in on_message
  * a summary table is printed every --summary-interval seconds
  * per-topic thresholds (thresholds.json) raise an ALERT on the rising edge and a CLEARED line when the value returns
  * a topic seen for the first time is announced as NEW TOPIC - nothing in the code names individual topics,
    so sensors added later are picked up with no code change
  * status topics (<plant>/<line>/status) are tracked separately; an "offline:*" payload is the Last Will of a dead sensor

Run:  python aggregator.py --duration 30
"""
import argparse
import csv
import json
import os
import signal
import threading
import time
from datetime import datetime

import paho.mqtt.client as mqtt

HERE = os.path.dirname(os.path.abspath(__file__))


def ts():
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


class Aggregator:
    def __init__(self, thresholds, csv_path):
        self.th = thresholds
        self.latest = {}            # topic -> dict(value, count, min, max, time, alert)
        self.status = {}            # status topic -> (payload, time, retained)
        self.alerts = 0
        self.lock = threading.Lock()
        self.csv = open(csv_path, "w", newline="")
        self.w = csv.writer(self.csv)
        self.w.writerow(["time", "topic", "payload", "qos", "retained", "event"])

    def threshold_for(self, topic):
        t = self.th["topics"].get(topic)
        if t is None:
            t = self.th["defaults_by_measurement"].get(topic.rsplit("/", 1)[-1])
        return t

    def log(self, topic, payload, qos, retained, event=""):
        self.w.writerow([datetime.now().isoformat(timespec="milliseconds"), topic, payload, qos, int(retained), event])
        self.csv.flush()

    def on_message(self, client, userdata, msg):
        payload = msg.payload.decode(errors="replace")
        tag = " [RETAINED]" if msg.retain else ""
        with self.lock:
            if msg.topic.endswith("/status"):
                self.status[msg.topic] = (payload, ts(), bool(msg.retain))
                flag = "  <-- LAST WILL received: sensor lost" if payload.startswith("offline") else ""
                print(f"[{ts()}] STATUS  {msg.topic} = {payload} qos={msg.qos}{tag}{flag}", flush=True)
                self.log(msg.topic, payload, msg.qos, msg.retain, "status")
                return
            try:
                v = float(payload)
            except ValueError:
                print(f"[{ts()}] IGNORED non-numeric payload on {msg.topic}: {payload!r}", flush=True)
                self.log(msg.topic, payload, msg.qos, msg.retain, "ignored")
                return
            new = msg.topic not in self.latest
            s = self.latest.setdefault(msg.topic, dict(value=v, count=0, min=v, max=v, time=ts(), alert=False))
            s.update(value=v, count=s["count"] + 1, min=min(s["min"], v), max=max(s["max"], v), time=ts())
            if new:
                print(f"[{ts()}] NEW TOPIC discovered: {msg.topic} (threshold {self.threshold_for(msg.topic)})", flush=True)
            print(f"[{ts()}] READING {msg.topic} = {v:.2f} qos={msg.qos}{tag}", flush=True)
            event = ""
            limit = self.threshold_for(msg.topic)
            if limit is not None:
                if v > limit and not s["alert"]:
                    s["alert"] = True
                    self.alerts += 1
                    event = "alert"
                    print(f"[{ts()}] ALERT   {msg.topic} = {v:.2f} exceeds {limit}", flush=True)
                elif v <= limit and s["alert"]:
                    s["alert"] = False
                    event = "cleared"
                    print(f"[{ts()}] CLEARED {msg.topic} = {v:.2f} back under {limit}", flush=True)
            self.log(msg.topic, payload, msg.qos, msg.retain, event)

    def summary(self, title="SUMMARY"):
        with self.lock:
            lines = [f"[{ts()}] ---- {title}: latest value per topic ----",
                     f"    {'topic':<28}{'latest':>8}{'n':>5}{'min':>8}{'max':>8}{'limit':>7}  state"]
            for t in sorted(self.latest):
                s = self.latest[t]
                lim = self.threshold_for(t)
                lines.append(f"    {t:<28}{s['value']:>8.2f}{s['count']:>5}{s['min']:>8.2f}{s['max']:>8.2f}"
                             f"{lim if lim is not None else '-':>7}  {'ALERT' if s['alert'] else 'ok'}")
            for t in sorted(self.status):
                lines.append(f"    {t:<28}{self.status[t][0]}")
            lines.append(f"    alerts raised so far: {self.alerts}")
        print("\n".join(lines), flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--broker", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--filter", default="plant1/+/+", help="the single wildcard subscription")
    ap.add_argument("--thresholds", default=os.path.join(HERE, "thresholds.json"))
    ap.add_argument("--csv", default=os.path.join(HERE, "readings_log.csv"))
    ap.add_argument("--summary-interval", type=float, default=5.0)
    ap.add_argument("--duration", type=float, default=0, help="seconds to run (0 = until Ctrl-C)")
    ap.add_argument("--client-id", default="plant1-aggregator")
    a = ap.parse_args()

    agg = Aggregator(json.load(open(a.thresholds)), a.csv)
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=a.client_id)
    c.on_message = agg.on_message
    c.on_connect = lambda cl, u, f, rc, p: cl.subscribe(a.filter, qos=1)
    c.on_subscribe = lambda cl, u, mid, rcs, p: print(f"[{ts()}] aggregator subscribed to '{a.filter}' (single wildcard, QoS 1)", flush=True)
    c.connect(a.broker, a.port, 60)
    c.loop_start()
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    t0 = time.time()
    nxt = t0 + a.summary_interval
    while not stop.is_set():
        if a.duration and time.time() - t0 >= a.duration:
            break
        if time.time() >= nxt:
            agg.summary()
            nxt += a.summary_interval
        stop.wait(0.1)
    agg.summary("FINAL SUMMARY")
    c.loop_stop()
    c.disconnect()


if __name__ == "__main__":
    main()
