# Component 01 · Find & Filter Data Guide

The **Find & Filter Data** workspace (`http://127.0.0.1:8000/#find`) translates plain-English bioacoustic requests (spoken or typed) and structured filter selections into **copy-ready PostgreSQL queries** and **downloadable/reviewable CSV datasets**.

---

## Step-by-Step Workflow

### Step 1: Describe What You Want (Voice, Audio File, or Text)
- **Type a natural-language prompt** in the composer box—for example:
  - *"Find verified positive right whale upcalls in DCLDE_2013 between 50 and 220 Hz with deployment coordinates and GCS audio paths"*
  - *"Annotations only: RW_UPCALL detections limit 300"*
  - *"Random sample of 150 calls from NEFSC with procedure, effort, and byte offsets"*
- **Or click `Speak Query`:** Dictate your request aloud using your microphone. Live words appear as you speak, and if a `GEMINI_API_KEY` is configured in Settings, the raw audio recording is also interpreted multimodally.
- **Or click `Upload Audio Prompt`:** Attach a pre-recorded `.wav`, `.mp3`, or `.webm` voice note.
- **Quick Examples:** Click any of the four preset example chips beneath the prompt box to see how prompts map to SQL and metadata layers.

---

### Step 2: Choose Your Relational Metadata Scope
Passive acoustic workflows sometimes require a lightweight table of call timestamps/frequencies alone, and other times require rich environmental, deployment, and cloud-storage attributes.

- **Click `Annotations Only`** when you want strictly `core.annotations` (`annotation_id`, `organization_code`, `call_type_code`, `label_code`, `granularity_code`, `sharing_code`, `start_time_utc`, `end_time_utc`, `duration_secs`, `freq_min_hz`, `freq_max_hz`, `probability`, `confidence`, `analyst`, `recording_channel_id`, `procedure_id`).
- **Or toggle any combination of the four optional relational join cards:**
  1. **`+ Study, Effort & Procedure`**: Adds `procedure_name`, `analysis_code`, `analysis_name`, and `effort_names` (e.g., `DCLDE_2013`).
  2. **`+ Makara Deployment & Site`**: Adds `call_type_name`, `recording_code`, `sample_rate_khz`, `recording_uri`, `deployment_code`, `latitude`, `longitude`, `water_depth_m`, and `platform_type_code`.
  3. **`+ Cloud Audio & Segments`**: Uses PostgreSQL's GiST temporal overlap index (`s.tstzrange && a.tstzrange`) to resolve the exact `gs://` container (`obj_gsuri`), `format` (`.wav`, `.aif`, `.flac`, `.x.wav`, `.x.flac`), `subfile_index`, `file_channel`, `sample_rate_hz`, `bit_depth`, `call_offset_in_seg_secs`, and `data_byte_offset`.
  4. **`+ Reconciliation Health`**: Adds `reconciliation_state` and `reconciliation_checked_at` from `reconcile.recording_status`.

---

### Step 3: Refine with Structured Filters *(Optional)*
Click the **Structured Filter Refinements** header to expand optional filter controls (collapsed by default to keep the composer clean):
- **Effort Sample** (defaults to `DCLDE_2013` so new users immediately see populated North Atlantic right whale upcalls; select *All Efforts / Unfiltered* to search across the entire database)
- **Organization**, **Call Type**, **Granularity Code** *(open the dropdown and hover over any option—such as `EVENT_CALL`, `EVENT_ENCOUNTER`, or `INTERVAL`—to see a tooltip definition)*, and **Verification Label** (`YES`, `MAYBE`, `NO`, `UNVERIFIED`)
- **Min / Max Frequency (Hz)**, **Max Rows**, and **Randomize SQL Sample** (`ORDER BY random()`)

---

### Step 4: Copy, Hide, or Edit Live-Synced SQL & Choose Your Next Action
1. **Live Auto-Updating SQL Studio:** Directly beneath the prompt card, the **Copy-Ready SQL Query** section automatically regenerates whenever you change your prompt, metadata scope, or filter selections. You can click **Hide SQL** to collapse the query text while keeping the header/buttons visible, **Copy SQL** to paste into R/Python/Positron, or edit the SQL manually and click **Run SQL Query ▶**.
2. **Download or Review:** Once results load, the green **Dataset Ready** banner asks how you want to proceed:
   - **Download CSV File:** Immediately saves `annomate_query_<timestamp>.csv`.
   - **Review in Marimo Notebook →:** Stages the dataset and launches the interactive **Marimo Review Studio**.
   - **Configure Custom Export:** Opens **Export Data** to enrich or convert formats (such as Raven Pro selection tables).
3. **Quick Call Spectrogram Peek:** Click **`🔊 Inspect Call`** on any row in the preview table to slide open an instant spectrogram and audio player without leaving the page!
