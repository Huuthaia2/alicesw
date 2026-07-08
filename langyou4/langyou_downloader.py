#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Langyou Downloader - Tai truyen tu langyou4.langyou895.cc (狼友小说)

Crawl cac trang tim kiem (artsearch) theo tu khoa -> lay link truyen (artdetail)
-> tai noi dung -> them header -> dich Google (zh->vi) -> convert ten rieng sang
Han Viet -> luu file .txt vao thu muc langyou4/.

Chay:
  py langyou_downloader.py            # mo giao dien (UI)
  py langyou_downloader.py --cli      # chay dong lenh (khong UI)
"""

import os
os.environ.setdefault("PYTHONUNBUFFERED", "1")
os.environ.setdefault("translators_default_region", "EN")

import re
import sys
import time
import json
import argparse
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

# ─── Unicode console fix ─────────────────────────────────────
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# File nay nam trong langyou4/; them thu muc goc du an vao path
# de dung chung hanviet.py / glossary.json voi cac tool khac.
_ROOT_DIR = Path(__file__).resolve().parent.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

# ─── Optional deps (dung chung voi cac tool khac trong du an) ─
try:
    import hanviet as _hv
    _HV_AVAILABLE = True
except ImportError:
    _hv = None
    _HV_AVAILABLE = False

try:
    import translators as _ts
    _TRANSLATE_AVAILABLE = True
except Exception:
    _ts = None
    _TRANSLATE_AVAILABLE = False

try:
    import novel_manager as _nm
    _NM_AVAILABLE = True
except ImportError:
    _nm = None
    _NM_AVAILABLE = False

# Registry dung chung (o thu muc goc du an) de check trung truyen da tai
REGISTRY_PATH = _ROOT_DIR / "downloaded" / "downloaded_registry.json"

# ─── Config ──────────────────────────────────────────────────
BASE_URL   = "https://langyou4.langyou895.cc"
SEARCH_TPL = BASE_URL + "/artsearch/{kw}------{page}-.html"

SCRIPT_DIR  = Path(__file__).resolve().parent   # = ...\langyou4
DEFAULT_OUT = SCRIPT_DIR / "downloaded"          # luu txt + _progress.json vao langyou4\downloaded

DEFAULT_KEYWORD = "母子"
DEFAULT_START   = 1
DEFAULT_END     = 60
DELAY           = 1.2      # delay giua cac request (giay)
TRANS_DELAY     = 0.6      # delay sau moi chunk dich (moi luong)
TRANS_WORKERS   = 3        # so luong dich song song
MAX_CHUNK       = 4500     # gioi han ky tu moi lan goi Google

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": BASE_URL,
}

session = requests.Session()
session.headers.update(HEADERS)

# ─── Glossary (pinyin/ten rieng -> Han Viet) ─────────────────
_GLOSSARY_FILE = _ROOT_DIR / "glossary.json"
_glossary: dict = {}


def _load_glossary():
    global _glossary
    if _GLOSSARY_FILE.exists():
        try:
            _glossary = json.loads(_GLOSSARY_FILE.read_text(encoding="utf-8"))
        except Exception:
            _glossary = {}


def _apply_glossary(text: str) -> str:
    if not _glossary or not text:
        return text
    for src, dst in _glossary.items():
        if src in text:
            text = text.replace(src, dst)
    return text


# ─── HTTP helper ─────────────────────────────────────────────
def get_html(url: str, retries: int = 3, log=print):
    for attempt in range(retries):
        try:
            resp = session.get(url, timeout=25)
            resp.raise_for_status()
            resp.encoding = "utf-8"
            return BeautifulSoup(resp.text, "html.parser")
        except Exception as e:
            log(f"  [Loi tai] {url[:70]} (lan {attempt+1}): {e}")
            if attempt < retries - 1:
                time.sleep(3 + attempt * 2)
    return None


# ─── Search listing parser ───────────────────────────────────
_DATE_SUFFIX_RE = re.compile(r"\s*\d{1,2}[-/]\d{1,2}\s*$")


def get_search_page(keyword: str, page: int, log=print) -> list:
    """Tra ve list[{title, url}] cac truyen tren 1 trang tim kiem."""
    url = SEARCH_TPL.format(kw=quote(keyword), page=page)
    soup = get_html(url, log=log)
    if not soup:
        return []

    novels, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href.startswith("/artdetail-"):
            continue
        full = BASE_URL + href
        if full in seen:
            continue
        seen.add(full)
        title = _DATE_SUFFIX_RE.sub("", a.get_text(strip=True))
        novels.append({"title": title, "url": full})
    return novels


# ─── Category map (Han -> Viet) ──────────────────────────────
_CATEGORY_MAP = {
    "人妻": "Nhân thê", "都市": "Đô thị", "校园": "Học đường", "校園": "Học đường",
    "武侠": "Võ hiệp", "武俠": "Võ hiệp", "乱伦": "Loạn luân", "亂倫": "Loạn luân",
    "职场": "Công sở", "職場": "Công sở", "经验": "Kinh nghiệm", "經驗": "Kinh nghiệm",
    "暴力": "Bạo lực", "幻想": "Huyễn tưởng", "明星": "Minh tinh",
    "母子": "Mẹ con", "母女": "Mẹ con gái", "熟女": "Thục nữ",
}


def _category_vi(cat: str) -> str:
    c = cat.strip()
    if c in _CATEGORY_MAP:
        return _CATEGORY_MAP[c]
    if _HV_AVAILABLE and _hv.has_hanzi(c):
        return _hv.hanzi_to_hanviet(c)
    return c


# ─── Title / content cleaning ────────────────────────────────
_ATTACH_RE = re.compile(r"\[attach\][^\[]*\[/attach\]", re.I)


def _clean_title(title: str) -> str:
    """Bo ngoac 『』, giu noi dung 【】 nhung bo ngoac, bo ngay thang cuoi."""
    t = title.strip()
    t = t.replace("『", "").replace("』", "")
    t = t.replace("【", "").replace("】", "")
    t = t.replace("《", "").replace("》", "")
    t = _DATE_SUFFIX_RE.sub("", t)
    return t.strip()


def get_novel_content(url: str, fallback_title: str = "", log=print) -> dict | None:
    """Tra ve {title, category, paras} hoac None."""
    soup = get_html(url, log=log)
    if not soup:
        return None

    # Title
    tt = soup.select_one("div.article-title")
    title = _clean_title(tt.get_text(strip=True)) if tt and tt.get_text(strip=True) else ""
    if not title:
        title = _clean_title(fallback_title) or url.rsplit("/", 1)[-1]

    # Category tu breadcrumb (link cuoi trong div.title)
    category = ""
    bc = soup.select_one("div.title")
    if bc:
        links = [a.get_text(strip=True) for a in bc.find_all("a")]
        cats = [x for x in links if x and x != "首页"]
        if cats:
            category = cats[-1]

    # Content
    art = soup.select_one("div.artcontent")
    if not art:
        return None
    for tag in art.select("script, style, iframe, ins"):
        tag.decompose()
    for br in art.find_all("br"):
        br.replace_with("\n")

    raw = art.get_text("\n")
    raw = _ATTACH_RE.sub("", raw)
    paras = []
    for ln in raw.split("\n"):
        ln = ln.strip()
        if ln:
            paras.append(ln)

    if not paras:
        return None

    return {"title": title, "category": category, "paras": paras}


# ─── Translation (Google) ────────────────────────────────────
def _google(text: str) -> str | None:
    if not _TRANSLATE_AVAILABLE or not text.strip():
        return None
    try:
        r = _ts.translate_text(text[:MAX_CHUNK], translator="google",
                               from_language="zh", to_language="vi")
        if r and r.strip():
            return r
    except Exception:
        pass
    return None


def _han_fallback(text: str) -> str:
    """Chuyen ky tu Han con sot sang am Han Viet."""
    if _HV_AVAILABLE and _hv.has_hanzi(text):
        return _hv.hanzi_to_hanviet(text)
    return text


def _finalize(text: str) -> str:
    """Sau khi dich: convert ten rieng pinyin -> Han Viet, glossary, fallback Han."""
    if _HV_AVAILABLE:
        text = _hv.convert_names(text)
    text = _apply_glossary(text)
    text = _han_fallback(text)
    return text


def translate_title(title: str) -> str:
    r = _google(title)
    if r:
        title = r.splitlines()[0].strip()
    return _finalize(title)


def translate_paras(paras: list, log=print, should_stop=lambda: False) -> tuple:
    """Dich list doan van. Tra ve (list_dich, so_chunk_fail)."""
    text = "\n\n".join(paras)
    # Chia chunk theo ranh gioi doan
    chunks, cur = [], ""
    for para in text.split("\n\n"):
        if cur and len(cur) + len(para) + 2 > MAX_CHUNK:
            chunks.append(cur.rstrip())
            cur = para + "\n\n"
        else:
            cur += para + "\n\n"
    if cur.strip():
        chunks.append(cur.rstrip())

    # Dich cac chunk SONG SONG (giu nguyen thu tu khi ghep lai)
    results = [None] * len(chunks)
    lock = threading.Lock()
    counter = {"done": 0, "fail": 0}

    def _work(i: int, chunk: str):
        if should_stop():
            results[i] = chunk
            return
        res = _google(chunk)
        if res:
            results[i] = res
        else:
            results[i] = _han_fallback(chunk)
            with lock:
                counter["fail"] += 1
        time.sleep(TRANS_DELAY)
        with lock:
            counter["done"] += 1
            if len(chunks) > 1:
                log(f"    dich chunk {counter['done']}/{len(chunks)}")

    if len(chunks) == 1:
        _work(0, chunks[0])
    elif len(chunks) > 1:
        with ThreadPoolExecutor(max_workers=TRANS_WORKERS) as ex:
            futures = [ex.submit(_work, i, c) for i, c in enumerate(chunks)]
            for _ in as_completed(futures):
                pass

    joined = _finalize("\n\n".join(r for r in results if r is not None))
    return joined.split("\n\n"), counter["fail"]


# ─── Filename / progress ─────────────────────────────────────
def sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = re.sub(r"\s+", " ", name).strip(". ")
    return name[:120] or "truyen"


def load_progress(out_dir: Path) -> dict:
    f = out_dir / "_progress.json"
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_progress(out_dir: Path, done: dict):
    try:
        (out_dir / "_progress.json").write_text(
            json.dumps(done, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8")
    except Exception:
        pass


# ─── Write file ──────────────────────────────────────────────
def write_novel(out_path: Path, url: str, title: str, category: str, paras: list):
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("=" * 60 + "\n")
        f.write(f"  {title}\n")
        f.write(f"  Nguồn    : {url}\n")
        if category:
            f.write(f"  Thể loại : {category}\n")
        f.write("=" * 60 + "\n\n")
        for p in paras:
            f.write(p + "\n\n")


def write_duplicate_marker(out_path: Path, url: str, vi_title: str,
                           han_title: str, entry: dict, reason: str):
    """Ghi file danh dau truyen TRUNG (ten file da co prefix '_').
    Noi dung: header + danh sach 'links' trung tu registry."""
    links = entry.get("links", []) if entry else []
    vi_names = entry.get("ten_viet_lien_quan", []) if entry else []
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("=" * 60 + "\n")
        f.write(f"  {vi_title}   [TRÙNG]\n")
        f.write(f"  Nguồn    : {url}\n")
        f.write(f"  Tên gốc  : {han_title}\n")
        f.write("=" * 60 + "\n\n")
        f.write("[TRÙNG với truyện đã có trong downloaded_registry.json]\n")
        f.write(f"Lý do       : {reason}\n")
        if entry:
            f.write(f"ID chuẩn    : {entry.get('truyen_id_chuan', '')}\n")
            f.write(f"Tên gốc Hán : {entry.get('ten_goc_han', '')}\n")
            if vi_names:
                f.write(f"Tên Việt    : {', '.join(vi_names)}\n")
        f.write("\n")
        f.write('"links": [\n')
        for i, lk in enumerate(links):
            comma = "," if i < len(links) - 1 else ""
            f.write(f'    "{lk}"{comma}\n')
        f.write("]\n")


# ─── Registry duplicate check ────────────────────────────────
def load_registry():
    """Tra ve dict registry (rong neu khong co novel_manager / file)."""
    if _NM_AVAILABLE and REGISTRY_PATH.exists():
        try:
            return _nm.load_registry(REGISTRY_PATH)
        except Exception:
            pass
    return {}


def check_dup_registry(registry: dict, url: str = None, han_title: str = None,
                       content: str = None):
    """Check trung voi registry theo URL / ten goc Han / van tay noi dung.
    Tra ve (is_dup, entry, reason)."""
    if not registry or not _NM_AVAILABLE:
        return False, None, ""
    is_dup, entry, reason, _ = _nm.check_duplicate(
        registry, check_url=url, check_title=han_title, check_content=content)
    return is_dup, entry, reason


def register_novel(registry: dict, url: str, han_title: str, vi_title: str,
                   raw_han_body: str, fname: str):
    """Them truyen moi vao registry (downloaded_registry.json) sau khi tai xong."""
    if not _NM_AVAILABLE:
        return
    try:
        _nm.add_novel_to_registry(
            registry=registry,
            chinese_title=han_title,
            links=[url],
            viet_title=vi_title,
            author="Khong ro",
            content_body=raw_han_body,
            trans_filename=fname,
        )
        _nm.save_registry(REGISTRY_PATH, registry)
    except Exception as e:
        print(f"[!] Khong cap nhat duoc registry: {e}")


# ─── Main crawl ──────────────────────────────────────────────
def run(keyword: str, start_page: int, end_page: int, out_dir: Path,
        do_translate: bool = True, log=print, should_stop=lambda: False,
        on_progress=None):
    out_dir.mkdir(parents=True, exist_ok=True)
    _load_glossary()
    done = load_progress(out_dir)
    registry = load_registry()

    n_dl = n_skip = n_fail = n_dup = 0

    def _mark_dup(url, han_title, entry, reason):
        """Ghi file danh dau TRUNG + gop link vao registry + cap nhat progress."""
        nonlocal n_dup
        # Gop URL langyou vao links[] cua ban ghi trung (neu chua co) roi luu lai
        if entry is not None and _NM_AVAILABLE:
            links = set(entry.get("links", []))
            if url and url not in links:
                links.add(url)
                entry["links"] = sorted(links)
                try:
                    _nm.save_registry(REGISTRY_PATH, registry)
                    log(f"    [registry] da gop link vao ID {entry.get('truyen_id_chuan', '?')}")
                except Exception as e:
                    log(f"    [!] Khong luu duoc registry: {e}")
        dup_vi = translate_title(han_title) if (do_translate and han_title) \
            else _finalize(han_title or "")
        dup_fname = "_" + sanitize_filename(dup_vi) + ".txt"
        write_duplicate_marker(out_dir / dup_fname, url, dup_vi, han_title, entry, reason)
        log(f"  [TRÙNG] {(han_title or url)[:45]} -> {dup_fname}")
        done[url] = dup_fname
        save_progress(out_dir, done)
        n_dup += 1
        if on_progress:
            on_progress(n_dl, n_skip, n_fail)

    log(f"Tu khoa : {keyword}")
    log(f"Trang   : {start_page} -> {end_page}")
    log(f"Dich    : {'Google (zh->vi) + Han Viet' if do_translate else 'KHONG (giu chu Han)'}")
    log(f"Luu vao : {out_dir}")
    log(f"Registry: {len(registry)} truyen ({'da tai' if registry else 'trong/khong co'})")
    log("-" * 55)

    for page in range(start_page, end_page + 1):
        if should_stop():
            break
        log(f"[Trang {page}] dang lay danh sach...")
        novels = get_search_page(keyword, page, log=log)
        if not novels:
            log(f"[Trang {page}] khong co truyen (co the da het) -> bo qua.")
            time.sleep(DELAY)
            continue
        log(f"[Trang {page}] {len(novels)} truyen.")

        for nv in novels:
            if should_stop():
                break
            url = nv["url"]
            if url in done:
                n_skip += 1
                continue

            # Bo ky hieu 『』【】《》 + ngay thang truoc khi check trung
            han_title = _clean_title(nv["title"])

            # Tang 1+3: check URL + ten goc Han truoc khi tai (0 request)
            is_dup, dup_entry, dup_reason = check_dup_registry(
                registry, url=url, han_title=han_title)
            if is_dup:
                _mark_dup(url, han_title, dup_entry, dup_reason)
                time.sleep(DELAY)
                continue

            log(f"  Tai: {han_title[:55]}")
            info = get_novel_content(url, fallback_title=han_title, log=log)
            if not info:
                n_fail += 1
                log(f"    [!] Khong lay duoc noi dung.")
                continue

            title, category, paras = info["title"], info["category"], info["paras"]
            raw_han_body = "\n\n".join(paras)   # giu chu Han goc cho fingerprint registry

            # Tang 2: check van tay noi dung TRUOC khi dich (dich moi la phan dat)
            is_dup, dup_entry, dup_reason = check_dup_registry(
                registry, content=raw_han_body)
            if is_dup:
                _mark_dup(url, han_title, dup_entry, dup_reason)
                time.sleep(DELAY)
                continue

            if do_translate:
                vi_title = translate_title(title)
                category = _category_vi(category)
                log(f"    => {vi_title}")
                log(f"    Dich {len(paras)} doan...")
                paras, fail = translate_paras(paras, log=log, should_stop=should_stop)
                if should_stop():
                    break
                if fail:
                    log(f"    [!] {fail} chunk dich loi (fallback Han Viet).")
            else:
                vi_title = _finalize(title)
                category = _category_vi(category)

            fname = sanitize_filename(vi_title) + ".txt"
            out_path = out_dir / fname
            write_novel(out_path, url, vi_title, category, paras)
            size_kb = out_path.stat().st_size / 1024
            log(f"    [OK] {fname} ({size_kb:.1f} KB)")

            done[url] = fname
            save_progress(out_dir, done)

            # Truyen moi -> them vao registry de lan sau check trung
            register_novel(registry, url, han_title, vi_title, raw_han_body, fname)

            n_dl += 1
            if on_progress:
                on_progress(n_dl, n_skip, n_fail)
            time.sleep(DELAY)

    save_progress(out_dir, done)
    log("-" * 55)
    log(f"XONG. Tai moi: {n_dl} | Trung: {n_dup} | Bo qua (da co): {n_skip} | Loi: {n_fail}")
    log(f"Thu muc: {out_dir}")
    return n_dl, n_skip, n_fail


# ─── UI (Tkinter) ────────────────────────────────────────────
def launch_ui():
    import tkinter as tk
    from tkinter import ttk, filedialog, scrolledtext

    root = tk.Tk()
    root.title("Langyou Downloader - Tai + dich truyen (狼友小说)")
    root.geometry("820x620")

    worker = {"thread": None, "stop": False}

    # --- Form ---
    frm = ttk.Frame(root, padding=10)
    frm.pack(fill="x")

    ttk.Label(frm, text="Tu khoa:").grid(row=0, column=0, sticky="w", pady=3)
    kw_var = tk.StringVar(value=DEFAULT_KEYWORD)
    ttk.Entry(frm, textvariable=kw_var, width=20).grid(row=0, column=1, sticky="w", padx=5)

    ttk.Label(frm, text="Trang tu:").grid(row=0, column=2, sticky="e", padx=5)
    start_var = tk.IntVar(value=DEFAULT_START)
    ttk.Spinbox(frm, from_=1, to=999, textvariable=start_var, width=6).grid(row=0, column=3, sticky="w")

    ttk.Label(frm, text="den:").grid(row=0, column=4, sticky="e", padx=5)
    end_var = tk.IntVar(value=DEFAULT_END)
    ttk.Spinbox(frm, from_=1, to=999, textvariable=end_var, width=6).grid(row=0, column=5, sticky="w")

    trans_var = tk.BooleanVar(value=True)
    ttk.Checkbutton(frm, text="Dich Google + Han Viet", variable=trans_var)\
        .grid(row=1, column=0, columnspan=2, sticky="w", pady=3)

    ttk.Label(frm, text="Luu vao:").grid(row=2, column=0, sticky="w", pady=3)
    out_var = tk.StringVar(value=str(DEFAULT_OUT))
    ttk.Entry(frm, textvariable=out_var, width=60).grid(row=2, column=1, columnspan=4, sticky="w", padx=5)

    def _browse():
        d = filedialog.askdirectory(initialdir=out_var.get() or str(SCRIPT_DIR))
        if d:
            out_var.set(d)
    ttk.Button(frm, text="...", width=3, command=_browse).grid(row=2, column=5, sticky="w")

    # --- Buttons + status ---
    bar = ttk.Frame(root, padding=(10, 0))
    bar.pack(fill="x")
    start_btn = ttk.Button(bar, text="Bat dau")
    start_btn.pack(side="left")
    stop_btn = ttk.Button(bar, text="Dung", state="disabled")
    stop_btn.pack(side="left", padx=6)
    status_var = tk.StringVar(value="San sang.")
    ttk.Label(bar, textvariable=status_var).pack(side="left", padx=12)

    # --- Log ---
    log_box = scrolledtext.ScrolledText(root, wrap="word", height=26,
                                        font=("Consolas", 9))
    log_box.pack(fill="both", expand=True, padx=10, pady=10)

    def ui_log(msg):
        def _append():
            log_box.insert("end", msg + "\n")
            log_box.see("end")
        root.after(0, _append)

    def ui_progress(dl, skip, fail):
        root.after(0, lambda: status_var.set(f"Tai: {dl} | Bo qua: {skip} | Loi: {fail}"))

    def _done():
        start_btn.config(state="normal")
        stop_btn.config(state="disabled")
        status_var.set(status_var.get() + "  [KET THUC]")

    def _start():
        if worker["thread"] and worker["thread"].is_alive():
            return
        if not _TRANSLATE_AVAILABLE and trans_var.get():
            ui_log("[!] Chua cai thu vien 'translators'. Chay: pip install translators")
        worker["stop"] = False
        start_btn.config(state="disabled")
        stop_btn.config(state="normal")
        log_box.delete("1.0", "end")
        status_var.set("Dang chay...")

        kw = kw_var.get().strip() or DEFAULT_KEYWORD
        sp, ep = start_var.get(), end_var.get()
        out_dir = Path(out_var.get().strip() or str(DEFAULT_OUT))
        do_tr = trans_var.get()

        def job():
            try:
                run(kw, sp, ep, out_dir, do_translate=do_tr, log=ui_log,
                    should_stop=lambda: worker["stop"], on_progress=ui_progress)
            except Exception as e:
                ui_log(f"[LOI NGHIEM TRONG] {e}")
            finally:
                root.after(0, _done)

        worker["thread"] = threading.Thread(target=job, daemon=True)
        worker["thread"].start()

    def _stop():
        worker["stop"] = True
        status_var.set("Dang dung (cho chunk hien tai xong)...")
        stop_btn.config(state="disabled")

    start_btn.config(command=_start)
    stop_btn.config(command=_stop)

    root.mainloop()


# ─── CLI ─────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(description="Langyou Downloader")
    p.add_argument("--cli", action="store_true", help="Chay dong lenh (khong UI)")
    p.add_argument("--keyword", default=DEFAULT_KEYWORD)
    p.add_argument("--start", type=int, default=DEFAULT_START)
    p.add_argument("--end", type=int, default=DEFAULT_END)
    p.add_argument("--out", default=str(DEFAULT_OUT))
    p.add_argument("--no-translate", action="store_true")
    args = p.parse_args()

    if args.cli:
        run(args.keyword, args.start, args.end, Path(args.out),
            do_translate=not args.no_translate)
    else:
        launch_ui()


if __name__ == "__main__":
    main()
