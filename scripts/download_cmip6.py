#!/usr/bin/env python3
"""CMIP6 wrapper; see download_cmip.py."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from download_cmip import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(["--project", "cmip6", *sys.argv[1:]]))
