#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tìm và đổi tên các file trong downloaded/ còn chứa chữ Hán tự.
Ưu tiên dịch qua Caiyun/Google; fallback sang âm Hán Việt.
"""

import sys
import re
import time
from pathlib import Path

import hanviet as _hv

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ── Cố gắng dùng translators nếu có ─────────────────────────
try:
    import translators as _ts
    _TRANSLATE_OK = True
except Exception:
    _TRANSLATE_OK = False

BASE = Path(__file__).parent / "downloaded"
DIRS = [BASE / "origin", BASE / "translated"]

_SUFFIX_RE = re.compile(r"^(.+?)(\+\d+ Chuong(?:_origin)?\.txt)$")
_BAD_WIN = re.compile(r'[:*?"<>|]')


def sanitize(name: str) -> str:
    return _BAD_WIN.sub("_", name).strip()


def translate_api(title: str) -> str | None:
    if not _TRANSLATE_OK:
        return None
    for eng in ["caiyun", "google"]:
        try:
            result = _ts.translate_text(title, translator=eng,
                                        from_language="zh", to_language="vi")
            if result and result.strip() and not _hv.has_hanzi(result):
                time.sleep(0.8)
                return result.splitlines()[0].strip()
        except Exception:
            pass
    return None


def vi_name(title: str) -> str:
    via_api = translate_api(title)
    if via_api:
        return sanitize(via_api)
    return sanitize(_hv.hanzi_to_hanviet(title))


def rename_files():
    renamed = []
    for folder in DIRS:
        if not folder.exists():
            continue
        for f in sorted(folder.iterdir()):
            if not _hv.has_hanzi(f.name):
                continue
            m = _SUFFIX_RE.match(f.name)
            if not m:
                print(f"[?] Bỏ qua (không khớp pattern): {f.name}")
                continue
            old_title, suffix = m.group(1), m.group(2)
            print(f"\n[*] Đang xử lý: {f.name}")
            new_title = vi_name(old_title)
            if not new_title or new_title == old_title:
                print(f"[!] Không dịch được, giữ nguyên.")
                continue
            new_name = new_title + suffix
            dest = folder / new_name
            if dest.exists():
                print(f"[!] File đích đã tồn tại, bỏ qua: {new_name}")
                continue
            f.rename(dest)
            print(f"[OK] {f.name}")
            print(f"  -> {new_name}")
            renamed.append((str(f), str(dest)))

    print(f"\n{'='*60}")
    print(f"Đã đổi tên {len(renamed)} file.")
    return renamed


if __name__ == "__main__":
    rename_files()
