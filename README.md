# Mobile Communications - Unit 4 Lab (Mini Projects 4.1 - 4.3)

University of Rwanda, Gako Campus - Computer Engineering, Year 4 - Group assignment

Members: Janvier NSHIMIYIMANA (223026679), Blandon ASHIMIRWE (223026675), Gilbert HIRWA NTWALI (223026689)

The written report is `Lab4_Report.pdf`.

| Folder | Content | Run |
|---|---|---|
| `Mini-Project-4.1` | MQTT publisher/subscribers (LWT, retained, QoS), scripted demo, QoS reliability tests, LPWAN link-budget and battery comparison | `python run_demo_4_1.py`, `python reliability_test.py`, `python link_budget_compare.py` |
| `Mini-Project-4.2` | Rule-based IoT connectivity selector | `python iot_selector.py --builtin` (also `--scenario file.json`, `--interactive`, `--sensitivity`) |
| `Mini-Project-4.3` | Multi-sensor MQTT dashboard: sensors, wildcard aggregator, late joiner, scripted demo, scaling model, comparison report | `python run_demo_4_3.py` |

## Setup
```
pip install -r requirements.txt
sudo apt install mosquitto      # only for the MQTT demos; the demo scripts start their own throw-away broker
```
The individual publisher/subscriber scripts also work against any broker (`--broker`, `--port`).

Notes: battery currents and the Unit 4.3 scenario figures used in 4.1/4.2 are stated assumptions, not measurements. Log files (`demo_log_4_1.txt`, `sample_log.txt`, `*_output.txt`) are the output of the last run; timings vary slightly between runs.
