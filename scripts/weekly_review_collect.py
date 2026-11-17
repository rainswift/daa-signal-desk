#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股周度复盘数据采集 CLI（逻辑在 backend/app/weekly_collect.py）。

安装依赖：
  cd backend && pip install '.[market]' pandas

运行：
  python scripts/weekly_review_collect.py
  python scripts/weekly_review_collect.py --out-dir ./scripts/output
  python scripts/weekly_review_collect.py --full-industry
  python scripts/weekly_review_collect.py --week-key 2026-W46
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.weekly_collect import main  # noqa: E402


if __name__ == "__main__":
    sys.exit(main())
