#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
18av Downloader
===============
Tai truyen tu 18av (https://18av.mm-cg.com) theo tu khoa tim kiem, dich sang
tieng Viet + doi ten rieng Han-Viet, CHONG TRUNG qua registry chung
(downloaded/downloaded_registry.json), luu ra 18av.mm-cg/txt/.

Dac diem site:
  - KHONG co Cloudflare -> dung requests thuan (nhanh, khong can trinh duyet).
  - Chu PHON THE (繁体). Dedup tu dong chuan hoa 简↔繁 (qua opencc) de khop registry.
  - Trang tim kiem : /zh/novel_search/all/<wd>/<page>.html   (page 1..N)
  - Truyen         : /zh/novel_content/<id>/content.html   (1 trang = ca truyen)
  - Noi dung       : span.content_18h_wpcg (cac dong ngan cach boi <br>)
  - Tieu de ket qua: "[The loai]Ten truyen" -> tach [The loai] lam tag.

Tai dung logic cua sosing_downloader (registry dedup + dich + ghi file).

Quy tac chong trung (giong langyou/sosing):
  - Truyen MOI  -> them ban ghi + van tay vao registry, dich va luu txt.
  - Truyen TRUNG -> them link vao ban ghi da co; file txt ten co '_' o dau,
    noi dung chua thong tin ban ghi trung.

Cach dung:
  py -u av18_downloader.py                       # wd=母子, tat ca trang
  py -u av18_downloader.py --wd 母子 --pages 3
  py -u av18_downloader.py --limit 10 --engine caiyun
  py -u av18_downloader.py --workers 5 --engine google
  py -u av18_downloader.py --no-translate        # chi luu ban goc tieng Trung
"""
import os
os.environ.setdefault("PYTHONUNBUFFERED", "1")
import re
import sys
import gzip
import json
import time
import argparse
import threading
import urllib.request
from pathlib import Path
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor

from bs4 import BeautifulSoup

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ── Tai dung sosing_downloader (registry dedup + dich + ghi file) ──
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "sosing.com"))
sys.path.insert(0, str(_ROOT))
import sosing_downloader as sd
dl = sd.dl

BASE = "https://18av.mm-cg.com"
THIS_DIR = Path(__file__).resolve().parent
TXT_DIR = THIS_DIR / "txt"
ORIGIN_DIR = TXT_DIR / "origin"
DONE_FILE = TXT_DIR / "_done.json"

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": BASE + "/",
}
_done_lock = threading.Lock()


def log(msg, tag="*"):
    print(f"[{tag}] {msg}", flush=True)


# ════════════════════════════════════════════════════════════
#  TAI + PARSE
# ════════════════════════════════════════════════════════════
def fetch(url: str, retries: int = 3) -> str | None:
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            r = urllib.request.urlopen(req, timeout=30)
            data = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                data = gzip.decompress(data)
            return data.decode("utf-8", "replace")
        except Exception as e:
            log(f"Loi tai {url}: {str(e)[:80]}", "!")
            time.sleep(2)
    return None


def search_url(wd: str, page: int) -> str:
    return f"{BASE}/zh/novel_search/all/{quote(wd)}/{page}.html"


def story_url(sid: str) -> str:
    return f"{BASE}/zh/novel_content/{sid}/content.html"


_CONTENT_RE = re.compile(r"/novel_content/(\d+)/content\.html")
_CAT_RE = re.compile(r"^\[([^\]]+)\]\s*")   # tach "[The loai]" o dau tieu de
# cac tu khoa cua khung dieu khien co chu (font-size / line-height)
_CTRL_RE = re.compile(r"(文字放大|縮小|原始|放大|自訂|行距|文字大小)")


def collect_stories(html: str) -> list[tuple[str, str, str]]:
    """Tra ve [(url, cn_title, category), ...] tu 1 trang tim kiem (giu thu tu)."""
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        m = _CONTENT_RE.search(a["href"])
        if not m:
            continue
        url = story_url(m.group(1))
        raw = a.get_text(strip=True)
        cm = _CAT_RE.match(raw)
        category = cm.group(1).strip() if cm else ""
        title = _CAT_RE.sub("", raw).strip()
        if url in seen or not title:
            continue
        seen.add(url)
        out.append((url, title, category))
    return out


def parse_story(html: str) -> str:
    """Trich noi dung truyen tu span.content_18h_wpcg (cac dong ngan cach <br>)."""
    soup = BeautifulSoup(html, "html.parser")
    sp = soup.select_one("span.content_18h_wpcg") or soup.select_one(".content")
    if not sp:
        return ""
    for junk in sp.find_all(["script", "style", "input", "ins", "iframe", "a", "select"]):
        junk.decompose()
    txt = sp.get_text("\n")   # <br> khong tao text -> dung separator de ngat dong
    lines = [re.sub(r"[　 \t]+", " ", ln).strip() for ln in txt.split("\n")]
    lines = [ln for ln in lines if ln and not _CTRL_RE.search(ln)]
    return "\n\n".join(lines)


# ════════════════════════════════════════════════════════════
#  RESUME
# ════════════════════════════════════════════════════════════
def load_done() -> set:
    try:
        return set(json.loads(DONE_FILE.read_text(encoding="utf-8")))
    except Exception:
        return set()


def save_done(done: set):
    with _done_lock:
        DONE_FILE.parent.mkdir(parents=True, exist_ok=True)
        DONE_FILE.write_text(json.dumps(sorted(done), ensure_ascii=False, indent=1),
                             encoding="utf-8")


# ════════════════════════════════════════════════════════════
#  XU LY 1 TRUYEN
# ════════════════════════════════════════════════════════════
def process_story(url: str, cn_title: str, category: str,
                  do_translate: bool, done: set) -> bool:
    html = fetch(url)
    if not html:
        return False
    content_cn = parse_story(html)
    if not content_cn.strip():
        log(f"Khong co noi dung: {url}", "!")
        return False

    tags = [category] if category else []

    if not do_translate:
        ORIGIN_DIR.mkdir(parents=True, exist_ok=True)
        m = _CONTENT_RE.search(url)                       # id truyen -> ten file DUY NHAT
        sid = (m.group(1) + "_") if m else ""             # (tranh trung tieu de ghi de nhau)
        p = ORIGIN_DIR / (sid + sd.safe_filename(cn_title) + ".json")
        p.write_text(json.dumps(
            {"url": url, "cn_title": cn_title, "tags": tags, "total_pages": 1,
             "chapters_cn": [content_cn]}, ensure_ascii=False, indent=1), encoding="utf-8")
        log(f"Da luu goc: {p}", "OK")
        return True

    vi_title = sd.translate_title_vi(cn_title)
    planned = str(TXT_DIR / (sd.safe_filename(vi_title) + ".txt"))
    # ── Chong trung qua registry (ten + van tay, chuan hoa 简繁) ──
    is_dup, entry_id, entry = sd.registry_check_and_update(
        cn_title, [content_cn], url, vi_title, translated_path=planned)
    if is_dup:
        path = sd.write_dup_txt(TXT_DIR, vi_title, cn_title, url, entry_id, entry)
        log(f"TRUNG (registry ID {entry_id}) -> them link + luu: {path.name}", "OK")
        return True

    log(f"Moi (ID {entry_id}): {cn_title} -> {vi_title}  ({len(content_cn)} ky tu)")
    vi = sd.translate_block(content_cn)
    tags_vi = sd.translate_tags_vi(tags)
    path = sd.write_story(TXT_DIR, vi_title, cn_title, url, tags_vi, 1, [vi])
    log(f"  Da luu: {path.name}", "OK")
    return True


# ════════════════════════════════════════════════════════════
#  CRAWL
# ════════════════════════════════════════════════════════════
def crawl(wd: str, max_pages: int, limit: int, do_translate: bool,
          workers: int, resume: bool):
    # 1) Thu thap link truyen qua cac trang tim kiem
    stories, seen = [], set()
    page = 1
    while True:
        url = search_url(wd, page)
        log(f"Trang tim kiem {page}: {url}")
        html = fetch(url)
        if not html:
            break
        found = [(u, t, c) for (u, t, c) in collect_stories(html) if u not in seen]
        if not found:
            log("Khong con truyen moi -> dung.")
            break
        for u, t, c in found:
            seen.add(u); stories.append((u, t, c))
        log(f"  +{len(found)} truyen (tong {len(stories)})")
        if limit and len(stories) >= limit:
            stories = stories[:limit]; break
        if max_pages and page >= max_pages:
            break
        page += 1
        time.sleep(0.5)

    done = load_done() if resume else set()
    pending = [(u, t, c) for (u, t, c) in stories if u not in done]
    log(f"Tong {len(stories)} truyen | da xong {len(stories)-len(pending)} | "
        f"se xu ly {len(pending)} (workers={workers}).\n")

    ok = 0
    def _run(item):
        u, t, c = item
        try:
            if process_story(u, t, c, do_translate, done):
                with _done_lock:
                    done.add(u)
                save_done(done)
                return True
        except Exception as e:
            log(f"Loi xu ly {u}: {str(e)[:100]}", "!")
        return False

    if workers <= 1:
        for i, item in enumerate(pending, 1):
            log(f"===== [{i}/{len(pending)}] {item[1][:30]} =====")
            if _run(item):
                ok += 1
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for r in ex.map(_run, pending):
                if r:
                    ok += 1
    log(f"\nHoan tat: {ok}/{len(pending)} truyen.", "OK")


def main():
    ap = argparse.ArgumentParser(description="Tai + dich truyen tu 18av (co chong trung registry)")
    ap.add_argument("--wd", default="母子", help="Tu khoa tim kiem (mac dinh 母子)")
    ap.add_argument("--pages", type=int, default=0, help="Gioi han so trang tim kiem (0 = het)")
    ap.add_argument("--limit", type=int, default=0, help="Gioi han so truyen (0 = tat ca)")
    ap.add_argument("--engine", choices=["free", "caiyun", "google", "gemini"], default="free",
                    help="Engine dich (mac dinh free: Caiyun->Google)")
    ap.add_argument("--gemini-key", default="", help="GEMINI_API_KEY khi --engine gemini")
    ap.add_argument("--workers", type=int, default=1, help="So truyen xu ly song song (mac dinh 1)")
    ap.add_argument("--no-translate", action="store_true",
                    help="Chi luu ban goc tieng Trung (JSON) vao txt/origin/")
    ap.add_argument("--no-resume", action="store_true", help="Khong bo qua truyen da xong")
    args = ap.parse_args()

    dl.ENGINE = args.engine
    if args.engine == "gemini":
        dl.GEMINI_API_KEY = args.gemini_key or os.environ.get("GEMINI_API_KEY", "")
        if not dl.GEMINI_API_KEY:
            log("Thieu --gemini-key / GEMINI_API_KEY", "!"); sys.exit(1)
    elif not dl.TRANSLATE_AVAILABLE and not args.no_translate:
        log("Thu vien 'translators' chua co. Chay: py -m pip install translators", "!")
        sys.exit(1)

    log(f"wd='{args.wd}' | engine={dl.ENGINE} | dich={not args.no_translate} | "
        f"workers={args.workers} | out={TXT_DIR}")
    crawl(args.wd, args.pages, args.limit, not args.no_translate,
          max(1, args.workers), resume=not args.no_resume)


if __name__ == "__main__":
    main()
