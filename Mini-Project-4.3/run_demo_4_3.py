#!/usr/bin/env python3
"""Mini Project 4.3 - scripted demonstration. Starts a throw-away Mosquitto broker on port 18843, then runs the
sensors, the aggregator and a late joiner in the order below and writes everything to sample_log.txt.

  A  normal multi-sensor operation, wildcard aggregation, per-topic thresholds (82 on lineA passes, 82 on lineB alerts)
  B  retained messages: a subscriber that joins late gets the latest value of every topic at once
  C  a new sensor topic appears while the system runs - the aggregator picks it up with no code change
  D  Last Will: the lineB temperature sensor is killed with SIGKILL; the broker publishes its will
  E  clean shutdown

Run:  python run_demo_4_3.py
"""
import os
import signal
import subprocess
import sys
import threading
import time

from broker_utils import Broker

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 18843
LOG = []
LOCK = threading.Lock()


def log(line):
    with LOCK:
        LOG.append(line)
        print(line, flush=True)


class Proc:
    def __init__(self, tag, args):
        self.tag = tag
        self.p = subprocess.Popen([sys.executable, "-u"] + args, cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.lines = []
        self.t = threading.Thread(target=self._read, daemon=True)
        self.t.start()

    def _read(self):
        for line in self.p.stdout:
            line = line.rstrip()
            self.lines.append(line)
            log(f"{self.tag:<11}| {line}")

    def wait_for(self, text, timeout=10, after=0):
        t0 = time.time()
        while time.time() - t0 < timeout:
            for i, l in enumerate(self.lines):
                if i >= after and text in l:
                    return i
            time.sleep(0.02)
        return -1

    def stop(self, sig=signal.SIGINT):
        if self.p.poll() is None:
            self.p.send_signal(sig)
            try:
                self.p.wait(5)
            except subprocess.TimeoutExpired:
                self.p.kill()
        self.t.join(2)


def banner(text):
    log("")
    log("=" * 100)
    log(text)
    log("=" * 100)


def sensor(tag, line, kind, interval, extra=()):
    return Proc(tag, ["sensor.py", "--port", str(PORT), "--line", line, "--kind", kind, "--interval", str(interval), "--retain", "--seed", str(sum(map(ord, tag))), *extra])


def main():
    broker = Broker(PORT).start()
    procs = []
    try:
        banner("A. Normal operation: 3 sensors -> 1 broker -> 1 aggregator using ONE wildcard subscription 'plant1/+/+'")
        agg = Proc("AGGREGATOR", ["aggregator.py", "--port", str(PORT), "--summary-interval", "4", "--csv", "readings_log.csv"])
        procs.append(agg)
        agg.wait_for("subscribed")
        sA_t = sensor("A-temp", "lineA", "temperature", 0.5, ["--spike-readings", "6", "--spike-value", "82"])
        sA_v = sensor("A-vib", "lineA", "vibration", 0.7, ["--spike-readings", "5,6"])
        sB_t = sensor("B-temp", "lineB", "temperature", 0.6, ["--lwt", "--spike-readings", "6", "--spike-value", "82"])
        procs += [sA_t, sA_v, sB_t]
        time.sleep(7.0)
        log("")
        log("# note: lineA temperature = 82 stayed under its own limit (85) -> no alert; lineB temperature = 82 exceeded its limit (80) -> alert.")
        log("# vibration limit is 7.0 mm/s, so 9.5 mm/s on lineA/vibration alerts; each topic is judged independently.")

        banner("B. Retained messages: a subscriber joins late (every reading and the status are retained)")
        lj = Proc("LATE-JOINER", ["late_joiner.py", "--port", str(PORT), "--duration", "1.5"])
        lj.p.wait(10)
        lj.t.join(2)
        log("# the messages flagged [RETAINED] arrived within milliseconds of connecting, long before the next live reading.")

        banner("C. A NEW sensor topic (plant1/lineB/vibration) is started while the aggregator keeps running - no code change")
        n0 = len(agg.lines)
        sB_v = sensor("B-vib", "lineB", "vibration", 0.8, ["--spike-readings", "4"])
        procs.append(sB_v)
        agg.wait_for("NEW TOPIC discovered: plant1/lineB/vibration", timeout=5, after=n0)
        time.sleep(3.5)

        banner("D. Last Will: kill -9 on the lineB temperature sensor (no clean disconnect)")
        n0 = len(agg.lines)
        t_kill = time.time()
        log(f"# [{time.strftime('%H:%M:%S')}] sending SIGKILL to the B-temp sensor (pid {sB_t.p.pid})")
        sB_t.p.send_signal(signal.SIGKILL)
        i = agg.wait_for("LAST WILL received", timeout=15, after=n0)
        dt = time.time() - t_kill
        log(f"# will observed by the aggregator {dt * 1000:.0f} ms after the kill" if i >= 0 else "# WILL NOT OBSERVED")
        time.sleep(1.5)
        log("")
        log("# a fresh late joiner now sees the retained 'offline' status plus the last retained readings:")
        lj2 = Proc("LATE-JOINER", ["late_joiner.py", "--port", str(PORT), "--duration", "1.2"])
        lj2.p.wait(10)
        lj2.t.join(2)

        banner("E. Clean shutdown (SIGINT): clean disconnects do not trigger any will; aggregator prints its final summary")
        for p in (sA_t, sA_v, sB_v):
            p.stop()
        time.sleep(0.5)
        agg.stop()
    finally:
        for p in procs:
            if p.p.poll() is None:
                p.p.kill()
        broker.cleanup()
    with open(os.path.join(HERE, "sample_log.txt"), "w") as f:
        f.write("\n".join(LOG) + "\n")


if __name__ == "__main__":
    main()
