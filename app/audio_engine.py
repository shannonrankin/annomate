"""
Bioacoustic Audio & Spectrogram Engine for Annomate.

Supports:
- Google Cloud Storage (gs://...) byte-range slicing for uncompressed PCM (.wav, .x.wav)
- Cached GCS object streaming via soundfile (libsndfile) for .flac, .x.flac, .aif, .aiff, .wav
- HARP .x.wav and .x.flac multi-subfile addressing (translating byte_loc offsets to sample indices
  per Triton's xwav_read specification)
- Customizable STFT spectrogram generation + normalized WAV snippet encoding for browser playback
- Clearly labeled synthetic bioacoustic FM-call fallback when offline or unauthenticated
"""

from __future__ import annotations

import base64
import hashlib
import io
import math
import subprocess
import time
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np
from scipy import signal
import soundfile as sf

from .config import CACHE_DIR, get_settings
from .db import is_demo_mode_active

GCS_AUDIO_CACHE = CACHE_DIR / "gcs_audio"
GCS_AUDIO_CACHE.mkdir(parents=True, exist_ok=True)

_gcs_client = None
_gcs_client_ts: float = 0.0
_gcs_error: Optional[str] = None


def get_gcs_client(force_refresh: bool = False):
    """
    Initialize Google Cloud Storage client using either:
    1. Standard Application Default Credentials (`gcloud auth application-default login`), or
    2. Active `gcloud` CLI session token (`gcloud auth login` -> `gcloud auth print-access-token`).
    """
    global _gcs_client, _gcs_client_ts, _gcs_error
    now = time.time()
    if not force_refresh and _gcs_client is not None and (now - _gcs_client_ts) < 1500:
        return _gcs_client

    settings = get_settings()
    try:
        from google.cloud import storage

        if settings.gcp_project:
            _gcs_client = storage.Client(project=settings.gcp_project)
        else:
            _gcs_client = storage.Client()
        _gcs_client_ts = now
        _gcs_error = None
        return _gcs_client
    except Exception as adc_exc:
        # Try gcloud CLI user session token fallback
        gcloud_candidates = [
            "gcloud",
            str(Path.home() / "AppData" / "Local" / "Google" / "Cloud SDK" / "google-cloud-sdk" / "bin" / "gcloud.cmd"),
        ]
        for gcloud_bin in gcloud_candidates:
            try:
                tok = subprocess.check_output(
                    [gcloud_bin, "auth", "print-access-token"],
                    text=True,
                    stderr=subprocess.PIPE,
                    timeout=6,
                ).strip()
                if tok:
                    from google.cloud import storage
                    from google.oauth2.credentials import Credentials

                    creds = Credentials(token=tok)
                    _gcs_client = storage.Client(
                        project=settings.gcp_project or "noaa-pam-client",
                        credentials=creds,
                    )
                    _gcs_client_ts = now
                    _gcs_error = None
                    return _gcs_client
            except Exception:
                continue

        _gcs_error = (
            "GCS credentials need sign-in (`gcloud auth login` or `gcloud auth application-default login`). "
            f"Detail: {adc_exc}"
        )
        return None


def parse_gs_uri(gs_uri: str) -> Tuple[str, str]:
    if not gs_uri or not gs_uri.startswith("gs://"):
        raise ValueError(f"Invalid GCS URI: {gs_uri}")
    without_scheme = gs_uri[5:]
    slash_idx = without_scheme.find("/")
    if slash_idx <= 0:
        raise ValueError(f"GCS URI missing object path: {gs_uri}")
    return without_scheme[:slash_idx], without_scheme[slash_idx + 1 :]


def _decode_pcm_bytes(
    raw_bytes: bytes,
    bit_depth: int,
    num_channels: int,
    target_channel: int,
    big_endian: bool = False,
) -> np.ndarray:
    """Decode raw little-endian (WAV/XWAV) or big-endian (AIFF/AIF) PCM bytes into float32 mono array."""
    num_channels = max(1, int(num_channels or 1))
    target_channel = min(max(0, int(target_channel or 0)), num_channels - 1)
    endian = ">" if big_endian else "<"

    if bit_depth == 16:
        frame_bytes = 2 * num_channels
        usable = (len(raw_bytes) // frame_bytes) * frame_bytes
        arr = np.frombuffer(raw_bytes[:usable], dtype=f"{endian}i2").astype(np.float32) / 32768.0
        return arr.reshape(-1, num_channels)[:, target_channel]
    elif bit_depth == 32:
        frame_bytes = 4 * num_channels
        usable = (len(raw_bytes) // frame_bytes) * frame_bytes
        arr = np.frombuffer(raw_bytes[:usable], dtype=f"{endian}i4").astype(np.float32) / 2147483648.0
        return arr.reshape(-1, num_channels)[:, target_channel]
    elif bit_depth == 24:
        frame_bytes = 3 * num_channels
        n_frames = len(raw_bytes) // frame_bytes
        usable = n_frames * frame_bytes
        b = np.frombuffer(raw_bytes[:usable], dtype=np.uint8).reshape(n_frames, num_channels, 3)
        ch_b = b[:, target_channel, :]
        if big_endian:
            signed = (
                (ch_b[:, 0].astype(np.int32) << 16)
                | (ch_b[:, 1].astype(np.int32) << 8)
                | ch_b[:, 2].astype(np.int32)
            )
        else:
            signed = (
                ch_b[:, 0].astype(np.int32)
                | (ch_b[:, 1].astype(np.int32) << 8)
                | (ch_b[:, 2].astype(np.int32) << 16)
            )
        signed = np.where(signed & 0x800000, signed - 0x1000000, signed)
        return signed.astype(np.float32) / 8388608.0
    elif bit_depth == 8:
        frame_bytes = 1 * num_channels
        usable = (len(raw_bytes) // frame_bytes) * frame_bytes
        arr = (np.frombuffer(raw_bytes[:usable], dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
        return arr.reshape(-1, num_channels)[:, target_channel]
    else:
        raise ValueError(f"Unsupported PCM bit depth: {bit_depth}")


def _inspect_magic_bytes(path: Path) -> str:
    """Identify container from magic bytes rather than trusting filename extension."""
    with open(path, "rb") as f:
        magic = f.read(4)
    if magic == b"fLaC":
        return "flac"
    if magic == b"RIFF":
        return "wav"
    if magic == b"FORM":
        return "aiff"
    return "unknown"


def _parse_iso_utc(val: Any) -> Optional[datetime]:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
    s = str(val).strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def synthesize_bioacoustic_call(
    sample_rate_hz: float,
    total_duration_s: float,
    call_offset_s: float,
    call_duration_s: float,
    freq_min_hz: float,
    freq_max_hz: float,
    seed: int = 42,
) -> np.ndarray:
    """
    Generate a realistic synthetic bioacoustic call (FM sweep + subtle harmonics + ocean ambient pink noise)
    ONLY used as an explicitly badged preview fallback when GCS audio is unreachable.
    """
    rng = np.random.default_rng(seed)
    sr = float(sample_rate_hz or 2000.0)
    n_samples = max(256, int(round(total_duration_s * sr)))
    t = np.arange(n_samples, dtype=np.float32) / sr

    # Ambient 1/f ocean background noise
    white = rng.standard_normal(n_samples).astype(np.float32)
    freqs = np.fft.rfftfreq(n_samples, d=1.0 / sr)
    spec = np.fft.rfft(white)
    pink_scale = 1.0 / np.maximum(np.sqrt(freqs), 1.0)
    ambient = np.fft.irfft(spec * pink_scale, n=n_samples).astype(np.float32)
    ambient = 0.08 * ambient / (np.max(np.abs(ambient)) + 1e-6)

    # Bioacoustic FM contour (e.g. Right Whale upcall concave upsweep)
    call_start = max(0.0, call_offset_s)
    call_end = min(total_duration_s, call_start + max(0.15, call_duration_s))
    mask = (t >= call_start) & (t <= call_end)
    if np.any(mask):
        tau = np.clip((t[mask] - call_start) / max(call_end - call_start, 1e-4), 0.0, 1.0)
        nyq = 0.46 * sr
        f0 = min(max(20.0, freq_min_hz or 85.0), nyq * 0.7)
        f1 = min(max(f0 + 30.0, freq_max_hz or 200.0), nyq)
        # Concave upward sweep characteristic of mysticete contact calls
        inst_freq = f0 + (f1 - f0) * (0.35 * tau + 0.65 * (tau ** 2.1))
        phase = 2.0 * np.pi * np.cumsum(inst_freq) / sr
        env = np.maximum(0.0, np.sin(np.pi * tau)) ** 0.65
        call_sig = 0.65 * env * np.sin(phase)
        if 2.0 * f1 < nyq:
            call_sig += 0.18 * env * np.sin(2.0 * phase + 0.4)
        ambient[mask] += call_sig.astype(np.float32)

    ambient = np.nan_to_num(ambient, nan=0.0, posinf=0.0, neginf=0.0)
    peak = np.max(np.abs(ambient))
    if peak > 0.98:
        ambient = ambient * (0.95 / peak)
    return ambient


def encode_wav_base64(samples: np.ndarray, sample_rate_hz: float, normalize: bool = True) -> str:
    """
    Encode mono float32 samples into a standard 16-bit PCM WAV data URI payload.
    Automatically upsamples low-sample-rate PAM streams (e.g., 2,000 Hz MARU recordings)
    to >= 8,000 Hz via polyphase filtering so Chromium/HTML5 <audio> plays them natively
    at true 1x pitch and duration.
    """
    arr = np.nan_to_num(np.asarray(samples, dtype=np.float32), nan=0.0, posinf=0.0, neginf=0.0)
    if arr.size == 0:
        arr = np.zeros(256, dtype=np.float32)
    sr_in = max(200, int(round(sample_rate_hz or 2000.0)))
    sr_out = sr_in
    if sr_in < 8000:
        up_factor = int(math.ceil(8000.0 / sr_in))
        arr = signal.resample_poly(arr, up=up_factor, down=1).astype(np.float32)
        sr_out = sr_in * up_factor

    arr = arr - np.mean(arr)
    if normalize:
        peak = float(np.max(np.abs(arr)))
        if peak > 1e-6:
            arr = arr * (0.90 / peak)
    pcm16 = np.clip(arr * 32767.0, -32768, 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr_out)
        wf.writeframes(pcm16.tobytes())
    return base64.b64encode(buf.getvalue()).decode("ascii")


def fetch_audio_window(
    meta: Dict[str, Any],
    padding_sec: float = 2.5,
) -> Dict[str, Any]:
    """
    Retrieve the audio waveform surrounding an annotation.

    Tries:
    1. Exact GCS byte-range download when `data_byte_offset`, `bit_depth`, `sample_rate_hz`,
       and uncompressed WAV/XWAV format are available.
    2. Cached GCS container download + `soundfile` frame seek (supporting `.flac`, `.x.flac`,
       `.aif`, `.aiff`, `.wav`, and multi-subfile HARP `.x.flac` via `first_seg_byte_offset`).
    3. Explicitly badged synthetic bioacoustic preview fallback if GCS is unreachable.
    """
    start_dt = _parse_iso_utc(meta.get("start_time_utc"))
    end_dt = _parse_iso_utc(meta.get("end_time_utc"))
    seg_start_dt = _parse_iso_utc(meta.get("seg_start_utc"))
    seg_end_dt = _parse_iso_utc(meta.get("seg_end_utc"))

    call_dur = 1.25
    if start_dt and end_dt:
        call_dur = max(0.05, (end_dt - start_dt).total_seconds())

    sr = float(meta.get("sample_rate_hz") or meta.get("recording_sample_rate_hz") or 2000.0)
    bit_depth = int(meta.get("bit_depth") or 16)
    num_channels = int(meta.get("container_channels") or 1)
    file_channel = int(meta.get("file_channel") or 0)
    gs_uri = str(meta.get("obj_gsuri") or "").strip()
    fmt = str(meta.get("format") or "").lower().lstrip(".")
    data_byte_offset = meta.get("data_byte_offset")
    data_byte_length = meta.get("data_byte_length")
    first_seg_byte_offset = meta.get("first_seg_byte_offset")

    fmin_ann = float(meta.get("freq_min_hz") or 80.0)
    fmax_ann = float(meta.get("freq_max_hz") or min(sr * 0.45, 250.0))

    # Compute target read window relative to segment start
    if start_dt and end_dt and seg_start_dt:
        seg_dur = (
            (seg_end_dt - seg_start_dt).total_seconds()
            if seg_end_dt
            else float(meta.get("seg_duration_secs") or 3600.0)
        )
        call_rel_start = (start_dt - seg_start_dt).total_seconds()
        call_rel_end = (end_dt - seg_start_dt).total_seconds()
        win_rel_start = max(0.0, call_rel_start - padding_sec)
        win_rel_end = min(max(seg_dur, call_rel_end), call_rel_end + padding_sec)
        if win_rel_end <= win_rel_start:
            win_rel_end = win_rel_start + call_dur + 2 * padding_sec
        call_offset_in_window = max(0.0, call_rel_start - win_rel_start)
    else:
        win_rel_start = 0.0
        win_rel_end = call_dur + 2.0 * padding_sec
        call_offset_in_window = padding_sec

    win_duration_s = max(0.25, min(60.0, win_rel_end - win_rel_start))
    start_frame = max(0, int(round(win_rel_start * sr)))
    n_frames = max(128, int(round(win_duration_s * sr)))

    gcs_attempt_error: Optional[str] = None
    is_demo_row = is_demo_mode_active() or gs_uri.startswith("gs://demo-noaa-pam/") or bool(meta.get("demo_synthetic_playable"))

    if is_demo_row:
        raw_id = meta.get("annotation_id")
        try:
            seed_val = int(float(raw_id)) if raw_id is not None and str(raw_id).strip() != "" else 42
        except Exception:
            seed_val = 42
        synth_samples = synthesize_bioacoustic_call(
            sample_rate_hz=sr,
            total_duration_s=win_duration_s,
            call_offset_s=call_offset_in_window,
            call_duration_s=call_dur,
            freq_min_hz=fmin_ann,
            freq_max_hz=fmax_ann,
            seed=seed_val,
        )
        return {
            "samples": synth_samples,
            "sample_rate_hz": sr,
            "duration_s": float(synth_samples.size / sr),
            "call_offset_s": call_offset_in_window,
            "call_duration_s": call_dur,
            "source_status": "live_demo_synthetic",
            "source_badge": "DEMO MODE · PLAYABLE SYNTHETIC AUDIO",
            "gs_uri": gs_uri or "gs://demo-noaa-pam/synthetic_preview.wav",
            "byte_range": None,
            "error": None,
        }

    if gs_uri.startswith("gs://"):
        client = get_gcs_client()
        if client is not None:
            try:
                bucket_name, blob_name = parse_gs_uri(gs_uri)
                bucket = client.bucket(bucket_name)
                blob = bucket.blob(blob_name)

                # Strategy A: Direct GCS HTTP Range read for uncompressed PCM (.wav, .x.wav, .aif, .aiff)
                is_aiff = fmt in ("aif", "aiff") or gs_uri.lower().endswith((".aif", ".aiff"))
                is_uncompressed_wav = fmt in ("wav", "xwav", "x.wav") or (
                    gs_uri.lower().endswith((".wav", ".x.wav")) and "flac" not in fmt
                )
                if (
                    (is_uncompressed_wav or is_aiff)
                    and data_byte_offset is not None
                    and bit_depth in (8, 16, 24, 32)
                    and sr > 0
                ):
                    bytes_per_frame = max(1, num_channels) * (bit_depth // 8)
                    byte_start = int(data_byte_offset) + start_frame * bytes_per_frame
                    max_bytes = n_frames * bytes_per_frame
                    if data_byte_length is not None:
                        seg_end_byte = int(data_byte_offset) + int(data_byte_length)
                        byte_end = min(seg_end_byte - 1, byte_start + max_bytes - 1)
                    else:
                        byte_end = byte_start + max_bytes - 1

                    if byte_end > byte_start:
                        raw_bytes = blob.download_as_bytes(start=byte_start, end=byte_end)
                        samples = _decode_pcm_bytes(
                            raw_bytes, bit_depth, num_channels, file_channel, big_endian=is_aiff
                        )
                        if samples.size > 32:
                            return {
                                "samples": samples,
                                "sample_rate_hz": sr,
                                "duration_s": float(samples.size / sr),
                                "call_offset_s": call_offset_in_window,
                                "call_duration_s": call_dur,
                                "source_status": "live_gcs_range",
                                "source_badge": f"LIVE GCS BYTE-RANGE ({'AIFF' if is_aiff else 'WAV'})",
                                "gs_uri": gs_uri,
                                "byte_range": [byte_start, byte_end],
                                "error": None,
                            }

                # Strategy B: Download container to local cache & slice via soundfile (FLAC, X.FLAC, AIF, WAV)
                ext = Path(blob_name).suffix or ".audio"
                cache_key = hashlib.sha256(gs_uri.encode("utf-8")).hexdigest()[:20]
                local_path = GCS_AUDIO_CACHE / f"{cache_key}{ext}"
                if not local_path.exists() or local_path.stat().st_size == 0:
                    blob.download_to_filename(str(local_path))

                kind = _inspect_magic_bytes(local_path)
                with sf.SoundFile(str(local_path), mode="r") as snd:
                    actual_sr = float(snd.samplerate) if fmt not in ("xwav", "x.wav", "xflac", "x.flac") else float(sr or snd.samplerate)
                    n_ch = snd.channels
                    seek_frame = int(round(win_rel_start * actual_sr))

                    # Handle multi-subfile .x.flac sample addressing per Triton xwav_read spec
                    if kind == "flac" and data_byte_offset is not None and first_seg_byte_offset is not None:
                        bytes_per_slice = max(1, n_ch) * max(1, bit_depth // 8)
                        subfile_sample_offset = max(0, (int(data_byte_offset) - int(first_seg_byte_offset)) // bytes_per_slice)
                        seek_frame += subfile_sample_offset

                    seek_frame = min(max(0, seek_frame), max(0, snd.frames - 1))
                    read_frames = min(int(round(win_duration_s * actual_sr)), snd.frames - seek_frame)
                    snd.seek(seek_frame)
                    data = snd.read(read_frames, dtype="float32", always_2d=True)
                    ch_idx = min(max(0, file_channel), n_ch - 1)
                    samples = data[:, ch_idx]

                    return {
                        "samples": samples,
                        "sample_rate_hz": actual_sr,
                        "duration_s": float(samples.size / actual_sr),
                        "call_offset_s": call_offset_in_window,
                        "call_duration_s": call_dur,
                        "source_status": "live_gcs_container",
                        "source_badge": f"LIVE GCS ({kind.upper()})",
                        "gs_uri": gs_uri,
                        "byte_range": None,
                        "error": None,
                    }
            except Exception as exc:
                gcs_attempt_error = str(exc)
        else:
            gcs_attempt_error = _gcs_error or "Google Cloud Storage client unavailable"
    else:
        gcs_attempt_error = "No gs:// acoustic file URI linked to this time window"

    # Strategy C: Clearly badged synthetic preview so spectrogram UI remains interactive
    raw_id = meta.get("annotation_id")
    try:
        seed_val = int(float(raw_id)) if raw_id is not None and str(raw_id).strip() != "" else 42
    except Exception:
        seed_val = 42
    synth_samples = synthesize_bioacoustic_call(
        sample_rate_hz=sr,
        total_duration_s=win_duration_s,
        call_offset_s=call_offset_in_window,
        call_duration_s=call_dur,
        freq_min_hz=fmin_ann,
        freq_max_hz=fmax_ann,
        seed=seed_val,
    )
    return {
        "samples": synth_samples,
        "sample_rate_hz": sr,
        "duration_s": float(synth_samples.size / sr),
        "call_offset_s": call_offset_in_window,
        "call_duration_s": call_dur,
        "source_status": "synthetic_fallback",
        "source_badge": "SYNTHETIC CALL PREVIEW",
        "gs_uri": gs_uri,
        "byte_range": None,
        "error": gcs_attempt_error,
    }


def compute_spectrogram_payload(
    meta: Dict[str, Any],
    nfft: int = 256,
    overlap_pct: float = 85.0,
    window_type: str = "hann",
    fmin_hz: Optional[float] = None,
    fmax_hz: Optional[float] = None,
    padding_sec: float = 2.5,
    db_range: float = 55.0,
) -> Dict[str, Any]:
    """
    Fetch audio window and compute a high-resolution STFT spectrogram + base64 WAV audio.
    """
    audio_info = fetch_audio_window(meta, padding_sec=padding_sec)
    samples: np.ndarray = audio_info["samples"]
    sr: float = audio_info["sample_rate_hz"]

    # Ensure NFFT fits comfortably inside the waveform
    max_reasonable_nfft = max(64, 2 ** int(math.floor(math.log2(max(128, samples.size // 4)))))
    eff_nfft = min(max(64, int(nfft)), max_reasonable_nfft, 8192)
    overlap_frac = min(0.95, max(0.10, float(overlap_pct) / 100.0))
    noverlap = min(eff_nfft - 1, int(round(eff_nfft * overlap_frac)))

    win_name = window_type.lower().strip()
    if win_name == "kaiser":
        win_arg: Any = ("kaiser", 8.0)
    elif win_name in ("hann", "hamming", "blackman", "bartlett", "boxcar"):
        win_arg = win_name
    else:
        win_arg = "hann"

    # Detrend DC offset prior to STFT
    clean = samples - np.mean(samples)
    freqs, times, sxx = signal.spectrogram(
        clean,
        fs=sr,
        window=win_arg,
        nperseg=eff_nfft,
        noverlap=noverlap,
        scaling="density",
        mode="psd",
    )

    nyquist = sr / 2.0
    eff_fmin = max(0.0, float(fmin_hz) if fmin_hz is not None else 0.0)
    eff_fmax = min(nyquist, float(fmax_hz) if (fmax_hz is not None and fmax_hz > 0) else nyquist)
    if eff_fmax <= eff_fmin:
        eff_fmin, eff_fmax = 0.0, nyquist

    f_mask = (freqs >= eff_fmin) & (freqs <= eff_fmax)
    if np.sum(f_mask) < 4:
        f_mask = np.ones_like(freqs, dtype=bool)

    freqs_crop = freqs[f_mask]
    sxx_crop = sxx[f_mask, :]

    power_db = 10.0 * np.log10(np.maximum(sxx_crop, 1e-18))
    p99 = float(np.percentile(power_db, 99.2))
    z_max = round(p99, 2)
    z_min = round(p99 - max(20.0, float(db_range)), 2)

    # Downsample time columns slightly if > 650 columns so JSON payload stays snappy & crisp
    if power_db.shape[1] > 650:
        step = int(math.ceil(power_db.shape[1] / 650))
        power_db = power_db[:, ::step]
        times = times[::step]

    wav_b64 = encode_wav_base64(samples, sr, normalize=True)

    # Downsampled waveform envelope for synchronized time-series strip
    wf_points = min(600, samples.size)
    idx = np.linspace(0, samples.size - 1, wf_points, dtype=int)
    wf_t = (idx / sr).round(4).tolist()
    wf_y = samples[idx].round(4).tolist()

    return {
        "times_s": np.round(times, 4).tolist(),
        "freqs_hz": np.round(freqs_crop, 2).tolist(),
        "power_db": np.round(power_db, 2).tolist(),
        "z_min_db": z_min,
        "z_max_db": z_max,
        "sample_rate_hz": sr,
        "nyquist_hz": nyquist,
        "effective_nfft": eff_nfft,
        "overlap_pct": overlap_pct,
        "window_type": win_name,
        "duration_s": round(audio_info["duration_s"], 4),
        "call_box": {
            "t0": round(audio_info["call_offset_s"], 4),
            "t1": round(audio_info["call_offset_s"] + audio_info["call_duration_s"], 4),
            "f0": meta.get("freq_min_hz"),
            "f1": meta.get("freq_max_hz"),
            "polygon": meta.get("polygon"),
        },
        "waveform": {"t": wf_t, "y": wf_y},
        "audio_wav_b64": wav_b64,
        "source_status": audio_info["source_status"],
        "source_badge": audio_info["source_badge"],
        "gs_uri": audio_info["gs_uri"],
        "byte_range": audio_info["byte_range"],
        "gcs_note": audio_info["error"],
    }
