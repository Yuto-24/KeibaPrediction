"""Tests for optional Kaggle acquisition: all fixture content is synthetic."""
from __future__ import annotations
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from keiba_backtest.kaggle_download import DATASET_HANDLE, _version, inventory, download_and_inventory


class TestKaggleDownload(unittest.TestCase):
    def test_inventory_hashes_and_version(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "versions" / "4"
            root.mkdir(parents=True)
            (root / "Odds.csv").write_text("race,odds\nTEST,2.0\n")
            result = inventory(root)
            self.assertEqual(result["dataset_handle"], DATASET_HANDLE)
            self.assertEqual(result["dataset_version"], "4")
            self.assertFalse(result["version_verified"])
            self.assertEqual(len(result["files"]), 1)
            self.assertEqual(len(result["files"][0]["sha256"]), 64)
            self.assertNotIn("TEST,2.0", json.dumps(result))
    def test_missing_files_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, "no files"):
                inventory(temp)
    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/"a.csv").write_text("test")
            (root/"b.csv").symlink_to(root/"a.csv")
            with self.assertRaisesRegex(ValueError, "symbolic"):
                inventory(root)
    def test_version_unknown_does_not_guess(self):
        self.assertIsNone(_version(Path("/cache/kaggle/downloads/dataset")))
    def test_stub_downloader_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "versions" / "3"
            root.mkdir(parents=True)
            (root/"synthetic.csv").write_text("column\nvalue\n")
            destination=Path(temp)/"manifest.json"
            fake=types.SimpleNamespace(dataset_download=lambda handle: str(root))
            with patch.dict(sys.modules, {"kagglehub": fake}):
                result=download_and_inventory(output=destination)
                self.assertEqual(result["files"], 1)
                with self.assertRaises(FileExistsError):
                    download_and_inventory(output=destination)
            self.assertTrue(destination.exists())
    def test_unreviewed_dataset_rejected(self):
        with self.assertRaisesRegex(ValueError, "reviewed"):
            download_and_inventory(output="unused", handle="other/unknown")
