#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
18av Translate (luong DICH rieng)
=================================
Theo doi 18av.mm-cg/txt/origin/*.json (ban goc do av18_downloader.py
--no-translate tao ra), dich sang tieng Viet + chong trung registry, luu ra
18av.mm-cg/txt/.  Chay SONG SONG voi luong tai (2 cua so):

  Cua so 1 (lay truyen, nhanh):
      py -u av18_downloader.py --wd 母子 --no-translate
  Cua so 2 (dich, chay lien tuc):
      py -u av18_translate.py --engine caiyun --workers 5

Tai dung toan bo logic dich + chong trung cua sosing_downloader (registry
check_and_update, translate, write) va cac duong dan cua av18_downloader.
Resume qua txt/_translated.json.
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import av18_downloader as ld      # duong dan TXT_DIR / ORIGIN_DIR + fetch config
import sosing_downloader as sd    # registry dedup + dich + ghi file
dl = sd.dl

PROGRESS = ld.TXT_DIR / "_translated.json"
_lock = threading.Lock()


def log(msg, tag="*"):
    print(f"[{tag}] {msg}", flush=True)


def load_done() -> set:
    try:
        return set(json.loads(PROGRESS.read_text(encoding="utf-8")))
    except Exception:
        return set()


def save_done(done: set):
    with _lock:
        PROGRESS.parent.mkdir(parents=True, exist_ok=True)
        PROGRESS.write_text(json.dumps(sorted(done), ensure_ascii=False, indent=1),
                            encoding="utf-8")


def translate_one(jf: Path) -> str | None:
    try:
        d = json.loads(jf.read_text(encoding="utf-8"))
    except Exception as e:
        log(f"Loi doc {jf.name}: {e}", "!"); return None

    url = d.get("url", "")
    cn_title = d.get("cn_title", jf.stem)
    tags = d.get("tags", [])
    total = d.get("total_pages", len(d.get("chapters_cn", [])))
    chapters_cn = d.get("chapters_cn", [])
    if not chapters_cn:
        log(f"Bo qua (rong): {jf.name}", "!"); return None

    vi_title = sd.translate_title_vi(cn_title)
    planned = str(ld.TXT_DIR / (sd.safe_filename(vi_title) + ".txt"))
    is_dup, entry_id, entry = sd.registry_check_and_update(
        cn_title, chapters_cn, url, vi_title, translated_path=planned)
    if is_dup:
        path = sd.write_dup_txt(ld.TXT_DIR, vi_title, cn_title, url, entry_id, entry)
        log(f"TRUNG (registry ID {entry_id}) -> them link + luu: {path.name}", "OK")
        return url or str(jf)

    log(f"Moi (ID {entry_id}): {cn_title} -> {vi_title} ({total} phan)")
    chapters = []
    for i, cn in enumerate(chapters_cn, 1):
        log(f"  phan {i}/{total} ({len(cn)} ky tu)...")
        chapters.append(sd.translate_block(cn))
    tags_vi = sd.translate_tags_vi(tags)
    path = sd.write_story(ld.TXT_DIR, vi_title, cn_title, url, tags_vi, total, chapters)
    log(f"  Da luu: {path.name}", "OK")
    return url or str(jf)


def scan_once(done: set, workers: int) -> int:
    if not ld.ORIGIN_DIR.exists():
        return 0
    pending = []
    for jf in sorted(ld.ORIGIN_DIR.glob("*.json")):
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
    ap = argparse.ArgumentParser(description="Luong dich rieng cho 18av (JSON goc -> txt Viet)")
    ap.add_argument("--engine", choices=["free", "caiyun", "google", "gemini"], default="free")
    ap.add_argument("--gemini-key", default="")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--once", action="store_true", help="Quet 1 lan roi thoat")
    args = ap.parse_args()

    dl.ENGINE = args.engine
    if args.engine == "gemini":
        dl.GEMINI_API_KEY = args.gemini_key or os.environ.get("GEMINI_API_KEY", "")
        if not dl.GEMINI_API_KEY:
            log("Thieu --gemini-key / GEMINI_API_KEY", "!"); sys.exit(1)
    elif not dl.TRANSLATE_AVAILABLE:
        log("Thu vien 'translators' chua co.", "!"); sys.exit(1)

    log(f"Engine={dl.ENGINE} | workers={args.workers} | "
        f"Doc goc: {ld.ORIGIN_DIR} -> {ld.TXT_DIR}")
    done = load_done()
    if args.once:
        log(f"Xong 1 luot: dich {scan_once(done, args.workers)} truyen.", "OK"); return

    log("Che do lien tuc — quet origin/ moi vai giay. Ctrl+C de dung.")
    idle = 0
    try:
        while True:
            n = scan_once(done, args.workers)
            if n == 0:
                idle += 1
                if idle % 15 == 1:
                    log("Chua co truyen goc moi de dich... (dang cho luong tai)")
                time.sleep(4.0)
            else:
                idle = 0
    except KeyboardInterrupt:
        log("Da dung.", "OK")


if __name__ == "__main__":
    main()
