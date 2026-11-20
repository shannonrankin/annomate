from pathlib import Path as _Path
import marimo

__generated_with = "0.25.2"
app = marimo.App(
    width="full",
    app_title="Annomate · Bioacoustic Review Studio",
    css_file=str(_Path(__file__).with_name("marimo_theme.css")),
)


@app.cell
def _():
    import base64
    import json
    import os
    from pathlib import Path
    import sys

    import marimo as mo
    import numpy as np
    import pandas as pd
    import plotly.express as px
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    ROOT_DIR = Path(__file__).resolve().parent.parent
    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))

    from app.audio_engine import compute_spectrogram_payload
    from app.bathy_and_pampal import (
        build_bathymetry_deployment_figure,
        infer_dataset_timezone,
        render_pampal_pamscapes_suite,
    )
    from app.config import REVIEW_SESSION_DIR, get_settings
    from app.db import execute_readonly_query, fetch_annotation_audio_context
    from app.schema_context import build_structured_sql

    logo_path = ROOT_DIR / "static" / "assets" / "annomate_tile_no_background.png"
    logo_b64 = base64.b64encode(logo_path.read_bytes()).decode("ascii") if logo_path.exists() else ""

    SHADOW_STYLE = """
    <style>
      .ann-hero-banner {
        background: linear-gradient(135deg, #09182c 0%, #0f2942 55%, #0c2338 100%);
        border: 1px solid rgba(34, 211, 238, 0.30);
        border-radius: 16px;
        padding: 22px 26px;
        color: #f1f5f9;
        box-shadow: 0 18px 40px -16px rgba(2, 8, 23, 0.65);
        font-family: 'Plus Jakarta Sans', system-ui, sans-serif;
      }
      .ann-hero-eyebrow {
        font-family: 'JetBrains Mono', monospace;
        font-size: 11px;
        letter-spacing: 0.14em;
        text-transform: uppercase;
        color: #22d3ee;
        margin-bottom: 5px;
        font-weight: 600;
      }
      .ann-hero-title {
        font-size: 25px;
        font-weight: 700;
        letter-spacing: -0.02em;
        color: #f8fafc;
        margin: 0 0 6px 0;
      }
      .ann-steps-grid {
        display: grid;
        grid-template-columns: repeat(4, minmax(170px, 1fr));
        gap: 12px;
        margin-top: 16px;
      }
      .ann-step-pill {
        background: rgba(7, 17, 31, 0.72);
        border: 1px solid rgba(148, 163, 184, 0.22);
        border-radius: 10px;
        padding: 11px 13px;
        font-size: 12.5px;
        line-height: 1.45;
        color: #cbd5e1;
      }
      .ann-step-pill strong { color: #22d3ee; font-family: monospace; }
      .ann-kpi-strip {
        display: grid;
        grid-template-columns: repeat(5, minmax(140px, 1fr));
        gap: 12px;
        margin: 10px 0 4px;
        font-family: 'Plus Jakarta Sans', system-ui, sans-serif;
      }
      .ann-kpi-card {
        background: linear-gradient(180deg, #0e1e33 0%, #091424 100%);
        border: 1px solid rgba(56, 189, 248, 0.22);
        border-radius: 12px;
        padding: 14px 16px;
        color: #f1f5f9;
      }
      .ann-kpi-label {
        font-size: 10.5px;
        text-transform: uppercase;
        letter-spacing: 0.09em;
        color: #94a3b8;
        font-family: monospace;
      }
      .ann-kpi-val {
        font-size: 22px;
        font-weight: 700;
        color: #f8fafc;
        margin-top: 5px;
        font-variant-numeric: tabular-nums;
      }
      .ann-audio-panel {
        background: linear-gradient(135deg, #0b192b 0%, #091424 100%);
        border: 1px solid rgba(34, 211, 238, 0.28);
        border-radius: 14px;
        padding: 15px 20px;
        color: #e2e8f0;
        font-family: 'Plus Jakarta Sans', system-ui, sans-serif;
      }
      .ann-badge-live {
        display: inline-block; padding: 3px 9px; border-radius: 999px; font-family: monospace;
        font-size: 11px; font-weight: 600; background: rgba(16, 185, 129, 0.18); color: #34d399; border: 1px solid rgba(52, 211, 153, 0.4);
      }
      .ann-badge-synth {
        display: inline-block; padding: 3px 9px; border-radius: 999px; font-family: monospace;
        font-size: 11px; font-weight: 600; background: rgba(245, 158, 11, 0.16); color: #fbbf24; border: 1px solid rgba(251, 191, 36, 0.4);
      }
      /* 'gcloud auth login' command highlight: White in Dark Mode, Blue in Light Mode */
      .ann-gcloud-cmd {
        font-family: 'JetBrains Mono', monospace;
        font-weight: 700;
        color: #ffffff;
        background: rgba(255, 255, 255, 0.13);
        border: 1px solid rgba(255, 255, 255, 0.32);
        padding: 1px 7px;
        border-radius: 5px;
      }
      :host-context(.light) .ann-gcloud-cmd,
      :host-context([data-theme="light"]) .ann-gcloud-cmd {
        color: #1d4ed8;
        background: rgba(29, 78, 216, 0.10);
        border: 1px solid rgba(29, 78, 216, 0.32);
      }
      .ann-play-btn {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 9px 16px;
        border-radius: 999px;
        border: 1px solid rgba(34, 211, 238, 0.45);
        background: rgba(34, 211, 238, 0.16);
        color: #f8fafc;
        font-family: 'Plus Jakarta Sans', system-ui, sans-serif;
        font-size: 13px;
        font-weight: 600;
        cursor: pointer;
      }
      .ann-play-btn:hover {
        background: rgba(34, 211, 238, 0.28);
      }
      .ann-play-btn.warn {
        border-color: rgba(251, 191, 36, 0.45);
        background: rgba(245, 158, 11, 0.15);
        color: #fef3c7;
      }
      .ann-audio-popup {
        margin-top: 10px;
        padding: 11px 14px;
        border-radius: 10px;
        background: rgba(127, 29, 29, 0.42);
        border: 1px solid rgba(251, 113, 133, 0.55);
        color: #fecdd3;
        font-size: 12.5px;
        line-height: 1.5;
      }
      .ann-pampal-grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(260px, 1fr));
        gap: 14px;
        margin-top: 10px;
      }
      .ann-pampal-card {
        background: #0b192b;
        border: 1px solid rgba(56, 189, 248, 0.22);
        border-radius: 12px;
        padding: 10px;
      }
      .ann-pampal-card img {
        width: 100%;
        height: auto;
        border-radius: 8px;
        display: block;
      }
    </style>
    """
    settings = get_settings()
    app_base_url = f"http://127.0.0.1:{settings.app_port}"
    return (
        Path,
        REVIEW_SESSION_DIR,
        ROOT_DIR,
        SHADOW_STYLE,
        app_base_url,
        base64,
        build_bathymetry_deployment_figure,
        build_structured_sql,
        compute_spectrogram_payload,
        execute_readonly_query,
        fetch_annotation_audio_context,
        get_settings,
        go,
        infer_dataset_timezone,
        json,
        logo_b64,
        make_subplots,
        mo,
        np,
        os,
        pd,
        px,
        render_pampal_pamscapes_suite,
        settings,
    )


@app.cell
def _(SHADOW_STYLE, app_base_url, logo_b64, mo, settings):
    logo_html = (
        f'<img src="data:image/png;base64,{logo_b64}" alt="annomate" style="width:52px; height:52px; object-fit:contain; flex-shrink:0;" />'
        if logo_b64
        else ""
    )
    mo.Html(
        SHADOW_STYLE
        + f"""
        <div class="ann-hero-banner">
          <div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:14px;">
            <div style="display:flex; align-items:center; gap:15px;">
              {logo_html}
              <div>
                <div class="ann-hero-eyebrow">ANNOMATE · REACTIVE MARIMO REVIEW STUDIO</div>
                <h1 class="ann-hero-title">Bioacoustic Call Verification &amp; Exploratory Studio</h1>
                <div style="color:#94a3b8; font-size:13.5px; max-width:780px;">
                  Explore staged acoustic annotation datasets from <code>nmfs_annotation_db</code>, reproducibly subset large call catalogs,
                  inspect linked cloud spectrograms &amp; PAMpal/PAMscapes visualizations, and interrogate your dataset conversationally.
                </div>
              </div>
            </div>
            <div style="display:flex; gap:10px; align-items:center; flex-wrap:wrap;">
              <a href="{app_base_url}" target="_blank"
                 style="padding:8px 14px; border-radius:9px; background:rgba(34,211,238,0.14); border:1px solid rgba(34,211,238,0.4); color:#22d3ee; text-decoration:none; font-size:12.5px; font-weight:600;">
                 ← Return to Annomate Platform
              </a>
              <a href="{app_base_url}/guide?section=review" target="_blank"
                 style="padding:8px 14px; border-radius:9px; background:rgba(148,163,184,0.12); border:1px solid rgba(148,163,184,0.3); color:#e2e8f0; text-decoration:none; font-size:12.5px; font-weight:600;">
                 Detailed Review Guide ↗
              </a>
              <a href="{settings.erd_url}" target="_blank"
                 style="padding:8px 14px; border-radius:9px; background:rgba(20,184,166,0.14); border:1px solid rgba(20,184,166,0.35); color:#2dd4bf; text-decoration:none; font-size:12.5px; font-weight:600;">
                 Interactive NMFS ERD ↗
              </a>
            </div>
          </div>
          <div class="ann-steps-grid">
            <div class="ann-step-pill"><strong>01 · Choose &amp; Subset</strong><br/>Load staged queries or <code>DCLDE_2013</code> and stratify by granularity, label, or call type.</div>
            <div class="ann-step-pill"><strong>02 · Bathymetry &amp; PAMpal</strong><br/>Explore ETOPO bathymetric maps and authentic R <code>PAMscapes</code> / <code>PAMpal</code> plots.</div>
            <div class="ann-step-pill"><strong>03 · Spectrogram &amp; Audio</strong><br/>Inspect any call (or the synthetic reference call) with tunable STFT parameters.</div>
            <div class="ann-step-pill"><strong>04 · Chat &amp; Export</strong><br/>Ask the embedded Bioacoustics Assistant questions and save your reviewed subset.</div>
          </div>
        </div>
        """
    )
    return


@app.cell
def _(REVIEW_SESSION_DIR, json, mo):
    staged_csv_path = REVIEW_SESSION_DIR / "active_review.csv"
    staged_meta_path = REVIEW_SESSION_DIR / "session_meta.json"
    has_staged = staged_csv_path.exists()
    staged_meta = {}
    if staged_meta_path.exists():
        try:
            staged_meta = json.loads(staged_meta_path.read_text(encoding="utf-8"))
        except Exception:
            staged_meta = {}

    default_source = "staged" if has_staged else "dclde_live"
    source_selector = mo.ui.dropdown(
        options={
            "Staged Dataset from Annomate Find & Filter": "staged",
            "Live DB · DCLDE_2013 Right Whale Upcalls (NEFSC)": "dclde_live",
            "Upload Custom CSV File": "upload",
        },
        value="Staged Dataset from Annomate Find & Filter" if default_source == "staged" else "Live DB · DCLDE_2013 Right Whale Upcalls (NEFSC)",
        label="Dataset Source",
    )
    csv_uploader = mo.ui.file(filetypes=[".csv", ".tsv"], label="Optional CSV Upload")
    refresh_btn = mo.ui.run_button(label="Reload Dataset")

    mo.hstack([source_selector, csv_uploader, refresh_btn], justify="start", align="end", gap=1.5)
    return csv_uploader, refresh_btn, source_selector, staged_csv_path, staged_meta


@app.cell
def _(
    build_structured_sql,
    csv_uploader,
    execute_readonly_query,
    pd,
    refresh_btn,
    source_selector,
    staged_csv_path,
    staged_meta,
):
    _ = refresh_btn.value
    import io as _io

    source_mode = source_selector.value
    dataset_label = ""

    if source_mode == "upload" and csv_uploader.value:
        uploaded_item = csv_uploader.value[0]
        full_df = pd.read_csv(_io.BytesIO(uploaded_item.contents))
        dataset_label = f"Uploaded File: {uploaded_item.name}"
    elif source_mode == "staged" and staged_csv_path.exists():
        full_df = pd.read_csv(staged_csv_path)
        prompt_desc = staged_meta.get("prompt") or "Staged SQL Query"
        dataset_label = f"Staged from Annomate ({prompt_desc})"
    else:
        sql_q, _ = build_structured_sql(
            layers=["annotations", "provenance", "makara", "audio"],
            filters={"effort_name": "DCLDE_2013"},
            limit=2000,
        )
        res = execute_readonly_query(sql_q, max_rows=2000)
        full_df = pd.DataFrame(res["rows"])
        dataset_label = f"Live nmfs_annotation_db · DCLDE_2013 ({res['mode']})"

    for _col in ("freq_min_hz", "freq_max_hz", "duration_secs", "latitude", "longitude", "sample_rate_hz"):
        if _col in full_df.columns:
            full_df[_col] = pd.to_numeric(full_df[_col], errors="coerce")

    if "start_time_utc" in full_df.columns and "end_time_utc" in full_df.columns and "duration_secs" not in full_df.columns:
        _st = pd.to_datetime(full_df["start_time_utc"], utc=True, errors="coerce")
        _et = pd.to_datetime(full_df["end_time_utc"], utc=True, errors="coerce")
        full_df["duration_secs"] = (_et - _st).dt.total_seconds().round(3)

    return dataset_label, full_df, source_mode


@app.cell
def _(full_df, mo):
    total_available = max(1, len(full_df))
    default_n = min(250, total_available)

    subset_mode = mo.ui.radio(
        options={
            "Random Subset (Recommended for rapid review)": "random",
            "All Loaded Rows": "all",
        },
        value="Random Subset (Recommended for rapid review)" if total_available > 250 else "All Loaded Rows",
        inline=True,
        label="Sampling Mode",
    )
    sample_n = mo.ui.slider(
        start=min(10, total_available),
        stop=total_available,
        step=max(1, total_available // 100),
        value=default_n,
        show_value=True,
        label="Subset Size (N calls)",
    )

    # Always expose Granularity alongside Label, Call Type, Recording, Organization & Analyst
    stratify_opts = {"None (Uniform Random)": "none"}
    for _display_lbl, _cand in [
        ("Granularity (granularity_code)", "granularity_code"),
        ("Verification Label (label_code)", "label_code"),
        ("Call Type (call_type_code)", "call_type_code"),
        ("Recording (recording_code)", "recording_code"),
        ("Organization (organization_code)", "organization_code"),
        ("Analyst (analyst)", "analyst"),
    ]:
        if _cand in full_df.columns or _cand == "granularity_code":
            stratify_opts[f"Stratify by {_display_lbl}"] = _cand

    stratify_by = mo.ui.dropdown(
        options=stratify_opts,
        value="None (Uniform Random)",
        label="Stratification",
    )
    seed_input = mo.ui.number(start=1, stop=99999, step=1, value=42, label="Random Seed")

    mo.callout(
        mo.vstack(
            [
                mo.md("### Reproducible Random Subsetting"),
                mo.md(
                    "Large passive acoustic catalogs can contain thousands of detections. "
                    "Use uniform random or stratified sampling (by **Granularity**, **Verification Label**, **Call Type**, etc.) to review an unbiased, reproducible sample."
                ),
                mo.hstack([subset_mode, sample_n, stratify_by, seed_input], justify="start", align="center", wrap=True, gap=2.0),
            ]
        ),
        kind="info",
    )
    return sample_n, seed_input, stratify_by, subset_mode


@app.cell
def _(SHADOW_STYLE, dataset_label, full_df, mo, sample_n, seed_input, stratify_by, subset_mode):
    if full_df.empty:
        subset_df = full_df.copy()
    elif subset_mode.value == "all" or sample_n.value >= len(full_df):
        subset_df = full_df.copy().reset_index(drop=True)
    else:
        target_k = int(sample_n.value)
        seed_val = int(seed_input.value or 42)
        strat_col = stratify_by.value
        if strat_col != "none" and strat_col in full_df.columns and full_df[strat_col].nunique(dropna=True) > 1:
            frac = min(1.0, target_k / len(full_df))
            subset_df = (
                full_df.groupby(strat_col, dropna=False, group_keys=False)
                .apply(lambda g: g.sample(n=min(len(g), max(1, round(len(g) * frac))), random_state=seed_val))
                .head(target_k)
                .reset_index(drop=True)
            )
        else:
            subset_df = (
                full_df.sample(n=min(target_k, len(full_df)), random_state=seed_val)
                .sort_values(by="start_time_utc" if "start_time_utc" in full_df.columns else full_df.columns[0])
                .reset_index(drop=True)
            )

    n_sub = len(subset_df)
    n_tot = len(full_df)
    n_yes = int((subset_df["label_code"] == "YES").sum()) if "label_code" in subset_df.columns else n_sub
    med_dur = f"{subset_df['duration_secs'].median():.2f}s" if "duration_secs" in subset_df.columns and not subset_df["duration_secs"].dropna().empty else "—"
    freq_span = (
        f"{subset_df['freq_min_hz'].min():.0f}–{subset_df['freq_max_hz'].max():.0f} Hz"
        if "freq_min_hz" in subset_df.columns and "freq_max_hz" in subset_df.columns and not subset_df["freq_min_hz"].dropna().empty
        else "—"
    )
    n_audio = int(subset_df["obj_gsuri"].notna().sum()) if "obj_gsuri" in subset_df.columns else 0

    kpi_html = mo.Html(
        SHADOW_STYLE
        + f"""
        <div style="font-size:12px; color:#94a3b8; margin-bottom:4px; font-family:monospace;">
          ACTIVE SOURCE: <strong style="color:#22d3ee;">{dataset_label}</strong> · Showing {n_sub:,} of {n_tot:,} loaded rows
        </div>
        <div class="ann-kpi-strip">
          <div class="ann-kpi-card"><div class="ann-kpi-label">Active Subset</div><div class="ann-kpi-val">{n_sub:,} <span style="font-size:13px;color:#64748b;">/ {n_tot:,}</span></div></div>
          <div class="ann-kpi-card"><div class="ann-kpi-label">Verified Positive (YES)</div><div class="ann-kpi-val" style="color:#34d399;">{n_yes:,}</div></div>
          <div class="ann-kpi-card"><div class="ann-kpi-label">Median Call Duration</div><div class="ann-kpi-val">{med_dur}</div></div>
          <div class="ann-kpi-card"><div class="ann-kpi-label">Frequency Envelope</div><div class="ann-kpi-val" style="color:#22d3ee;">{freq_span}</div></div>
          <div class="ann-kpi-card"><div class="ann-kpi-label">Linked GCS Audio</div><div class="ann-kpi-val">{n_audio:,}</div></div>
        </div>
        """
    )
    kpi_html
    return subset_df


@app.cell
def _(build_bathymetry_deployment_figure, mo, pd, px, subset_df):
    plot_template = "plotly_dark"
    common_layout = {
        "paper_bgcolor": "#0b192b",
        "plot_bgcolor": "#07111f",
        "font": {"family": "Plus Jakarta Sans, sans-serif", "color": "#e2e8f0", "size": 12},
        "margin": {"l": 48, "r": 24, "t": 48, "b": 42},
    }

    figs = []

    # 1. Diel UTC Hour vs Date Heatmap
    if "start_time_utc" in subset_df.columns and not subset_df.empty:
        _ts = pd.to_datetime(subset_df["start_time_utc"], utc=True, errors="coerce").dropna()
        if not _ts.empty:
            _tdf = pd.DataFrame({"date": _ts.dt.strftime("%Y-%m-%d"), "hour_utc": _ts.dt.hour})
            _piv = _tdf.groupby(["date", "hour_utc"]).size().reset_index(name="calls")
            fig_diel = px.density_heatmap(
                _piv,
                x="date",
                y="hour_utc",
                z="calls",
                nbinsy=24,
                color_continuous_scale="Tealgrn",
                title="Diel & Daily Acoustic Call Density (UTC Hour × Date)",
                labels={"date": "UTC Date", "hour_utc": "Hour of Day (UTC)", "calls": "Annotations"},
                template=plot_template,
            )
            fig_diel.update_coloraxes(colorbar_title="Calls")
            fig_diel.update_layout(**common_layout, height=330)
            figs.append(fig_diel)

    # 2. Time-Frequency Acoustic Space
    if {"freq_min_hz", "freq_max_hz", "duration_secs"}.issubset(subset_df.columns) and not subset_df.empty:
        _fdf = subset_df.dropna(subset=["freq_min_hz", "freq_max_hz", "duration_secs"]).copy()
        if not _fdf.empty:
            _fdf["center_freq_hz"] = ((_fdf["freq_min_hz"] + _fdf["freq_max_hz"]) / 2.0).round(1)
            _fdf["bandwidth_hz"] = (_fdf["freq_max_hz"] - _fdf["freq_min_hz"]).round(1)
            color_col = "label_code" if "label_code" in _fdf.columns else None
            fig_tf = px.scatter(
                _fdf,
                x="duration_secs",
                y="center_freq_hz",
                size="bandwidth_hz",
                color=color_col,
                hover_data=[c for c in ("annotation_id", "call_type_code", "freq_min_hz", "freq_max_hz", "start_time_utc") if c in _fdf.columns],
                color_discrete_map={"YES": "#34d399", "MAYBE": "#f59e0b", "NO": "#fb7185", "UNVERIFIED": "#38bdf8"},
                title="Call Duration vs. Center Frequency & Bandwidth",
                labels={"duration_secs": "Call Duration (s)", "center_freq_hz": "Center Frequency (Hz)"},
                template=plot_template,
            )
            fig_tf.update_layout(**common_layout, height=330)
            figs.append(fig_tf)

    # 3. Call Type / Label Breakdown
    if "call_type_code" in subset_df.columns and not subset_df.empty:
        _grp_cols = ["call_type_code"] + (["label_code"] if "label_code" in subset_df.columns else [])
        _cdf = subset_df.groupby(_grp_cols, dropna=False).size().reset_index(name="count")
        fig_bar = px.bar(
            _cdf,
            x="call_type_code",
            y="count",
            color="label_code" if "label_code" in _cdf.columns else None,
            color_discrete_map={"YES": "#34d399", "MAYBE": "#f59e0b", "NO": "#fb7185", "UNVERIFIED": "#38bdf8"},
            title="Annotations by Call Type & Verification Label",
            labels={"call_type_code": "Call Type Code", "count": "Annotations"},
            template=plot_template,
        )
        fig_bar.update_layout(**common_layout, height=330)
        figs.append(fig_bar)

    # 4. Topography / Bathymetry Overlay Map with Solar Yellow (#FACC15) Hydrophone Markers
    fig_bathy = build_bathymetry_deployment_figure(subset_df)
    if fig_bathy is not None:
        figs.append(fig_bathy)

    if len(figs) >= 2:
        row1 = mo.hstack([mo.ui.plotly(figs[0]), mo.ui.plotly(figs[1])], widths="equal")
        row2 = mo.hstack([mo.ui.plotly(f) for f in figs[2:]], widths="equal") if len(figs) > 2 else mo.md("")
        viz_out = mo.vstack([mo.md("## Exploratory Bioacoustic & Bathymetric Visualizations"), row1, row2])
    elif len(figs) == 1:
        viz_out = mo.vstack([mo.md("## Exploratory Bioacoustic & Bathymetric Visualizations"), mo.ui.plotly(figs[0])])
    else:
        viz_out = mo.md("_No plottable columns in active dataset._")

    viz_out
    return


@app.cell
def _(full_df, infer_dataset_timezone, mo):
    pampal_box_bin = mo.ui.dropdown(
        options={
            "Hours per Day (hour/day)": "hour/day",
            "Hours per Week (hour/week)": "hour/week",
            "Days per Week (day/week)": "day/week",
            "Days per Month (day/month)": "day/month",
        },
        value="Hours per Day (hour/day)",
        label="Boxplot Bin",
    )
    pampal_scene_bin = mo.ui.dropdown(
        options={
            "Auto-Scale by Span": "auto",
            "15-Minute Bins (15min)": "15min",
            "1-Hour Bins (1hour)": "1hour",
            "1-Day Bins (1day)": "1day",
        },
        value="Auto-Scale by Span",
        label="Acoustic Scene Bin",
    )
    pampal_polar_bin = mo.ui.dropdown(
        options={
            "Detections by Hour of Day (detection/hour)": "detection/hour",
            "Hours by Hour of Day (hour/hour)": "hour/hour",
            "Days by Month (day/month)": "day/month",
        },
        value="Detections by Hour of Day (detection/hour)",
        label="Polar Detections Cycle",
    )

    _inferred_tz = infer_dataset_timezone(full_df)
    _auto_lbl = f"Dataset Default ({_inferred_tz['tz_short']})"
    _tz_opts = {_auto_lbl: "auto"}
    if int(_inferred_tz.get("offset_hours", 0)) != 0:
        _tz_opts["UTC · Database Native (UTC+00:00)"] = "utc"
    for _tz_disp, _tz_code in [
        ("NW/SE Atlantic · EST (UTC-05:00)", "utc-5"),
        ("Gulf of Mexico · CST (UTC-06:00)", "utc-6"),
        ("California Current · PST (UTC-08:00)", "utc-8"),
        ("Alaska · AKST (UTC-09:00)", "utc-9"),
        ("Hawaiian Islands · HST (UTC-10:00)", "utc-10"),
    ]:
        if _tz_code not in _tz_opts.values():
            _tz_opts[_tz_disp] = _tz_code

    pampal_polar_tz = mo.ui.dropdown(
        options=_tz_opts,
        value=_auto_lbl,
        label="Polar Plot Time Zone",
    )

    mo.vstack(
        [
            mo.md("## R `PAMpal` / `PAMscapes` Acoustic Analysis Plots"),
            mo.md(
                "Authentic NOAA SWFSC FOSSA suite plots (`plotDetectionBoxplot`, `plotAcousticScene`, and `plotPolarDetections`) "
                "rendered directly in R on your active subset, with automatic hydrophone site standard time zone detection for diel polar plots:"
            ),
            mo.hstack(
                [pampal_box_bin, pampal_scene_bin, pampal_polar_bin, pampal_polar_tz],
                justify="start",
                wrap=True,
                gap=1.5,
            ),
        ]
    )
    return pampal_box_bin, pampal_polar_bin, pampal_polar_tz, pampal_scene_bin


@app.cell
def _(
    SHADOW_STYLE,
    mo,
    pampal_box_bin,
    pampal_polar_bin,
    pampal_polar_tz,
    pampal_scene_bin,
    render_pampal_pamscapes_suite,
    subset_df,
):
    pampal_res = render_pampal_pamscapes_suite(
        subset_df,
        box_bin=pampal_box_bin.value,
        scene_bin=pampal_scene_bin.value,
        polar_bin=pampal_polar_bin.value,
        polar_tz_mode=pampal_polar_tz.value,
    )
    if not pampal_res.get("ok"):
        pampal_view = mo.callout(
            mo.md(f"**PAMpal / PAMscapes R Plot Note:** {pampal_res.get('error', 'Unavailable')}"),
            kind="warn",
        )
    else:
        pampal_view = mo.Html(
            SHADOW_STYLE
            + f"""
            <div style="font-family:monospace; font-size:11.5px; color:#34d399; margin-bottom:6px;">
              ✓ Rendered via {pampal_res['rscript']} · PAMscapes / PAMpal · Polar Time Zone: <span style="color:#22d3ee;">{pampal_res.get('polar_tz_label', 'UTC+00:00')}</span>
            </div>
            <div class="ann-pampal-grid">
              <div class="ann-pampal-card">
                <img src="data:image/png;base64,{pampal_res['boxplot_b64']}" alt="plotDetectionBoxplot" />
              </div>
              <div class="ann-pampal-card">
                <img src="data:image/png;base64,{pampal_res['scene_b64']}" alt="plotAcousticScene" />
              </div>
              <div class="ann-pampal-card">
                <img src="data:image/png;base64,{pampal_res['polar_b64']}" alt="plotPolarDetections" />
              </div>
            </div>
            """
        )
    pampal_view
    return


@app.cell
def _(mo, subset_df):
    review_table = mo.ui.table(
        subset_df,
        selection="multi",
        page_size=12,
        label="Interactive Annotation Review Table (Select rows to inspect or export)",
    )
    save_export_btn = mo.ui.run_button(label="Save Reviewed Subset to Annomate Export Studio")

    mo.vstack(
        [
            mo.hstack(
                [
                    mo.md("## Interactive Call Table & Export Staging"),
                    save_export_btn,
                ],
                justify="space-between",
                align="center",
            ),
            review_table,
        ]
    )
    return review_table, save_export_btn


@app.cell
def _(REVIEW_SESSION_DIR, json, mo, review_table, save_export_btn, subset_df):
    export_status = mo.md("")
    if save_export_btn.value:
        to_save = review_table.value if (review_table.value is not None and len(review_table.value) > 0) else subset_df
        out_path = REVIEW_SESSION_DIR / "reviewed_subset.csv"
        to_save.to_csv(out_path, index=False)
        (REVIEW_SESSION_DIR / "reviewed_meta.json").write_text(
            json.dumps({"row_count": len(to_save), "saved_from": "marimo_review_studio"}),
            encoding="utf-8",
        )
        export_status = mo.callout(
            mo.md(
                f"**Saved {len(to_save):,} reviewed rows** to `{out_path.name}`. "
                "Switch to **Annomate → Export Data** and choose *Reviewed Subset from Marimo* to enrich & download!"
            ),
            kind="success",
        )
    export_status
    return


@app.cell
def _(mo, review_table, subset_df):
    SYNTHETIC_OPTION_LABEL = "★ SYNTHETIC REFERENCE CALL — Calibrated FM Upcall Demo (No Annotation ID · Unvalidated)"
    call_options = {SYNTHETIC_OPTION_LABEL: "__synthetic__"}

    if not subset_df.empty:
        for _pos, (_, _r) in enumerate(subset_df.head(500).iterrows()):
            _aid = _r.get("annotation_id", _pos + 1)
            _ct = _r.get("call_type_code", "CALL")
            _lbl = _r.get("label_code", "UNSPECIFIED")
            _st = str(_r.get("start_time_utc", ""))[:22]
            _key = f"#{_aid} · {_ct} [{_lbl}] @ {_st}"
            # Disambiguate duplicate keys if needed
            if _key in call_options:
                _key = f"{_key} (row {_pos + 1})"
            call_options[_key] = str(_pos)

    # Default to first real annotation row (or table-selected row), keeping Synthetic Reference Call always accessible at top
    option_keys = list(call_options.keys())
    default_key = option_keys[1] if len(option_keys) > 1 else SYNTHETIC_OPTION_LABEL

    if review_table.value is not None and len(review_table.value) > 0 and not subset_df.empty:
        _sel_first = review_table.value.iloc[0]
        _sel_aid = _sel_first.get("annotation_id")
        _sel_st = str(_sel_first.get("start_time_utc", ""))
        for _k, _val in call_options.items():
            if _val == "__synthetic__":
                continue
            _row_cand = subset_df.iloc[int(_val)]
            if (_sel_aid is not None and _row_cand.get("annotation_id") == _sel_aid) and (
                str(_row_cand.get("start_time_utc", "")) == _sel_st
            ):
                default_key = _k
                break

    call_picker = mo.ui.dropdown(options=call_options, value=default_key, label="Focal Call to Inspect")
    nfft_select = mo.ui.dropdown(
        options={"128 pts": 128, "256 pts (Balanced)": 256, "512 pts (High Freq Res)": 512, "1024 pts": 1024, "2048 pts": 2048},
        value="256 pts (Balanced)",
        label="FFT Window (NFFT)",
    )
    overlap_slider = mo.ui.slider(start=50, stop=95, step=5, value=85, show_value=True, label="Overlap (%)")
    win_select = mo.ui.dropdown(
        options={"Hann": "hann", "Hamming": "hamming", "Blackman": "blackman", "Kaiser (β=8)": "kaiser"},
        value="Hann",
        label="Window Function",
    )
    pad_slider = mo.ui.slider(start=0.5, stop=10.0, step=0.5, value=2.5, show_value=True, label="Context Padding (±s)")
    fmax_slider = mo.ui.slider(start=150, stop=2000, step=50, value=500, show_value=True, label="Max Freq Display (Hz)")
    dbrange_slider = mo.ui.slider(start=30, stop=85, step=5, value=55, show_value=True, label="Dynamic Range (dB)")
    cmap_select = mo.ui.dropdown(
        options=["Magma", "Viridis", "Cividis", "Inferno", "YlGnBu", "Greys"],
        value="Magma",
        label="Colormap",
    )

    mo.vstack(
        [
            mo.md("## Embedded Call Spectrogram & Cloud Audio Inspector"),
            mo.hstack([call_picker, nfft_select, overlap_slider, win_select], justify="start", wrap=True, gap=1.5),
            mo.hstack([pad_slider, fmax_slider, dbrange_slider, cmap_select], justify="start", wrap=True, gap=1.5),
        ]
    )
    return (
        call_picker,
        cmap_select,
        dbrange_slider,
        fmax_slider,
        nfft_select,
        overlap_slider,
        pad_slider,
        win_select,
    )


@app.cell
def _(
    SHADOW_STYLE,
    call_picker,
    cmap_select,
    compute_spectrogram_payload,
    dbrange_slider,
    fetch_annotation_audio_context,
    fmax_slider,
    go,
    make_subplots,
    mo,
    nfft_select,
    overlap_slider,
    pad_slider,
    source_mode,
    subset_df,
    win_select,
):
    picker_val = call_picker.value
    is_explicit_synthetic = (picker_val == "__synthetic__") or subset_df.empty

    if is_explicit_synthetic:
        meta_ctx = {
            "annotation_id": None,
            "call_type_code": "SYNTHETIC_FM_UPCALL",
            "label_code": None,
            "start_time_utc": None,
            "end_time_utc": None,
            "freq_min_hz": 65.0,
            "freq_max_hz": 215.0,
            "sample_rate_hz": 2000.0,
            "obj_gsuri": "",
        }
        subplot_header = "SYNTHETIC REFERENCE CALL · Calibrated FM Upcall Preview (No Annotation ID · Unvalidated)"
    else:
        row_pos = min(max(0, int(picker_val)), len(subset_df) - 1)
        sel_row = subset_df.iloc[row_pos].to_dict()
        ann_id = sel_row.get("annotation_id")

        # Only enrich missing physical audio segment geometry from DB (never overwrite sel_row's label_code / call_type_code!)
        audio_geom_keys = (
            "obj_gsuri",
            "format",
            "container_channels",
            "file_channel",
            "subfile_index",
            "seg_start_utc",
            "seg_end_utc",
            "sample_rate_hz",
            "bit_depth",
            "seg_duration_secs",
            "data_byte_offset",
            "data_byte_length",
            "first_seg_byte_offset",
        )
        meta_ctx = dict(sel_row)
        if source_mode != "upload" and ann_id is not None:
            try:
                db_ctx = fetch_annotation_audio_context(int(float(ann_id)))
                if db_ctx:
                    for _k in audio_geom_keys:
                        _cur = meta_ctx.get(_k)
                        if _cur is None or (isinstance(_cur, float) and (_cur != _cur)) or str(_cur).strip() == "":
                            meta_ctx[_k] = db_ctx.get(_k)
            except Exception:
                pass

        disp_call = meta_ctx.get("call_type_code") or "CALL"
        disp_lbl = meta_ctx.get("label_code") or "UNLABELED"
        disp_id = meta_ctx.get("annotation_id", row_pos + 1)
        subplot_header = f"STFT Spectrogram · Annotation #{disp_id} ({disp_call} · {disp_lbl})"

    spec = compute_spectrogram_payload(
        meta=meta_ctx,
        nfft=int(nfft_select.value),
        overlap_pct=float(overlap_slider.value),
        window_type=str(win_select.value),
        fmin_hz=0.0,
        fmax_hz=float(fmax_slider.value),
        padding_sec=float(pad_slider.value),
        db_range=float(dbrange_slider.value),
    )

    custom_magma = [
        [0.0, "#040714"],
        [0.22, "#221149"],
        [0.48, "#6f1d63"],
        [0.72, "#ca3e4b"],
        [0.90, "#f89540"],
        [1.0, "#fcfdbf"],
    ]
    resolved_cmap = custom_magma if cmap_select.value == "Magma" else cmap_select.value

    fig_sp = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        row_heights=[0.74, 0.26],
        vertical_spacing=0.07,
        subplot_titles=(
            subplot_header,
            "Normalized Hydrophone Waveform",
        ),
    )

    fig_sp.add_trace(
        go.Heatmap(
            x=spec["times_s"],
            y=spec["freqs_hz"],
            z=spec["power_db"],
            zmin=spec["z_min_db"],
            zmax=spec["z_max_db"],
            colorscale=resolved_cmap,
            colorbar={"title": "PSD (dB)", "len": 0.70, "y": 0.64},
            hovertemplate="Time: %{x:.3f}s<br>Freq: %{y:.1f} Hz<br>Power: %{z:.1f} dB<extra></extra>",
        ),
        row=1,
        col=1,
    )

    cbox = spec["call_box"]
    f0 = float(cbox["f0"]) if cbox.get("f0") is not None else min(spec["freqs_hz"])
    f1 = float(cbox["f1"]) if cbox.get("f1") is not None else max(spec["freqs_hz"])
    box_color = "#facc15" if is_explicit_synthetic else "#22d3ee"
    fig_sp.add_shape(
        type="rect",
        x0=cbox["t0"],
        x1=cbox["t1"],
        y0=f0,
        y1=min(f1, max(spec["freqs_hz"])),
        line={"color": box_color, "width": 2.4, "dash": "dash" if is_explicit_synthetic else "solid"},
        fillcolor="rgba(250, 204, 21, 0.08)" if is_explicit_synthetic else "rgba(34, 211, 238, 0.10)",
        row=1,
        col=1,
    )

    fig_sp.add_trace(
        go.Scatter(
            x=spec["waveform"]["t"],
            y=spec["waveform"]["y"],
            mode="lines",
            line={"color": box_color, "width": 1.1},
            name="Amplitude",
            hovertemplate="Time: %{x:.3f}s<br>Amp: %{y:.3f}<extra></extra>",
        ),
        row=2,
        col=1,
    )
    fig_sp.add_vline(x=cbox["t0"], line_dash="dot", line_color=box_color, row=2, col=1)
    fig_sp.add_vline(x=cbox["t1"], line_dash="dot", line_color=box_color, row=2, col=1)

    fig_sp.update_yaxes(title_text="Frequency (Hz)", row=1, col=1)
    fig_sp.update_yaxes(title_text="Norm. Amp", row=2, col=1)
    fig_sp.update_xaxes(title_text="Window Time Offset (seconds)", row=2, col=1)
    fig_sp.update_layout(
        template="plotly_dark",
        paper_bgcolor="#0b192b",
        plot_bgcolor="#07111f",
        height=500,
        showlegend=False,
        margin={"l": 58, "r": 30, "t": 44, "b": 48},
    )

    is_live_gcs = spec["source_status"].startswith("live")
    gs_uri = str(meta_ctx.get("obj_gsuri") or "")
    gcs_console_url = (
        f"https://console.cloud.google.com/storage/browser/_details/{gs_uri[5:]}"
        if gs_uri.startswith("gs://")
        else "#"
    )

    if is_explicit_synthetic:
        badge_html = '<span class="ann-badge-synth">★ SYNTHETIC REFERENCE DEMO (NO ANNOTATION ID)</span>'
        uri_line = '<div style="margin-top:6px; font-family:monospace; font-size:12px; color:#94a3b8;">Source: Mathematically synthesized concave FM upcall + 1/f ocean ambient noise (unvalidated reference signal).</div>'
        note_html = ""
        audio_control_html = f"""
          <div style="display:flex; flex-direction:column; align-items:flex-end; gap:6px;">
            <span style="font-size:11px; font-family:monospace; color:#fbbf24;">Synthetic Reference Audio</span>
            <audio controls src="data:audio/wav;base64,{spec['audio_wav_b64']}" style="height:38px; color-scheme:dark;"></audio>
          </div>
        """
    elif is_live_gcs:
        badge_html = f'<span class="ann-badge-live">{spec["source_badge"]}</span>'
        uri_line = f'<div style="margin-top:6px; font-family:monospace; font-size:12px; color:#94a3b8; overflow-wrap:anywhere;">Original Cloud Audio: <a href="{gcs_console_url}" target="_blank" style="color:#22d3ee;">{gs_uri}</a></div>'
        note_html = ""
        audio_control_html = f"""
          <audio controls src="data:audio/wav;base64,{spec['audio_wav_b64']}" style="height:38px; color-scheme:dark;"></audio>
        """
    else:
        badge_html = '<span class="ann-badge-synth">GCS DISCONNECTED · SHOWING CALIBRATED PREVIEW</span>'
        uri_disp = gs_uri or "No gs:// URI linked to this annotation"
        uri_line = f'<div style="margin-top:6px; font-family:monospace; font-size:12px; color:#94a3b8; overflow-wrap:anywhere;">Target Cloud Audio: <a href="{gcs_console_url}" target="_blank" style="color:#22d3ee;">{uri_disp}</a></div>'
        note_html = (
            '<div style="margin-top:8px; font-size:12.5px; color:#fbbf24;">'
            'Tip: Run <code class="ann-gcloud-cmd">gcloud auth login</code> in terminal to stream live private GCS audio (showing calibrated FM call preview).'
            "</div>"
        )
        reason_detail = (
            f"Cannot stream cloud audio (<code>{uri_disp}</code>) because Google Cloud (GCS) authentication is not active on this machine. "
            'Run <code class="ann-gcloud-cmd">gcloud auth login</code> in PowerShell and reload to hear the real hydrophone recording—or choose '
            "<strong>★ SYNTHETIC REFERENCE CALL</strong> at the top of the Focal Call dropdown to test synthetic audio playback."
            if gs_uri
            else "This annotation row does not have a linked Google Cloud Storage (<code>gs://</code>) audio file."
        )
        # Interactive Play button that reveals a clear diagnostic popup when clicked while disconnected from GCP
        audio_control_html = f"""
          <details style="position:relative;">
            <summary class="ann-play-btn warn" style="list-style:none;">
              ▶ Play Cloud Audio
            </summary>
            <div class="ann-audio-popup">
              <strong>⚠ Cloud Audio Playback Unavailable</strong><br/>
              {reason_detail}
            </div>
          </details>
        """

    audio_bar = mo.Html(
        SHADOW_STYLE
        + f"""
        <div class="ann-audio-panel">
          <div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:14px;">
            <div style="flex:1; min-width:280px;">
              {badge_html}
              <span style="margin-left:10px; font-family:monospace; font-size:12px; color:#cbd5e1;">
                SR: {spec["sample_rate_hz"]:.0f} Hz · NFFT: {spec["effective_nfft"]} · Byte Offset: {meta_ctx.get("data_byte_offset", "—") if not is_explicit_synthetic else "N/A"} · Ch: {meta_ctx.get("file_channel", 0) if not is_explicit_synthetic else "Synth"}
              </span>
              {uri_line}
              {note_html}
            </div>
            <div>
              {audio_control_html}
            </div>
          </div>
        </div>
        """
    )

    spec_view = mo.vstack([audio_bar, mo.ui.plotly(fig_sp)])
    spec_view
    return


@app.cell
def _(get_settings, mo, pd, subset_df):
    def bioacoustic_chat_model(messages, config):
        user_msg = str(messages[-1].content if messages else "").strip()
        lower_q = user_msg.lower()
        live_settings = get_settings()

        summary_lines = [f"Active subset rows: {len(subset_df)}"]
        if not subset_df.empty:
            if "call_type_code" in subset_df.columns:
                summary_lines.append(f"Call types: {subset_df['call_type_code'].value_counts().to_dict()}")
            if "label_code" in subset_df.columns:
                summary_lines.append(f"Labels: {subset_df['label_code'].value_counts().to_dict()}")
            if "granularity_code" in subset_df.columns:
                summary_lines.append(f"Granularities: {subset_df['granularity_code'].value_counts().to_dict()}")
            if "duration_secs" in subset_df.columns and not subset_df["duration_secs"].dropna().empty:
                d = subset_df["duration_secs"].dropna()
                summary_lines.append(
                    f"Duration (s): min={d.min():.2f}, median={d.median():.2f}, mean={d.mean():.2f}, max={d.max():.2f}"
                )
            if "freq_min_hz" in subset_df.columns and "freq_max_hz" in subset_df.columns:
                f0 = subset_df["freq_min_hz"].dropna()
                f1 = subset_df["freq_max_hz"].dropna()
                if not f0.empty and not f1.empty:
                    summary_lines.append(
                        f"Frequency bounds (Hz): median low={f0.median():.1f} Hz, median high={f1.median():.1f} Hz, overall [{f0.min():.1f}, {f1.max():.1f}] Hz"
                    )
            if "deployment_code" in subset_df.columns:
                summary_lines.append(f"Deployments: {subset_df['deployment_code'].value_counts().head(5).to_dict()}")

        context_blob = "\n".join(summary_lines)

        if live_settings.gemini_api_key:
            try:
                from google import genai

                client = genai.Client(api_key=live_settings.gemini_api_key)
                sys_prompt = (
                    "You are the Annomate Bioacoustics Data Explorer embedded in a Marimo review notebook. "
                    "Answer concisely using markdown and exact figures from the active dataset summary below:\n\n"
                    f"{context_blob}\n\nSample rows:\n{subset_df.head(5).to_markdown(index=False) if not subset_df.empty else 'Empty'}"
                )
                history_txt = "\n".join(f"{m.role.upper()}: {m.content}" for m in messages[-6:])
                resp = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=f"{sys_prompt}\n\nConversation:\n{history_txt}",
                )
                return resp.text
            except Exception:
                pass

        if subset_df.empty:
            return "No rows are currently loaded. Select a dataset source at the top of the notebook to start exploring."

        if (
            any(w in lower_q for w in ["freq", "hz", "band", "pitch"])
            and "freq_min_hz" in subset_df.columns
            and "freq_max_hz" in subset_df.columns
        ):
            bw = (subset_df["freq_max_hz"] - subset_df["freq_min_hz"]).dropna()
            return (
                f"### Frequency Profile ({len(subset_df):,} calls)\n"
                f"- **Low Frequency (`freq_min_hz`)**: median **{subset_df['freq_min_hz'].median():.1f} Hz** "
                f"(range `{subset_df['freq_min_hz'].min():.1f}` – `{subset_df['freq_min_hz'].max():.1f} Hz`)\n"
                f"- **High Frequency (`freq_max_hz`)**: median **{subset_df['freq_max_hz'].median():.1f} Hz** "
                f"(range `{subset_df['freq_max_hz'].min():.1f}` – `{subset_df['freq_max_hz'].max():.1f} Hz`)\n"
                f"- **Bandwidth**: median **{bw.median():.1f} Hz** (IQR `{bw.quantile(0.25):.1f}` – `{bw.quantile(0.75):.1f} Hz`)"
            )

        if any(w in lower_q for w in ["dur", "long", "short", "length"]) and "duration_secs" in subset_df.columns:
            d = subset_df["duration_secs"].dropna()
            return (
                f"### Call Duration Summary ({len(d):,} calls)\n"
                f"- **Median duration**: **{d.median():.2f} s** (mean `{d.mean():.2f} ± {d.std():.2f} s`)\n"
                f"- **Range**: `{d.min():.2f} s` to `{d.max():.2f} s` (90th percentile: `{d.quantile(0.9):.2f} s`)"
            )

        if any(w in lower_q for w in ["hour", "diel", "time", "when", "day", "night"]) and "start_time_utc" in subset_df.columns:
            ts = pd.to_datetime(subset_df["start_time_utc"], utc=True, errors="coerce").dropna()
            top_hrs = ts.dt.hour.value_counts().head(3)
            hr_str = ", ".join(f"**{h:02d}:00 UTC** ({c} calls)" for h, c in top_hrs.items())
            return (
                f"### Temporal & Diel Activity\n"
                f"- **Window**: `{ts.min().isoformat()}` → `{ts.max().isoformat()}`\n"
                f"- **Peak UTC hours**: {hr_str}"
            )

        if any(w in lower_q for w in ["audio", "gcs", "xwav", "x.flac", "aif", "file"]):
            n_linked = int(subset_df["obj_gsuri"].notna().sum()) if "obj_gsuri" in subset_df.columns else 0
            fmts = subset_df["format"].value_counts().to_dict() if "format" in subset_df.columns else {}
            return (
                f"### Linked Cloud Audio Coverage\n"
                f"- **{n_linked:,} / {len(subset_df):,}** calls in this subset resolve to physical `gs://` segments via `tstzrange &&`.\n"
                f"- **Container formats**: `{fmts}`\n"
                f"- Remember: `core.annotations` links only to `recording_channel_id` so calls spanning file boundaries or inside multi-segment `.x.wav`/`.x.flac` containers resolve cleanly."
            )

        return (
            "### Active Review Subset Summary\n"
            + "\n".join(f"- {line}" for line in summary_lines)
            + "\n\n*Try asking about **frequency ranges**, **call durations**, **diel peak hours**, or **GCS audio coverage**—or add a `GEMINI_API_KEY` in Annomate Settings for open-ended AI analysis.*"
        )

    chatbot = mo.ui.chat(
        bioacoustic_chat_model,
        prompts=[
            "Summarize the frequency bounds and bandwidth of these calls",
            "What are the peak UTC hours and date span of detections?",
            "Summarize call durations across the active subset",
            "How many annotations link to GCS audio files and what formats are they?",
        ],
        show_configuration_controls=False,
    )

    mo.vstack(
        [
            mo.md("## Embedded Bioacoustics Data Explorer Chatbot"),
            mo.md("Ask quantitative questions about your active subset, diel trends, frequency bounds, or cloud audio links:"),
            chatbot,
        ]
    )
    return


if __name__ == "__main__":
    app.run()
