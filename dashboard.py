#!/usr/bin/env python
"""Run the local Propsearch dashboard.

Usage:
    python dashboard.py
    python dashboard.py --port 8080
"""
from __future__ import annotations

import argparse

import uvicorn


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--reload", action="store_true", help="Auto-reload on code changes (development)")
    args = ap.parse_args()

    print(f"Propsearch dashboard: http://{args.host}:{args.port}")
    uvicorn.run("dashboard.app:app", host=args.host, port=args.port, reload=args.reload, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
