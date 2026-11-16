#!/usr/bin/env python3
"""Mini Project 4.3 - simple counting model: request/response polling vs MQTT publish/subscribe.

S sensors each produce one reading per second. C consumers (dashboard, alerting, archive, ...) each need every reading.
  Polling (HTTP/CoAP GET): every consumer asks every sensor once per second.
  Pub/sub (MQTT): every sensor publishes once per second to the broker; the broker delivers to each subscriber.
Counted per second.  'Endpoint' = something a sensor must serve or connect to.
"""
rows = []
print(f"{'S':>6}{'C':>5} | {'polling: requests/s':>20}{'sensor-side endpoints':>23}{'consumer config entries':>25}"
      f" | {'pub/sub: publishes/s':>21}{'sensor-side endpoints':>23}{'consumer config entries':>25}{'broker deliveries/s':>21}")
for S, C in ((3, 2), (3, 10), (100, 5), (100, 50), (1000, 50), (10000, 100)):
    poll_req = S * C              # one request (and one response) per consumer per sensor per second
    poll_sensor_endpoints = C     # each sensor must accept C separate requesters
    poll_cfg = S * C              # every consumer must know every sensor's address
    ps_pub = S                    # constant per sensor: one publish
    ps_sensor_endpoints = 1       # one connection (to the broker)
    ps_cfg = C                    # each consumer needs one wildcard filter
    ps_deliv = S * C              # work moves to the broker, which fans out
    print(f"{S:>6}{C:>5} | {poll_req:>20}{poll_sensor_endpoints:>23}{poll_cfg:>25} | {ps_pub:>21}{ps_sensor_endpoints:>23}{ps_cfg:>25}{ps_deliv:>21}")
