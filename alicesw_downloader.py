#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AliceSW Downloader - Tai truyen tu alicesw.com
Luu 2 thu muc: origin/ (ban goc) va translated/ (tieng Viet)
Su dung: py -u alicesw_downloader.py [URL] [options]
"""

import os
os.environ.setdefault("PYTHONUNBUFFERED", "1")  # Force unbuffered output
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
from concurrent.futures import ThreadPoolExecutor


def _log(msg: str, level: str = ""):
    """In log co timestamp de biet tool dang lam gi."""
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    prefix = {"ok": "[OK]", "warn": "[!]", "err": "[ERR]"}.get(level, "[*]")
    print(f"{ts} {prefix} {msg}", flush=True)

_errors_lock = threading.Lock()
_last_printed_errors = {}

def _log_once(msg: str, level: str = "", expiry: float = 10.0):
    """In thong bao loi nhung tranh trung lap trong khoang thoi gian expiry giay."""
    global _last_printed_errors
    now = time.time()
    # Chuan hoa de gom nhom tin nhan giong nhau
    norm_msg = msg.strip()
    if "429" in norm_msg or "bi chan" in norm_msg or "too many requests" in norm_msg.lower():
        if "doi ip" in norm_msg.lower() or "rotate" in norm_msg.lower():
            norm_msg = "429_doi_ip"
        elif "loi" in norm_msg.lower() or "error" in norm_msg.lower():
            norm_msg = "429_engine_error"
        else:
            norm_msg = "429_other"
    else:
        norm_msg = re.sub(r'\d+', '', norm_msg)
    
    with _errors_lock:
        last_time = _last_printed_errors.get(norm_msg, 0)
        if now - last_time > expiry:
            _last_printed_errors[norm_msg] = now
            _log(msg, level)
import _vpn_lock
import hanviet as _hv

# ── Novel Registry integration (kiem tra trung lap truyen) ───
try:
    import novel_manager as _nm
    _NM_AVAILABLE = True
except ImportError:
    _NM_AVAILABLE = False

_nm_registry_cache = None  # Lazy-load khi can

def _nm_load():
    global _nm_registry_cache
    if _NM_AVAILABLE and _nm_registry_cache is None:
        _nm_registry_cache = _nm.load_registry(_nm.DEFAULT_REGISTRY_PATH)
    return _nm_registry_cache

def _nm_check_url(novel_url: str):
    """Kiem tra URL co trung trong registry khong. Tra ve (is_dup, entry, reason)."""
    if not _NM_AVAILABLE:
        return False, None, ""
    reg = _nm_load()
    if not reg:
        return False, None, ""
    is_dup, entry, reason, _ = _nm.check_duplicate(reg, check_url=novel_url)
    return is_dup, entry, reason

def _nm_add(info: dict, origin_file: str, trans_file: str = "", out_dir=None):
    """Cap nhat registry sau khi tai xong mot truyen.
    Doc file goc de trich fingerprint 200 ky tu Han chinh xac nhat."""
    if not _NM_AVAILABLE:
        return
    global _nm_registry_cache
    reg = _nm_load()
    if reg is None:
        reg = {}
    content_body = ""
    if out_dir and origin_file:
        fp = Path(out_dir) / "origin" / origin_file
        if fp.exists():
            try:
                content_body = fp.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                pass
    _nm.add_novel_to_registry(
        registry=reg,
        chinese_title="",
        links=[info.get("novel_url", "")],
        viet_title=info.get("title", ""),
        author=info.get("author", "Khong ro"),
        content_body=content_body,
        origin_filename=origin_file,
        trans_filename=trans_file,
    )
    _nm.save_registry(_nm.DEFAULT_REGISTRY_PATH, reg)
    _nm_registry_cache = reg

def _nm_check_novel(info: dict) -> tuple:
    """Kiem tra trung lap Tang 1: URL (0 request). Tra ve (dup_type, entry, reason).
    dup_type: None = truyen moi | 'url' = URL da co trong registry (se tai lai/cap nhat)
    Kiem tra noi dung (Tang 2) da tach thanh: python novel_manager.py match
    """
    is_url_dup, entry, reason = _nm_check_url(info.get("novel_url", ""))
    if is_url_dup:
        return "url", entry, reason
    return None, None, ""

# ── Tim ProtonVPN CLI de tu doi IP khi bi block ──────────────
_PROTON_CANDIDATES = [
    shutil.which("protonvpn-cli"),
    shutil.which("protonvpn"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "protonvpn-cli", "protonvpn-cli.exe"),
    r"C:\Program Files\Proton\VPN\protonvpn-cli.exe",
    r"C:\Program Files (x86)\Proton\VPN\protonvpn-cli.exe",
]
PROTON_CLI = next((p for p in _PROTON_CANDIDATES if p and Path(p).exists()), None)

# Fallback cho app GUI Windows (khong co CLI): dieu khien qua Windows Service.
_PROTON_SVC = "ProtonVPN Service"
def _proton_service_running() -> bool:
    try:
        r = subprocess.run(["sc", "query", _PROTON_SVC], capture_output=True, timeout=5)
        return b"RUNNING" in r.stdout
    except Exception:
        return False
PROTON_SERVICE = _PROTON_SVC if _proton_service_running() else None
USE_PROTON = bool(PROTON_CLI or PROTON_SERVICE)   # co cach nao doi IP khong
VPN_TYPE = "none"  # Dat tu command line: protonvpn | warp | none
_short_novel_count = 0   # dem truyen ngan (<8 chuong) de gom 8 truyen reset 1 lan
_last_captcha_log_t = 0.0
_captcha_log_lock   = threading.Lock()

# Fix unicode tren Windows console - dung reconfigure() de khong pha vo buffering
_real_stdin = sys.stdin
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
        _real_stdin = sys.stdin
except Exception:
    pass


def safe_input(prompt: str = "") -> str:
    """Hien thi prompt va doc dong nhap tu stdin."""
    print(prompt, end="", flush=True)
    try:
        return _real_stdin.readline().rstrip("\n")
    except Exception:
        return input()

BASE_URL    = "https://www.alicesw.com"
DELAY       = 1.5   # delay giua cac request (giay)
TRANS_DELAY = 0.8   # delay giua cac request dich
MAX_CHUNK   = 4500  # gioi han ky tu khi gom chunk
TRANSLATE_WORKERS = 1  # so luong dich SONG SONG (1 = tuan tu nhu cu; >1 = dich nhieu chuong cung luc)
CHAPTER_MIN_HAN = 5    # chuong co < bao nhieu chu Han = nghi ngo loi (CAPTCHA page co ~50 chu Han)
# Trang CAPTCHA toan trang (chac chan la trang chan) -> check tren CA trang HTML
CAPTCHA_MARKERS = ['访问验证', '当前访问行为触发了安全验证', '请输入验证码']
# Noi dung gia khi IP bi chan (trang tra ve hop thoai "提示信息" thay vi chuong)
# -> CHI check tren NOI DUNG da trich (tranh nham voi chuong ngan that su)
PLACEHOLDER_MARKERS = ['提示信息', '访问验证', '验证码', '请输入验证码']

# Gioi han that su cua tung engine (lay tu translators source: input_limit)
# Chunk se bi cat xuong con ENGINE_LIMIT[eng] truoc khi gui de tranh bi tu choi
ENGINE_LIMITS = {
    "caiyun":  4990,
    "google":  4990,
    "bing":    4990,
    "alibaba": 4990,
}

# ── Trang thai dich ────
_engine_stats    = {}                  # dem so chunk moi engine da dich thanh cong {eng: count}
_engine_lock     = threading.Lock()    # bao ve _engine_stats khi dich song song (nhieu thread cung dem)
_engine_disabled = set()               # engine bi 403/Forbidden trong phien nay -> bo qua luon
_translate_rotate_lock = threading.Lock()  # chong nhieu thread cung doi IP khi dich bi chan
TRANSLATE_ROTATE_MIN   = 45.0       # giay toi thieu giua 2 lan doi IP do dich 429 (tranh thrash)
_html_rotate_lock = threading.Lock()   # chi 1 thread tai HTML duoc rotate tai 1 thoi diem
_html_rotate_done = threading.Event()  # bao hieu rotation xong de thread khac retry ngay

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


def _load_cookies_file(path: str):
    """
    Doc file cookies.txt dinh dang Netscape va ap vao session.
    Chi lay cookie cua alicesw.com, bo qua domain khac.
    """
    loaded = 0
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n").rstrip("\r")
                # Cookie HttpOnly trong Netscape co tien to "#HttpOnly_" -> VAN la cookie hop le
                # (thuong la cookie phien dang nhap quan trong nhat). Bo tien to roi xu ly.
                if line.startswith("#HttpOnly_"):
                    line = line[len("#HttpOnly_"):]
                elif not line.strip() or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) < 7:
                    continue
                domain, _, path_, _, _, name, value = parts[:7]
                if "alicesw.com" in domain:
                    session.cookies.set(name, value, domain=domain.lstrip("."))
                    loaded += 1
        print(f"[*] Da tai {loaded} cookie alicesw.com tu {path}")
    except Exception as e:
        print(f"[!] Khong doc duoc cookies file: {e}")


# ── Khoi tao translator ──────────────────────────────────────
try:
    import os as _os
    _os.environ["translators_default_region"] = "EN"
    import translators as _ts
    TRANSLATE_AVAILABLE = True
except Exception as e:
    _ts = None
    TRANSLATE_AVAILABLE = False
    print(f"[!] Loi/Khong co thu vien 'translators' ({e}). Chay: py -m pip install translators")


# ── Cau hinh engine dich ─────────────────────────────────────
# ENGINE: "free"   - xoay Caiyun→Google (free, khong can key)
#         "gemini" - LLM, chat luong cao nhat (can GEMINI_API_KEY free)
ENGINE         = "free"
GEMINI_API_KEY = ""
GEMINI_MODEL   = "gemini-2.5-flash"  # nhanh + free tier rong; doi "gemini-2.5-pro" neu muon hay hon
GEMINI_DELAY   = 4.0                  # delay giua cac request Gemini (free tier ~15 req/phut)
GEMINI_URL_TPL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# Tat bo loc an toan: tieu thuyet mang co the chua noi dung 18+, tranh bi tu choi dich
GEMINI_SAFETY = [
    {"category": "HARM_CATEGORY_HARASSMENT",        "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH",       "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]

GEMINI_SYS_PROMPT = (
    "Ban la dich gia tieu thuyet mang chuyen nghiep, dich tu tieng Trung sang tieng Viet.\n"
    "Quy tac BAT BUOC:\n"
    "- Van phong tieu thuyet tu nhien, muot ma, dung giong nhan vat; KHONG dich may moc.\n"
    "- Giu nhat quan ten rieng nhan vat / dia danh (uu tien phien am Han-Viet hop ly).\n"
    "- GIU NGUYEN cau truc xuong dong va phan doan: so doan (cach nhau bang dong trong) phai khop ban goc.\n"
    "- TUYET DOI khong them loi giai thich, ghi chu, tieu de hay bat ky chu nao ngoai ban dich.\n"
    "- Neu input chi la mot tieu de ngan, chi tra ve tieu de da dich."
)


def gemini_generate(text: str, retries: int = 3, retry_delay: float = 5.0):
    """
    Goi Gemini REST API de dich Trung -> Viet.
    Tra ve chuoi da dich, hoac None neu that bai (de caller fallback sang Google).
    """
    if not GEMINI_API_KEY or not text.strip():
        return None

    url = GEMINI_URL_TPL.format(model=GEMINI_MODEL)
    payload = {
        "system_instruction": {"parts": [{"text": GEMINI_SYS_PROMPT}]},
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {"temperature": 0.3},
        "safetySettings": GEMINI_SAFETY,
    }

    for attempt in range(retries):
        try:
            resp = requests.post(
                url,
                params={"key": GEMINI_API_KEY},
                json=payload,
                timeout=120,
            )
            # 429 = het quota/qua nhanh -> cho roi thu lai
            if resp.status_code == 429:
                wait = retry_delay * (attempt + 2)
                print(f"  [Gemini 429] Cho {wait:.0f}s roi thu lai ({attempt+1}/{retries})...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()

            candidates = data.get("candidates", [])
            if not candidates:
                # Co the bi block boi prompt_feedback
                fb = data.get("promptFeedback", {})
                print(f"  [Gemini] Khong co ket qua (feedback={fb}).")
                return None

            parts = candidates[0].get("content", {}).get("parts", [])
            result = "".join(p.get("text", "") for p in parts).strip()
            return result or None

        except Exception as e:
            print(f"  [Loi Gemini] Lan {attempt+1}/{retries}: {e}")
            if attempt < retries - 1:
                time.sleep(retry_delay)

    return None


# ════════════════════════════════════════════════════════════
#  HELPER FUNCTIONS
# ════════════════════════════════════════════════════════════

# Sentinel: URL thuc sau redirect la trang ngoai (jjwxc.net, v.v.) -> chuong bi xoa/redirect
_REDIRECT_SENTINEL = object()


def get_html(url: str, retries: int = 3):
    """Tai HTML -> BeautifulSoup. Retry khi bi loi/CAPTCHA, doi IP sau cac lan that bai.
    Tra ve _REDIRECT_SENTINEL neu URL bi redirect sang domain ngoai (jjwxc.net).
    """
    for round_i in range(retries):
        try:
            resp = session.get(url, timeout=20)
            resp.raise_for_status()
            resp.encoding = "utf-8"

            # Phat hien redirect ra ngoai alicesw (vi du: jjwxc.net)
            final_url = resp.url
            if "alicesw.com" not in final_url and url.startswith("https://www.alicesw.com"):
                _log(f"  [Redirect] {url[:60]} -> {final_url[:60]} (ngoai alicesw)", "warn")
                return _REDIRECT_SENTINEL

            if any(m in resp.text for m in CAPTCHA_MARKERS):
                print(f"  [CAPTCHA] {url[:60]}")
            else:
                return BeautifulSoup(resp.text, "html.parser")
        except Exception as e:
            print(f"  [Loi] {url[:60]} (vong {round_i+1}): {e}")
        if round_i < retries - 1:
            if VPN_TYPE != "none":
                acquired = _html_rotate_lock.acquire(blocking=False)
                if acquired:
                    # Thread nay la nguoi rotate - cac thread khac se cho event
                    global _last_captcha_log_t
                    with _captcha_log_lock:
                        now = time.time()
                        if now - _last_captcha_log_t > 10:
                            _last_captcha_log_t = now
                            _log("CAPTCHA/loi -> doi IP roi thu lai...", "warn")
                    _html_rotate_done.clear()
                    rotate_ip()
                    _html_rotate_done.set()
                    _html_rotate_lock.release()
                else:
                    # Thread khac dang rotate, cho no xong roi retry
                    _html_rotate_done.wait(timeout=60)
            time.sleep(3)
    return None


# Fallback tag map cho layout Hán ngữ (khi IP ngoại quốc)
_TAG_MAP: dict[str, str] = {
    "乱伦": "Loạn luân", "母子": "Mẹ con", "母女": "Mẹ con gái",
    "母亲": "Mẹ", "儿子": "Con trai", "父女": "Cha con gái",
    "兄妹": "Anh em gái", "姐弟": "Chị em trai",
    "家庭": "Gia đình", "夫妻": "Vợ chồng",
    "老师": "Giáo viên", "学生": "Học sinh",
    "职场": "Công sở", "校园": "Học đường",
    "催眠": "Thôi miên", "调教": "Huấn luyện",
    "NTR": "NTR", "出轨": "Ngoại tình",
    "熟女": "Phụ nữ chín chắn", "少女": "Thiếu nữ",
    "巨乳": "Ngực to", "人妻": "Vợ người",
    "穿越": "Xuyên không", "重生": "Trọng sinh",
    "异世界": "Dị thế giới", "玄幻": "Huyền huyễn",
    "修仙": "Tu tiên", "武侠": "Võ hiệp",
    "都市": "Đô thị", "言情": "Ngôn tình",
    "短篇": "Truyện ngắn", "长篇": "Truyện dài",
    "凌辱": "Lăng nhục", "调教": "Huấn luyện",
    "媚黑": "Mê hắc", "肉文": "Nhục văn",
    "堕落": "Đọa lạc", "性奴": "Tình nô", "奴隶": "Nô lệ",
    "母亲": "Mẹ", "继母": "Mẹ kế", "岳母": "Mẹ vợ",
    "姐姐": "Chị gái", "妹妹": "Em gái",
    "轮奸": "Luân cưỡng", "强奸": "Cưỡng hiếp",
    "乡村": "Nông thôn", "农村": "Nông thôn",
    "剧情": "Cốt truyện", "情节": "Tình tiết",
    "受孕": "Thụ thai", "怀孕": "Mang thai",
    "小马拉大车": "Ngựa nhỏ kéo xe lớn",
    "巨根": "Cặc to", "巨屌": "Cặc to",
    "肥臀": "Mông béo", "巨臀": "Mông to",
    "偷情": "Ngoại tình", "出轨": "Ngoại tình",
    "丝袜": "Tất nylon", "黑丝": "Tất đen",
    "高跟": "Giày cao gót",
    "爸爸": "Bố", "父亲": "Cha", "儿女": "Con cái",
    "妻子": "Vợ", "老婆": "Vợ",
    "暗恋": "Yêu thầm", "禁忌": "Cấm kỵ",
    "绿帽": "Mọc sừng", "戴绿帽": "Bị cắm sừng",
    "兄弟": "Anh em", "同学": "Bạn học",
    "老师": "Giáo viên", "学生": "Học sinh",
    "邻居": "Hàng xóm", "上司": "Cấp trên",
    "秘书": "Thư ký", "护士": "Y tá",
    "空姐": "Tiếp viên hàng không",
    "游戏": "Game", "异能": "Dị năng",
    "妈妈": "Mẹ", "爸爸": "Bố",
    "换妻": "Hoán vợ", "交换伴侣": "Hoán đổi bạn đời",
    "中文/中国语": "Tiếng Trung", "中文／中国语": "Tiếng Trung",
    "反差": "Phản sai", "开大车": "Khai đại xa",
    "小孩开大车": "Tiểu hài khai đại xa",
    "正太": "Chính thái", "纯爱": "Thuần ái", "純愛": "Thuần ái",
    "足交": "Túc giao", "肛交": "Hậu giao",
    "中文": "Tiếng Trung", "中国语": "Tiếng Trung",
    "后宫": "Hậu cung", "後宮": "Hậu cung",
    "群交": "Quần giao", "3P": "3P", "4P": "4P",
    "肉便器": "Nhục tiện khí",
}

# Ánh xạ trạng thái Hán → Việt (fallback layout Hán ngữ)
_STATUS_CN_MAP: dict[str, str] = {
    "已完结": "Đã hoàn thành",
    "完结":   "Đã hoàn thành",
    "完結":   "Đã hoàn thành",
    "连载中": "Đang tiếp diễn",
    "連載中": "Đang tiếp diễn",
    "连载":   "Đang tiếp diễn",
}

_KW_RE = re.compile(r'#\s*([\wÀ-ỹĂăÂâĐđÊêÔôƠơƯư]+(?:\s+[\wÀ-ỹĂăÂâĐđÊêÔôƠơƯư]+)*)')


def _is_completed(status: str) -> bool:
    """Trả về True nếu truyện đã hoàn thành (hỗ trợ cả Việt lẫn Hán)."""
    s = status.lower()
    return ("hoàn thành" in s or "kết thúc" in s or "đã kết" in s
            or "已完结" in status or "完结" in status)


def sanitize_filename(name: str) -> str:
    """Loai bo ky tu khong hop le trong ten file Windows."""
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    return name.strip(". ")[:100]


def clean_title(name: str) -> str:
    """
    Chuan hoa ten truyen cho ten file:
      - Bo HET cum [ ... ] (ca noi dung ben trong - day la cac tag the loai dau truyen).
      - Voi 【 】: CHI bo dau ngoac, GIU LAI noi dung ben trong.
      - Gop khoang trang du, cat khoang trang dau/cuoi.
      - Chi viet HOA chu cai dau tien, cac chu con lai viet thuong (sentence case).
    """
    # Thu xoa tat ca [tag] truoc
    stripped = re.sub(r"\s+", " ", re.sub(r"\[[^\]]*\]", " ", name)).strip("_ ")
    # Neu phan con lai khong co chu co nghia (rong hoac chi so/ky hieu) -> bracket chua title that
    # -> chi bo ngoac, giu noi dung
    if not re.search(r"[a-zA-ZÀ-ɏ一-鿿]", stripped):
        name = re.sub(r"[\[\]]", "", name)
    else:
        name = stripped
    name = re.sub(r"[【】\[\]]", " ", name)     # bo dau【】va [] le con sot
    name = re.sub(r"\s+", " ", name).strip("_ ")
    if name:
        name = name[0].upper() + name[1:].lower()
    return name


def split_long_paragraph(para: str, max_size: int = 2000) -> list:
    """Chia nho mot doan van qua dai thanh cac doan ngan hon dua tren cac dau cau."""
    if len(para) <= max_size:
        return [para]
    
    parts = []
    current = ""
    # Tach theo cac dau cau tieng Trung
    sentences = re.split(r"([。！？；])", para)
    
    i = 0
    while i < len(sentences):
        sentence = sentences[i]
        punct = sentences[i+1] if i+1 < len(sentences) else ""
        combined = sentence + punct
        
        if len(current) + len(combined) > max_size:
            if current:
                parts.append(current)
            current = combined
        else:
            current += combined
        i += 2
        
    if current:
        parts.append(current)
        
    final_parts = []
    for part in parts:
        if len(part) > max_size:
            for j in range(0, len(part), max_size):
                final_parts.append(part[j:j+max_size])
        else:
            final_parts.append(part)
            
    return final_parts


def translate_text(text: str, retry_delay: float = 3.0, return_details: bool = False) -> tuple:
    """
    Dich doan van (Trung -> Viet). Tra ve (van_ban_da_dich, so_chunk_fail).
    so_chunk_fail tra ve theo gia tri (KHONG dung global) -> an toan khi dich song song.
    - Neu ENGINE = "gemini": uu tien Gemini (gui ca chuong 1 luot, chat luong cao);
      that bai thi tu rot ve Google.
    - Neu ENGINE = "google": dung Google Translate (chia nho + retry).
    """
    _fail = [0]  # dem chunk fail rieng cho moi lan goi (call-local -> an toan da luong)
    para_details = []

    if not text.strip():
        if return_details:
            return text, 0, []
        return text, 0

    # ── Engine Gemini (chat luong cao nhat) ──
    if ENGINE == "gemini":
        result = gemini_generate(text)
        if result:
            time.sleep(GEMINI_DELAY)
            if return_details:
                for p in result.split("\n\n"):
                    para_details.append((p, "Gemini", False))
                return result, 0, para_details
            return result, 0
        print("  [Gemini that bai -> fallback Google]")

    if not TRANSLATE_AVAILABLE:
        if return_details:
            for p in text.split("\n\n"):
                para_details.append((p, "None", True))
            return text, 0, para_details
        return text, 0

    # ── Chia text thanh cac chunk <= MAX_CHUNK ──────────────
    # B1: tach theo paragraph (\n\n)
    # B2: neu paragraph van qua dai (truyen lien tuc khong xuong dong) ->
    #     tach tiep theo dau cau Trung (。！？；)
    # B3: gom lai thanh chunk <= MAX_CHUNK, giu nguyen \n\n giua cac doan
    chunks: list[str] = []
    current_chunk = ""

    def _split_by_sentence(para: str) -> list[str]:
        """Chia doan qua dai theo dau cau tieng Trung."""
        if len(para) <= MAX_CHUNK:
            return [para]
        parts, buf = [], ""
        for token in re.split(r"([。！？；])", para):
            if len(buf) + len(token) > MAX_CHUNK and buf:
                parts.append(buf)
                buf = token
            else:
                buf += token
        if buf:
            parts.append(buf)
        return parts or [para]

    for raw_para in text.split("\n\n"):
        for para in _split_by_sentence(raw_para):
            # +2 cho "\n\n" se them vao
            if current_chunk and len(current_chunk) + len(para) + 2 > MAX_CHUNK:
                chunks.append(current_chunk.rstrip())
                current_chunk = para + "\n\n"
            else:
                current_chunk += para + "\n\n"

    if current_chunk.strip():
        chunks.append(current_chunk.rstrip())

    # ── Dich tung chunk, xoay engine khi bi loi ─────────────
    if ENGINE == "caiyun":
        _FREE_ENGINES = ["caiyun"]
    elif ENGINE == "google":
        _FREE_ENGINES = ["google"]
    else:
        _FREE_ENGINES = ["caiyun", "google"]   # bo Bing (hay 401) -> chi Caiyun + Google

    # Loi parse (JSON None, etc.) -> khong retry vi retry cung fail nhu nhau
    _NO_RETRY_ERRORS = ("NoneType", "JSON object", "JSONDecodeError", "object must be str")

    def _call_engine_once(text: str, eng: str) -> tuple:
        """
        Goi engine 1 lan. Tra ve (result_str, should_retry).
        should_retry=False khi gap loi parse -> khong ich gi khi thu lai.
        """
        try:
            result = _ts.translate_text(
                text, translator=eng,
                from_language="zh", to_language="vi",
                timeout=20,   # tranh treo vo han khi server khong phan hoi (freeze)
            )
            if result and result.strip():
                # Kiem tra neu ket qua bi loi khong dich (con nguyen chu Han) hoac tra ve y nguyen
                if result.strip() == text.strip():
                    _log_once(f"[{eng}] Loi: ket qua trung khop hoan toan voi text goc (chua dich) -> chuyen engine", "warn", expiry=8.0)
                    return None, True
                
                # Neu input co chu Han va output van con >= 5% chu Han thi coi nhu chua dich thanh cong
                input_han = sum(1 for c in text if "一" <= c <= "鿿")
                if input_han > 0:
                    output_han = sum(1 for c in result if "一" <= c <= "鿿")
                    output_ratio = output_han / len(result)
                    if output_ratio >= 0.05:
                        _log_once(f"[{eng}] Loi: ban dich con {output_ratio*100:.1f}% chu Han sot -> chuyen engine", "warn", expiry=8.0)
                        return None, True
                return result, False
        except Exception as e:
            msg = str(e)
            if "403" in msg or "Forbidden" in msg or "401" in msg:
                with _engine_lock:
                    if eng not in _engine_disabled:
                        _engine_disabled.add(eng)
                        _log(f"[{eng}] {msg[:60]} -> disable engine nay ca phien", "warn")
                return None, False  # khong retry, engine bi khoa
            is_parse_err = any(k in msg for k in _NO_RETRY_ERRORS)
            if is_parse_err:
                _log(f"[{eng}] Response loi (parse error) -> chuyen engine", "warn")
                return None, False  # khong retry
            _log_once(f"[Loi {eng}]: {msg[:80]}", "warn", expiry=8.0)
            return None, True  # co the retry
        return None, True

    def _call_engine_retry(text: str, eng: str, tries: int = 2) -> str | None:
        """Goi engine voi so lan retry, bo qua neu gap loi parse."""
        for attempt in range(tries):
            result, should_retry = _call_engine_once(text, eng)
            if result:
                return result
            if not should_retry:
                return None  # loi parse, khong ich retry
            if attempt < tries - 1:
                time.sleep(retry_delay)
        return None

    def _split_oversized(text: str, limit: int) -> list:
        """Cat text lon hon limit thanh cac phan nho, uu tien cat tai dau cau."""
        parts, remaining = [], text
        while remaining:
            if len(remaining) <= limit:
                parts.append(remaining)
                break
            cut_at = limit
            for punct in "。！？；\n":
                idx = remaining.rfind(punct, 0, limit)
                if idx > limit // 2:
                    cut_at = idx + 1
                    break
            parts.append(remaining[:cut_at])
            remaining = remaining[cut_at:]
        return parts

    def _translate_with_engine(text: str, eng: str, tries: int) -> str | None:
        """Dich text voi 1 engine, tu dong chia nho neu qua limit. Tra ve None neu fail."""
        limit = ENGINE_LIMITS.get(eng, 4990)
        if len(text) <= limit:
            return _call_engine_retry(text, eng, tries)
        # Qua lon: chia nho, dich tung phan, noi lai
        sub_parts = _split_oversized(text, limit)
        results = [_call_engine_retry(p, eng, tries) for p in sub_parts]
        return "".join(results) if all(results) else None

    def _translate_chunk_detailed(chunk_text: str) -> tuple[str, str] | None:
        """Moi chunk thu lan luot Caiyun -> Google, dung engine dau tien thanh cong. Tra ve (result, eng)"""
        for eng in _FREE_ENGINES:
            if eng in _engine_disabled:
                continue
            tries = 1 if eng == "caiyun" else 2
            result = _translate_with_engine(chunk_text, eng, tries)
            if result:
                with _engine_lock:
                    _engine_stats[eng] = _engine_stats.get(eng, 0) + 1
                return result, eng
        # Ca Caiyun + Google deu fail -> nghi 429/chan IP -> doi IP ProtonVPN roi thu lai 1 luot
        if rotate_ip_for_translate():
            for eng in _FREE_ENGINES:
                result = _translate_with_engine(chunk_text, eng, 1)
                if result:
                    with _engine_lock:
                        _engine_stats[eng] = _engine_stats.get(eng, 0) + 1
                    return result, eng
        return None

    def _translate_chunk(chunk_text: str):
        res = _translate_chunk_detailed(chunk_text)
        return res[0] if res else None

    def _is_sound_effect(text: str) -> bool:
        """
        Phat hien doan chi gom am thanh lap lai / emoji khong co nghia.
        Nhung doan nay cac engine dich hay tra ve null -> giu nguyen la hop le.
        VD: '啪啪啪啪啪❤~!!!', '哦哦哦哦哦哦哦'
        """
        import unicodedata
        if not text.strip():
            return True
        clean = text.strip()
        total = max(len(clean), 1)
        # Neu doan van dai hon 100 ky tu, chac chan khong phai am thanh lap lai don thuan
        if total > 100:
            return False
        # Chi bo qua chuoi rong hoac 1 ky tu don le (khong the dich co nghia)
        if total < 2:
            return True
        # Ky tu xuat hien nhieu nhat chiem >50% -> am thanh lap (啪啪啪, 哦哦哦)
        from collections import Counter
        top_count = Counter(clean).most_common(1)[0][1]
        if top_count / total > 0.50:
            return True
        # Qua it ky tu khac nhau -> van la am thanh
        if len(set(clean)) / total < 0.15:
            return True
        return False

    def _translate_exhaustive(text: str, depth: int = 0) -> str:
        """
        Dam bao dich het: neu tat ca engine fail, cat doi va thu lai de qui.
        Depth gioi han de quy, dung lai khi chunk qua nho (am thanh/emoji thuan tuy).
        """
        # Dung lai khi chunk la am thanh thuan tuy (啪啪啪, emoji lap...) - _is_sound_effect da co check < 15
        if _is_sound_effect(text):
            if return_details:
                for p in text.split("\n\n"):
                    para_details.append((p, "SoundEffect", False))
            return text  # giu nguyen, khong phai loi

        res = _translate_chunk_detailed(text)
        if res is not None:
            translated_chunk, eng = res
            if return_details:
                orig_paras = text.split("\n\n")
                trans_paras = translated_chunk.split("\n\n")
                if len(orig_paras) == len(trans_paras):
                    for orig_p, trans_p in zip(orig_paras, trans_paras):
                        para_details.append((trans_p, eng, False))
                else:
                    for p in trans_paras:
                        para_details.append((p, eng, False))
            return translated_chunk

        # Fail: neu con the cat doi -> cat tai dau cau gan giua
        if depth >= 4 or len(text) < 50:
            # Het kha nang cat -> giu nguyen, danh dau la loi that su
            _fail[0] += 1   # dem call-local (an toan da luong)
            if return_details:
                for p in text.split("\n\n"):
                    para_details.append((p, "None", True))
            return text

        mid = len(text) // 2
        # Tim dau cau gan giua nhat
        for punct in "。！？；\n":
            idx = text.rfind(punct, mid // 2, mid + mid // 2)
            if idx > 0:
                mid = idx + 1
                break

        left  = _translate_exhaustive(text[:mid],  depth + 1)
        right = _translate_exhaustive(text[mid:], depth + 1)
        return left + right

    translated_parts = []
    for chunk in chunks:
        result = _translate_exhaustive(chunk)
        translated_parts.append(result)
        time.sleep(TRANS_DELAY)

    full_translated = "\n\n".join(translated_parts).strip()
    if return_details:
        return full_translated, _fail[0], para_details
    return full_translated, _fail[0]


def translate_title(title: str, retries: int = 3, retry_delay: float = 2.0) -> str:
    """Dich tieu de chuong ngan; uu tien Gemini neu bat, that bai thi fallback Google."""
    if not title.strip():
        return title

    # ── Engine Gemini ──
    if ENGINE == "gemini":
        result = gemini_generate(title)
        if result:
            time.sleep(GEMINI_DELAY)
            return result.splitlines()[0].strip() if result else title

    if not TRANSLATE_AVAILABLE:
        return title
    if ENGINE == "caiyun":
        _FREE_ENGINES = ["caiyun"]
    elif ENGINE == "google":
        _FREE_ENGINES = ["google"]
    else:
        _FREE_ENGINES = ["caiyun", "google"]   # bo Bing (hay 401) -> chi Caiyun + Google
    for eng in _FREE_ENGINES:
        for attempt in range(retries):
            try:
                result = _ts.translate_text(
                    title, translator=eng,
                    from_language="zh", to_language="vi",
                )
                if result and result.strip():
                    time.sleep(TRANS_DELAY)
                    return result.splitlines()[0].strip()
            except Exception:
                if attempt < retries - 1:
                    time.sleep(retry_delay)
    # Fallback: chuyển ký tự Hán tự còn sót sang âm Hán Việt
    if _hv.has_hanzi(title):
        return _hv.hanzi_to_hanviet(title)
    return title


# ════════════════════════════════════════════════════════════
#  PHAN TICH WEB
# ════════════════════════════════════════════════════════════

def parse_novel_list_page(url: str) -> list:
    """
    Phan tich trang danh sach truyen (ho tro ca trang the loai va trang tim kiem).
    Tra ve list[dict]: title, novel_url, author, words, update_date
    """
    soup = get_html(url)
    if not soup:
        return []
    novels = []
    
    # 1. Neu la trang tim kiem (search)
    if soup.select("div.list-group div.list-group-item"):
        for item in soup.select("div.list-group div.list-group-item"):
            title_tag = item.select_one("h5 a")
            if not title_tag:
                continue
            
            href = title_tag.get("href", "")
            novel_url = (BASE_URL + href) if href.startswith("/") else href
            
            # Lay tieu de va xoa so thu tu o dau (vi du: "1. 跟妈妈..." -> "跟妈妈...")
            title = title_tag.get_text(strip=True)
            title = re.sub(r"^\d+\.\s*", "", title)
            
            # Lay tac gia va so chu
            author = "Khong ro"
            words = "?"
            author_p = item.select_one("p.mb-1")
            if author_p:
                author_text = author_p.get_text(strip=True)
                m_author = re.search(r"作者：([^\s字]+)", author_text)
                if m_author:
                    author = m_author.group(1).strip()
                else:
                    a_author = author_p.select_one("a[href*='author']")
                    if a_author:
                        author = a_author.get_text(strip=True)
                
                m_words = re.search(r"字数：([^\s浏览]+)", author_text)
                if m_words:
                    words = m_words.group(1).strip()
            
            # Lay ngay cap nhat
            update_date = "?"
            date_p = item.select_one("p.timedesc")
            if date_p:
                date_text = date_p.get_text(strip=True)
                m_date = re.search(r"更新时间：([^\s]+(?:\s+[^\s]+)?)", date_text)
                if m_date:
                    update_date = m_date.group(1).strip()
            
            novels.append({
                "title":       title,
                "novel_url":   novel_url,
                "author":      author,
                "words":       words,
                "update_date": update_date,
            })
            
    # 2. Neu la trang listing the loai thuong
    else:
        for ul in soup.select("div.rec_rullist ul"):
            title_tag  = ul.select_one("li.two a")
            author_tag = ul.select_one("li.four")
            words_tag  = ul.select_one("li.five")
            date_tag   = ul.select_one("li.six")
            if not title_tag:
                continue
            href      = title_tag.get("href", "")
            novel_url = (BASE_URL + href) if href.startswith("/") else href
            novels.append({
                "title":       title_tag.get_text(strip=True),
                "novel_url":   novel_url,
                "author":      author_tag.get_text(strip=True) if author_tag else "Khong ro",
                "words":       words_tag.get_text(strip=True)  if words_tag  else "?",
                "update_date": date_tag.get_text(strip=True)   if date_tag   else "?",
            })
            
    return novels


def get_total_pages(soup) -> int:
    total = 1
    for a in soup.select("ul.pagination a"):
        href = a.get("href", "")
        m = re.search(r"[?&](?:page|p)=(\d+)", href)
        if m:
            total = max(total, int(m.group(1)))
    return total


def iter_listing_pages(base_url: str, max_pages: int = 0, reverse: bool = False):
    """
    Generator: tra ve tung trang listing mot lan, moi yield la list[dict] cua trang do.
    reverse=True: tai tu trang CUOI nguoc len trang 1, danh sach tung trang cung dao nguoc.
    """
    is_search = "/search" in base_url
    param_name = "p" if is_search else "page"
    url_clean = re.sub(rf"[?&]{param_name}=\d+", "", base_url)
    connector = "&" if "?" in url_clean else "?"

    print(f"\n[*] Listing: {url_clean}  {'[NGUOC]' if reverse else ''}")
    soup = get_html(f"{url_clean}{connector}{param_name}=1")
    if not soup:
        print("[!] Khong the tai trang dau.")
        return

    total_pages = get_total_pages(soup)
    if max_pages > 0:
        total_pages = min(total_pages, max_pages)
    print(f"[*] Tong so trang: {total_pages}  (Ctrl+C de dung tai som va hien menu)")

    if not reverse:
        # Trang 1 da co soup, dung lai luon
        novels = parse_novel_list_page(f"{url_clean}{connector}{param_name}=1")
        if novels:
            yield 1, total_pages, novels
        page_range = range(2, total_pages + 1)
    else:
        # Nguoc: tu trang cuoi ve trang 1 (tai lai trang 1 de dong nhat)
        page_range = range(total_pages, 0, -1)

    for page in page_range:
        time.sleep(DELAY)
        page_url = f"{url_clean}{connector}{param_name}={page}"
        print(f"  [{page}/{total_pages}] Dang tai trang {page}...", end="\r", flush=True)
        novels = parse_novel_list_page(page_url)
        if novels:
            yield page, total_pages, (list(reversed(novels)) if reverse else novels)


def get_all_pages_from_listing(base_url: str, max_pages: int = 0) -> list:
    """Gop tat ca trang listing thanh 1 list (dung cho show_novel_menu).
    Nhan Ctrl+C giua chung se dung tai trang moi nhung van hien menu voi so truyen da co.
    """
    all_novels = []
    current_page = 0
    try:
        for page_num, total_pages, novels in iter_listing_pages(base_url, max_pages):
            current_page = page_num
            all_novels.extend(novels)
            print(f"  [{page_num}/{total_pages}] Trang {page_num}: +{len(novels)} truyen  (tong: {len(all_novels)})", flush=True)
    except KeyboardInterrupt:
        print(f"\n[!] Dung tai (Ctrl+C) sau trang {current_page}. Da co {len(all_novels)} truyen.")
        print("    Tiep tuc hien menu voi so truyen da tai duoc...")

    print(f"\n[*] Tong cong {len(all_novels)} truyen.")
    return all_novels


def get_novel_info(novel_url: str):
    soup = get_html(novel_url)
    if not soup:
        return None
    m = re.search(r"/novel/(\d+)\.html", novel_url)
    novel_id = m.group(1) if m else "0"

    title = ""
    tag   = soup.select_one("div.novel_title")
    if tag:
        title = tag.get_text(strip=True)
    if not title:
        t = soup.find("title")
        if t:
            title = t.get_text().split("-")[0].strip()

    author    = ""
    tags_vi:  list[str] = []   # từ layout Việt (Từ khóa / Thể loại)
    tags_cn:  list[str] = []   # từ layout Hán (分类)
    status_vi = ""             # layout Việt (Trạng thái)
    status_cn = ""             # layout Hán (状态)

    for p in soup.select("div.novel_info p"):
        text = p.get_text(separator=" ")
        # ── Layout Việt ──────────────────────────────────────
        if "Tác giả" in text or ("Tác" in text and "giả" in text):
            a_tag  = p.find("a")
            author = a_tag.get_text(strip=True) if a_tag else re.sub(r".*[：:\s]", "", text).strip()
        elif "Thể loại" in text:
            tags_vi = [a.get_text(strip=True) for a in p.find_all("a")]
        elif "Trạng thái" in text:
            status_vi = re.sub(r"Trạng\s*thái\s*[：:]\s*", "", text).strip()
        # ── Layout Hán (fallback) ─────────────────────────────
        elif "作" in text and "者" in text:
            a_tag  = p.find("a")
            author = a_tag.get_text(strip=True) if a_tag else re.sub(r".*[：:]", "", text).strip()
        elif "分" in text and "类" in text:
            tags_cn = [a.get_text(strip=True) for a in p.find_all("a")]
        elif "标" in text and "签" in text:
            # 标签：#乱伦#乡村#剧情... → tách theo #, bỏ phần "注意：..."
            raw = re.sub(r"标\s*签\s*[：:]\s*", "", text)
            raw = re.split(r"注意|请谨慎", raw)[0]   # cắt phần ghi chú phía sau
            parts = [t.strip() for t in raw.split("#") if t.strip()]
            if parts:
                tags_cn = parts   # override phân loại bằng tag đầy đủ hơn
        elif "状" in text and "态" in text:
            status_cn = re.sub(r"[状态：:\s]+", "", text).strip()

    # Layout Hán: parse div.tags_list trực tiếp — <a> không nằm trong <p>
    # Một số novel nhét cả '#tag1#tag2' vào 1 <a> → split thêm theo #
    tags_div = soup.select_one("div.tags_list")
    if tags_div:
        cn_links = []
        for a in tags_div.find_all("a"):
            for part in a.get_text(strip=True).split("#"):
                part = part.strip()
                if part:
                    cn_links.append(part)
        if cn_links:
            tags_cn = cn_links  # override, đầy đủ hơn loop p

    # Từ khóa (layout Việt) — luôn ưu tiên, tìm đúng element chứa trực tiếp
    kw_node = soup.find(string=re.compile(r"Từ\s*khóa"))
    if kw_node:
        kw_parent = kw_node.find_parent(["p", "div", "span", "li"])
        if kw_parent:
            kw_links = []
            for a in kw_parent.find_all("a"):
                for part in a.get_text(strip=True).split("#"):
                    part = part.strip()
                    if part:
                        kw_links.append(part)
            if kw_links:
                tags_vi = kw_links
            else:
                raw = kw_parent.get_text(separator=" ")
                raw = raw.split("Từ khóa", 1)[-1].split(":", 1)[-1]
                parts = [p.strip() for p in raw.split("#") if p.strip()]
                tags_vi = [p.rstrip(" \t\n.,;:") for p in parts]

    return {
        "title":     title,
        "author":    author or "Khong ro",
        "novel_id":  novel_id,
        "novel_url": novel_url,
        "tags_vi":   tags_vi,
        "tags_cn":   tags_cn,
        "status_vi": status_vi,
        "status_cn": status_cn,
    }


def get_chapter_list(novel_id: str) -> list:
    url  = f"{BASE_URL}/other/chapters/id/{novel_id}.html"
    soup = get_html(url)
    if not soup:
        return []
    chapters = []
    for li in soup.select("ul.mulu_list li"):
        a = li.find("a")
        if not a or not a.get("href"):
            continue
        href = a["href"]
        if href.endswith("/0.html"):
            continue
        chapter_url = (BASE_URL + href) if href.startswith("/") else href
        chapters.append({"title": a.get_text(strip=True), "url": chapter_url})
    return chapters


# Backoff cho chuong tra ve noi dung rong: NGAN truoc (loi ngau nhien hay gap nhat),
# dai dan sau (phong khi bi block nang). Do thuc nghiem: alicesw thi thoang tra trang
# rong NGAU NHIEN (~8%), chuong ngay sau thu lai thuong OK -> khong can cho lau.
_EMPTY_RETRY_WAITS = [3, 8, 20, 40]

def get_chapter_content(chapter_url: str, retries: int = 5, novel_title: str = "", ch_title_hint: str = "") -> tuple:
    """
    Tai noi dung mot chuong. Tra ve (chapter_title: str, paragraphs: list[str]).

    LUU Y: alicesw thi thoang tra ve trang chi co tieu de "第X章", noi dung RONG
    (vai chu Han) - khong phai loi HTTP, khong phai CAPTCHA cookie. Phai check SO CHU
    HAN (trang rong van co the co 1 doan rong) chu khong chi check "co doan khong".
    Loi nay phan lon NGAU NHIEN/tam thoi -> thu lai sau vai giay la ra ban that.
    Neu chuong bi redirect sang jjwxc.net -> tra ve placeholder ngay, khong retry.
    """
    chapter_title = ""
    paras = []
    prev_key = None
    for attempt in range(retries):
        paras, chapter_title = _fetch_chapter_once(chapter_url, novel_title=novel_title, ch_title_hint=ch_title_hint)
        # Placeholder redirect -> chuong bi mat/xoa, khong retry
        if chapter_title == "(bi thieu - can xem lai)":
            return chapter_title, paras
        han = sum(1 for p in paras for c in p if '一' <= c <= '鿿')
        if han >= CHAPTER_MIN_HAN:
            return chapter_title, paras
        curr_key = "||".join(paras)
        # Noi dung giong het lan truoc -> chuong that su ngan (thong bao tac gia), khong phai CAPTCHA
        if prev_key is not None and curr_key == prev_key:
            return chapter_title, paras
        prev_key = curr_key
        if attempt < retries - 1:
            wait = _EMPTY_RETRY_WAITS[min(attempt, len(_EMPTY_RETRY_WAITS) - 1)]
            _log(f"  Noi dung qua it ({han} chu Han, lan {attempt+1}/{retries}) "
                 f"- cho {wait}s roi thu lai...", "warn")
            time.sleep(wait)
    return chapter_title, paras


def _fetch_chapter_once(chapter_url: str, novel_title: str = "", ch_title_hint: str = "") -> tuple:
    """Tai 1 lan, tra ve (paras, title). Dung boi get_chapter_content.
    Neu URL bi redirect sang jjwxc.net (chuong bi xoa/an), tra ve placeholder
    thay vi rong de pipeline khong retry va khong ghi vao failed.
    """
    soup = get_html(chapter_url)

    # Redirect sang jjwxc.net hoac domain ngoai -> ghi placeholder, xem nhu thanh cong
    if soup is _REDIRECT_SENTINEL:
        label_parts = [p for p in [novel_title, ch_title_hint] if p]
        label = " - ".join(label_parts) if label_parts else chapter_url[:60]
        _log(f"[THIEU] {label} - bi thieu can xem lai", "warn")
        placeholder = f"[{label} - bi thieu can xem lai]"
        return [placeholder], "(bi thieu - can xem lai)"

    if not soup:
        return [], ""

    # Phat hien trang CAPTCHA som -> bo qua ngay
    page_text = soup.get_text()
    if any(m in page_text for m in CAPTCHA_MARKERS):
        return [], ""

    # Tieu de
    chapter_title = ""
    for sel in ["h1", "h2.chapter-title", ".chaptername", ".chapter-title"]:
        tag = soup.select_one(sel)
        if tag:
            chapter_title = tag.get_text(strip=True)
            break

    # Noi dung
    content_div = None
    for sel in [
        "div.read-content",       # alicesw.com primary
        "div#content",
        "div.content",
        "div.chapter-content",
        "div#chaptercontent",
        "div.booktextdata",
        "div#booktextdata",
        "div.noveltext",
        "div#noveltext",
        "article",
    ]:
        div = soup.select_one(sel)
        if div and len(div.get_text(strip=True)) > 200:
            content_div = div
            break

    # Fallback: div co nhieu <p> nhat
    if not content_div:
        candidates = [d for d in soup.find_all("div") if len(d.find_all("p")) >= 5]
        content_div = max(candidates, key=lambda d: len(d.get_text(strip=True)), default=None)

    if not content_div:
        # Fallback cuoi: lay tat ca text co chu Han
        all_text = soup.get_text("\n", strip=True)
        paras = [ln for ln in all_text.splitlines()
                 if ln.strip() and any('\u4e00' <= c <= '\u9fff' for c in ln)]
        return paras, chapter_title

    for tag in content_div.select("script, style, .gg, iframe, [class*='ad']"):
        tag.decompose()

    paras = []
    for elem in content_div.find_all(["p", "br"]):
        text = elem.get_text(strip=True)
        if text and len(text) > 1:
            paras.append(text)

    if not paras:
        raw  = content_div.get_text("\n", strip=True)
        paras = [ln for ln in raw.splitlines() if ln.strip()]

    # Trang chan tra ve placeholder (vd "提示信息") thay vi chuong that:
    # noi dung qua it chu Han + chua marker chan -> coi nhu rong de retry/doi IP.
    # (Chuong ngan that su KHONG chua cac marker nay -> van duoc giu lai)
    content_text = "".join(paras)
    han_in_content = sum(1 for c in content_text if '一' <= c <= '鿿')
    if han_in_content < CHAPTER_MIN_HAN and any(m in content_text for m in PLACEHOLDER_MARKERS):
        return [], chapter_title

    return paras, chapter_title


# ════════════════════════════════════════════════════════════
#  THEO DOI TIEN DO BATCH (resume + log loi)
# ════════════════════════════════════════════════════════════

def _state_paths(out_dir: Path) -> dict:
    """4 file rieng cho origin va translated."""
    return {
        "origin_done": out_dir / "_origin_progress.json",
        "origin_fail": out_dir / "_origin_failed.json",
        "trans_done":  out_dir / "_translated_progress.json",
        "trans_fail":  out_dir / "_translated_failed.json",
    }


def load_state(out_dir: Path) -> dict:
    """Doc tien do/loi rieng cho origin va translated.
      origin_done / trans_done : {novel_id: ten_file.txt}
      origin_fail / trans_fail : {novel_id: ly_do}
      origin_no_chapters       : {novel_id: ghi_chu}  - khong lay duoc danh sach chuong
      origin_redirect          : {novel_id: ghi_chu}  - co chuong bi redirect sang jjwxc.net
    _origin_progress.json luu ca 3 nhom: done / no_chapters / redirect.
    """
    def _load(p: Path, default):
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass
        return default
    pp = _state_paths(out_dir)

    # _origin_progress.json: ho tro dinh dang cu (flat {id: file}) va moi ({done,no_chapters,redirect})
    raw_origin = _load(pp["origin_done"], {})
    if isinstance(raw_origin, dict) and "done" in raw_origin:
        origin_done        = raw_origin.get("done", {})
        origin_no_chapters = raw_origin.get("no_chapters", {})
        origin_redirect    = raw_origin.get("redirect", {})
    else:
        origin_done        = raw_origin
        origin_no_chapters = {}
        origin_redirect    = {}

    origin_fail = _load(pp["origin_fail"], {})
    trans_done  = _load(pp["trans_done"],  {})
    trans_fail  = _load(pp["trans_fail"],  {})

    # Enforce consistency: ID da co trong done khong duoc nam trong fail.
    # Nguyen nhan pho bien: script bi ngat giua 2 lan write file state.
    stale_of = set(origin_fail) & set(origin_done)
    stale_tf = set(trans_fail)  & set(trans_done)
    if stale_of:
        for nid in stale_of:
            del origin_fail[nid]
    if stale_tf:
        for nid in stale_tf:
            del trans_fail[nid]
    if stale_of or stale_tf:
        _log(f"[load_state] Tu dong xoa {len(stale_of)} origin_fail + {len(stale_tf)} trans_fail"
             " khong nhat quan (ID da co trong done).", "ok")

    return {
        "origin_done":        origin_done,
        "origin_fail":        origin_fail,
        "trans_done":         trans_done,
        "trans_fail":         trans_fail,
        "origin_no_chapters": origin_no_chapters,
        "origin_redirect":    origin_redirect,
        "_counter":           0,
    }


def save_state(out_dir: Path, st: dict):
    """Ghi 4 file (ghi sau moi truyen de crash van resume duoc).
    _origin_progress.json ghi ca done / no_chapters / redirect vao 1 JSON.
    Enforce consistency truoc khi ghi: xoa ID trong fail neu da co trong done."""
    # Enforce: ID trong done khong duoc o trong fail (cap nhat st in-place)
    for nid in list(st.get("origin_fail", {})):
        if nid in st.get("origin_done", {}):
            del st["origin_fail"][nid]
    for nid in list(st.get("trans_fail", {})):
        if nid in st.get("trans_done", {}):
            del st["trans_fail"][nid]

    pp = _state_paths(out_dir)
    try:
        pp["origin_done"].write_text(
            json.dumps({
                "done":        st["origin_done"],
                "no_chapters": st.get("origin_no_chapters", {}),
                "redirect":    st.get("origin_redirect", {}),
            }, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        pp["origin_fail"].write_text(
            json.dumps(st["origin_fail"], ensure_ascii=False, indent=2), encoding="utf-8")
        pp["trans_done"].write_text(
            json.dumps(st["trans_done"], ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        pp["trans_fail"].write_text(
            json.dumps(st["trans_fail"], ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"  [!] Khong luu duoc tien do: {e}")


def append_failed_novel(out_dir: Path, url: str, reason: str):
    """Ghi truyen loi vao file text de chay lai 1 luot rieng sau nay."""
    try:
        with open(out_dir / "_failed_novels.txt", "a", encoding="utf-8") as f:
            f.write(f"{url}\t{reason}\n")
    except Exception:
        pass


def log_failed_chunk(out_dir: Path, novel_id: str, chapter_idx: int, fail_count: int):
    """Ghi log chuong co chunk dich fail (de biet cho nao con tieng Trung)."""
    try:
        with open(out_dir / "_failed_chunks.log", "a", encoding="utf-8") as f:
            f.write(f"novel={novel_id} chuong={chapter_idx} so_chunk_fail={fail_count}\n")
    except Exception:
        pass


# ════════════════════════════════════════════════════════════
#  VIET FILE
# ════════════════════════════════════════════════════════════

def format_chapter_text(ch_title: str, paras: list, sep: str = "\n\n", separators: bool = True) -> str:
    """Dinh dang mot chuong thanh chuoi van ban."""
    content = sep.join(paras)
    if separators:
        return f"{ch_title}\n{'─'*40}\n\n{content}\n"
    return f"{ch_title}\n\n{content}\n"


def parse_orig_cache(orig_text: str) -> tuple:
    """Tach (ch_title, paras) tu van ban goc da format_chapter_text (separators=True).
    Dung de lay lai tieu de + cac doan tu cache ma dich (khong can tai lai HTML)."""
    sep_line = "─" * 40
    if sep_line in orig_text:
        head, body = orig_text.split(sep_line, 1)
        ch_title = head.strip()
    else:
        parts = orig_text.split("\n\n", 1)
        ch_title = parts[0].strip()
        body = parts[1] if len(parts) > 1 else ""
    paras = [p.strip() for p in body.split("\n\n") if p.strip()]
    return ch_title, paras


def cleanup_old_count_files(directory: Path, title: str, keep_name: str):
    """
    Xoa cac file cu cua CUNG truyen nhung khac so chuong.
    Dung khi truyen ra them chuong moi -> ten file '...+50 Chuong.txt' bi
    thay bang '...+55 Chuong.txt'; file cu can duoc don de tranh trung lap.
    KHONG dung toi thu muc .cache (resume van an toan).
    """
    if not directory.exists():
        return
    prefix = f"{title}+"
    for old in directory.iterdir():
        # Chi xoa file cung tien to ten truyen, dung dinh dang '+N Chuong'
        if (old.is_file()
                and old.name.startswith(prefix)
                and old.name != keep_name
                and " Chuong" in old.name):
            try:
                old.unlink()
                print(f"  [Don] Xoa file cu (so chuong thay doi): {old.name}")
            except Exception as e:
                print(f"  [!] Khong xoa duoc {old.name}: {e}")


def write_full_book(out_file: Path, novel_info: dict, chapter_data: dict, total: int,
                    engine: str = "", separators: bool = True):
    """
    Ghi toan bo truyen vao file.
    separators=True  : giu dong ke === va --- (file goc)
    separators=False : bo dong ke (file dich, doc tren app/reader)
    """
    # tags_vi: ưu tiên tags đã Việt hóa từ trang, fallback dùng _TAG_MAP rồi Hán Việt
    def _tag_vi(t: str) -> str:
        if t in _TAG_MAP:
            return _TAG_MAP[t]
        return _hv.hanzi_to_hanviet(t) if _hv.has_hanzi(t) else t

    raw_vi = novel_info.get("tags_vi") or []
    raw_cn = novel_info.get("tags_cn") or []
    raw    = raw_vi if raw_vi else raw_cn
    _seen: set[str] = set()
    tags_vi = []
    for _t in raw:
        _t = _t.lstrip("#").strip()
        if not _t:
            continue
        _tv = _tag_vi(_t)
        if _tv.lower() not in _seen:
            _seen.add(_tv.lower())
            tags_vi.append(_tv)
    raw_status = novel_info.get("status_vi") or novel_info.get("status_cn", "")
    status_vi  = _STATUS_CN_MAP.get(raw_status, raw_status)
    with open(out_file, "w", encoding="utf-8") as f:
        if separators:
            f.write(f"{'='*60}\n")
        f.write(f"  {novel_info['title']}\n")
        author_vi = _hv.hanzi_to_hanviet(novel_info['author']) if _hv.has_hanzi(novel_info['author']) else novel_info['author']
        f.write(f"  Tác giả    : {author_vi}\n")
        f.write(f"  Nguồn      : {novel_info['novel_url']}\n")
        if tags_vi:
            f.write(f"  Tag        : {', '.join('#' + t[:1].upper() + t[1:] for t in tags_vi)}\n")
        f.write(f"  Chương     : {total}\n")
        if status_vi:
            f.write(f"  Tình trạng : {status_vi}\n")
        if engine:
            f.write(f"  Dịch       : {engine}\n")
        if separators:
            f.write(f"{'='*60}\n\n")
        else:
            f.write(f"\n")
        for i in range(1, total + 1):
            if i in chapter_data:
                f.write(f"\n\n{'─'*50}\n" if separators else f"\n\n")
                f.write(chapter_data[i])


# ════════════════════════════════════════════════════════════
#  DOI IP QUA PROTONVPN CLI
# ════════════════════════════════════════════════════════════

def _get_ip() -> str:
    """Lay IP public hien tai (qua cloudflare trace). '' neu loi."""
    try:
        r = requests.get("https://www.cloudflare.com/cdn-cgi/trace", timeout=8)
        for ln in r.text.splitlines():
            if ln.startswith("ip="):
                return ln[3:].strip()
    except Exception:
        pass
    return ""


def reset_translator_sessions():
    """Reset translators sessions to avoid 429 session/cookie leak."""
    if TRANSLATE_AVAILABLE and _ts:
        try:
            for translator_name, translator_instance in _ts.server.tss._translators_dict.items():
                if hasattr(translator_instance, "session"):
                    translator_instance.session = None
                    translator_instance.language_map = None
                    translator_instance.query_count = 0
            _log("Da reset cookie/session cua cac engine dich de tranh bi nhan dien 429.", "ok")
        except Exception as e:
            _log(f"Khong the reset session cua translators: {e}", "warn")


def rotate_proton_ip():
    """Doi IP qua ProtonVPN (cross-process lock, an toan khi chay song song voi txt_to_mp3).
    Uu tien CLI (protonvpn-cli connect --random); neu khong co CLI thi restart Windows Service
    'ProtonVPN Service' (app GUI - CAN chay script voi quyen Administrator)."""
    if not USE_PROTON:
        _log("Khong tim thay ProtonVPN CLI/Service, bo qua doi IP.", "warn")
        return False

    if not _vpn_lock.acquire(timeout=15):
        _log("VPN lock timeout - process khac dang doi IP, bo qua.", "warn")
        return False
    try:
        gap = _vpn_lock.elapsed_since_last()
        if gap is not None and gap < 45:
            return False  # vua doi IP -> im lang, khong log spam
        old_ip = _get_ip()
        if PROTON_CLI:
            # _log("Doi IP ProtonVPN (CLI: disconnect -> connect --random)...", "warn")
            subprocess.run([PROTON_CLI, "disconnect"], timeout=15, capture_output=True)
            time.sleep(3)
            subprocess.run([PROTON_CLI, "connect", "--random"], timeout=30, capture_output=True)
        else:
            # _log("Doi IP ProtonVPN (restart Windows Service - can quyen Admin)...", "warn")
            subprocess.run(["sc", "stop", _PROTON_SVC], timeout=20, capture_output=True)
            time.sleep(3)
            subprocess.run(["sc", "start", _PROTON_SVC], timeout=20, capture_output=True)
        # Cho VPN ket noi lai + xac minh IP da doi
        for _ in range(15):
            time.sleep(1)
            new_ip = _get_ip()
            if new_ip:
                _vpn_lock.record_rotation()
                tag = "(IP MOI)" if (old_ip and new_ip != old_ip) else "(IP nhu cu)"
                _log(f"ProtonVPN: {new_ip} {tag}", "ok")
                reset_translator_sessions()
                return True
        _log("Doi IP xong nhung chua xac nhan duoc IP moi.", "warn")
        _vpn_lock.record_rotation()
        reset_translator_sessions()
        return True
    except Exception as e:
        _log(f"Khong the doi IP ProtonVPN: {e}", "warn")
        return False
    finally:
        _vpn_lock.release()


def rotate_warp_ip():
    """Doi IP qua Cloudflare WARP (cross-process lock, an toan khi chay song song)."""
    warp_cli = r"C:\Program Files\Cloudflare\Cloudflare WARP\warp-cli.exe"
    if not os.path.exists(warp_cli):
        _log("Khong tim thay Cloudflare WARP CLI (warp-cli.exe), bo qua doi IP.", "warn")
        return False

    if not _vpn_lock.acquire(timeout=15):
        _log("VPN lock timeout - process khac dang doi IP, bo qua.", "warn")
        return False
    try:
        gap = _vpn_lock.elapsed_since_last()
        if gap is not None and gap < 30:
            return False  # vua doi IP -> im lang
        old_ip = _get_ip()
        
        subprocess.run([warp_cli, "disconnect"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)
        subprocess.run([warp_cli, "connect"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # Cho ket noi lai + xac minh IP da doi
        for _ in range(15):
            time.sleep(1)
            new_ip = _get_ip()
            if new_ip:
                _vpn_lock.record_rotation()
                tag = "(IP MOI)" if (old_ip and new_ip != old_ip) else "(IP nhu cu)"
                _log(f"Cloudflare WARP: {new_ip} {tag}", "ok")
                reset_translator_sessions()
                return True
        _log("Doi IP xong nhung chua xac nhan duoc IP moi.", "warn")
        _vpn_lock.record_rotation()
        reset_translator_sessions()
        return True
    except Exception as e:
        _log(f"Khong the doi IP Cloudflare WARP: {e}", "warn")
        return False
    finally:
        _vpn_lock.release()


def rotate_ip() -> bool:
    """Tu dong xoay IP dua tren VPN_TYPE."""
    if VPN_TYPE == "protonvpn":
        return rotate_proton_ip()
    elif VPN_TYPE == "warp":
        return rotate_warp_ip()
    return False


def rotate_ip_for_translate() -> bool:
    """Doi IP khi DICH bi chan (Caiyun+Google deu fail -> nghi 429/chan IP).
    Throttle: neu vua doi IP < TRANSLATE_ROTATE_MIN giay (boi thread/process khac) thi
    bo qua - IP moi da co hieu luc cho moi luong. Tra ve True neu vua doi IP."""
    if VPN_TYPE == "none":
        return False
    with _translate_rotate_lock:
        gap = _vpn_lock.elapsed_since_last()
        if gap is not None and gap < TRANSLATE_ROTATE_MIN:
            return False   # vua doi IP gan day -> khong xoay nua
        _log_once(f"Dich bi chan (Caiyun+Google fail) -> doi IP qua {VPN_TYPE}...", "warn", expiry=15.0)
        return rotate_ip()


# ════════════════════════════════════════════════════════════
#  TAI TRUYEN CHINH
# ════════════════════════════════════════════════════════════

def download_novel(novel_info: dict, base_output: Path, delay: float, do_translate: bool,
                   workers: int = 1, skip_translated: bool = False):
    """
    Tai toan bo truyen.
    Luu 2 thu muc:
      <base_output>/origin/      - ban goc tieng Trung
      <base_output>/translated/  - ban dich tieng Viet (neu do_translate=True)

    workers > 1: tai cac chuong SONG SONG (chi khi --no-translate). Khong dung cho
    che do dich vi khau dich phai TUAN TU (token Caiyun dung chung).
    """
    title    = sanitize_filename(novel_info["title"])
    author   = novel_info.get("author", "Khong ro")
    novel_id = novel_info["novel_id"]

    # Cac thu muc
    origin_dir  = base_output / "origin"
    trans_dir   = base_output / "translated"
    cache_dir   = base_output / ".cache" / novel_id

    origin_dir.mkdir(parents=True, exist_ok=True)
    if do_translate:
        trans_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Lay danh sach chuong truoc de biet tong so chuong
    print("[*] Dang lay danh sach chuong...")
    chapters = get_chapter_list(novel_id)
    if not chapters:
        print("[!] Khong lay duoc danh sach chuong!")
        # Lay ten tieng Viet tu cache neu co, khong thi dich nhanh
        title_cache = cache_dir / "title_vi.txt"
        if title_cache.exists() and title_cache.stat().st_size > 0:
            vn_title = sanitize_filename(clean_title(title_cache.read_text(encoding="utf-8").strip()))
        else:
            _t = translate_title(novel_info["title"])
            vn_title = sanitize_filename(clean_title(_t or novel_info["title"]))
            if _t and _t != novel_info["title"]:
                title_cache.write_text(_t, encoding="utf-8")
        note_file = origin_dir / f"{vn_title}_khong_lay_duoc_chuong.txt"
        note_file.write_text(
            f"{vn_title}\n"
            f"Khong lay duoc danh sach chuong. Xem lai link:\n"
            f"{novel_info['novel_url']}\n",
            encoding="utf-8",
        )
        _log(f"Ghi file thong bao: {note_file.name}", "warn")
        return {
            "origin_ok":     True,
            "no_chapters":   True,
            "origin_file":   note_file.name,
            "trans_ok":      True,
            "trans_file":    "",
            "redirect_count": 0,
        }
    total = len(chapters)
    print(f"[*] Tong so chuong: {total}")

    # Truyen dai (>10 chuong): doi IP truoc khi tai de co IP sach.
    # Throttle: chi doi neu chua reset IP trong 5 phut gan day (tranh doi lien tuc).
    if total > 10 and VPN_TYPE != "none":
        elapsed = _vpn_lock.elapsed_since_last()
        if elapsed is None or elapsed > 300:
            _log("Truyen dai (>10 chuong) -> doi IP truoc khi tai...", "warn")
            rotate_ip()

    # Ten truyen LUON dich sang tieng Viet (de ten file origin/translated deu tieng Viet),
    # ke ca khi --no-translate. Cache lai de nhat quan qua moi lan chay.
    title_cache = cache_dir / "title_vi.txt"
    if title_cache.exists() and title_cache.stat().st_size > 0:
        cached = title_cache.read_text(encoding="utf-8").strip()
        if cached:
            title = sanitize_filename(cached)
    else:
        print("[*] Dang dich ten truyen sang tieng Viet...")
        translated_title = translate_title(novel_info["title"])
        if translated_title and translated_title != novel_info["title"]:
            title = sanitize_filename(translated_title)
            title_cache.write_text(translated_title, encoding="utf-8")

    # Chuan hoa ten truyen: bo ngoac vuong + sentence case (giu nguyen duoi "+N Chuong")
    title = clean_title(title)
    novel_info["title"] = title

    # _end suffix khi truyen da hoan thanh
    _status_raw = novel_info.get("status_vi") or novel_info.get("status_cn", "")
    _end = "_end" if _is_completed(_status_raw) else ""

    # Dat ten file theo dinh dang: <Ten Truyen Viet>+<So Chuong> Chuong_origin[_end].txt
    origin_file = origin_dir / f"{title}+{total} Chuong_origin{_end}.txt"
    trans_file  = trans_dir  / f"{title}+{total} Chuong{_end}.txt"

    # --skip-translated: bo qua neu ban dich da ton tai
    if skip_translated and do_translate and trans_file.exists() and trans_file.stat().st_size > 1000:
        _log(f"(da dich) {trans_file.name} - bo qua", "ok")
        return True

    print(f"\n{'='*60}")
    print(f"  Truyen : {title} ({novel_info['title']})")
    print(f"  Tac gia: {author}")
    print(f"  Ban goc: {origin_file}")
    if do_translate:
        print(f"  Dich   : {trans_file}")
    print(f"{'='*60}")

    origin_texts = {}
    trans_texts  = {}
    origin_failed      = 0   # so chuong GOC bi loi (trang rong/CAPTCHA) -> origin chua hoan chinh
    origin_failed_urls = []  # URL cac chuong bi loi (trang rong/CAPTCHA)
    trans_failed       = 0   # so doan DICH fail / chu Han sot -> ban dich chua hoan chinh
    placeholder_count = [0]  # so chuong bi redirect sang jjwxc.net (dung list de closure ghi duoc)
    global _engine_stats
    _engine_stats = {}  # reset dem engine cho tung truyen

    # ════════════════════════════════════════════════════════
    #  CHE DO SONG SONG
    #   - Pha A: tai HTML song song (workers luong) -> cache goc
    #   - Pha B: dich cac chuong song song (TRANSLATE_WORKERS luong)
    #  Moi chunk thu Caiyun->Google; 3 luong chay song song tu do.
    # ════════════════════════════════════════════════════════
    if workers > 1 or (do_translate and TRANSLATE_WORKERS > 1):
        log_lock   = threading.Lock()
        trans_lock = threading.Lock()

        # ── Pha A: resume cache goc + gom chuong can tai HTML ──
        todo = []
        for i, ch in enumerate(chapters, 1):
            cache_orig = cache_dir / f"{i:06d}_orig.txt"
            if cache_orig.exists() and cache_orig.stat().st_size > 20:
                cached = cache_orig.read_text(encoding="utf-8")
                han_cached = sum(1 for c in cached if '一' <= c <= '鿿')
                if han_cached >= CHAPTER_MIN_HAN and not any(m in cached for m in PLACEHOLDER_MARKERS):
                    origin_texts[i] = cached
                    continue
                cache_orig.unlink()   # cache xau (CAPTCHA/placeholder cu) -> tai lai
            todo.append((i, ch, cache_orig))

        done_count = [len(origin_texts)]

        def _download_one(arg):
            i, ch, cache_orig = arg
            ch_title, paras = get_chapter_content(ch["url"], novel_title=title, ch_title_hint=ch["title"])
            if not ch_title:
                ch_title = ch["title"]
            is_placeholder = ch_title == "(bi thieu - can xem lai)"
            han = sum(1 for p in paras for c in p if '一' <= c <= '鿿')
            with log_lock:
                done_count[0] += 1
                if is_placeholder:
                    placeholder_count[0] += 1
                tag = "THIEU" if is_placeholder else ("OK " if han >= CHAPTER_MIN_HAN else "LOI")
                _log(f"[{done_count[0]:3d}/{total}] {tag} {ch_title[:45]} ({han} chu Han)")
            if is_placeholder:
                # Redirect -> ghi placeholder vao cache, coi la thanh cong de khong retry
                orig_text = format_chapter_text(ch_title, paras)
                cache_orig.write_text(orig_text, encoding="utf-8")
                return i, orig_text, None
            if han >= CHAPTER_MIN_HAN:
                orig_text = format_chapter_text(ch_title, paras)
                cache_orig.write_text(orig_text, encoding="utf-8")
                return i, orig_text, None
            # Noi dung rong/CAPTCHA -> ghi log, khong cache
            try:
                with open(base_output / "_failed_empty.log", "a", encoding="utf-8") as _fe:
                    _fe.write(f"novel={novel_id} chuong={i} han={han} url={ch['url']} title={ch['title']}\n")
            except Exception:
                pass
            return i, None, ch["url"]

        if todo:
            _log(f"Tai {len(todo)} chuong HTML voi {max(workers,1)} luong...")
            with ThreadPoolExecutor(max_workers=max(workers, 1)) as pool:
                for i, orig_text, fail_url in pool.map(_download_one, todo):
                    if orig_text is not None:
                        origin_texts[i] = orig_text
                    else:
                        origin_failed += 1
                        if fail_url:
                            origin_failed_urls.append(fail_url)

        # ── Pha B: DICH song song (chi khi do_translate) ──
        if do_translate:
            # Chuong can dich = co origin hop le, chua co ban dich cache hop le
            todo_tr = []
            for i, ch in enumerate(chapters, 1):
                if i not in origin_texts:
                    continue
                cache_trans = cache_dir / f"{i:06d}_trans.txt"
                if cache_trans.exists() and cache_trans.stat().st_size > 20:
                    tc = cache_trans.read_text(encoding="utf-8")
                    han = sum(1 for c in tc if '一' <= c <= '鿿')
                    if han / max(len(tc), 1) < 0.05:
                        trans_texts[i] = tc
                        continue
                todo_tr.append(i)

            tr_done = [0]
            ntr = len(todo_tr)

            def _translate_one(i):
                nonlocal trans_failed
                ch_title, paras = parse_orig_cache(origin_texts[i])
                if not paras:
                    return
                vi_title = translate_title(ch_title)
                translated_content, fail_count = translate_text("\n\n".join(paras))
                vi_paras = translated_content.split("\n\n")
                trans_text = format_chapter_text(vi_title, vi_paras, separators=False)
                cache_trans = cache_dir / f"{i:06d}_trans.txt"
                with trans_lock:
                    tr_done[0] += 1
                    if fail_count > 0:
                        trans_failed += fail_count
                        log_failed_chunk(base_output, novel_id, i, fail_count)
                        _log(f"[{tr_done[0]:3d}/{ntr}] {fail_count} doan dich fail (chuong {i}) -> se dich lai", "warn")
                    else:
                        trans_texts[i] = trans_text
                        cache_trans.write_text(trans_text, encoding="utf-8")
                        _log(f"[{tr_done[0]:3d}/{ntr}] Dich xong : {vi_title[:50]}", "ok")

            if todo_tr:
                if TRANSLATE_WORKERS > 1 and ntr > 1:
                    # Warm-up: dich chuong dau TUAN TU de khoi tao session engine truoc khi song song
                    _log(f"Dich {ntr} chuong ({TRANSLATE_WORKERS} luong song song; chuong dau khoi dong tuan tu)...")
                    _translate_one(todo_tr[0])
                    with ThreadPoolExecutor(max_workers=TRANSLATE_WORKERS) as pool:
                        list(pool.map(_translate_one, todo_tr[1:]))
                else:
                    _log(f"Dich {ntr} chuong (tuan tu)...")
                    for i in todo_tr:
                        _translate_one(i)

        # Bo qua vong tuan tu ben duoi
        chapters_iter = []
    else:
        chapters_iter = list(enumerate(chapters, 1))

    _seq_dl_count = 0   # so chuong THUC TAI (khong tinh cache) de rotate IP
    for i, ch in chapters_iter:
        # Cache files
        cache_orig  = cache_dir / f"{i:06d}_orig.txt"
        cache_trans = cache_dir / f"{i:06d}_trans.txt"

        ch_from_cache = False

        # ── Doc tu cache neu co ──
        if cache_orig.exists() and cache_orig.stat().st_size > 20:
            orig_text = cache_orig.read_text(encoding="utf-8")
            # Kiem tra cache goc co bi CAPTCHA khong
            han_in_orig = sum(1 for c in orig_text if '一' <= c <= '鿿')
            if han_in_orig < CHAPTER_MIN_HAN or any(m in orig_text for m in PLACEHOLDER_MARKERS):
                cache_orig.unlink()  # xoa cache xau (CAPTCHA/placeholder), se tai lai
                ch_from_cache = False
            else:
                origin_texts[i] = orig_text
                ch_from_cache = True

            if do_translate:
                if cache_trans.exists() and cache_trans.stat().st_size > 20:
                    trans_content = cache_trans.read_text(encoding="utf-8")
                    # Kiem tra cache co phai ban dich that su khong:
                    # neu van con nhieu chu Han (>5% tong ky tu) -> cache bi loi, dich lai
                    han_count = sum(1 for c in trans_content if '一' <= c <= '鿿')
                    total_chars = max(len(trans_content), 1)
                    is_translated = (han_count / total_chars) < 0.05
                    if is_translated:
                        trans_texts[i] = trans_content
                    else:
                        ch_from_cache = False  # Cache con nhieu chu Han -> dich lai
                else:
                    ch_from_cache = False  # Can dich lai

            if ch_from_cache:
                _log(f"[{i:3d}/{total}] (cache) {ch['title'][:55]}")
                continue

        # ── Tai trang chuong ──
        _log(f"[{i:3d}/{total}] Tai HTML  : {ch['title'][:50]}")
        ch_title, paras = get_chapter_content(ch["url"], novel_title=title, ch_title_hint=ch["title"])
        if not ch_title:
            ch_title = ch["title"]
        is_placeholder = ch_title == "(bi thieu - can xem lai)"
        char_count = sum(len(p) for p in paras)
        han_in_chapter = sum(1 for p in paras for c in p if '一' <= c <= '鿿')
        if not is_placeholder:
            _log(f"[{i:3d}/{total}] Tai xong  : {len(paras)} doan, {char_count} ky tu, {han_in_chapter} chu Han")

        # ── Trang rong hoan toan (CAPTCHA / chuong bi khoa): bo qua, danh dau loi ──
        if not paras:
            _log(f"[{i:3d}/{total}] CANH BAO: trang rong - co the CAPTCHA hoac chuong bi khoa!", "warn")
            try:
                with open(base_output / "_failed_empty.log", "a", encoding="utf-8") as _fe:
                    _fe.write(f"novel={novel_id} chuong={i} han={han_in_chapter} url={ch['url']} title={ch['title']}\n")
            except Exception:
                pass
            origin_failed += 1
            origin_failed_urls.append(ch["url"])
            time.sleep(delay)
            continue

        # ── Chuong bi redirect sang jjwxc.net: luu placeholder, dem, khong dich ──
        if is_placeholder:
            placeholder_count[0] += 1
            orig_text = format_chapter_text(ch_title, paras)
            cache_orig.write_text(orig_text, encoding="utf-8")
            origin_texts[i] = orig_text
            time.sleep(delay)
            continue

        # ── Chuong ngan hop le (thong bao tac gia, v.v.): luu nguyen, khong skip ──
        if han_in_chapter < CHAPTER_MIN_HAN:
            _log(f"[{i:3d}/{total}] Chuong ngan ({han_in_chapter} chu Han) - luu nhu thong bao", "warn")

        orig_text = format_chapter_text(ch_title, paras)
        cache_orig.write_text(orig_text, encoding="utf-8")
        origin_texts[i] = orig_text

        # Truyen rat dai (>30 chuong): rotate IP moi 30 chuong THUC TAI (khong tinh cache)
        if total > 30 and VPN_TYPE != "none":
            _seq_dl_count += 1
            if _seq_dl_count % 30 == 0:
                _log(f"Da tai {_seq_dl_count} chuong -> doi IP...", "warn")
                rotate_ip()

        # ── Dich sang tieng Viet ──
        if do_translate:
            _log(f"[{i:3d}/{total}] Dich      : {ch_title[:45]} ({char_count} ky tu)")
            vi_title = translate_title(ch_title)

            full_content = "\n\n".join(paras)
            translated_content, fail_count = translate_text(full_content)
            vi_paras = translated_content.split("\n\n")

            trans_text = format_chapter_text(vi_title, vi_paras, separators=False)

            if fail_count > 0:
                trans_failed += fail_count
                log_failed_chunk(base_output, novel_id, i, fail_count)
                _log(f"[{i:3d}/{total}] {fail_count} doan dich fail -> se dich lai lan sau", "warn")
            else:
                trans_texts[i] = trans_text
                cache_trans.write_text(trans_text, encoding="utf-8")
                _log(f"[{i:3d}/{total}] Dich xong : {vi_title[:50]}", "ok")

        time.sleep(delay)

    _log(f"Da xu ly {len(origin_texts)}/{total} chuong.")

    # origin HOAN CHINH = du toan bo chuong, khong chuong nao loi (trang rong/CAPTCHA)
    origin_ok = (origin_failed == 0 and len(origin_texts) == total)

    # ── Ghi file ban goc (QUY UOC: chi ghep .txt khi origin DONE) ──
    if origin_ok:
        _log("Ghi file ban goc...")
        cleanup_old_count_files(origin_dir, title, origin_file.name)
        write_full_book(origin_file, novel_info, origin_texts, total)
        size_orig = origin_file.stat().st_size / 1024 / 1024
        _log(f"Ban goc : {origin_file.name}  ({size_orig:.2f} MB)", "ok")
    else:
        # Chua du chuong -> KHONG ghi file goc (tranh de lai ban thieu chuong).
        # Cache tung chuong van giu lai de chay lai chi tai not phan thieu.
        if origin_file.exists():
            origin_file.unlink()
        _log(f"Origin chua du chuong ({len(origin_texts)}/{total}, {origin_failed} loi) "
             f"-> CHUA ghi file goc (cache giu lai de chay lai).", "warn")

    # ── Ghi file ban dich (QUY UOC: chi ghep .txt khi origin done VA dich du chuong) ──
    trans_ok = False
    if do_translate:
        if not origin_ok:
            # Theo y nguoi dung: origin chua xong thi khoan dich -> de retry tu cache sau
            if trans_file.exists():
                trans_file.unlink()
            _log("Origin chua xong -> CHUA ghi ban dich (cho origin done).", "warn")
        elif trans_failed > 0 or len(trans_texts) < total:
            # Xoa file cu neu ton tai (tranh de lai ban thieu chuong / con tieng Trung)
            if trans_file.exists():
                trans_file.unlink()
                _log(f"Xoa file dich cu (con {trans_failed} loi / {len(trans_texts)}/{total} chuong).", "warn")
            else:
                _log(f"Con chuong chua dich xong ({len(trans_texts)}/{total}) -> CHUA ghi file dich.", "warn")
        else:
            _log("Ghi file ban dich...")
            cleanup_old_count_files(trans_dir, title, trans_file.name)
            if ENGINE == "gemini":
                engine_label = f"Gemini ({GEMINI_MODEL})"
            elif _engine_stats:
                total_chunks = sum(_engine_stats.values())
                parts = [f"{eng.capitalize()} {round(n*100/total_chunks)}%" for eng, n in sorted(_engine_stats.items(), key=lambda x: -x[1])]
                engine_label = " / ".join(parts)
            else:
                engine_label = "Caiyun -> Google"
            write_full_book(trans_file, novel_info, trans_texts, total, engine=engine_label, separators=False)
            size_vi = trans_file.stat().st_size / 1024 / 1024

            # Kiem tra chat luong file dich: dem chu Han con sot
            full_trans = trans_file.read_text(encoding="utf-8", errors="ignore")
            han_remaining = sum(1 for c in full_trans if '一' <= c <= '鿿')
            han_ratio = han_remaining / max(len(full_trans), 1)
            if han_ratio >= 0.05:
                residual_info = f"{han_remaining} chu Han con sot ({han_ratio*100:.1f}%)"
                _log(f"Ban dich: {trans_file.name}  ({size_vi:.2f} MB)  [{engine_label}]  [{residual_info}]", "warn")
                # Chat luong kem -> xoa file, khong danh dau done
                trans_file.unlink()
                _log(f"Xoa file dich (chat luong kem, con chu Han sot) -> chay lai se dich not.", "warn")
            else:
                _log(f"Ban dich: {trans_file.name}  ({size_vi:.2f} MB)  [{engine_label}]", "ok")
                trans_ok = True

    # Truyen ngan (<8 chuong): gom 8 truyen moi reset IP 1 lan (tranh doi IP qua thuong)
    if total < 8 and VPN_TYPE != "none":
        global _short_novel_count
        _short_novel_count += 1
        if _short_novel_count >= 8:
            _short_novel_count = 0
            _log("Da tai 8 truyen ngan -> doi IP...", "warn")
            rotate_ip()

    # Tra ve trang thai TACH ROI + ten file (de batch luu vao progress & TTS doc)
    return {
        "origin_ok":           origin_ok,
        "trans_ok":            trans_ok,
        "origin_file":         origin_file.name,
        "trans_file":          trans_file.name,
        "redirect_count":      placeholder_count[0],
        "origin_failed_count": origin_failed,
        "origin_failed_urls":  origin_failed_urls,
        "origin_got":          len(origin_texts),
        "total_chapters":      total,
    }


# ════════════════════════════════════════════════════════════
#  MENU CHON TRUYEN
# ════════════════════════════════════════════════════════════

def show_novel_menu(novels: list) -> list:
    print("\n" + "="*72)
    print(f"  {'STT':>4}  {'Ten truyen':<36} {'Tac gia':<15} {'So chu':>8}")
    print("="*72)
    for i, n in enumerate(novels, 1):
        print(f"  {i:>4}  {n['title'][:35]:<36} {n['author'][:14]:<15} {n['words']:>8}")
    print("="*72)
    raw = safe_input("\nNhap STT muon tai (VD: 1 3 5), 'all' de tai tat ca, Enter de thoat: ").strip()
    if not raw:
        return []
    if raw.lower() == "all":
        return novels
    selected = []
    for part in raw.split():
        try:
            idx = int(part) - 1
            if 0 <= idx < len(novels):
                selected.append(novels[idx])
        except ValueError:
            pass
    return selected


# ════════════════════════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════════════════════════

_TRANSLATE_RETRY_MAX   = 5     # so lan tu dong retry khi con chuong dich loi
_TRANSLATE_RETRY_DELAY = 30.0  # giay cho giua cac lan retry (de rate-limit phuc hoi)


def _download_novel_with_retry(info: dict, out_dir, delay: float, do_translate: bool,
                                workers: int = 1, skip_translated: bool = False):
    """Goi download_novel, tu dong retry phan DICH neu con chuong dich loi.
    Tra ve dict {origin_ok, trans_ok, origin_file, trans_file}.
    Retry chi dich lai tu cache (khong tai lai origin)."""
    res = download_novel(info, out_dir, delay, do_translate, workers=workers,
                         skip_translated=skip_translated)
    if not do_translate:
        return res
    # Da xong dich, hoac origin chua xong (chua dich duoc) -> khong retry dich
    if res["trans_ok"] or not res["origin_ok"]:
        return res

    for attempt in range(1, _TRANSLATE_RETRY_MAX + 1):
        _log(f"Con chuong dich loi -> tu dong retry {attempt}/{_TRANSLATE_RETRY_MAX} "
             f"(cho {_TRANSLATE_RETRY_DELAY:.0f}s)...", "warn")
        time.sleep(_TRANSLATE_RETRY_DELAY)
        res = download_novel(info, out_dir, delay, do_translate, workers=workers,
                             skip_translated=False)  # luon dich lai
        if res["trans_ok"]:
            _log(f"Retry {attempt} thanh cong!", "ok")
            return res

    _log(f"Sau {_TRANSLATE_RETRY_MAX} lan retry van con loi -> bo qua.", "warn")
    return res


def _is_fully_done(nid: str, st: dict, do_translate: bool) -> bool:
    """Truyen coi nhu xong han khi: origin done VA (neu dich) translated done.
    Truyen khong lay dc chuong (no_chapters) luon coi la done (khong retry)."""
    if nid in st.get("origin_no_chapters", {}):
        return True
    return nid in st["origin_done"] and (not do_translate or nid in st["trans_done"])


def _record_result(info: dict, out_dir, delay: float, do_translate: bool,
                   st: dict, log_dir, workers: int, skip_translated: bool, label: str = ""):
    """Tai 1 truyen (info da resolve) roi cap nhat state: origin/translated done & fail rieng."""
    nid = info["novel_id"]
    prefix = f"[{label}] " if label else ""
    try:
        res = _download_novel_with_retry(
            info, out_dir, delay, do_translate, workers=workers, skip_translated=skip_translated)
        origin_ok, trans_ok = res["origin_ok"], res["trans_ok"]

        # ── ORIGIN ── (luu ten file de doi chieu)
        if origin_ok:
            st["origin_done"][nid] = res["origin_file"]
            st["origin_fail"].pop(nid, None)
            _nm_add(info, res["origin_file"], res.get("trans_file", ""), out_dir=out_dir)

            if res.get("no_chapters"):
                note = f"{info['title']} - khong lay dc danh sach chuong - {info['novel_url']}"
                st.setdefault("origin_no_chapters", {})[nid] = note
                _log(f"{prefix}Ghi nhan vao danh sach 'no_chapters' trong _origin_progress.json", "warn")
            elif res.get("redirect_count", 0) > 0:
                n = res["redirect_count"]
                note = f"{info['title']} - {n} chuong bi redirect sang jjwxc.net"
                st.setdefault("origin_redirect", {})[nid] = note
                _log(f"{prefix}Ghi nhan vao danh sach 'redirect' ({n} chuong) trong _origin_progress.json", "warn")
        else:
            st["origin_done"].pop(nid, None)
            n_fail     = res.get("origin_failed_count", 0)
            n_got      = res.get("origin_got", 0)
            n_total    = res.get("total_chapters", 0)
            fail_urls  = res.get("origin_failed_urls", [])
            novel_url  = info.get("novel_url", "")
            parts = [f"origin thieu chuong (trang rong/CAPTCHA): {n_fail} loi, dat {n_got}/{n_total} chuong"]
            if novel_url:
                parts.append(f"novel: {novel_url}")
            if fail_urls:
                shown = fail_urls[:10]
                tail  = f" (+{len(fail_urls)-10} chuong nua)" if len(fail_urls) > 10 else ""
                parts.append(f"chuong loi: {', '.join(shown)}{tail}")
            reason = " | ".join(parts)
            st["origin_fail"][nid] = reason
            print(f"  [!] {prefix}Origin chua du chuong ({n_got}/{n_total}, {n_fail} loi) -> ghi _origin_failed.json")

        # ── TRANSLATED ── (luu ten file -> TTS chi doc file da done)
        if do_translate:
            if trans_ok and res.get("trans_file"):
                st["trans_done"][nid] = res["trans_file"]
                st["trans_fail"].pop(nid, None)
            elif res.get("no_chapters"):
                # Khong co chuong -> khong dich duoc, nhung khong phai loi that su
                st["trans_fail"].pop(nid, None)
            elif not trans_ok:
                st["trans_done"].pop(nid, None)
                reason = "cho origin xong" if not origin_ok else "con doan dich loi / chu Han sot"
                st["trans_fail"][nid] = reason
                print(f"  [!] {prefix}Ban dich chua xong ({reason}) -> ghi _translated_failed.json")

        save_state(out_dir, st)

    except KeyboardInterrupt:
        print("\n[!] Ctrl+C - Da luu tien do. Chay lai se tiep tuc.")
        save_state(out_dir, st)
        sys.exit(0)
    except Exception as e:
        reason = str(e)[:200]
        print(f"  [!] {prefix}Loi -> bo qua: {reason}")
        st["origin_fail"][nid] = reason
        if do_translate:
            st["trans_fail"][nid] = reason
        save_state(out_dir, st)
        append_failed_novel(log_dir, f"{BASE_URL}/novel/{nid}.html", reason)


def _scan_missing_chapters(cache_dir: Path) -> tuple:
    """Quet cache_dir, tra ve (cached_ok, max_index, missing_list).
    missing_list: cac chi so chuong chua co cache hop le (0 Han hoac file nho).
    Khong can HTTP, chi doc file local."""
    existing = {}
    if not cache_dir.exists():
        return 0, 0, []
    for f in cache_dir.glob("*_orig.txt"):
        m = re.match(r"(\d+)_orig\.txt", f.name)
        if not m:
            continue
        idx = int(m.group(1))
        if f.stat().st_size <= 20:
            existing[idx] = False
        else:
            try:
                cached = f.read_text(encoding="utf-8", errors="ignore")
                han = sum(1 for c in cached if '一' <= c <= '鿿')
                # Chuong placeholder (redirect jjwxc) cung co han=0 nhung hop le
                is_placeholder = "(bi thieu - can xem lai)" in cached
                existing[idx] = (han >= CHAPTER_MIN_HAN or is_placeholder)
            except Exception:
                existing[idx] = False
    if not existing:
        return 0, 0, []
    max_i = max(existing.keys())
    cached_ok = sum(1 for v in existing.values() if v)
    missing = sorted(i for i in range(1, max_i + 1) if not existing.get(i, False))
    return cached_ok, max_i, missing


def retry_failed(out_dir, delay: float, do_translate: bool, st: dict, log_dir,
                 workers: int = 1, skip_translated: bool = False):
    """Doc lai file fail (origin + translated), thu lai tung truyen de bo sung.
    Done thi cap nhat progress + xoa khoi fail. (origin da done -> chi dich lai tu cache.)
    Truoc khi retry: quet cache va log so chuong thieu cua tung truyen."""
    no_chapters = set(st.get("origin_no_chapters", {}).keys())

    # origin_fail: luon retry, chi bo qua no_chapters (khong co chuong = binh thuong)
    # KHONG dung _is_fully_done vi neu state khong nhat quan (co trong ca done lan fail)
    # thi van phai retry lai de sua state cho dung.
    ids_origin = {i for i in st["origin_fail"] if i not in no_chapters}

    # trans_fail: chi retry khi chua fully done
    ids_trans: set[str] = set()
    if do_translate:
        ids_trans = {i for i in st["trans_fail"] if not _is_fully_done(i, st, do_translate)}

    if not ids_origin and not ids_trans:
        n_skip_nc = len(set(st["origin_fail"]) & no_chapters)
        if st["origin_fail"] or (do_translate and st["trans_fail"]):
            _log(f"Tat ca truyen fail da duoc xu ly hoac la no_chapters ({n_skip_nc} bo qua) -> khong can retry.", "ok")
        return

    # ── Auto-fix: novels trong CA origin_done VA origin_fail (state khong nhat quan) ──
    # Nguyen nhan: script bi ngat giua 2 lan ghi file state -> _origin_progress.json ghi xong
    # nhung _origin_failed.json chua duoc cap nhat (hoac nguoc lai).
    # Neu file origin van con tren disk -> chi xoa stale fail entry, KHONG can goi HTTP.
    origin_dir = out_dir / "origin"
    autofix: list[str] = []
    for nid in list(ids_origin):
        if nid in st["origin_done"]:
            fname = st["origin_done"].get(nid, "")
            if fname and (origin_dir / fname).exists():
                autofix.append(nid)
    if autofix:
        for nid in autofix:
            st["origin_fail"].pop(nid, None)
            ids_origin.discard(nid)
        save_state(out_dir, st)
        _log(f"[auto-fix] {len(autofix)} truyen co state khong nhat quan (ca done lan fail)"
             f" nhung file origin van con -> xoa stale fail entry khong can HTTP.", "ok")

    ids = sorted(ids_origin | ids_trans)
    if not ids:
        return
    _log(f"── Retry {len(ids)} truyen fail truoc khi tai moi"
         f" (origin: {len(ids_origin)}, trans: {len(ids_trans)}) ──")

    # Quet cache local truoc: hien thi chuong thieu ma khong can HTTP
    for nid in ids:
        cached_ok, max_i, missing = _scan_missing_chapters(out_dir / ".cache" / nid)
        if max_i > 0:
            miss_str = str(missing[:30]) + ("..." if len(missing) > 30 else "")
            _log(f"  ID {nid}: {cached_ok}/{max_i} chuong da cache | chuong thieu: {miss_str}", "warn")
        else:
            reason = st["origin_fail"].get(nid, st.get("trans_fail", {}).get(nid, ""))
            _log(f"  ID {nid}: chua co cache nao ({reason[:60]})", "warn")

    for nid in ids:
        try:
            info = get_novel_info(f"{BASE_URL}/novel/{nid}.html")
        except Exception:
            info = None
        if not info:
            _log(f"[retry] Khong lay duoc thong tin truyen {nid} -> de lai sau.", "warn")
            continue
        print(f"\n[retry] {info['title']}")
        _record_result(info, out_dir, delay, do_translate, st, log_dir,
                       workers, skip_translated=skip_translated, label="retry")
        time.sleep(delay)


def _process_stubs(stubs: list, out_dir, delay: float, do_translate: bool,
                   st: dict, log_dir, label: str = "", workers: int = 1,
                   novel_delay: float = 0.0, skip_translated: bool = False):
    """Xu ly danh sach novel stubs MOI: download + dich + luu state.
    Sau moi 5 truyen MOI -> kiem tra lai file fail de bo sung roi moi lay tiep."""
    for stub in stubs:
        m = re.search(r"/novel/(\d+)", stub["novel_url"])
        nid = m.group(1) if m else stub["novel_url"]
        prefix = f"[{label}] " if label else ""

        if _is_fully_done(nid, st, do_translate):
            print(f"{prefix}(da xong) {stub['title'][:40]} - bo qua")
            continue

        print(f"\n{prefix}{stub['title']}")
        try:
            info = get_novel_info(stub["novel_url"])
        except KeyboardInterrupt:
            save_state(out_dir, st)
            print("\n[!] Ctrl+C - Da luu tien do. Chay lai se tiep tuc.")
            sys.exit(0)
        except Exception:
            info = None
        if not info:
            print(f"  [!] {prefix}Khong lay duoc thong tin -> ghi fail, bo qua")
            st["origin_fail"][nid] = "khong lay duoc thong tin truyen"
            save_state(out_dir, st)
            continue
        if not info.get("author") and stub.get("author"):
            info["author"] = stub["author"]

        # Kiem tra trung lap: URL (instant) + fingerprint chuong 1 neu can
        _dup_type_b, _dup_be, _dup_br = _nm_check_novel(info)
        if _dup_type_b == "url":
            print(f"  [*] Da co trong registry: {_dup_br} -> Tai lai de cap nhat.")

        _record_result(info, out_dir, delay, do_translate, st, log_dir,
                       workers, skip_translated, label=label)

        st["_counter"] += 1

        time.sleep(novel_delay if novel_delay > 0 else delay)


def main():
    global ENGINE, GEMINI_API_KEY, GEMINI_MODEL, TRANSLATE_WORKERS, VPN_TYPE

    parser = argparse.ArgumentParser(
        description="AliceSW Downloader - Tai truyen + Dich sang tieng Viet",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Vi du su dung:\n"
            "  # Tai 1 truyen (co dich):\n"
            "  py alicesw_downloader.py https://www.alicesw.com/novel/32514.html\n\n"
            "  # Tai 1 truyen, chi luu ban goc (khong dich):\n"
            "  py alicesw_downloader.py https://www.alicesw.com/novel/32514.html --no-translate\n\n"
            "  # Duyet danh sach, chon truyen:\n"
            "  py alicesw_downloader.py https://www.alicesw.com/all/id/65/order/word+desc.html\n\n"
            "  # Tai tat ca, gioi han 2 trang, luu vao D:/truyen:\n"
            "  py alicesw_downloader.py URL --all --max-pages 2 --output D:/truyen\n\n"
            "Thu muc ket qua:\n"
            "  <output>/origin/      -> ban goc tieng Trung\n"
            "  <output>/translated/  -> ban dich tieng Viet\n"
            "  <output>/.cache/      -> cache tung chuong (co the resume)\n"
        ),
    )
    parser.add_argument(
        "url", nargs="?",
        default="",
        help="URL truyen hoac trang listing (bo trong de duoc hoi nhap)",
    )
    parser.add_argument(
        "--all", dest="download_all", action="store_true",
        help="Tai tat ca truyen trong listing (khong hoi)",
    )
    parser.add_argument(
        "-y", "--yes", dest="yes", action="store_true",
        help="Tu dong xac nhan, khong hoi lai (dung trong script)",
    )
    parser.add_argument(
        "--no-translate", dest="no_translate", action="store_true",
        help="Chi luu ban goc, khong dich sang tieng Viet",
    )
    parser.add_argument(
        "--workers", type=int, default=1,
        help="So luong TAI HTML chuong song song (mac dinh 1 = tuan tu). Nen <=3 de tranh "
             "server nghen (10 luong de gay loi). Co tac dung ca khi dich (tai HTML truoc, dich sau).",
    )
    parser.add_argument(
        "--translate-workers", dest="translate_workers", type=int, default=1,
        help="So luong DICH song song (mac dinh 1 = tuan tu). >1 -> dich nhieu chuong cung luc, "
             "nhanh hon nhieu. Moi chunk tu xoay Caiyun -> Google. "
             "Nen 3-4; cao qua de bi 429.",
    )
    parser.add_argument(
        "--max-pages", type=int, default=0,
        help="Gioi han so trang listing (0 = tat ca trang)",
    )
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Gioi han so TRUYEN se tai tu listing (0 = khong gioi han). Dung de test.",
    )
    parser.add_argument(
        "--delay", type=float, default=DELAY,
        help=f"Delay giua cac CHUONG (mac dinh: {DELAY}s)",
    )
    parser.add_argument(
        "--novel-delay", type=float, default=0.0, dest="novel_delay",
        help="Delay giua cac TRUYEN khi batch (mac dinh: bang --delay). VD: --novel-delay 1",
    )
    parser.add_argument(
        "--skip-translated", dest="skip_translated", action="store_true",
        help="Bo qua truyen da co file ban dich (.txt) trong translated/ (du khong co trong progress).",
    )
    parser.add_argument(
        "--reverse", dest="reverse", action="store_true",
        help="Tai nguoc: bat dau tu trang CUOI cung ve trang 1 (uu tien truyen cu nhat / moi nhat tuy thu tu listing).",
    )
    parser.add_argument(
        "--cookie", type=str, default="",
        help="Cookie tu browser (copy tu F12->Network->Request Headers->Cookie). Giup vuot CAPTCHA.",
    )
    parser.add_argument(
        "--cookies-file", type=str, default="",
        help="File cookies.txt dinh dang Netscape (xuat tu extension Get cookies.txt LOCALLY).",
    )
    parser.add_argument(
        "--output", type=str, default="downloaded",
        help="Thu muc goc de luu ket qua (mac dinh: downloaded/)",
    )
    parser.add_argument(
        "--engine", choices=["free", "gemini", "caiyun", "google"], default="free",
        help="Engine dich: free (Caiyun->Google tu dong xoay) | gemini (chat luong cao nhat) | caiyun (chi dung Caiyun) | google (chi dung Google)",
    )
    parser.add_argument(
        "--gemini-key", type=str, default="",
        help="Gemini API key (hoac dat bien moi truong GEMINI_API_KEY). Lay free tai aistudio.google.com",
    )
    parser.add_argument(
        "--gemini-model", type=str, default=GEMINI_MODEL,
        help=f"Model Gemini (mac dinh: {GEMINI_MODEL}; doi 'gemini-2.5-pro' neu muon hay hon)",
    )
    parser.add_argument(
        "--vpn", choices=["protonvpn", "warp", "none", "auto"], default="auto",
        help="Chon loai VPN de tu dong doi IP khi bi block (protonvpn | warp | none | auto, mac dinh: auto)",
    )

    args = parser.parse_args()

    # ── Cau hinh engine dich (gan vao bien module-level) ──
    ENGINE = args.engine
    GEMINI_MODEL = args.gemini_model
    GEMINI_API_KEY = args.gemini_key or os.environ.get("GEMINI_API_KEY", "")
    TRANSLATE_WORKERS = max(1, args.translate_workers)

    # Determine auto VPN type
    is_warp_available = os.path.exists(r"C:\Program Files\Cloudflare\Cloudflare WARP\warp-cli.exe")
    is_proton_available = bool(PROTON_CLI or PROTON_SERVICE)
    
    if args.vpn == "auto":
        if is_proton_available:
            VPN_TYPE = "protonvpn"
        elif is_warp_available:
            VPN_TYPE = "warp"
        else:
            VPN_TYPE = "none"
    else:
        VPN_TYPE = args.vpn
    
    if VPN_TYPE != "none":
        _log(f"Da thiet lap tu dong xoay IP bang VPN: {VPN_TYPE}", "ok")

    # ── Ap cookie vao session ──
    # Tu dong dung cookies.txt neu co canh script (khong can --cookies-file)
    _cookies_file = args.cookies_file or ""
    if not _cookies_file:
        _auto = Path(__file__).parent / "cookies.txt"
        if _auto.exists():
            _cookies_file = str(_auto)

    if _cookies_file:
        _load_cookies_file(_cookies_file)
    elif args.cookie:
        session.headers.update({"Cookie": args.cookie})
        print(f"[*] Da ap cookie vao session ({len(args.cookie)} ky tu)")

    do_translate = not args.no_translate

    if do_translate and ENGINE == "gemini":
        if not GEMINI_API_KEY:
            print("[!] Engine gemini can API key. Dung --gemini-key=XXX hoac:")
            print("    set GEMINI_API_KEY=XXX   (PowerShell: $env:GEMINI_API_KEY='XXX')")
            print("    Lay key free tai: https://aistudio.google.com/apikey")
            sys.exit(1)
    if do_translate and ENGINE == "free" and not TRANSLATE_AVAILABLE:
        print("[!] Khong co translators. Chay: py -m pip install translators")
        print("    Hoac them --no-translate de chi luu ban goc.")
        sys.exit(1)

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print("  AliceSW Downloader")
    print(f"  Luu tai : {out_dir.resolve()}")
    print(f"    origin/     -> ban goc tieng Trung")
    if do_translate:
        print(f"    translated/ -> ban dich tieng Viet")
        if ENGINE == "gemini":
            print(f"  Engine  : Gemini ({GEMINI_MODEL}) + fallback free")
        else:
            print(f"  Engine  : Caiyun -> Google (tu dong xoay)")
    print(f"  Delay   : {args.delay}s")
    print(f"  Tai HTML: {args.workers} luong" + (" song song" if args.workers > 1 else " (tuan tu)"))
    if do_translate:
        if TRANSLATE_WORKERS > 1:
            print(f"  Dich    : {TRANSLATE_WORKERS} luong song song (Caiyun->Google moi chunk)")
        else:
            print(f"  Dich    : 1 luong (tuan tu) - dung --translate-workers 4 de nhanh hon")
    print(f"{'='*60}")

    url = args.url.strip().strip("'\" ")

    # Neu khong co URL, hoi nguoi dung nhap
    if not url:
        print()
        url = safe_input("Nhap URL truyen hoac trang listing:\n> ").strip().strip("'\" ")
        if not url:
            print("Khong co URL. Thoat.")
            sys.exit(0)

    # Xu ly link chuong /book/<id>/xxx.html -> chuyen ve /novel/<id>.html
    m_book = re.search(r"/book/(\d+)/", url)
    if m_book:
        novel_id = m_book.group(1)
        url = f"{BASE_URL}/novel/{novel_id}.html"
        print(f"[*] Phat hien link chuong -> chuyen ve trang truyen: {url}")

    # ── Tai 1 truyen cu the ──────────────────────────────────
    if "/novel/" in url:
        # Kiem tra va tai lai truyen fail truoc (giong listing mode)
        st = load_state(out_dir)
        retry_failed(out_dir, args.delay, do_translate, st, out_dir,
                     workers=args.workers, skip_translated=args.skip_translated)

        print("[*] Phat hien URL truyen, dang lay thong tin...")
        info = get_novel_info(url)
        if not info:
            print("[!] Khong lay duoc thong tin truyen.")
            sys.exit(1)
        print(f"    Ten    : {info['title']}")
        print(f"    Tac gia: {info['author']}")
        print(f"    ID     : {info['novel_id']}")
        # Kiem tra trung lap Tang 1: URL (0 request)
        _dup_type, _dup_e, _dup_r = _nm_check_novel(info)
        if _dup_type == "url":
            print(f"\n[*] Da co trong registry: {_dup_r} -> Tai lai de cap nhat chuong moi.")
        if not args.yes:
            ans = safe_input("Tai truyen nay? (Y/n): ").strip().lower()
            if ans in ("n", "no"):
                print("Da huy.")
                sys.exit(0)
        _record_result(info, out_dir, args.delay, do_translate, st, out_dir,
                       workers=args.workers, skip_translated=args.skip_translated)

    # ── Trang listing ────────────────────────────────────────
    else:
        st = load_state(out_dir)

        # Luc START: kiem tra file fail (origin + translated) de bo sung truoc
        retry_failed(out_dir, args.delay, do_translate, st, out_dir,
                     workers=args.workers, skip_translated=args.skip_translated)

        if not args.download_all:
            # Mode chon tay: load het roi hien menu
            novels = get_all_pages_from_listing(url, max_pages=args.max_pages)
            if not novels:
                print("[!] Khong tim thay truyen nao.")
                sys.exit(1)
            selected = show_novel_menu(novels)
            if not selected:
                print("Khong chon truyen nao. Thoat.")
                sys.exit(0)
            if args.limit > 0:
                selected = selected[:args.limit]
            _process_stubs(selected, out_dir, args.delay, do_translate, st, out_dir,
                           workers=args.workers, novel_delay=args.novel_delay,
                           skip_translated=args.skip_translated)
        else:
            # Mode --all: load tung trang, xu ly truyện trên trang do ngay, roi moi sang trang tiep
            novel_counter = 0
            limit_hit = False
            for page_num, total_pages, page_novels in iter_listing_pages(url, max_pages=args.max_pages, reverse=args.reverse):
                print(f"\n── Trang {page_num}/{total_pages} ({len(page_novels)} truyen) ──")
                for stub in page_novels:
                    if args.limit > 0 and novel_counter >= args.limit:
                        limit_hit = True
                        break
                    novel_counter += 1
                    _process_stubs([stub], out_dir, args.delay, do_translate, st, out_dir,
                                   label=f"#{novel_counter}", workers=args.workers, novel_delay=args.novel_delay,
                                   skip_translated=args.skip_translated)
                if limit_hit:
                    break

        print(f"\n[*] Tong ket:")
        print(f"    Origin     done: {len(st['origin_done']):4d}  | fail: {len(st['origin_fail'])}")
        if do_translate:
            print(f"    Translated done: {len(st['trans_done']):4d}  | fail: {len(st['trans_fail'])}")
        if st.get("origin_no_chapters"):
            print(f"    Khong lay dc chuong (xem lai): {len(st['origin_no_chapters'])}")
        if st.get("origin_redirect"):
            print(f"    Co chuong redirect -> jjwxc.net: {len(st['origin_redirect'])}")
        if st["origin_fail"] or st["trans_fail"]:
            print(f"    Xem: _origin_failed.json / _translated_failed.json")
        if st.get("origin_no_chapters") or st.get("origin_redirect"):
            print(f"    Xem chi tiet: _origin_progress.json (muc no_chapters / redirect)")

    print("\n[OK] Hoan thanh!")


if __name__ == "__main__":
    main()
