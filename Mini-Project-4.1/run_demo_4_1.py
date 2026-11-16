#!/usr/bin/env python3
"""Mini Project 4.1, Part A - scripted demonstration (writes demo_log_4_1.txt).

Starts a throw-away local Mosquitto broker and runs the three Part A scripts exactly as the manual's Procedure steps 8-10,
plus lab task 1 (second sensor + wildcard alert subscription):

  A  normal operation: both subscribers receive every reading, only the alert subscriber reacts to values > 90
  B  retained messages: a dashboard started mid-run shows the retained temperature + status at once
  C  ungraceful termination (kill -9): the broker publishes the retained 'offline' will
  D  frozen publisher (SIGSTOP, socket stays open): the will is published only when the keep-alive timer expires
  E  clean disconnect: no will is sent, so the retained status is left stale at 'online'
  F  lab task 1: humidity sensor + alert subscriber on factory/line3/+
"""
import os
import re
import signal
import subprocess
import sys
import threading
import time

from broker_utils import Broker

PORT = 18831
HERE = os.path.dirname(os.path.abspath(__file__))
LOG, LOCK, T0 = [], threading.Lock(), time.time()


def stamp(t=None):
    t = t or time.time()
    return time.strftime("%H:%M:%S", time.localtime(t)) + f".{int((t % 1) * 1000):03d}"


def say(msg):
    line = f"[{stamp()}] ===== {msg}"
    with LOCK:
        LOG.append(line)
    print(line, flush=True)


class Proc:
    def __init__(self, tag, script, *args):
        self.tag = tag
        self.p = subprocess.Popen([sys.executable, "-u", os.path.join(HERE, script), "--port", str(PORT), *args],
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        self.lines = []
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.p.stdout:
            line = line.rstrip("\n")
            self.lines.append(line)
            out = f"{self.tag:<9}| {line}"
            with LOCK:
                LOG.append(out)
            print(out, flush=True)

    def kill9(self):
        say(f"kill -9 {self.tag} (no DISCONNECT packet is sent)")
        self.p.send_signal(signal.SIGKILL)

    def wait(self, t=15):
        self.p.wait(timeout=t)


def secs(line):
    m = re.match(r"\[(\d+):(\d+):(\d+\.\d+)\]", line)
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else None


def wait_for(proc, text, timeout, after=0):
    """Seconds until a line containing `text` appears at index >= `after` of proc.lines (None on timeout)."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        if any(text in l for l in proc.lines[after:]):
            return time.time() - t0
        time.sleep(0.02)
    return None


def main():
    broker = Broker(PORT).start()
    say(f"local Mosquitto broker started on 127.0.0.1:{PORT}")
    try:
        # ---------------- A: normal operation ----------------
        say("A. normal operation: dashboard + alert subscriber, then the publisher (1 s interval so the demo is short)")
        dash = Proc("DASH-A", "dashboard_subscriber.py", "--client-id", "dashboard")
        alrt = Proc("ALERT-A", "alert_subscriber.py", "--threshold", "90")
        time.sleep(0.6)
        sensor = Proc("SENSOR", "sensor_publisher.py", "--interval", "1.0", "--retain-all", "--seed", "2")
        while sum("publish #" in l for l in sensor.lines) < 6:
            time.sleep(0.02)
        time.sleep(0.4)                                   # let the 6th reading reach both subscribers
        for p in (dash, alrt):
            p.p.send_signal(signal.SIGINT)                # Ctrl-C: the scripts print a summary and exit
        dash.wait(); alrt.wait()
        n_pub = sum("publish #" in l for l in sensor.lines[: next(i for i, l in enumerate(sensor.lines) if "publish #6" in l) + 1])
        dash_n = len([l for l in dash.lines if "DASHBOARD factory/line3/temperature" in l])
        alert_summary = [l for l in alrt.lines if "stopped" in l][0]
        say(f"A result: sensor published {n_pub} readings; dashboard printed {dash_n} temperature lines; alert subscriber: "
            f"{alert_summary.split('stopped; ')[1]}")

        # ---------------- B: retained message for a late subscriber ----------------
        say("B. late subscriber: restart the dashboard while the publisher keeps running")
        late = Proc("DASH-LATE", "dashboard_subscriber.py", "--client-id", "dashboard-late", "--duration", "2.0")
        t_wait = time.time()
        while sum("[RETAINED]" in l for l in late.lines) < 2 and time.time() - t_wait < 3:
            time.sleep(0.01)
        late.wait()
        conn = secs([l for l in late.lines if "connected" in l][0])
        ret = [l for l in late.lines if "[RETAINED]" in l]
        live = [l for l in late.lines if "DASHBOARD factory" in l and "[RETAINED]" not in l]
        say(f"B result: {len(ret)} retained messages ({', '.join(l.split()[2].split('/')[-1] + '=' + l.split()[3] for l in ret)}) "
            f"arrived {(secs(ret[-1]) - conn) * 1000:.0f} ms after the connection was made; the next live reading came "
            f"{(secs(live[0]) - conn):.2f} s after connecting")

        # ---------------- C: ungraceful termination ----------------
        say("C. ungraceful termination of the publisher (hard kill)")
        d2 = Proc("DASH-C", "dashboard_subscriber.py", "--client-id", "dashboard-c", "--duration", "3.5")
        time.sleep(0.4)
        t_kill = time.time()
        idx = len(d2.lines)
        sensor.kill9()
        dt = wait_for(d2, "offline", 3, after=idx)
        d2.wait()
        say(f"C result: broker published the will ('offline') {dt*1000:.0f} ms after the kill - the publisher sent nothing. "
            "The OS closed the TCP socket, so the broker noticed at once (no keep-alive wait).")

        # ---------------- D: frozen publisher (keep-alive expiry) ----------------
        say("D. frozen publisher (SIGSTOP): socket stays open, so only the keep-alive timer can reveal the failure (keep-alive = 4 s)")
        d3 = Proc("DASH-D", "dashboard_subscriber.py", "--client-id", "dashboard-d", "--duration", "17")
        s2 = Proc("SENSOR-2", "sensor_publisher.py", "--interval", "1.0", "--keepalive", "4", "--retain-all", "--seed", "5")
        time.sleep(2.5)
        t_stop = time.time()
        say("SIGSTOP sensor (process frozen, no more packets, TCP connection still open)")
        idx = len(d3.lines)
        s2.p.send_signal(signal.SIGSTOP)
        dt = wait_for(d3, "offline", 14, after=idx)
        s2.p.send_signal(signal.SIGKILL)
        d3.wait()
        say(f"D result: will published {dt:.1f} s after the freeze (keep-alive 4 s, so the nominal limit is 1.5 x 4 = 6 s; "
            "the broker checks keep-alives periodically, so detection is somewhat later than the nominal limit)" if dt else "D result: no will within 14 s")

        # ---------------- E: clean disconnect ----------------
        say("E. clean disconnect: publisher exits normally after 3 readings")
        s3 = Proc("SENSOR-3", "sensor_publisher.py", "--interval", "0.5", "--count", "3", "--seed", "8")
        s3.wait()
        time.sleep(0.3)
        d4 = Proc("DASH-E", "dashboard_subscriber.py", "--client-id", "dashboard-e", "--duration", "1.2")
        d4.wait()
        st = [l for l in d4.lines if "status" in l and "DASHBOARD factory" in l]
        say(f"E result: no will was published; a new subscriber still sees the retained status '{st[0].split()[3] if st else '?'}' "
            "although the publisher is gone (stale). Publish 'offline' explicitly before a clean exit (--offline-on-exit).")

        # ---------------- F: lab task 1 ----------------
        say("F. lab task 1: add a humidity sensor; alert subscriber now subscribes to factory/line3/+")
        a2 = Proc("ALERT-F", "alert_subscriber.py", "--client-id", "alert-2", "--topic", "factory/line3/+", "--duration", "5.5")
        dF = Proc("DASH-F", "dashboard_subscriber.py", "--client-id", "dashboard-f", "--duration", "5.5",
                  "--topics", "factory/line3/temperature", "factory/line3/humidity", "factory/line3/status")
        time.sleep(0.5)
        t1 = Proc("TEMP", "sensor_publisher.py", "--interval", "1.0", "--count", "4", "--seed", "3", "--retain-all")
        h1 = Proc("HUMID", "sensor_publisher.py", "--interval", "1.0", "--count", "4", "--seed", "4", "--retain-all",
                  "--client-id", "line3-humidity-sensor", "--topic", "factory/line3/humidity",
                  "--status-topic", "factory/line3/humidity_status", "--low", "40", "--high", "85")
        for p in (t1, h1, a2, dF):
            p.wait()
        say(f"F result: {[l for l in a2.lines if 'stopped' in l][0].split('stopped; ')[1]} (temperature AND humidity readings, "
            "status texts ignored, threshold logic unchanged)")
    finally:
        broker.cleanup()
        say("broker stopped")
        with open(os.path.join(HERE, "demo_log_4_1.txt"), "w") as f:
            f.write("\n".join(LOG) + "\n")


if __name__ == "__main__":
    main()
