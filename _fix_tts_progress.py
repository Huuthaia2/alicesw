#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fix _tts_progress.json: them entry thieu, xoa entry thua (txt khong con)."""
import sys, json
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

trans_dir = Path("downloaded/translated")
mp3_dir   = trans_dir / "mp3"
prog_file = mp3_dir / "_tts_progress.json"

data = json.loads(prog_file.read_text(encoding="utf-8"))
done = data["done"]

print(f"TTS progress hien tai: {len(done)} entry")

# 1. Xoa entry thua (txt nguon khong con ton tai)
stale = [k for k in list(done.keys()) if not (trans_dir / k).exists()]
for k in stale:
    print(f"  [xoa thua] {k[:70]}")
    del done[k]

# 2. Them entry thieu (txt co mp3 nhung chua co trong progress)
added = 0
no_mp3 = []
for txt in sorted(trans_dir.glob("*.txt")):
    if txt.name.startswith("_"):
        continue
    if txt.name in done:
        # Kiem tra mp3 van con khong
        rec = done[txt.name]
        if (mp3_dir / rec.get("out", "")).exists():
            continue
        print(f"  [reset] {txt.name[:65]} -> mp3 khong con")
        del done[txt.name]

    expected_mp3 = txt.stem + ".mp3"
    if (mp3_dir / expected_mp3).exists():
        st = txt.stat()
        done[txt.name] = {
            "size": st.st_size,
            "mtime": int(st.st_mtime),
            "out": expected_mp3,
        }
        added += 1
        print(f"  + {txt.name[:65]}")
    else:
        no_mp3.append(txt.name)

prog_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

total_txt = sum(1 for _ in trans_dir.glob("*.txt") if not _.name.startswith("_"))
print(f"\n=== Ket qua ===")
print(f"Da them/cap nhat : {added} entry")
print(f"Xoa entry thua   : {len(stale)} entry")
print(f"Chua co mp3      : {len(no_mp3)} file (se xu ly khi chay txt_to_mp3)")
for f in no_mp3:
    print(f"  -> {f}")
print(f"Tong TTS progress: {len(done)} / {total_txt} translated files")
