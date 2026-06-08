#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Quet tat ca file translated, phat hien file con chu Han > nguong,
danh dau fail + xoa file + xoa cache -> alicesw_translate.py se dich lai.
Dong thoi ap dung glossary + ten Han Viet cho file da ok.
"""
import os, sys, json
from pathlib import Path

os.environ.setdefault("PYTHONUNBUFFERED", "1")
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE      = Path(__file__).parent / "downloaded"
TRANS_DIR = BASE / "translated"
CACHE_TR  = BASE / ".cache_translate"
HAN_THRESHOLD = 0.01   # >= 1% chu Han -> fail

PROG_FILE = BASE / "_translated_progress.json"
FAIL_FILE = BASE / "_translated_failed.json"
# file tien do cua watcher dich rieng (trong translated/)
WATCHER_PROG = TRANS_DIR / "_translate_progress.json"

def _han_ratio(text: str) -> float:
    han = sum(1 for c in text if "一" <= c <= "鿿")
    return han / max(len(text), 1)


def load_json(p: Path, default):
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return default


def save_json(p: Path, data):
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def clear_trans_cache(novel_id: str):
    """Xoa cache dich (*_trans.txt) cua truyen -> bat buoc dich lai."""
    d = CACHE_TR / novel_id
    if not d.exists():
        return 0
    removed = 0
    for f in d.glob("*_trans.txt"):
        f.unlink()
        removed += 1
    return removed


# ── Load state files ──────────────────────────────────────────
prog = load_json(PROG_FILE, {})       # {novel_id: filename}
fail = load_json(FAIL_FILE, {})       # {novel_id: reason}
watcher_prog = load_json(WATCHER_PROG, {"done": {}, "failed": {}})

# Reverse map: filename -> novel_id (tu _translated_progress.json)
fname_to_id = {v: k for k, v in prog.items()}

# ── Scan ─────────────────────────────────────────────────────
txts = sorted([f for f in TRANS_DIR.glob("*.txt") if not f.name.startswith("_")],
              key=lambda f: f.stat().st_size)

print(f"Quet {len(txts)} file translated...\n")

bad_files   = []   # (file, ratio, novel_id)
ok_files    = []   # (file, ratio, novel_id)

for f in txts:
    text  = f.read_text(encoding="utf-8", errors="replace")
    ratio = _han_ratio(text)
    nid   = fname_to_id.get(f.name)
    if ratio >= HAN_THRESHOLD:
        bad_files.append((f, ratio, nid))
    else:
        ok_files.append((f, ratio, nid))

# ── Bao cao ──────────────────────────────────────────────────
print(f"{'='*65}")
print(f"  KET QUA QUET")
print(f"{'='*65}")
print(f"  Tong file : {len(txts)}")
print(f"  OK (<5%)  : {len(ok_files)}")
print(f"  LOI (>=5%): {len(bad_files)}")
print()

if bad_files:
    print(f"--- FILE CON CHU HAN ---")
    for f, r, nid in bad_files:
        id_str = nid or "???"
        print(f"  [{r*100:5.1f}%] id={id_str:<8}  {f.name[:70]}")
    print()

    confirm = input("Xoa + danh dau fail de dich lai? (y/N): ").strip().lower()
    if confirm == "y":
        for f, r, nid in bad_files:
            # Xoa file dich
            f.unlink()
            print(f"  [xoa] {f.name[:60]}")

            if nid:
                # Cap nhat _translated_progress.json
                prog.pop(nid, None)
                fail[nid] = f"{r*100:.1f}% Han sot -> danh dau lai"
                # Xoa cache dich
                n = clear_trans_cache(nid)
                if n:
                    print(f"         xoa {n} cache dich (novel_id={nid})")

            # Cap nhat watcher progress (xoa khoi done, cho len failed)
            wname = f.name
            if wname.endswith("_end.txt"):
                origin_name = wname.replace("_end.txt", "_origin_end.txt")
            else:
                origin_name = wname.replace(".txt", "_origin.txt")

            if origin_name in watcher_prog.get("done", {}):
                watcher_prog["done"].pop(origin_name)
            if wname in watcher_prog.get("done", {}):
                watcher_prog["done"].pop(wname)

            watcher_prog.setdefault("failed", {})[origin_name] = {
                "reason": f"{r*100:.1f}% Han sot"
            }
            if wname in watcher_prog.get("failed", {}):
                watcher_prog["failed"].pop(wname)

        save_json(PROG_FILE, prog)
        save_json(FAIL_FILE, fail)
        save_json(WATCHER_PROG, watcher_prog)
        print(f"\n[OK] Da danh dau {len(bad_files)} file fail. Chay alicesw_translate.py de dich lai.")
    else:
        print("[bo qua] Khong thay doi gi.")
else:
    print("Tat ca file translated deu sach (<5% Han).")

# ── Apply glossary + ten Han Viet cho file OK ─────────────────
print()
try:
    sys.path.insert(0, str(Path(__file__).parent))
    import alicesw_translate as tr
    glossary = load_json(Path(__file__).parent / "glossary.json", {})
except ImportError as e:
    print(f"[!] Khong import duoc module: {e}")
    sys.exit(0)

if not ok_files:
    sys.exit(0)

fix_confirm = input(f"\nAp dung glossary + ten Han Viet cho {len(ok_files)} file OK? (y/N): ").strip().lower()
if fix_confirm != "y":
    print("[bo qua]")
    sys.exit(0)

fixed_count = 0
for f, r, nid in ok_files:
    raw = f.read_text(encoding="utf-8", errors="replace")

    # 1. Glossary (ten rieng duyet tay)
    fixed = raw
    for src, dst in glossary.items():
        fixed = fixed.replace(src, dst)

    # 2. Auto-convert cum pinyin 2+ tu hoa -> Han Viet
    tr.convert_names_safe(fixed)
    fixed = tr.convert_names_safe._last

    if fixed != raw:
        f.write_text(fixed, encoding="utf-8")
        fixed_count += 1
        print(f"  [fix] {f.name[:65]}")

print(f"\n[OK] Da fix ten {fixed_count}/{len(ok_files)} file.")
