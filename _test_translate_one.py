#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test dich 1 file origin cu the bang Caiyun.
Dung luong: py _test_translate_one.py <duong_dan_file_origin>
"""
import sys
import os
os.environ.setdefault("PYTHONUNBUFFERED", "1")
from pathlib import Path

# Them thu muc cha vao sys.path de import duoc
sys.path.insert(0, str(Path(__file__).parent))

import alicesw_translate as tr
import alicesw_downloader as dl

def main():
    if len(sys.argv) < 2:
        print("Usage: py _test_translate_one.py <duong_dan_file_origin>")
        sys.exit(1)

    origin = Path(sys.argv[1]).resolve()
    if not origin.exists():
        print(f"[!] Khong tim thay file: {origin}")
        sys.exit(1)

    # Thu muc output
    trans_dir  = origin.parent.parent / "translated"
    cache_root = origin.parent.parent / ".cache_translate"
    trans_dir.mkdir(parents=True, exist_ok=True)
    cache_root.mkdir(parents=True, exist_ok=True)

    # Dung Caiyun thuan tuy
    dl.ENGINE = "caiyun"

    print(f"[TEST] Dich: {origin.name}")
    print(f"       -> {trans_dir}")
    ok, out_name = tr.process_origin_file(origin, trans_dir, cache_root)
    if ok:
        print(f"\n[OK] Dich thanh cong: {out_name}")
    else:
        print(f"\n[WARN] Dich co loi / Han sot, file khong giu: {out_name}")

if __name__ == "__main__":
    main()
