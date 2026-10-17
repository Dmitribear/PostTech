"""Local presentation server. Start through start_jury.ps1."""

import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
import uvicorn

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8010)
    args = parser.parse_args()
    uvicorn.run("app.main:app", host="127.0.0.1", port=args.port, access_log=False)
