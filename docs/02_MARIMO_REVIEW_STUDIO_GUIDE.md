# Component 02 · Marimo Review Studio & Spectrogram Guide

The **Marimo Review Studio** ([notebooks/review_studio.py](file:///c:/Users/shannon.rankin/Documents/GitHub/annomate/notebooks/review_studio.py)) provides a reactive Python notebook environment for reviewing acoustic detections, subsetting large datasets, exploring visualizations, inspecting call spectrograms/audio, and chatting with your data.

---

## 1. Opening the Review Studio

- **From Annomate Web UI:** Run a query in **01 · Find & Filter Data** and click **Review in Marimo Notebook →** (or switch to Tab **02 · Review Data** and click **Stage Dataset & Launch Marimo Studio**).
- **Embedded vs. Full-Tab View:** You can use the studio directly inside Tab 02 or click **Open Notebook in Full Browser Tab ↗** (`http://127.0.0.1:2718`).
- **Developer / Code Edit Mode:** By default, Annomate launches Marimo in clean reactive App mode (`marimo run`). If you want to inspect or add custom Python cells interactively, run:
  ```powershell
  .\.venv\Scripts\python.exe -m marimo edit .\notebooks\review_studio.py --port 2718
  ```

---

## 2. Dataset Source & Reproducible Random Subsetting

1. **Dataset Source Dropdown:** Switch at any time between:
   - *Staged Dataset from Annomate Find & Filter* (`data/review_session/active_review.csv`)
   - *Live DB · DCLDE_2013 Right Whale Upcalls (NEFSC)*
   - *Upload Custom CSV File* (drag and drop any local `.csv` or `.tsv`)
2. **Reproducible Random Subsetting Prompt:**
   - When reviewing thousands of calls, select **Random Subset**, choose your **Subset Size (N calls)** on the slider, optionally select **Stratification** (e.g., *Stratify by `label_code`* or *`call_type_code`* so rare classes are preserved proportionally), and set a **Random Seed** (default `42`) so colleagues can reproduce the exact same sample.
   - All downstream KPI cards, charts, tables, spectrograms, and chatbot summaries update reactively whenever you adjust the subset!

---

## 3. Exploratory Bioacoustic, Bathymetric & R `PAMpal` / `PAMscapes` Plots

Four dark-themed interactive Plotly charts summarize your active subset:
1. **Diel & Daily Acoustic Call Density:** Heatmap of UTC Hour of Day (0–23) × Date to spot nocturnal/diurnal calling patterns and peak bouts.
2. **Call Duration vs. Center Frequency & Bandwidth:** Bubble scatter plot colored by verification label (`YES`, `MAYBE`, `NO`, `UNVERIFIED`) to identify acoustic outliers or false positives.
3. **Annotations by Call Type & Verification Label:** Stacked bar summary of class balance.
4. **Hydrophone Coordinates on NOAA ETOPO 2022 Bathymetry/Topography:** Overlays high-contrast Solar Yellow (`#FACC15`) hydrophone markers atop oceanic bathymetric contours and coastal topography.

Directly beneath the interactive charts, Annomate executes your local R **`PAMscapes` / `PAMpal`** installation (NOAA SWFSC FOSSA suite) to render three publication-ready acoustic plots with adjustable temporal bins:
- **`plotDetectionBoxplot`** (e.g., `hour/day`, `hour/week`, `day/week`, `day/month`)
- **`plotAcousticScene`** (auto-scaled or `15min` / `1hour` / `1day` presence across each call type's frequency band)
- **`plotPolarDetections`** (circular 24-hour diel or 12-month seasonal detection rose plot)

---

## 4. Embedded Spectrogram, Synthetic Reference Call & Cloud Audio Inspector

Select any row in the **Interactive Annotation Review Table**—or pick from the **Focal Call to Inspect** dropdown (including **`★ SYNTHETIC REFERENCE CALL`** at the very top of the dropdown anytime you want an unvalidated reference FM call with playable synthetic audio)—to inspect its acoustic signal:

- **Direct Link to Original Cloud Audio:** Displays the authoritative `gs://` URI (`obj_gsuri`), sample rate, channel index, and exact `data_byte_offset`, with a clickable link to Google Cloud Storage.
- **How Audio Is Fetched:**
  - For uncompressed `.wav`, `.x.wav`, and big-endian MARU `.aif`/`.aiff` containers, Annomate performs an **HTTP byte-range request** to GCS—downloading only the few kilobytes surrounding the call rather than the entire multi-megabyte file.
  - For compressed `.flac` and multi-subfile HARP `.x.flac` containers, Annomate caches the container locally and seeks to the exact sample frame (translating HARP `byte_loc` offsets per Triton's `xwav_read` specification).
  - If `gcloud` is not currently authenticated, an amber **`SYNTHETIC CALL PREVIEW`** badge appears so you can still test spectrogram controls while offline.
- **Tunable Spectrogram Parameters:**
  - **FFT Window (`NFFT`):** `128`, `256` *(balanced default for 2 kHz right whale data)*, `512`, `1024`, `2048`. Larger `NFFT` sharpens frequency resolution; smaller `NFFT` sharpens time resolution.
  - **Overlap (%):** `50%` – `95%` (default `85%` for smooth temporal contours).
  - **Window Function:** `Hann`, `Hamming`, `Blackman`, or `Kaiser (β=8)`.
  - **Context Padding (±s):** `0.5s` – `10.0s` of surrounding ambient audio before and after the call's bounding box.
  - **Max Freq Display (Hz):** Crop the upper frequency axis to zoom in on low-frequency mysticete calls.
  - **Dynamic Range (dB) & Colormap:** Adjust contrast (`30`–`85 dB` below 99th-percentile peak) and choose between `Magma`, `Viridis`, `Cividis`, `Inferno`, `YlGnBu`, or `Greys`.
- **Listen to the Call:** Press play on the embedded HTML5 audio player right next to the spectrogram metadata bar.

---

## 5. Embedded Bioacoustics Chatbot & Saving Subsets for Export

- **Data Explorer Chatbot:** Scroll to the bottom of the notebook and click one of the starter prompts (or type your own question about frequency quartiles, call durations, diel peak hours, or GCS audio coverage). Without an API key, it runs deterministic pandas statistical analyses on your active subset; with `GEMINI_API_KEY` set, it supports open-ended conversational exploration.
- **Stage for Export:** Select specific rows in the review table (or leave unselected to take the entire subset) and click **Save Reviewed Subset to Annomate Export Studio**. Then switch to **03 · Export Data** and choose *Reviewed Subset from Marimo*!
