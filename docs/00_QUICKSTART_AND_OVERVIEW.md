# Getting Started with Annomate

Welcome to **annomate**—your bioacoustic annotation discovery, review, standardization, and cloud-export platform built on NOAA NMFS's `nmfs_annotation_db` (PostgreSQL + PostGIS), **Makara** deployment metadata, and **Google Cloud Storage (`gs://`)** audio archives.

---

## 1. Before You Launch (Live Mode vs. Offline Demo Mode)

> **Giving a Demo Away from GCP or NOAA VPN?**  
> You do **not** need Google Cloud credentials or VPN access to run a full interactive demo! Double-click **`Start_Annomate_Demo.bat`** in your `annomate` folder—or click the **`Demo Mode: OFF / ON`** button in the top header bar at any time—to explore a built-in 180-call multi-site bioacoustic dataset (`NEFSC_SBNMS`, `NEFSC_CCBAY`, `NEFSC_GSC`) with live filtering, bathymetry + `PAMpal` plots, playable call audio & spectrograms, exports, and safe simulated database imports.

1. **Connect to the NOAA VPN *(Live Mode)***  
   `nmfs_annotation_db` is hosted on an internal NOAA endpoint (`10.27.24.242`). Ensure your Cisco / org VPN is connected so Annomate displays the green **`VPN Live`** indicator in the top bar. *(If you are away from VPN, Annomate also automatically falls back to the built-in 180-call demo dataset.)*

2. **Sign In to Google Cloud for Live Audio Streaming *(Live Mode)***  
   To stream live byte-ranges from private NOAA buckets (such as `gs://nefsc-1/...`) for call spectrograms and audio playback, open PowerShell once and run:
   ```powershell
   gcloud auth login
   ```
   *(Alternatively, `gcloud auth application-default login` works as well.)* Once signed in, click the **Settings (⚙)** gear in the top-right corner of Annomate and click **Save & Refresh Connections**.

3. **Optional: Add a Gemini API Key**  
   Voice dictation (via browser speech recognition), schema-aware text-to-SQL, and quantitative Marimo chat work **out of the box with no API key**. If you want raw audio-memo-to-SQL and open-ended LLM conversation in the Marimo chatbot, click **Settings (⚙)** and paste your `GEMINI_API_KEY`.

---

## 2. Launching Annomate

- **No Command Line Needed (Windows Explorer):** Double-click **`Start_Annomate.bat`** (for Live Mode) or **`Start_Annomate_Demo.bat`** (for 100% offline Demo Mode).
- **PowerShell:** Run `.\run_annomate.ps1` in `c:\Users\shannon.rankin\Documents\GitHub\annomate`.

Then open your browser to:

| Component | Local URL | Purpose |
| :--- | :--- | :--- |
| **Main Annomate Web App** | http://127.0.0.1:8000 | Find & Filter, Review launcher, Export Studio, and Annotation Aligner |
| **Documentation Hub** | http://127.0.0.1:8000/guide | Step-by-step guides for every component + database schema reference |
| **Marimo Review Studio** | http://127.0.0.1:2718 | Auto-launched when you click **Review in Marimo Notebook** |
| **Interactive NMFS ERD** | [Open Cloud Run ERD ↗](https://anndb-frontend-app-948464146942.us-east4.run.app/) | Live entity-relationship & Makara–GCS sync diagram *(NOAA Google login)* |

---

## 3. How the Four Modules Fit Together

1. **01 · Find & Filter Data:** Speak or type what you are looking for, choose whether you want **Annotations Only** or joined relational metadata (`makara`, `audio`, `provenance`, `reconcile`), copy the generated PostgreSQL query, and either **Download CSV** or **Send to Marimo**.
2. **02 · Review Data (Marimo Studio):** Reproducibly subset large call catalogs using a random seed, explore diel/frequency/spatial plots, inspect interactive call spectrograms + audio linked back to `gs://`, and ask questions in the embedded chatbot.
3. **03 · Export Data:** Package your query results, your reviewed Marimo subset, or an entire effort dataset (`DCLDE_2013`) with guaranteed `gs://` cloud audio URIs and byte offsets into **CSV**, **Raven Pro Selection Tables (`.txt`)**, **JSONL ML Manifests**, or a **`gcloud storage cp` batch download script**.
4. **04 · Add & Align Annotations:** Drop in Raven Pro, Triton Logger / Remora, PAMGuard, or custom CSV files, align columns and controlled codes to `core.annotations`, validate every row pre-flight, and export standardized CSVs or commit transactionally to `nmfs_annotation_db`.

---

## 4. Common Troubleshooting & "When to Ask Dan"

- **A Makara recording has no audio files (`obj_gsuri` is blank):** Because NOAA's GCS archive uses Autoclass storage tiers, the crawler only indexes recordings meeting Standard-tier thresholds or explicitly whitelisted recordings. **Ask Dan** to add specific recordings to the GCS crawler whitelist.
- **Need a new top-level study in `core.analyses`:** Your database role (`shannon_ai_agent`) can read all schemas and write to `annotations`, `procedures`, `effort`, `bins`, `bins_effort`, and `effort_procedures`. You can create new `core.procedures` under existing `core.analyses` rows (such as `UNCLASSIFIED` or `DCLDE_2013`) right inside Module 04; if you need a brand-new `core.analyses` or `makara.organizations` entry, **ask Dan**.
