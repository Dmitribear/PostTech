"""Copy source files to a NEW empty directory, excluding runtime state and secrets."""
import argparse
from datetime import datetime
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = ("app", "database", "docs", "evals", "examples", "frontend", "scripts", "tests")
FILES = ("README.md", "requirements.txt", "requirements.lock.txt", "requirements-dev.txt", "Dockerfile", "compose.yaml", ".dockerignore", ".gitignore", ".env.example", "Start PostTech.cmd", "Stop PostTech.cmd")

def copy_to(destination):
    destination = destination.resolve()
    if destination.exists():
        raise ValueError("Destination must not exist; nothing was overwritten")
    destination.mkdir(parents=True)
    ignore = shutil.ignore_patterns(".env", ".env.local", ".env.*.local", ".local", "node_modules", "dist", "__pycache__", "*.pyc", "*.tsbuildinfo", "test-results", "playwright-report", ".npm-cache", ".pytest_cache")
    for name in DIRECTORIES:
        source = ROOT / name
        if source.exists(): shutil.copytree(source, destination / name, ignore=ignore)
    for name in FILES:
        if (ROOT / name).is_file(): shutil.copy2(ROOT / name, destination / name)
    if (destination / ".env").exists() or (destination / ".local").exists():
        raise RuntimeError("Unexpected private state in clean copy")
    return destination

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--destination", type=Path, default=ROOT / ".local" / ("clean-" + datetime.now().strftime("%Y%m%d-%H%M%S")))
    print(copy_to(p.parse_args().destination))
