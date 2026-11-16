"""Helpers for the demo scripts: start/stop a throw-away local Mosquitto broker.

The three Part A scripts do NOT need this file; they connect to any broker (default localhost:1883).
It is used only by run_demo_4_1.py, reliability_test.py and the Mini-Project-4.3 demo, so the demonstrations are
repeatable without touching a system-wide broker.
"""
import os
import shutil
import signal
import socket
import subprocess
import tempfile
import time


def port_open(port, host="127.0.0.1"):
    with socket.socket() as s:
        s.settimeout(0.2)
        return s.connect_ex((host, port)) == 0


class Broker:
    """A local Mosquitto process on 127.0.0.1:<port> with optional on-disk persistence."""

    def __init__(self, port, persistence=False):
        self.port, self.persistence = port, persistence
        self.dir = tempfile.mkdtemp(prefix="mosq_")
        os.chmod(self.dir, 0o777)                       # mosquitto may drop privileges to its own user
        self.conf = os.path.join(self.dir, "mosquitto.conf")
        lines = [f"listener {port} 127.0.0.1", "allow_anonymous true", "log_type error"]
        if persistence:
            lines += ["persistence true", f"persistence_location {self.dir}/", "autosave_interval 1"]
        with open(self.conf, "w") as f:
            f.write("\n".join(lines) + "\n")
        self.proc = None

    def start(self):
        if shutil.which("mosquitto") is None:
            raise RuntimeError("mosquitto is not installed (apt install mosquitto) - or point the scripts at a public broker")
        self.proc = subprocess.Popen(["mosquitto", "-c", self.conf], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            if port_open(self.port):
                return self
            time.sleep(0.05)
        raise RuntimeError("broker did not start")

    def stop(self, graceful=True):
        """graceful=True sends SIGTERM (persistence is written); False is a hard kill (simulated outage)."""
        if self.proc and self.proc.poll() is None:
            self.proc.send_signal(signal.SIGTERM if graceful else signal.SIGKILL)
            self.proc.wait(timeout=5)
        for _ in range(100):
            if not port_open(self.port):
                break
            time.sleep(0.05)

    def cleanup(self):
        self.stop()
        shutil.rmtree(self.dir, ignore_errors=True)
