"""Synthetic-only tests: no real betting prices or vendor market data."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from keiba_backtest import cli
from keiba_backtest.market_capture import capture_to_directory, create_snapshot, verify_seal
from keiba_backtest.records import load_json, validate_market
from keiba_backtest.scoring import market_probabilities, score_forecast


class TestMarketCapture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.forecast = load_json(ROOT / "data/forecasts/2026_kikka_forecast.json")
        cls.outcome = load_json(ROOT / "data/outcomes/2026_kikka_result.json")
        cls.instant = datetime.fromisoformat("2026-10-23T14:50:00+09:00")

    def input(self):
        return {"race_id": self.forecast["race_id"],
                "source_url": "https://example.org/synthetic-odds",
                "source_label": "synthetic unit-test prices",
                "status": "available",
                "decimal_win_odds": {str(r["number"]): 10 + r["number"] for r in self.forecast["runners"]}}

    def test_capture_atomic_immutable_and_scored(self):
        with tempfile.TemporaryDirectory() as d:
            raw = Path(d) / "input.json"
            raw.write_text(json.dumps(self.input(), ensure_ascii=False), encoding="utf-8")
            dst = capture_to_directory(raw, self.forecast, Path(d) / "private",
                                       clock=lambda: self.instant)
            snap = load_json(dst)
            self.assertEqual(snap["status"], "available")
            self.assertEqual(snap["decision_at"], self.instant.astimezone(timezone.utc).isoformat(timespec="microseconds"))
            self.assertEqual(snap["observed_at"], snap["captured_at"])
            self.assertEqual(snap["evidence_level"], "SELF_REPORTED_NOT_INDEPENDENTLY_VERIFIED")
            verify_seal(snap)
            validate_market(snap, self.forecast)
            self.assertTrue(dst.name.endswith(snap["snapshot_sha256"] + ".json"))
            self.assertAlmostEqual(sum(market_probabilities(snap, self.forecast)), 1)
            result = score_forecast(self.forecast, self.outcome, snap)
            self.assertEqual(result["market"]["status"], "available_self_reported")
            self.assertGreater(result["market"]["implied_inverse_odds_sum"], 0)
            self.assertTrue(result["market"]["market_has_later_information"])
            original = dst.read_bytes()
            with self.assertRaises(FileExistsError):
                capture_to_directory(raw, self.forecast, Path(d) / "private",
                                     clock=lambda: self.instant)
            self.assertEqual(dst.read_bytes(), original)

    def test_undocumented_field_rejected(self):
        incoming = self.input()
        incoming["post_race_payout"] = 42.0
        with self.assertRaisesRegex(ValueError, "unknown market input"):
            create_snapshot(incoming, self.forecast, captured_at=self.instant)

    def test_full_field_and_valid_odds(self):
        for case in ("missing", "extra", "zero", "nan", "bool"):
            with self.subTest(case=case):
                incoming = self.input()
                if case == "missing":
                    del incoming["decimal_win_odds"]["1"]
                if case == "extra":
                    incoming["decimal_win_odds"]["999"] = 50
                if case == "zero":
                    incoming["decimal_win_odds"]["1"] = 0
                if case == "nan":
                    incoming["decimal_win_odds"]["1"] = float("nan")
                if case == "bool":
                    incoming["decimal_win_odds"]["1"] = True
                with self.assertRaisesRegex(ValueError, "odds"):
                    create_snapshot(incoming, self.forecast, captured_at=self.instant)

    def test_timestamp_invariant(self):
        for delta in (timedelta(days=-1), timedelta(days=3)):
            with self.subTest(delta=delta):
                with self.assertRaisesRegex(ValueError, "live capture"):
                    create_snapshot(self.input(), self.forecast,
                                    captured_at=self.instant + delta)
        with self.assertRaisesRegex(ValueError, "timezone"):
            create_snapshot(self.input(), self.forecast,
                            captured_at=datetime(2026, 10, 23, 14, 50))

    def test_seal_and_timestamp_tampering_fails_closed(self):
        snap = create_snapshot(self.input(), self.forecast, captured_at=self.instant)
        tampered = copy.deepcopy(snap)
        tampered["decimal_win_odds"]["9"] = 999
        with self.assertRaisesRegex(ValueError, "integrity"):
            validate_market(tampered, self.forecast)
        tampered = copy.deepcopy(snap)
        tampered["observed_at"] = "2026-10-23T10:00:00+00:00"
        with self.assertRaisesRegex(ValueError, "chronology|match"):
            validate_market(tampered, self.forecast)
        tampered = copy.deepcopy(snap)
        tampered["decision_at"] = "2026-10-25T16:00:00+09:00"
        with self.assertRaisesRegex(ValueError, "chronology"):
            validate_market(tampered, self.forecast)

    def test_not_available_is_explicitly_unscored(self):
        data = {"race_id": self.forecast["race_id"], "status": "not_available",
                "source_url": "https://example.org/synthetic-odds",
                "reason": "No complete price was supplied"}
        snap = create_snapshot(data, self.forecast, captured_at=self.instant)
        validate_market(snap, self.forecast)
        score = score_forecast(self.forecast, self.outcome, snap)
        self.assertEqual(score["market"]["status"], "not_available")
        self.assertNotIn("log_loss", score["market"])
        no_quote = score_forecast(self.forecast, self.outcome)
        self.assertEqual(no_quote["market"]["status"], "not_available")
        with self.assertRaisesRegex(ValueError, "no market odds"):
            market_probabilities(snap, self.forecast)

    def test_unavailable_requires_reason_without_odds(self):
        data = self.input()
        data["status"] = "not_available"
        with self.assertRaisesRegex(ValueError, "not_available"):
            create_snapshot(data, self.forecast, captured_at=self.instant)
        del data["decimal_win_odds"]
        with self.assertRaisesRegex(ValueError, "reason"):
            create_snapshot(data, self.forecast, captured_at=self.instant)

    def test_legacy_quote_labeled_unverified(self):
        data = self.input()
        legacy = {"race_id": data["race_id"], "observed_at": self.forecast["asof"],
                  "source_url": data["source_url"], "decimal_win_odds": data["decimal_win_odds"]}
        score = score_forecast(self.forecast, self.outcome, legacy)
        self.assertEqual(score["market"]["status"], "unverified_legacy_quote")

    def test_capture_cli_delegates_to_live_capture(self):
        with patch("keiba_backtest.cli.capture_to_directory", return_value=Path("/private/quote.json")) as mocked:
            cli.main(["capture-market", "--forecast", str(ROOT / "data/forecasts/2026_kikka_forecast.json"),
                      "--input", "dummy.json", "--output-dir", "/private"])
            self.assertTrue(mocked.called)

    def test_bad_or_missing_source_address_is_rejected(self):
        for invalid_url in ("", "https://", "http://example.org/quote", 12, None):
            with self.subTest(url=invalid_url):
                data = self.input()
                data["source_url"] = invalid_url
                with self.assertRaisesRegex(ValueError, "source_url"):
                    create_snapshot(data, self.forecast, captured_at=self.instant)

    def test_available_not_available_sources_remain_different(self):
        missing = {"race_id": self.forecast["race_id"],
                   "source_url": "https://example.org/quote", "status": "not_available",
                   "reason": "Full field missing"}
        available = self.input()
        first = create_snapshot(missing, self.forecast, captured_at=self.instant)
        second = create_snapshot(available, self.forecast, captured_at=self.instant)
        self.assertNotEqual(first["snapshot_sha256"], second["snapshot_sha256"])
        self.assertNotIn("decimal_win_odds", first)
        self.assertEqual(score_forecast(self.forecast, self.outcome, first)["market"]["status"], "not_available")

    def test_reject_path_traversal_in_race_id(self):
        f = copy.deepcopy(self.forecast)
        f["race_id"] = "../../escape"
        incoming = self.input()
        incoming["race_id"] = f["race_id"]
        with self.assertRaisesRegex(ValueError, "filename-safe"):
            create_snapshot(incoming, f, captured_at=self.instant)


if __name__ == "__main__":
    unittest.main()
