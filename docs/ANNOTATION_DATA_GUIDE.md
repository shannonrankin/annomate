# Understanding Bioacoustic Annotation Data in Annomate (`nmfs_annotation_db`)

**Annomate** connects acoustic detections and analyst labels to authoritative deployment metadata (**Makara**) and physical cloud recordings stored in **Google Cloud Storage (GCS)**. Because passive acoustic monitoring (PAM) spans wildly different instruments—from continuous WAV recorders to duty-cycled HARP `.x.wav` / `.x.flac` containers, multi-channel MARUs, and multi-file AURAL streams—the underlying PostgreSQL/PostGIS database separates **scientific provenance**, **logical hydrophone streams**, and **physical container files**.

> **Interactive ERD & System Diagram:** When signed in with your NOAA Google identity, you can explore the full live Entity-Relationship Diagram and Makara–GCS sync architecture at:  
> **https://anndb-frontend-app-948464146942.us-east4.run.app/**

---

## 1. The Three Database Schemas

| Schema | Role | Key Tables |
| :--- | :--- | :--- |
| **`makara`** | Authoritative high-level PAM metadata synced from Makara | `organizations`, `deployments`, `recordings` (`recording_uri`), `sound_sources`, `sound_groups`, `call_types`, `analysis_granularity_types`, `tracks`, `track_positions` |
| **`core`** | Physical cloud audio inventory, logical channels, effort/sampling bins, procedures, and annotations | `acoustic_files`, `audio_segments`, `recording_channels`, `analyses`, `procedures`, `effort`, `bins`, `bins_effort`, `effort_procedures`, `annotations`, `annotation_labels`, `sharing_scopes` |
| **`reconcile`** | Automated GCS crawler observability & data integrity checks | `worker_runs`, `recording_discovery_state`, `recording_object_observations`, `recording_status`, `findings` |

---

## 2. Why Audio Metadata Is Split Across Four Tables

A frequent question when writing SQL against `nmfs_annotation_db` is: *"Why doesn't `core.annotations` link directly to an audio filename?"* Three real-world bioacoustics edge cases drive this design:

1. **`core.acoustic_files` vs. `core.audio_segments` (Container Subfiles):**  
   Instruments like **HARPs** store dozens of duty-cycled raw disk writes inside a single `.x.wav` or lossless `.x.flac` container (`flac --keep-foreign-metadata`, which preserves the 64+ byte RIFF `harp` header chunk byte-for-byte). One row in `core.acoustic_files` (`obj_gsuri`) unpacks into many `(subfile_index, file_channel)` rows in `core.audio_segments`, each carrying its own exact `tstzrange`, `sample_rate_hz`, `data_byte_offset`, and `data_byte_length`.
2. **`makara.recordings` vs. `core.recording_channels` (Per-Channel Streams):**  
   An acoustic call annotation normally applies to a single hydrophone channel (`channel`, zero-based). In multi-channel arrays such as **NEFSC MARUs**, individual channels can even correspond to distinct deployments.
3. **`core.recording_channels` vs. `core.audio_segments` (Calls Spanning File Boundaries):**  
   Continuous recorders (such as **AFSC AURALs**) split audio arbitrarily at file boundaries, meaning a single whale call or bout can start at the end of File A and finish at the beginning of File B. By linking `core.annotations` **only** to `recording_channel_id` and indexing `(recording_channel_id, tstzrange)` with PostgreSQL **GiST range indexes**, a simple temporal overlap join (`seg.tstzrange && ann.tstzrange`) cleanly retrieves one—or multiple—underlying `audio_segments` and `gs://` URIs in milliseconds.

---

## 3. Anatomy of a Standardized Annotation (`core.annotations`)

Every standardized annotation in `core.annotations` captures **where/when**, **what**, **how**, and **who can access it**:

- **`recording_channel_id`** *(required)*: The sole relational link back to the logical hydrophone stream (`core.recording_channels` → `makara.recordings` → `makara.deployments`) and, via `tstzrange &&`, to `core.audio_segments` → `core.acoustic_files`.
- **`tstzrange`** *(required, GiST-indexed)*: PostgreSQL timestamp-with-timezone range `[start_utc, end_utc)`. In Annomate's UI and CSV exports, this is surfaced as familiar `start_time_utc` (`lower(tstzrange)`) and `end_time_utc` (`upper(tstzrange)`), while generated SQL preserves native `tstzrange` operators (`&&` for overlap, `<@` for containment) so queries scale to millions of rows.
- **`freqrange`** *(optional)*: Custom `core.freqrange` (`[min_hz, max_hz]`), surfaced in tables/exports as `freq_min_hz` and `freq_max_hz`.
- **`polygon`** *(optional JSONB)*: 2D time-frequency contour stored as `[[offset_sec, freq_hz], ...]` (minimum 3 vertices, relative to `lower(tstzrange)`), while `tstzrange` and `freqrange` store the bounding box.
- **`organization_code`** *(required)*: Denormalized steward organization (e.g., `NEFSC`, `SWFSC`, `AFSC`, `PIFSC`, `SEFSC`). **Must always be retained** to support declarative list partitioning and organization-level access control at scale.
- **`call_type_code`** *(required)*: Standardized call code from `makara.call_types` (linked to species in `makara.sound_sources`).
- **`label_code`** *(required)*: Controlled detection verification state (`core.annotation_labels`):
  - `YES` (1): Direct human-verified positive detection
  - `NO` (0): Direct human-verified negative / false positive
  - `MAYBE` (2): Direct human-verified uncertain / possible detection
  - `PROTOCOL_YES` / `PROTOCOL_NO` / `PROTOCOL_MAYBE`: Inferred by subsampling or protocol rules
  - `UNVERIFIED` (99): Raw detector or unreviewed candidate output
- **`granularity_code`** *(required)*: Analysis granularity from `makara.analysis_granularity_types` (e.g., `CALL`, `BINNED`, `ENCOUNTER`).
- **`sharing_code`** *(required, default `ORG_INTERNAL`)*: Data release scope (`ORG_INTERNAL`, `NOAA_INTERNAL`, `PACM_SUMMARY_ONLY`, `PUBLIC_DATA_ONLY`, `PUBLIC`).
- **`procedure_id`** *(required)*: Links the annotation to `core.procedures` → `core.analyses` (scientific study, protocol, and analyst list).
- **`probability` / `confidence` / `analyst`**: Optional detector score, analyst confidence, and Makara-formatted analyst identifier (`FIRSTINITIAL+LAST`, e.g., `GDAVIS`, `SRANKIN`).

---

## 4. Effort, Sampling Bins & Implied Negatives

Knowing where calls were **not** heard requires knowing where analysts or detectors actually looked:
- **`core.effort` → `core.bins_effort` → `core.bins`**: Defines exact `(recording_channel_id, tstzrange)` windows that were sampled (for example, the **`DCLDE_2013`** North Atlantic right whale upcall competition dataset from NEFSC).
- **`core.effort_procedures`**: Connects a `procedure_id` and `effort_id` for a specific `call_type_code`, recording the review method (`effproc_type_code`) and negative-space assumption (`effproc_assumption_code`, e.g., whether unannotated time inside effort bins implies true absence).

---

## 5. Data Readiness & Troubleshooting Tips

- **GCS Autoclass & Whitelisting:** Because NOAA's GCS archive uses Autoclass storage tiers, the database crawler currently indexes recordings that meet Standard-tier thresholds or are explicitly whitelisted. **If a Makara recording you need does not yet have `core.acoustic_files` / `core.audio_segments` populated, ask Dan to add it to the crawler whitelist.**
- **Checking Integrity (`reconcile` schema):** Asynchronous workers audit temporal containment and file headers, logging issues in `reconcile.findings` (such as `annotation_without_audio_segment` or `inconsistent_core_audio_properties`) and rolling status up into `reconcile.recording_status`.
- **Reviewing Data in Marimo:** After running any search in **Find & Filter**, click **Review in Marimo Studio** to subset large result sets reproducibly, explore interactive diel/frequency/spatial plots, inspect live GCS spectrograms (with customizable FFT window, overlap, colormap, and audio playback), and chat with the dataset.
