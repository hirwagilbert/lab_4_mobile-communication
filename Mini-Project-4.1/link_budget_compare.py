#!/usr/bin/env python3
"""Mini Project 4.1, Part B - LPWAN link-budget and battery-life comparison.

Scenario (manual): 200 soil-moisture/temperature sensors on a 25 km2 farm, 12-byte reading every 30 min, maximum
sensor-to-gateway distance 8 km, 5-year target on a 3.6 V / 19 000 mAh primary lithium battery, NO cellular coverage nearby,
no per-device fees preferred.

  Coverage : MCL = Ptx - sensitivity;   PL(d) = PL(d0) + 10 n log10(d/d0), PL(1 km) = 91.5 dB, n = 3.5;   margin = MCL - PL(d)
  Battery  : mAh/cycle = I_tx * t_tx / 3600 + I_rx * t_rx / 3600 + I_sleep * (T - t_active) / 3600;  years = capacity / mAh per year

Extras (lab tasks): --scenario container (task 4), RedCap column (task 5), path-loss-exponent sweep (task 6).
Every current / duration below is an ASSUMPTION (representative module figures, not measurements) and is labelled as such.

Run:  python link_budget_compare.py            (prints everything, writes link_budget_output.txt and two PNG charts)
"""
import argparse
import math
import os
from dataclasses import dataclass

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))

# ------------------------------------------------------------------ scenario constants
PL_D0_DB = 91.5            # free-space loss at d0 = 1 km, ~900 MHz (manual)
N_RURAL = 3.5              # path-loss exponent, open rural terrain (manual)
DIST_KM = 8.0
INTERVAL_S = 30 * 60       # one reading every 30 min
PAYLOAD_B = 12
BATTERY_MAH = 19000.0
TARGET_YEARS = 5.0
SELF_DISCHARGE = 0.01      # assumption: 1 % of capacity per year (lithium primary)
FADE_MARGIN_DB = 10.0      # assumption: desired margin on top of the median path loss
N_DEVICES = 200
AREA_KM2 = 25.0


def lora_airtime_s(payload_bytes, sf=12, bw=125e3, cr=1, preamble=8, crc=True, explicit_header=True):
    """Semtech SX127x time-on-air formula (LoRa PHY payload = application payload + 13 B LoRaWAN overhead is added by caller)."""
    t_sym = (2 ** sf) / bw
    de = 1 if (sf >= 11 and bw == 125e3) else 0
    ih = 0 if explicit_header else 1
    num = 8 * payload_bytes - 4 * sf + 28 + 16 * (1 if crc else 0) - 20 * ih
    n_payload = 8 + max(math.ceil(num / (4 * (sf - 2 * de))) * (cr + 4), 0)
    return (preamble + 4.25) * t_sym + n_payload * t_sym


@dataclass
class Tech:
    name: str
    tx_dbm: float
    sens_dbm: float
    tx_ma: float            # average current during the active transmit/connect phase  (assumption)
    tx_s: float             # duration of that phase per reading                           (assumption)
    sleep_ua: float         # sleep current (PSM / eDRX / MCU sleep)                       (assumption)
    rx_ma: float = 0.0      # receive-window current (LoRaWAN class A)
    rx_s: float = 0.0
    needs_operator: bool = True      # needs a mobile-operator network where the device is
    recurring_fee: bool = True       # per-device subscription
    note: str = ""

    @property
    def mcl_db(self):
        return self.tx_dbm - self.sens_dbm


LORA_TOA = lora_airtime_s(PAYLOAD_B + 13, sf=12)       # 12 B payload + 13 B LoRaWAN MAC overhead
TECHS = [
    Tech("NB-IoT",            23, -129, tx_ma=110, tx_s=8.0, sleep_ua=5, note="repetition-based coverage enhancement, PSM sleep"),
    Tech("LTE-M (CE Mode B)", 23, -125, tx_ma=190, tx_s=6.0, sleep_ua=8, note="higher transmit current, shorter on-air time than NB-IoT"),
    Tech("LoRaWAN SF12",      14, -137, tx_ma=44, tx_s=LORA_TOA, sleep_ua=5, rx_ma=12, rx_s=0.4,
         needs_operator=False, recurring_fee=False, note=f"time-on-air {LORA_TOA:.2f} s (Semtech formula), two short RX windows"),
]
REDCAP = Tech("5G RedCap", 23, -100, tx_ma=250, tx_s=1.5, sleep_ua=15,
              note="representative: 20 MHz carrier, noise figure 7 dB, low-SNR MCS; eDRX sleep")


# ------------------------------------------------------------------ calculations
def path_loss(d_km, n=N_RURAL, pl0=PL_D0_DB, d0=1.0):
    return pl0 + 10 * n * math.log10(d_km / d0)


def cycle_mah(t, interval=INTERVAL_S):
    active = t.tx_s + t.rx_s
    return (t.tx_ma * t.tx_s + t.rx_ma * t.rx_s) / 3600.0 + t.sleep_ua / 1000.0 * (interval - active) / 3600.0


def battery_years(t, interval=INTERVAL_S, capacity=BATTERY_MAH, energy_scale=1.0):
    cycles = 365 * 24 * 3600 / interval
    # energy_scale scales only the ACTIVE part (sensitivity analysis on the uncertain current x time product)
    active = (t.tx_ma * t.tx_s + t.rx_ma * t.rx_s) / 3600.0 * energy_scale
    sleep = t.sleep_ua / 1000.0 * (interval - t.tx_s - t.rx_s) / 3600.0
    per_year = (active + sleep) * cycles + SELF_DISCHARGE * capacity
    return capacity / per_year, (active + sleep), per_year


def table(techs, d_km, n):
    pl = path_loss(d_km, n)
    rows = []
    for t in techs:
        margin = t.mcl_db - pl
        years, mah_cycle, mah_year = battery_years(t)
        rows.append(dict(name=t.name, mcl=t.mcl_db, pl=pl, margin=margin, years=years, mah_cycle=mah_cycle, mah_year=mah_year, tech=t))
    return rows


def fmt_rows(rows):
    out = [f"{'Technology':<20}{'Ptx':>5}{'Sens':>7}{'MCL':>7}{'PL':>8}{'Margin':>8}{'mAh/cycle':>11}{'mAh/year':>10}{'Years':>8}  Links?"]
    for r in rows:
        t = r["tech"]
        yrs = f"{r['years']:.1f}" if r["years"] < 99 else ">99"
        out.append(f"{t.name:<20}{t.tx_dbm:>5.0f}{t.sens_dbm:>7.0f}{r['mcl']:>7.0f}{r['pl']:>8.1f}{r['margin']:>8.1f}"
                   f"{r['mah_cycle']:>11.4f}{r['mah_year']:>10.0f}{yrs:>8}  {'yes' if r['margin'] > 0 else 'NO'}"
                   f"{' (>= 10 dB fade margin)' if r['margin'] >= FADE_MARGIN_DB else ''}")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--distance", type=float, default=DIST_KM, help="sensor-to-gateway distance in km")
    ap.add_argument("--n", type=float, default=N_RURAL, help="path-loss exponent")
    a = ap.parse_args()
    lines = []
    P = lambda s="": (print(s), lines.append(s))

    P("=" * 100)
    P(f"PART B: {N_DEVICES} sensors, {AREA_KM2:.0f} km2 farm, {PAYLOAD_B}-byte reading every {INTERVAL_S // 60} min, "
      f"max distance {a.distance:g} km, target {TARGET_YEARS:g} y on {BATTERY_MAH:.0f} mAh")
    P(f"Path loss: PL(d) = {PL_D0_DB} + 10 x {a.n} x log10(d/1 km);  PL({a.distance:g} km) = {path_loss(a.distance, a.n):.2f} dB")
    P("MCL = Ptx - receiver sensitivity:  " + ",  ".join(f"{t.name} {t.tx_dbm:.0f} - ({t.sens_dbm:.0f}) = {t.mcl_db:.0f} dB" for t in TECHS))
    P()
    P("Battery assumptions (representative figures, NOT measurements):")
    for t in TECHS + [REDCAP]:
        extra = f" + RX {t.rx_ma:g} mA x {t.rx_s:g} s" if t.rx_s else ""
        P(f"  {t.name:<20} TX {t.tx_ma:g} mA x {t.tx_s:.2f} s{extra}; sleep {t.sleep_ua:g} uA; {t.note}")
    P(f"  Cycles per year = {365 * 24 * 3600 / INTERVAL_S:.0f}; self-discharge {SELF_DISCHARGE * 100:.0f} %/year = {SELF_DISCHARGE * BATTERY_MAH:.0f} mAh/year")
    P()
    P("--- Comparison for the assigned scenario (manual technologies) ---")
    base = table(TECHS, a.distance, a.n)
    P(fmt_rows(base))
    P()
    P("--- Lab task 5: with 5G RedCap added ---")
    with_rc = table(TECHS + [REDCAP], a.distance, a.n)
    P(fmt_rows(with_rc))

    P()
    P("--- Requirements check (coverage, battery target, infrastructure, fees) ---")
    P(f"{'Technology':<20}{'link closes':>12}{'>=10 dB margin':>16}{f'>= {TARGET_YEARS:g} y battery':>16}{'operator net needed':>21}{'per-device fee':>16}  Feasible here?")
    for r in with_rc:
        t = r["tech"]
        feasible = r["margin"] > 0 and r["years"] >= TARGET_YEARS and not t.needs_operator and not t.recurring_fee
        P(f"{t.name:<20}{'yes' if r['margin'] > 0 else 'no':>12}{'yes' if r['margin'] >= FADE_MARGIN_DB else 'no':>16}"
          f"{'yes' if r['years'] >= TARGET_YEARS else 'no':>16}{'yes' if t.needs_operator else 'no':>21}"
          f"{'yes' if t.recurring_fee else 'no':>16}  {'YES' if feasible else 'no'}")

    # ------------------------------------------------------ LoRaWAN capacity sanity check
    P()
    P("--- LoRaWAN capacity check (200 nodes, worst case: every node at SF12) ---")
    load = N_DEVICES * LORA_TOA / INTERVAL_S
    duty = LORA_TOA / INTERVAL_S * 100
    for ch in (3, 8):
        g = load / ch
        P(f"  {ch} channels: offered load G = {g:.3f} per channel, pure-ALOHA success probability exp(-2G) = {math.exp(-2 * g) * 100:.1f} %")
    P(f"  per-node airtime duty cycle = {duty:.3f} % (EU868 sub-band limit 1 %);  one central gateway: farthest point of a "
      f"{AREA_KM2:.0f} km2 square from its centre is {math.sqrt(2) * math.sqrt(AREA_KM2) / 2:.1f} km, well inside {a.distance:g} km")

    # ------------------------------------------------------ battery sensitivity
    P()
    P("--- Sensitivity of battery life to the uncertain active-phase energy (x0.5, x1, x1.5, x2) ---")
    P(f"{'Technology':<20}" + "".join(f"{'x' + str(s):>9}" for s in (0.5, 1, 1.5, 2)))
    sens_tbl = {}
    for t in TECHS + [REDCAP]:
        ys = [battery_years(t, energy_scale=s)[0] for s in (0.5, 1, 1.5, 2)]
        sens_tbl[t.name] = ys
        P(f"{t.name:<20}" + "".join(f"{y:>9.1f}" for y in ys))

    # ------------------------------------------------------ lab task 6: exponent sweep
    P()
    P("--- Lab task 6: path-loss exponent sweep at 8 km (coverage margin in dB) ---")
    exps = (2.5, 3.0, 3.5, 4.0, 4.5)
    P(f"{'Technology':<20}" + "".join(f"{'n=' + str(e):>9}" for e in exps) + f"{'max n that closes':>20}")
    sweep = {}
    for t in TECHS + [REDCAP]:
        ms = [t.mcl_db - path_loss(DIST_KM, e) for e in exps]
        nmax = (t.mcl_db - PL_D0_DB) / (10 * math.log10(DIST_KM))
        sweep[t.name] = ms
        P(f"{t.name:<20}" + "".join(f"{m:>9.1f}" for m in ms) + f"{nmax:>20.2f}")
    P("  PL(8 km): " + ", ".join(f"n={e}: {path_loss(DIST_KM, e):.1f} dB" for e in exps))

    # ------------------------------------------------------ lab task 4: container
    P()
    P("--- Lab task 4: fleet-tracked shipping container across an ocean (single-distance link budget) ---")
    P("Requirement: stay connected for weeks, mobile, no terrestrial coverage. Same formula, over-water exponent n = 2.0.")
    P(f"{'Distance to nearest base station':<36}" + "".join(f"{t.name:>20}" for t in TECHS + [REDCAP]))
    for d in (8, 35, 100, 300):
        pl = path_loss(d, 2.0)
        P(f"{f'{d} km (PL = {pl:.1f} dB)':<36}" + "".join(f"{t.mcl_db - pl:>20.1f}" for t in TECHS + [REDCAP]))
    P("  Line-of-sight horizon for a 50 m mast and a 10 m container stack: about "
      f"{3.57 * (math.sqrt(50) + math.sqrt(10)):.0f} km, so the 100 km and 300 km rows have no radio path at all, whatever the margin says.")

    P()
    P("--- Charts ---")
    # chart 1: margins; chart 2: battery
    names = [r["name"] for r in with_rc]
    cols = ["#1f77b4", "#ff7f0e", "#2ca02c", "#9467bd"]
    fig, ax = plt.subplots(figsize=(7.5, 4))
    bars = ax.bar(names, [r["margin"] for r in with_rc], color=cols, edgecolor="black")
    for b, r in zip(bars, with_rc):
        ax.text(b.get_x() + b.get_width() / 2, r["margin"] + (0.6 if r["margin"] >= 0 else -2.2), f"{r['margin']:.1f} dB", ha="center", fontsize=9)
    ax.axhline(0, color="black", lw=1); ax.axhline(FADE_MARGIN_DB, color="grey", ls="--", lw=1, label=f"{FADE_MARGIN_DB:.0f} dB fade margin")
    ax.set_ylabel("coverage margin at 8 km (dB)"); ax.set_title(f"Coverage margin, n = {a.n}"); ax.legend(); ax.grid(axis="y", alpha=.3)
    fig.tight_layout(); fig.savefig(os.path.join(HERE, "link_margin.png"), dpi=170); plt.close(fig)

    fig, ax = plt.subplots(figsize=(7.5, 4))
    yrs = [min(r["years"], 40) for r in with_rc]
    bars = ax.bar(names, yrs, color=cols, edgecolor="black")
    for b, r in zip(bars, with_rc):
        ax.text(b.get_x() + b.get_width() / 2, min(r["years"], 40) + 0.6, f"{r['years']:.1f} y", ha="center", fontsize=9)
    ax.axhline(TARGET_YEARS, color="red", ls="--", label=f"{TARGET_YEARS:g}-year target")
    ax.set_ylabel("estimated battery life (years)"); ax.set_title("Battery life, 12 B every 30 min, 19 000 mAh"); ax.legend(); ax.grid(axis="y", alpha=.3)
    fig.tight_layout(); fig.savefig(os.path.join(HERE, "link_battery.png"), dpi=170); plt.close(fig)

    fig, ax = plt.subplots(figsize=(7.5, 4))
    for t, c in zip(TECHS + [REDCAP], cols):
        ax.plot(exps, sweep[t.name], "o-", color=c, label=t.name)
    ax.axhline(0, color="black", lw=1); ax.set_xlabel("path-loss exponent n"); ax.set_ylabel("coverage margin at 8 km (dB)")
    ax.set_title("Sensitivity to the path-loss exponent"); ax.grid(alpha=.3); ax.legend()
    fig.tight_layout(); fig.savefig(os.path.join(HERE, "link_exponent_sweep.png"), dpi=170); plt.close(fig)
    P("link_margin.png, link_battery.png, link_exponent_sweep.png written")

    with open(os.path.join(HERE, "link_budget_output.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
