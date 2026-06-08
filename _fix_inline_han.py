#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dich in-place cac doan/cau tieng Trung con sot trong file translated.
KHONG xoa file - chi tim dung doan Han, dich, vat lai.
"""
import os, sys, time
os.environ.setdefault("PYTHONUNBUFFERED", "1")
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from pathlib import Path
import alicesw_downloader as dl

TRANS_DIR  = Path(__file__).parent / "downloaded" / "translated"
HAN_INLINE = 0.003   # file co >= 0.3% Han moi xu ly
MIN_HAN    = 6       # doan Han phai co >= 6 chu Han moi dich


def han_ratio(text: str) -> float:
    n = sum(1 for c in text if "一" <= c <= "鿿")
    return n / max(len(text), 1)


def is_han(c: str) -> bool:
    return "一" <= c <= "鿿"


def extract_han_spans(line: str) -> list:
    """
    Tim cac doan 'Han-dense' trong 1 dong.
    Thuat toan: mo rong doan khi gap chu Han, dong lai khi gap khoang trang/Latin
    dai > 8 ky tu LIEN TUC khong co Han.
    Tra ve list[(start, end)] - chi giu doan co >= MIN_HAN chu Han.
    """
    spans = []
    i = 0
    n = len(line)
    while i < n:
        if not is_han(line[i]):
            i += 1
            continue
        # Bat dau doan Han
        start = i
        non_han_run = 0
        j = i
        while j < n:
            if is_han(line[j]):
                non_han_run = 0
            else:
                non_han_run += 1
                # Neu gap >= 9 ky tu lien tuc khong Han -> dong doan
                if non_han_run >= 9:
                    j = j - non_han_run + 1
                    break
            j += 1
        end = j
        chunk = line[start:end].rstrip()
        han_count = sum(1 for c in chunk if is_han(c))
        if han_count >= MIN_HAN:
            spans.append((start, start + len(chunk)))
        i = end + 1
    return spans


def translate_span(text: str) -> str:
    """Dich 1 doan Han. Tra ve ban dich hoac giu nguyen neu that bai."""
    result, _ = dl.translate_text(text)
    if han_ratio(result) > 0.3:
        return text  # van con nhieu Han -> giu nguyen
    return result


def fix_file(path: Path) -> int:
    raw = path.read_text(encoding="utf-8", errors="replace")
    if han_ratio(raw) < HAN_INLINE:
        return 0

    lines = raw.split("\n")
    changed = 0

    for idx, line in enumerate(lines):
        if not any(is_han(c) for c in line):
            continue
        if han_ratio(line) < 0.05:
            continue  # it Han, co the chi ten rieng -> bo qua

        spans = extract_han_spans(line)
        if not spans:
            continue

        new_line = line
        offset = 0
        for start, end in spans:
            s, e = start + offset, end + offset
            han_text = new_line[s:e]
            translated = translate_span(han_text)
            if translated != han_text:
                new_line = new_line[:s] + translated + new_line[e:]
                offset += len(translated) - len(han_text)
                dl._log(f"  [{idx+1}] {han_text[:35]!r} -> {translated[:35]!r}", "ok")
                changed += 1
            else:
                dl._log(f"  [{idx+1}] Khong dich duoc: {han_text[:50]!r}", "warn")
            time.sleep(0.3)

        lines[idx] = new_line

    if changed:
        path.write_text("\n".join(lines), encoding="utf-8")

    return changed


def main():
    files = sorted(
        [f for f in TRANS_DIR.glob("*.txt") if not f.name.startswith("_")],
        key=lambda f: f.stat().st_size
    )

    candidates = []
    for f in files:
        t = f.read_text(encoding="utf-8", errors="replace")
        r = han_ratio(t)
        if r >= HAN_INLINE:
            candidates.append((f, r))

    print(f"Tim thay {len(candidates)} file con chu Han (>= {HAN_INLINE*100:.1f}%):\n")
    for f, r in candidates:
        print(f"  {r*100:.3f}%  {f.name[:75]}")

    if not candidates:
        print("Tat ca file sach.")
        return

    print()
    confirm = input("Dich in-place? (y/N): ").strip().lower()
    if confirm != "y":
        print("Bo qua.")
        return

    total_fixed = 0
    for f, r in candidates:
        dl._log(f"\n=== {f.name[:65]} ({r*100:.2f}% Han) ===")
        n = fix_file(f)
        dl._log(f"    {n} doan da sua.", "ok" if n else "")
        total_fixed += n

    print(f"\n[OK] Tong cong {total_fixed} doan da duoc dich in-place.")


if __name__ == "__main__":
    main()
