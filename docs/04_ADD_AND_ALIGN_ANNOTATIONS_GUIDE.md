# Component 04 · Add & Align Annotations Guide

Bioacoustic analysts and automated detectors produce outputs in many different table layouts. The **Add & Align Annotations** workbench (`http://127.0.0.1:8000/#align`) aligns heterogeneous detection logs into the standardized `core.annotations` schema, validates every row against database constraints pre-flight, and either exports a clean standardized CSV or commits rows transactionally to `nmfs_annotation_db`.

---

## 1. Supported Bioacoustic Formats & Quick Sample Testing

Annomate includes built-in column and unit profiles for four common PAM workflows:
1. **Raven Pro Selection Tables (`.txt` / `.tsv`):** Maps 1-based `Channel`, file-relative `Begin Time (s)` / `End Time (s)`, `Low Freq (Hz)` / `High Freq (Hz)`, and `Begin File`.
2. **Triton Logger / Remora Spreadsheets (`.xls` / `.xlsx` / `.csv`):** Maps `Input file` (including `.x.wav` / `.x.flac`), absolute UTC `Start time` / `End time`, `Parameter 1 (Hz)` / `Parameter 2 (Hz)`, `Call`, and `User ID`.
3. **PAMGuard Detection Exports (`.csv`):** Maps `UTC` start timestamp + `Duration_ms` (automatically computing `end_time_utc`), `ChannelMap`, `MinFreq_Hz` / `MaxFreq_Hz`, `DetectorScore`, and `SpeciesClass`.
4. **Generic CSV / Excel Tables:** Auto-matches common column headers with full manual override dropdowns.

> **Try It in One Click:** At the top-right of Module 04, click **Load Raven Pro (.txt)**, **Load Triton Logger (.csv)**, or **Load PAMGuard (.csv)** to test the entire alignment and validation workflow using sample files from [`sample_data/`](../sample_data/).

---

## 2. Step-by-Step Standardization Workflow

### Step 1 & 2: Upload File & Set Provenance Context
1. **Drop or select your file** (`.txt`, `.tsv`, `.csv`, `.xls`, `.xlsx`). Annomate auto-detects the delimiter and format profile.
2. **Select Required Provenance Defaults:**
   - **Organization Code:** Steward center (e.g., `NEFSC`, `SWFSC`)—required on every row for database partitioning and permissions.
   - **Target Recording Channel (`recording_channel_id`):** Pick the hydrophone channel your annotations belong to, or leave on *Auto-resolve from filename* if your file lists filenames already indexed in `core.acoustic_files`.
   - **Study Procedure (`core.procedures`):** Select an existing procedure—or expand **`+ Or Create a New Procedure under an Existing Analysis`** to register a new `core.procedures` record under an existing study (such as `DCLDE_2013` or `UNCLASSIFIED`) in the same database transaction!
   - **Default Call Type, Verification Label, Granularity, Sharing Scope & Analyst:** Used whenever a row does not specify its own per-row value. Analyst identifiers follow Makara's `FIRSTINITIAL+LAST` convention (e.g., `SRANKIN`).
3. **Set Unit & Time Anchors:**
   - **1-based channel toggle:** Checked by default for Raven/Triton (`Channel 1` → database `0`).
   - **kHz-to-Hz toggle:** Check if your source table reports frequencies in kHz rather than Hz.
   - **Fallback File Start UTC:** When importing Raven selection tables that only contain relative `Begin Time (s)` (e.g., `188.812 s` from file start), Annomate resolves the absolute UTC timestamp automatically from:
     1. Matching the `Begin File` name in `core.acoustic_files` / `core.audio_segments`, or
     2. Parsing `YYYYMMDD_HHMMSS` / HARP `YYMMDD_HHMMSS` timestamps embedded in the filename, or
     3. Adding the offset to your supplied **Fallback File Start UTC** anchor (e.g., `2009-03-28T05:00:00Z`).

---

### Step 3: Map Columns & Custom Vocabulary Synonyms
- Review the right-hand **Map Source Columns** list. Auto-matched source columns are pre-selected; change any dropdown to remap or set to *Unmapped / Use Default*.
- Expand **Custom Call Type / Label Synonym Overrides** if your analysts use shorthand strings not yet in the built-in dictionary—for example:
  - Call Type Map: `Upcall=RW_UPCALL, Moan=RW_MOAN`
  - Label Map: `Pos=YES, Distant=MAYBE, Vessel=NO`
- Click **Align & Validate Rows ▶** to run pre-flight checks.

---

### Step 4: Pre-Flight Validation & Safe Database Commit
Before anything touches PostgreSQL, Annomate validates every row against `core.annotations` constraints:
- Non-empty temporal range (`end_time_utc > start_time_utc`) formatted into `tstzrange`
- Non-negative ordered frequency bounds (`0 <= freq_min_hz < freq_max_hz`) formatted into `core.freqrange`
- Valid foreign-key codes against live `makara.organizations`, `makara.call_types`, `core.annotation_labels`, `makara.analysis_granularity_types`, and `core.sharing_scopes`
- Valid `recording_channel_id` and `procedure_id`

Once rows show green **`READY`** badges:
- Click **Download Standardized CSV** to save a clean, schema-compliant CSV file for sharing or archival, **and/or**
- Click **Commit Validated Rows to `nmfs_annotation_db`** to insert the rows inside a single atomic PostgreSQL transaction (automatically rolling back if any database constraint fails).
