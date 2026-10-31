"""Free Kaggle dataset acquisition and local provenance manifest.

Optional dependency kagglehub, installed by the operator. No dataset bytes are
transmitted to this repository; inventories and hashes are recorded locally.
"""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import importlib
import json
from pathlib import Path

DATASET_HANDLE = "takamotoki/jra-horse-racing-dataset"


def _digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as src:
        for chunk in iter(lambda: src.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def _version(directory: Path) -> str | None:
    parts = directory.parts
    for index in range(len(parts) - 2, -1, -1):
        if parts[index] == "versions" and index + 1 < len(parts):
            version = parts[index + 1]
            return version if version.isdigit() else None
    return None


def inventory(directory: str | Path, *, handle: str = DATASET_HANDLE) -> dict:
    root = Path(directory).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("dataset_download must return a directory")
    files = []
    for item in sorted(root.rglob("*")):
        if item.is_symlink():
            raise ValueError(f"symbolic links are not permitted: {item.name}")
        if not item.is_file():
            continue
        files.append({
            "path": item.relative_to(root).as_posix(),
            "bytes": item.stat().st_size,
            "sha256": _digest(item),
        })
    if not files:
        raise ValueError("downloaded dataset directory contains no files")
    return {
        "schema_version": 1,
        "dataset_handle": handle,
        "dataset_version": _version(root),
        "version_verified": False,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "dataset_page": f"https://www.kaggle.com/datasets/{handle}",
        "provenance": "LOCAL_DOWNLOAD_NOT_INDEPENDENTLY_ATTESTED",
        "files": files,
        "warning": "Manifest describes local bytes, not a license or proof that values were final odds.",
    }


def download_and_inventory(*, output: str | Path, handle: str = DATASET_HANDLE) -> dict:
    if handle != DATASET_HANDLE:
        raise ValueError("only the reviewed dataset handle is supported")
    try:
        kagglehub = importlib.import_module("kagglehub")
    except ImportError as exc:
        raise RuntimeError("Install the optional free package: python -m pip install kagglehub") from exc
    root = Path(kagglehub.dataset_download(handle))
    report = inventory(root, handle=handle)
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Do not overwrite an older manifest; preserve the version and file hashes.
    with destination.open("x", encoding="utf-8") as file:
        json.dump(report, file, indent=2, ensure_ascii=False)
        file.write("\n")
    return {"status": "downloaded_and_inventoried", "manifest_path": str(destination),
            "files": len(report["files"]), "dataset_version": report["dataset_version"],
            "version_verified": False,
            "dataset_path": str(root),
            "notice": "Do not commit downloaded files or proprietary data to public GitHub."}
