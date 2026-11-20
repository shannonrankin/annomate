# Component 03 · Export Studio & Cloud Audio Packaging Guide

The **Export Data** workspace (`http://127.0.0.1:8000/#export`) packages acoustic annotations together with relational **Makara** metadata and authoritative **Google Cloud Storage (`gs://`)** audio pointers for downstream machine learning, call studies, Raven Pro verification, or localization workflows.

---

## 1. Choosing Which Dataset to Export

Under **1. Choose Source Dataset**, select one of three sources:
1. **Current Find & Filter Results:** Exports the dataset from your latest search or custom SQL query in Module 01.
2. **Reviewed Subset from Marimo:** Exports the exact random/stratified subset (or hand-selected table rows) you saved inside the Marimo Review Studio.
3. **Full Effort Dataset from DB:** Queries an entire named effort sample (such as `DCLDE_2013`) directly from `nmfs_annotation_db` up to your chosen row limit.

---

## 2. Guaranteed Cloud Audio Pointers

Every export—regardless of which optional enrichment checkboxes you pick—automatically resolves and attaches the physical audio location columns required to slice the exact call waveform downstream:

| Exported Audio Column | Description |
| :--- | :--- |
| **`obj_gsuri`** | Immutable Google Cloud Storage URI (`gs://bucket/path/file.aif`, `.wav`, `.x.wav`, `.x.flac`) |
| **`recording_uri`** | High-level Makara recording collection URI in GCS |
| **`audio_container_format`** | Physical container format (`wav`, `aif`, `flac`, `x.wav`, `x.flac`) |
| **`audio_file_name`** | Basename of the acoustic container file |
| **`subfile_index`** | Zero-based subfile index inside multi-segment containers (critical for HARP `.x.wav`/`.x.flac`) |
| **`file_channel`** | Channel index inside the physical audio container |
| **`sample_rate_hz` / `bit_depth`** | Observed physical stream sample rate and bit depth |
| **`seg_start_utc` / `seg_end_utc`** | Exact UTC start and end timestamps of the physical audio segment |
| **`call_offset_in_seg_secs`** | Seconds elapsed from `seg_start_utc` to the annotation's `start_time_utc` |
| **`data_byte_offset` / `data_byte_length`** | Byte offset and byte length of the raw audio stream inside the container |

---

## 3. Optional Relational Metadata Enrichment

Toggle any combination of relational tables under **2. Enrich with Additional Relational Metadata**, then click **Refresh Export Schema & Preview** to inspect the resulting columns before downloading:

- **Makara Deployment Metadata:** `deployment_code`, `latitude`, `longitude`, `water_depth_m`, `platform_type_code`, `vessel`, `cruise`.
- **Makara Recording Attributes:** `recording_code`, `makara_sample_rate_khz`, `usable_min_frequency_hz`, `usable_max_frequency_hz`, `calibration_uri`.
- **Species & Call Taxonomy:** `call_type_name`, `species_common_name`, `scientific_name`, `itis_tsn`, `aphia_id`.
- **Study & Procedure Provenance:** `procedure_name`, `analysis_code`, `analysis_name`, `protocol_reference`, `dataset_url`.
- **Reconciliation Audit Status:** `reconciliation_state` (`consistent`, `pending_review`, etc.) and `reconciliation_checked_at`.

---

## 4. Available Download Formats

Click any of the four format cards on the right to generate and download immediately:

1. **`CSV` · Enriched Relational CSV:** Universal comma-separated table suitable for R, Python (`pandas` / `polars`), MATLAB, or Excel.
2. **`RAVEN .TXT` · Raven Pro Selection Table:** Tab-delimited `.selection.txt` table formatted with `Selection`, `View`, 1-based `Channel`, segment-relative `Begin Time (s)` / `End Time (s)`, `Low Freq (Hz)` / `High Freq (Hz)`, `Begin File`, and `GCS Audio URI`—ready to open directly in Cornell Lab's **Raven Pro**.
3. **`JSONL` · ML Training Manifest:** Newline-delimited JSON (`application/x-ndjson`) ideal for streaming PyTorch / TensorFlow bioacoustic dataloaders.
4. **`GCLOUD .PS1` · Cloud Audio Fetch Script:** Generates a ready-to-run PowerShell script executing `gcloud storage cp` for every unique `gs://` audio file referenced by your exported annotations so you can stage local copies in one command.
