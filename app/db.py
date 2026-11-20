"""
Database connectivity, read-only query execution, reference catalog loading,
and transactional annotation ingestion for nmfs_annotation_db.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import re
from typing import Any, Dict, List, Optional, Tuple

import psycopg
from psycopg.rows import dict_row

from .config import get_settings
from .demo_data import evaluate_demo_sql, get_demo_rows

_runtime_demo_override: Optional[bool] = None


def is_demo_mode_active() -> bool:
    if _runtime_demo_override is not None:
        return _runtime_demo_override
    return get_settings().demo_mode


def set_demo_mode(enabled: bool) -> bool:
    global _runtime_demo_override, _health_cache
    _runtime_demo_override = bool(enabled)
    _health_cache = None
    return _runtime_demo_override

FORBIDDEN_SQL_PATTERN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE|COPY|VACUUM|CALL|DO)\b",
    re.IGNORECASE,
)


def serialize_value(val: Any) -> Any:
    """Convert PostgreSQL / Python rich types into JSON-safe primitives."""
    if val is None:
        return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            val = val.replace(tzinfo=timezone.utc)
        return val.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(val, Decimal):
        return float(val)
    if isinstance(val, (bytes, bytearray, memoryview)):
        return f"<{len(val)} bytes>"
    if hasattr(val, "lower") and hasattr(val, "upper") and hasattr(val, "isempty"):
        # psycopg Range object (tstzrange, freqrange)
        if val.isempty:
            return None
        lo = serialize_value(val.lower)
        hi = serialize_value(val.upper)
        return f"[{lo}, {hi})"
    if isinstance(val, (list, tuple)):
        return [serialize_value(x) for x in val]
    if isinstance(val, dict):
        return {str(k): serialize_value(v) for k, v in val.items()}
    return val


def get_connection(autocommit: bool = False):
    settings = get_settings()
    return psycopg.connect(settings.pg_conninfo, row_factory=dict_row, autocommit=autocommit)


_health_cache: Optional[Dict[str, Any]] = None
_health_cache_ts: float = 0.0


def check_db_health(force: bool = False) -> Dict[str, Any]:
    """Check connectivity to nmfs_annotation_db over NOAA VPN (or return instant Demo Mode stats)."""
    global _health_cache, _health_cache_ts
    import time

    settings = get_settings()
    if is_demo_mode_active():
        return {
            "connected": False,
            "mode": "demo",
            "host": "offline-demo",
            "database": "demo_dclde_catalog",
            "user": "demo_user",
            "counts": {
                "annotations_count": len(get_demo_rows()),
                "effort_count": 1,
                "acoustic_files_count": 48,
                "audio_segments_count": 48,
                "recordings_count": 3,
                "deployments_count": 3,
                "active_findings_count": 0,
            },
            "erd_url": settings.erd_url,
            "error": None,
        }

    now = time.time()
    if not force and _health_cache is not None and (now - _health_cache_ts) < 45.0:
        return _health_cache
    try:
        with get_connection(autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SET statement_timeout = '5s'")
                cur.execute(
                    """
                    SELECT
                        (SELECT count(*) FROM core.annotations) AS annotations_count,
                        (SELECT count(*) FROM core.effort) AS effort_count,
                        GREATEST(0, (SELECT reltuples::bigint FROM pg_class WHERE oid = 'core.acoustic_files'::regclass)) AS acoustic_files_count,
                        GREATEST(0, (SELECT reltuples::bigint FROM pg_class WHERE oid = 'core.audio_segments'::regclass)) AS audio_segments_count,
                        (SELECT count(*) FROM makara.recordings) AS recordings_count,
                        (SELECT count(*) FROM makara.deployments) AS deployments_count,
                        GREATEST(0, (SELECT reltuples::bigint FROM pg_class WHERE oid = 'reconcile.findings'::regclass)) AS active_findings_count
                    """
                )
                counts = dict(cur.fetchone() or {})
        _health_cache = {
            "connected": True,
            "mode": "live",
            "host": settings.db_host,
            "database": settings.db_name,
            "user": settings.db_user,
            "counts": {k: int(v or 0) for k, v in counts.items()},
            "erd_url": settings.erd_url,
            "error": None,
        }
        _health_cache_ts = now
        return _health_cache
    except Exception as exc:
        return {
            "connected": False,
            "mode": "demo_fallback",
            "host": settings.db_host,
            "database": settings.db_name,
            "user": settings.db_user,
            "counts": {
                "annotations_count": 24,
                "effort_count": 1,
                "acoustic_files_count": 6,
                "audio_segments_count": 6,
                "recordings_count": 2,
                "deployments_count": 2,
                "active_findings_count": 0,
            },
            "erd_url": settings.erd_url,
            "error": str(exc),
        }


def validate_readonly_sql(sql: str) -> str:
    cleaned = (sql or "").strip().rstrip(";").strip()
    if not cleaned:
        raise ValueError("SQL query cannot be empty.")
    # Strip SQL comments before checking leading keyword
    no_comments = re.sub(r"--[^\n]*", " ", cleaned)
    no_comments = re.sub(r"/\*.*?\*/", " ", no_comments, flags=re.DOTALL).strip()
    if not re.match(r"^(SELECT|WITH)\b", no_comments, re.IGNORECASE):
        raise ValueError("Only read-only SELECT or WITH (CTE) queries are permitted in Find & Export.")
    if FORBIDDEN_SQL_PATTERN.search(no_comments):
        raise ValueError("Mutating or DDL SQL keywords are blocked in read-only query mode.")
    return cleaned


def _demo_fallback_rows(limit: int = 50) -> Tuple[List[str], List[Dict[str, Any]]]:
    """Fallback DCLDE_2013-modeled dataset used ONLY when NOAA VPN is disconnected."""
    base_dt = datetime(2009, 3, 28, 0, 5, 0, tzinfo=timezone.utc)
    rows: List[Dict[str, Any]] = []
    labels = ["YES", "YES", "YES", "MAYBE", "NO", "YES", "YES", "UNVERIFIED"]
    for i in range(min(limit, 24)):
        st = base_dt + timedelta(minutes=i * 17, seconds=(i * 13) % 45)
        dur = round(1.05 + (i % 5) * 0.18, 3)
        et = st + timedelta(seconds=dur)
        fmin = round(78.0 + (i % 6) * 5.5, 1)
        fmax = round(fmin + 95.0 + (i % 4) * 14.0, 1)
        seg_st = st.replace(minute=0, second=0, microsecond=0)
        seg_et = seg_st + timedelta(minutes=15)
        rows.append(
            {
                "annotation_id": 1001 + i,
                "organization_code": "NEFSC",
                "effort_name": "DCLDE_2013",
                "call_type_code": "RW_UPCALL",
                "label_code": labels[i % len(labels)],
                "granularity_code": "EVENT_CALL",
                "sharing_code": "PUBLIC",
                "start_time_utc": st.isoformat().replace("+00:00", "Z"),
                "end_time_utc": et.isoformat().replace("+00:00", "Z"),
                "duration_secs": dur,
                "freq_min_hz": fmin,
                "freq_max_hz": fmax,
                "confidence": round(0.75 + (i % 5) * 0.05, 2),
                "probability": round(0.82 + (i % 4) * 0.04, 2),
                "analyst": "GDAVIS",
                "recording_channel_id": 10 + (i % 2),
                "channel": i % 2,
                "recording_id": 501,
                "recording_code": f"NEFSC_SBNMS_200903_CH{i % 2}",
                "deployment_code": "NEFSC_SBNMS_200903",
                "latitude": round(42.315 + (i % 3) * 0.042, 5),
                "longitude": round(-70.285 - (i % 3) * 0.038, 5),
                "water_depth_m": 84.0,
                "obj_gsuri": f"gs://noaa-passive-bioacoustic/nefsc/dclde_2013/SBNMS_20090328_{seg_st.strftime('%H%M%S')}.wav",
                "format": "wav",
                "subfile_index": 0,
                "file_channel": i % 2,
                "sample_rate_hz": 2000.0,
                "bit_depth": 16,
                "seg_start_utc": seg_st.isoformat().replace("+00:00", "Z"),
                "seg_end_utc": seg_et.isoformat().replace("+00:00", "Z"),
                "data_byte_offset": 44,
                "data_byte_length": 3600000,
            }
        )
    cols = list(rows[0].keys()) if rows else []
    return cols, rows


def execute_readonly_query(
    sql: str,
    max_rows: int = 5000,
) -> Dict[str, Any]:
    """
    Execute a validated read-only SQL query against nmfs_annotation_db
    (or evaluate instantly against the built-in multi-day Demo catalog when Demo Mode is on).
    """
    cleaned_sql = validate_readonly_sql(sql)
    if is_demo_mode_active():
        cols, rows = evaluate_demo_sql(cleaned_sql, max_rows=max_rows)
        return {
            "ok": True,
            "mode": "demo",
            "sql": cleaned_sql,
            "columns": cols,
            "rows": rows,
            "row_count": len(rows),
            "truncated": False,
            "error": None,
        }

    try:
        with get_connection(autocommit=False) as conn:
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION READ ONLY")
                cur.execute("SET LOCAL statement_timeout = '20s'")
                cur.execute(cleaned_sql)
                cols = [desc.name for desc in (cur.description or [])]
                raw_rows = cur.fetchmany(max_rows + 1)
                truncated = len(raw_rows) > max_rows
                if truncated:
                    raw_rows = raw_rows[:max_rows]
                rows = [
                    {k: serialize_value(v) for k, v in dict(r).items()}
                    for r in raw_rows
                ]
            conn.rollback()
        return {
            "ok": True,
            "mode": "live",
            "sql": cleaned_sql,
            "columns": cols,
            "rows": rows,
            "row_count": len(rows),
            "truncated": truncated,
            "error": None,
        }
    except psycopg.OperationalError as op_exc:
        cols, rows = evaluate_demo_sql(cleaned_sql, max_rows=max_rows)
        return {
            "ok": True,
            "mode": "demo_fallback",
            "sql": cleaned_sql,
            "columns": cols,
            "rows": rows,
            "row_count": len(rows),
            "truncated": False,
            "error": f"Database unreachable (check NOAA VPN or enable Demo Mode): {op_exc}",
        }
    except Exception as exc:
        return {
            "ok": False,
            "mode": "error",
            "sql": cleaned_sql,
            "columns": [],
            "rows": [],
            "row_count": 0,
            "truncated": False,
            "error": str(exc),
        }


def fetch_reference_catalog() -> Dict[str, Any]:
    """Fetch controlled vocabularies, efforts, analyses, procedures, and channels for dropdowns & alignment."""
    if is_demo_mode_active():
        return _build_demo_catalog("demo")
    try:
        with get_connection(autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SET statement_timeout = '10s'")

                cur.execute("SELECT code, name FROM makara.organizations ORDER BY code")
                organizations = [dict(r) for r in cur.fetchall()]

                cur.execute(
                    """
                    SELECT ct.code, ct.name, ct.description,
                           COALESCE(
                               array_agg( DISTINCT ss.code ) FILTER (WHERE ss.code IS NOT NULL),
                               ARRAY[]::varchar[]
                           ) AS sound_source_codes
                    FROM makara.call_types ct
                    LEFT JOIN makara.call_types_sound_sources ctss ON ctss.call_type_code = ct.code
                    LEFT JOIN makara.sound_sources ss ON ss.code = ctss.sound_source_code
                    GROUP BY ct.code, ct.name, ct.description
                    ORDER BY ct.code
                    """
                )
                call_types = [{k: serialize_value(v) for k, v in dict(r).items()} for r in cur.fetchall()]

                cur.execute("SELECT code, legacy_id, name, is_protocol_inferred, description FROM core.annotation_labels ORDER BY legacy_id")
                labels = [dict(r) for r in cur.fetchall()]

                cur.execute("SELECT code, name, description FROM makara.analysis_granularity_types ORDER BY code")
                granularities = [dict(r) for r in cur.fetchall()]

                cur.execute("SELECT code, name, release_noaa, release_pacm, release_data, description FROM core.sharing_scopes ORDER BY code")
                sharing_scopes = [dict(r) for r in cur.fetchall()]

                cur.execute(
                    """
                    SELECT e.id, e.organization_code, e.name, e.description,
                           count(be.bin_id) AS bin_count
                    FROM core.effort e
                    LEFT JOIN core.bins_effort be ON be.effort_id = e.id
                    GROUP BY e.id, e.organization_code, e.name, e.description
                    ORDER BY e.name
                    """
                )
                efforts = [{k: serialize_value(v) for k, v in dict(r).items()} for r in cur.fetchall()]

                cur.execute(
                    """
                    SELECT id, organization_code, code, name, description
                    FROM core.analyses
                    ORDER BY organization_code, id
                    """
                )
                analyses = [{k: serialize_value(v) for k, v in dict(r).items()} for r in cur.fetchall()]

                cur.execute(
                    """
                    SELECT p.id, p.analysis_id, a.organization_code, a.name AS analysis_name,
                           p.name, p.description, lower(p.freqrange) AS freq_min_hz, upper(p.freqrange) AS freq_max_hz
                    FROM core.procedures p
                    JOIN core.analyses a ON a.id = p.analysis_id
                    ORDER BY p.id DESC
                    """
                )
                procedures = [{k: serialize_value(v) for k, v in dict(r).items()} for r in cur.fetchall()]

                cur.execute(
                    """
                    SELECT rc.id AS recording_channel_id,
                           rc.recording_id,
                           rc.channel,
                           rec.code AS recording_code,
                           dep.code AS deployment_code,
                           dep.organization_code,
                           lower(rc.tstzrange) AS channel_start_utc,
                           upper(rc.tstzrange) AS channel_end_utc
                    FROM core.recording_channels rc
                    JOIN makara.recordings rec ON rec.id = rc.recording_id
                    LEFT JOIN makara.deployments dep ON dep.id = rec.deployment_id
                    ORDER BY (EXISTS (SELECT 1 FROM core.annotations a WHERE a.recording_channel_id = rc.id)) DESC,
                             rc.id ASC
                    LIMIT 250
                    """
                )
                recording_channels = [{k: serialize_value(v) for k, v in dict(r).items()} for r in cur.fetchall()]

                cur.execute("SELECT code, name, description FROM core.effproc_types ORDER BY code")
                effproc_types = [dict(r) for r in cur.fetchall()]

                cur.execute("SELECT code, name, description FROM core.effproc_assumptions ORDER BY code")
                effproc_assumptions = [dict(r) for r in cur.fetchall()]

        return {
            "mode": "live",
            "organizations": organizations,
            "call_types": call_types,
            "labels": labels,
            "granularities": granularities,
            "sharing_scopes": sharing_scopes,
            "efforts": efforts,
            "analyses": analyses,
            "procedures": procedures,
            "recording_channels": recording_channels,
            "effproc_types": effproc_types,
            "effproc_assumptions": effproc_assumptions,
        }
    except Exception as exc:
        return _build_demo_catalog("demo_fallback", error=str(exc))


def _build_demo_catalog(mode: str = "demo", error: Optional[str] = None) -> Dict[str, Any]:
    return {
        "mode": mode,
        "error": error,
        "organizations": [
            {"code": "NEFSC", "name": "NOAA Northeast Fisheries Science Center"},
            {"code": "SWFSC", "name": "NOAA Southwest Fisheries Science Center"},
            {"code": "AFSC", "name": "NOAA Alaska Fisheries Science Center"},
            {"code": "PIFSC", "name": "NOAA Pacific Islands Fisheries Science Center"},
            {"code": "SEFSC", "name": "NOAA Southeast Fisheries Science Center"},
        ],
        "call_types": [
            {"code": "RW_UPCALL", "name": "Right whale upcall", "description": "Contact FM upsweep", "sound_source_codes": ["EUGL"]},
            {"code": "RW_MOAN", "name": "Right whale moan", "description": "Low-frequency tonal moan", "sound_source_codes": ["EUGL"]},
            {"code": "SEWH_DS100HZ", "name": "Sei whale 100-44 Hz downsweep", "description": "Low-frequency mysticete downsweep", "sound_source_codes": ["BABO"]},
            {"code": "BLWH_A", "name": "Blue whale A calls", "description": "Northeast Pacific / Atlantic A call", "sound_source_codes": ["BAMU"]},
        ],
        "labels": [
            {"code": "YES", "legacy_id": 1, "name": "Verified Positive", "is_protocol_inferred": False},
            {"code": "NO", "legacy_id": 0, "name": "Verified Negative", "is_protocol_inferred": False},
            {"code": "MAYBE", "legacy_id": 2, "name": "Verified Uncertain", "is_protocol_inferred": False},
            {"code": "PROTOCOL_YES", "legacy_id": 21, "name": "Protocol-Inferred Positive", "is_protocol_inferred": True},
            {"code": "PROTOCOL_NO", "legacy_id": 20, "name": "Protocol-Inferred Negative", "is_protocol_inferred": True},
            {"code": "UNVERIFIED", "legacy_id": 99, "name": "Unverified Candidate", "is_protocol_inferred": False},
        ],
        "granularities": [
            {"code": "EVENT_CALL", "name": "Single Call Detection", "description": "Each row bounds one discrete individual vocalization in time and frequency."},
            {"code": "EVENT_ENCOUNTER", "name": "Individual or Group Detection", "description": "Each row spans an acoustic encounter or bout window containing multiple calls."},
            {"code": "INTERVAL", "name": "Binned Time Intervals", "description": "Presence/absence evaluated across standardized fixed-duration time bins."},
        ],
        "sharing_scopes": [
            {"code": "ORG_INTERNAL", "name": "Organization Internal"},
            {"code": "NOAA_INTERNAL", "name": "NOAA Internal"},
            {"code": "PACM_SUMMARY_ONLY", "name": "PACM Summary Release"},
            {"code": "PUBLIC_DATA_ONLY", "name": "Public Data / ML Release"},
            {"code": "PUBLIC", "name": "Full Public Release"},
        ],
        "efforts": [
            {"id": 1, "organization_code": "NEFSC", "name": "DCLDE_2013", "description": "NEFSC Right Whale Upcall Demo Dataset", "bin_count": 48}
        ],
        "analyses": [
            {"id": 1, "organization_code": "NEFSC", "code": "DCLDE_2013", "name": "DCLDE 2013 Right Whale Study", "description": "Demo ground truth study"},
            {"id": 2, "organization_code": "NEFSC", "code": "UNCLASSIFIED", "name": "NEFSC Unclassified", "description": "Exploratory container"},
        ],
        "procedures": [
            {"id": 1, "analysis_id": 1, "organization_code": "NEFSC", "analysis_name": "DCLDE 2013 Right Whale Study", "name": "dclde_2013_demo_ground_truth", "description": "Manual bounding box review"}
        ],
        "recording_channels": [
            {"recording_channel_id": 525768, "recording_id": 1144, "channel": 0, "recording_code": "MARU_SBNMS_CH0", "deployment_code": "NEFSC_SBNMS_200903_NOPP6_CH1", "organization_code": "NEFSC"},
            {"recording_channel_id": 525769, "recording_id": 1145, "channel": 1, "recording_code": "MARU_CCBAY_CH1", "deployment_code": "NEFSC_CCBAY_200903_NOPP2_CH2", "organization_code": "NEFSC"},
            {"recording_channel_id": 525770, "recording_id": 1146, "channel": 0, "recording_code": "HARP_GSC_CH0", "deployment_code": "NEFSC_GSC_200903_SITE3", "organization_code": "NEFSC"},
        ],
        "effproc_types": [],
        "effproc_assumptions": [],
    }


def fetch_annotation_audio_context(annotation_id: int) -> Optional[Dict[str, Any]]:
    """Fetch complete audio segment & GCS container geometry for a single annotation ID."""
    if is_demo_mode_active():
        for r in get_demo_rows():
            if int(r["annotation_id"]) == int(annotation_id):
                return r
        return None

    sql = """
        SELECT
            a.id AS annotation_id,
            a.organization_code,
            a.call_type_code,
            a.label_code,
            a.granularity_code,
            a.sharing_code,
            lower(a.tstzrange) AS start_time_utc,
            upper(a.tstzrange) AS end_time_utc,
            lower(a.freqrange) AS freq_min_hz,
            upper(a.freqrange) AS freq_max_hz,
            a.polygon,
            a.probability,
            a.confidence,
            a.analyst,
            rc.id AS recording_channel_id,
            rc.channel,
            rec.id AS recording_id,
            rec.code AS recording_code,
            rec.recording_uri,
            (rec.sample_rate_khz * 1000.0) AS recording_sample_rate_hz,
            dep.code AS deployment_code,
            dep.latitude,
            dep.longitude,
            af.id AS acoustic_file_id,
            af.obj_gsuri,
            af.format,
            af.name AS file_name,
            af.channels AS container_channels,
            af.subfile_count,
            seg.id AS audio_segment_id,
            seg.subfile_index,
            seg.file_channel,
            lower(seg.tstzrange) AS seg_start_utc,
            upper(seg.tstzrange) AS seg_end_utc,
            seg.sample_rate_hz,
            seg.bit_depth,
            seg.duration_secs AS seg_duration_secs,
            seg.data_byte_offset,
            seg.data_byte_length,
            (
                SELECT min(s0.data_byte_offset)
                FROM core.audio_segments s0
                WHERE s0.acoustic_file_id = af.id
            ) AS first_seg_byte_offset
        FROM core.annotations a
        JOIN core.recording_channels rc ON rc.id = a.recording_channel_id
        JOIN makara.recordings rec ON rec.id = rc.recording_id
        LEFT JOIN makara.deployments dep ON dep.id = rec.deployment_id
        LEFT JOIN LATERAL (
            SELECT s.*
            FROM core.audio_segments s
            WHERE s.recording_channel_id = a.recording_channel_id
              AND s.tstzrange && a.tstzrange
            ORDER BY lower(s.tstzrange) ASC
            LIMIT 1
        ) seg ON true
        LEFT JOIN core.acoustic_files af ON af.id = seg.acoustic_file_id
        WHERE a.id = %s
    """
    try:
        with get_connection(autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (annotation_id,))
                row = cur.fetchone()
                if row:
                    return {k: serialize_value(v) for k, v in dict(row).items()}
    except Exception:
        pass

    # Fallback lookup from demo dataset
    for r in get_demo_rows():
        if int(r["annotation_id"]) == int(annotation_id):
            return r
    return None
