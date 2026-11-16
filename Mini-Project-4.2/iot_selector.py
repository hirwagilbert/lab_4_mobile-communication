#!/usr/bin/env python3
"""Mini Project 4.2 - Rule-based IoT connectivity technology selector.

Ranks NB-IoT, LTE-M, LoRaWAN, 5G RedCap and BLE/Zigbee for a deployment described by six requirement axes:
    data rate | coverage | battery life | mobility | infrastructure ownership | cost sensitivity

Method (every number is in the tables below, nothing is hidden):
  1. Each requirement is mapped to a 0-5 DEMAND on the same scale as the technology CAPABILITY matrix.
  2. Per-axis match  m = 1 - max(0, demand - capability) / 5      (a shortfall costs score, a surplus does not)
  3. Base score      S = 100 * sum(w_axis * m_axis) / sum(w_axis)  (weights adjustable)
  4. Constraint rules add or subtract points for cases a plain sum handles badly; every fired rule is printed.
  5. Final score is clipped to 0..100 and the techs are ranked; the justification names the axes that moved the score.

Usage:
    python iot_selector.py --builtin                 run the 4 unit scenarios + the new one, print and save results
    python iot_selector.py --scenario my.json        score one scenario from a JSON file (see SCENARIOS below for keys)
    python iot_selector.py --interactive             answer prompts at the keyboard
    python iot_selector.py --builtin --weights data=2,battery=0.5     override weights
    python iot_selector.py --builtin --sensitivity   vary every weight x0.5 / x2 and report whether each winner survives
"""
import argparse
import csv
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

TECHS = ["NB-IoT", "LTE-M", "LoRaWAN", "5G RedCap", "BLE/Zigbee"]
AXES = ["data_rate", "coverage", "battery", "mobility", "infrastructure", "cost"]
AXIS_LABEL = {"data_rate": "data rate", "coverage": "coverage", "battery": "battery life",
              "mobility": "mobility", "infrastructure": "infrastructure fit", "cost": "cost"}

DEFAULT_WEIGHTS = {"data_rate": 1.0, "coverage": 2.0, "battery": 1.5, "mobility": 1.5, "infrastructure": 1.0, "cost": 1.0}

# ---------------------------------------------------------------------------------------------
# Capability matrix (0-5).  Source: unit Sections 4.2 / 4.3 comparison of the technologies.
# ---------------------------------------------------------------------------------------------
# data_rate: highest requirement band the technology can carry  (bands defined in demand_data_rate)
CAP_DATA = {"NB-IoT": 3, "LTE-M": 4, "LoRaWAN": 2, "5G RedCap": 5, "BLE/Zigbee": 4}
# battery: realistic multi-year life on a small cell with the technology's sleep modes (band defined in demand_battery)
CAP_BATTERY = {"NB-IoT": 4, "LTE-M": 3, "LoRaWAN": 5, "5G RedCap": 2, "BLE/Zigbee": 5}
# mobility: highest mobility level supported (stationary 1, local 2, wide-area 4, global roaming 5)
CAP_MOBILITY = {"NB-IoT": 3, "LTE-M": 5, "LoRaWAN": 2, "5G RedCap": 5, "BLE/Zigbee": 2}
# coverage: how well the technology serves each coverage category (the categories are not ordered, so each gets its own column)
CAP_COVERAGE = {
    "deep_indoor":        {"NB-IoT": 5, "LTE-M": 4, "LoRaWAN": 3, "5G RedCap": 2, "BLE/Zigbee": 1},
    "wide_area_cellular": {"NB-IoT": 4, "LTE-M": 5, "LoRaWAN": 2, "5G RedCap": 4, "BLE/Zigbee": 0},
    "long_range_rural":   {"NB-IoT": 3, "LTE-M": 3, "LoRaWAN": 5, "5G RedCap": 2, "BLE/Zigbee": 0},
    "short_range":        {"NB-IoT": 1, "LTE-M": 1, "LoRaWAN": 2, "5G RedCap": 1, "BLE/Zigbee": 5},
}
# infrastructure: fit with the stated ownership preference (no_preference scores 5 for everyone)
CAP_INFRA = {
    "operator":      {"NB-IoT": 5, "LTE-M": 5, "LoRaWAN": 2, "5G RedCap": 4, "BLE/Zigbee": 1},
    "self_owned":    {"NB-IoT": 1, "LTE-M": 2, "LoRaWAN": 5, "5G RedCap": 2, "BLE/Zigbee": 5},
    "no_preference": {t: 5 for t in TECHS},
}
# cost: per-device lifetime cost attractiveness (module price + subscription); 5 = cheapest
CAP_COST = {"NB-IoT": 4, "LTE-M": 3, "LoRaWAN": 5, "5G RedCap": 2, "BLE/Zigbee": 5}

COVERAGE_CATS = list(CAP_COVERAGE)
MOBILITY_LEVELS = {"stationary": 1, "local": 2, "wide_area": 4, "global": 5}
BUDGET_BASE = {"relaxed": 1, "moderate": 2, "strict": 3}


# ---------------------------------------------------------------------------------------------
# Requirement -> 0..5 demand mapping
# ---------------------------------------------------------------------------------------------
def required_kbps(s):
    """Average data rate in kbps, from an explicit rate or from message size and interval."""
    if s.get("data_rate_kbps") is not None:
        return float(s["data_rate_kbps"])
    return s["message_bytes"] * 8 / s["interval_s"] / 1000.0


def demand_data_rate(kbps):
    for limit, d in ((1, 1), (30, 2), (100, 3), (1000, 4)):
        if kbps <= limit:
            return d
    return 5


def demand_battery(years):
    for limit, d in ((1, 1), (3, 2), (5, 3), (10, 4)):
        if years <= limit:
            return d
    return 5


def demand_cost(devices, budget):
    d = BUDGET_BASE[budget] + (devices >= 1000) + (devices >= 10000)
    return min(d, 5)


def demands(s):
    return {
        "data_rate": demand_data_rate(required_kbps(s)),
        "coverage": 5,                                    # the chosen category must be served as well as possible
        "battery": demand_battery(s["battery_years"]),
        "mobility": MOBILITY_LEVELS[s["mobility"]],
        "infrastructure": 5,
        "cost": demand_cost(s["devices"], s["budget"]),
    }


def capability(tech, s):
    return {
        "data_rate": CAP_DATA[tech],
        "coverage": CAP_COVERAGE[s["coverage"]][tech],
        "battery": CAP_BATTERY[tech],
        "mobility": CAP_MOBILITY[tech],
        "infrastructure": CAP_INFRA[s["infrastructure"]][tech],
        "cost": CAP_COST[tech],
    }


def validate(s):
    errs = []
    if s.get("data_rate_kbps") is None and not (s.get("message_bytes") and s.get("interval_s")):
        errs.append("give data_rate_kbps, or both message_bytes and interval_s")
    for key, allowed in (("coverage", COVERAGE_CATS), ("mobility", list(MOBILITY_LEVELS)),
                         ("infrastructure", list(CAP_INFRA)), ("budget", list(BUDGET_BASE))):
        if s.get(key) not in allowed:
            errs.append(f"{key} must be one of {allowed}, got {s.get(key)!r}")
    for key in ("battery_years", "devices"):
        if not isinstance(s.get(key), (int, float)) or s[key] <= 0:
            errs.append(f"{key} must be a positive number")
    if errs:
        raise ValueError("; ".join(errs))


# ---------------------------------------------------------------------------------------------
# Constraint rules: (id, text, predicate(tech, scenario, demand, cap) -> points)
# ---------------------------------------------------------------------------------------------
def rules(tech, s, dem, cap):
    fired = []
    if tech == "LoRaWAN" and s["mobility"] in ("wide_area", "global"):
        fired.append(("R1", -20, "LoRaWAN has no cellular-style handover or roaming, so wide-area/global mobility is penalised"))
    if tech == "BLE/Zigbee" and s["coverage"] != "short_range":
        fired.append(("R2", -40, "BLE/Zigbee reach tens of metres; they cannot serve a non-short-range coverage need"))
    if tech in ("LoRaWAN", "BLE/Zigbee") and s["infrastructure"] != "operator" and s["devices"] >= 1000 and s["budget"] == "strict":
        fired.append(("R3", +8, "self-owned options avoid per-device subscriptions once the fleet is >= 1000 devices on a strict budget"))
    if dem["data_rate"] - cap["data_rate"] >= 2:
        fired.append(("R4", -15, "required data rate is two or more bands above what the technology can carry"))
    if dem["battery"] >= 4 and cap["battery"] <= 3:
        fired.append(("R5", -10, "a 5-10+ year battery target is out of reach for this technology's active/idle current"))
    if tech in ("NB-IoT", "LTE-M", "5G RedCap") and s["coverage"] == "short_range":
        fired.append(("R6", -10, "a cellular subscription and module are over-specified for a short-range-only need"))
    if cap["coverage"] <= 2 and not any(r[0] in ("R2", "R6") for r in fired):
        fired.append(("R7", -10, "the technology serves the required coverage category poorly (capability <= 2 of 5)"))
    return fired


def score_all(s, weights=None):
    validate(s)
    w = dict(DEFAULT_WEIGHTS, **(weights or {}))
    dem = demands(s)
    wsum = sum(w.values())
    out = []
    for t in TECHS:
        cap = capability(t, s)
        match = {a: 1 - max(0, dem[a] - cap[a]) / 5 for a in AXES}
        base = 100 * sum(w[a] * match[a] for a in AXES) / wsum
        fired = rules(t, s, dem, cap)
        final = max(0.0, min(100.0, base + sum(p for _, p, _ in fired)))
        out.append(dict(tech=t, base=base, rules=fired, score=final, match=match, cap=cap))
    out.sort(key=lambda r: -r["score"])
    for r in out:
        r["justification"] = justify(r, dem, w)
    return out, dem


def justify(r, dem, w):
    loss = {a: w[a] * (1 - r["match"][a]) for a in AXES}
    full = [AXIS_LABEL[a] for a in AXES if r["match"][a] == 1.0 and a in ("coverage", "battery", "mobility", "data_rate")]
    worst = sorted((a for a in AXES if loss[a] > 0), key=lambda a: -loss[a])[:2]
    parts = []
    if full:
        parts.append("meets " + ", ".join(full[:3]))
    if worst:
        parts.append("held back by " + " and ".join(
            f"{AXIS_LABEL[a]} (needs {dem[a]}, offers {r['cap'][a]})" for a in worst))
    for rid, pts, _ in r["rules"]:
        parts.append(f"{rid} {pts:+d}")
    return "; ".join(parts) + "."


# ---------------------------------------------------------------------------------------------
# Scenarios (the first four re-create the unit's worked examples; the fifth is the student's own)
# Section 4.3's exact figures were not reproduced in the lab sheet, so the numbers below are stated assumptions.
# ---------------------------------------------------------------------------------------------
SCENARIOS = [
    dict(name="1. Smart water meter", expected="NB-IoT",
         note="basement/underground meters, 50 B per day, 15-year battery, stationary, utility buys operator connectivity, 50 000 units on a strict budget",
         message_bytes=50, interval_s=86400, coverage="deep_indoor", battery_years=15, mobility="stationary",
         infrastructure="operator", devices=50000, budget="strict"),
    dict(name="2. Fleet-tracked shipping container", expected="LTE-M",
         note="position + temperature, 100 B per hour, 2-year battery, crosses countries, needs roaming, 2 000 units",
         message_bytes=100, interval_s=3600, coverage="wide_area_cellular", battery_years=2, mobility="global",
         infrastructure="operator", devices=2000, budget="moderate"),
    dict(name="3. Factory-floor sensor network", expected="LoRaWAN",
         note="site-wide vibration/temperature, 50 B every 10 s, owned gateways, 3 000 fixed sensors, 8-year battery, strict budget",
         message_bytes=50, interval_s=10, coverage="long_range_rural", battery_years=8, mobility="stationary",
         infrastructure="self_owned", devices=3000, budget="strict"),
    dict(name="4. Wearable health monitor", expected="BLE/Zigbee",
         note="heart-rate stream to a phone, about 10 kbps, one-week battery, moves with the wearer, 1 000 units",
         data_rate_kbps=10, coverage="short_range", battery_years=0.02, mobility="local",
         infrastructure="no_preference", devices=1000, budget="moderate"),
    dict(name="5. NEW: livestock tracking collars on a ranch", expected="LoRaWAN",
         note="",
         message_bytes=30, interval_s=900, coverage="long_range_rural", battery_years=3, mobility="local",
         infrastructure="no_preference", devices=800, budget="strict"),
]
SCENARIOS[4]["note"] = ("30 km2 ranch, 800 collars, 30 B GPS fix every 15 min, animals roam slowly (local mobility), "
                        "3-year battery, no guaranteed cellular coverage, owner has no ownership preference but a strict budget")


def render(s, ranked, dem, weights):
    lines = [f"Scenario: {s.get('name', 'custom')}"]
    if s.get("note"):
        lines.append(f"  {s['note']}")
    lines.append(f"  inputs: {required_kbps(s):.5g} kbps average, coverage={s['coverage']}, battery={s['battery_years']} y, "
                 f"mobility={s['mobility']}, infrastructure={s['infrastructure']}, devices={s['devices']}, budget={s['budget']}")
    lines.append("  demands (0-5): " + ", ".join(f"{AXIS_LABEL[a]}={dem[a]}" for a in AXES))
    lines.append(f"  {'rank':<5}{'technology':<13}{'base':>7}{'rules':>7}{'score':>8}   justification")
    for i, r in enumerate(ranked, 1):
        lines.append(f"  {i:<5}{r['tech']:<13}{r['base']:>7.1f}{sum(p for _, p, _ in r['rules']):>+7d}{r['score']:>8.1f}   {r['justification']}")
    if s.get("expected"):
        ok = ranked[0]["tech"] == s["expected"]
        lines.append(f"  expected top pick: {s['expected']}  ->  tool says {ranked[0]['tech']}  [{'MATCH' if ok else 'DIVERGES'}]")
    return "\n".join(lines)


def parse_weights(txt):
    out = {}
    if txt:
        for kv in txt.split(","):
            k, v = kv.split("=")
            if k.strip() not in AXES:
                sys.exit(f"unknown weight axis {k!r}; use one of {AXES}")
            out[k.strip()] = float(v)
    return out


def interactive():
    def ask(prompt, options=None, cast=str):
        while True:
            v = input(prompt + (f" {options}" if options else "") + ": ").strip()
            try:
                v = cast(v)
            except ValueError:
                print("  not a valid number"); continue
            if options is None or v in options:
                return v
            print("  choose one of", options)
    s = {"name": "interactive"}
    s["message_bytes"] = ask("message size in bytes", cast=float)
    s["interval_s"] = ask("seconds between messages", cast=float)
    s["coverage"] = ask("coverage", COVERAGE_CATS)
    s["battery_years"] = ask("battery target in years", cast=float)
    s["mobility"] = ask("mobility", list(MOBILITY_LEVELS))
    s["infrastructure"] = ask("infrastructure preference", list(CAP_INFRA))
    s["devices"] = ask("number of devices", cast=float)
    s["budget"] = ask("budget tier", list(BUDGET_BASE))
    return s


def sensitivity(weights):
    """Multiply each weight by 0.5 and by 2 (one at a time) and see whether each scenario's winner changes."""
    lines = ["Weight sensitivity: top pick when ONE weight is halved / doubled (base weights " +
             ", ".join(f"{a}={weights[a]:g}" for a in AXES) + ")"]
    lines.append(f"  {'scenario':<46}{'base pick':<13}{'changes':<9}  detail")
    stable = 0
    for s in SCENARIOS:
        base = score_all(s, weights)[0][0]["tech"]
        changes = []
        for a in AXES:
            for f in (0.5, 2.0):
                w = dict(weights); w[a] = weights[a] * f
                top = score_all(s, w)[0][0]["tech"]
                if top != base:
                    changes.append(f"{a} x{f:g} -> {top}")
        stable += not changes
        lines.append(f"  {s['name']:<46}{base:<13}{len(changes):<9}  {'; '.join(changes) if changes else 'stable under all 12 variations'}")
    lines.append(f"  {stable} of {len(SCENARIOS)} scenarios keep the same winner under all 12 single-weight changes")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--builtin", action="store_true", help="run the five built-in scenarios")
    ap.add_argument("--scenario", help="JSON file with one scenario")
    ap.add_argument("--interactive", action="store_true")
    ap.add_argument("--weights", help="e.g. data_rate=2,battery=0.5")
    ap.add_argument("--sensitivity", action="store_true")
    ap.add_argument("--no-save", action="store_true")
    a = ap.parse_args()
    w = dict(DEFAULT_WEIGHTS, **parse_weights(a.weights))

    if a.scenario:
        s = json.load(open(a.scenario))
        try:
            ranked, dem = score_all(s, w)
        except ValueError as e:
            sys.exit(f"invalid scenario: {e}")
        print(render(s, ranked, dem, w))
        return
    if a.interactive:
        s = interactive()
        ranked, dem = score_all(s, w)
        print(render(s, ranked, dem, w))
        return
    if not (a.builtin or a.sensitivity):
        ap.print_help(); return

    out, rows, hits = [], [], 0
    out.append("Weights: " + ", ".join(f"{k}={v:g}" for k, v in w.items()))
    out.append("")
    for s in SCENARIOS:
        ranked, dem = score_all(s, w)
        out.append(render(s, ranked, dem, w)); out.append("")
        hits += ranked[0]["tech"] == s["expected"]
        rows.append([s["name"], s["expected"]] + [f"{r['tech']} ({r['score']:.1f})" for r in ranked])
    out.append(f"Top pick equals the expected technology in {hits} of {len(SCENARIOS)} scenarios.")
    out.append("")
    out.append(sensitivity(w))
    text = "\n".join(out)
    print(text)
    if not a.no_save:
        open(os.path.join(HERE, "selector_output.txt"), "w").write(text + "\n")
        with open(os.path.join(HERE, "results_table.csv"), "w", newline="") as f:
            cw = csv.writer(f)
            cw.writerow(["scenario", "expected", "rank1", "rank2", "rank3", "rank4", "rank5"])
            cw.writerows(rows)
        json.dump(SCENARIOS, open(os.path.join(HERE, "scenarios.json"), "w"), indent=2)


if __name__ == "__main__":
    main()
