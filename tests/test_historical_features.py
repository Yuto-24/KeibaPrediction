"""Contract tests: synthetic multi-race records are NEVER training evidence."""
from __future__ import annotations
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from keiba_backtest.historical_features import build_features, build_from_file


class TestHistoricalFeatures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture_path = ROOT / "data" / "fixtures" / "historical_synthetic.json"
        cls.source = json.loads(cls.fixture_path.read_text(encoding="utf-8"))

    def clone(self):
        return copy.deepcopy(self.source)

    def test_three_races_and_complete_horse_features(self):
        result = build_from_file(self.fixture_path)
        self.assertEqual([r["race_id"] for r in result["races"]], ["SYN-R1", "SYN-R2", "SYN-R3"])
        self.assertEqual([len(r["runners"]) for r in result["races"]], [2, 2, 2])
        self.assertEqual(result["quality"], "SYNTHETIC_NOT_EMPIRICAL")
        self.assertFalse(result["empirical_backtest_eligible"])
        self.assertEqual(len(result["input_sha256"]), 64)
        first, second, third = result["races"]
        self.assertEqual(first["excluded_entries"], [{"number": 3, "horse_id": "SYN-C", "entry_status": "withdrawn"}])
        self.assertEqual(first["runners"][0]["features"]["wins"], 1)
        self.assertEqual(first["runners"][1]["features"]["past_starts"], 0)
        self.assertIsNone(first["runners"][1]["features"]["max_prior_distance_m"])
        self.assertIsNone(first["runners"][1]["features"]["last_start_days_ago"])
        self.assertEqual(second["runners"][0]["features"]["past_starts"], 2)
        self.assertEqual(third["runners"][0]["features"]["turf_2400m_plus_starts"], 2)
        self.assertTrue(third["runners"][0]["features"]["first_time_target_distance_or_more"])
        self.assertEqual(third["runners"][1]["features"]["completed_finishes"], 1)
        self.assertEqual(third["runners"][1]["features"]["top3_finishes"], 1)
        self.assertAlmostEqual(third["runners"][0]["features"]["mean_last3f_seconds"], 35.1)

    def test_repeated_run_is_deterministic(self):
        self.assertEqual(build_features(self.source), build_features(self.source))
        reordered = self.clone()
        reordered["races"] = list(reversed(reordered["races"]))
        for r in reordered["races"]:
            r["entries"] = list(reversed(r["entries"]))
        self.assertEqual(build_features(self.source), build_features(reordered))

    def test_future_result_referenced_in_horse_history_rejected(self):
        data = self.clone()
        data["races"][0]["entries"][0]["past_starts"][0]["race_at"] = "2025-05-11T15:40:00+09:00"
        data["races"][0]["entries"][0]["past_starts"][0]["result_available_at"] = "2025-05-12T00:00:00+09:00"
        with self.assertRaisesRegex(ValueError, "future result leakage"):
            build_features(data)

    def test_not_yet_available_past_result_rejected(self):
        data = self.clone()
        data["races"][0]["entries"][0]["past_starts"][0]["result_available_at"] = "2025-05-10T09:00:00+09:00"
        with self.assertRaisesRegex(ValueError, "lookahead"):
            build_features(data)

    def test_historical_page_observed_after_asof_rejected(self):
        data = self.clone()
        data["races"][0]["entries"][0]["past_starts"][0]["evidence"]["observed_at"] = "2025-05-11T12:00:00+09:00"
        with self.assertRaisesRegex(ValueError, "observed_at after asof"):
            build_features(data)

    def test_entrant_list_captured_after_asof_rejected(self):
        data = self.clone()
        data["races"][0]["snapshot"]["observed_at"] = "2025-05-10T14:00:00+09:00"
        with self.assertRaisesRegex(ValueError, "observed_at after asof"):
            build_features(data)

    def test_target_race_result_as_feature_rejected(self):
        data = self.clone()
        data["races"][1]["entries"][0]["past_starts"][1]["race_id"] = "SYN-R2"
        with self.assertRaisesRegex(ValueError, "target leakage"):
            build_features(data)

    def test_duplicate_starts_rejected(self):
        data = self.clone()
        start = data["races"][1]["entries"][0]["past_starts"][0]
        data["races"][1]["entries"][0]["past_starts"].append(copy.deepcopy(start))
        with self.assertRaisesRegex(ValueError, "duplicate past race_id"):
            build_features(data)

    def test_duplicate_horse_id_rejected(self):
        data = self.clone()
        data["races"][0]["entries"][1]["horse_id"] = "SYN-A"
        with self.assertRaisesRegex(ValueError, "duplicate number or horse_id"):
            build_features(data)

    def test_stale_published_record_before_actual_race_rejected(self):
        data = self.clone()
        data["races"][0]["entries"][0]["past_starts"][0]["result_available_at"] = "2025-03-01T10:00:00+09:00"
        with self.assertRaisesRegex(ValueError, "result_available_at must be after"):
            build_features(data)

    def test_result_in_race_schema_rejected(self):
        data = self.clone()
        data["races"][0]["actual_winner"] = "SYN-A"
        with self.assertRaisesRegex(ValueError, "unknown fields"):
            build_features(data)

    def test_malformed_result_or_unknown_history_rejected(self):
        data = self.clone()
        data["races"][1]["entries"][1]["past_starts"][0]["finish_position"] = 1
        with self.assertRaisesRegex(ValueError, "must have null"):
            build_features(data)
        data = self.clone()
        data["races"][2]["entries"][1]["past_starts"][1]["field_size"] = 1
        with self.assertRaisesRegex(ValueError, "exceeds field_size"):
            build_features(data)

    def test_unverified_reconstruction_segregated_from_empirical(self):
        data = self.clone()
        data["dataset_kind"] = "retrospective_research"
        for race in data["races"]:
            race["snapshot"]["kind"] = "retrospective_unverified"
            race["snapshot"]["observed_at"] = "2026-10-25T21:00:00+09:00"
            for runner in race["entries"]:
                for s in runner["past_starts"]:
                    s["evidence"]["kind"] = "retrospective_unverified"
                    s["evidence"]["observed_at"] = "2026-10-25T21:00:00+09:00"
        with self.assertRaisesRegex(ValueError, "--allow-unverified"):
            build_features(data)
        result = build_features(data, allow_unverified=True)
        self.assertFalse(result["empirical_backtest_eligible"])
        self.assertEqual(result["quality"], "RETROSPECTIVE_UNVERIFIED_NOT_EMPIRICAL")
        self.assertTrue(all(r["quality"] == "RETROSPECTIVE_UNVERIFIED_NOT_EMPIRICAL" for r in result["races"]))

    def test_archive_cannot_contain_synthetic_or_retro(self):
        data = self.clone()
        data["dataset_kind"] = "historical_archive"
        with self.assertRaisesRegex(ValueError, "requires captured_pre_race"):
            build_features(data)
        data["dataset_kind"] = "synthetic_fixture"
        data["races"][0]["snapshot"]["kind"] = "captured_pre_race"
        data["races"][0]["snapshot"]["source_sha256"] = "a" * 64
        with self.assertRaisesRegex(ValueError, "may only contain synthetic"):
            build_features(data)

    def test_cross_snapshot_conflict_rejected(self):
        data = self.clone()
        # Prior run SYN-R1 is also present in SYN-R3. Its outcome cannot
        # silently change between snapshots with this immutable schema.
        data["races"][2]["entries"][0]["past_starts"][1]["finish_position"] = 1
        with self.assertRaisesRegex(ValueError, "conflicting prior start across snapshots"):
            build_features(data)

    def test_captured_start_before_official_result_is_rejected(self):
        data = self.clone()
        data["races"][0]["entries"][0]["past_starts"][0]["evidence"]["observed_at"] = "2025-03-01T17:00:00+09:00"
        with self.assertRaisesRegex(ValueError, "observed_at before result_available_at"):
            build_features(data)

    def test_capture_missing_source_hash_rejected(self):
        data = self.clone()
        data["dataset_kind"] = "historical_archive"
        data["races"][0]["snapshot"]["kind"] = "captured_pre_race"
        with self.assertRaisesRegex(ValueError, "requires source_sha256"):
            build_features(data)

    def test_capture_can_create_empirical_grade_output(self):
        # Synthetic test of the capture contract, NOT proof that real snapshots exist.
        data = self.clone()
        data["dataset_kind"] = "historical_archive"
        for race in data["races"]:
            race["snapshot"]["kind"] = "captured_pre_race"
            race["snapshot"]["source_sha256"] = "a" * 64
            for runner in race["entries"]:
                for s in runner["past_starts"]:
                    s["evidence"]["kind"] = "captured_pre_race"
                    s["evidence"]["source_sha256"] = "a" * 64
        result = build_features(data)
        self.assertTrue(result["empirical_backtest_eligible"])
        self.assertEqual(result["quality"], "VERIFIED_PRE_RACE")
        # The captured timestamps above are invented for a test; they must never
        # be presented as evidence of real archival availability.

    def test_bad_timestamps_and_status_rejected(self):
        data = self.clone()
        data["races"][0]["asof"] = data["races"][0]["race_at"]
        with self.assertRaisesRegex(ValueError, "asof must be before"):
            build_features(data)
        data = self.clone()
        data["races"][0]["asof"] = "2025-05-09T18:00:00"
        with self.assertRaisesRegex(ValueError, "timezone"):
            build_features(data)
        data = self.clone()
        data["races"][0]["entries"][0]["status"] = "retired_after_race"
        with self.assertRaisesRegex(ValueError, "entry status"):
            build_features(data)

    def test_cli_writes_only_validated_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "history.json"
            cmd = [sys.executable, "-m", "keiba_backtest.cli", "historical-features", "--input", str(self.fixture_path), "--output", str(target)]
            env = dict(__import__("os").environ, PYTHONPATH=str(ROOT / "src"))
            run = subprocess.run(cmd, env=env, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertTrue(target.exists())
            self.assertEqual(len(json.loads(target.read_text(encoding="utf-8"))["races"]), 3)
            target.unlink()
            data = self.clone()
            data["races"][1]["entries"][0]["past_starts"][0]["evidence"]["observed_at"] = "2026-01-01T00:00:00+09:00"
            invalid = Path(tmp) / "invalid.json"
            invalid.write_text(json.dumps(data), encoding="utf-8")
            failed = subprocess.run(cmd[:-3]+["--input", str(invalid), "--output", str(target)], env=env, capture_output=True, text=True)
            self.assertNotEqual(failed.returncode, 0)
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
