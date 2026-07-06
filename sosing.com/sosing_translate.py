#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sosing Translate (luong DICH rieng)
===================================
Theo doi thu muc txt/origin/*.json (ban goc tieng Trung do sosing_downloader.py
--no-translate tao ra), dich sang tieng Viet + doi ten rieng Han-Viet, luu ra
txt/*.txt.  Chay SONG SONG voi tool tai (2 cua so):

  Cua so 1 (lay truyen, nhanh):
      py -u sosing_downloader.py --tag 13 --no-translate
  Cua so 2 (dich, chay lien tuc):
      py -u sosing_translate.py

Dac diem:
  - Tai dung TOAN BO logic dich cua sosing_downloader (Caiyun/Google/Gemini +
    convert Han-Viet + loc quang cao) qua import -> khong nhan doi code.
  - Resume: moi truyen dich xong ghi vao txt/_translated.json -> gian doan van
    tiep tuc duoc. Truyen da co file .txt cung duoc bo qua.
  - --once: quet 1 lan roi thoat. Mac dinh: quet lien tuc moi vai giay.
  - --workers N: dich N truyen SONG SONG (mac dinh 1; 2-3 nhanh hon nhung de bi
    rate-limit hon).

Cach dung:
  py -u sosing_translate.py                 # quet lien tuc, engine free
  py -u sosing_translate.py --engine caiyun
  py -u sosing_translate.py --once
  py -u sosing_translate.py --workers 2 --engine caiyun
  py -u sosing_translate.py --engine gemini --gemini-key <KEY>
"""
import os
os.environ.setdefault("PYTHONUNBUFFERED", "1")
import sys
import json
import time
import argparse
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

# Tai dung toan bo helper cua sosing_downloader (dich, ghi file, log, duong dan)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import sosing_downloader as sd
dl = sd.dl

SCAN_INTERVAL = 4.0                       # giay giua cac lan quet (che do lien tuc)
_PROGRESS = sd.TXT_DIR / "_translated.json"
_prog_lock = threading.Lock()


def log(msg, tag="*"):
    print(f"[{tag}] {msg}", flush=True)


def load_done() -> set:
    try:
        return set(json.loads(_PROGRESS.read_text(encoding="utf-8")))
    except Exception:
        return set()


def save_done(done: set):
    with _prog_lock:
        _PROGRESS.parent.mkdir(parents=True, exist_ok=True)
        _PROGRESS.write_text(json.dumps(sorted(done), ensure_ascii=False, indent=1),
                             encoding="utf-8")


def translate_one(jf: Path) -> str | None:
    """Dich 1 file goc JSON -> ghi txt tieng Viet. Tra ve url neu thanh cong."""
    try:
        data = json.loads(jf.read_text(encoding="utf-8"))
    except Exception as e:
        log(f"Loi doc {jf.name}: {e}", "!")
        return None

    url = data.get("url", "")
    cn_title = data.get("cn_title", jf.stem)
    tags = data.get("tags", [])
    total = data.get("total_pages", len(data.get("chapters_cn", [])))
    chapters_cn = data.get("chapters_cn", [])
    if not chapters_cn:
        log(f"Bo qua (rong): {jf.name}", "!")
        return None

    vi_title = sd.translate_title_vi(cn_title)
    planned = str(sd.TXT_DIR / (sd.safe_filename(vi_title) + ".txt"))

    # ── Check trung TRUOC khi dich (theo ten + van tay noi dung) ──
    is_dup, entry_id, entry = sd.registry_check_and_update(
        cn_title, chapters_cn, url, vi_title, translated_path=planned)
    if is_dup:
        path = sd.write_dup_txt(sd.TXT_DIR, vi_title, cn_title, url, entry_id, entry)
        log(f"TRUNG (registry ID {entry_id}) -> them link + luu: {path}", "OK")
        return url or str(jf)

    tags_vi = sd.translate_tags_vi(tags)
    log(f"Moi (registry ID {entry_id}). Dich: {cn_title} -> {vi_title} ({total} phan)")
    chapters = []
    for i, cn in enumerate(chapters_cn, 1):
        log(f"  phan {i}/{total} ({len(cn)} ky tu)...")
        chapters.append(sd.translate_block(cn))

    path = sd.write_story(sd.TXT_DIR, vi_title, cn_title, url, tags_vi, total, chapters)
    log(f"  Da luu: {path}", "OK")
    return url or str(jf)


def scan_once(done: set, workers: int) -> int:
    """Quet origin/*.json, dich cac truyen chua xong. Tra ve so truyen vua dich."""
    if not sd.ORIGIN_DIR.exists():
        return 0
    pending = []
    for jf in sorted(sd.ORIGIN_DIR.glob("*.json")):
        try:
            url = json.loads(jf.read_text(encoding="utf-8")).get("url", str(jf))
        except Exception:
            url = str(jf)
        if url not in done:
            pending.append((jf, url))
    if not pending:
        return 0

    n_ok = 0
    if workers <= 1:
        for jf, url in pending:
            if translate_one(jf):
                done.add(url); save_done(done); n_ok += 1
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(translate_one, jf): url for jf, url in pending}
            for fut in futs:
                try:
                    if fut.result():
                        done.add(futs[fut]); save_done(done); n_ok += 1
                except Exception as e:
                    log(f"Loi dich: {e}", "!")
    return n_ok


def main():
    ap = argparse.ArgumentParser(description="Luong dich rieng cho sosing (JSON goc -> txt Viet)")
    ap.add_argument("--engine", choices=["free", "caiyun", "google", "gemini"],
                    default="free", help="Engine dich (mac dinh free: Caiyun->Google)")
    ap.add_argument("--gemini-key", default="", help="GEMINI_API_KEY khi --engine gemini")
    ap.add_argument("--workers", type=int, default=1,
                    help="So truyen dich song song (mac dinh 1)")
    ap.add_argument("--once", action="store_true", help="Quet 1 lan roi thoat")
    args = ap.parse_args()

    dl.ENGINE = args.engine
    if args.engine == "gemini":
        dl.GEMINI_API_KEY = args.gemini_key or os.environ.get("GEMINI_API_KEY", "")
        if not dl.GEMINI_API_KEY:
            log("Thieu --gemini-key / GEMINI_API_KEY", "!"); sys.exit(1)
    elif not dl.TRANSLATE_AVAILABLE:
        log("Thu vien 'translators' chua co. Chay: py -m pip install translators", "!")
        sys.exit(1)

    log(f"Engine dich: {dl.ENGINE} | workers: {args.workers} | "
        f"Doc goc: {sd.ORIGIN_DIR} -> {sd.TXT_DIR}")
    done = load_done()

    if args.once:
        n = scan_once(done, args.workers)
        log(f"Xong 1 luot: dich {n} truyen.", "OK")
        return

    log("Che do lien tuc — quet origin/ moi vai giay. Ctrl+C de dung.")
    idle = 0
    try:
        while True:
            n = scan_once(done, args.workers)
            if n == 0:
                idle += 1
                if idle % 15 == 1:
                    log("Chua co truyen goc moi de dich... (dang cho luong tai)")
                time.sleep(SCAN_INTERVAL)
            else:
                idle = 0
    except KeyboardInterrupt:
        log("Da dung.", "OK")


if __name__ == "__main__":
    main()
