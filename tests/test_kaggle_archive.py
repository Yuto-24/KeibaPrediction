"""Read-only archive inspection never publishes source CSV contents."""
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from keiba_backtest.kaggle_archive import inspect_archive

class TestArchiveInspection(unittest.TestCase):
    def test_multiple_csv_with_japanese_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "races.zip"
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("Odds.csv", "race_id,馬番,単勝\nA,1,2.0\n")
                z.writestr("Results.csv", "race_id,馬番,着順\nA,1,1\n")
            result = inspect_archive(path)
            self.assertEqual(len(result["entries"]), 2)
            self.assertEqual(result["entries"][0]["columns"], ["race_id", "馬番", "単勝"])
            self.assertNotIn("A,1,2.0", str(result))
    def test_reject_zip_slip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.zip"
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("../secret.csv", "a,b\n1,2\n")
            with self.assertRaisesRegex(ValueError, "unsafe"):
                inspect_archive(path)
    def test_reject_duplicate_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.zip"
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("x.csv", "a,a\n1,2\n")
            with self.assertRaisesRegex(ValueError, "duplicate"):
                inspect_archive(path)
    def test_file_count_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "too-many.zip"
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("a.csv", "a,b\n")
                z.writestr("b.csv", "a,b\n")
            with self.assertRaisesRegex(ValueError, "file-count"):
                inspect_archive(path, max_files=1)
