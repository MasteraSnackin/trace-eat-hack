#!/usr/bin/env python3
"""Fetch the five pinned Open Model Zoo weights; verify upstream size + SHA-384.

Only model data is downloaded. TLS verification remains enabled. Files are
published atomically after verification; existing valid downloads are reused.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def verify(path: Path, entry: dict) -> bool:
    if not path.is_file() or path.stat().st_size != entry["size"]:
        return False
    digest = hashlib.sha384()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != entry["sha384"]:
        return False
    if path.suffix == ".xml":
        try:
            if ET.parse(path).getroot().tag != "net":
                return False
        except ET.ParseError:
            return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, default=ROOT / "models")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    manifest = json.loads((ROOT / "model-provenance.json").read_text())
    destination = args.model_dir.resolve()
    total = 0
    for model in manifest["models"]:
        for entry in model["files"]:
            path = destination / entry["path"]
            if not path.resolve().is_relative_to(destination):
                raise ValueError("Unsafe model destination")
            if verify(path, entry):
                print(f"Verified {entry['path']}", flush=True)
                total += entry["size"]
                continue
            if args.verify_only:
                raise SystemExit(f"Missing or invalid: {path}")
            if not entry["url"].startswith("https://storage.openvinotoolkit.org/"):
                raise ValueError("Model URL is not the pinned official storage host")
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                prefix=path.name + ".", suffix=path.suffix,
                dir=path.parent, delete=False
            ) as handle:
                temporary = Path(handle.name)
            try:
                subprocess.run([
                    "curl", "--fail", "--location", "--silent", "--show-error",
                    "--proto", "=https", "--proto-redir", "=https",
                    "--retry", "2", "--connect-timeout", "15", "--max-time", "180",
                    "--output", str(temporary), entry["url"]
                ], check=True)
                if not verify(temporary, entry):
                    raise RuntimeError(f"Size, SHA-384 or XML validation failed: {entry['path']}")
                temporary.replace(path)
                total += entry["size"]
                print(f"Downloaded and verified {entry['path']}", flush=True)
            finally:
                temporary.unlink(missing_ok=True)
    print(f"Ready: {len(manifest['models'])} models, {total:,} verified bytes.")


if __name__ == "__main__":
    main()
