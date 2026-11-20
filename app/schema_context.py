"""
Authoritative Schema Context, Composable SQL Builder, and Multimodal (Voice/Text)
Natural-Language-to-SQL Engine for `nmfs_annotation_db`.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from .config import get_settings

AUTHORITATIVE_SCHEMA_PROMPT = """You are an expert PostgreSQL + PostGIS bioacoustics SQL architect for NOAA NMFS's `nmfs_annotation_db`.
Generate ONE clean, read-only PostgreSQL `SELECT` (or `WITH ... SELECT`) query matching the user's request.

CRITICAL SCHEMA RULES:
1. Schemas:
   - `makara`: `organizations(code, name)`, `deployments(id, code, status, deployment_datetime, recovery_datetime, latitude, longitude, water_depth_m, vessel, cruise, organization_code, platform_type_code)`, `recordings(id, deployment_id, code, recording_start_datetime, recording_end_datetime, sample_rate_khz, bit_depth, recording_n_channels, recording_uri, usable_min_frequency_hz, usable_max_frequency_hz)`, `call_types(code, name, description)`, `sound_sources(code, name, scientific_name, itis_tsn, aphia_id)`, `call_types_sound_sources(call_type_code, sound_source_code)`, `analysis_granularity_types(code, name)`.
   - `core`:
     * `annotations(id, recording_channel_id, procedure_id, organization_code, call_type_code, label_code, granularity_code, sharing_code, tstzrange, freqrange, polygon, probability, confidence, analyst)`
     * `annotation_labels(code, legacy_id, name)`: codes are `'YES'`, `'NO'`, `'MAYBE'`, `'PROTOCOL_YES'`, `'PROTOCOL_NO'`, `'PROTOCOL_MAYBE'`, `'UNVERIFIED'`.
     * `sharing_scopes(code, name)`: `'ORG_INTERNAL'`, `'NOAA_INTERNAL'`, `'PACM_SUMMARY_ONLY'`, `'PUBLIC_DATA_ONLY'`, `'PUBLIC'`.
     * `recording_channels(id, recording_id, channel, tstzrange)` — `annotations.recording_channel_id` is the ONLY link from annotations to recordings & audio!
     * `audio_segments(id, acoustic_file_id, recording_channel_id, subfile_index, file_channel, tstzrange, sample_rate_hz, bit_depth, total_samples, duration_secs, data_byte_offset, data_byte_length)` — join to annotations using GiST-indexed overlap: `seg.recording_channel_id = a.recording_channel_id AND seg.tstzrange && a.tstzrange`.
     * `acoustic_files(id, obj_gsuri, obj_generation_number, format, name, size_bytes, channels, subfile_count)` — `seg.acoustic_file_id = af.id`.
     * `procedures(id, analysis_id, name, description, freqrange, analysts)` and `analyses(id, organization_code, code, name, protocol_reference, dataset_url)`.
     * `effort(id, organization_code, name, description)` -> `bins_effort(bin_id, effort_id)` -> `bins(id, recording_channel_id, tstzrange)` AND `effort_procedures(id, procedure_id, effort_id, call_type_code, effproc_type_code, effproc_assumption_code)`. Note: The recommended working dataset is effort `name = 'DCLDE_2013'`.
   - `reconcile`: `recording_status(recording_id, state, last_checked_at)`, `findings(id, recording_id, deployment_id, acoustic_file_id, finding_code, status)`.
2. Always project `tstzrange` and `freqrange` into user-friendly columns:
   `lower(a.tstzrange) AS start_time_utc`, `upper(a.tstzrange) AS end_time_utc`,
   `ROUND(EXTRACT(EPOCH FROM (upper(a.tstzrange) - lower(a.tstzrange)))::numeric, 3) AS duration_secs`,
   `lower(a.freqrange) AS freq_min_hz`, `upper(a.freqrange) AS freq_max_hz`.
3. Respect the requested metadata scope (`layers`): if the user selected ONLY `["annotations"]`, query `core.annotations` (with only necessary `EXISTS` filters if filtering by effort) without adding extra metadata columns unless asked.
4. Always include `a.id AS annotation_id` so downstream review & spectrogram lookup work seamlessly.
5. Return valid JSON ONLY with keys: `{"transcript": "...", "sql": "SELECT ...", "explanation": "Concise 1-2 sentence explanation of the query and joins."}`.
"""


def build_structured_sql(
    layers: List[str],
    filters: Optional[Dict[str, Any]] = None,
    limit: int = 500,
    random_sample: bool = False,
) -> Tuple[str, str]:
    """
    Build a clean, well-formatted, GiST-index-friendly PostgreSQL query
    from selected relational layers and filter criteria.
    """
    filters = filters or {}
    layer_set = set(layers or ["annotations"])
    layer_set.add("annotations")

    select_cols: List[str] = [
        "a.id AS annotation_id",
        "a.organization_code",
        "a.call_type_code",
        "a.label_code",
        "a.granularity_code",
        "a.sharing_code",
        "lower(a.tstzrange) AS start_time_utc",
        "upper(a.tstzrange) AS end_time_utc",
        "ROUND(EXTRACT(EPOCH FROM (upper(a.tstzrange) - lower(a.tstzrange)))::numeric, 3) AS duration_secs",
        "lower(a.freqrange) AS freq_min_hz",
        "upper(a.freqrange) AS freq_max_hz",
        "a.probability",
        "a.confidence",
        "a.analyst",
        "a.recording_channel_id",
        "a.procedure_id",
    ]

    joins: List[str] = []
    need_rc = bool({"makara", "audio", "reconcile"} & layer_set)
    need_rec = bool({"makara", "reconcile"} & layer_set)

    if "provenance" in layer_set:
        select_cols.extend(
            [
                "p.name AS procedure_name",
                "an.code AS analysis_code",
                "an.name AS analysis_name",
                "eff_lookup.effort_names",
            ]
        )
        joins.append("LEFT JOIN core.procedures p ON p.id = a.procedure_id")
        joins.append("LEFT JOIN core.analyses an ON an.id = p.analysis_id")
        joins.append(
            """LEFT JOIN (
    SELECT ep.procedure_id, string_agg(DISTINCT e.name, ', ' ORDER BY e.name) AS effort_names
    FROM core.effort_procedures ep
    JOIN core.effort e ON e.id = ep.effort_id
    GROUP BY ep.procedure_id
) eff_lookup ON eff_lookup.procedure_id = a.procedure_id"""
        )

    if need_rc:
        joins.append("JOIN core.recording_channels rc ON rc.id = a.recording_channel_id")
        select_cols.append("rc.channel")

    if need_rec:
        joins.append("JOIN makara.recordings rec ON rec.id = rc.recording_id")

    if "makara" in layer_set:
        joins.append("LEFT JOIN makara.deployments dep ON dep.id = rec.deployment_id")
        joins.append("LEFT JOIN makara.call_types ct ON ct.code = a.call_type_code")
        select_cols.extend(
            [
                "ct.name AS call_type_name",
                "rec.id AS recording_id",
                "rec.code AS recording_code",
                "rec.sample_rate_khz",
                "rec.recording_uri",
                "dep.code AS deployment_code",
                "dep.latitude",
                "dep.longitude",
                "dep.water_depth_m",
                "dep.platform_type_code",
            ]
        )

    if "audio" in layer_set:
        joins.append(
            """LEFT JOIN LATERAL (
    SELECT s.*
    FROM core.audio_segments s
    WHERE s.recording_channel_id IS NOT NULL
      AND s.recording_channel_id = a.recording_channel_id
      AND s.tstzrange && a.tstzrange
    ORDER BY lower(s.tstzrange) ASC
    LIMIT 1
) seg ON true"""
        )
        joins.append("LEFT JOIN core.acoustic_files af ON af.id = seg.acoustic_file_id")
        select_cols.extend(
            [
                "af.obj_gsuri",
                "af.format",
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
        )

    if "reconcile" in layer_set:
        joins.append("LEFT JOIN reconcile.recording_status rs ON rs.recording_id = rec.id")
        select_cols.extend(
            [
                "rs.state AS reconciliation_state",
                "rs.last_checked_at AS reconciliation_checked_at",
            ]
        )

    where_clauses: List[str] = []
    explanation_parts: List[str] = []

    def sql_lit(s: str) -> str:
        return "'" + str(s).replace("'", "''") + "'"

    effort_name = str(filters.get("effort_name") or "").strip()
    if effort_name:
        where_clauses.append(
            f"""(
        EXISTS (
            SELECT 1
            FROM core.bins b
            JOIN core.bins_effort be ON be.bin_id = b.id
            JOIN core.effort e ON e.id = be.effort_id
            WHERE b.recording_channel_id = a.recording_channel_id
              AND b.tstzrange && a.tstzrange
              AND e.name ILIKE {sql_lit(effort_name)}
        )
        OR EXISTS (
            SELECT 1
            FROM core.effort_procedures ep
            JOIN core.effort e ON e.id = ep.effort_id
            WHERE ep.procedure_id = a.procedure_id
              AND e.name ILIKE {sql_lit(effort_name)}
        )
    )"""
        )
        explanation_parts.append(f"scoped to effort sample '{effort_name}' via GiST bin overlap / procedure linkage")

    org = str(filters.get("organization_code") or "").strip()
    if org:
        where_clauses.append(f"a.organization_code = {sql_lit(org.upper())}")
        explanation_parts.append(f"organization '{org.upper()}'")

    call_type = str(filters.get("call_type_code") or "").strip()
    if call_type:
        where_clauses.append(f"a.call_type_code ILIKE {sql_lit(call_type)}")
        explanation_parts.append(f"call type '{call_type}'")

    label_codes = filters.get("label_codes")
    if isinstance(label_codes, str) and label_codes.strip():
        label_codes = [x.strip().upper() for x in label_codes.split(",") if x.strip()]
    if isinstance(label_codes, list) and label_codes:
        lits = ", ".join(sql_lit(x.upper()) for x in label_codes)
        where_clauses.append(f"a.label_code IN ({lits})")
        explanation_parts.append(f"verification label in ({', '.join(label_codes)})")

    granularity = str(filters.get("granularity_code") or "").strip()
    if granularity:
        where_clauses.append(f"a.granularity_code = {sql_lit(granularity.upper())}")

    sharing = str(filters.get("sharing_code") or "").strip()
    if sharing:
        where_clauses.append(f"a.sharing_code = {sql_lit(sharing.upper())}")

    fmin = filters.get("freq_min_hz")
    fmax = filters.get("freq_max_hz")
    if fmin is not None and str(fmin).strip() != "" and fmax is not None and str(fmax).strip() != "":
        lo = float(fmin)
        hi = float(fmax)
        where_clauses.append(f"a.freqrange && '[{lo}, {hi}]'::core.freqrange")
        explanation_parts.append(f"frequency overlapping {lo:g}–{hi:g} Hz")
    elif fmin is not None and str(fmin).strip() != "":
        lo = float(fmin)
        where_clauses.append(f"upper(a.freqrange) >= {lo}")
        explanation_parts.append(f"frequency >= {lo:g} Hz")
    elif fmax is not None and str(fmax).strip() != "":
        hi = float(fmax)
        where_clauses.append(f"lower(a.freqrange) <= {hi}")
        explanation_parts.append(f"frequency <= {hi:g} Hz")

    start_after = str(filters.get("start_after_utc") or "").strip()
    end_before = str(filters.get("end_before_utc") or "").strip()
    if start_after and end_before:
        where_clauses.append(
            f"a.tstzrange && tstzrange({sql_lit(start_after)}::timestamptz, {sql_lit(end_before)}::timestamptz, '[)')"
        )
        explanation_parts.append(f"time window {start_after} to {end_before}")
    elif start_after:
        where_clauses.append(f"upper(a.tstzrange) >= {sql_lit(start_after)}::timestamptz")
    elif end_before:
        where_clauses.append(f"lower(a.tstzrange) <= {sql_lit(end_before)}::timestamptz")

    min_conf = filters.get("min_confidence")
    if min_conf is not None and str(min_conf).strip() != "":
        where_clauses.append(f"COALESCE(a.confidence, a.probability, 1.0) >= {float(min_conf)}")
        explanation_parts.append(f"confidence/probability >= {float(min_conf):g}")

    if filters.get("require_audio_file"):
        if "audio" in layer_set:
            where_clauses.append("af.obj_gsuri IS NOT NULL")
        else:
            where_clauses.append(
                """EXISTS (
        SELECT 1 FROM core.audio_segments s2
        WHERE s2.recording_channel_id = a.recording_channel_id
          AND s2.tstzrange && a.tstzrange
    )"""
            )
        explanation_parts.append("with linked GCS audio segments")

    safe_limit = max(1, min(int(limit or 500), 10000))
    order_clause = "ORDER BY random()" if random_sample else "ORDER BY lower(a.tstzrange) ASC, a.id ASC"

    sql_lines = [
        "SELECT",
        "    " + ",\n    ".join(select_cols),
        "FROM core.annotations a",
    ]
    if joins:
        sql_lines.extend(joins)
    if where_clauses:
        sql_lines.append("WHERE " + "\n  AND ".join(where_clauses))
    sql_lines.append(order_clause)
    sql_lines.append(f"LIMIT {safe_limit};")

    layer_desc = {
        "annotations": "core.annotations",
        "provenance": "study/procedure/effort provenance",
        "makara": "Makara recording & deployment metadata",
        "audio": "GCS acoustic files & segment byte offsets",
        "reconcile": "reconciliation health",
    }
    included_str = ", ".join(layer_desc[k] for k in ["annotations", "provenance", "makara", "audio", "reconcile"] if k in layer_set)
    filter_str = "; ".join(explanation_parts) if explanation_parts else "all available annotations"
    explanation = f"Queries {included_str} ({filter_str}), returning up to {safe_limit:,} rows."

    return "\n".join(sql_lines), explanation


def _parse_nl_heuristics(
    prompt_text: str,
    selected_layers: List[str],
    ui_filters: Optional[Dict[str, Any]] = None,
    catalog: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Deterministic, schema-aware natural language parser for bioacoustic queries.
    Extracts layers, effort names, call types, labels, frequency bands, dates, and limits.
    """
    text = (prompt_text or "").strip()
    lower = text.lower()
    merged_layers = list(dict.fromkeys(selected_layers or ["annotations"]))
    filters: Dict[str, Any] = dict(ui_filters or {})
    limit = int(filters.pop("limit", 500) or 500)
    random_sample = bool(filters.pop("random_sample", False))

    # Detect requested relational metadata layers from natural language unless user locked "only annotations"
    only_ann = any(p in lower for p in ["only annotation", "annotations only", "just annotation"])
    if only_ann:
        merged_layers = ["annotations"]
    else:
        if any(w in lower for w in ["gcs", "audio", "wav", "flac", "xwav", "uri", "path", "file", "segment", "spectrogram", "byte"]):
            if "audio" not in merged_layers:
                merged_layers.append("audio")
        if any(w in lower for w in ["deploy", "lat", "lon", "coord", "depth", "site", "vessel", "cruise", "makara", "platform", "map"]):
            if "makara" not in merged_layers:
                merged_layers.append("makara")
        if any(w in lower for w in ["effort", "study", "procedure", "protocol", "analysis", "dclde"]):
            if "provenance" not in merged_layers:
                merged_layers.append("provenance")
        if any(w in lower for w in ["reconcil", "finding", "status", "integrity", "audit"]):
            if "reconcile" not in merged_layers:
                merged_layers.append("reconcile")

    # Effort detection (e.g. DCLDE_2013 or catalog efforts)
    if not filters.get("effort_name"):
        if "dclde" in lower:
            filters["effort_name"] = "DCLDE_2013"
        elif catalog and catalog.get("efforts"):
            for eff in catalog["efforts"]:
                ename = str(eff.get("name") or "")
                if ename and ename.lower() in lower:
                    filters["effort_name"] = ename
                    break

    # Organization detection
    if not filters.get("organization_code"):
        for org_code in ["NEFSC", "SWFSC", "AFSC", "PIFSC", "SEFSC", "NWFSC", "HQ"]:
            if re.search(rf"\b{org_code.lower()}\b", lower):
                filters["organization_code"] = org_code
                break

    # Label verification detection
    if not filters.get("label_codes"):
        detected_labels: List[str] = []
        if any(p in lower for p in ["verified positive", "positive", "confirmed", "label yes", "true call"]):
            detected_labels.append("YES")
        if any(p in lower for p in ["false positive", "negative", "rejected", "label no"]):
            detected_labels.append("NO")
        if any(p in lower for p in ["uncertain", "maybe", "possible"]):
            detected_labels.append("MAYBE")
        if any(p in lower for p in ["unverified", "candidate", "raw detector"]):
            detected_labels.append("UNVERIFIED")
        if detected_labels:
            filters["label_codes"] = detected_labels

    # Call type matching against live catalog + common synonyms
    if not filters.get("call_type_code"):
        if catalog and catalog.get("call_types"):
            for ct in catalog["call_types"]:
                code = str(ct.get("code") or "")
                name = str(ct.get("name") or "")
                if code and re.search(rf"\b{re.escape(code.lower())}\b", lower):
                    filters["call_type_code"] = code
                    break
                if name and len(name) >= 4 and name.lower() in lower:
                    filters["call_type_code"] = code
                    break
        if not filters.get("call_type_code"):
            if "upcall" in lower or "up-call" in lower:
                # Match catalog upcall code if present
                up_match = next(
                    (
                        c["code"]
                        for c in (catalog or {}).get("call_types", [])
                        if "up" in str(c.get("code", "")).lower() or "upcall" in str(c.get("name", "")).lower()
                    ),
                    None,
                )
                if up_match:
                    filters["call_type_code"] = up_match
            elif "gunshot" in lower:
                gs_match = next(
                    (
                        c["code"]
                        for c in (catalog or {}).get("call_types", [])
                        if "gun" in str(c.get("code", "")).lower() or "gunshot" in str(c.get("name", "")).lower()
                    ),
                    None,
                )
                if gs_match:
                    filters["call_type_code"] = gs_match

    # Frequency range parsing: "between 80 and 250 hz" or "80-250 hz"
    freq_between = re.search(r"(?:between\s+)?(\d+(?:\.\d+)?)\s*(?:and|to|\-|–)\s*(\d+(?:\.\d+)?)\s*(khz|hz)", lower)
    if freq_between:
        mult = 1000.0 if freq_between.group(3) == "khz" else 1.0
        filters["freq_min_hz"] = float(freq_between.group(1)) * mult
        filters["freq_max_hz"] = float(freq_between.group(2)) * mult
    else:
        above_m = re.search(r"(?:above|over|>=?|greater than)\s*(\d+(?:\.\d+)?)\s*(khz|hz)", lower)
        below_m = re.search(r"(?:below|under|<=?|less than)\s*(\d+(?:\.\d+)?)\s*(khz|hz)", lower)
        if above_m:
            mult = 1000.0 if above_m.group(2) == "khz" else 1.0
            filters["freq_min_hz"] = float(above_m.group(1)) * mult
        if below_m:
            mult = 1000.0 if below_m.group(2) == "khz" else 1.0
            filters["freq_max_hz"] = float(below_m.group(1)) * mult

    # Year filter: "in 2009" / "from 2013" (avoid matching DCLDE_2013!)
    cleaned_for_year = re.sub(r"dclde[_\s]*\d{4}", "", lower)
    year_m = re.search(r"\b(199\d|20[0-2]\d)\b", cleaned_for_year)
    if year_m and not filters.get("start_after_utc"):
        yr = int(year_m.group(1))
        filters["start_after_utc"] = f"{yr}-01-01T00:00:00Z"
        filters["end_before_utc"] = f"{yr + 1}-01-01T00:00:00Z"

    # Confidence threshold
    conf_m = re.search(r"(?:confidence|probability|score)\s*(?:above|over|>=?|>)\s*(0?\.\d+|\d+%)", lower)
    if conf_m:
        raw_c = conf_m.group(1)
        filters["min_confidence"] = float(raw_c[:-1]) / 100.0 if raw_c.endswith("%") else float(raw_c)

    # Random sample & limit
    if "random" in lower or "sample" in lower and "effort" not in lower:
        random_sample = True
    lim_m = re.search(r"(?:limit|top|first|sample of|random)\s+(\d{1,5})\b", lower)
    if lim_m:
        limit = int(lim_m.group(1))

    if any(p in lower for p in ["with audio", "has audio", "populated audio"]):
        filters["require_audio_file"] = True

    sql, explanation = build_structured_sql(
        layers=merged_layers,
        filters=filters,
        limit=limit,
        random_sample=random_sample,
    )
    return {
        "transcript": text,
        "sql": sql,
        "explanation": explanation,
        "layers_used": merged_layers,
        "engine": "schema_aware_parser",
    }


def generate_sql_from_prompt(
    prompt_text: str = "",
    selected_layers: Optional[List[str]] = None,
    ui_filters: Optional[Dict[str, Any]] = None,
    catalog: Optional[Dict[str, Any]] = None,
    audio_bytes: Optional[bytes] = None,
    audio_mime: str = "audio/webm",
) -> Dict[str, Any]:
    """
    Convert user text and/or spoken voice audio into a PostgreSQL query against `nmfs_annotation_db`.
    Uses Gemini (`gemini-2.5-flash`) when `GEMINI_API_KEY` is configured, falling back seamlessly
    to the built-in schema-aware bioacoustics parser.
    """
    selected_layers = selected_layers or ["annotations", "makara", "audio"]
    settings = get_settings()

    if settings.gemini_api_key:
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=settings.gemini_api_key)
            catalog_context = ""
            if catalog:
                eff_names = [e["name"] for e in catalog.get("efforts", [])[:15]]
                call_codes = [f"{c['code']} ({c.get('name', '')})" for c in catalog.get("call_types", [])[:40]]
                org_codes = [o["code"] for o in catalog.get("organizations", [])]
                catalog_context = (
                    f"\nLive DB Catalog Values:\n"
                    f"- Organizations: {org_codes}\n"
                    f"- Effort samples: {eff_names}\n"
                    f"- Call types: {call_codes}\n"
                )

            user_context = (
                f"Selected relational layers: {selected_layers}\n"
                f"Structured UI filters: {json.dumps(ui_filters or {})}\n"
                f"User text prompt: {prompt_text or '(Listen to attached voice prompt and transcribe it into `transcript`)'}"
                f"{catalog_context}"
            )
            contents: List[Any] = [AUTHORITATIVE_SCHEMA_PROMPT, user_context]
            if audio_bytes:
                contents.append(types.Part.from_bytes(data=audio_bytes, mime_type=audio_mime))

            resp = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1,
                ),
            )
            parsed = json.loads(resp.text)
            if parsed.get("sql"):
                return {
                    "transcript": parsed.get("transcript") or prompt_text,
                    "sql": parsed["sql"],
                    "explanation": parsed.get("explanation") or "Generated by Gemini using the authoritative NMFS schema.",
                    "layers_used": selected_layers,
                    "engine": "gemini-2.5-flash",
                }
        except Exception as gemini_exc:
            fallback = _parse_nl_heuristics(prompt_text, selected_layers, ui_filters, catalog)
            fallback["gemini_note"] = f"Used local schema parser (Gemini error: {gemini_exc})"
            return fallback

    return _parse_nl_heuristics(prompt_text, selected_layers, ui_filters, catalog)
