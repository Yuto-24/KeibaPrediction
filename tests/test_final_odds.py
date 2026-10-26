"""Synthetic-only settled odds tests; no licensed provider records in repo."""
from __future__ import annotations

from datetime import datetime, timezone
import copy
import hashlib
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from keiba_backtest import cli
from keiba_backtest.final_odds import (build_final_odds_snapshot, import_final_odds,
                                      validate_final_odds, score_against_final_odds,
                                      batch_compare_final_odds)
from keiba_backtest.market_capture import canonical_bytes
from keiba_backtest.records import load_json, validate_market
from keiba_backtest.scoring import score_forecast


class TestFinalOdds(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.forecast = load_json(ROOT / "data/forecasts/2026_kikka_forecast.json")
        cls.outcome = load_json(ROOT / "data/outcomes/2026_kikka_result.json")
        cls.now = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)

    def example(self):
        return {"race_id": self.forecast["race_id"],
                "source_url": "https://example.org/illustrative-not-real",
                "source_label": "synthetic test only", "status": "available",
                "decimal_win_odds": {str(x["number"]): x["number"] + 2.0
                                     for x in self.forecast["runners"]}}

    def snapshot(self, data=None):
        return build_final_odds_snapshot(self.example() if data is None else data,
                                         self.forecast, retrieved_at=self.now)

    @staticmethod
    def reseal(data):
        data["snapshot_sha256"] = hashlib.sha256(canonical_bytes(
            {k: v for k, v in data.items() if k != "snapshot_sha256"})).hexdigest()
        return data

    def test_not_ex_ante_quote(self):
        snap = self.snapshot()
        validate_final_odds(snap, self.forecast)
        with self.assertRaisesRegex(ValueError, "not an observed pre-race"):
            validate_market(snap, self.forecast)
        with self.assertRaisesRegex(ValueError, "not an observed pre-race"):
            score_forecast(self.forecast, self.outcome, snap)

    def test_scoring_winner_and_provenance(self):
        report = score_against_final_odds(self.forecast, self.outcome, self.snapshot())
        market = report["market_final"]
        self.assertEqual(market["status"], "available_retrospective_benchmark")
        self.assertTrue(market["not_a_purchase_backtest"])
        self.assertFalse(market["source_verified"])
        self.assertAlmostEqual(market["log_loss"], -math.log(market["winner_probability"]))
        self.assertEqual(set(report["difference_model_minus_final_market"]),
                         {"log_loss", "brier_multiclass_sum"})
        self.assertNotIn("market", report)

    def test_explicit_not_available(self):
        incoming = self.example()
        incoming.pop("decimal_win_odds")
        incoming["status"] = "not_available"
        incoming["reason"] = "no historical record"
        report = score_against_final_odds(self.forecast, self.outcome, self.snapshot(incoming))
        self.assertEqual(report["market_final"]["status"], "not_available")
        self.assertNotIn("difference_model_minus_final_market", report)

    def test_reject_bad_price_and_missing_entrants(self):
        for k in ("missing", "extra", "negative", "bool", "nan", "mismatch", "unknown", "bad_status"):
            with self.subTest(k=k):
                inp = self.example()
                if k == "missing": inp["decimal_win_odds"].pop("1")
                if k == "extra": inp["decimal_win_odds"]["0"] = 5
                if k == "negative": inp["decimal_win_odds"]["1"] = 0
                if k == "bool": inp["decimal_win_odds"]["1"] = True
                if k == "nan": inp["decimal_win_odds"]["1"] = float('nan')
                if k == "mismatch": inp["race_id"] = "different"
                if k == "unknown": inp["winner"] = 9
                if k == "bad_status": inp["status"] = "unverified"
                with self.assertRaises((ValueError, TypeError)):
                    self.snapshot(inp)

    def test_clock_and_final_kind_validation(self):
        with self.assertRaisesRegex(ValueError, "before race"):
            build_final_odds_snapshot(self.example(), self.forecast,
                                      retrieved_at=datetime(2026, 10, 24, tzinfo=timezone.utc))
        with self.assertRaisesRegex(ValueError, "timezone"):
            build_final_odds_snapshot(self.example(), self.forecast,
                                      retrieved_at=datetime(2026, 10, 27))
        snap = self.snapshot()
        snap["odds_kind"] = "observed_pre_race"
        self.reseal(snap)
        with self.assertRaisesRegex(ValueError, "settled final"):
            validate_final_odds(snap, self.forecast)

    def test_tamper_and_shape(self):
        snap = self.snapshot()
        snap["decimal_win_odds"]["8"] = 123.0
        with self.assertRaisesRegex(ValueError, "integrity"):
            score_against_final_odds(self.forecast, self.outcome, snap)
        snap = self.snapshot()
        snap["status"] = "not_available"
        snap["reason"] = "nothing"
        self.reseal(snap)
        with self.assertRaisesRegex(ValueError, "no prices"):
            validate_final_odds(snap, self.forecast)

    def test_import_writes_once_with_seal(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "source.json"
            src.write_text(json.dumps(self.example()), encoding="utf-8")
            target = Path(d) / "private"
            stored = import_final_odds(src, self.forecast, target, clock=lambda: self.now)
            self.assertTrue(stored.is_file())
            self.assertEqual(stored.stat().st_mode & 0o777, 0o600)
            self.assertEqual(load_json(stored)["retrieved_at"], self.now.isoformat(timespec="microseconds"))
            with self.assertRaises(FileExistsError):
                import_final_odds(src, self.forecast, target, clock=lambda: self.now)

    def test_batch_strict_completeness_and_duplicate(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            for name in ("forecasts", "outcomes", "odds"):
                (p / name).mkdir()
            (p / "forecasts" / "one.json").write_text(json.dumps(self.forecast))
            (p / "outcomes" / "one.json").write_text(json.dumps(self.outcome))
            blank = batch_compare_final_odds(p / "forecasts", p / "outcomes", p / "odds")
            self.assertEqual(blank["market_scored_races"], 0)
            self.assertEqual(blank["market_not_available"][0]["reason"], "no_final_odds_record")
            (p / "odds" / "nested").mkdir()
            snap = self.snapshot()
            (p / "odds" / "nested" / "one.json").write_text(json.dumps(snap))
            out = batch_compare_final_odds(p / "forecasts", p / "outcomes", p / "odds")
            self.assertEqual(out["market_scored_races"], 1)
            self.assertIn("sample_size_warning", out)
            self.assertAlmostEqual(out["matched_race_mean_scores"]["market_final"]["log_loss"],
                                   out["race_scores"][0]["market_final"]["log_loss"])
            (p / "odds" / "dup.json").write_text(json.dumps(snap))
            with self.assertRaisesRegex(ValueError, "duplicate"):
                batch_compare_final_odds(p / "forecasts", p / "outcomes", p / "odds")

    def test_cli_parsers_and_json_output(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            source = p / "source.json"
            source.write_text(json.dumps(self.example()))
            # CLI clock is system-provided; monkeypatch function at the seam.
            with patch("keiba_backtest.cli.import_final_odds") as imported:
                imported.return_value = p / "sealed.json"
                cli.main(["import-final-odds", "--forecast", str(ROOT / "data/forecasts/2026_kikka_forecast.json"),
                          "--input", str(source), "--output-dir", str(p / "odds")])
                self.assertTrue(imported.called)
            snapshot = p / "sealed.json"
            snapshot.write_text(json.dumps(self.snapshot()))
            dst = p / "output.json"
            cli.main(["evaluate-final-odds", "--forecast", str(ROOT / "data/forecasts/2026_kikka_forecast.json"),
                      "--outcome", str(ROOT / "data/outcomes/2026_kikka_result.json"),
                      "--final-odds", str(snapshot), "--output", str(dst)])
            self.assertIn("market_final", json.loads(dst.read_text()))


if __name__ == "__main__":
    unittest.main()
