"""One-time download of the pinned public CPU model (about 288 MB).

python -m scripts.prepare_jana_local
Subsequent inference is offline. Existing valid files are reused.
"""

import urllib.request

from app.core.config import get_settings
from app.services.local_embeddings import MODEL_FILES, MODEL_ID, REVISION, file_matches


def main() -> None:
    model_dir = get_settings().jana_model_dir
    for name, digest in MODEL_FILES.items():
        target = model_dir / name
        if file_matches(target, digest):
            print(f"Verified: {name}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix(target.suffix + ".part")
        url = f"https://huggingface.co/{MODEL_ID}/resolve/{REVISION}/{name}"
        print(f"Downloading: {name}", flush=True)
        try:
            with urllib.request.urlopen(url, timeout=60) as response, partial.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
            if not file_matches(partial, digest):
                raise RuntimeError(f"Checksum mismatch: {name}")
            partial.replace(target)
        finally:
            partial.unlink(missing_ok=True)
    print(f"Local model ready: {model_dir}")


if __name__ == "__main__":
    main()
