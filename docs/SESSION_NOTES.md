# Annomate — Session Pause & Resume Notes

**Paused:** 2026-11-19  
**Workspace:** `c:\Users\shannon.rankin\Documents\GitHub\annomate`

---

## 1. Current State (Where We Stopped)

All four core modules of **Annomate** v1.0 are implemented, tested against the live `nmfs_annotation_db` over NOAA VPN, and visually polished across two browser render passes:

- **01 · Find & Filter Data** (`app/schema_context.py`, `static/index.html`, `static/app.js`):
  - Browser voice dictation + audio memo upload + natural-language text → copy-ready PostgreSQL (`tstzrange &&` GiST joins) + CSV download + Marimo review handoff.
  - Toggleable relational metadata scope: **Annotations Only** (`core.annotations`) vs. joining **Study/Effort Provenance**, **Makara Deployments & Recordings**, **Physical Cloud Audio (`gs://`) & Byte Offsets**, and **Reconciliation Status**.
  - Inline visual schema guide + full multi-section Documentation Hub at `/guide` (`docs/00_QUICKSTART_AND_OVERVIEW.md` through `docs/04_ADD_AND_ALIGN_ANNOTATIONS_GUIDE.md` + `docs/ANNOTATION_DATA_GUIDE.md`).
- **Automated Test Suite** (`tests/test_annomate.py`):
  - Covers SQL builder & NL-to-SQL parser, little/big-endian PCM decoding & STFT spectrogram engine, Raven/Triton/PAMGuard aligner & validator, FastAPI routes, and full headless execution of `notebooks/review_studio.py`.
- **02 · Review Data — Reactive Marimo Notebook** (`notebooks/review_studio.py`, `notebooks/marimo_theme.css`):
  - Pre-loads staged query data (or live `DCLDE_2013`), provides reproducible random & stratified subsetting, 4 interactive bioacoustic visualizations, embedded STFT spectrogram + HTML5 audio player with user-tunable parameters (`NFFT`, `Overlap %`, `Window`, `Padding`, `Max Hz`, `Dynamic Range`, `Colormap`), and an embedded Bioacoustics Data Chatbot.
- **03 · Export Data** (`app/main.py`):
  - Exports active query results, Marimo reviewed subsets, or full effort datasets enriched with Makara/taxonomy/provenance columns and guaranteed `gs://` audio URIs (`CSV`, `Raven Pro .selection.txt`, `JSONL ML Manifest`, and `gcloud storage cp` `.ps1` batch download script).
- **04 · Add & Align Annotations** (`app/aligner.py`, `sample_data/`):
  - Smart presets for **Raven Pro**, **Triton Logger / Remora**, **PAMGuard**, and **Custom CSV/Excel**, column & vocabulary alignment, pre-flight schema/FK validation, standardized CSV export, and transactional commit to `core.procedures` & `core.annotations`.

### Git Status Note
- Files are currently **uncommitted** on `main` (`git status` is clean with `.env`, `.venv/`, and `data/` excluded via `.gitignore` so credentials are safe).

---

## 2. How to Restart Next Session

### Step A — Prerequisites
1. Connect to the **NOAA VPN** (required to reach `nmfs_annotation_db` at `10.27.24.242`).
2. *(Recommended for live private GCS audio slicing on `gs://nefsc-1/...`)* Refresh your Google Cloud login in PowerShell:
   ```powershell
   gcloud auth login
   # or:
   gcloud auth application-default login
   ```

### Step B — Start Annomate
From PowerShell in `c:\Users\shannon.rankin\Documents\GitHub\annomate`:
```powershell
.\run_annomate.ps1
```
Then open:
- **Web App:** http://127.0.0.1:8000
- **Schema Guide:** http://127.0.0.1:8000/guide
- **Marimo Studio:** Click **Review in Marimo Notebook** in the app (auto-starts on http://127.0.0.1:2718), or run manually:
  ```powershell
  .\.venv\Scripts\python.exe -m marimo edit .\notebooks\review_studio.py --port 2718
  ```

---

## 3. Suggested Next Steps When Resuming

1. **Test Live GCS Byte-Range Streaming:** After running `gcloud auth login`, click **🔊 Inspect Call** on any `DCLDE_2013` row (or inspect inside Marimo) to verify live byte-range audio streaming from the 10-channel MARU `.aif` files in `gs://nefsc-1/...` (and any SWFSC `.x.wav` / `.x.flac` recordings once whitelisted by Dan).
2. **Optional Gemini API Key:** Add `GEMINI_API_KEY` via the top-right **Settings (⚙)** modal (or in `.env`) to enable multimodal voice-audio-to-SQL and open-ended LLM chat in Marimo.
3. **Test Real Lab Annotation Logs:** Upload a real SWFSC Raven Pro selection table, Triton Logger `.xls`/`.csv`, or PAMGuard table in **04 · Add & Align Annotations** to fine-tune any lab-specific call-type or analyst codes.
4. **Initial Git Commit & Push:** Once happy with your first live walkthrough, run `git add .` and `git commit -m "Initial Annomate platform"` (double-checking `.env` stays ignored).
