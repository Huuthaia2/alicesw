#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Quet cac file da dich, gom ten rieng pinyin con sot -> tao/cap nhat glossary.json.

Quy tac loc (tranh false positive):
  - Chi lay cum 2+ tu viet hoa (vd "Zhou Mingming") - tu don qua dang nghia toi nghia
  - Tat ca tu trong cum phai tach duoc 100% thanh am tiet pinyin hop le
  - Loai tu trong KEEP_AS_IS (Martin, Yuko, ...)
  - Xep theo tan suat giam dan -> ten chinh (xuat hien nhieu) hien truoc
  - Them vao glossary.json neu CHUA CO, KHONG de bai entry da co (bao ve sua tay cua ban)
"""
import sys, json, re
from pathlib import Path
from collections import Counter

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import hanviet as hv

TRANS_DIR    = Path("downloaded/translated")
GLOSSARY     = Path("glossary.json")
_NAME_RE     = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b")  # 2+ tu


def load_glossary() -> dict:
    if GLOSSARY.exists():
        try:
            return json.loads(GLOSSARY.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_glossary(data: dict):
    GLOSSARY.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False),
        encoding="utf-8"
    )


def scan():
    counter: Counter = Counter()

    txt_files = [f for f in TRANS_DIR.glob("*.txt") if not f.name.startswith("_")]
    print(f"Quet {len(txt_files)} file translated...")

    for f in txt_files:
        text = f.read_text(encoding="utf-8", errors="replace")
        for m in _NAME_RE.finditer(text):
            phrase = m.group(0)
            # Tat ca tu trong cum phai chuyen duoc het
            words = phrase.split()
            all_ok = all(
                w in hv.KEEP_AS_IS or hv._segment(w.lower()) is not None
                for w in words
            )
            if not all_ok:
                continue
            # Loai neu co tu nao trong KEEP_AS_IS (khong phai ten Trung)
            if any(w in hv.KEEP_AS_IS for w in words):
                continue
            counter[phrase] += 1

    # Gom va chuyen
    candidates = {}
    for phrase, count in counter.most_common():
        converted = hv.convert_names(phrase)
        hv.pop_converted()  # clear log
        if converted != phrase:
            candidates[phrase] = (converted, count)

    # Merge vao glossary hien tai (KHONG ghi de entry da co)
    existing = load_glossary()
    added = 0
    for phrase, (converted, count) in candidates.items():
        if phrase not in existing:
            existing[phrase] = converted
            added += 1

    save_glossary(existing)

    # In bao cao
    print(f"\n=== KET QUA ===")
    print(f"Tim thay  : {len(candidates)} cum ten pinyin")
    print(f"Them moi  : {added} vao glossary.json")
    print(f"Da co san : {len(candidates) - added} (giu nguyen, khong ghi de)")
    print(f"\n--- Top 40 cum xuat hien nhieu nhat ---")
    print(f"{'Pinyin':<30} {'Han Viet':<30} {'So lan'}")
    print("-" * 70)
    for phrase, (converted, count) in list(candidates.items())[:40]:
        mark = "" if phrase in existing else "[MOI]"
        print(f"{phrase:<30} {converted:<30} x{count}  {mark}")

    print(f"\n-> Kiem tra glossary.json, xoa ten sai, giu ten dung. Chay lai de them moi.")
    input("\nNhan Enter de dong...")


if __name__ == "__main__":
    scan()
