"""Populate only the model volume; never execute a downloaded binary."""
from pathlib import Path
import argparse
import json
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts import prepare_jana_reader as pinned


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="Optional read-only directory of existing GGUF files")
    args = parser.parse_args()
    spec = json.loads((ROOT / "knowledge_base/reader-model.json").read_text())["model"]
    pinned.DEST = Path("/models")
    pinned.DEST.mkdir(parents=True, exist_ok=True)
    target = pinned.DEST / spec["filename"]
    if args.source and not pinned.valid(target, spec):
        source = args.source / spec["filename"]
        if not pinned.valid(source, spec):
            raise SystemExit("Source GGUF failed pinned SHA256/size verification")
        partial = target.with_suffix(".copying")
        shutil.copyfile(source, partial)
        if not pinned.valid(partial, spec):
            raise SystemExit("Copied GGUF failed verification")
        partial.replace(target)
    pinned.obtain(spec, verify_only=False)
    target.chmod(0o444)
    print("Pinned model volume is ready", flush=True)


if __name__ == "__main__":
    main()
