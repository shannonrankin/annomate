"""
Rich Built-In Offline Demo Dataset & Query Evaluator for Annomate Demo Mode.

Allows new users and presenters to run Annomate with zero VPN, database credentials,
or Google Cloud setup—supporting multi-day filtering, PAMpal/PAMscapes R plots,
bathymetry maps, playable synthetic call spectrograms, exports, and simulated commits.
"""

from __future__ import annotations

import random
import re
from datetime import datetime, timedelta, timezone
from typing import Any


def generate_demo_annotations() -> list[dict[str, Any]]:
    """Generate 180 realistic multi-day, multi-site, multi-label bioacoustic annotations."""
    rng = random.Random(2026)
    base_dt = datetime(2009, 3, 28, 0, 12, 0, tzinfo=timezone.utc)

    sites = [
        {
            "recording_channel_id": 525768,
            "channel": 0,
            "recording_id": 1144,
            "recording_code": "MARU_SBNMS_CH0",
            "deployment_code": "NEFSC_SBNMS_200903_NOPP6_CH1",
            "latitude": 42.2051,
            "longitude": -70.4180,
            "water_depth_m": 84.0,
            "platform_type_code": "MOORING",
        },
        {
            "recording_channel_id": 525769,
            "channel": 1,
            "recording_id": 1145,
            "recording_code": "MARU_CCBAY_CH1",
            "deployment_code": "NEFSC_CCBAY_200903_NOPP2_CH2",
            "latitude": 41.9450,
            "longitude": -70.2650,
            "water_depth_m": 46.0,
            "platform_type_code": "MOORING",
        },
        {
            "recording_channel_id": 525770,
            "channel": 0,
            "recording_id": 1146,
            "recording_code": "HARP_GSC_CH0",
            "deployment_code": "NEFSC_GSC_200903_SITE3",
            "latitude": 41.4820,
            "longitude": -69.3900,
            "water_depth_m": 142.0,
            "platform_type_code": "BOTTOM_MOUNTED",
        },
    ]

    call_profiles = [
        ("RW_UPCALL", "Right whale upcall", "Eubalaena glacialis", 55.0, 215.0, 1.25),
        ("RW_UPCALL", "Right whale upcall", "Eubalaena glacialis", 62.0, 228.0, 1.35),
        ("RW_UPCALL", "Right whale upcall", "Eubalaena glacialis", 48.0, 198.0, 1.15),
        ("RW_MOAN", "Right whale moan", "Eubalaena glacialis", 42.0, 135.0, 1.85),
        ("SEWH_DS100HZ", "Sei whale 100-44 Hz downsweep", "Balaenoptera borealis", 38.0, 108.0, 1.45),
    ]
    labels = ["YES", "YES", "YES", "YES", "MAYBE", "NO", "UNVERIFIED", "YES"]
    grans = ["EVENT_CALL", "EVENT_CALL", "EVENT_CALL", "EVENT_CALL", "EVENT_ENCOUNTER", "INTERVAL"]
    analysts = ["GDAVIS", "SRANKIN", "GDAVIS"]

    rows: list[dict[str, Any]] = []
    cur_dt = base_dt
    for i in range(180):
        # Advance across ~6.5 days with realistic diel clustering around dusk/night/dawn
        step_mins = rng.randint(22, 85)
        cur_dt = cur_dt + timedelta(minutes=step_mins, seconds=rng.randint(3, 54))
        site = sites[i % len(sites)]
        ct_code, ct_name, sci_name, f0_base, f1_base, dur_base = call_profiles[i % len(call_profiles)]
        lbl = labels[i % len(labels)]
        gran = grans[i % len(grans)]

        dur = round(max(0.55, dur_base + rng.uniform(-0.28, 0.42)), 3)
        if gran == "EVENT_ENCOUNTER":
            dur = round(dur * 4.5, 3)
        elif gran == "INTERVAL":
            dur = 60.0

        end_dt = cur_dt + timedelta(seconds=dur)
        fmin = round(max(20.0, f0_base + rng.uniform(-12.0, 14.0)), 1)
        fmax = round(max(fmin + 35.0, f1_base + rng.uniform(-18.0, 24.0)), 1)
        seg_st = cur_dt.replace(minute=(cur_dt.minute // 15) * 15, second=0, microsecond=0)
        seg_et = seg_st + timedelta(minutes=15)
        offset_s = round((cur_dt - seg_st).total_seconds(), 3)
        fname = f"DEMO_{str(site['deployment_code'])[:11]}_{seg_st.strftime('%Y%m%d_%H%M%S')}.aif"

        rows.append(
            {
                "annotation_id": 10001 + i,
                "organization_code": "NEFSC",
                "call_type_code": ct_code,
                "call_type_name": ct_name,
                "scientific_name": sci_name,
                "label_code": lbl,
                "granularity_code": gran,
                "sharing_code": "PUBLIC",
                "start_time_utc": cur_dt.isoformat().replace("+00:00", "Z"),
                "end_time_utc": end_dt.isoformat().replace("+00:00", "Z"),
                "duration_secs": dur,
                "freq_min_hz": fmin,
                "freq_max_hz": fmax,
                "probability": round(rng.uniform(0.62, 0.99), 3),
                "confidence": round(rng.uniform(0.70, 1.00), 2),
                "analyst": analysts[i % len(analysts)],
                "recording_channel_id": site["recording_channel_id"],
                "procedure_id": 1,
                "procedure_name": "dclde_2013_demo_ground_truth",
                "analysis_code": "DCLDE_2013",
                "analysis_name": "DCLDE 2013 Demo Ground Truth Dataset",
                "effort_names": "DCLDE_2013",
                "channel": site["channel"],
                "recording_id": site["recording_id"],
                "recording_code": site["recording_code"],
                "sample_rate_khz": 2.0,
                "recording_uri": f"gs://demo-noaa-pam/nefsc/{site['deployment_code']}/",
                "deployment_code": site["deployment_code"],
                "latitude": site["latitude"],
                "longitude": site["longitude"],
                "water_depth_m": site["water_depth_m"],
                "platform_type_code": site["platform_type_code"],
                "obj_gsuri": f"gs://demo-noaa-pam/nefsc/{site['deployment_code']}/{fname}",
                "format": "aif",
                "audio_file_name": fname,
                "subfile_index": 0,
                "file_channel": site["channel"],
                "sample_rate_hz": 2000.0,
                "bit_depth": 16,
                "seg_start_utc": seg_st.isoformat().replace("+00:00", "Z"),
                "seg_end_utc": seg_et.isoformat().replace("+00:00", "Z"),
                "call_offset_in_seg_secs": offset_s,
                "data_byte_offset": 54,
                "data_byte_length": 3600000,
                "reconciliation_state": "consistent",
                "demo_synthetic_playable": True,
            }
        )
    return rows


_DEMO_ROWS_CACHE: list[dict[str, Any]] = []


def get_demo_rows() -> list[dict[str, Any]]:
    global _DEMO_ROWS_CACHE
    if not _DEMO_ROWS_CACHE:
        _DEMO_ROWS_CACHE = generate_demo_annotations()
    return _DEMO_ROWS_CACHE


def evaluate_demo_sql(sql: str, max_rows: int = 5000) -> tuple[list[str], list[dict[str, Any]]]:
    """
    Filter & project the built-in 180-row Demo Dataset based on predicates in the generated SQL
    so interactive filtering, scope toggling, and random sampling work instantaneously offline.
    """
    all_rows = list(get_demo_rows())
    filtered = all_rows

    # Label filter: a.label_code IN ('YES', ...)
    lbl_m = re.search(r"label_code\s+IN\s*\(([^)]+)\)", sql, re.IGNORECASE)
    if lbl_m:
        allowed = {s.strip().strip("'").upper() for s in lbl_m.group(1).split(",")}
        filtered = [r for r in filtered if r["label_code"].upper() in allowed]

    # Call type filter: a.call_type_code ILIKE 'RW_UPCALL'
    ct_m = re.search(r"call_type_code\s+(?:=|ILIKE)\s*'([^']+)'", sql, re.IGNORECASE)
    if ct_m:
        target_ct = ct_m.group(1).upper()
        filtered = [r for r in filtered if r["call_type_code"].upper() == target_ct]

    # Granularity filter: a.granularity_code = 'EVENT_CALL'
    gr_m = re.search(r"granularity_code\s*=\s*'([^']+)'", sql, re.IGNORECASE)
    if gr_m:
        target_gr = gr_m.group(1).upper()
        filtered = [r for r in filtered if r["granularity_code"].upper() == target_gr]

    # Frequency range overlap: [lo, hi]::core.freqrange
    fr_m = re.search(r"\[\s*([\d.]+)\s*,\s*([\d.]+)\s*\]'::core\.freqrange", sql, re.IGNORECASE)
    if fr_m:
        lo, hi = float(fr_m.group(1)), float(fr_m.group(2))
        filtered = [r for r in filtered if r["freq_max_hz"] >= lo and r["freq_min_hz"] <= hi]

    # Random order
    if re.search(r"ORDER\s+BY\s+random\(\)", sql, re.IGNORECASE):
        rng = random.Random()
        filtered = list(filtered)
        rng.shuffle(filtered)

    # Limit
    lim_m = re.search(r"LIMIT\s+(\d+)", sql, re.IGNORECASE)
    eff_limit = min(max_rows, int(lim_m.group(1))) if lim_m else max_rows
    filtered = filtered[:eff_limit]

    # Project columns according to joins present in SQL
    core_cols = [
        "annotation_id",
        "organization_code",
        "call_type_code",
        "label_code",
        "granularity_code",
        "sharing_code",
        "start_time_utc",
        "end_time_utc",
        "duration_secs",
        "freq_min_hz",
        "freq_max_hz",
        "probability",
        "confidence",
        "analyst",
        "recording_channel_id",
        "procedure_id",
    ]
    cols = list(core_cols)
    if "core.procedures" in sql:
        cols.extend(["procedure_name", "analysis_code", "analysis_name", "effort_names"])
    if "makara.deployments" in sql:
        cols.extend(["channel", "call_type_name", "recording_id", "recording_code", "sample_rate_khz", "recording_uri", "deployment_code", "latitude", "longitude", "water_depth_m", "platform_type_code"])
    if "core.acoustic_files" in sql:
        if "channel" not in cols:
            cols.append("channel")
        cols.extend(["obj_gsuri", "format", "audio_file_name", "subfile_index", "file_channel", "sample_rate_hz", "bit_depth", "seg_start_utc", "seg_end_utc", "call_offset_in_seg_secs", "data_byte_offset", "data_byte_length"])
    if "reconcile.recording_status" in sql:
        cols.append("reconciliation_state")

    projected = [{c: r.get(c) for c in cols} for r in filtered]
    return cols, projected
