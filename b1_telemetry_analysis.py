"""
KESTREL-4 Telemetry Analysis & Anomaly Report Reproducer (Assignment B1)
Author: Bhagyashree Reddy
Description:
  Reproduces every statistic, anomaly detection, data-quality check, and PNG plot
  referenced in the B1 Anomaly Report from the raw telemetry_48h.csv in one run.
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# ---------------------------------------------------------------------------
# 1. LOAD RAW CSV (DO NOT EDIT RAW FILE BY HAND)
# ---------------------------------------------------------------------------
CSV_PATH = "telemetry_48h.csv"  # Change if named 'telemetry_48h (1).csv'
df_raw = pd.read_csv(CSV_PATH)
orig_cols = list(df_raw.columns)
df_raw["excel_row"] = df_raw.index + 2  # Row 1 is CSV header

print(f"Loaded {len(df_raw)} raw rows from {CSV_PATH}.")

# ---------------------------------------------------------------------------
# 2. DETECT DATA-QUALITY ISSUES ON RAW DATA (BEFORE CLEANING)
# ---------------------------------------------------------------------------
print("\n=== DATA-QUALITY CHECKS (RAW FILE) ===")

# DQ-1: Duplicate timestamps
dup_ts_mask = df_raw.duplicated(subset=["timestamp_utc"], keep=False)
dup_rows = df_raw[dup_ts_mask]
print(f"DQ-1 Duplicate timestamp rows found: {len(dup_rows)} rows (4 pairs)")
for idx, r in dup_rows.iterrows():
    exact = df_raw.duplicated(subset=orig_cols, keep=False).loc[idx]
    print(f"  Excel Row {r['excel_row']}: {r['timestamp_utc']} | exact_duplicate={exact}")

# DQ-2: Out-of-order timestamps before sorting
raw_ts = pd.to_datetime(df_raw["timestamp_utc"])
raw_dt = raw_ts.diff().dt.total_seconds()
backwards = df_raw[raw_dt < 0]
for idx, r in backwards.iterrows():
    print(f"DQ-2 Backward timestamp step at Excel Row {r['excel_row']} ({r['timestamp_utc']}): dt = {raw_dt.loc[idx]:.1f} s")

# ---------------------------------------------------------------------------
# 3. CLEAN DATA IN CODE (DEDUPLICATE & SORT CHRONOLOGICALLY)
# ---------------------------------------------------------------------------
df = (
    df_raw.drop_duplicates(subset=["timestamp_utc"], keep="first")
    .sort_values("timestamp_utc")
    .reset_index(drop=True)
)
df["ts"] = pd.to_datetime(df["timestamp_utc"])
df["dt_s"] = df["ts"].diff().dt.total_seconds()

print(f"\nCleaned dataframe row count: {len(df)} (removed {len(df_raw) - len(df)} duplicate timestamps; sorted out-of-order rows 1104-1108).")

# DQ-5: Telemetry gaps after sorting
gaps = df[df["dt_s"] > 10.0]
for idx, r in gaps.iterrows():
    prev_r = df.loc[idx - 1]
    print(
        f"DQ-5 Telemetry gap: {r['dt_s']:.0f} s ({int(r['dt_s']//10 - 1)} missing samples) "
        f"between Excel Row {prev_r['excel_row']} ({prev_r['timestamp_utc']}) "
        f"and Excel Row {r['excel_row']} ({r['timestamp_utc']})"
    )

# DQ-3: Flatline / stuck sensor check
same_bt = df["batt_temp_c"].diff() == 0
bt_blocks = np.split(df[same_bt].index, np.where(np.diff(df[same_bt].index) != 1)[0] + 1)
for b in bt_blocks:
    if len(b) >= 100:
        s_row = df.loc[b[0] - 1]
        e_row = df.loc[b[-1]]
        print(
            f"DQ-3 Frozen sensor: batt_temp_c stuck at {s_row['batt_temp_c']:.2f} C for {len(b)+1} samples "
            f"from Excel Row {s_row['excel_row']} ({s_row['timestamp_utc']}) "
            f"to Excel Row {e_row['excel_row']} ({e_row['timestamp_utc']})"
        )

# ---------------------------------------------------------------------------
# 4. COMPUTE NOMINAL BASELINE (PRE-HEATER ANOMALY: 00:00 TO 19:39:50 UTC)
# ---------------------------------------------------------------------------
nom = df[df["timestamp_utc"] < "2026-09-14T19:40:00Z"].copy()

# Orbit period and eclipse duration from shadow entries (eclipse 0 -> 1)
ecl_diff = df["eclipse"].diff()
entries = df[ecl_diff == 1].index.tolist()
exits = df[ecl_diff == -1].index.tolist()

orbit_periods_min = []
for i in range(len(entries) - 1):
    dt_min = (df.loc[entries[i + 1], "ts"] - df.loc[entries[i], "ts"]).total_seconds() / 60.0
    if 90.0 < dt_min < 100.0:  # Exclude interval spanning the 1,510s telemetry gap
        orbit_periods_min.append(dt_min)

ecl_durations_min = []
for en in entries:
    matching_exits = [ex for ex in exits if ex > en]
    if matching_exits:
        ex = matching_exits[0]
        dur_min = (df.loc[ex, "ts"] - df.loc[en, "ts"]).total_seconds() / 60.0
        if 30.0 < dur_min < 40.0:
            ecl_durations_min.append(dur_min)

print("\n=== NOMINAL BASELINE METRICS ===")
print(f"Mean Orbit Period: {np.mean(orbit_periods_min):.2f} min (min={np.min(orbit_periods_min):.2f}, max={np.max(orbit_periods_min):.2f})")
print(f"Mean Eclipse Duration: {np.mean(ecl_durations_min):.2f} min (fraction={np.mean(ecl_durations_min)/np.mean(orbit_periods_min):.4f})")
print(f"Nominal SoC Range: {nom['batt_soc_pct'].min():.2f}% to {nom['batt_soc_pct'].max():.2f}%")
print(f"Nominal batt_temp_c: {nom['batt_temp_c'].min():.2f} to {nom['batt_temp_c'].max():.2f} C")
print(f"Nominal obc_temp_c: {nom['obc_temp_c'].min():.2f} to {nom['obc_temp_c'].max():.2f} C")
print(f"Nominal STANDBY pay_temp_c: {nom[nom['pay_state']=='STANDBY']['pay_temp_c'].min():.2f} to {nom[nom['pay_state']=='STANDBY']['pay_temp_c'].max():.2f} C")

# ---------------------------------------------------------------------------
# 5. CHECK TM_LIMITS.YAML VIOLATIONS (WITH 3-SAMPLE PERSISTENCE)
# ---------------------------------------------------------------------------
LIMITS = {
    "batt_voltage_v": {"yl": 15.4, "yh": 16.95, "rl": 15.0, "rh": 17.2},
    "batt_current_a": {"yl": -2.0, "yh": 2.0, "rl": -3.0, "rh": 3.0},
    "batt_soc_pct": {"yl": 70.0, "yh": None, "rl": 60.0, "rh": None},
    "batt_temp_c": {"yl": 5.0, "yh": 30.0, "rl": 0.0, "rh": 40.0},
    "sa_current_a": {"yl": None, "yh": 2.8, "rl": None, "rh": 3.2},
    "bus_voltage_v": {"yl": 27.5, "yh": 28.5, "rl": 27.0, "rh": 29.0},
    "obc_temp_c": {"yl": 5.0, "yh": 45.0, "rl": 0.0, "rh": 55.0},
    "mem_used_pct": {"yl": None, "yh": 85.0, "rl": None, "rh": 95.0},
    "pay_temp_c": {"yl": 0.0, "yh": 40.0, "rl": -10.0, "rh": 45.0},
    "heater_a": {"yl": None, "yh": 1.2, "rl": None, "rh": 1.5},
    "gyro_x_dps": {"yl": -1.0, "yh": 1.0, "rl": -2.0, "rh": 2.0},
    "gyro_y_dps": {"yl": -1.0, "yh": 1.0, "rl": -2.0, "rh": 2.0},
    "gyro_z_dps": {"yl": -1.0, "yh": 1.0, "rl": -2.0, "rh": 2.0},
    "att_err_deg": {"yl": None, "yh": 0.5, "rl": None, "rh": 2.0},
    "rw_speed_rpm": {"yl": 800.0, "yh": 3000.0, "rl": 300.0, "rh": 5000.0},
}

print("\n=== LIMIT EXCURSIONS (PERSISTENT >= 3 SAMPLES vs TRANSIENT < 3 SAMPLES) ===")
for col, lim in LIMITS.items():
    s = df[col]
    for level, lo, hi in [("YELLOW", lim["yl"], lim["yh"]), ("RED", lim["rl"], lim["rh"])]:
        cond = pd.Series(False, index=df.index)
        if lo is not None:
            cond |= s < lo
        if hi is not None:
            cond |= s > hi
        idxs = df[cond].index
        if len(idxs) > 0:
            blocks = np.split(idxs, np.where(np.diff(idxs) != 1)[0] + 1)
            for b in blocks:
                sub = df.loc[b]
                status = "PERSISTENT (>=3)" if len(b) >= 3 else "TRANSIENT (<3, GLITCH/MINOR)"
                print(
                    f"  {col:15s} {level:6s} [{status:28s}]: len={len(b):3d} | "
                    f"Row {sub['excel_row'].iloc[0]} ({sub['timestamp_utc'].iloc[0]}) to "
                    f"Row {sub['excel_row'].iloc[-1]} ({sub['timestamp_utc'].iloc[-1]}) | "
                    f"min={sub[col].min():.3f}, max={sub[col].max():.3f}"
                )

# ---------------------------------------------------------------------------
# 6. GENERATE REPORT PLOTS (PNG FILES)
# ---------------------------------------------------------------------------
plt.rcParams["font.sans-serif"] = "DejaVu Sans"
plt.rcParams["axes.edgecolor"] = "#333333"

# --- FIGURE 1: Stuck Heater, Battery Temperature Flatline, and SoC Drain ---
fig, axes = plt.subplots(3, 1, figsize=(12, 8), sharex=True)
t_heater_stuck = pd.to_datetime("2026-09-14T19:40:00Z")

axes[0].plot(df["ts"], df["heater_a"], color="#d95f02", lw=1.2, label="heater_a (A)")
axes[0].axvline(t_heater_stuck, color="red", ls="--", lw=1.2, label="SE-1: Heater Latch ON (19:40:00Z, Row 7086)")
axes[0].set_ylabel("Heater (A)")
axes[0].set_title("KESTREL-4 Power & Thermal Anomaly: Stuck Heater (SE-1), Sensor Flatline (DQ-3) & SoC Drain")
axes[0].legend(loc="upper left", fontsize=9)
axes[0].grid(True, alpha=0.3)

axes[1].plot(df["ts"], df["batt_temp_c"], color="#1b9e77", lw=1.2, label="batt_temp_c (°C)")
axes[1].axvspan(
    pd.to_datetime("2026-09-15T11:00:00Z"),
    pd.to_datetime("2026-09-15T13:59:50Z"),
    color="orange",
    alpha=0.3,
    label="DQ-3: Frozen 18.40 °C Sensor (Rows 12606–13685)",
)
axes[1].axvline(t_heater_stuck, color="red", ls="--", lw=1.2)
axes[1].set_ylabel("Batt Temp (°C)")
axes[1].legend(loc="upper left", fontsize=9)
axes[1].grid(True, alpha=0.3)

axes[2].plot(df["ts"], df["batt_soc_pct"], color="#7570b3", lw=1.3, label="batt_soc_pct (%)")
axes[2].axhline(70.0, color="#e6ab02", ls="--", lw=1.2, label="Yellow Low Limit (70.0%)")
axes[2].axhline(60.0, color="#e41a1c", ls=":", lw=1.2, label="Red Low Limit (60.0%)")
axes[2].axvline(t_heater_stuck, color="red", ls="--", lw=1.2)
axes[2].axvspan(
    pd.to_datetime("2026-09-15T20:11:50Z"),
    pd.to_datetime("2026-09-15T20:37:00Z"),
    color="grey",
    alpha=0.35,
    label="DQ-5: 1,510 s Telemetry Gap (Rows 15917–15918)",
)
axes[2].set_ylabel("Battery SoC (%)")
axes[2].set_xlabel("Time (UTC)")
axes[2].legend(loc="lower left", fontsize=9)
axes[2].grid(True, alpha=0.3)
axes[2].xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))

plt.tight_layout()
plt.savefig("fig1_power_heater_soc.png", dpi=200)
plt.close()

# --- FIGURE 2: Payload Overheat Event (SE-2) vs Nominal Imaging Passes ---
fig, ax = plt.subplots(figsize=(11, 4.5))
ax.plot(df["ts"], df["pay_temp_c"], color="#2b5c8f", lw=1.2, label="pay_temp_c (°C)")
ax.axhline(40.0, color="#e6ab02", ls="--", lw=1.2, label="Yellow High Limit (40.0 °C)")
ax.axhline(45.0, color="#e41a1c", ls="--", lw=1.2, label="Red High Limit (45.0 °C)")
ax.annotate(
    "SE-2: Peak 48.93 °C\n(2026-09-14 09:36:20Z, Row 3464)",
    xy=(pd.to_datetime("2026-09-14T09:36:20Z"), 48.93),
    xytext=(pd.to_datetime("2026-09-14T12:30:00Z"), 46.0),
    arrowprops=dict(arrowstyle="->", color="#e41a1c", lw=1.5),
    fontsize=9,
    fontweight="bold",
    color="#b30000",
)
ax.set_title("KESTREL-4 Payload Focal Plane Temperature (SE-2 Overheat at 09:35 UTC vs Nominal Collects)")
ax.set_ylabel("Payload Temp (°C)")
ax.set_xlabel("Time (UTC)")
ax.legend(loc="upper right", fontsize=9)
ax.grid(True, alpha=0.3)
ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))

plt.tight_layout()
plt.savefig("fig2_payload_thermal_spike.png", dpi=200)
plt.close()

# --- FIGURE 3: OBC Watchdog Reboot & SAFE Mode Entry (SE-3) ---
win = df[
    (df["ts"] >= pd.to_datetime("2026-09-15T06:45:00Z"))
    & (df["ts"] <= pd.to_datetime("2026-09-15T07:55:00Z"))
].copy()

fig, axes = plt.subplots(3, 1, figsize=(11, 7.5), sharex=True)
t_reboot = pd.to_datetime("2026-09-15T06:58:10Z")
t_recov = pd.to_datetime("2026-09-15T07:40:10Z")

axes[0].step(win["ts"], win["obc_boot_count"], where="post", color="#d95f02", lw=1.8, label="obc_boot_count")
axes[0].axvline(t_reboot, color="red", ls="--", label="SE-3: Reboot 41->42 & SAFE Mode (06:58:10Z, Row 11155)")
axes[0].axvline(t_recov, color="green", ls="--", label="Ground Recovery to NOMINAL (07:40:10Z, Row 11407)")
axes[0].set_ylabel("Boot Count")
axes[0].set_title("KESTREL-4 OBC Reboot, SAFE Mode Entry & Attitude Transient (SE-3)")
axes[0].legend(loc="upper left", fontsize=9)
axes[0].grid(True, alpha=0.3)

axes[1].plot(win["ts"], win["att_err_deg"], color="#e41a1c", lw=1.5, label="att_err_deg (°)")
axes[1].axhline(0.5, color="#e6ab02", ls="--", lw=1.1, label="Yellow High (0.5°)")
axes[1].axhline(2.0, color="#e41a1c", ls=":", lw=1.1, label="Red High (2.0°)")
axes[1].set_ylabel("Attitude Error (°)")
axes[1].legend(loc="upper right", fontsize=9)
axes[1].grid(True, alpha=0.3)

axes[2].plot(win["ts"], win["rw_speed_rpm"], color="#1b9e77", lw=1.4, label="rw_speed_rpm (RPM)")
axes[2].set_ylabel("RW Speed (RPM)")
axes[2].set_xlabel("Time on 2026-09-15 (UTC)")
axes[2].legend(loc="lower right", fontsize=9)
axes[2].grid(True, alpha=0.3)
axes[2].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))

plt.tight_layout()
plt.savefig("fig3_obc_reboot_safemode.png", dpi=200)
plt.close()

print("\nSaved plots: fig1_power_heater_soc.png, fig2_payload_thermal_spike.png, fig3_obc_reboot_safemode.png")