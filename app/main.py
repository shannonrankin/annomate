"""
FastAPI Backend for Annomate — Bioacoustic Annotation Discovery, Review, Export & Ingestion Platform.
"""

from __future__ import annotations

from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from typing import Any, Dict, List, Optional

from dotenv import set_key
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
import markdown as md_lib
import pandas as pd
from pydantic import BaseModel

from .aligner import (
    PRESET_PROFILES,
    align_and_validate_dataframe,
    commit_aligned_annotations,
    parse_uploaded_table,
    suggest_column_mapping,
)
from .audio_engine import compute_spectrogram_payload, get_gcs_client
from .config import EXPORT_DIR, REVIEW_SESSION_DIR, ROOT_DIR, UPLOAD_DIR, get_settings
from .db import (
    check_db_health,
    execute_readonly_query,
    fetch_annotation_audio_context,
    fetch_reference_catalog,
    get_connection,
    is_demo_mode_active,
    serialize_value,
    set_demo_mode,
)
from .demo_data import get_demo_rows
from .schema_context import build_structured_sql, generate_sql_from_prompt

app = FastAPI(
    title="Annomate",
    description="NOAA NMFS Bioacoustic Annotation Discovery, Review, Standardization & Export Platform",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_Methods=["*"],
    allow_headers=["*"],
) if False else app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_catalog_cache: Optional[Dict[str, Any]] = None
_marimo_proc: Optional[subprocess.Popen] = None
_uploaded_align_cache: Dict[str, pd.DataFrame] = {}


def _is_port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex((host, port)) == 0


def ensure_marimo_running(mode: str = "edit") -> Dict[str, Any]:
    """Ensure the reactive Marimo Review Studio server is running and reachable."""
    global _marimo_proc
    settings = get_settings()
    port = settings.marimo_port
    url = f"http://127.0.0.1:{port}"

    if _is_port_open("127.0.0.1", port):
        return {"running": True, "url": url, "port": port, "mode": mode}

    notebook_path = ROOT_DIR / "notebooks" / "review_studio.py"
    python_exe = sys.executable
    subcmd = "edit" if mode == "edit" else "run"
    cmd = [
        python_exe,
        "-m",
        "marimo",
        subcmd,
        str(notebook_path),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--headless",
        "--no-token",
    ]
    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    _marimo_proc = subprocess.Popen(
        cmd,
        cwd=str(ROOT_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation_flags,
    )
    # Wait briefly for port bind
    import time

    for _ in range(25):
        if _is_port_open("127.0.0.1", port):
            return {"running": True, "url": url, "port": port, "mode": subcmd}
        time.sleep(0.2)

    return {"running": _is_port_open("127.0.0.1", port), "url": url, "port": port, "mode": subcmd}


# ---------------------------------------------------------------------------
# Pydantic Request Models
# ---------------------------------------------------------------------------
class SettingsUpdateRequest(BaseModel):
    gemini_api_key: Optional[str] = None
    gcp_project: Optional[str] = None


class DemoModeRequest(BaseModel):
    enabled: bool


class ExecuteSqlRequest(BaseModel):
    sql: str
    prompt_summary: Optional[str] = ""
    max_rows: int = 2500


class StageReviewRequest(BaseModel):
    use_last_query: bool = True
    sql: Optional[str] = None
    prompt_summary: Optional[str] = ""
    marimo_mode: str = "edit"


class SpectrogramRequest(BaseModel):
    annotation_id: Optional[int] = None
    row_meta: Optional[Dict[str, Any]] = None
    nfft: int = 256
    overlap_pct: float = 85.0
    window_type: str = "hann"
    fmin_hz: float = 0.0
    fmax_hz: float = 500.0
    padding_sec: float = 2.5
    db_range: float = 55.0


class ExportBuildRequest(BaseModel):
    source: str = "last_query"  # "last_query" | "marimo_reviewed" | "effort"
    effort_name: Optional[str] = "DCLDE_2013"
    limit: int = 5000
    enrich_makara_deployment: bool = True
    enrich_makara_recording: bool = True
    enrich_taxonomy: bool = True
    enrich_provenance: bool = True
    enrich_reconcile: bool = False
    export_format: str = "csv"  # "csv" | "jsonl" | "raven_tsv" | "gcloud_script"


class AlignValidateRequest(BaseModel):
    session_id: str
    mapping: Dict[str, Optional[str]]
    defaults: Dict[str, Any]
    vocab_maps: Optional[Dict[str, Dict[str, str]]] = None


class AlignCommitRequest(BaseModel):
    session_id: str
    mapping: Dict[str, Optional[str]]
    defaults: Dict[str, Any]
    vocab_maps: Optional[Dict[str, Dict[str, str]]] = None
    new_procedure: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# System & Catalog Endpoints
# ---------------------------------------------------------------------------
@app.get("/api/status")
def api_status():
    settings = get_settings()
    demo_active = is_demo_mode_active()
    db_health = check_db_health()
    gcs_cli = None if demo_active else get_gcs_client()
    marimo_open = _is_port_open("127.0.0.1", settings.marimo_port)

    last_q_meta = {}
    if (REVIEW_SESSION_DIR / "last_query_meta.json").exists():
        try:
            last_q_meta = json.loads((REVIEW_SESSION_DIR / "last_query_meta.json").read_text(encoding="utf-8"))
        except Exception:
            pass

    reviewed_meta = {}
    if (REVIEW_SESSION_DIR / "reviewed_meta.json").exists():
        try:
            reviewed_meta = json.loads((REVIEW_SESSION_DIR / "reviewed_meta.json").read_text(encoding="utf-8"))
        except Exception:
            pass

    return {
        "demo_mode": demo_active,
        "db": db_health,
        "gcs_authenticated": True if demo_active else (gcs_cli is not None),
        "gemini_configured": bool(settings.gemini_api_key),
        "marimo": {
            "running": marimo_open,
            "url": f"http://127.0.0.1:{settings.marimo_port}",
        },
        "sessions": {
            "last_query": last_q_meta,
            "marimo_reviewed": reviewed_meta,
        },
    }


@app.post("/api/demo-mode")
def api_toggle_demo_mode(req: DemoModeRequest):
    global _catalog_cache
    active = set_demo_mode(req.enabled)
    _catalog_cache = fetch_reference_catalog()
    return {"ok": True, "demo_mode": active}


@app.post("/api/settings")
def api_update_settings(req: SettingsUpdateRequest):
    env_file = ROOT_DIR / ".env"
    if not env_file.exists():
        env_file.write_text("", encoding="utf-8")
    if req.gemini_api_key is not None:
        set_key(str(env_file), "GEMINI_API_KEY", req.gemini_api_key.strip())
    if req.gcp_project is not None:
        set_key(str(env_file), "GOOGLE_CLOUD_PROJECT", req.gcp_project.strip())
    get_gcs_client(force_refresh=True)
    s = get_settings()
    return {"ok": True, "gemini_configured": bool(s.gemini_api_key), "gcp_project": s.gcp_project}


@app.get("/api/catalog")
def api_catalog(refresh: bool = Query(False)):
    global _catalog_cache
    if _catalog_cache is None or refresh:
        _catalog_cache = fetch_reference_catalog()
    return _catalog_cache


# ---------------------------------------------------------------------------
# Module 1: Find & Filter Data (Audio/Text NL -> SQL + CSV + Review Prompt)
# ---------------------------------------------------------------------------
@app.post("/api/query/nl-to-sql")
async def api_nl_to_sql(
    prompt_text: str = Form(""),
    layers_json: str = Form('["annotations", "makara", "audio"]'),
    filters_json: str = Form("{}"),
    audio_file: Optional[UploadFile] = File(None),
):
    global _catalog_cache
    if _catalog_cache is None:
        _catalog_cache = fetch_reference_catalog()

    try:
        layers = json.loads(layers_json) if layers_json else ["annotations"]
    except Exception:
        layers = ["annotations"]

    try:
        ui_filters = json.loads(filters_json) if filters_json else {}
    except Exception:
        ui_filters = {}

    audio_bytes: Optional[bytes] = None
    audio_mime = "audio/webm"
    if audio_file is not None:
        audio_bytes = await audio_file.read()
        audio_mime = audio_file.content_type or "audio/webm"

    result = generate_sql_from_prompt(
        prompt_text=prompt_text,
        selected_layers=layers,
        ui_filters=ui_filters,
        catalog=_catalog_cache,
        audio_bytes=audio_bytes,
        audio_mime=audio_mime,
    )
    return result


@app.post("/api/query/execute")
def api_execute_query(req: ExecuteSqlRequest):
    res = execute_readonly_query(req.sql, max_rows=req.max_rows)
    if not res["ok"]:
        raise HTTPException(status_code=400, detail=res["error"] or "SQL execution failed.")

    df = pd.DataFrame(res["rows"], columns=res["columns"]) if res["columns"] else pd.DataFrame()
    csv_path = REVIEW_SESSION_DIR / "last_query.csv"
    df.to_csv(csv_path, index=False)

    # Compute rich dataset summary for the post-query decision card
    summary: Dict[str, Any] = {
        "row_count": len(df),
        "column_count": len(df.columns),
        "truncated": res["truncated"],
        "mode": res["mode"],
        "positive_yes_count": int((df["label_code"] == "YES").sum()) if "label_code" in df.columns else None,
        "call_types": df["call_type_code"].value_counts().head(6).to_dict() if "call_type_code" in df.columns else {},
        "deployments_count": int(df["deployment_code"].nunique()) if "deployment_code" in df.columns else None,
        "linked_audio_count": int(df["obj_gsuri"].notna().sum()) if "obj_gsuri" in df.columns else None,
        "saved_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "prompt": req.prompt_summary or "Custom SQL Query",
    }
    if "start_time_utc" in df.columns and not df.empty:
        valid_ts = df["start_time_utc"].dropna().astype(str)
        if not valid_ts.empty:
            summary["min_start_utc"] = valid_ts.min()
            summary["max_start_utc"] = valid_ts.max()

    (REVIEW_SESSION_DIR / "last_query_meta.json").write_text(json.dumps(summary), encoding="utf-8")

    return {
        "ok": True,
        "mode": res["mode"],
        "warning": res["error"],
        "sql": res["sql"],
        "columns": res["columns"],
        "preview_rows": res["rows"][:250],
        "summary": summary,
    }


@app.get("/api/query/download-csv")
def api_download_query_csv():
    csv_path = REVIEW_SESSION_DIR / "last_query.csv"
    if not csv_path.exists():
        raise HTTPException(status_code=404, detail="No query results cached yet. Run a query first.")
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return StreamingResponse(
        open(csv_path, "rb"),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="annomate_query_{ts}.csv"'},
    )


# ---------------------------------------------------------------------------
# Module 2: Stage & Launch Marimo Review Studio + Quick Spectrogram Preview
# ---------------------------------------------------------------------------
@app.post("/api/review/stage")
def api_stage_review(req: StageReviewRequest):
    last_csv = REVIEW_SESSION_DIR / "last_query.csv"
    active_csv = REVIEW_SESSION_DIR / "active_review.csv"

    if req.sql:
        res = execute_readonly_query(req.sql, max_rows=5000)
        if not res["ok"]:
            raise HTTPException(status_code=400, detail=res["error"])
        df = pd.DataFrame(res["rows"], columns=res["columns"])
        df.to_csv(active_csv, index=False)
        row_count = len(df)
    elif req.use_last_query and last_csv.exists():
        active_csv.write_bytes(last_csv.read_bytes())
        row_count = sum(1 for _ in open(active_csv, "rb")) - 1
    else:
        sql_q, _ = build_structured_sql(
            layers=["annotations", "provenance", "makara", "audio"],
            filters={"effort_name": "DCLDE_2013"},
            limit=2000,
        )
        res = execute_readonly_query(sql_q, max_rows=2000)
        df = pd.DataFrame(res["rows"], columns=res["columns"])
        df.to_csv(active_csv, index=False)
        row_count = len(df)

    meta = {
        "prompt": req.prompt_summary or "Annomate Query Dataset",
        "staged_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "row_count": max(0, row_count),
    }
    (REVIEW_SESSION_DIR / "session_meta.json").write_text(json.dumps(meta), encoding="utf-8")

    marimo_info = ensure_marimo_running(mode=req.marimo_mode)
    return {
        "ok": True,
        "staged_rows": meta["row_count"],
        "marimo": marimo_info,
    }


@app.post("/api/spectrogram")
def api_spectrogram(req: SpectrogramRequest):
    meta: Dict[str, Any] = dict(req.row_meta or {})
    if req.annotation_id is not None:
        db_ctx = fetch_annotation_audio_context(req.annotation_id)
        if db_ctx:
            meta = {**meta, **db_ctx}
    if not meta:
        raise HTTPException(status_code=404, detail="Annotation metadata not found.")

    payload = compute_spectrogram_payload(
        meta=meta,
        nfft=req.nfft,
        overlap_pct=req.overlap_pct,
        window_type=req.window_type,
        fmin_hz=req.fmin_hz,
        fmax_hz=req.fmax_hz,
        padding_sec=req.padding_sec,
        db_range=req.db_range,
    )
    payload["annotation"] = meta
    return payload


# ---------------------------------------------------------------------------
# Module 3: Export Studio (Relational Enrichment + Guaranteed Cloud Audio Paths)
# ---------------------------------------------------------------------------
def _enrich_dataframe_for_export(df: pd.DataFrame, req: ExportBuildRequest) -> pd.DataFrame:
    """
    Ensure exported datasets ALWAYS carry authoritative cloud audio paths (`obj_gsuri`, `recording_uri`,
    `format`, `subfile_index`, `file_channel`, `data_byte_offset`, `call_offset_in_seg_secs`) plus any
    user-selected Makara / taxonomy / provenance / reconciliation columns.
    """
    if df.empty or "annotation_id" not in df.columns:
        return df

    if is_demo_mode_active():
        demo_lookup = pd.DataFrame(get_demo_rows())
        extra_cols = ["annotation_id"] + [c for c in demo_lookup.columns if c not in df.columns and c != "annotation_id"]
        return df.merge(demo_lookup[extra_cols], on="annotation_id", how="left")

    ann_ids = [int(x) for x in pd.to_numeric(df["annotation_id"], errors="coerce").dropna().unique().tolist()]
    if not ann_ids:
        return df

    select_parts = [
        "a.id AS annotation_id",
        "rc.channel AS hydrophone_channel",
        "rec.recording_uri",
        "af.obj_gsuri",
        "af.format AS audio_container_format",
        "af.name AS audio_file_name",
        "seg.subfile_index",
        "seg.file_channel",
        "seg.sample_rate_hz",
        "seg.bit_depth",
        "lower(seg.tstzrange) AS seg_start_utc",
        "upper(seg.tstzrange) AS seg_end_utc",
        "ROUND(EXTRACT(EPOCH FROM (lower(a.tstzrange) - lower(seg.tstzrange)))::numeric, 3) AS call_offset_in_seg_secs",
        "seg.data_byte_offset",
        "seg.data_byte_length",
    ]
    joins = [
        "JOIN core.recording_channels rc ON rc.id = a.recording_channel_id",
        "JOIN makara.recordings rec ON rec.id = rc.recording_id",
        "LEFT JOIN LATERAL (SELECT s.* FROM core.audio_segments s WHERE s.recording_channel_id IS NOT NULL AND s.recording_channel_id = a.recording_channel_id AND s.tstzrange && a.tstzrange ORDER BY lower(s.tstzrange) ASC LIMIT 1) seg ON true",
        "LEFT JOIN core.acoustic_files af ON af.id = seg.acoustic_file_id",
    ]

    if req.enrich_makara_recording:
        select_parts.extend(
            [
                "rec.code AS recording_code",
                "rec.sample_rate_khz AS makara_sample_rate_khz",
                "rec.usable_min_frequency_hz",
                "rec.usable_max_frequency_hz",
                "rec.calibration_uri",
            ]
        )

    if req.enrich_makara_deployment:
        joins.append("LEFT JOIN makara.deployments dep ON dep.id = rec.deployment_id")
        select_parts.extend(
            [
                "dep.code AS deployment_code",
                "dep.latitude",
                "dep.longitude",
                "dep.water_depth_m",
                "dep.platform_type_code",
                "dep.vessel",
                "dep.cruise",
            ]
        )

    if req.enrich_taxonomy:
        joins.append("LEFT JOIN makara.call_types ct ON ct.code = a.call_type_code")
        joins.append(
            """LEFT JOIN LATERAL (
                SELECT ss.name AS species_common_name, ss.scientific_name, ss.itis_tsn, ss.aphia_id
                FROM makara.call_types_sound_sources ctss
                JOIN makara.sound_sources ss ON ss.code = ctss.sound_source_code
                WHERE ctss.call_type_code = a.call_type_code
                LIMIT 1
            ) tax ON true"""
        )
        select_parts.extend(
            [
                "ct.name AS call_type_name",
                "tax.species_common_name",
                "tax.scientific_name",
                "tax.itis_tsn",
                "tax.aphia_id",
            ]
        )

    if req.enrich_provenance:
        joins.append("LEFT JOIN core.procedures p ON p.id = a.procedure_id")
        joins.append("LEFT JOIN core.analyses an ON an.id = p.analysis_id")
        select_parts.extend(
            [
                "p.name AS procedure_name",
                "an.code AS analysis_code",
                "an.name AS analysis_name",
                "an.protocol_reference",
                "an.dataset_url",
            ]
        )

    if req.enrich_reconcile:
        joins.append("LEFT JOIN reconcile.recording_status rs ON rs.recording_id = rec.id")
        select_parts.extend(["rs.state AS reconciliation_state", "rs.last_checked_at AS reconciliation_checked_at"])

    enrich_sql = (
        "SELECT "
        + ", ".join(select_parts)
        + " FROM core.annotations a "
        + " ".join(joins)
        + " WHERE a.id = ANY(%s)"
    )

    try:
        with get_connection(autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SET statement_timeout = '15s'")
                cur.execute(enrich_sql, (ann_ids,))
                enrich_rows = [{k: serialize_value(v) for k, v in dict(r).items()} for r in cur.fetchall()]
        if enrich_rows:
            edf = pd.DataFrame(enrich_rows)
            new_cols = ["annotation_id"] + [c for c in edf.columns if c not in df.columns and c != "annotation_id"]
            # Also fill missing obj_gsuri if present but null
            for c in ("obj_gsuri", "recording_uri", "data_byte_offset", "call_offset_in_seg_secs"):
                if c in df.columns and c in edf.columns and df[c].isna().all():
                    df = df.drop(columns=[c])
                    if c not in new_cols:
                        new_cols.append(c)
            merged = df.merge(edf[new_cols], on="annotation_id", how="left")
            return merged
    except Exception:
        pass
    return df


@app.post("/api/export/preview")
def api_export_preview(req: ExportBuildRequest):
    df = _load_export_base_df(req)
    enriched = _enrich_dataframe_for_export(df, req)
    distinct_uris = (
        enriched["obj_gsuri"].dropna().unique().tolist() if "obj_gsuri" in enriched.columns else []
    )
    return {
        "row_count": len(enriched),
        "column_count": len(enriched.columns),
        "columns": list(enriched.columns),
        "distinct_audio_files": len(distinct_uris),
        "sample_uris": distinct_uris[:5],
        "preview_rows": json.loads(enriched.head(50).to_json(orient="records")),
    }


def _load_export_base_df(req: ExportBuildRequest) -> pd.DataFrame:
    if req.source == "marimo_reviewed":
        p = REVIEW_SESSION_DIR / "reviewed_subset.csv"
        if not p.exists():
            p = REVIEW_SESSION_DIR / "active_review.csv"
        if not p.exists():
            raise HTTPException(status_code=404, detail="No reviewed subset saved from Marimo yet.")
        return pd.read_csv(p).head(req.limit)
    elif req.source == "last_query":
        p = REVIEW_SESSION_DIR / "last_query.csv"
        if p.exists():
            return pd.read_csv(p).head(req.limit)

    sql_q, _ = build_structured_sql(
        layers=["annotations", "audio"],
        filters={"effort_name": req.effort_name or "DCLDE_2013"},
        limit=req.limit,
    )
    res = execute_readonly_query(sql_q, max_rows=req.limit)
    return pd.DataFrame(res["rows"], columns=res["columns"])


@app.post("/api/export/download")
def api_export_download(req: ExportBuildRequest):
    df = _load_export_base_df(req)
    enriched = _enrich_dataframe_for_export(df, req)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    if req.export_format == "jsonl":
        payload = enriched.to_json(orient="records", lines=True)
        return Response(
            content=payload,
            media_type="application/x-ndjson",
            headers={"Content-Disposition": f'attachment; filename="annomate_export_{ts}.jsonl"'},
        )
    elif req.export_format == "raven_tsv":
        raven_df = pd.DataFrame()
        raven_df["Selection"] = range(1, len(enriched) + 1)
        raven_df["View"] = "Spectrogram 1"
        raven_df["Channel"] = (pd.to_numeric(enriched.get("file_channel", 0), errors="coerce").fillna(0).astype(int) + 1)
        offset_s = pd.to_numeric(enriched.get("call_offset_in_seg_secs", 0.0), errors="coerce").fillna(0.0)
        dur_s = pd.to_numeric(enriched.get("duration_secs", 1.0), errors="coerce").fillna(1.0)
        raven_df["Begin Time (s)"] = offset_s.round(4)
        raven_df["End Time (s)"] = (offset_s + dur_s).round(4)
        raven_df["Low Freq (Hz)"] = enriched.get("freq_min_hz", "")
        raven_df["High Freq (Hz)"] = enriched.get("freq_max_hz", "")
        raven_df["Begin File"] = enriched.get("audio_file_name", enriched.get("obj_gsuri", ""))
        raven_df["GCS Audio URI"] = enriched.get("obj_gsuri", "")
        raven_df["Call Type"] = enriched.get("call_type_code", "")
        raven_df["Label"] = enriched.get("label_code", "")
        raven_df["Start UTC"] = enriched.get("start_time_utc", "")
        buf = io.StringIO()
        raven_df.to_csv(buf, sep="\t", index=False)
        return Response(
            content=buf.getvalue(),
            media_type="text/tab-separated-values",
            headers={"Content-Disposition": f'attachment; filename="annomate_raven_{ts}.selection.txt"'},
        )
    elif req.export_format == "gcloud_script":
        uris = enriched["obj_gsuri"].dropna().unique().tolist() if "obj_gsuri" in enriched.columns else []
        lines = [
            "# Annomate Cloud Audio Batch Download Script (PowerShell / gcloud CLI)",
            f"# Generated: {ts} UTC · Distinct GCS containers: {len(uris)}",
            '$DestDir = "./annomate_audio_files"',
            "New-Item -ItemType Directory -Force -Path $DestDir | Out-Null",
            "",
        ]
        for u in uris:
            lines.append(f'gcloud storage cp "{u}" $DestDir')
        return Response(
            content="\n".join(lines) + "\n",
            media_type="text/plain",
            headers={"Content-Disposition": f'attachment; filename="fetch_annomate_audio_{ts}.ps1"'},
        )
    else:
        buf = io.StringIO()
        enriched.to_csv(buf, index=False)
        return Response(
            content=buf.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="annomate_export_{ts}.csv"'},
        )


# ---------------------------------------------------------------------------
# Module 4: Add & Align Annotations (Standardize + Validate + Commit)
# ---------------------------------------------------------------------------
@app.get("/api/align/presets")
def api_align_presets():
    return {
        "presets": [
            {"id": k, "name": v["name"], "description": v["description"], "one_based_channel": v["one_based_channel"]}
            for k, v in PRESET_PROFILES.items()
        ]
    }


@app.post("/api/align/load-sample/{preset_id}")
def api_align_load_sample(preset_id: str):
    sample_map = {
        "raven_pro": ROOT_DIR / "sample_data" / "raven_selection_table_sample.txt",
        "triton_logger": ROOT_DIR / "sample_data" / "triton_logger_sample.csv",
        "pamguard": ROOT_DIR / "sample_data" / "pamguard_detections_sample.csv",
    }
    path = sample_map.get(preset_id, sample_map["raven_pro"])
    raw_bytes = path.read_bytes()
    df, detected = parse_uploaded_table(raw_bytes, path.name)
    session_id = f"sample_{preset_id}"
    _uploaded_align_cache[session_id] = df
    suggested = suggest_column_mapping(list(df.columns), detected)
    return {
        "session_id": session_id,
        "filename": path.name,
        "detected_preset": detected,
        "row_count": len(df),
        "columns": list(df.columns),
        "suggested_mapping": suggested,
        "sample_rows": json.loads(df.head(10).to_json(orient="records")),
    }


@app.post("/api/align/upload")
async def api_align_upload(file: UploadFile = File(...), preset_override: Optional[str] = Form(None)):
    raw_bytes = await file.read()
    try:
        df, detected = parse_uploaded_table(raw_bytes, file.filename or "annotations.csv")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not parse annotation file: {exc}")

    preset = preset_override if preset_override in PRESET_PROFILES else detected
    session_id = f"upload_{datetime.now(timezone.utc).strftime('%H%M%S_%f')}"
    _uploaded_align_cache[session_id] = df
    suggested = suggest_column_mapping(list(df.columns), preset)

    return {
        "session_id": session_id,
        "filename": file.filename,
        "detected_preset": preset,
        "row_count": len(df),
        "columns": list(df.columns),
        "suggested_mapping": suggested,
        "sample_rows": json.loads(df.head(12).to_json(orient="records")),
    }


@app.post("/api/align/validate")
def api_align_validate(req: AlignValidateRequest):
    global _catalog_cache
    if req.session_id not in _uploaded_align_cache:
        raise HTTPException(status_code=404, detail="Upload session expired. Please re-upload your annotation file.")
    if _catalog_cache is None:
        _catalog_cache = fetch_reference_catalog()

    df = _uploaded_align_cache[req.session_id]
    report = align_and_validate_dataframe(
        df=df,
        mapping=req.mapping,
        defaults=req.defaults,
        vocab_maps=req.vocab_maps,
        catalog=_catalog_cache,
    )
    return report


@app.post("/api/align/download-standardized")
def api_align_download_standardized(req: AlignValidateRequest):
    global _catalog_cache
    if req.session_id not in _uploaded_align_cache:
        raise HTTPException(status_code=404, detail="Upload session expired.")
    if _catalog_cache is None:
        _catalog_cache = fetch_reference_catalog()

    df = _uploaded_align_cache[req.session_id]
    report = align_and_validate_dataframe(df, req.mapping, req.defaults, req.vocab_maps, _catalog_cache)
    std_cols = [
        "recording_channel_id",
        "procedure_id",
        "organization_code",
        "call_type_code",
        "label_code",
        "granularity_code",
        "sharing_code",
        "start_time_utc",
        "end_time_utc",
        "tstzrange",
        "freq_min_hz",
        "freq_max_hz",
        "freqrange",
        "probability",
        "confidence",
        "analyst",
        "valid",
    ]
    out_df = pd.DataFrame(report["rows"])[std_cols]
    buf = io.StringIO()
    out_df.to_csv(buf, index=False)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="annomate_standardized_{ts}.csv"'},
    )


@app.post("/api/align/commit")
def api_align_commit(req: AlignCommitRequest):
    global _catalog_cache
    if req.session_id not in _uploaded_align_cache:
        raise HTTPException(status_code=404, detail="Upload session expired.")
    if _catalog_cache is None:
        _catalog_cache = fetch_reference_catalog()

    df = _uploaded_align_cache[req.session_id]
    defaults_copy = dict(req.defaults)
    if req.new_procedure and req.new_procedure.get("name"):
        defaults_copy["create_new_procedure"] = True
    report = align_and_validate_dataframe(df, req.mapping, defaults_copy, req.vocab_maps, _catalog_cache)
    if report["valid_rows"] == 0:
        raise HTTPException(status_code=400, detail="Zero valid rows available to commit. Fix validation issues first.")

    if is_demo_mode_active():
        return {
            "ok": True,
            "simulated_demo": True,
            "inserted_count": report["valid_rows"],
            "inserted_ids": list(range(90001, 90001 + min(50, report["valid_rows"]))),
            "procedure_id": defaults_copy.get("procedure_id") or 1,
            "created_new_procedure": bool(req.new_procedure and req.new_procedure.get("name")),
        }

    try:
        commit_res = commit_aligned_annotations(report["rows"], new_procedure=req.new_procedure)
        # Refresh catalog if new procedure was added
        if commit_res.get("created_new_procedure"):
            _catalog_cache = fetch_reference_catalog()
        return {"ok": True, **commit_res}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Database transaction rolled back: {exc}")


# ---------------------------------------------------------------------------
# Detailed Documentation Route (/guide) & Frontend Static Mount
# ---------------------------------------------------------------------------
GUIDE_SECTIONS = [
    ("quickstart", "00 · Quick Start & Setup", "00_QUICKSTART_AND_OVERVIEW.md"),
    ("find", "01 · Find & Filter Data", "01_FIND_AND_FILTER_GUIDE.md"),
    ("review", "02 · Marimo Review Studio", "02_MARIMO_REVIEW_STUDIO_GUIDE.md"),
    ("export", "03 · Export Data & Audio", "03_EXPORT_STUDIO_GUIDE.md"),
    ("align", "04 · Add & Align Annotations", "04_ADD_AND_ALIGN_ANNOTATIONS_GUIDE.md"),
    ("schema", "NMFS Schema & Data Architecture", "ANNOTATION_DATA_GUIDE.md"),
]


@app.get("/guide", response_class=HTMLResponse)
def serve_guide_page(section: str = Query("quickstart")):
    selected = next((item for item in GUIDE_SECTIONS if item[0] == section), GUIDE_SECTIONS[0])
    slug, _, filename = selected
    guide_md = (ROOT_DIR / "docs" / filename).read_text(encoding="utf-8")
    body_html = md_lib.markdown(guide_md, extensions=["tables", "fenced_code"])

    nav_links = "\n".join(
        f'<a class="nav-item {"active" if s == slug else ""}" href="/guide?section={s}">{label}</a>'
        for s, label, _ in GUIDE_SECTIONS
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Annomate · Component & Schema Documentation Hub</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@600;700&family=JetBrains+Mono:wght@400;500;600&family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0; background: #050c17; color: #e2e8f0;
      font-family: 'Plus Jakarta Sans', sans-serif; line-height: 1.72;
    }}
    .topbar {{
      position: sticky; top: 0; z-index: 20; backdrop-filter: blur(16px);
      background: rgba(5, 12, 23, 0.88); border-bottom: 1px solid rgba(56,189,248,0.16);
      padding: 14px 32px; display: flex; justify-content: space-between; align-items: center;
    }}
    .brand {{ font-family: 'Instrument Sans', sans-serif; font-size: 19px; font-weight: 700; color: #f8fafc; }}
    .brand span {{ font-family: 'JetBrains Mono', monospace; font-size: 11px; color: #22d3ee; margin-left: 10px; letter-spacing: 0.08em; }}
    .layout {{
      max-width: 1280px; margin: 0 auto; padding: 32px 28px 80px;
      display: grid; grid-template-columns: 270px minmax(0, 1fr); gap: 36px; align-items: start;
    }}
    .sidebar {{
      position: sticky; top: 82px; background: #0b1829; border: 1px solid rgba(56,189,248,0.18);
      border-radius: 14px; padding: 14px; display: flex; flex-direction: column; gap: 5px;
    }}
    .sidebar-title {{
      font-family: 'JetBrains Mono', monospace; font-size: 10.5px; color: #94a3b8;
      letter-spacing: 0.12em; text-transform: uppercase; padding: 6px 10px 8px;
    }}
    .nav-item {{
      padding: 9px 12px; border-radius: 9px; color: #cbd5e1; text-decoration: none;
      font-size: 13px; font-weight: 500; transition: all 0.15s ease; border: 1px solid transparent;
    }}
    .nav-item:hover {{ background: rgba(34,211,238,0.08); color: #f8fafc; }}
    .nav-item.active {{
      background: rgba(34,211,238,0.15); border-color: rgba(34,211,238,0.4);
      color: #22d3ee; font-weight: 600;
    }}
    .content-card {{
      background: #0a1525; border: 1px solid rgba(125,211,252,0.14); border-radius: 16px;
      padding: 34px 40px; box-shadow: 0 20px 44px -18px rgba(2,6,18,0.7);
    }}
    a {{ color: #22d3ee; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    h1, h2, h3 {{ font-family: 'Instrument Sans', sans-serif; color: #f8fafc; letter-spacing: -0.02em; }}
    h1 {{ font-size: 30px; margin-top: 0; }}
    h2 {{ font-size: 20px; margin-top: 34px; padding-bottom: 8px; border-bottom: 1px solid rgba(148,163,184,0.14); color: #38bdf8; }}
    code {{
      font-family: 'JetBrains Mono', monospace; font-size: 0.88em; background: rgba(15, 23, 42, 0.9);
      padding: 2px 6px; border-radius: 5px; border: 1px solid rgba(56,189,248,0.18); color: #67e8f9;
    }}
    pre {{
      background: #040b15; border: 1px solid rgba(56,189,248,0.2); border-radius: 10px;
      padding: 14px 16px; overflow-x: auto;
    }}
    pre code {{ background: none; border: none; padding: 0; color: #a5f3fc; }}
    blockquote {{
      margin: 20px 0; padding: 14px 20px; background: rgba(34,211,238,0.08);
      border-left: 3px solid #22d3ee; border-radius: 0 10px 10px 0;
    }}
    table {{ width: 100%; border-collapse: collapse; margin: 20px 0; background: #07111f; border-radius: 10px; overflow: hidden; }}
    th, td {{ text-align: left; padding: 11px 15px; border-bottom: 1px solid rgba(148,163,184,0.14); font-size: 13.5px; }}
    th {{ background: #0f2036; color: #22d3ee; font-family: 'JetBrains Mono', monospace; font-size: 11.5px; text-transform: uppercase; letter-spacing: 0.06em; }}
    hr {{ border: none; border-top: 1px solid rgba(148,163,184,0.14); margin: 30px 0; }}
    .btn {{
      padding: 7px 14px; border-radius: 8px; background: rgba(34,211,238,0.14);
      border: 1px solid rgba(34,211,238,0.4); color: #22d3ee; font-weight: 600; font-size: 12.5px; text-decoration: none;
    }}
    @media (max-width: 900px) {{ .layout {{ grid-template-columns: 1fr; }} .sidebar {{ position: static; }} }}
  </style>
</head>
<body>
  <header class="topbar">
    <div class="brand" style="display:flex; align-items:center; gap:10px;">
      <img src="/assets/annomate_tile_no_background.png" alt="annomate" style="width:34px; height:34px; object-fit:contain;" />
      annomate <span>DOCUMENTATION HUB</span>
    </div>
    <div style="display:flex; gap:10px;">
      <a class="btn" href="/">← Back to Annomate App</a>
      <a class="btn" href="http://127.0.0.1:2718" target="_blank">Marimo Studio ↗</a>
      <a class="btn" href="https://anndb-frontend-app-948464146942.us-east4.run.app/" target="_blank">Interactive ERD ↗</a>
    </div>
  </header>
  <div class="layout">
    <nav class="sidebar" aria-label="Component Guides">
      <div class="sidebar-title">Component Guides</div>
      {nav_links}
    </nav>
    <article class="content-card">
      {body_html}
    </article>
  </div>
</body>
</html>"""


@app.get("/vendor/plotly.min.js")
def serve_local_plotly():
    import plotly as _plotly_pkg

    plotly_js = Path(_plotly_pkg.__file__).resolve().parent / "package_data" / "plotly.min.js"
    if plotly_js.exists():
        return FileResponse(str(plotly_js), media_type="application/javascript")
    raise HTTPException(status_code=404, detail="Local plotly.min.js not found")


STATIC_DIR = ROOT_DIR / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
