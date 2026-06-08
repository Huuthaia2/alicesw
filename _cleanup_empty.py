"""
Script quet tat ca file _origin.txt trong origin/ va cache *_orig.txt.
Xac dinh file loi (khong co noi dung thuc, chi co header + tieu de chuong).
In danh sach file can xoa, sau do xoa neu xac nhan.
"""
import os
import re
import sys
from pathlib import Path

ROOT = Path(r"d:\Unity\Python\alicesw\downloaded")
ORIGIN_DIR = ROOT / "origin"
TRANS_DIR  = ROOT / "translated"
CACHE_DIR  = ROOT / ".cache"

def count_real_content(text: str) -> int:
    """Dem so ky tu Han that su (khong phai tieu de/header)."""
    # Loai bo phan header (truoc doan phan cach dau tien)
    lines = text.splitlines()
    content_lines = []
    in_header = True
    for line in lines:
        if '─' * 10 in line and in_header:
            # Dong phan cach dau tien -> bat dau body
            in_header = False
            continue
        if not in_header:
            content_lines.append(line)
    
    body = '\n'.join(content_lines)
    # Dem chu Han trong body (tru tieu de chuong la dong ngan)
    real_chars = 0
    for line in content_lines:
        stripped = line.strip()
        # Bo qua tieu de chuong (第X章 ...) va dong phan cach
        if re.match(r'^第\d+', stripped) or '─' in stripped or '━' in stripped:
            continue
        real_chars += sum(1 for c in stripped if '\u4e00' <= c <= '\u9fff')
    return real_chars

bad_origins  = []  # (file_path, novel_id, tieu_de)
good_origins = []

print("Dang quet origin/...")
for f in sorted(ORIGIN_DIR.glob("*_origin.txt")):
    try:
        text = f.read_text(encoding="utf-8", errors="ignore")
        real_ch = count_real_content(text)
        
        # Lay novel_id tu dong Nguon
        m = re.search(r'/novel/(\d+)', text)
        novel_id = m.group(1) if m else "?"
        
        # Lay so chuong tu ten file
        m2 = re.search(r'\+(\d+) Chuong', f.name)
        num_ch = int(m2.group(1)) if m2 else 0
        
        # Tinh TB ky tu Han moi chuong
        avg = real_ch / max(num_ch, 1)
        
        if real_ch < 100 or avg < 20:
            bad_origins.append((f, novel_id, real_ch, avg, num_ch))
            print(f"  [LOI] {f.name[:60]}  | Han={real_ch}  chuong={num_ch}  avg={avg:.0f}")
        else:
            good_origins.append(f)
    except Exception as e:
        print(f"  [ERR] {f.name}: {e}")

print(f"\nTong: {len(bad_origins)} file loi / {len(bad_origins)+len(good_origins)} file origin")

if not bad_origins:
    print("Khong co file loi!")
    sys.exit(0)

print("\n=== DANH SACH SE XOA ===")
for f, nid, real_ch, avg, num_ch in bad_origins:
    print(f"  origin: {f.name}")
    # Tim cache
    if nid != "?":
        cd = CACHE_DIR / nid
        if cd.exists():
            cache_files = list(cd.glob("*_orig.txt")) + list(cd.glob("*_trans.txt"))
            print(f"    cache ({nid}): {len(cache_files)} files")
    # Tim ban dich
    trans_name = f.name.replace("_origin.txt", ".txt")
    tf = TRANS_DIR / trans_name
    if tf.exists():
        print(f"    trans: {tf.name}")

print("\nBan co muon XOA tat ca cac file loi tren khong? (y/n): ", end="", flush=True)
ans = input().strip().lower()
if ans != "y":
    print("Huy. Khong xoa gi ca.")
    sys.exit(0)

deleted = 0
for f, nid, real_ch, avg, num_ch in bad_origins:
    # Xoa file origin
    try:
        f.unlink()
        print(f"  [XOA] {f.name}")
        deleted += 1
    except Exception as e:
        print(f"  [LOI xoa] {f.name}: {e}")
    
    # Xoa cache
    if nid != "?":
        cd = CACHE_DIR / nid
        if cd.exists():
            for cf in list(cd.glob("*_orig.txt")) + list(cd.glob("*_trans.txt")):
                try:
                    cf.unlink()
                    deleted += 1
                except Exception as e:
                    print(f"    [LOI cache] {cf.name}: {e}")
            # Xoa ca thu muc cache neu trong
            remaining = list(cd.iterdir())
            if not remaining or all(x.name in ("title_vi.txt",) for x in remaining):
                # Giu lai title_vi.txt de khong dich lai ten truyen
                for x in remaining:
                    if x.name != "title_vi.txt":
                        x.unlink()
    
    # Xoa ban dich neu co
    trans_name = f.name.replace("_origin.txt", ".txt")
    tf = TRANS_DIR / trans_name
    if tf.exists():
        try:
            tf.unlink()
            print(f"  [XOA trans] {tf.name}")
            deleted += 1
        except Exception as e:
            print(f"  [LOI] {tf.name}: {e}")

print(f"\nHoan thanh! Da xoa {deleted} file.")
