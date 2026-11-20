"""
Standardized Annotation Alignment, Pre-Flight Validation & Database Ingestion Engine.

Aligns heterogeneous bioacoustic outputs:
- Raven Pro Selection Tables (.txt / .tsv)
- Triton Logger / Remora Spreadsheets (.csv / .xls / .xlsx)
- PAMGuard Detection Exports (.csv / .tsv)
- Generic CSV / TSV / Excel analyst & detector logs

into the authoritative `nmfs_annotation_db` (`core.annotations`) schema:
- recording_channel_id (resolved directly or matched by acoustic file name + channel / timestamp)
- procedure_id (selected or newly created under core.analyses)
- organization_code (denormalized, required for partitioning/permissions)
- call_type_code (mapped against makara.call_types)
- label_code (mapped against core.annotation_labels: YES, NO, MAYBE, PROTOCOL_*, UNVERIFIED)
- granularity_code (mapped against makara.analysis_granularity_types)
- sharing_code (mapped against core.sharing_scopes)
- tstzrange ([start_time_utc, end_time_utc))
- freqrange ([freq_min_hz, freq_max_hz])
- probability, confidence, analyst (FIRSTINITIAL+LAST)
"""

from __future__ import annotations

import io
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .db import get_connection, serialize_value

PRESET_PROFILES: dict[str, dict[str, Any]] = {
    "raven_pro": {
        "name": "Raven Pro Selection Table (.txt / TSV)",
        "description": "Cornell Lab Raven Pro 1.5 / 1.6 / 2.0 tab-delimited selection tables with file-relative offsets or Date/Time columns.",
        "column_hints": {
            "begin_offset_sec": ["Begin Time (s)", "Begin Time", "Delta Time (s)"],
            "end_offset_sec": ["End Time (s)", "End Time"],
            "start_time_utc": ["Begin Date Time", "Real Start Datetime", "Start UTC"],
            "end_time_utc": ["End Date Time", "End UTC"],
            "freq_min_hz": ["Low Freq (Hz)", "Low Freq", "Min Freq (Hz)"],
            "freq_max_hz": ["High Freq (Hz)", "High Freq", "Max Freq (Hz)"],
            "source_file": ["Begin File", "Begin Path", "File Name"],
            "channel": ["Channel"],
            "call_type_code": ["Call Type", "Annotation", "Sound Type", "Species"],
            "label_code": ["Verified", "Label", "Detection", "Valid"],
            "confidence": ["Confidence", "Score"],
            "probability": ["Probability", "Detector Score"],
            "analyst": ["Analyst", "Reviewer", "Observer"],
        },
        "one_based_channel": True,
    },
    "triton_logger": {
        "name": "Triton Logger / Remora (.xls / .xlsx / .csv)",
        "description": "Scripps Whale Acoustics Lab Triton Logger & Remora event logs with absolute UTC Start/End times and Hz parameters.",
        "column_hints": {
            "start_time_utc": ["Start time", "Start Time", "Event Start", "UTC Start"],
            "end_time_utc": ["End time", "End Time", "Event End", "UTC End"],
            "freq_min_hz": ["Parameter 1 (Hz)", "Min Freq (Hz)", "Low Freq (Hz)", "Parameter 1"],
            "freq_max_hz": ["Parameter 2 (Hz)", "Max Freq (Hz)", "High Freq (Hz)", "Parameter 2"],
            "source_file": ["Input file", "XWAV File", "Audio File"],
            "channel": ["Channel", "Ch"],
            "call_type_code": ["Call", "Call Type", "Species Code"],
            "label_code": ["Verified", "Status", "Label"],
            "analyst": ["User ID", "Analyst", "Logger ID"],
            "confidence": ["Confidence", "SNR"],
        },
        "one_based_channel": True,
    },
    "pamguard": {
        "name": "PAMGuard Detection Export (.csv)",
        "description": "PAMGuard Click / Whistle & Moan / Deep Learning detector tables using UTC + Duration_ms and ChannelMap bitmasks.",
        "column_hints": {
            "start_time_utc": ["UTC", "PCTime", "StartUTC", "DateTime"],
            "duration_ms": ["Duration_ms", "Duration (ms)", "Duration"],
            "end_time_utc": ["EndUTC", "EndDateTime"],
            "freq_min_hz": ["MinFreq_Hz", "LowFreq", "MinFreq", "startFreq"],
            "freq_max_hz": ["MaxFreq_Hz", "HighFreq", "MaxFreq", "endFreq"],
            "channel": ["ChannelMap", "Channel"],
            "call_type_code": ["SpeciesClass", "Classification", "CallType"],
            "label_code": ["ValidationStatus", "Verified", "Label"],
            "probability": ["DetectorScore", "Probability", "ClassificationScore"],
            "analyst": ["Operator", "Analyst"],
        },
        "one_based_channel": True,
    },
    "custom_csv": {
        "name": "Generic CSV / Excel Table",
        "description": "Flexible tabular import with auto-matched column headers and custom vocabulary mapping.",
        "column_hints": {
            "start_time_utc": ["start_time_utc", "start_utc", "start_time", "start", "begin_datetime", "timestamp"],
            "end_time_utc": ["end_time_utc", "end_utc", "end_time", "end", "end_datetime"],
            "begin_offset_sec": ["begin_time_s", "start_sec", "offset_sec"],
            "end_offset_sec": ["end_time_s", "end_sec"],
            "freq_min_hz": ["freq_min_hz", "min_freq_hz", "low_freq_hz", "fmin", "min_freq"],
            "freq_max_hz": ["freq_max_hz", "max_freq_hz", "high_freq_hz", "fmax", "max_freq"],
            "source_file": ["file_name", "filename", "audio_file", "obj_gsuri"],
            "channel": ["channel", "ch", "file_channel"],
            "recording_channel_id": ["recording_channel_id"],
            "call_type_code": ["call_type_code", "call_type", "call", "species"],
            "label_code": ["label_code", "label", "verified", "status"],
            "granularity_code": ["granularity_code", "granularity"],
            "sharing_code": ["sharing_code", "sharing"],
            "probability": ["probability", "prob", "score"],
            "confidence": ["confidence", "conf"],
            "analyst": ["analyst", "reviewer", "user"],
        },
        "one_based_channel": False,
    },
}

DEFAULT_LABEL_SYNONYMS: dict[str, str] = {
    "yes": "YES",
    "y": "YES",
    "1": "YES",
    "true": "YES",
    "pos": "YES",
    "positive": "YES",
    "detected": "YES",
    "valid": "YES",
    "verified": "YES",
    "no": "NO",
    "n": "NO",
    "0": "NO",
    "false": "NO",
    "neg": "NO",
    "negative": "NO",
    "fp": "NO",
    "false_positive": "NO",
    "maybe": "MAYBE",
    "m": "MAYBE",
    "2": "MAYBE",
    "?": "MAYBE",
    "uncertain": "MAYBE",
    "possible": "MAYBE",
    "possibly_detected": "MAYBE",
    "21": "PROTOCOL_YES",
    "protocol_yes": "PROTOCOL_YES",
    "20": "PROTOCOL_NO",
    "protocol_no": "PROTOCOL_NO",
    "22": "PROTOCOL_MAYBE",
    "protocol_maybe": "PROTOCOL_MAYBE",
    "99": "UNVERIFIED",
    "unverified": "UNVERIFIED",
    "candidate": "UNVERIFIED",
    "auto": "UNVERIFIED",
}

DEFAULT_CALL_SYNONYMS: dict[str, str] = {
    "upcall": "RW_UPCALL",
    "up-call": "RW_UPCALL",
    "rw_upcall": "RW_UPCALL",
    "narw_upcall": "RW_UPCALL",
    "right whale upcall": "RW_UPCALL",
    "moan": "RW_MOAN",
    "rw_moan": "RW_MOAN",
    "whistle": "OD_WHIS",
    "click": "OD_CLICK",
    "buzz": "OD_BUZZ",
    "blue a": "BLWH_A",
    "blue b": "BLWH_B",
    "blue d": "BLWH_D",
    "cod grunt": "COD_GRUNT",
}

DEFAULT_GRANULARITY_SYNONYMS: dict[str, str] = {
    "call": "EVENT_CALL",
    "event_call": "EVENT_CALL",
    "single call": "EVENT_CALL",
    "encounter": "EVENT_ENCOUNTER",
    "event_encounter": "EVENT_ENCOUNTER",
    "binned": "INTERVAL",
    "interval": "INTERVAL",
    "bin": "INTERVAL",
}

FILENAME_TS_PATTERNS = [
    # e.g. 20090328_120000 or 20090328T120000
    (re.compile(r"(20\d{2})(\d{2})(\d{2})[_T\-]?(\d{2})(\d{2})(\d{2})"), False),
    # e.g. HARP 160402_000000 -> 2016-04-02 00:00:00
    (re.compile(r"(?<!\d)(\d{2})(\d{2})(\d{2})[_T\-](\d{2})(\d{2})(\d{2})(?!\d)"), True),
]


def parse_uploaded_table(file_bytes: bytes, filename: str) -> tuple[pd.DataFrame, str]:
    """Read uploaded Raven TSV, CSV, or Excel file into a clean DataFrame and detect preset."""
    lower_name = (filename or "upload.csv").lower()
    if lower_name.endswith((".xlsx", ".xls")):
        df = pd.read_excel(io.BytesIO(file_bytes))
    else:
        text_sample = file_bytes[:4096].decode("utf-8", errors="replace")
        if "\t" in text_sample and text_sample.count("\t") >= text_sample.count(","):
            df = pd.read_csv(io.BytesIO(file_bytes), sep="\t")
        else:
            df = pd.read_csv(io.BytesIO(file_bytes))

    df.columns = [str(c).strip() for c in df.columns]
    cols_set = {c.lower() for c in df.columns}

    if "begin time (s)" in cols_set or ("selection" in cols_set and "low freq (hz)" in cols_set):
        detected = "raven_pro"
    elif "input file" in cols_set or "parameter 1 (hz)" in cols_set:
        detected = "triton_logger"
    elif "channelmap" in cols_set or "duration_ms" in cols_set or "speciesclass" in cols_set:
        detected = "pamguard"
    else:
        detected = "custom_csv"

    return df, detected


def suggest_column_mapping(columns: list[str], preset: str) -> dict[str, str | None]:
    """Auto-suggest mapping from uploaded columns to standardized fields."""
    profile = PRESET_PROFILES.get(preset, PRESET_PROFILES["custom_csv"])
    hints = profile["column_hints"]
    lower_lookup = {c.lower(): c for c in columns}

    all_target_fields = [
        "recording_channel_id",
        "source_file",
        "channel",
        "start_time_utc",
        "end_time_utc",
        "begin_offset_sec",
        "end_offset_sec",
        "duration_ms",
        "freq_min_hz",
        "freq_max_hz",
        "call_type_code",
        "label_code",
        "granularity_code",
        "sharing_code",
        "probability",
        "confidence",
        "analyst",
    ]
    mapping: dict[str, str | None] = dict.fromkeys(all_target_fields)
    for field, candidates in hints.items():
        for cand in candidates:
            if cand.lower() in lower_lookup:
                mapping[field] = lower_lookup[cand.lower()]
                break
    # Fallback loose match across custom_csv hints
    for field, candidates in PRESET_PROFILES["custom_csv"]["column_hints"].items():
        if mapping.get(field) is None:
            for cand in candidates:
                if cand.lower() in lower_lookup:
                    mapping[field] = lower_lookup[cand.lower()]
                    break
    return mapping


def _infer_file_anchor_utc(filename: str) -> datetime | None:
    if not filename:
        return None
    for regex, two_digit_year in FILENAME_TS_PATTERNS:
        m = regex.search(filename)
        if m:
            yr = int(m.group(1))
            if two_digit_year:
                yr += 2000
            try:
                return datetime(
                    yr,
                    int(m.group(2)),
                    int(m.group(3)),
                    int(m.group(4)),
                    int(m.group(5)),
                    int(m.group(6)),
                    tzinfo=timezone.utc,
                )
            except ValueError:
                continue
    return None


def _parse_any_utc(val: Any) -> datetime | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip()
    if not s or s.lower() == "nan":
        return None
    try:
        ts = pd.to_datetime(s, utc=True)
        if pd.isna(ts):
            return None
        return ts.to_pydatetime()
    except Exception:
        return None


def _lookup_db_file_anchors(
    filenames: list[str],
    recording_channel_id: Any | None = None,
) -> dict[str, dict[str, Any]]:
    """Resolve uploaded source filenames against core.acoustic_files + core.audio_segments if connected."""
    clean_names = list({Path(str(f)).name for f in filenames if f and str(f).lower() != "nan"})
    if not clean_names:
        return {}
    result: dict[str, dict[str, Any]] = {}
    try:
        with get_connection(autocommit=True) as conn, conn.cursor() as cur:
            cur.execute("SET statement_timeout = '4s'")
            if recording_channel_id is not None and str(recording_channel_id).strip() != "":
                cur.execute(
                    """
                        SELECT af.name,
                               seg.recording_channel_id,
                               seg.file_channel,
                               lower(seg.tstzrange) AS seg_start_utc,
                               upper(seg.tstzrange) AS seg_end_utc
                        FROM core.audio_segments seg
                        JOIN core.acoustic_files af ON af.id = seg.acoustic_file_id
                        WHERE seg.recording_channel_id = %s
                          AND af.name = ANY(%s)
                        ORDER BY seg.subfile_index ASC
                        """,
                    (int(float(recording_channel_id)), clean_names),
                )
            else:
                cur.execute(
                    """
                        SELECT af.name,
                               seg.recording_channel_id,
                               seg.file_channel,
                               lower(seg.tstzrange) AS seg_start_utc,
                               upper(seg.tstzrange) AS seg_end_utc
                        FROM core.acoustic_files af
                        JOIN core.audio_segments seg ON seg.acoustic_file_id = af.id
                        WHERE af.name = ANY(%s)
                          AND seg.recording_channel_id IS NOT NULL
                        ORDER BY seg.subfile_index ASC
                        LIMIT 200
                        """,
                    (clean_names,),
                )
            for r in cur.fetchall():
                key = f"{r['name']}::{r['file_channel']}"
                if key not in result:
                    result[key] = dict(r)
                if r["name"] not in result:
                    result[r["name"]] = dict(r)
    except Exception:
        pass
    return result


def align_and_validate_dataframe(
    df: pd.DataFrame,
    mapping: dict[str, str | None],
    defaults: dict[str, Any],
    vocab_maps: dict[str, dict[str, str]] | None = None,
    catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Transform raw bioacoustic table rows into standardized `core.annotations` records
    and perform full pre-flight validation against DB schema & foreign-key constraints.
    """
    vocab_maps = vocab_maps or {}
    label_map = {**DEFAULT_LABEL_SYNONYMS, **{k.lower(): v for k, v in vocab_maps.get("label_code", {}).items()}}
    call_map = {**DEFAULT_CALL_SYNONYMS, **{k.lower(): v for k, v in vocab_maps.get("call_type_code", {}).items()}}
    gran_map = {**DEFAULT_GRANULARITY_SYNONYMS, **{k.lower(): v for k, v in vocab_maps.get("granularity_code", {}).items()}}

    valid_orgs = {o["code"] for o in (catalog or {}).get("organizations", [])}
    valid_calls = {c["code"] for c in (catalog or {}).get("call_types", [])}
    valid_labels = {lbl["code"] for lbl in (catalog or {}).get("labels", [])} or {
        "YES", "NO", "MAYBE", "PROTOCOL_YES", "PROTOCOL_NO", "PROTOCOL_MAYBE", "UNVERIFIED"
    }
    valid_grans = {g["code"] for g in (catalog or {}).get("granularities", [])}
    valid_sharings = {s["code"] for s in (catalog or {}).get("sharing_scopes", [])} or {
        "ORG_INTERNAL", "NOAA_INTERNAL", "PACM_SUMMARY_ONLY", "PUBLIC_DATA_ONLY", "PUBLIC"
    }

    freq_unit_khz = bool(defaults.get("freq_in_khz", False))
    one_based_ch = bool(defaults.get("one_based_channel", True))
    fallback_anchor_dt = _parse_any_utc(defaults.get("file_start_anchor_utc"))

    source_file_col = mapping.get("source_file")
    file_list = df[source_file_col].dropna().astype(str).tolist() if source_file_col and source_file_col in df.columns else []
    db_file_anchors = _lookup_db_file_anchors(file_list, defaults.get("recording_channel_id"))

    aligned_rows: list[dict[str, Any]] = []
    issue_summary: dict[str, int] = {}

    def record_issue(row_issues: list[str], msg: str):
        row_issues.append(msg)
        issue_summary[msg] = issue_summary.get(msg, 0) + 1

    for idx, row in df.iterrows():
        row_issues: list[str] = []

        def get_col(field: str, _row: Any = row) -> Any:
            col = mapping.get(field)
            if col and col in df.columns:
                v = _row[col]
                if pd.isna(v):
                    return None
                return v
            return None

        src_file = str(get_col("source_file") or "").strip()
        raw_ch = get_col("channel")
        ch_num = 0
        if raw_ch is not None:
            try:
                ch_int = int(float(raw_ch))
                ch_num = max(0, ch_int - 1) if one_based_ch and ch_int >= 1 else max(0, ch_int)
            except Exception:
                ch_num = 0

        # Resolve recording_channel_id
        rc_id_val = get_col("recording_channel_id") or defaults.get("recording_channel_id")
        db_anchor = db_file_anchors.get(f"{Path(src_file).name}::{ch_num}") or db_file_anchors.get(Path(src_file).name) if src_file else None
        if rc_id_val is None and db_anchor and db_anchor.get("recording_channel_id"):
            rc_id_val = db_anchor["recording_channel_id"]

        rc_id: int | None = None
        if rc_id_val is not None and str(rc_id_val).strip() != "":
            try:
                rc_id = int(float(rc_id_val))
            except Exception:
                record_issue(row_issues, "Invalid recording_channel_id integer")
        else:
            record_issue(row_issues, "Missing recording_channel_id (select target channel or match known file)")

        # Resolve start_time_utc & end_time_utc
        start_dt = _parse_any_utc(get_col("start_time_utc"))
        end_dt = _parse_any_utc(get_col("end_time_utc"))

        if start_dt is None:
            beg_off = get_col("begin_offset_sec")
            if beg_off is not None:
                anchor = (
                    (db_anchor["seg_start_utc"] if db_anchor and db_anchor.get("seg_start_utc") else None)
                    or _infer_file_anchor_utc(src_file)
                    or fallback_anchor_dt
                )
                if anchor is not None:
                    start_dt = anchor + timedelta(seconds=float(beg_off))
                    end_off = get_col("end_offset_sec")
                    if end_off is not None and end_dt is None:
                        end_dt = anchor + timedelta(seconds=float(end_off))
                else:
                    record_issue(row_issues, "Relative Begin Time (s) requires file timestamp or File Start UTC anchor")

        if start_dt is not None and end_dt is None:
            dur_ms = get_col("duration_ms")
            if dur_ms is not None:
                end_dt = start_dt + timedelta(milliseconds=float(dur_ms))

        if start_dt is None or end_dt is None:
            record_issue(row_issues, "Missing or unparseable UTC start/end timestamp")
        elif end_dt <= start_dt:
            record_issue(row_issues, "Temporal range invalid: end_time_utc must be > start_time_utc")

        # Frequency bounds
        fmin_raw = get_col("freq_min_hz")
        fmax_raw = get_col("freq_max_hz")
        fmin_hz: float | None = None
        fmax_hz: float | None = None
        if fmin_raw is not None and fmax_raw is not None:
            try:
                scale = 1000.0 if freq_unit_khz else 1.0
                fmin_hz = round(float(fmin_raw) * scale, 2)
                fmax_hz = round(float(fmax_raw) * scale, 2)
                if fmin_hz < 0 or fmax_hz <= fmin_hz:
                    record_issue(row_issues, "Frequency range invalid: require 0 <= freq_min_hz < freq_max_hz")
            except Exception:
                record_issue(row_issues, "Unparseable frequency values")

        # Controlled codes
        org_code = str(defaults.get("organization_code") or "").strip().upper()
        if not org_code:
            record_issue(row_issues, "Missing organization_code")
        elif valid_orgs and org_code not in valid_orgs:
            record_issue(row_issues, f"Unknown organization_code '{org_code}'")

        raw_call = str(get_col("call_type_code") or defaults.get("call_type_code") or "").strip()
        call_code = call_map.get(raw_call.lower(), raw_call.upper() if raw_call else "")
        if not call_code:
            record_issue(row_issues, "Missing call_type_code")
        elif valid_calls and call_code not in valid_calls:
            # Try case-insensitive match against catalog
            ci_match = next((c for c in valid_calls if c.lower() == call_code.lower()), None)
            if ci_match:
                call_code = ci_match
            else:
                record_issue(row_issues, f"Call type '{call_code}' not in makara.call_types (use vocabulary mapper)")

        raw_label = str(get_col("label_code") or defaults.get("label_code") or "YES").strip()
        label_code = label_map.get(raw_label.lower(), raw_label.upper())
        if label_code not in valid_labels:
            record_issue(row_issues, f"Label '{raw_label}' must map to core.annotation_labels (YES/NO/MAYBE/UNVERIFIED)")

        raw_gran = str(get_col("granularity_code") or defaults.get("granularity_code") or "EVENT_CALL").strip()
        gran_code = gran_map.get(raw_gran.lower(), raw_gran.upper())
        if not gran_code:
            record_issue(row_issues, "Missing granularity_code")
        elif valid_grans and gran_code not in valid_grans:
            ci_g = next((g for g in valid_grans if g.lower() == gran_code.lower()), None)
            if ci_g:
                gran_code = ci_g
            else:
                record_issue(row_issues, f"Granularity '{gran_code}' not in makara.analysis_granularity_types")

        sharing_code = str(get_col("sharing_code") or defaults.get("sharing_code") or "ORG_INTERNAL").strip().upper()
        if sharing_code not in valid_sharings:
            record_issue(row_issues, f"Invalid sharing_code '{sharing_code}'")

        proc_id = defaults.get("procedure_id")
        try:
            proc_id_int = int(proc_id) if proc_id is not None and str(proc_id).strip() != "" else None
        except Exception:
            proc_id_int = None
        if proc_id_int is None and not defaults.get("create_new_procedure"):
            record_issue(row_issues, "Select an existing procedure_id or enable 'Create New Procedure'")

        prob_raw = get_col("probability")
        conf_raw = get_col("confidence")
        prob_val = round(float(prob_raw), 4) if prob_raw is not None else None
        conf_val = round(float(conf_raw), 4) if conf_raw is not None else None

        analyst_val = str(get_col("analyst") or defaults.get("analyst") or "").strip().upper() or None

        aligned_rows.append(
            {
                "row_num": int(idx) + 1,
                "valid": len(row_issues) == 0,
                "issues": row_issues,
                "recording_channel_id": rc_id,
                "procedure_id": proc_id_int,
                "organization_code": org_code,
                "call_type_code": call_code,
                "label_code": label_code,
                "granularity_code": gran_code,
                "sharing_code": sharing_code,
                "start_time_utc": serialize_value(start_dt),
                "end_time_utc": serialize_value(end_dt),
                "tstzrange": f"[{serialize_value(start_dt)}, {serialize_value(end_dt)})" if start_dt and end_dt else None,
                "freq_min_hz": fmin_hz,
                "freq_max_hz": fmax_hz,
                "freqrange": f"[{fmin_hz}, {fmax_hz}]" if fmin_hz is not None and fmax_hz is not None else None,
                "probability": prob_val,
                "confidence": conf_val,
                "analyst": analyst_val,
                "source_file": src_file or None,
            }
        )

    valid_count = sum(1 for r in aligned_rows if r["valid"])
    return {
        "total_rows": len(aligned_rows),
        "valid_rows": valid_count,
        "invalid_rows": len(aligned_rows) - valid_count,
        "ready_to_commit": valid_count > 0 and valid_count == len(aligned_rows),
        "issue_summary": issue_summary,
        "rows": aligned_rows,
    }


def commit_aligned_annotations(
    aligned_rows: list[dict[str, Any]],
    new_procedure: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Transactionally insert (optional) `core.procedures` and standardized `core.annotations`
    into `nmfs_annotation_db` using granted DML permissions.
    """
    valid_rows = [r for r in aligned_rows if r.get("valid")]
    if not valid_rows:
        raise ValueError("No valid standardized rows to insert.")

    inserted_ids: list[int] = []
    created_procedure_id: int | None = None

    with get_connection(autocommit=False) as conn:
        with conn.cursor() as cur:
            if new_procedure and new_procedure.get("name") and new_procedure.get("analysis_id"):
                fmin = new_procedure.get("freq_min_hz")
                fmax = new_procedure.get("freq_max_hz")
                freq_literal = f"[{float(fmin)},{float(fmax)}]" if fmin is not None and fmax is not None else None
                analysts_arr = [a.strip().upper() for a in str(new_procedure.get("analysts") or "").split(",") if a.strip()] or None
                cur.execute(
                    """
                    INSERT INTO core.procedures (analysis_id, name, description, freqrange, analysts, procedure_json)
                    VALUES (%s, %s, %s, %s::core.freqrange, %s, %s::jsonb)
                    RETURNING id
                    """,
                    (
                        int(new_procedure["analysis_id"]),
                        str(new_procedure["name"]).strip(),
                        str(new_procedure.get("description") or "").strip() or None,
                        freq_literal,
                        analysts_arr,
                        json.dumps({"created_by": "annomate"}),
                    ),
                )
                created_procedure_id = int(cur.fetchone()["id"])

            for r in valid_rows:
                proc_id = created_procedure_id or int(r["procedure_id"])
                tstz_literal = f"[{r['start_time_utc']},{r['end_time_utc']})"
                freq_literal = (
                    f"[{float(r['freq_min_hz'])},{float(r['freq_max_hz'])}]"
                    if r.get("freq_min_hz") is not None and r.get("freq_max_hz") is not None
                    else None
                )
                cur.execute(
                    """
                    INSERT INTO core.annotations (
                        recording_channel_id,
                        procedure_id,
                        organization_code,
                        call_type_code,
                        label_code,
                        granularity_code,
                        sharing_code,
                        tstzrange,
                        freqrange,
                        probability,
                        confidence,
                        analyst
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s,
                        %s::tstzrange,
                        %s::core.freqrange,
                        %s, %s, %s
                    )
                    RETURNING id
                    """,
                    (
                        int(r["recording_channel_id"]),
                        proc_id,
                        r["organization_code"],
                        r["call_type_code"],
                        r["label_code"],
                        r["granularity_code"],
                        r["sharing_code"],
                        tstz_literal,
                        freq_literal,
                        r.get("probability"),
                        r.get("confidence"),
                        r.get("analyst"),
                    ),
                )
                inserted_ids.append(int(cur.fetchone()["id"]))
        conn.commit()

    return {
        "inserted_count": len(inserted_ids),
        "inserted_ids": inserted_ids[:50],
        "procedure_id": created_procedure_id or valid_rows[0]["procedure_id"],
        "created_new_procedure": created_procedure_id is not None,
    }
