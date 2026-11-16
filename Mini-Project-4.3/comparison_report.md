# Publish/Subscribe versus Request/Response for Many-to-Many Telemetry

## Where the coupling sits

A request/response design such as HTTP polling or CoAP GET makes every consumer talk directly to every sensor. The dashboard must know each sensor's address, the sensor must be awake and reachable when the question arrives, and every new consumer adds another stream of questions to every device. MQTT removes the direct link. A sensor publishes to a topic on the broker and neither knows nor cares who listens; a subscriber states an interest with a topic filter and neither knows nor cares who produced the data. The two sides are decoupled in space (no addresses), in time (the broker stores messages and state) and in synchronisation (publishing never waits for a reader).

## What our system showed

Three sensors publish under `plant1/<line>/<measurement>` and one aggregator subscribes once to `plant1/+/+`. When we started a fourth sensor, `plant1/lineB/vibration`, while the system was running, the aggregator logged "NEW TOPIC" and began applying the vibration threshold with no code change. The same hierarchy gave independent alerting: a temperature of 82 °C passed on line A (limit 85) but alerted on line B (limit 80). In a polling design the aggregator would have needed the new sensor's address and a new polling loop.

## Scaling with sensors and consumers

Let S be the number of sensors and C the number of consumers, with every consumer needing every reading each second. Polling issues S × C requests per second, every sensor must serve C separate requesters, and every consumer must be configured with S addresses, so S × C configuration entries in total. With MQTT each sensor sends one publish per second whatever C is, keeps one outbound connection, and each consumer is configured with one filter. Our counting model (`scaling_model.py`) gives, for 100 sensors and 50 consumers, 5 000 polling requests per second against 100 publishes per second leaving the sensors.

This needs an honest qualification. The broker still performs S × C deliveries, so the total number of messages moved does not fall; the work moves from constrained devices to a server that can be scaled, clustered or bridged. For battery-powered sensors this is the decisive change: a polled device must keep its radio listening, whereas a publisher can sleep and transmit only when it has a reading. Polling can also miss an excursion that falls between two polls.

## Quality of service

QoS lets each message state how much delivery effort it deserves, which request/response cannot express per message. QoS 0 sends once with no acknowledgement and suits high-rate readings where the next value replaces a lost one. QoS 1 (used by all our sensors) is acknowledged and retried, giving at-least-once delivery with possible duplicates. QoS 2 adds a four-step handshake for exactly-once delivery at higher cost. In our broker-outage test of 150 messages, QoS 0 lost 42 while QoS 1 delivered all 150, with one duplicate. The guarantee has a limit we also measured: it applies only to messages that reach the client library's queue, so a process killed immediately after `publish()` returns lost most messages at every QoS level.

## Retained messages and Last Will

A request/response client that starts late simply asks and receives the current value, but only if the sensor is awake. A retained message makes the broker keep the latest value per topic: in our demonstration a new subscriber received the latest value of every topic within about 45 ms of connecting, before any live reading arrived. The cost is staleness: a retained value can outlive its sensor, so it must be read together with a status topic.

The Last Will and Testament answers the question polling answers by timeout: is the sensor still there? The broker publishes the will if the connection drops without a clean DISCONNECT. We killed the line-B temperature sensor with SIGKILL and the aggregator received `offline:temperature` about 20 ms later, because the operating system closed the socket. When a device freezes with its socket open, detection waits for keep-alive expiry, about one and a half times the interval; in our earlier test that took about 7 seconds with a 4-second keep-alive. Publishing the will as a retained message means even a subscriber that joins afterwards learns the sensor is down.

## Limits of the pattern

The broker is a single point of failure unless clustered, and request/response remains the better fit for a command that needs a direct answer, such as "run this calibration now", or for a one-off query. Telemetry fan-out to many consumers, with devices that sleep and come and go, is where publish/subscribe grows by adding one subscription or one publisher at a time instead of rewriting every connection.
