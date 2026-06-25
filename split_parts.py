#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gop lai cac file bi chia sai (_1, _2, _3...) roi chia lai dung (_p1, _p2, _p3...).
Logic chia: moi 500 KB them 1 phan (dua tren kich thuoc file goc).
"""

import re, math, sys
from pathlib import Path
from collections import defaultdict

BASE = Path(r"C:\Users\Windows\Documents\MEGA\Python\alicesw\downloaded\mp3\temp\File3Mb")

# ── Clean header ───────────────────────────────────────────────
_SEP_RE = re.compile(r"^[\s─-╿—–=_*#.·•\-]+$")

def clean_text(raw: str) -> str:
    lines = raw.splitlines()
    start = 0
    if lines and _SEP_RE.match(lines[0].strip()):
        for i in range(1, len(lines)):
            if _SEP_RE.match(lines[i].strip()):
                start = i + 1
                break
    else:
        for i, ln in enumerate(lines):
            if ln.strip() == "" or ln.startswith("  "):
                start = i + 1
                continue
            break
    body = lines[start:] if start < len(lines) else lines
    out, blank = [], False
    for ln in body:
        s = ln.strip()
        if not s:
            if not blank and out:
                out.append("")
            blank = True
            continue
        if _SEP_RE.match(s):
            continue
        out.append(s)
        blank = False
    return "\n".join(out).strip()


# ── Chia deu theo ky tu, cat tai ranh gioi dong ───────────────
def split_equal(text: str, n: int) -> list:
    if n <= 1:
        return [text]
    lines = text.splitlines()
    total = sum(len(l) + 1 for l in lines) or 1
    target = total / n
    parts, cur, chars = [], [], 0
    for line in lines:
        cur.append(line)
        chars += len(line) + 1
        if chars >= target and len(parts) < n - 1:
            parts.append("\n".join(cur).strip())
            cur, chars = [], 0
    if cur:
        parts.append("\n".join(cur).strip())
    return [p for p in parts if p]


# ── Main ───────────────────────────────────────────────────────
# Pattern file chia sai: {ten_goc}_N (N la so, khong co chu 'p')
WRONG_PAT = re.compile(r"^(.+?)_(\d+)$")

total_merged = total_split = total_clean_only = 0

part_dirs = sorted(d for d in BASE.iterdir() if d.is_dir() and d.name.startswith("Part"))
if not part_dirs:
    print(f"[!] Khong tim thay thu muc Part* trong {BASE}")
    sys.exit(1)

for part_dir in part_dirs:
    all_txt = [f for f in part_dir.glob("*.txt") if not f.name.startswith("_")]

    # Phan loai: file chia sai vs file don
    groups   = defaultdict(list)   # {orig_stem: [(num, path), ...]}
    lone     = []                  # file don (khong co so cuoi / chi co 1 trong nhom)

    for txt in all_txt:
        # Bo qua file da chia dung (_p1, _p2, ...)
        if re.search(r"_p\d+$", txt.stem):
            continue
        m = WRONG_PAT.match(txt.stem)
        if m:
            groups[m.group(1)].append((int(m.group(2)), txt))
        else:
            lone.append(txt)

    # File chi co 1 thanh phan -> coi la don (khong phai split that su)
    real_groups = {}
    for stem, parts in groups.items():
        if len(parts) >= 2:
            real_groups[stem] = sorted(parts, key=lambda x: x[0])
        else:
            lone.append(parts[0][1])

    print(f"\n[{part_dir.name}] {len(real_groups)} nhom can gop, {len(lone)} file don")

    # ── Gop lai cac nhom sai ──
    to_process = list(lone)   # file can xu ly sau (gop + don)

    for orig_stem, parts in real_groups.items():
        merged_text = "\n".join(
            p.read_text(encoding="utf-8", errors="replace") for _, p in parts
        )
        merged_path = part_dir / f"{orig_stem}.txt"
        merged_path.write_text(merged_text, encoding="utf-8")
        for _, p in parts:
            p.unlink()
        total_merged += 1
        to_process.append(merged_path)

    # ── Chia lai dung (_p1, _p2, ...) ──
    for txt in to_process:
        size_kb = txt.stat().st_size / 1024
        n = max(1, math.ceil(size_kb / 500))

        raw   = txt.read_text(encoding="utf-8", errors="replace")
        clean = clean_text(raw)

        if n == 1:
            txt.write_text(clean, encoding="utf-8")
            total_clean_only += 1
        else:
            parts_text = split_equal(clean, n)
            for i, part_text in enumerate(parts_text, 1):
                out = part_dir / f"{txt.stem}_p{i}.txt"
                out.write_text(part_text, encoding="utf-8")
            txt.unlink()
            total_split += 1

print(f"\n{'='*50}")
print(f"Nhom da gop lai : {total_merged}")
print(f"Da chia lai     : {total_split}  file (>= 500 KB)")
print(f"Chi clean       : {total_clean_only} file (< 500 KB)")
print("Xong!")
