#!/usr/bin/env python3
"""Mini Project 4.3 - simulated plant sensor (one process = one publisher on one topic).

Topic hierarchy:  plant1/<line>/<measurement>      e.g. plant1/lineA/temperature
Status topic:     plant1/<line>/status             (LWT "offline", retained)  - only when --lwt is given

Examples:
    python sensor.py --line lineA --kind temperature --interval 0.5
    python sensor.py --line lineB --kind temperature --interval 0.6 --lwt --retain
    python sensor.py --line lineB --kind vibration --spike-readings 4,5

Every reading is published at QoS 1.  With --retain each reading is a retained message, so a late subscriber
immediately receives the latest value of the topic.  With --lwt the client registers a Last Will before connecting.
"""
import argparse
import random
import signal
import sys
import time

import paho.mqtt.client as mqtt

KINDS = {  # kind: (unit, normal mean, normal sigma, default spike value)
    "temperature": ("C", 70.0, 1.5, 91.0),
    "vibration": ("mm/s", 3.0, 0.4, 9.5),
}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--broker", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--plant", default="plant1")
    ap.add_argument("--line", required=True)
    ap.add_argument("--kind", required=True, choices=list(KINDS))
    ap.add_argument("--interval", type=float, default=1.0, help="seconds between readings")
    ap.add_argument("--qos", type=int, default=1, choices=(0, 1, 2))
    ap.add_argument("--keepalive", type=int, default=10)
    ap.add_argument("--retain", action="store_true", help="publish every reading as a retained message")
    ap.add_argument("--lwt", action="store_true", help="register a Last Will on <plant>/<line>/status")
    ap.add_argument("--spike-readings", default="", help="comma list of reading numbers (1-based) that exceed the threshold")
    ap.add_argument("--spike-value", type=float, default=None)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--count", type=int, default=0, help="stop after N readings (0 = run until interrupted)")
    a = ap.parse_args()

    unit, mean, sigma, spike_default = KINDS[a.kind]
    spike_value = a.spike_value if a.spike_value is not None else spike_default
    spikes = {int(x) for x in a.spike_readings.split(",") if x.strip()}
    rnd = random.Random(a.seed)
    topic = f"{a.plant}/{a.line}/{a.kind}"
    status_topic = f"{a.plant}/{a.line}/status"
    client_id = f"sensor-{a.line}-{a.kind}"

    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
    if a.lwt:
        c.will_set(status_topic, f"offline:{a.kind}", qos=1, retain=True)
    c.connect(a.broker, a.port, a.keepalive)
    c.loop_start()
    stop = {"flag": False}
    signal.signal(signal.SIGINT, lambda *_: stop.update(flag=True))
    signal.signal(signal.SIGTERM, lambda *_: stop.update(flag=True))
    print(f"[{client_id}] connected  topic={topic} qos={a.qos} interval={a.interval}s retain={a.retain} lwt={a.lwt}", flush=True)
    if a.lwt:
        c.publish(status_topic, f"online:{a.kind}", qos=1, retain=True).wait_for_publish()
    n = 0
    while not stop["flag"]:
        n += 1
        value = spike_value + rnd.uniform(-0.5, 0.5) if n in spikes else rnd.gauss(mean, sigma)
        info = c.publish(topic, f"{value:.2f}", qos=a.qos, retain=a.retain)
        info.wait_for_publish(5)
        print(f"[{client_id}] #{n} -> {topic} {value:.2f} {unit}", flush=True)
        if a.count and n >= a.count:
            break
        time.sleep(a.interval)
    c.loop_stop()
    c.disconnect()   # clean disconnect: the Last Will is NOT sent
    print(f"[{client_id}] clean disconnect after {n} readings", flush=True)


if __name__ == "__main__":
    main()
