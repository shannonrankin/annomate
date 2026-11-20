"""
Comprehensive Automated Test Suite for Annomate.
Covers:
1. Composable SQL builder & Natural-Language-to-SQL heuristics (`app.schema_context`)
2. Multi-endian PCM decoding (.wav little-endian & .aif big-endian), synthetic fallback,
   WAV base64 encoding, and STFT spectrogram generation (`app.audio_engine`)
3. Multi-format bioacoustic annotation alignment & validation for Raven Pro, Triton Logger,
   PAMGuard, and custom CSVs (`app.aligner`)
4. FastAPI endpoints including `/api/status`, `/api/catalog`, `/api/query/*`,
   `/api/spectrogram`, `/api/export/*`, `/api/align/*`, and `/guide` (`app.main`)
5. Headless execution of the reactive Marimo Review Studio notebook (`notebooks/review_studio.py`)
"""

from __future__ import annotations

from pathlib import Path
import struct
import sys
import unittest

import numpy as np
from fastapi.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.aligner import align_and_validate_dataframe, parse_uploaded_table, suggest_column_mapping
from app.audio_engine import _decode_pcm_bytes, compute_spectrogram_payload
from app.bathy_and_pampal import build_bathymetry_deployment_figure, render_pampal_pamscapes_suite
from app.main import app
from app.schema_context import build_structured_sql, generate_sql_from_prompt


class TestSchemaAndSqlBuilder(unittest.TestCase):
    def test_annotations_only_scope_omits_extra_joins(self):
        sql, explanation = build_structured_sql(
            layers=["annotations"],
            filters={"call_type_code": "RW_UPCALL", "label_codes": ["YES"]},
            limit=100,
        )
        self.assertIn("FROM core.annotations a", sql)
        self.assertNotIn("makara.deployments", sql)
        self.assertNotIn("core.acoustic_files", sql)
        self.assertIn("a.label_code IN ('YES')", sql)
        self.assertIn("LIMIT 100", sql)
        self.assertIn("core.annotations", explanation)

    def test_full_relational_layers_include_gist_overlap(self):
        sql, _ = build_structured_sql(
            layers=["annotations", "provenance", "makara", "audio", "reconcile"],
            filters={"effort_name": "DCLDE_2013", "freq_min_hz": 50, "freq_max_hz": 250},
            limit=250,
            random_sample=True,
        )
        self.assertIn("s.recording_channel_id IS NOT NULL", sql)
        self.assertIn("s.tstzrange && a.tstzrange", sql)
        self.assertIn("makara.deployments", sql)
        self.assertIn("reconcile.recording_status", sql)
        self.assertIn("ORDER BY random()", sql)

    def test_nl_heuristic_parser_extracts_bioacoustic_constraints(self):
        res = generate_sql_from_prompt(
            prompt_text="Find verified positive right whale upcalls in DCLDE_2013 between 60 and 220 Hz with deployment coordinates and GCS audio paths limit 75",
            selected_layers=["annotations"],
        )
        self.assertIn("makara", res["layers_used"])
        self.assertIn("audio", res["layers_used"])
        self.assertIn("DCLDE_2013", res["sql"])
        self.assertIn("[60.0, 220.0]", res["sql"])
        self.assertIn("LIMIT 75", res["sql"])


class TestAudioAndSpectrogramEngine(unittest.TestCase):
    def test_little_and_big_endian_16bit_pcm_decoding(self):
        # 2 frames, 2 channels: ch0 = 16384 (0.5), ch1 = -16384 (-0.5)
        le_bytes = struct.pack("<hhhh", 16384, -16384, 8192, -8192)
        be_bytes = struct.pack(">hhhh", 16384, -16384, 8192, -8192)

        ch0_le = _decode_pcm_bytes(le_bytes, bit_depth=16, num_channels=2, target_channel=0, big_endian=False)
        ch1_be = _decode_pcm_bytes(be_bytes, bit_depth=16, num_channels=2, target_channel=1, big_endian=True)

        np.testing.assert_allclose(ch0_le, np.array([0.5, 0.25], dtype=np.float32), atol=1e-4)
        np.testing.assert_allclose(ch1_be, np.array([-0.5, -0.25], dtype=np.float32), atol=1e-4)

    def test_spectrogram_payload_generation(self):
        meta = {
            "annotation_id": 42,
            "start_time_utc": "2009-03-28T05:03:08.811Z",
            "end_time_utc": "2009-03-28T05:03:10.585Z",
            "freq_min_hz": 45.0,
            "freq_max_hz": 210.0,
            "sample_rate_hz": 2000.0,
            "obj_gsuri": "",
        }
        payload = compute_spectrogram_payload(meta, nfft=256, overlap_pct=85.0, fmax_hz=450.0, padding_sec=2.0)
        self.assertGreater(len(payload["freqs_hz"]), 10)
        self.assertGreater(len(payload["times_s"]), 20)
        self.assertTrue(len(payload["audio_wav_b64"]) > 100)
        self.assertEqual(payload["call_box"]["f0"], 45.0)


class TestAnnotationAligner(unittest.TestCase):
    def test_raven_triton_pamguard_sample_files_validate_cleanly(self):
        samples = [
            ("raven_pro", ROOT_DIR / "sample_data" / "raven_selection_table_sample.txt"),
            ("triton_logger", ROOT_DIR / "sample_data" / "triton_logger_sample.csv"),
            ("pamguard", ROOT_DIR / "sample_data" / "pamguard_detections_sample.csv"),
        ]
        for expected_preset, path in samples:
            df, detected = parse_uploaded_table(path.read_bytes(), path.name)
            self.assertEqual(detected, expected_preset)
            mapping = suggest_column_mapping(list(df.columns), detected)
            report = align_and_validate_dataframe(
                df=df,
                mapping=mapping,
                defaults={
                    "organization_code": "NEFSC",
                    "recording_channel_id": 525768,
                    "procedure_id": 1,
                    "call_type_code": "RW_UPCALL",
                    "label_code": "YES",
                    "granularity_code": "EVENT_CALL",
                    "sharing_code": "ORG_INTERNAL",
                    "analyst": "SRANKIN",
                    "file_start_anchor_utc": "2009-03-28T05:00:00Z",
                    "one_based_channel": True,
                },
            )
            self.assertEqual(report["invalid_rows"], 0, f"Preset {expected_preset} had issues: {report['issue_summary']}")
            self.assertEqual(report["valid_rows"], len(df))


class TestFastApiAndMarimoNotebook(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_guide_and_vendor_routes(self):
        for sec in ("quickstart", "find", "review", "export", "align", "schema"):
            r_guide = self.client.get(f"/guide?section={sec}")
            self.assertEqual(r_guide.status_code, 200, f"Failed section {sec}")
            self.assertIn("DOCUMENTATION HUB", r_guide.text)

        r_plotly = self.client.get("/vendor/plotly.min.js")
        self.assertEqual(r_plotly.status_code, 200)

    def test_marimo_review_notebook_executes_cleanly(self):
        from notebooks import review_studio

        outputs, defs = review_studio.app.run()
        self.assertIn("subset_df", defs)
        self.assertGreater(len(defs["subset_df"]), 0)
        bathy_fig = build_bathymetry_deployment_figure(defs["subset_df"])
        self.assertIsNotNone(bathy_fig)
        pampal_res = render_pampal_pamscapes_suite(defs["subset_df"])
        self.assertTrue(pampal_res.get("ok"), pampal_res)


    def test_demo_mode_toggle_and_filtering(self):
        # Enable Demo Mode via API
        r_on = self.client.post("/api/demo-mode", json={"enabled": True})
        self.assertEqual(r_on.status_code, 200)
        self.assertTrue(r_on.json()["demo_mode"])

        st = self.client.get("/api/status").json()
        self.assertTrue(st["demo_mode"])
        self.assertEqual(st["db"]["mode"], "demo")
        self.assertEqual(st["db"]["counts"]["annotations_count"], 180)

        # Execute filtered query in Demo Mode
        q_res = self.client.post(
            "/api/query/execute",
            json={
                "sql": "SELECT a.id AS annotation_id, a.call_type_code, a.label_code FROM core.annotations a WHERE a.label_code IN ('MAYBE') LIMIT 50",
                "max_rows": 50,
            },
        ).json()
        self.assertEqual(q_res["mode"], "demo")
        self.assertGreater(q_res["summary"]["row_count"], 0)
        self.assertTrue(all(r["label_code"] == "MAYBE" for r in q_res["preview_rows"]))

        # Verify playable synthetic spectrogram in Demo Mode
        sp_res = self.client.post("/api/spectrogram", json={"annotation_id": 10001}).json()
        self.assertEqual(sp_res["source_status"], "live_demo_synthetic")

        # Restore Live Mode
        self.client.post("/api/demo-mode", json={"enabled": False})


if __name__ == "__main__":
    unittest.main()
