#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys, json
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

origin_dir = Path("downloaded/origin")
trans_dir  = Path("downloaded/translated")
prog_file  = trans_dir / "_translate_progress.json"

data = json.loads(prog_file.read_text(encoding="utf-8"))
done = data["done"]

print(f"Progress hien tai: {len(done)} entry")

added = 0
missing = []
for origin in sorted(origin_dir.glob("*.txt")):
    if origin.name.startswith("_"):
        continue
    if origin.name in done:
        # Kiem tra out file con ton tai khong
        rec = done[origin.name]
        out_name = rec.get("out", "")
        if out_name and (trans_dir / out_name).exists():
            continue  # ok roi
        # File dich bi xoa hoac chua co -> rebuild
        print(f"  [reset] {origin.name[:65]} -> out khong con ton tai")
        del done[origin.name]

    # Thu khop: _origin.txt -> .txt
    expected_out = origin.name.replace("_origin.txt", ".txt")
    if (trans_dir / expected_out).exists():
        st = origin.stat()
        done[origin.name] = {
            "size": st.st_size,
            "mtime": int(st.st_mtime),
            "out": expected_out,
        }
        added += 1
        print(f"  + {origin.name[:65]}")
    else:
        missing.append(origin.name)

# Kiem tra entry thua (origin file khong con)
stale = [k for k in list(done.keys()) if not (origin_dir / k).exists()]
for k in stale:
    print(f"  [xoa thua] {k[:65]}")
    del done[k]

prog_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

print(f"\n=== Ket qua ===")
print(f"Da them/cap nhat : {added} entry")
print(f"Xoa entry thua   : {len(stale)} entry")
print(f"Thieu ban dich   : {len(missing)} entry")
for m in missing:
    print(f"  ? {m}")
print(f"Tong progress    : {len(done)} / {sum(1 for _ in origin_dir.glob('*.txt') if not _.name.startswith('_'))} origin files")
