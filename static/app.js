/* ==========================================================================
   annomate · Interactive Frontend Controller
   ========================================================================== */

const state = {
  catalog: null,
  status: null,
  lastQueryRows: [],
  activeSpecRow: null,
  recordedAudioBlob: null,
  isRecording: false,
  mediaRecorder: null,
  speechRec: null,
  alignSession: null,
};

const TARGET_ALIGN_FIELDS = [
  { key: "source_file", label: "Source Audio Filename", desc: "Matches core.acoustic_files or file timestamp" },
  { key: "channel", label: "Channel Number", desc: "Hydrophone channel in file" },
  { key: "recording_channel_id", label: "recording_channel_id", desc: "Direct DB channel ID (if present in file)" },
  { key: "start_time_utc", label: "Absolute Start UTC", desc: "ISO-8601 or UTC datetime column" },
  { key: "end_time_utc", label: "Absolute End UTC", desc: "ISO-8601 or UTC end datetime" },
  { key: "begin_offset_sec", label: "Relative Begin Time (s)", desc: "Raven/file offset from segment start" },
  { key: "end_offset_sec", label: "Relative End Time (s)", desc: "Raven/file end offset in seconds" },
  { key: "duration_ms", label: "Duration (ms)", desc: "PAMGuard call duration in milliseconds" },
  { key: "freq_min_hz", label: "Low Frequency (Hz)", desc: "Lower bound of core.freqrange" },
  { key: "freq_max_hz", label: "High Frequency (Hz)", desc: "Upper bound of core.freqrange" },
  { key: "call_type_code", label: "Call Type / Species", desc: "Mapped to makara.call_types" },
  { key: "label_code", label: "Verification Label", desc: "Mapped to YES / NO / MAYBE / UNVERIFIED" },
  { key: "probability", label: "Detector Probability", desc: "Optional detector score" },
  { key: "confidence", label: "Analyst Confidence", desc: "Optional confidence rating" },
  { key: "analyst", label: "Analyst Code", desc: "FIRSTINITIAL+LAST (e.g. SRANKIN)" },
];

const BIOACOUSTIC_COLORSCALES = {
  Magma: [
    [0.0, "#040714"],
    [0.22, "#221149"],
    [0.48, "#6f1d63"],
    [0.72, "#ca3e4b"],
    [0.90, "#f89540"],
    [1.0, "#fcfdbf"],
  ],
  YlGnBu: [
    [0.0, "#040b18"],
    [0.25, "#0a2e4d"],
    [0.52, "#0d6e82"],
    [0.78, "#22d3ee"],
    [1.0, "#ecfeff"],
  ],
  Inferno: [
    [0.0, "#030510"],
    [0.28, "#380962"],
    [0.58, "#932667"],
    [0.82, "#f1605d"],
    [1.0, "#fcffa4"],
  ],
  Viridis: "Viridis",
  Cividis: "Cividis",
};

function toast(msg) {
  const wrap = document.getElementById("toastContainer");
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = msg;
  wrap.appendChild(el);
  setTimeout(() => el.remove(), 4200);
}

function escapeHtml(val) {
  if (val === null || val === undefined) return "";
  return String(val)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/* --------------------------------------------------------------------------
   1. Ambient Acoustic Wave Canvas
   -------------------------------------------------------------------------- */
function initAmbientWaveCanvas() {
  const canvas = document.getElementById("acousticWaveCanvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  let w = 0;
  let h = 0;
  let t = 0;

  function resize() {
    w = canvas.width = window.innerWidth;
    h = canvas.height = 300;
  }
  window.addEventListener("resize", resize);
  resize();

  function frame() {
    ctx.clearRect(0, 0, w, h);
    const harmonics = [
      { amp: 18, freq: 0.0045, speed: 0.014, color: "rgba(34, 211, 238, 0.22)", y: 110 },
      { amp: 13, freq: 0.0072, speed: -0.019, color: "rgba(52, 211, 153, 0.16)", y: 138 },
      { amp: 9, freq: 0.011, speed: 0.025, color: "rgba(56, 189, 248, 0.12)", y: 162 },
    ];
    for (const wave of harmonics) {
      ctx.beginPath();
      for (let x = 0; x <= w; x += 6) {
        const y =
          wave.y +
          Math.sin(x * wave.freq + t * wave.speed) * wave.amp +
          Math.cos(x * wave.freq * 0.45 - t * wave.speed * 0.7) * (wave.amp * 0.45);
        if (x === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.strokeStyle = wave.color;
      ctx.lineWidth = 1.4;
      ctx.stroke();
    }
    t += 1;
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}

/* --------------------------------------------------------------------------
   2. Navigation, Theme & Guide Drawer
   -------------------------------------------------------------------------- */
function switchTab(tabId) {
  document.querySelectorAll(".module-tab").forEach((btn) => {
    const active = btn.dataset.tab === tabId;
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-selected", String(active));
  });
  document.querySelectorAll(".tab-panel").forEach((panel) => {
    panel.hidden = panel.id !== `panel-${tabId}`;
  });
  if (tabId === "export") {
    refreshExportPreview();
  }
}

function initNavigationAndTheme() {
  document.querySelectorAll(".module-tab").forEach((btn) => {
    btn.addEventListener("click", () => switchTab(btn.dataset.tab));
  });

  document.getElementById("themeToggleBtn").addEventListener("click", () => {
    const html = document.documentElement;
    const next = html.getAttribute("data-theme") === "dark" ? "light" : "dark";
    html.setAttribute("data-theme", next);
  });

  const toggleExpBtn = document.getElementById("toggleExplainerBtn");
  const expBody = document.getElementById("explainerBody");
  toggleExpBtn.addEventListener("click", () => {
    expBody.hidden = !expBody.hidden;
    toggleExpBtn.textContent = expBody.hidden ? "Show Overview" : "Hide Overview";
  });

  const guideBtn = document.getElementById("openGuideDrawerBtn");
  if (guideBtn) {
    guideBtn.addEventListener("click", () => {
      switchTab("find");
      expBody.hidden = false;
      toggleExpBtn.textContent = "Hide Overview";
      document.getElementById("inlineExplainerCard").scrollIntoView({ behavior: "smooth" });
    });
  }

  // Settings Modal
  const modal = document.getElementById("settingsModal");
  const openModal = () => { modal.hidden = false; };
  const closeModal = () => { modal.hidden = true; };
  document.getElementById("openSettingsBtn").addEventListener("click", openModal);
  document.getElementById("gcsStatusPill").addEventListener("click", openModal);
  document.getElementById("closeSettingsBtn").addEventListener("click", closeModal);
  document.getElementById("cancelSettingsBtn").addEventListener("click", closeModal);

  // One-click Offline Demo Mode toggle
  const demoBtn = document.getElementById("demoModeToggleBtn");
  if (demoBtn) {
    demoBtn.addEventListener("click", async () => {
      const nextState = !(state.status?.demo_mode);
      await fetch("/api/demo-mode", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: nextState }),
      });
      toast(
        nextState
          ? "Switched to Offline Demo Mode (no VPN or GCP required — synthetic audio active)."
          : "Switched to Live Cloud / VPN Mode."
      );
      await Promise.all([loadSystemStatus(), loadCatalog()]);
      await generateAndRunQuery(true);
    });
  }

  document.getElementById("saveSettingsBtn").addEventListener("click", async () => {
    const geminiKey = document.getElementById("settingsGeminiKey").value;
    const gcpProj = document.getElementById("settingsGcpProject").value;
    const payload = { gcp_project: gcpProj };
    if (geminiKey.trim() !== "") payload.gemini_api_key = geminiKey.trim();

    await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    closeModal();
    toast("Settings updated & cloud connections refreshed.");
    await loadSystemStatus();
  });
}

/* --------------------------------------------------------------------------
   3. Status & Reference Catalog Loading
   -------------------------------------------------------------------------- */
async function loadSystemStatus() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    state.status = data;

    const demoBtn = document.getElementById("demoModeToggleBtn");
    const demoDot = document.getElementById("demoStatusDot");
    const demoTxt = document.getElementById("demoStatusText");
    if (demoBtn && demoDot && demoTxt) {
      if (data.demo_mode) {
        demoBtn.classList.add("active");
        demoDot.className = "status-dot demo";
        demoTxt.textContent = "Demo Mode: ON";
      } else {
        demoBtn.classList.remove("active");
        demoDot.className = "status-dot";
        demoTxt.textContent = "Demo Mode: OFF";
      }
    }

    const dbDot = document.getElementById("dbStatusDot");
    const dbTxt = document.getElementById("dbStatusText");
    if (data.demo_mode) {
      dbDot.className = "status-dot demo";
      const annCnt = (data.db.counts.annotations_count || 180).toLocaleString();
      dbTxt.textContent = `Demo Catalog · ${annCnt} calls · 3 sites`;
    } else if (data.db.connected) {
      dbDot.className = "status-dot ok";
      const annCnt = (data.db.counts.annotations_count || 0).toLocaleString();
      const fileCnt = Math.round((data.db.counts.acoustic_files_count || 0) / 1000).toLocaleString();
      dbTxt.textContent = `VPN Live · ${annCnt} calls · ${fileCnt}k files`;
    } else {
      dbDot.className = "status-dot warn";
      dbTxt.textContent = "DB Offline (Click Demo Mode)";
    }

    const gcsDot = document.getElementById("gcsStatusDot");
    const gcsTxt = document.getElementById("gcsStatusText");
    if (data.demo_mode) {
      gcsDot.className = "status-dot demo";
      gcsTxt.textContent = "Synthetic Audio Ready";
    } else if (data.gcs_authenticated) {
      gcsDot.className = "status-dot ok";
      gcsTxt.textContent = "GCS Audio Ready";
    } else {
      gcsDot.className = "status-dot warn";
      gcsTxt.textContent = "GCS Auth Needed";
    }

    const engBadge = document.getElementById("nlEngineBadge");
    engBadge.textContent = data.gemini_configured
      ? "Gemini 2.5 Multimodal Active"
      : "Schema-Aware Parser + Browser Voice";

    if (data.sessions?.last_query?.row_count !== undefined) {
      document.getElementById("exportLastQueryMeta").textContent =
        `${data.sessions.last_query.row_count.toLocaleString()} rows (${data.sessions.last_query.prompt || "Recent query"})`;
    }
    if (data.sessions?.marimo_reviewed?.row_count !== undefined) {
      document.getElementById("exportMarimoMeta").textContent =
        `${data.sessions.marimo_reviewed.row_count.toLocaleString()} rows saved from Marimo`;
    }
    if (data.marimo?.url) {
      document.getElementById("openMarimoNewTabLink").href = data.marimo.url;
    }
  } catch (err) {
    console.error("Status check failed:", err);
  }
}

async function loadCatalog() {
  try {
    const res = await fetch("/api/catalog");
    const cat = await res.json();
    state.catalog = cat;

    // Populate Find & Filter dropdowns
    const orgSel = document.getElementById("filterOrg");
    const alignOrgSel = document.getElementById("alignOrgSelect");
    alignOrgSel.innerHTML = "";
    (cat.organizations || []).forEach((o) => {
      orgSel.insertAdjacentHTML("beforeend", `<option value="${escapeHtml(o.code)}">${escapeHtml(o.code)} · ${escapeHtml(o.name)}</option>`);
      alignOrgSel.insertAdjacentHTML("beforeend", `<option value="${escapeHtml(o.code)}">${escapeHtml(o.code)} · ${escapeHtml(o.name)}</option>`);
    });

    const ctSel = document.getElementById("filterCallType");
    const alignCtSel = document.getElementById("alignDefaultCallType");
    alignCtSel.innerHTML = "";
    (cat.call_types || []).forEach((c) => {
      const selAttr = c.code === "RW_UPCALL" ? "selected" : "";
      ctSel.insertAdjacentHTML("beforeend", `<option value="${escapeHtml(c.code)}">${escapeHtml(c.code)} — ${escapeHtml(c.name || "")}</option>`);
      alignCtSel.insertAdjacentHTML("beforeend", `<option value="${escapeHtml(c.code)}" ${selAttr}>${escapeHtml(c.code)} — ${escapeHtml(c.name || "")}</option>`);
    });

    const effSel = document.getElementById("filterEffort");
    const expEffSel = document.getElementById("exportEffortSelect");
    effSel.innerHTML = `<option value="">All Efforts / Unfiltered</option>`;
    expEffSel.innerHTML = "";
    (cat.efforts || []).forEach((e) => {
      const sel = e.name === "DCLDE_2013" ? "selected" : "";
      effSel.insertAdjacentHTML("beforeend", `<option value="${escapeHtml(e.name)}" ${sel}>${escapeHtml(e.name)} (${escapeHtml(e.organization_code)})</option>`);
      expEffSel.insertAdjacentHTML("beforeend", `<option value="${escapeHtml(e.name)}" ${sel}>${escapeHtml(e.name)}</option>`);
    });

    // Align dropdowns: Granularities, Sharing Scopes, Recording Channels, Procedures, Analyses
    const granSel = document.getElementById("alignDefaultGranularity");
    granSel.innerHTML = "";
    (cat.granularities || []).forEach((g) => {
      const sel = g.code === "EVENT_CALL" ? "selected" : "";
      granSel.insertAdjacentHTML("beforeend", `<option value="${escapeHtml(g.code)}" ${sel}>${escapeHtml(g.code)} · ${escapeHtml(g.name)}</option>`);
    });
    renderGranularityFilterMenu(cat.granularities || []);

    const shareSel = document.getElementById("alignDefaultSharing");
    shareSel.innerHTML = "";
    (cat.sharing_scopes || []).forEach((s) => {
      const sel = s.code === "ORG_INTERNAL" ? "selected" : "";
      shareSel.insertAdjacentHTML("beforeend", `<option value="${escapeHtml(s.code)}" ${sel}>${escapeHtml(s.code)} · ${escapeHtml(s.name)}</option>`);
    });

    const rcSel = document.getElementById("alignRecordingChannelSelect");
    rcSel.innerHTML = `<option value="">Auto-resolve from filename (or pick channel)</option>`;
    (cat.recording_channels || []).forEach((rc, i) => {
      const sel = i === 0 ? "selected" : "";
      const label = `#${rc.recording_channel_id} · ${rc.deployment_code || rc.recording_code || "Rec"} (Ch ${rc.channel})`;
      rcSel.insertAdjacentHTML("beforeend", `<option value="${rc.recording_channel_id}" ${sel}>${escapeHtml(label)}</option>`);
    });

    const procSel = document.getElementById("alignProcedureSelect");
    procSel.innerHTML = "";
    (cat.procedures || []).forEach((p) => {
      procSel.insertAdjacentHTML(
        "beforeend",
        `<option value="${p.id}">#${p.id} · ${escapeHtml(p.name)} (${escapeHtml(p.analysis_name)})</option>`
      );
    });

    const anSel = document.getElementById("newProcAnalysisSelect");
    anSel.innerHTML = "";
    (cat.analyses || []).forEach((a) => {
      anSel.insertAdjacentHTML(
        "beforeend",
        `<option value="${a.id}">#${a.id} · [${escapeHtml(a.organization_code)}] ${escapeHtml(a.name)}</option>`
      );
    });
  } catch (err) {
    console.error("Failed loading reference catalog:", err);
  }
}

/* --------------------------------------------------------------------------
   4. Module 01: Find & Filter (Voice/Audio + Text -> SQL + CSV + Review)
   -------------------------------------------------------------------------- */
const GRANULARITY_EXPLANATIONS = {
  "": "Include annotations across every analysis granularity in nmfs_annotation_db.",
  EVENT_CALL: "Single Call Detection — Each row bounds one discrete individual vocalization in time (tstzrange) and frequency (freqrange).",
  EVENT_ENCOUNTER: "Individual or Group Encounter — Each row spans an acoustic bout or encounter window containing multiple calls.",
  INTERVAL: "Binned Time Intervals — Presence/absence evaluated across standardized fixed-duration windows (e.g., 1-min, 15-min, or hourly bins).",
  CALL: "Individual Call — Discrete vocalization event.",
  BINNED: "Presence Time Bin — Fixed-interval presence/absence evaluation.",
  ENCOUNTER: "Acoustic Encounter — Multi-call encounter window.",
};

function renderGranularityFilterMenu(granularities) {
  const menu = document.getElementById("granularityMenu");
  const trigger = document.getElementById("granularityTriggerBtn");
  const selectedTxt = document.getElementById("granularitySelectedText");
  const hiddenInput = document.getElementById("filterGranularity");
  const tooltip = document.getElementById("granularityHoverTooltip");
  if (!menu || !trigger) return;

  const items = [
    { code: "", label: "All Granularities", desc: GRANULARITY_EXPLANATIONS[""] },
    ...granularities.map((g) => ({
      code: g.code,
      label: `${g.code} · ${g.name || ""}`,
      desc: g.description || GRANULARITY_EXPLANATIONS[g.code] || `${g.name}: Standardized Makara analysis granularity.`,
    })),
  ];

  menu.innerHTML = items
    .map(
      (it, idx) => `
      <div class="custom-select-option ${idx === 0 ? "selected" : ""}" role="option"
           data-val="${escapeHtml(it.code)}" data-label="${escapeHtml(it.label)}" data-desc="${escapeHtml(it.desc)}">
        <span class="custom-select-option-code">${escapeHtml(it.label)}</span>
        <span class="custom-select-option-sub">${escapeHtml(it.desc.slice(0, 68))}${it.desc.length > 68 ? "…" : ""}</span>
      </div>`
    )
    .join("");

  menu.querySelectorAll(".custom-select-option").forEach((opt) => {
    opt.addEventListener("mouseenter", () => {
      tooltip.innerHTML = `<strong>${escapeHtml(opt.dataset.label)}</strong><br/>${escapeHtml(opt.dataset.desc)}`;
      tooltip.hidden = false;
    });
    opt.addEventListener("mouseleave", () => {
      tooltip.hidden = true;
    });
    opt.addEventListener("click", () => {
      hiddenInput.value = opt.dataset.val;
      selectedTxt.textContent = opt.dataset.label;
      menu.querySelectorAll(".custom-select-option").forEach((o) => o.classList.remove("selected"));
      opt.classList.add("selected");
      menu.hidden = true;
      tooltip.hidden = true;
      trigger.setAttribute("aria-expanded", "false");
      updateSubpanelSummaries();
      generateAndRunQuery(false);
    });
  });

  if (!trigger.dataset.bound) {
    trigger.dataset.bound = "1";
    trigger.addEventListener("click", (ev) => {
      ev.stopPropagation();
      const willOpen = menu.hidden;
      menu.hidden = !willOpen;
      if (!willOpen) tooltip.hidden = true;
      trigger.setAttribute("aria-expanded", String(willOpen));
    });
    document.addEventListener("click", (ev) => {
      if (!document.getElementById("granularityFieldWrap")?.contains(ev.target)) {
        menu.hidden = true;
        tooltip.hidden = true;
        trigger.setAttribute("aria-expanded", "false");
      }
    });
  }
}

function updateSubpanelSummaries() {
  const layers = getSelectedLayers();
  const scopeBadge = document.getElementById("scopeSummaryBadge");
  if (scopeBadge) {
    scopeBadge.textContent =
      layers.length === 1
        ? "Annotations Only · Click for options"
        : `${layers.length} relational layers active · Click for options`;
  }

  const f = getStructuredFilters();
  const parts = [];
  if (f.effort_name) parts.push(`Effort: ${f.effort_name}`);
  if (f.organization_code) parts.push(`Org: ${f.organization_code}`);
  if (f.call_type_code) parts.push(`Call: ${f.call_type_code}`);
  if (f.granularity_code) parts.push(`Granularity: ${f.granularity_code}`);
  if (f.label_codes?.length) parts.push(`Label: ${f.label_codes.join(",")}`);
  if (f.freq_min_hz || f.freq_max_hz) parts.push(`Hz: ${f.freq_min_hz || 0}–${f.freq_max_hz || "max"}`);
  const filterBadge = document.getElementById("filtersSummaryBadge");
  if (filterBadge) {
    filterBadge.textContent =
      (parts.length ? parts.join(" · ") : "No active filters") + " · Click for options";
  }
}

function getSelectedLayers() {
  const checked = [];
  document.querySelectorAll("#layerSelectorGroup input[type='checkbox']").forEach((cb) => {
    if (cb.checked) checked.push(cb.value);
  });
  return checked.length ? checked : ["annotations"];
}

function getStructuredFilters() {
  const lbl = document.getElementById("filterLabel").value;
  return {
    effort_name: document.getElementById("filterEffort").value,
    organization_code: document.getElementById("filterOrg").value,
    call_type_code: document.getElementById("filterCallType").value,
    granularity_code: document.getElementById("filterGranularity")?.value || "",
    label_codes: lbl ? [lbl] : [],
    freq_min_hz: document.getElementById("filterFreqMin").value,
    freq_max_hz: document.getElementById("filterFreqMax").value,
    limit: parseInt(document.getElementById("filterLimit").value || "500", 10),
    random_sample: document.getElementById("filterRandomSample").checked,
  };
}

async function generateAndRunQuery(autoExecute = true) {
  const btn = document.getElementById("generateSqlBtn");
  const origLabel = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Generating SQL…";

  try {
    const formData = new FormData();
    formData.append("prompt_text", document.getElementById("nlPromptInput").value);
    formData.append("layers_json", JSON.stringify(getSelectedLayers()));
    formData.append("filters_json", JSON.stringify(getStructuredFilters()));
    if (state.recordedAudioBlob) {
      formData.append("audio_file", state.recordedAudioBlob, "voice_query.webm");
      state.recordedAudioBlob = null;
      document.getElementById("voiceStatusText").textContent = "";
    }

    const res = await fetch("/api/query/nl-to-sql", { method: "POST", body: formData });
    const data = await res.json();

    if (data.transcript && !document.getElementById("nlPromptInput").value.trim()) {
      document.getElementById("nlPromptInput").value = data.transcript;
    }
    document.getElementById("sqlEditorTextarea").value = data.sql || "";
    document.getElementById("sqlExplanationBar").innerHTML =
      `<strong>${escapeHtml(data.engine || "SQL Builder")}:</strong> ${escapeHtml(data.explanation || "")}`;

    const syncBadge = document.getElementById("sqlSyncStatusBadge");
    if (syncBadge) {
      syncBadge.className = "sql-sync-pill";
      syncBadge.textContent = autoExecute
        ? "✓ SQL & Preview Table Synced"
        : '⟳ SQL auto-updated with your selections · Click "Run SQL Query ▶" to refresh table';
    }
    updateSubpanelSummaries();

    if (autoExecute && data.sql) {
      await executeCurrentSql(data.transcript || document.getElementById("nlPromptInput").value || "Filtered Dataset");
    }
  } catch (err) {
    toast(`Query generation failed: ${err.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = origLabel;
  }
}

async function executeCurrentSql(promptSummary = "") {
  const sql = document.getElementById("sqlEditorTextarea").value.trim();
  if (!sql) {
    toast("SQL editor is empty.");
    return;
  }
  const runBtn = document.getElementById("runCustomSqlBtn");
  runBtn.disabled = true;
  runBtn.textContent = "Running…";

  try {
    const maxRows = parseInt(document.getElementById("filterLimit").value || "1500", 10);
    const res = await fetch("/api/query/execute", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sql, prompt_summary: promptSummary, max_rows: maxRows }),
    });
    const payload = await res.json();
    if (!res.ok) {
      throw new Error(payload.detail || "SQL execution error");
    }

    state.lastQueryRows = payload.preview_rows || [];
    renderQueryResults(payload);
    await loadSystemStatus();
  } catch (err) {
    toast(`SQL Error: ${err.message}`);
  } finally {
    runBtn.disabled = false;
    runBtn.textContent = "Run SQL Query ▶";
  }
}

function renderQueryResults(payload) {
  const sec = document.getElementById("queryResultsSection");
  sec.hidden = false;

  const s = payload.summary || {};
  const rowCnt = (s.row_count || 0).toLocaleString();
  document.getElementById("decisionHeadline").textContent =
    `${rowCnt} acoustic annotations matched your query (${s.column_count || 0} columns).`;
  document.getElementById("decisionSubtext").textContent =
    "Would you like to download the CSV file directly, explore & subset these calls in the Marimo Review Notebook, or configure an enriched export?";

  // KPI Tiles
  const kpiGrid = document.getElementById("queryKpiGrid");
  const dateSpan = s.min_start_utc
    ? `${String(s.min_start_utc).slice(0, 10)} → ${String(s.max_start_utc || "").slice(0, 10)}`
    : "—";
  kpiGrid.innerHTML = `
    <div class="kpi-tile"><div class="kpi-tile-label">Matched Annotations</div><div class="kpi-tile-val">${rowCnt}${s.truncated ? "+" : ""}</div></div>
    <div class="kpi-tile"><div class="kpi-tile-label">Verified Positive (YES)</div><div class="kpi-tile-val" style="color:var(--accent-emerald)">${s.positive_yes_count !== null && s.positive_yes_count !== undefined ? s.positive_yes_count.toLocaleString() : "—"}</div></div>
    <div class="kpi-tile"><div class="kpi-tile-label">Deployments</div><div class="kpi-tile-val">${s.deployments_count ?? "—"}</div></div>
    <div class="kpi-tile"><div class="kpi-tile-label">Linked Cloud Audio (gs://)</div><div class="kpi-tile-val" style="color:var(--accent-cyan)">${s.linked_audio_count !== null && s.linked_audio_count !== undefined ? s.linked_audio_count.toLocaleString() : "—"}</div></div>
    <div class="kpi-tile"><div class="kpi-tile-label">UTC Date Span</div><div class="kpi-tile-val" style="font-size:15px; margin-top:8px;">${escapeHtml(dateSpan)}</div></div>
  `;

  // Render Table
  const cols = payload.columns || [];
  const rows = payload.preview_rows || [];
  document.getElementById("previewTableCountBadge").textContent =
    `Showing ${rows.length.toLocaleString()} of ${rowCnt} rows`;

  const thead = document.querySelector("#queryResultsTable thead");
  const tbody = document.querySelector("#queryResultsTable tbody");

  thead.innerHTML = `<tr><th>Spectrogram</th>${cols.map((c) => `<th>${escapeHtml(c)}</th>`).join("")}</tr>`;
  tbody.innerHTML = rows
    .map((r, idx) => {
      const cells = cols
        .map((c) => {
          const v = r[c];
          if (c === "label_code" && v) {
            const cls =
              v === "YES" ? "badge-yes" : v === "NO" ? "badge-no" : v === "MAYBE" ? "badge-maybe" : "badge-unverified";
            return `<td><span class="badge-pill ${cls}">${escapeHtml(v)}</span></td>`;
          }
          if ((c === "freq_min_hz" || c === "freq_max_hz") && typeof v === "number") {
            return `<td class="mono">${v.toFixed(1)}</td>`;
          }
          if (c === "obj_gsuri" && v) {
            const shortUri = String(v).length > 52 ? String(v).slice(0, 26) + "…" + String(v).slice(-24) : v;
            return `<td class="mono" title="${escapeHtml(v)}">${escapeHtml(shortUri)}</td>`;
          }
          return `<td>${escapeHtml(v ?? "—")}</td>`;
        })
        .join("");
      return `<tr><td><button class="btn-xs inspect-call-btn" data-row-idx="${idx}" type="button">🔊 Inspect Call</button></td>${cells}</tr>`;
    })
    .join("");

  tbody.querySelectorAll(".inspect-call-btn").forEach((b) => {
    b.addEventListener("click", () => {
      const row = state.lastQueryRows[parseInt(b.dataset.rowIdx, 10)];
      openSpectrogramInspector(row);
    });
  });
}

function initVoiceAndQueryControls() {
  // Layer checkboxes visual sync + automatic live SQL regeneration
  document.querySelectorAll("#layerSelectorGroup .layer-card").forEach((card) => {
    const cb = card.querySelector("input[type='checkbox']");
    if (!cb.disabled) {
      cb.addEventListener("change", () => {
        card.classList.toggle("active", cb.checked);
        updateSubpanelSummaries();
        generateAndRunQuery(false);
      });
    }
  });

  // Auto-update SQL whenever any Structured Filter changes
  [
    "filterEffort",
    "filterOrg",
    "filterCallType",
    "filterLabel",
    "filterFreqMin",
    "filterFreqMax",
    "filterLimit",
    "filterRandomSample",
  ].forEach((id) => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener("change", () => {
        updateSubpanelSummaries();
        generateAndRunQuery(false);
      });
    }
  });

  // Debounced live SQL update as user types natural-language prompt
  let promptDebounce = null;
  document.getElementById("nlPromptInput").addEventListener("input", () => {
    clearTimeout(promptDebounce);
    promptDebounce = setTimeout(() => generateAndRunQuery(false), 400);
  });

  // Hide / Show SQL body toggle (retains Copy-Ready SQL header)
  const toggleSqlBtn = document.getElementById("toggleSqlBodyBtn");
  const sqlBody = document.getElementById("sqlCollapsibleBody");
  if (toggleSqlBtn && sqlBody) {
    toggleSqlBtn.addEventListener("click", () => {
      sqlBody.hidden = !sqlBody.hidden;
      toggleSqlBtn.textContent = sqlBody.hidden ? "Show SQL" : "Hide SQL";
    });
  }

  // Indicate manual SQL edits clearly
  document.getElementById("sqlEditorTextarea").addEventListener("input", () => {
    const syncBadge = document.getElementById("sqlSyncStatusBadge");
    if (syncBadge) {
      syncBadge.className = "sql-sync-pill manual";
      syncBadge.textContent = '✎ Custom edited SQL · Click "Run SQL Query ▶" to execute';
    }
  });

  document.getElementById("scopeOnlyAnnotationsBtn").addEventListener("click", () => {
    document.querySelectorAll("#layerSelectorGroup input[type='checkbox']").forEach((cb) => {
      if (!cb.disabled) {
        cb.checked = false;
        cb.closest(".layer-card")?.classList.remove("active");
      }
    });
    generateAndRunQuery(false);
  });

  document.getElementById("scopeFullMetadataBtn").addEventListener("click", () => {
    document.querySelectorAll("#layerSelectorGroup input[type='checkbox']").forEach((cb) => {
      cb.checked = true;
      cb.closest(".layer-card")?.classList.add("active");
    });
    generateAndRunQuery(false);
  });

  // Curated example chips
  document.querySelectorAll(".chip[data-example]").forEach((chip) => {
    chip.addEventListener("click", () => {
      document.getElementById("nlPromptInput").value = chip.dataset.example;
      const targetLayers = (chip.dataset.layers || "annotations").split(",");
      document.querySelectorAll("#layerSelectorGroup input[type='checkbox']").forEach((cb) => {
        if (!cb.disabled) {
          cb.checked = targetLayers.includes(cb.value);
          cb.closest(".layer-card")?.classList.toggle("active", cb.checked);
        }
      });
      generateAndRunQuery(true);
    });
  });

  document.getElementById("generateSqlBtn").addEventListener("click", () => generateAndRunQuery(true));
  document.getElementById("runCustomSqlBtn").addEventListener("click", () => executeCurrentSql("Edited SQL Query"));

  document.getElementById("copySqlBtn").addEventListener("click", async () => {
    const sql = document.getElementById("sqlEditorTextarea").value;
    await navigator.clipboard.writeText(sql);
    toast("PostgreSQL query copied to clipboard!");
  });

  // Audio file upload prompt
  document.getElementById("audioPromptFileInput").addEventListener("change", (e) => {
    const f = e.target.files?.[0];
    if (f) {
      state.recordedAudioBlob = f;
      document.getElementById("voiceStatusText").textContent = `Attached audio: ${f.name}`;
      toast(`Audio prompt "${f.name}" attached—click Generate SQL.`);
    }
  });

  // Live Microphone Voice Dictation + Audio Capture
  const voiceBtn = document.getElementById("recordVoiceBtn");
  const voiceLbl = document.getElementById("recordVoiceLabel");
  const statusEl = document.getElementById("voiceStatusText");

  voiceBtn.addEventListener("click", async () => {
    if (state.isRecording) {
      stopVoiceRecording();
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      state.isRecording = true;
      voiceBtn.classList.add("recording");
      voiceLbl.textContent = "Stop Recording";
      statusEl.textContent = "Listening…";

      const chunks = [];
      const mr = new MediaRecorder(stream);
      state.mediaRecorder = mr;
      mr.ondataavailable = (ev) => { if (ev.data.size > 0) chunks.push(ev.data); };
      mr.onstop = () => {
        state.recordedAudioBlob = new Blob(chunks, { type: mr.mimeType || "audio/webm" });
        stream.getTracks().forEach((tr) => tr.stop());
        statusEl.textContent = "Voice captured ✓";
      };
      mr.start();

      // Browser SpeechRecognition for instant live text feedback
      const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
      if (SR) {
        const rec = new SR();
        rec.continuous = true;
        rec.interimResults = true;
        rec.lang = "en-US";
        rec.onresult = (event) => {
          let transcript = "";
          for (let i = 0; i < event.results.length; i++) {
            transcript += event.results[i][0].transcript;
          }
          document.getElementById("nlPromptInput").value = transcript;
        };
        rec.start();
        state.speechRec = rec;
      }
    } catch (err) {
      toast(`Microphone access unavailable: ${err.message}`);
    }
  });

  function stopVoiceRecording() {
    state.isRecording = false;
    voiceBtn.classList.remove("recording");
    voiceLbl.textContent = "Speak Query";
    if (state.speechRec) {
      try { state.speechRec.stop(); } catch (_) {}
      state.speechRec = null;
    }
    if (state.mediaRecorder && state.mediaRecorder.state !== "inactive") {
      state.mediaRecorder.stop();
    }
  }

  // Post-query decision buttons
  document.getElementById("sendToMarimoBtn").addEventListener("click", () => stageAndOpenMarimo());
  document.getElementById("sendToExportBtn").addEventListener("click", () => switchTab("export"));
}

/* --------------------------------------------------------------------------
   5. Module 02: Marimo Review Studio & Slide-Over Spectrogram Inspector
   -------------------------------------------------------------------------- */
async function stageAndOpenMarimo() {
  switchTab("review");
  const placeholder = document.getElementById("marimoPlaceholder");
  const iframe = document.getElementById("marimoIframe");
  placeholder.querySelector("h3").textContent = "Staging Dataset & Starting Marimo Review Studio…";

  try {
    const promptTxt = document.getElementById("nlPromptInput").value || "DCLDE_2013 Dataset";
    const res = await fetch("/api/review/stage", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        use_last_query: true,
        prompt_summary: promptTxt,
        marimo_mode: "run",
      }),
    });
    const data = await res.json();
    if (data.marimo?.url) {
      document.getElementById("openMarimoNewTabLink").href = data.marimo.url;
      iframe.src = data.marimo.url;
      iframe.hidden = false;
      placeholder.hidden = true;
      toast(`Staged ${data.staged_rows.toLocaleString()} annotations into Marimo Review Studio.`);
    }
  } catch (err) {
    toast(`Failed launching Marimo: ${err.message}`);
  }
}

async function openSpectrogramInspector(rowMeta) {
  state.activeSpecRow = rowMeta;
  const drawer = document.getElementById("spectrogramDrawer");
  drawer.hidden = false;
  await loadAndRenderSpectrogram();
}

async function loadAndRenderSpectrogram() {
  if (!state.activeSpecRow) return;
  const row = state.activeSpecRow;
  const plotBox = document.getElementById("specPlotContainer");
  plotBox.innerHTML = `<div style="padding:48px; text-align:center; color:#94a3b8;">Computing STFT spectrogram &amp; fetching audio slice…</div>`;

  const reqBody = {
    annotation_id: row.annotation_id ?? null,
    row_meta: row,
    nfft: parseInt(document.getElementById("specNfft").value, 10),
    overlap_pct: parseFloat(document.getElementById("specOverlap").value),
    window_type: document.getElementById("specWindow").value,
    fmin_hz: 0.0,
    fmax_hz: parseFloat(document.getElementById("specFmax").value || "450"),
    padding_sec: parseFloat(document.getElementById("specPadding").value),
    db_range: parseFloat(document.getElementById("specDbRange").value || "55"),
  };

  try {
    const res = await fetch("/api/spectrogram", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(reqBody),
    });
    const spec = await res.json();
    const ann = spec.annotation || row;

    document.getElementById("specDrawerTitle").textContent =
      `Annotation #${ann.annotation_id ?? "—"} · ${ann.call_type_code || "CALL"} [${ann.label_code || ""}]`;

    const gsUri = ann.obj_gsuri || spec.gs_uri || "Unlinked segment";
    const gcsUrl = gsUri.startsWith("gs://")
      ? `https://console.cloud.google.com/storage/browser/_details/${gsUri.slice(5)}`
      : "#";

    document.getElementById("specMetaBar").innerHTML = `
      <div><strong>UTC Window:</strong> ${escapeHtml(ann.start_time_utc)} → ${escapeHtml(ann.end_time_utc)} &nbsp;·&nbsp;
      <strong>Band:</strong> ${ann.freq_min_hz ? Number(ann.freq_min_hz).toFixed(1) : "—"}–${ann.freq_max_hz ? Number(ann.freq_max_hz).toFixed(1) : "—"} Hz &nbsp;·&nbsp;
      <strong>SR:</strong> ${spec.sample_rate_hz} Hz &nbsp;·&nbsp; <strong>Byte Offset:</strong> ${ann.data_byte_offset ?? "—"}</div>
      <div class="spec-uri-line"><strong>Cloud Audio URI:</strong> <a href="${escapeHtml(gcsUrl)}" target="_blank" class="link-accent">${escapeHtml(gsUri)}</a></div>
    `;

    const isLive = String(spec.source_status || "").startsWith("live");
    const friendlyNoteHtml = spec.gcs_note
      ? `Tip: Run <code class="gcloud-highlight">gcloud auth login</code> in terminal to stream live private GCS audio (showing calibrated FM call preview).`
      : "";
    document.getElementById("specSourceBadgeWrap").innerHTML = `
      <span class="badge-pill ${isLive ? "badge-yes" : "badge-maybe"}">${escapeHtml(spec.source_badge)}</span>
      ${friendlyNoteHtml ? `<span style="font-size:11.5px; color:var(--text-secondary); margin-left:8px;">${friendlyNoteHtml}</span>` : ""}
      <div id="drawerAudioErrorPopup" class="audio-error-popover" hidden></div>
    `;

    const player = document.getElementById("specAudioPlayer");
    if (isLive) {
      player.src = `data:audio/wav;base64,${spec.audio_wav_b64}`;
      player.onplay = null;
    } else {
      player.removeAttribute("src");
      player.load();
      player.onclick = (ev) => {
        ev.preventDefault();
        const pop = document.getElementById("drawerAudioErrorPopup");
        if (pop) {
          pop.hidden = false;
          pop.innerHTML = `<strong>Cloud Audio Unavailable — Not Connected to Google Cloud (GCS):</strong> Cannot stream <code>${escapeHtml(gsUri)}</code> because your Google Cloud session is not signed in. Run <code class="gcloud-highlight">gcloud auth login</code> in PowerShell, then click Settings (⚙) → Save &amp; Refresh Connections.`;
        }
      };
    }

    const cmapName = document.getElementById("specColormap").value;
    const resolvedScale = BIOACOUSTIC_COLORSCALES[cmapName] || cmapName;
    plotBox.innerHTML = "";

    if (window.Plotly) {
      const cbox = spec.call_box || {};
      const maxF = Math.max(...spec.freqs_hz);
      const traces = [
        {
          type: "heatmap",
          x: spec.times_s,
          y: spec.freqs_hz,
          z: spec.power_db,
          zmin: spec.z_min_db,
          zmax: spec.z_max_db,
          colorscale: resolvedScale,
          colorbar: { title: { text: "dB", side: "right" }, len: 0.66, y: 0.67, thickness: 14 },
          xaxis: "x",
          yaxis: "y",
          hovertemplate: "t=%{x:.3f}s<br>f=%{y:.1f} Hz<br>%{z:.1f} dB<extra></extra>",
        },
        {
          type: "scatter",
          mode: "lines",
          x: spec.waveform.t,
          y: spec.waveform.y,
          line: { color: "#22d3ee", width: 1.15 },
          xaxis: "x2",
          yaxis: "y2",
          hovertemplate: "t=%{x:.3f}s<br>amp=%{y:.3f}<extra></extra>",
        },
      ];
      const layout = {
        paper_bgcolor: "#06101e",
        plot_bgcolor: "#040b15",
        font: { family: "Plus Jakarta Sans, sans-serif", color: "#e2e8f0", size: 11.5 },
        height: 480,
        margin: { l: 62, r: 30, t: 22, b: 52 },
        showlegend: false,
        xaxis: { anchor: "y", showticklabels: false, gridcolor: "rgba(148,163,184,0.12)" },
        yaxis: { title: "Frequency (Hz)", domain: [0.32, 1.0], gridcolor: "rgba(148,163,184,0.12)" },
        xaxis2: {
          anchor: "y2",
          matches: "x",
          title: "Time Offset in Window (seconds)",
          gridcolor: "rgba(148,163,184,0.12)",
        },
        yaxis2: { title: "Waveform", domain: [0.0, 0.24], gridcolor: "rgba(148,163,184,0.12)" },
        shapes: [
          {
            type: "rect",
            xref: "x",
            yref: "y",
            x0: cbox.t0,
            x1: cbox.t1,
            y0: cbox.f0 ?? 0,
            y1: Math.min(cbox.f1 ?? maxF, maxF),
            line: { color: "#22d3ee", width: 2.2 },
            fillcolor: "rgba(34, 211, 238, 0.08)",
          },
        ],
      };
      window.Plotly.newPlot(plotBox, traces, layout, { responsive: true, displayModeBar: true });
    }
  } catch (err) {
    plotBox.innerHTML = `<div style="padding:32px; color:#fb7185;">Spectrogram failed: ${escapeHtml(err.message)}</div>`;
  }
}

/* --------------------------------------------------------------------------
   6. Module 03: Export Studio
   -------------------------------------------------------------------------- */
function getExportRequestPayload(format = "csv") {
  const src = document.querySelector("input[name='exportSource']:checked")?.value || "last_query";
  return {
    source: src,
    effort_name: document.getElementById("exportEffortSelect").value || "DCLDE_2013",
    limit: parseInt(document.getElementById("exportRowLimit").value || "5000", 10),
    enrich_makara_deployment: document.getElementById("expEnrichDeployment").checked,
    enrich_makara_recording: document.getElementById("expEnrichRecording").checked,
    enrich_taxonomy: document.getElementById("expEnrichTaxonomy").checked,
    enrich_provenance: document.getElementById("expEnrichProvenance").checked,
    enrich_reconcile: document.getElementById("expEnrichReconcile").checked,
    export_format: format,
  };
}

async function refreshExportPreview() {
  const box = document.getElementById("exportSummaryBox");
  box.textContent = "Building relational export preview…";
  try {
    const req = getExportRequestPayload("csv");
    const res = await fetch("/api/export/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Preview failed");

    box.innerHTML = `
      <div><strong>Ready to Export:</strong> ${data.row_count.toLocaleString()} annotations × ${data.column_count} columns &nbsp;|&nbsp;
      <strong>Distinct GCS Audio Containers (<code>gs://</code>):</strong> ${data.distinct_audio_files.toLocaleString()}</div>
      ${data.sample_uris?.length ? `<div class="mono" style="margin-top:5px; font-size:11px; color:var(--text-secondary);">Sample URI: ${escapeHtml(data.sample_uris[0])}</div>` : ""}
    `;

    const cols = data.columns || [];
    const rows = data.preview_rows || [];
    document.querySelector("#exportPreviewTable thead").innerHTML =
      `<tr>${cols.map((c) => `<th>${escapeHtml(c)}</th>`).join("")}</tr>`;
    document.querySelector("#exportPreviewTable tbody").innerHTML = rows
      .slice(0, 25)
      .map((r) => `<tr>${cols.map((c) => `<td>${escapeHtml(r[c] ?? "—")}</td>`).join("")}</tr>`)
      .join("");
  } catch (err) {
    box.innerHTML = `<span style="color:var(--accent-amber)">${escapeHtml(err.message)}</span>`;
  }
}

async function triggerExportDownload(format) {
  try {
    const req = getExportRequestPayload(format);
    const res = await fetch("/api/export/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    });
    if (!res.ok) {
      const errJson = await res.json();
      throw new Error(errJson.detail || "Export failed");
    }
    const blob = await res.blob();
    const disp = res.headers.get("Content-Disposition") || "";
    const match = disp.match(/filename="([^"]+)"/);
    const filename = match ? match[1] : `annomate_export.${format}`;
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    toast(`Downloaded ${filename}`);
  } catch (err) {
    toast(`Export failed: ${err.message}`);
  }
}

/* --------------------------------------------------------------------------
   7. Module 04: Add & Align Annotations Workbench
   -------------------------------------------------------------------------- */
function renderColumnMapper(uploadData) {
  state.alignSession = uploadData;
  document.getElementById("alignDropzoneTitle").textContent =
    `Loaded: ${uploadData.filename} (${uploadData.row_count.toLocaleString()} rows)`;
  document.getElementById("alignDropzoneSub").textContent =
    `Auto-detected profile: ${uploadData.detected_preset} · ${uploadData.columns.length} source columns`;
  document.getElementById("alignPresetSelect").value = uploadData.detected_preset;

  const container = document.getElementById("columnMapperContainer");
  const cols = uploadData.columns || [];
  const suggested = uploadData.suggested_mapping || {};

  container.innerHTML = TARGET_ALIGN_FIELDS.map((tf) => {
    const opts = [`<option value="">— Unmapped / Use Default —</option>`]
      .concat(
        cols.map((c) => {
          const sel = suggested[tf.key] === c ? "selected" : "";
          return `<option value="${escapeHtml(c)}" ${sel}>${escapeHtml(c)}</option>`;
        })
      )
      .join("");
    return `
      <div class="mapper-row">
        <div>
          <div class="mapper-target-name">${escapeHtml(tf.label)}</div>
          <div class="mapper-target-desc">${escapeHtml(tf.desc)}</div>
        </div>
        <select data-map-field="${escapeHtml(tf.key)}">${opts}</select>
      </div>
    `;
  }).join("");

  runAlignmentValidation();
}

function collectAlignRequest() {
  const mapping = {};
  document.querySelectorAll("#columnMapperContainer select[data-map-field]").forEach((sel) => {
    mapping[sel.dataset.mapField] = sel.value || null;
  });

  const parseOverridePairs = (str) => {
    const out = {};
    (str || "").split(",").forEach((pair) => {
      const idx = pair.indexOf("=");
      if (idx > 0) {
        out[pair.slice(0, idx).trim()] = pair.slice(idx + 1).trim();
      }
    });
    return out;
  };

  const newProcName = document.getElementById("newProcName").value.trim();
  const newProc = newProcName
    ? {
        analysis_id: parseInt(document.getElementById("newProcAnalysisSelect").value, 10),
        name: newProcName,
        description: document.getElementById("newProcDesc").value.trim(),
        analysts: document.getElementById("alignDefaultAnalyst").value.trim(),
      }
    : null;

  return {
    session_id: state.alignSession?.session_id,
    mapping,
    defaults: {
      organization_code: document.getElementById("alignOrgSelect").value,
      recording_channel_id: document.getElementById("alignRecordingChannelSelect").value,
      procedure_id: document.getElementById("alignProcedureSelect").value,
      create_new_procedure: Boolean(newProc),
      call_type_code: document.getElementById("alignDefaultCallType").value,
      label_code: document.getElementById("alignDefaultLabel").value,
      granularity_code: document.getElementById("alignDefaultGranularity").value,
      sharing_code: document.getElementById("alignDefaultSharing").value,
      analyst: document.getElementById("alignDefaultAnalyst").value,
      file_start_anchor_utc: document.getElementById("alignAnchorUtc").value,
      one_based_channel: document.getElementById("alignOneBasedCh").checked,
      freq_in_khz: document.getElementById("alignFreqKhz").checked,
    },
    vocab_maps: {
      call_type_code: parseOverridePairs(document.getElementById("vocabCallOverrides").value),
      label_code: parseOverridePairs(document.getElementById("vocabLabelOverrides").value),
    },
    new_procedure: newProc,
  };
}

async function runAlignmentValidation() {
  if (!state.alignSession) {
    toast("Upload a file or load a sample dataset first.");
    return;
  }
  const req = collectAlignRequest();
  try {
    const res = await fetch("/api/align/validate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    });
    const report = await res.json();
    if (!res.ok) throw new Error(report.detail || "Validation error");

    const panel = document.getElementById("alignValidationPanel");
    panel.hidden = false;

    document.getElementById("alignReportTitle").textContent =
      `Validation Report: ${report.valid_rows.toLocaleString()} / ${report.total_rows.toLocaleString()} Rows Ready`;

    const issueKeys = Object.entries(report.issue_summary || {});
    const banner = document.getElementById("alignIssuesBanner");
    if (issueKeys.length === 0) {
      banner.innerHTML = `<div class="guaranteed-audio-box" style="margin-top:0;"><div class="ga-icon">✓</div><div><strong>All ${report.valid_rows} rows passed schema &amp; foreign-key validation!</strong><p>Ready to download as standardized CSV or commit transactionally to <code>core.annotations</code>.</p></div></div>`;
    } else {
      banner.innerHTML = `<div class="export-summary-box" style="border-color:var(--accent-amber);"><strong>Pre-flight warnings (${report.invalid_rows} rows):</strong> ${issueKeys.map(([m, n]) => `${escapeHtml(m)} (${n})`).join(" · ")}</div>`;
    }

    const cols = [
      "row_num",
      "valid",
      "recording_channel_id",
      "organization_code",
      "call_type_code",
      "label_code",
      "granularity_code",
      "start_time_utc",
      "end_time_utc",
      "freq_min_hz",
      "freq_max_hz",
      "analyst",
      "issues",
    ];
    document.querySelector("#alignPreviewTable thead").innerHTML =
      `<tr>${cols.map((c) => `<th>${escapeHtml(c)}</th>`).join("")}</tr>`;
    document.querySelector("#alignPreviewTable tbody").innerHTML = (report.rows || [])
      .slice(0, 60)
      .map((r) => {
        return `<tr>${cols
          .map((c) => {
            if (c === "valid") {
              return `<td><span class="badge-pill ${r.valid ? "badge-yes" : "badge-maybe"}">${r.valid ? "READY" : "CHECK"}</span></td>`;
            }
            if (c === "issues") {
              return `<td style="color:var(--accent-amber)">${escapeHtml((r.issues || []).join("; ") || "—")}</td>`;
            }
            return `<td>${escapeHtml(r[c] ?? "—")}</td>`;
          })
          .join("")}</tr>`;
      })
      .join("");
  } catch (err) {
    toast(`Alignment check failed: ${err.message}`);
  }
}

function initModules02To04() {
  // Marimo Studio launchers
  document.getElementById("launchMarimoStudioBtn").addEventListener("click", stageAndOpenMarimo);
  document.getElementById("launchMarimoCenterBtn").addEventListener("click", stageAndOpenMarimo);

  // Spectrogram drawer controls
  document.getElementById("closeSpecDrawerBtn").addEventListener("click", () => {
    document.getElementById("spectrogramDrawer").hidden = true;
    document.getElementById("specAudioPlayer").pause();
  });
  document.getElementById("recomputeSpecBtn").addEventListener("click", loadAndRenderSpectrogram);

  // Export Studio controls
  document.querySelectorAll("input[name='exportSource']").forEach((rad) => {
    rad.addEventListener("change", () => {
      document.querySelectorAll("#exportSourceGroup .radio-card").forEach((c) => c.classList.remove("active"));
      rad.closest(".radio-card").classList.add("active");
      document.getElementById("exportEffortField").hidden = rad.value !== "effort";
      refreshExportPreview();
    });
  });
  document.getElementById("refreshExportPreviewBtn").addEventListener("click", refreshExportPreview);
  document.querySelectorAll(".export-dl-card").forEach((card) => {
    card.addEventListener("click", () => triggerExportDownload(card.dataset.format));
  });

  // Align & Ingest controls
  document.querySelectorAll("[data-sample]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const res = await fetch(`/api/align/load-sample/${btn.dataset.sample}`, { method: "POST" });
      const data = await res.json();
      renderColumnMapper(data);
      toast(`Loaded sample ${data.filename}`);
    });
  });

  document.getElementById("alignFileInput").addEventListener("change", async (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    const fd = new FormData();
    fd.append("file", f);
    const res = await fetch("/api/align/upload", { method: "POST", body: fd });
    const data = await res.json();
    if (!res.ok) {
      toast(data.detail || "Upload failed");
      return;
    }
    renderColumnMapper(data);
  });

  document.getElementById("runAlignValidationBtn").addEventListener("click", runAlignmentValidation);

  document.getElementById("downloadAlignedCsvBtn").addEventListener("click", async () => {
    if (!state.alignSession) return;
    const req = collectAlignRequest();
    const res = await fetch("/api/align/download-standardized", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    });
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "annomate_standardized_annotations.csv";
    a.click();
    URL.revokeObjectURL(url);
    toast("Downloaded standardized CSV!");
  });

  document.getElementById("commitAlignedDbBtn").addEventListener("click", async () => {
    if (!state.alignSession) return;
    const req = collectAlignRequest();
    if (!confirm("Insert all validated standardized rows into core.annotations on nmfs_annotation_db?")) {
      return;
    }
    const res = await fetch("/api/align/commit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    });
    const data = await res.json();
    if (!res.ok) {
      toast(`Commit failed: ${data.detail}`);
      return;
    }
    if (data.simulated_demo) {
      toast(`Demo Mode Simulation: Validated ${data.inserted_count} annotations (live DB untouched)!`);
    } else {
      toast(`Committed ${data.inserted_count} annotations to nmfs_annotation_db (procedure #${data.procedure_id})!`);
    }
    await loadSystemStatus();
    await loadCatalog();
  });
}

/* --------------------------------------------------------------------------
   Bootstrap
   -------------------------------------------------------------------------- */
document.addEventListener("DOMContentLoaded", async () => {
  initAmbientWaveCanvas();
  initNavigationAndTheme();
  initVoiceAndQueryControls();
  initModules02To04();

  const hash = (window.location.hash || "").replace(/^#/, "").toLowerCase();
  if (["find", "review", "export", "align"].includes(hash)) {
    switchTab(hash);
  }

  await Promise.all([loadSystemStatus(), loadCatalog()]);

  document.getElementById("nlPromptInput").value =
    "Find verified right whale upcalls in DCLDE_2013 with deployment coordinates and GCS audio paths";

  if (hash === "align") {
    const r = await fetch("/api/align/load-sample/raven_pro", { method: "POST" });
    if (r.ok) renderColumnMapper(await r.json());
  } else if (hash === "export") {
    await refreshExportPreview();
  } else if (hash === "review") {
    await stageAndOpenMarimo();
  } else {
    await generateAndRunQuery(true);
    if (hash === "spectrogram" && state.lastQueryRows.length > 0) {
      await openSpectrogramInspector(state.lastQueryRows[0]);
    }
  }
});
