#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Doi ten hang loat cac file ĐÃ tai/tao truoc day theo quy tac dat ten moi:
  - Bo HET cum [ ... ] (ca noi dung - tag the loai).
  - Voi 【 】: chi bo dau ngoac, giu noi dung.
  - Sentence case: chi hoa chu cai dau tien, con lai viet thuong.
  - Giu nguyen duoi "+N Chuong" / "+N Chuong_origin".

Pham vi: downloaded/origin/*.txt, downloaded/translated/*.txt,
         downloaded/translated/mp3/*.mp3  (+ cap nhat _tts_progress.json).

Cach dung:
  py _rename_clean.py            # XEM TRUOC (khong doi gi)
  py _rename_clean.py --apply    # THUC THI doi ten
"""
import os
os.environ.setdefault("PYTHONUNBUFFERED", "1")
import re
import sys
import json
import argparse
from pathlib import Path

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def clean_title(name: str) -> str:
    name = re.sub(r"\[[^\]]*\]", " ", name)   # bo [tag] ke ca noi dung
    name = re.sub(r"[【】\[\]]", " ", name)     # bo dau 【 】 va [ ] le con sot (giu noi dung)
    name = re.sub(r"\s+", " ", name).strip()
    if name:
        name = name[0].upper() + name[1:].lower()
    return name


def output_stem(stem: str) -> str:
    """Chuan hoa phan ten, giu nguyen duoi '+N Chuong...' (vd '+5 Chuong_origin')."""
    m = re.match(r"^(.*?)(\+\d+\s*Chuong.*)$", stem)
    if m:
        return clean_title(m.group(1)) + m.group(2)
    return clean_title(stem)


def plan_dir(d: Path, pattern: str):
    """Tra ve list (old_path, new_path) can doi ten + list collision THAT SU.

    Luu y Windows khong phan biet hoa/thuong: doi 'abc' -> 'Abc' thi target.exists()
    van True vi tro ve CHINH file do. Day KHONG phai collision - chi la doi case.
    Chi coi la trung khi target la file KHAC (ten viet thuong khac nhau).
    """
    renames, collisions = [], []
    if not d.exists():
        return renames, collisions
    for f in sorted(d.glob(pattern)):
        if f.name.startswith("_"):            # bo file he thong
            continue
        new_name = output_stem(f.stem) + f.suffix
        if new_name == f.name:
            continue
        target = f.with_name(new_name)
        # Collision that su: target ton tai VA la file khac (khong phai chinh f doi case)
        if target.exists() and target.name.lower() != f.name.lower():
            collisions.append((f, target))
        else:
            renames.append((f, target))
    return renames, collisions


def safe_rename(old: Path, new: Path):
    """Doi ten an toan; rieng truong hop chi doi hoa/thuong thi qua file tam (Windows)."""
    if old.name == new.name:
        return
    if old.name.lower() == new.name.lower():
        tmp = old.with_name(old.name + ".tmprn")
        old.rename(tmp)
        tmp.rename(new)
    else:
        old.rename(new)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="downloaded", help="Thu muc goc (mac dinh: downloaded)")
    ap.add_argument("--apply", action="store_true", help="Thuc thi doi ten (mac dinh chi xem truoc)")
    args = ap.parse_args()

    base = Path(args.base)
    origin = base / "origin"
    trans  = base / "translated"
    mp3dir = trans / "mp3"

    targets = [
        ("origin (.txt)",     origin, "*.txt"),
        ("translated (.txt)", trans,  "*.txt"),
        ("mp3 (.mp3)",        mp3dir, "*.mp3"),
    ]

    total_ren, total_col = 0, 0
    mode = "THUC THI" if args.apply else "XEM TRUOC (chua doi gi - them --apply de doi that)"
    print(f"{'='*64}\n  Doi ten file - che do: {mode}\n{'='*64}")

    for label, d, pat in targets:
        renames, collisions = plan_dir(d, pat)
        total_ren += len(renames)
        total_col += len(collisions)
        print(f"\n── {label}: {len(renames)} doi ten, {len(collisions)} trung ten ──")
        for old, new in renames[:5]:
            print(f"  {old.name}\n   -> {new.name}")
        if len(renames) > 5:
            print(f"  ... va {len(renames)-5} file khac")
        for old, new in collisions:
            print(f"  [TRUNG - BO QUA] {old.name}\n   -> da ton tai: {new.name}")

        if args.apply:
            for old, new in renames:
                try:
                    safe_rename(old, new)
                except Exception as e:
                    print(f"  [LOI] {old.name}: {e}")

    # ── Cap nhat _tts_progress.json (key = ten txt translated, va truong 'out') ──
    prog = mp3dir / "_tts_progress.json"
    if prog.exists():
        try:
            data = json.loads(prog.read_text(encoding="utf-8"))
            done = data.get("done", {})
            new_done = {}
            for old_key, rec in done.items():
                new_key = output_stem(Path(old_key).stem) + Path(old_key).suffix
                if isinstance(rec, dict) and rec.get("out"):
                    o = Path(rec["out"])
                    rec["out"] = output_stem(o.stem) + o.suffix
                new_done[new_key] = rec
            data["done"] = new_done
            print(f"\n── _tts_progress.json: cap nhat {len(new_done)} entry ──")
            if args.apply:
                prog.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                print("  [OK] da ghi lai _tts_progress.json")
        except Exception as e:
            print(f"  [LOI] doc/ghi _tts_progress.json: {e}")

    print(f"\n{'='*64}")
    print(f"  Tong: {total_ren} file se doi ten, {total_col} file trung ten (bo qua).")
    if not args.apply:
        print("  -> Chay lai voi --apply de thuc hien doi ten that.")
    else:
        print("  -> Da hoan thanh doi ten.")
    print(f"{'='*64}")


if __name__ == "__main__":
    main()
