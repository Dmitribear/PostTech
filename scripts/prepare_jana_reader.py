"""Install the pinned, free local reader; this script never executes downloads.

Usage: python scripts/prepare_jana_reader.py [--verify-only]
Weights and executables are stored below .models/reader (ignored by Git).
Only standard-library code is needed. Downloads are checked against the reviewed
SHA256/size in knowledge_base/reader-model.json before extraction or use.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / ".models" / "reader"
MANIFEST = ROOT / "knowledge_base" / "reader-model.json"


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(4 * 1024 * 1024):
            result.update(block)
    return result.hexdigest()


def valid(path: Path, spec: dict) -> bool:
    return (
        path.is_file()
        and path.stat().st_size == spec["size"]
        and digest(path) == spec["sha256"]
    )


def obtain(spec: dict, *, verify_only: bool) -> Path:
    filename = spec["filename"]
    if Path(filename).name != filename or not spec["url"].startswith("https://"):
        raise ValueError("Invalid pinned artifact")
    target = DEST / filename
    if valid(target, spec):
        print(f"Verified {filename}", flush=True)
        return target
    if verify_only:
        raise RuntimeError(
            f"Missing/corrupt {target}. Run the preparation script without --verify-only."
        )
    partial = target.with_suffix(target.suffix + ".partial")
    # A fresh request avoids accepting an incomplete response or an unverified cache.
    request = urllib.request.Request(
        spec["url"], headers={"User-Agent": "PostTech-Jana-setup/1"}
    )
    print(f"Downloading {filename} ({spec['size'] / 1_000_000:.1f} MB)", flush=True)
    started = last = time.monotonic()
    received = 0
    with (
        urllib.request.urlopen(request, timeout=120) as response,
        partial.open("wb") as output,
    ):
        while block := response.read(4 * 1024 * 1024):
            received += len(block)
            if received > spec["size"]:
                raise RuntimeError("Download exceeded the pinned file size")
            output.write(block)
            if time.monotonic() - last > 10:
                elapsed = time.monotonic() - started
                print(
                    f"  {received / spec['size']:.0%}; {received / elapsed / 1_000_000:.1f} MB/s",
                    flush=True,
                )
                last = time.monotonic()
    if not valid(partial, spec):
        raise RuntimeError(
            f"SHA256/size mismatch for {filename}; artifact was not installed"
        )
    partial.replace(target)
    print(f"Verified {filename}", flush=True)
    return target


def unpack_verified(archive: Path, *, verify_only: bool) -> Path:
    folder = DEST / "runtime"
    folder.mkdir(parents=True, exist_ok=True)
    root = folder.resolve()
    executable = None
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            relative = PurePosixPath(info.filename.replace("\\", "/"))
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or any(":" in p for p in relative.parts)
            ):
                raise RuntimeError("Unsafe archive path")
            if stat.S_ISLNK(info.external_attr >> 16):
                raise RuntimeError("Archive symlinks are not allowed")
            target = (folder / Path(*relative.parts)).resolve()
            if not target.is_relative_to(root):
                raise RuntimeError("Archive path escaped runtime folder")
            if info.is_dir():
                if not verify_only:
                    target.mkdir(parents=True, exist_ok=True)
                continue
            with bundle.open(info) as source:
                expected = hashlib.sha256(source.read()).hexdigest()
            if not target.is_file() or digest(target) != expected:
                if verify_only:
                    raise RuntimeError(f"Missing/corrupt runtime file {target}")
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(info) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                if digest(target) != expected:
                    raise RuntimeError(f"Runtime extraction failed {target}")
            if target.name == "llama-server.exe":
                if executable is not None:
                    raise RuntimeError("Multiple server executables in archive")
                executable = target
    if executable is None:
        raise RuntimeError("Server executable missing from the pinned archive")
    return executable


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Verify local files without any network access",
    )
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    DEST.mkdir(parents=True, exist_ok=True)
    # Small runtime first; the large model follows only after the ZIP is valid.
    archive = obtain(manifest["runtime"], verify_only=args.verify_only)
    server = unpack_verified(archive, verify_only=args.verify_only)
    model = obtain(manifest["model"], verify_only=args.verify_only)
    print(
        json.dumps(
            {"status": "verified", "server": str(server), "model": str(model)},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
