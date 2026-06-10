#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FSNovel Downloader - Tai truyen tu fsnovel.com (風雪文學)
Luu vao: fsnovel.com/downloaded/
Su dung:
  py -u fsnovel_downloader.py                          # tai toan bo category mac dinh
  py -u fsnovel_downloader.py --url <url>              # tai mot truyen cu the
  py -u fsnovel_downloader.py --category <url>         # tai category khac
  py -u fsnovel_downloader.py --translate              # dich sang tieng Viet
  py -u fsnovel_downloader.py --vpn protonvpn|warp     # doi IP khi bi chan
"""

import os
os.environ.setdefault("PYTHONUNBUFFERED", "1")
import re
import sys
import time
import datetime
import json
import shutil
import subprocess
import argparse
import threading
import requests
from pathlib import Path
from bs4 import BeautifulSoup

# ─── Unicode fix Windows console ───────────────────────────
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ─── Logging ────────────────────────────────────────────────
def _log(msg: str, level: str = ""):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    prefix = {"ok": "[OK]", "warn": "[!]", "err": "[ERR]"}.get(level, "[*]")
    print(f"{ts} {prefix} {msg}", flush=True)

_errors_lock = threading.Lock()
_last_printed_errors: dict = {}

def _log_once(msg: str, level: str = "", expiry: float = 10.0):
    now = time.time()
    norm = re.sub(r'\d+', '', msg.strip())
    with _errors_lock:
        if now - _last_printed_errors.get(norm, 0) > expiry:
            _last_printed_errors[norm] = now
            _log(msg, level)

# ─── Optional dependencies ──────────────────────────────────
try:
    import _vpn_lock
    _VPN_LOCK_AVAILABLE = True
except ImportError:
    _VPN_LOCK_AVAILABLE = False

try:
    import hanviet as _hv
    _HV_AVAILABLE = True
except ImportError:
    _HV_AVAILABLE = False

try:
    import os as _os
    _os.environ["translators_default_region"] = "EN"
    import translators as _ts
    TRANSLATE_AVAILABLE = True
except Exception:
    _ts = None
    TRANSLATE_AVAILABLE = False

# ─── Glossary (pinyin → Hán Việt) ───────────────────────────
_GLOSSARY_FILE = Path(__file__).parent / "glossary.json"
_glossary: dict[str, str] = {}

def _load_glossary():
    global _glossary
    if _GLOSSARY_FILE.exists():
        try:
            _glossary = json.loads(_GLOSSARY_FILE.read_text(encoding="utf-8"))
            _log(f"Glossary: {len(_glossary)} ten rieng", "ok")
        except Exception as e:
            _log(f"Khong doc duoc glossary.json: {e}", "warn")
            _glossary = {}

def apply_glossary(text: str) -> str:
    """Thay the ten rieng pinyin → Han Viet theo glossary.json."""
    if not _glossary or not text:
        return text
    for src, dst in _glossary.items():
        if src in text:
            text = text.replace(src, dst)
    return text

# ─── Novel Registry integration ──────────────────────────────
try:
    import novel_manager as _nm
    _NM_AVAILABLE = True
except ImportError:
    _NM_AVAILABLE = False

_nm_registry_cache = None

def _nm_load():
    global _nm_registry_cache
    if _NM_AVAILABLE and _nm_registry_cache is None:
        _nm_registry_cache = _nm.load_registry(_nm.DEFAULT_REGISTRY_PATH)
    return _nm_registry_cache

def _nm_check_url(novel_url: str):
    """Kiem tra URL da co trong registry chua. Tra ve (is_dup, entry, reason)."""
    if not _NM_AVAILABLE:
        return False, None, ""
    reg = _nm_load()
    if not reg:
        return False, None, ""
    is_dup, entry, reason, _ = _nm.check_duplicate(reg, check_url=novel_url)
    return is_dup, entry, reason

def _nm_register(novel_url: str, title: str, content_body: str = "", origin_file: str = ""):
    """Cap nhat registry sau khi tai xong mot truyen.
    content_body: noi dung tieng Han goc (de trich fingerprint)."""
    if not _NM_AVAILABLE:
        return
    global _nm_registry_cache
    reg = _nm_load()
    if reg is None:
        reg = {}
    _nm.add_novel_to_registry(
        registry=reg,
        chinese_title="",
        links=[novel_url],
        viet_title=title,
        author="Khong ro",
        content_body=content_body,
        origin_filename=origin_file,
        trans_filename="",
    )
    _nm.save_registry(_nm.DEFAULT_REGISTRY_PATH, reg)
    _nm_registry_cache = reg

# ─── Config ─────────────────────────────────────────────────
BASE_URL        = "https://fsnovel.com"
DEFAULT_CAT_URL = "https://fsnovel.com/category/%e4%ba%82%e5%80%ab%e5%b0%8f%e8%aa%aa/"
DEFAULT_OUT     = Path(__file__).parent / "fsnovel.com" / "downloaded"
DELAY           = 1.5
TRANS_DELAY     = 0.8
MAX_CHUNK       = 4500
VPN_TYPE        = "none"   # set via --vpn arg

ENGINE         = "free"    # "free" | "gemini" | "google" | "caiyun"
GEMINI_API_KEY = ""
GEMINI_MODEL   = "gemini-2.5-flash"
GEMINI_DELAY   = 4.0
GEMINI_URL_TPL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_SAFETY  = [
    {"category": "HARM_CATEGORY_HARASSMENT",        "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH",       "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]
GEMINI_SYS = (
    "Ban la dich gia tieu thuyet mang chuyen nghiep, dich tu tieng Trung sang tieng Viet.\n"
    "Quy tac: van phong tu nhien, giu ten rieng, giu xuat dong, KHONG them ghi chu."
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "Referer": BASE_URL,
}

session = requests.Session()
session.headers.update(HEADERS)

# ─── VPN rotation ────────────────────────────────────────────
_PROTON_CANDIDATES = [
    shutil.which("protonvpn-cli"),
    shutil.which("protonvpn"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "protonvpn-cli", "protonvpn-cli.exe"),
    r"C:\Program Files\Proton\VPN\protonvpn-cli.exe",
    r"C:\Program Files (x86)\Proton\VPN\protonvpn-cli.exe",
]
PROTON_CLI = next((p for p in _PROTON_CANDIDATES if p and Path(p).exists()), None)

_html_rotate_lock = threading.Lock()
_html_rotate_done = threading.Event()
_html_rotate_done.set()
_last_captcha_t   = 0.0
_captcha_lock     = threading.Lock()


def _get_ip() -> str:
    try:
        r = requests.get("https://www.cloudflare.com/cdn-cgi/trace", timeout=8)
        for ln in r.text.splitlines():
            if ln.startswith("ip="):
                return ln[3:].strip()
    except Exception:
        pass
    return ""


def _reset_translate_sessions():
    if TRANSLATE_AVAILABLE and _ts:
        try:
            for _inst in _ts.server.tss._translators_dict.values():
                if hasattr(_inst, "session"):
                    _inst.session = None
                    _inst.language_map = None
                    _inst.query_count = 0
        except Exception:
            pass


def rotate_ip() -> bool:
    if VPN_TYPE == "none":
        return False
    if not _VPN_LOCK_AVAILABLE:
        return False

    warp_cli = r"C:\Program Files\Cloudflare\Cloudflare WARP\warp-cli.exe"

    if not _vpn_lock.acquire(timeout=15):
        return False
    try:
        gap = _vpn_lock.elapsed_since_last()
        if gap is not None and gap < 45:
            return False
        old_ip = _get_ip()
        if VPN_TYPE == "protonvpn" and PROTON_CLI:
            subprocess.run([PROTON_CLI, "disconnect"], timeout=15, capture_output=True)
            time.sleep(3)
            subprocess.run([PROTON_CLI, "connect", "--random"], timeout=30, capture_output=True)
        elif VPN_TYPE == "warp" and os.path.exists(warp_cli):
            subprocess.run([warp_cli, "disconnect"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(2)
            subprocess.run([warp_cli, "connect"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            _vpn_lock.release()
            return False
        for _ in range(15):
            time.sleep(1)
            new_ip = _get_ip()
            if new_ip:
                _vpn_lock.record_rotation()
                tag = "(IP MOI)" if (old_ip and new_ip != old_ip) else "(IP nhu cu)"
                _log(f"VPN rotate: {new_ip} {tag}", "ok")
                _reset_translate_sessions()
                return True
        _vpn_lock.record_rotation()
        _reset_translate_sessions()
        return True
    except Exception as e:
        _log(f"Rotate IP loi: {e}", "warn")
        return False
    finally:
        try:
            _vpn_lock.release()
        except Exception:
            pass


# ─── HTTP helper ─────────────────────────────────────────────
def get_html(url: str, retries: int = 3):
    global _last_captcha_t
    for attempt in range(retries):
        try:
            resp = session.get(url, timeout=20)
            resp.raise_for_status()
            resp.encoding = "utf-8"
            return BeautifulSoup(resp.text, "html.parser")
        except Exception as e:
            _log(f"  [Loi] {url[:60]} (lan {attempt+1}): {e}", "warn")
        if attempt < retries - 1:
            if VPN_TYPE != "none":
                acquired = _html_rotate_lock.acquire(blocking=False)
                if acquired:
                    with _captcha_lock:
                        now = time.time()
                        if now - _last_captcha_t > 10:
                            _last_captcha_t = now
                            _log("Loi tai HTML -> doi IP...", "warn")
                    _html_rotate_done.clear()
                    rotate_ip()
                    _html_rotate_done.set()
                    _html_rotate_lock.release()
                else:
                    _html_rotate_done.wait(timeout=60)
            time.sleep(3)
    return None


# ─── Tag map (Traditional Chinese → Tiếng Việt) ─────────────
_TAG_MAP: dict[str, str] = {
    "亂倫小說": "Loạn luân",        "亂倫": "Loạn luân",
    "人妻小說": "Nhân thê",          "人妻": "Nhân thê",
    "公司職場": "Công sở",           "職場": "Công sở",
    "都市生活": "Đô thị",            "都市": "Đô thị",
    "多人群交": "Quần giao",         "群交": "Quần giao",
    "古典文學": "Cổ điển",           "古典": "Cổ điển",
    "暴力虐待": "Bạo lực",
    "教師學生": "Thầy trò",          "老師學生": "Thầy trò",
    "母子": "Mẹ con",               "母女": "Mẹ con gái",
    "父女": "Cha con gái",           "兄妹": "Anh em gái",
    "姐弟": "Chị em trai",           "姊弟": "Chị em trai",
    "繼母": "Mẹ kế",                "岳母": "Mẹ vợ",
    "NTR": "NTR",                   "出軌": "Ngoại tình",
    "偷情": "Ngoại tình",            "綠帽": "Mọc sừng",
    "熟女": "Phụ nữ chín chắn",      "少女": "Thiếu nữ",
    "巨乳": "Ngực to",              "人妻": "Người vợ",
    "穿越": "Xuyên không",           "重生": "Trọng sinh",
    "玄幻": "Huyền huyễn",          "修仙": "Tu tiên",
    "武俠": "Võ hiệp",              "言情": "Ngôn tình",
    "短篇": "Truyện ngắn",           "長篇": "Truyện dài",
    "凌辱": "Lăng nhục",            "性奴": "Tình nô",
    "強姦": "Cưỡng hiếp",           "輪姦": "Luân cưỡng",
    "鄉村": "Nông thôn",            "農村": "Nông thôn",
    "受孕": "Thụ thai",             "懷孕": "Mang thai",
    "足交": "Túc giao",             "肛交": "Hậu giao",
    "後宮": "Hậu cung",             "換妻": "Hoán vợ",
    "催眠": "Thôi miên",            "調教": "Huấn luyện",
    "堕落": "Đọa lạc",              "墮落": "Đọa lạc",
    "禁忌": "Cấm kỵ",               "暗戀": "Yêu thầm",
    "鄰居": "Hàng xóm",             "上司": "Cấp trên",
    "秘書": "Thư ký",               "護士": "Y tá",
    "空姐": "Tiếp viên hàng không",
    "同學": "Bạn học",              "兄弟": "Anh em",
    "丁字褲": "Quần lọt khe",        "絲襪": "Tất nylon",
    "高跟": "Giày cao gót",
}


def _tag_vi(tag: str) -> str:
    """Chuyển tag Hán → Việt: tra bảng trước, fallback Hán Việt."""
    t = tag.strip()
    if t in _TAG_MAP:
        return _TAG_MAP[t]
    if _HV_AVAILABLE and _hv.has_hanzi(t):
        return _hv.hanzi_to_hanviet(t)
    return t


def _title_hanviet(title: str) -> str:
    """Chuyển tên truyện sang Hán Việt khi không dùng engine dịch."""
    if _HV_AVAILABLE and _hv.has_hanzi(title):
        return _hv.hanzi_to_hanviet(title)
    return title


# ─── Filename helpers ────────────────────────────────────────
def sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    return name.strip(". ")[:100]


# ─── Translation ─────────────────────────────────────────────
_engine_stats: dict = {}
_engine_lock = threading.Lock()
_engine_disabled: set = set()

ENGINE_LIMITS = {"caiyun": 4990, "google": 4990, "bing": 4990}


def gemini_generate(text: str, retries: int = 3) -> str | None:
    if not GEMINI_API_KEY or not text.strip():
        return None
    url = GEMINI_URL_TPL.format(model=GEMINI_MODEL)
    payload = {
        "system_instruction": {"parts": [{"text": GEMINI_SYS}]},
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {"temperature": 0.3},
        "safetySettings": GEMINI_SAFETY,
    }
    for attempt in range(retries):
        try:
            resp = requests.post(url, params={"key": GEMINI_API_KEY}, json=payload, timeout=120)
            if resp.status_code == 429:
                time.sleep(5 * (attempt + 2))
                continue
            resp.raise_for_status()
            data = resp.json()
            parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            result = "".join(p.get("text", "") for p in parts).strip()
            return result or None
        except Exception as e:
            _log(f"  [Gemini loi {attempt+1}]: {e}", "warn")
            if attempt < retries - 1:
                time.sleep(5)
    return None


def translate_text(text: str) -> tuple[str, int]:
    """Dich Trung -> Viet. Tra ve (ban_dich, so_chunk_fail)."""
    if not text.strip():
        return text, 0

    if ENGINE == "gemini":
        result = gemini_generate(text)
        if result:
            time.sleep(GEMINI_DELAY)
            return result, 0
        _log("  [Gemini that bai -> fallback Google]", "warn")

    if not TRANSLATE_AVAILABLE:
        return text, 0

    if ENGINE == "caiyun":
        free_engines = ["caiyun"]
    elif ENGINE == "google":
        free_engines = ["google"]
    else:
        free_engines = ["caiyun", "google"]

    # Chia chunk
    chunks: list[str] = []
    cur = ""
    for para in text.split("\n\n"):
        if cur and len(cur) + len(para) + 2 > MAX_CHUNK:
            chunks.append(cur.rstrip())
            cur = para + "\n\n"
        else:
            cur += para + "\n\n"
    if cur.strip():
        chunks.append(cur.rstrip())

    fail = 0
    translated_parts = []

    for chunk in chunks:
        result = None
        for eng in free_engines:
            if eng in _engine_disabled:
                continue
            limit = ENGINE_LIMITS.get(eng, 4990)
            try_text = chunk[:limit] if len(chunk) > limit else chunk
            try:
                res = _ts.translate_text(try_text, translator=eng, from_language="zh", to_language="vi")
                if res and res.strip() and res.strip() != try_text.strip():
                    result = res
                    with _engine_lock:
                        _engine_stats[eng] = _engine_stats.get(eng, 0) + 1
                    break
            except Exception as e:
                msg = str(e)
                if "403" in msg or "401" in msg or "Forbidden" in msg:
                    _engine_disabled.add(eng)
                _log_once(f"[{eng}] {msg[:60]}", "warn")

        if result:
            translated_parts.append(result)
        else:
            fail += 1
            translated_parts.append(chunk)
        time.sleep(TRANS_DELAY)

    return "\n\n".join(translated_parts).strip(), fail


def translate_title(title: str) -> str:
    if not title.strip():
        return title
    if ENGINE == "gemini":
        r = gemini_generate(title)
        if r:
            time.sleep(GEMINI_DELAY)
            return r.splitlines()[0].strip()
    if not TRANSLATE_AVAILABLE:
        if _HV_AVAILABLE and _hv.has_hanzi(title):
            return _hv.hanzi_to_hanviet(title)
        return title
    if ENGINE == "caiyun":
        engs = ["caiyun"]
    elif ENGINE == "google":
        engs = ["google"]
    else:
        engs = ["caiyun", "google"]
    for eng in engs:
        try:
            r = _ts.translate_text(title, translator=eng, from_language="zh", to_language="vi")
            if r and r.strip():
                time.sleep(TRANS_DELAY)
                return r.splitlines()[0].strip()
        except Exception:
            pass
    if _HV_AVAILABLE and _hv.has_hanzi(title):
        return _hv.hanzi_to_hanviet(title)
    return title


# ─── Category / Listing parser ───────────────────────────────

def get_listing_page(url: str) -> tuple[list[dict], int]:
    """
    Phan tich 1 trang danh sach truyen.
    Tra ve (list[{title, novel_url, date}], total_pages).
    """
    soup = get_html(url)
    if not soup:
        return [], 1

    novels = []
    for item in soup.select("p.entry-title, .td-module-title"):
        a = item.find("a")
        if not a or not a.get("href"):
            continue
        href = a["href"]
        if not href.startswith("http"):
            href = BASE_URL + href
        # lay date tu parent container
        parent = item.find_parent(class_="td-module-container") or item.find_parent()
        date = ""
        if parent:
            t = parent.select_one("time.entry-date")
            date = t.get("datetime", "") if t else ""
        novels.append({
            "title":     a.get_text(strip=True),
            "novel_url": href,
            "date":      date,
        })

    # So trang
    total_pages = 1
    for a in soup.select(".page-nav a, .page-numbers a"):
        href = a.get("href", "")
        m = re.search(r"/page/(\d+)/", href)
        if m:
            total_pages = max(total_pages, int(m.group(1)))

    return novels, total_pages


def iter_category(cat_url: str, max_pages: int = 0, start_page: int = 1, reverse: bool = False):
    """Generator: yield (page_no, total_pages, list[novel_dict]) moi trang."""
    cat_url = cat_url.rstrip("/")

    if reverse:
        # Lay tong so trang bang cach fetch trang 1
        _, total_pages = get_listing_page(f"{cat_url}/")
        _log(f"  Tong so trang: {total_pages} (tai NGUOC tu trang cuoi)")
        pages = list(range(total_pages, 0, -1))
        if max_pages:
            pages = pages[:max_pages]
        for page in pages:
            url = f"{cat_url}/" if page == 1 else f"{cat_url}/page/{page}/"
            _log(f"  Trang {page}/{total_pages}: {url}")
            novels, _ = get_listing_page(url)
            if not novels:
                _log(f"  Trang {page} khong co truyen nao -> bo qua.", "warn")
                continue
            yield page, total_pages, novels
            time.sleep(DELAY)
        return

    page = start_page
    total_pages = None

    while True:
        if max_pages and page > start_page + max_pages - 1:
            break
        if total_pages and page > total_pages:
            break

        url = f"{cat_url}/" if page == 1 else f"{cat_url}/page/{page}/"
        _log(f"  Trang {page}{f'/{total_pages}' if total_pages else ''}: {url}")
        novels, tp = get_listing_page(url)

        if total_pages is None:
            total_pages = tp
            _log(f"  Tong so trang: {total_pages}")

        if not novels:
            _log(f"  Trang {page} khong co truyen nao -> dung.", "warn")
            break

        yield page, total_pages, novels
        page += 1
        time.sleep(DELAY)


# ─── Novel content scraper ───────────────────────────────────

def get_novel_content(novel_url: str) -> dict | None:
    """
    Lay noi dung truyen tu trang chi tiet.
    Tra ve dict: {title, date, tags, content_raw, paras}
    """
    soup = get_html(novel_url)
    if not soup:
        return None

    # Title
    art = soup.select_one("article[data-post-title]")
    title = art["data-post-title"] if art else ""
    if not title:
        h1 = soup.select_one("h1.entry-title, h1")
        title = h1.get_text(strip=True) if h1 else ""
    if not title:
        title = novel_url.rstrip("/").rsplit("/", 1)[-1]

    # Date
    t_tag = soup.select_one("time.entry-date")
    date = t_tag.get("datetime", "") if t_tag else ""

    # Tags / Categories
    tags: list[str] = []
    for sel in [".td-tags a", ".td-post-small-box a", ".td-category a"]:
        found = soup.select(sel)
        if found:
            tags = [a.get_text(strip=True) for a in found if a.get_text(strip=True)]
            break
    # Fallback: lay tu category listing
    cat_a = soup.select(".td-post-category")
    for a in cat_a:
        t = a.get_text(strip=True)
        if t and t not in tags:
            tags.append(t)

    # Content
    content_div = soup.select_one(".td-post-content, .entry-content, .post-content")
    if not content_div:
        return None

    # Loai bo quang cao / script
    for tag in content_div.select("script, style, .gg, iframe, [class*='ad'], .sharedaddy"):
        tag.decompose()

    paras = []
    for p in content_div.find_all("p"):
        text = p.get_text(strip=True)
        if text:
            paras.append(text)

    if not paras:
        raw = content_div.get_text("\n", strip=True)
        paras = [ln for ln in raw.splitlines() if ln.strip()]

    return {
        "title":    title,
        "date":     date,
        "tags":     tags,
        "paras":    paras,
    }


# ─── Progress state ──────────────────────────────────────────

def load_progress(out_dir: Path) -> dict:
    done_f = out_dir / "_progress.json"
    fail_f = out_dir / "_failed.json"

    def _rd(p):
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    return {"done": _rd(done_f), "failed": _rd(fail_f)}


def save_progress(out_dir: Path, state: dict):
    try:
        (out_dir / "_progress.json").write_text(
            json.dumps(state["done"],   ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        (out_dir / "_failed.json").write_text(
            json.dumps(state["failed"], ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        _log(f"Khong luu duoc progress: {e}", "warn")


# ─── Write novel file ────────────────────────────────────────

def write_novel_file(out_path: Path, novel_url: str, info: dict,
                     trans_title: str = "", trans_paras: list | None = None):
    """
    Ghi 1 file truyen.
    Neu trans_paras != None -> ghi ban dich tieng Viet.
    Nguoc lai -> ghi ban goc chu Han.
    """
    title_line    = trans_title if trans_title else _title_hanviet(info["title"])
    content_paras = trans_paras if trans_paras is not None else info["paras"]
    # Convert tags: tra bảng TAG_MAP trước, fallback Hán Việt
    seen: set[str] = set()
    tags_vi: list[str] = []
    for t in info.get("tags", []):
        v = _tag_vi(t)
        if v.lower() not in seen:
            seen.add(v.lower())
            tags_vi.append(v)
    tags_str = ", ".join(tags_vi)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("=" * 60 + "\n")
        f.write(f"  {title_line}\n")
        f.write(f"  Nguồn      : {novel_url}\n")
        if info.get("date"):
            f.write(f"  Ngày       : {info['date'][:10]}\n")
        if tags_str:
            f.write(f"  Tags       : {tags_str}\n")
        f.write("=" * 60 + "\n\n")
        for para in content_paras:
            f.write(para + "\n\n")


# ─── Main download logic ─────────────────────────────────────

def download_one(novel_url: str, out_dir: Path, state: dict,
                 do_translate: bool, quiet: bool = False):
    """
    Tai va luu 1 truyen. Cap nhat state in-place.
    Tra ve True neu thanh cong.
    """
    url_key = novel_url.rstrip("/")

    if url_key in state["done"]:
        if not quiet:
            _log(f"(da co) {state['done'][url_key]}", "ok")
        return True

    # Kiem tra registry Tang 1: URL (0 request)
    _dup, _dup_e, _dup_r = _nm_check_url(novel_url)
    if _dup:
        _log(f"  [*] Da co trong registry: {_dup_r} -> Tai lai de cap nhat.", "ok")

    info = get_novel_content(novel_url)
    if not info or not info["paras"]:
        state["failed"][url_key] = "Khong lay duoc noi dung"
        return False

    title = info["title"]

    if do_translate:
        _log(f"  Dich tieu de: {title}")
        vn_title = apply_glossary(translate_title(title))
        _log(f"  => {vn_title}")
        filename = sanitize_filename(vn_title) + ".txt"
        out_path = out_dir / filename

        _log(f"  Dich noi dung ({len(info['paras'])} doan)...")
        content_text = "\n\n".join(info["paras"])
        trans_text, fail_count = translate_text(content_text)
        trans_text = apply_glossary(trans_text)
        trans_paras = trans_text.split("\n\n")

        n_gloss = sum(1 for k in _glossary if k in trans_text) if _glossary else 0
        if n_gloss:
            _log(f"  Glossary: thay {n_gloss} cum ten rieng", "ok")

        write_novel_file(out_path, novel_url, info, vn_title, trans_paras)

        if fail_count > 0:
            _log(f"  {fail_count} doan dich that bai (con chu Han)", "warn")
            with open(out_dir / "_failed_chunks.log", "a", encoding="utf-8") as f:
                f.write(f"{novel_url}\t{filename}\tfail_chunks={fail_count}\n")
    else:
        hv_title = _title_hanviet(title)
        filename = sanitize_filename(hv_title) + ".txt"
        out_path = out_dir / filename
        write_novel_file(out_path, novel_url, info)

    size_kb = out_path.stat().st_size / 1024
    _log(f"  Luu: {filename} ({size_kb:.1f} KB)", "ok")
    state["done"][url_key] = filename
    state["failed"].pop(url_key, None)

    # Dang ky vao registry (dung noi dung Han goc de tao fingerprint)
    _nm_register(
        novel_url=novel_url,
        title=info["title"],
        content_body="\n\n".join(info.get("paras", [])),
        origin_file=filename if not do_translate else "",
    )
    return True


def download_category(cat_url: str, out_dir: Path,
                       do_translate: bool,
                       max_pages: int = 0,
                       start_page: int = 1,
                       limit: int = 0,
                       reverse: bool = False):
    """Tai toan bo truyen trong category."""
    out_dir.mkdir(parents=True, exist_ok=True)
    state = load_progress(out_dir)

    total_downloaded = 0
    total_skipped    = 0
    total_failed     = 0

    _log(f"Category: {cat_url}")
    _log(f"Output  : {out_dir}")

    try:
        for page, total_pages, novels in iter_category(cat_url, max_pages, start_page, reverse):
            _log(f"Trang {page}/{total_pages}: {len(novels)} truyen")

            for novel in novels:
                url = novel["novel_url"]
                url_key = url.rstrip("/")

                if url_key in state["done"]:
                    total_skipped += 1
                    _log(f"  (da co) {novel['title'][:50]}")
                    continue

                _log(f"  Tai: {novel['title'][:60]}  [{url}]")
                ok = download_one(url, out_dir, state, do_translate, quiet=True)
                if ok:
                    total_downloaded += 1
                else:
                    total_failed += 1
                    _log(f"  THAT BAI: {novel['title'][:50]}", "warn")

                save_progress(out_dir, state)
                time.sleep(DELAY)

                if limit and total_downloaded >= limit:
                    _log(f"Da dat gioi han {limit} truyen.", "ok")
                    raise StopIteration

    except (KeyboardInterrupt, StopIteration):
        _log(f"\nDung tai. Da tai: {total_downloaded}, bo qua: {total_skipped}, loi: {total_failed}")

    save_progress(out_dir, state)
    _log(f"\nHoan thanh! Tai: {total_downloaded} | Bo qua: {total_skipped} | Loi: {total_failed}", "ok")
    _log(f"Luu tai: {out_dir}")


# ─── CLI ─────────────────────────────────────────────────────

def main():
    global VPN_TYPE, ENGINE, GEMINI_API_KEY, GEMINI_MODEL, DELAY

    p = argparse.ArgumentParser(
        description="FSNovel Downloader - Tai truyen tu fsnovel.com"
    )
    p.add_argument("--url",       help="URL truyen cu the (chi tai 1 truyen)")
    p.add_argument("--category",  default=DEFAULT_CAT_URL,
                   help="URL category (mac dinh: category loanan)")
    p.add_argument("--out",       default=str(DEFAULT_OUT),
                   help="Thu muc luu (mac dinh: fsnovel.com/downloaded)")
    p.add_argument("--translate", action="store_true",
                   help="Dich sang tieng Viet")
    p.add_argument("--engine",    default="free",
                   choices=["free", "google", "caiyun", "gemini"],
                   help="Engine dich (mac dinh: free = Caiyun+Google)")
    p.add_argument("--gemini-key", default="", help="Gemini API key (neu dung --engine gemini)")
    p.add_argument("--gemini-model", default=GEMINI_MODEL, help="Gemini model")
    p.add_argument("--vpn",       default="none",
                   choices=["none", "protonvpn", "warp"],
                   help="Doi IP qua VPN khi bi chan")
    p.add_argument("--max-pages", type=int, default=0,
                   help="So trang toi da (0 = tat ca)")
    p.add_argument("--start-page", type=int, default=1,
                   help="Bat dau tu trang nay")
    p.add_argument("--limit",     type=int, default=0,
                   help="Gioi han so truyen tai (0 = khong gioi han)")
    p.add_argument("--delay",     type=float, default=DELAY,
                   help=f"Delay giua request (mac dinh: {DELAY}s)")
    p.add_argument("--reverse",   action="store_true",
                   help="Tai tu trang CUOI ve trang dau (moi nhat truoc)")
    args = p.parse_args()

    VPN_TYPE       = args.vpn
    ENGINE         = args.engine
    GEMINI_API_KEY = args.gemini_key
    GEMINI_MODEL   = args.gemini_model
    DELAY          = args.delay

    if args.translate:
        _load_glossary()

    out_dir = Path(args.out)

    if args.url:
        # Tai 1 truyen cu the
        out_dir.mkdir(parents=True, exist_ok=True)
        state = load_progress(out_dir)
        _log(f"Tai truyen: {args.url}")
        ok = download_one(args.url, out_dir, state, args.translate)
        save_progress(out_dir, state)
        sys.exit(0 if ok else 1)
    else:
        # Tai toan bo category
        download_category(
            cat_url     = args.category,
            out_dir     = out_dir,
            do_translate= args.translate,
            max_pages   = args.max_pages,
            start_page  = args.start_page,
            limit       = args.limit,
            reverse     = args.reverse,
        )


if __name__ == "__main__":
    main()
