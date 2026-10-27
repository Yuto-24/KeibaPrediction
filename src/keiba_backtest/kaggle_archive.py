"""Read-only ZIP inventory for manually downloaded historical CSV archives.

Never extracts entries, sends data to a server, or claims licensing provenance.
"""
from __future__ import annotations
import csv
import io
from pathlib import Path, PurePosixPath
import zipfile

def inspect_archive(path: str | Path, *, encoding: str = "utf-8-sig", max_files: int = 100, max_header_bytes: int = 65536) -> dict:
    """Inspect CSV headers safely without inflating the entire archive."""
    if max_files < 1 or max_header_bytes < 1:
        raise ValueError("limits must be positive")
    records = []
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if len(infos) > max_files:
            raise ValueError("archive exceeds file-count limit")
        for item in infos:
            if item.is_dir():
                continue
            name = item.filename
            pure = PurePosixPath(name)
            if pure.is_absolute() or ".." in pure.parts or "\\" in name or name.startswith("/"):
                raise ValueError("unsafe archive entry path")
            if item.flag_bits & 0x1:
                raise ValueError("encrypted ZIP entries are unsupported")
            if not name.lower().endswith(".csv"):
                records.append({"filename": name, "csv": False, "size_bytes": item.file_size})
                continue
            with archive.open(item) as stream:
                head = stream.read(max_header_bytes + 1)
            if len(head) > max_header_bytes:
                head = head[:max_header_bytes]
            # Inspect just one header record. Multiline CSV headers are deliberately
            # unsupported and flagged rather than guessed.
            line = head.splitlines()[0] if head.splitlines() else b""
            try:
                header = next(csv.reader(io.StringIO(line.decode(encoding))), [])
            except (UnicodeError, csv.Error) as exc:
                raise ValueError(f"{name}: encoding/header parse failed") from exc
            if not header or len(set(header)) != len(header):
                raise ValueError(f"{name}: missing or duplicate headers")
            records.append({"filename": name, "csv": True, "size_bytes": item.file_size, "columns": header})
    return {"archive_name": Path(path).name, "entries": records,
            "notice": "Only ZIP metadata and CSV headers inspected; confirm source schema, permissions and odds semantics before import."}
