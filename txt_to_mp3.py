#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TXT -> MP3 Watcher (gTTS)
=========================
Tu dong quet 1 thu muc, phat hien file .txt MOI hoac DA SUA -> dung gTTS
tao file .mp3 (tieng Viet) luu vao thu muc con /mp3 cung ten file.

Dac diem:
  - Quet lai moi 5 giay (mac dinh).
  - Nho file nao da xong (trang thai luu _tts_progress.json) -> khong lam lai.
  - File .txt bi sua (doi size/mtime) -> tu dong tao lai mp3.
  - Resume tung doan: moi chunk luu cache rieng, gian doan giua chung van tiep tuc duoc.
  - Chong loi 429 (Too Many Requests) cua Google: goi DON LUONG, delay hop ly
    giua cac chunk + backoff tang dan khi bi chan.
  - Ghep cac chunk mp3 lai thanh 1 file (gTTS ghep bang noi byte mp3).

Cach dung:
  py -u txt_to_mp3.py                       # quet downloaded/translated, mp3 -> .../translated/mp3
  py -u txt_to_mp3.py --dir D:/truyen/vi     # quet thu muc khac
  py -u txt_to_mp3.py --once                 # chay 1 lan roi thoat (khong quet lien tuc)
  py -u txt_to_mp3.py --interval 10          # quet 10s/lan
  py -u txt_to_mp3.py --max-size 1.5         # chi tao mp3 cho file .txt < 1.5 MB
"""

import os
os.environ.setdefault("PYTHONUNBUFFERED", "1")
import re
import sys
import json
import time
import shutil
import argparse
import subprocess
import threading
import urllib.request
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import _vpn_lock

FFMPEG = shutil.which("ffmpeg")  # None neu may chua co ffmpeg -> bo qua hau ky

# Tim ProtonVPN: uu tien CLI (cross-platform), fallback Windows service (v4+ GUI)
_PROTON_SVC = "ProtonVPN Service"   # Windows service name cua ProtonVPN v4

def _proton_service_running() -> bool:
    try:
        r = subprocess.run(["sc", "query", _PROTON_SVC],
                           capture_output=True, timeout=5)
        return b"RUNNING" in r.stdout
    except Exception:
        return False

_PROTON_CLI_CANDIDATES = [
    shutil.which("protonvpn-cli"),
    shutil.which("protonvpn"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "protonvpn-cli", "protonvpn-cli.exe"),
]
PROTON_CLI = next((p for p in _PROTON_CLI_CANDIDATES if p and Path(p).exists()), None)
PROTON_SERVICE = _PROTON_SVC if _proton_service_running() else None
USE_PROTON = bool(PROTON_CLI or PROTON_SERVICE)

def _find_hss_service_name() -> str:
    """Lay ten service Hotspot Shield (vi du: hshld_12.16.1). Tra ve '' neu khong thay."""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-Service | Where-Object {$_.DisplayName -like '*Hotspot Shield Service*'} | Select-Object -First 1 -ExpandProperty Name"],
            capture_output=True, text=True, timeout=8, encoding="utf-8", errors="replace"
        )
        return r.stdout.strip()
    except Exception:
        return ""

HSS_SERVICE = _find_hss_service_name() or None   # vd: "hshld_12.16.1"

VPN_TYPE = "none"  # Dat tu command line: protonvpn | warp | hotspot | none

# ── Ep console Windows xuat UTF-8 (tranh crash ky tu tieng Viet) ──
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ── Vo hieu hoa QuickEdit Mode tren Windows console (tranh treo/pause khi click vao cua so) ──
def disable_quick_edit():
    if os.name == "nt":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            # STD_INPUT_HANDLE = -10
            hStdin = kernel32.GetStdHandle(-10)
            mode = ctypes.c_ulong()
            if kernel32.GetConsoleMode(hStdin, ctypes.byref(mode)):
                # ENABLE_QUICK_EDIT_MODE = 0x0040, ENABLE_EXTENDED_FLAGS = 0x0080
                new_mode = (mode.value & ~0x0040) | 0x0080
                kernel32.SetConsoleMode(hStdin, new_mode)
        except Exception:
            pass

disable_quick_edit()

try:
    from gtts import gTTS
    from gtts.tts import gTTSError
except ImportError:
    print("[!] Chua cai gTTS. Chay: py -m pip install gTTS")
    sys.exit(1)


# ════════════════════════════════════════════════════════════
#  CAU HINH
# ════════════════════════════════════════════════════════════
LANG            = "vi"     # ngon ngu doc (tieng Viet)
SCAN_INTERVAL   = 3.0      # giay: bao lau quet 1 lan
CHUNK_MAX_CHARS = 480      # do dai toi da moi chunk gui gTTS (cat tai dau cau)
CHUNK_DELAY     = 0.8      # giay nghi giua cac chunk (don luong, tranh 429) - 0.8s la muc can bang
FILE_STABLE_SEC = 3.0      # file phai "yen" >= 3s (khong con dang ghi) moi xu ly

# Hau ky bang ffmpeg (chay 1 lan tren file da ghep) - KHONG anh huong toc do tao,
# chi lam audio ngan hon (nghe nhanh) + file nhe hon.
SPEED   = 1.15     # he so toc do doc (1.0 = giu nguyen; 1.15 = nhanh 15%). gTTS khong tu chinh -> dung ffmpeg atempo.
BITRATE = "32k"   # bitrate mp3 dau ra ("" = giu nguyen ~64k cua gTTS). 32k -> file nhe hon ~nua.

# Backoff khi bi 429 / loi mang
RETRY_MAX       = 8        # so lan thu lai toi da moi chunk
BACKOFF_BASE    = 1.0      # nghi ngan 1s o lan dau
BACKOFF_MAX     = 2.0      # cho toi da 2s

# ── Delay thich nghi: tu gian ra khi 429, tu thu lai khi on ────
# Sau moi chunk dinh 429 -> cong them ADAPT_STEP vao delay; chay tron tru
# lien tiep -> tru dan ve 0. Giup tu dong tim toc do an toan cho IP cua may.
_adaptive_extra  = 0.0
_adaptive_lock   = threading.Lock()   # bao ve _adaptive_extra va _ok_streak
_ok_streak       = 0                  # dem so chunk OK lien tiep (thread-safe qua _adaptive_lock)
_proton_rotate_lock = threading.Lock()  # chi 1 thread rotate IP tai 1 thoi diem
_ip_rotated_this_file = threading.Event()  # set khi rotate IP thanh cong trong 1 file (xoa truoc moi file)
_post_rotate_event = threading.Event()   # clear khi vua doi IP, set lai sau khi on dinh
_post_rotate_event.set()               # mac dinh: "san sang" (khong dang doi)
ADAPT_STEP      = 0.2      # moi lan 429 cong them 0.2s vao delay giua chunk
ADAPT_MAX       = 0.2      # delay phu toi da 0.2s (ProtonVPN xoay IP thay cho backoff dai)
ADAPT_DECAY     = 0.05     # moi chunk thanh cong tru bot 0.05s
ADAPT_RECOVER   = 5        # can 5 chunk lien tiep OK moi bat dau tru
WORKERS         = 4        # so thread song song tai chunk (tang x4 toc do)
MAX_WORKERS     = 64       # tran toi da (tang khi file thanh cong)
MIN_WORKERS     = 15       # san toi thieu = gia tri khoi dong mac dinh (--workers 15)
AUTO_SCALE      = True     # tu dong tang/giam WORKERS theo ket qua (tat bang --no-auto)
MAX_TXT_MB      = 0.0      # gioi han kich thuoc file .txt dau vao MB (0 = khong gioi han)


def clean_title(name: str) -> str:
    """
    Chuan hoa ten cho ten file mp3:
      - Bo HET cum [ ... ] (ca noi dung ben trong - day la cac tag the loai dau ten truyen).
      - Voi 【 】: CHI bo dau ngoac, GIU LAI noi dung ben trong.
      - Gop khoang trang du, cat khoang trang dau/cuoi.
      - Chi viet HOA chu cai dau tien, cac chu con lai viet thuong (sentence case).
    """
    name = re.sub(r"\[[^\]]*\]", " ", name)   # bo [tag] ke ca noi dung
    name = re.sub(r"[【】\[\]]", " ", name)     # bo dau 【 】 va [ ] le con sot (giu noi dung)
    name = re.sub(r"\s+", " ", name).strip()
    if name:
        name = name[0].upper() + name[1:].lower()
    return name


def output_stem(stem: str) -> str:
    """
    Ten file mp3 dau ra (khong duoi) da chuan hoa. Giu nguyen phan duoi
    "+N Chuong" do tool tai truyen tu them, chi chuan hoa phan ten truyen.
    """
    m = re.match(r"^(.*?)(\+\d+\s*Chuong.*)$", stem)
    if m:
        return clean_title(m.group(1)) + m.group(2)
    return clean_title(stem)


def note_429():
    """Bi 429 -> gian delay giua chunk, reset streak (thread-safe)."""
    global _adaptive_extra, _ok_streak
    with _adaptive_lock:
        _adaptive_extra = min(_adaptive_extra + ADAPT_STEP, ADAPT_MAX)
        _ok_streak = 0


def note_ok():
    """Chunk OK -> tang streak, sau ADAPT_RECOVER lan lien tiep thi giam delay dan (thread-safe)."""
    global _adaptive_extra, _ok_streak
    with _adaptive_lock:
        _ok_streak += 1
        if _ok_streak >= ADAPT_RECOVER and _adaptive_extra > 0:
            _adaptive_extra = max(_adaptive_extra - ADAPT_DECAY, 0.0)


# ════════════════════════════════════════════════════════════
#  LOC NOI DUNG TXT
# ════════════════════════════════════════════════════════════
_SEP_RE = re.compile(r"^[\s─—–=_*#\.·•\-]+$")  # dong chi gom ky tu ke/phan cach

def clean_text_for_tts(raw: str) -> str:
    """
    Bo header metadata (cac dong thut le dau file: ten goc, Tac gia, Nguon...),
    bo cac dong ke phan cach, gop bot dong trong. Tra ve van ban sach de doc.
    """
    lines = raw.splitlines()

    # 1) Bo khoi header dau file:
    # Neu file bat dau bang mot dong ke phan cach (vd: ===...), ta tim dong ke tiep theo
    # va bo qua toan bo phan giua chung.
    start = 0
    if lines and _SEP_RE.match(lines[0].strip()):
        # Tim dong ke tiep theo de bo qua header
        for i in range(1, len(lines)):
            if _SEP_RE.match(lines[i].strip()):
                start = i + 1
                break
    else:
        # Fallback: cac dong thut 2+ space hoac trong, cho toi dong noi dung dau tien (khong thut le).
        for i, ln in enumerate(lines):
            if ln.strip() == "" or ln.startswith("  "):
                start = i + 1
                continue
            break
    body = lines[start:] if start < len(lines) else lines

    # 2) Bo dong ke phan cach + gop dong trong lien tiep
    out, blank = [], False
    for ln in body:
        s = ln.strip()
        if not s:
            if not blank and out:        # giu toi da 1 dong trong
                out.append("")
            blank = True
            continue
        if _SEP_RE.match(s):             # dong ke "────" / "====" -> bo
            continue
        out.append(s)
        blank = False

    return "\n".join(out).strip()


def split_into_chunks(text: str, max_chars: int = None) -> list:
    """
    Chia van ban thanh cac chunk <= max_chars, uu tien cat tai ranh gioi cau/dong
    de gTTS doc tu nhien. Don luong se doc tung chunk mot.
    """
    if max_chars is None:
        max_chars = CHUNK_MAX_CHARS   # doc global luc goi (cho phep --chunk-chars override)
    chunks, cur = [], ""
    # Tach theo dong truoc, roi theo dau cau neu dong qua dai
    for para in text.split("\n"):
        para = para.strip()
        if not para:
            continue
        # Neu doan qua dai, cat tiep theo dau cau
        pieces = _split_sentences(para, max_chars) if len(para) > max_chars else [para]
        for piece in pieces:
            if cur and len(cur) + len(piece) + 1 > max_chars:
                chunks.append(cur.strip())
                cur = piece
            else:
                cur = f"{cur} {piece}".strip() if cur else piece
    if cur.strip():
        chunks.append(cur.strip())
    return chunks


def _split_sentences(para: str, max_chars: int) -> list:
    """Cat 1 doan dai theo dau cau tieng Viet (. ! ? ; : , ...)."""
    parts, buf = [], ""
    tokens = re.split(r"([.!?;:,…])", para)
    i = 0
    while i < len(tokens):
        seg = tokens[i] + (tokens[i + 1] if i + 1 < len(tokens) else "")
        if len(buf) + len(seg) > max_chars and buf:
            parts.append(buf.strip())
            buf = seg
        else:
            buf += seg
        i += 2
    if buf.strip():
        parts.append(buf.strip())
    # Con phan tu nao van qua dai -> cat cung theo do dai
    final = []
    for p in parts:
        if len(p) > max_chars:
            for j in range(0, len(p), max_chars):
                final.append(p[j:j + max_chars])
        else:
            final.append(p)
    return final or [para]


# ════════════════════════════════════════════════════════════
#  GOI gTTS (don luong + chong 429)
# ════════════════════════════════════════════════════════════
def is_429(err: Exception) -> bool:
    msg = str(err).lower()
    return "429" in msg or "too many requests" in msg

def is_conn_error(err: Exception) -> bool:
    msg = str(err).lower()
    return "failed to connect" in msg or "connection" in msg or "network" in msg


def _proton_cli_cmd(*args, timeout: float = 30.0):
    """Goi protonvpn-cli (neu co), nuot output."""
    try:
        subprocess.run([PROTON_CLI, *args], capture_output=True, timeout=timeout)
    except Exception:
        pass


def _proton_svc_cmd(action: str, timeout: float = 20.0):
    """Goi sc stop/start ProtonVPN Service (Windows GUI edition)."""
    try:
        subprocess.run(["sc", action, _PROTON_SVC],
                       capture_output=True, timeout=timeout)
    except Exception:
        pass


def _get_ip() -> str:
    """Lay IP public hien tai qua cloudflare trace."""
    try:
        with urllib.request.urlopen(
                "https://www.cloudflare.com/cdn-cgi/trace", timeout=5) as r:
            body = r.read().decode("utf-8", "replace")
        return next((ln[3:] for ln in body.splitlines() if ln.startswith("ip=")), "")
    except Exception:
        return ""


def reset_tts_sessions():
    """Dong het session requests dang mo de buoc gTTS dung TCP connection moi voi IP moi."""
    try:
        import gc
        import requests as _req
        closed = 0
        for obj in gc.get_objects():
            if isinstance(obj, _req.Session):
                try:
                    obj.close()
                    closed += 1
                except Exception:
                    pass
        print(f"  [VPN] Da close {closed} session(s), TCP connection moi se dung IP vua doi.")
    except Exception as e:
        print(f"  [VPN] Khong the reset sessions: {e}")


def proton_rotate() -> bool:
    """
    Doi IP: chi 1 thread/process duoc rotate tai mot thoi diem.
    - _proton_rotate_lock: in-process lock (tranh nhieu thread cung rotate)
    - _vpn_lock: cross-process file lock (tranh 2 script cung chay cung rotate)
    Thread/process khac se cho xong roi retry luon, khong rotate them.
    """
    if not USE_PROTON:
        return False

    # In-process: neu thread khac dang rotate thi cho roi retry
    acquired = _proton_rotate_lock.acquire(blocking=False)
    if not acquired:
        got = _proton_rotate_lock.acquire(timeout=45)  # ProtonVPN co the mat den 30s
        if got:
            _proton_rotate_lock.release()
        return bool(_get_ip())

    # Cross-process: giu file lock truoc khi cham VPN
    if not _vpn_lock.acquire(timeout=15):
        _proton_rotate_lock.release()
        return bool(_get_ip())  # process kia vua doi xong, dung IP moi luon

    try:
        gap = _vpn_lock.elapsed_since_last()
        if gap is not None and gap < 45:
            return False   # vua doi IP < 45s truoc -> de backoff, KHONG toggle lai (giong downloader)
        if gap is not None:
            print(f"  [VPN] Lan cuoi doi IP: {gap:.0f}s truoc ({gap/60:.1f} phut)")
        old_ip = _get_ip()
        if PROTON_CLI:
            _proton_cli_cmd("disconnect")
            time.sleep(2)
            _proton_cli_cmd("connect", "--random")
        else:
            _proton_svc_cmd("stop")
            time.sleep(3)
            _proton_svc_cmd("start")

        for _ in range(30):
            time.sleep(1)
            new_ip = _get_ip()
            if new_ip:
                tag = "(IP moi)" if (old_ip and new_ip != old_ip) else "(IP nhu cu)"
                _vpn_lock.record_rotation()
                _ip_rotated_this_file.set()
                print(f"  [ProtonVPN] {new_ip} {tag}")
                reset_tts_sessions()
                # Pause tat ca worker 2s de IP moi khong bi spam ngay lap tuc
                _post_rotate_event.clear()
                threading.Timer(2.0, _post_rotate_event.set).start()
                return True
        print("  [ProtonVPN] khong lay duoc IP sau khi doi (se backoff thuong)")
        return False
    finally:
        _vpn_lock.release()
        _proton_rotate_lock.release()


def rotate_warp_ip() -> bool:
    """Doi IP qua Cloudflare WARP (cross-process lock, an toan khi chay song song)."""
    warp_cli = r"C:\Program Files\Cloudflare\Cloudflare WARP\warp-cli.exe"
    if not os.path.exists(warp_cli):
        print("  [WARP] Khong tim thay Cloudflare WARP CLI (warp-cli.exe), bo qua doi IP.")
        return False

    # In-process lock
    acquired = _proton_rotate_lock.acquire(blocking=False)
    if not acquired:
        got = _proton_rotate_lock.acquire(timeout=30)
        if got:
            _proton_rotate_lock.release()
        return bool(_get_ip())

    # Cross-process lock
    if not _vpn_lock.acquire(timeout=15):
        _proton_rotate_lock.release()
        return bool(_get_ip())

    try:
        gap = _vpn_lock.elapsed_since_last()
        if gap is not None and gap < 30:
            return False   # vua doi IP < 30s truoc -> de backoff, KHONG toggle lai (giong downloader)
        if gap is not None:
            print(f"  [VPN] Lan cuoi doi IP: {gap:.0f}s truoc ({gap/60:.1f} phut)")
        old_ip = _get_ip()

        subprocess.run([warp_cli, "disconnect"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)
        subprocess.run([warp_cli, "connect"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        for _ in range(15):
            time.sleep(1)
            new_ip = _get_ip()
            if new_ip:
                tag = "(IP moi)" if (old_ip and new_ip != old_ip) else "(IP nhu cu)"
                _vpn_lock.record_rotation()
                _ip_rotated_this_file.set()
                print(f"  [Cloudflare WARP] {new_ip} {tag}")
                reset_tts_sessions()
                # Pause tat ca worker 2s de IP moi khong bi spam ngay lap tuc
                _post_rotate_event.clear()
                threading.Timer(2.0, _post_rotate_event.set).start()
                return True
        print("  [Cloudflare WARP] khong lay duoc IP sau khi doi (se backoff thuong)")
        return False
    finally:
        _vpn_lock.release()
        _proton_rotate_lock.release()


def rotate_hotspot_ip() -> bool:
    """Doi IP qua Hotspot Shield: stop/start service de lay IP moi tu carrier."""
    if not HSS_SERVICE:
        print("  [HotspotShield] Khong tim thay service Hotspot Shield tren may.")
        return False

    acquired = _proton_rotate_lock.acquire(blocking=False)
    if not acquired:
        got = _proton_rotate_lock.acquire(timeout=45)
        if got:
            _proton_rotate_lock.release()
        return bool(_get_ip())

    if not _vpn_lock.acquire(timeout=15):
        _proton_rotate_lock.release()
        return bool(_get_ip())

    try:
        gap = _vpn_lock.elapsed_since_last()
        if gap is not None and gap < 30:
            return False
        if gap is not None:
            print(f"  [VPN] Lan cuoi doi IP: {gap:.0f}s truoc ({gap/60:.1f} phut)")

        old_ip = _get_ip()
        subprocess.run(["sc", "stop", HSS_SERVICE], capture_output=True, timeout=15)
        time.sleep(4)
        subprocess.run(["sc", "start", HSS_SERVICE], capture_output=True, timeout=15)

        for _ in range(30):
            time.sleep(1)
            new_ip = _get_ip()
            if new_ip:
                tag = "(IP moi)" if (old_ip and new_ip != old_ip) else "(IP nhu cu)"
                _vpn_lock.record_rotation()
                _ip_rotated_this_file.set()
                print(f"  [HotspotShield] {new_ip} {tag}")
                reset_tts_sessions()
                _post_rotate_event.clear()
                threading.Timer(2.0, _post_rotate_event.set).start()
                return True
        print("  [HotspotShield] Khong lay duoc IP sau khi restart service (se backoff thuong)")
        return False
    finally:
        _vpn_lock.release()
        _proton_rotate_lock.release()


def rotate_ip() -> bool:
    """Tu dong xoay IP dua tren VPN_TYPE."""
    if VPN_TYPE == "protonvpn":
        return proton_rotate()
    elif VPN_TYPE == "warp":
        return rotate_warp_ip()
    elif VPN_TYPE == "hotspot":
        return rotate_hotspot_ip()
    return False


def _start_periodic_rotate(interval_sec: float = 600.0):
    """Khoi dong thread rotate IP dinh ky (daemon, tu tat khi main thoat).
    Tinh thoi gian cho tu lan rotate cuoi — neu vua rotate do 429, timer reset theo."""
    def _worker():
        while True:
            gap = _vpn_lock.elapsed_since_last()
            wait = max(10.0, interval_sec - gap) if gap is not None else interval_sec
            time.sleep(wait)
            print(f"\n  [VPN] Rotate dinh ky ({interval_sec/60:.0f} phut ke tu lan cuoi)...", flush=True)
            rotate_ip()
    t = threading.Thread(target=_worker, daemon=True, name="periodic-rotate")
    t.start()


_errors_lock = threading.Lock()
_last_printed_errors = {}

def print_error_once(msg: str, expiry: float = 15.0):
    """In thong bao loi nhung tranh trung lap trong khoang thoi gian expiry giay."""
    global _last_printed_errors
    now = time.time()
    # Chuan hoa de gom nhom cac loi giong nhau
    norm_msg = msg.strip()
    if "429" in norm_msg:
        if "doi ip" in norm_msg.lower():
            norm_msg = "429_doi_ip"
        else:
            norm_msg = "429_nghi"
    else:
        norm_msg = re.sub(r'\s*\(thu lai \d+/\d+\)', '', norm_msg)
        norm_msg = re.sub(r'\d+', '', norm_msg)  # loai bo con so cu the de gom nhom
    
    with _errors_lock:
        last_time = _last_printed_errors.get(norm_msg, 0)
        if now - last_time > expiry:
            _last_printed_errors[norm_msg] = now
            print(msg)


def tts_chunk_to_file(text: str, out_path: Path) -> bool:
    """
    Doc 1 chunk -> luu ra file mp3. Tu retry voi backoff tang dan khi gap 429.
    Tra ve True neu thanh cong.
    """
    backoff = BACKOFF_BASE
    for attempt in range(1, RETRY_MAX + 1):
        try:
            gTTS(text=text, lang=LANG, slow=False).save(str(out_path))
            return True
        except gTTSError as e:
            if is_429(e):
                # Uu tien: doi IP qua ProtonVPN roi retry NGAY (nhanh hon ngoi cho)
                if VPN_TYPE != "none":
                    print_error_once(f"\n  [429] doi IP qua {VPN_TYPE} (thu lai {attempt}/{RETRY_MAX})...", expiry=8.0)
                    if rotate_ip():
                        time.sleep(1)
                        continue   # IP moi -> thu lai luon, khong backoff
                # Khong co ProtonVPN (hoac doi IP that bai) -> backoff + gian delay
                note_429()
                wait = min(backoff, BACKOFF_MAX)
                print_error_once(f"\n  [429] -> nghi {wait:.0f}s "
                      f"(thu lai {attempt}/{RETRY_MAX}, delay giua chunk -> {CHUNK_DELAY + _adaptive_extra:.1f}s)...", expiry=8.0)
                time.sleep(wait)
                backoff *= 2
                continue
            # Loi ket noi (Failed to connect) -> rotate IP roi thu lai
            if VPN_TYPE != "none" and is_conn_error(e):
                print_error_once(f"\n  [conn] Failed to connect -> doi IP...", expiry=8.0)
                if rotate_ip():
                    time.sleep(1)
                    continue
            print_error_once(f"\n  [gTTS loi] {str(e)[:90]} (thu lai {attempt}/{RETRY_MAX})")
            time.sleep(min(backoff, BACKOFF_MAX))
        except Exception as e:
            print_error_once(f"\n  [Loi mang] {str(e)[:90]} (thu lai {attempt}/{RETRY_MAX})")
            time.sleep(min(backoff, BACKOFF_MAX))
    return False



def postprocess_audio(raw_path: Path, out_path: Path) -> bool:
    """
    Chay 1 lan ffmpeg tren file da ghep: ap toc do (atempo=SPEED) + bitrate (BITRATE).
    Khong doi -> chi doi ten file. Thieu ffmpeg -> giu nguyen file ghep.
    """
    need_speed = abs(SPEED - 1.0) > 1e-3
    need_rate  = bool(BITRATE)
    if not (need_speed or need_rate):
        raw_path.replace(out_path)        # khong hau ky -> dung file ghep luon
        return True
    if not FFMPEG:
        print("  [!] Khong co ffmpeg -> bo qua hau ky (giu nguyen file ghep).")
        raw_path.replace(out_path)
        return True

    cmd = [FFMPEG, "-y", "-loglevel", "error", "-i", str(raw_path)]
    if need_speed:
        cmd += ["-filter:a", f"atempo={SPEED}"]   # atempo ho tro 0.5..2.0
    if need_rate:
        cmd += ["-b:a", BITRATE]
    cmd.append(str(out_path))
    try:
        subprocess.run(cmd, check=True)
        raw_path.unlink(missing_ok=True)
        return True
    except Exception as e:
        print(f"  [!] ffmpeg loi ({str(e)[:60]}) -> giu nguyen file ghep.")
        raw_path.replace(out_path)
        return True


# ════════════════════════════════════════════════════════════
#  TRANG THAI (nho file nao da xong)
# ════════════════════════════════════════════════════════════
def load_progress(mp3_dir: Path) -> dict:
    p = mp3_dir / "_tts_progress.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"done": {}, "failed": {}}


def save_progress(mp3_dir: Path, data: dict):
    try:
        (mp3_dir / "_tts_progress.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"  [!] Khong luu duoc trang thai: {e}")


def sync_translated_progress(watch_dir: Path):
    """Quet thu muc watch_dir, trich xuat novel_id tu URL nguon cua cac file .txt,
    va tu dong bo sung vao _translated_progress.json neu con thieu."""
    progress_file = None
    for d in (watch_dir, watch_dir.parent, watch_dir.parent.parent):
        p = d / "_translated_progress.json"
        if p.exists() or (d / "translated").exists():
            progress_file = p
            break
    if not progress_file:
        return

    try:
        if progress_file.exists():
            data = json.loads(progress_file.read_text(encoding="utf-8"))
        else:
            data = {}
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}

    existing_values = set(data.values())
    updated = False
    
    txt_files = list(watch_dir.glob("*.txt"))
    for txt in txt_files:
        if txt.name.startswith("_"):
            continue
        if txt.name in existing_values:
            continue
        
        try:
            head = txt.read_text(encoding="utf-8", errors="ignore")[:2000]
            m = re.search(r"https?://[^/]+/novel/(?:id/)?(\d+)", head)
            if m:
                nid = m.group(1)
                if nid not in data:
                    data[nid] = txt.name
                    print(f"  [Sync] Bo sung truyen: {txt.name} -> ID: {nid}")
                    updated = True
        except Exception:
            pass

    if updated:
        try:
            progress_file.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
            print(f"  [Sync] Da cap nhat lai {progress_file.name}")
        except Exception as e:
            print(f"  [Sync] Loi ghi file _translated_progress: {e}")


def load_translated_done(watch_dir: Path):
    """Doc _translated_progress.json (do alicesw_downloader ghi) -> set ten file .txt
    DA DICH XONG. Tim o watch_dir va 2 cap thu muc cha.
    Tra ve None neu khong tim thay file (=> khong gate, xu ly moi file nhu cu).
    Cau truc file: {novel_id: "ten_file.txt"} -> lay cac gia tri (ten file)."""
    for d in (watch_dir, watch_dir.parent, watch_dir.parent.parent):
        p = d / "_translated_progress.json"
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                return None
            if isinstance(data, dict):
                return {str(v) for v in data.values()}
            return None   # dinh dang khac (list id) -> khong doi chieu duoc theo ten
    return None


def file_sig(p: Path) -> dict:
    st = p.stat()
    return {"size": st.st_size, "mtime": int(st.st_mtime)}


def needs_processing(txt: Path, mp3_dir: Path, done: dict) -> bool:
    """File can xu ly neu: chua tung lam, hoac da bi sua, hoac mp3 dich bi xoa."""
    out_name = f"{output_stem(txt.stem)}.mp3"
    out = mp3_dir / out_name
    rec = done.get(txt.name)

    # Chua co record -> can xu ly
    if not rec:
        return True

    sig = file_sig(txt)
    sig_changed = (rec.get("size") != sig["size"] or rec.get("mtime") != sig["mtime"])

    # Mp3 da co va du lon (> 10KB) -> cap nhat signature moi vao done (tranh lam lai)
    if out.exists() and out.stat().st_size > 10_000:
        if sig_changed:
            # File txt thay doi signature (vi du: bi touch/ghi lai) nhung mp3 van on
            # -> Chi cap nhat signature, KHONG tao lai mp3
            done[txt.name] = {**sig, "out": out_name}
            print(f"  [skip] {txt.name}: mp3 da co, cap nhat signature moi.")
        return False

    # Mp3 chua co hoac qua nho -> can xu ly neu signature thay doi
    return sig_changed or not out.exists()



# ════════════════════════════════════════════════════════════
#  XU LY 1 FILE TXT -> MP3
# ════════════════════════════════════════════════════════════
def process_file(txt: Path, mp3_dir: Path) -> bool:
    """
    Chuyen 1 file .txt thanh .mp3. Resume tung chunk qua thu muc cache.
    Tra ve True neu hoan tat day du.
    """
    raw = txt.read_text(encoding="utf-8", errors="replace")
    text = clean_text_for_tts(raw)
    if not text:
        print(f"  [bo qua] {txt.name}: rong sau khi loc.")
        return False

    chunks = split_into_chunks(text)
    total = len(chunks)

    if MAX_TXT_MB > 0 and txt.stat().st_size > MAX_TXT_MB * 1024 * 1024:
        print(f"  [skip-size] {txt.name}: {txt.stat().st_size//1024}KB > {MAX_TXT_MB:.0f}MB gioi han -> bo qua.")
        return False

    out_stem = output_stem(txt.stem)
    cache_dir = mp3_dir / ".cache" / txt.stem   # cache theo ten goc -> resume khong doi
    cache_dir.mkdir(parents=True, exist_ok=True)
    out_path = mp3_dir / f"{out_stem}.mp3"

    print(f"\n[>] {txt.name}  ({len(text):,} ky tu, {total} chunk, {WORKERS} thread song song)")

    # ── Chuan bi danh sach chunk can tai (bo qua cache) ──
    todo = []   # [(i, chunk, cache_mp3), ...]
    for i, chunk in enumerate(chunks, 1):
        cache_mp3 = cache_dir / f"{i:05d}.mp3"
        if cache_mp3.exists() and cache_mp3.stat().st_size > 0:
            continue
        todo.append((i, chunk, cache_mp3))

    cached_count = total - len(todo)
    if cached_count:
        print(f"  [cache] {cached_count}/{total} chunk da co, can tai: {len(todo)} chunk")

    # ── Tai song song voi WORKERS thread ──
    done_count   = [cached_count]   # dung list de co the sua trong closure
    fail_chunks  = []               # index chunk bi loi
    print_lock   = threading.Lock()

    def _fetch_one(args):
        """Worker: tai 1 chunk, delay rieng. Tra ve (i, ok)."""
        i, chunk, cache_mp3 = args
        _post_rotate_event.wait()    # cho neu vua doi IP (khong spam IP moi)
        eff_delay = CHUNK_DELAY + _adaptive_extra
        ok = tts_chunk_to_file(chunk, cache_mp3)
        if ok:
            note_ok()
            time.sleep(eff_delay)    # don luong sau moi request
        else:
            note_429()
        with print_lock:
            done_count[0] += 1
            tag = f" +delay {_adaptive_extra:.1f}s" if _adaptive_extra > 0 else ""
            print(f"  [{done_count[0]:4d}/{total}] {'OK' if ok else 'FAIL'} chunk {i}{tag}     ", end="\r", flush=True)
        return i, ok

    if todo:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = {pool.submit(_fetch_one, args): args[0] for args in todo}
            for fut in as_completed(futures):
                i, ok = fut.result()
                if not ok:
                    fail_chunks.append(i)

    if fail_chunks:
        print(f"\n  [!] {len(fail_chunks)} chunk that bai ({fail_chunks[:5]}...) -> se lam lai o lan quet sau.")
        return False

    # ── Ghep cac chunk mp3 thanh 1 file (noi byte) ──
    raw_path = mp3_dir / f"{out_stem}.raw.mp3"
    print(f"  [ghep] {total} chunk...        ")
    try:
        with open(raw_path, "wb") as out:
            for i in range(1, total + 1):
                out.write((cache_dir / f"{i:05d}.mp3").read_bytes())
    except Exception as e:
        print(f"  [!] Loi ghep file: {e}")
        return False

    # ── Hau ky: toc do + bitrate (1 lan ffmpeg) ──
    if not (abs(SPEED - 1.0) <= 1e-3 and not BITRATE):
        print(f"  [hau ky] speed={SPEED}x, bitrate={BITRATE or 'goc'} -> {out_path.name}")
    if not postprocess_audio(raw_path, out_path):
        return False

    # ── Don cache ──
    try:
        for f in cache_dir.iterdir():
            f.unlink()
        cache_dir.rmdir()
    except Exception:
        pass

    size_mb = out_path.stat().st_size / 1024 / 1024
    print(f"  [OK] {out_path.name}  ({size_mb:.2f} MB)")
    return True


def format_eta(seconds: float) -> str:
    """Quy doi giay ra chuoi thong minh (Ngay Gio Phut Giay)."""
    if seconds <= 0:
        return "0 giây"
    
    d = int(seconds // 86400)
    h = int((seconds % 86400) // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    
    parts = []
    if d > 0:
        parts.append(f"{d} ngày")
    if h > 0 or d > 0:
        parts.append(f"{h} giờ")
    if m > 0 or h > 0 or d > 0:
        parts.append(f"{m} phút")
    parts.append(f"{s} giây")
    
    # Neu con lai > 1 ngay, chi can hien ngay va gio
    if d > 0:
        return f"{d} ngày {h} giờ"
    # Neu con lai > 1 gio, hien gio va phut
    if h > 0:
        return f"{h} giờ {m} phút"
    # Neu con lai > 1 phut, hien phut va giay
    if m > 0:
        return f"{m} phút {s} giây"
    
    return f"{s} giây"


# ════════════════════════════════════════════════════════════
#  VONG QUET
# ════════════════════════════════════════════════════════════
def scan_once(watch_dir: Path, mp3_dir: Path, progress: dict, gate_done: bool = True, reverse_sort: bool = False, max_size_mb: float = None) -> int:
    """Quet toàn bộ thu muc, xu ly cac file moi/sua. Tra ve so file da xu ly xong.
    gate_done=True: CHI tao mp3 cho file co trong _translated_progress.json (da dich xong).
    max_size_mb: neu dat, bo qua cac file .txt co kich thuoc >= X MB."""
    done = progress["done"]
    processed = 0
    now = time.time()

    # Reload ban dich da hoan thanh
    done_names = load_translated_done(watch_dir) if gate_done else None

    # Uu tien theo kich thuoc file (nho truoc, hoac lon truoc neu reverse_sort=True)
    txt_files = sorted(watch_dir.glob("*.txt"), key=lambda p: p.stat().st_size, reverse=reverse_sort)
    todo_files = []
    
    for txt in txt_files:
        if txt.name.startswith("_"):          # bo file he thong (_progress...)
            continue
        # ── GATE: chi tao mp3 tu ban dich DA DONE ──
        if done_names is not None and txt.name not in done_names:
            continue
        if not needs_processing(txt, mp3_dir, done):
            continue
        # Bo qua file txt qua lon
        if MAX_TXT_MB > 0 and txt.stat().st_size > MAX_TXT_MB * 1024 * 1024:
            print(f"  [skip-size] {txt.name}: {txt.stat().st_size//1024}KB > {MAX_TXT_MB:.0f}MB gioi han -> bo qua.")
            continue
        # Bo qua file vua duoc ghi (chua on dinh) -> tranh doc file dang dich do
        if now - txt.stat().st_mtime < FILE_STABLE_SEC:
            print(f"  [cho] {txt.name} vua thay doi, doi on dinh...", end="\r")
            continue
        todo_files.append(txt)

    total_files = len(todo_files)
    if total_files == 0:
        print("  [gate] Khong co file .txt nao can xu ly.")
        return 0

    file_sizes_kb = {txt: txt.stat().st_size / 1024 for txt in todo_files}
    total_kb = sum(file_sizes_kb.values())
    print(f"\n[*] Tim thay {total_files} file can chuyen doi sang MP3 (tong {total_kb:.0f} KB).")
    global WORKERS
    start_time = time.time()
    processed_kb = 0.0

    for idx, txt in enumerate(todo_files, 1):
        _ip_rotated_this_file.clear()
        ok = process_file(txt, mp3_dir)
        processed_kb += file_sizes_kb[txt]

        if ok:
            done[txt.name] = {**file_sig(txt), "out": f"{output_stem(txt.stem)}.mp3"}
            progress.setdefault("failed", {}).pop(txt.name, None)
            save_progress(mp3_dir, progress)
            processed += 1
            if AUTO_SCALE:
                WORKERS = min(WORKERS + 1, MAX_WORKERS)
                print(f"  [thread] OK -> tang len {WORKERS} thread")
        else:
            progress.setdefault("failed", {})[txt.name] = {"failed_at": int(time.time())}
            save_progress(mp3_dir, progress)
            if AUTO_SCALE and _ip_rotated_this_file.is_set():
                WORKERS = max(WORKERS - 1, MIN_WORKERS)
                print(f"  [thread] Fail + doi IP -> giam xuong {WORKERS} thread")

        remaining_files = total_files - idx
        remaining_kb = total_kb - processed_kb
        if remaining_files > 0 and processed_kb > 0:
            elapsed = time.time() - start_time
            rate_kb_per_sec = processed_kb / elapsed if elapsed > 0 else 0
            est_remaining_sec = remaining_kb / rate_kb_per_sec if rate_kb_per_sec > 0 else 0
            print(f"  [Uoc tinh] Con lai {remaining_files}/{total_files} file ({remaining_kb:.0f}/{total_kb:.0f} KB), du kien: {format_eta(est_remaining_sec)}")

    return processed


def main():
    global LANG, CHUNK_DELAY, CHUNK_MAX_CHARS, SPEED, BITRATE, USE_PROTON, WORKERS, VPN_TYPE, MIN_WORKERS, AUTO_SCALE
    parser = argparse.ArgumentParser(
        description="Quet thu muc, tu dong chuyen .txt -> .mp3 bang gTTS.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--dir", default="downloaded/translated",
                        help="Thu muc chua file .txt can theo doi (mac dinh: downloaded/translated)")
    parser.add_argument("--mp3", default="",
                        help="Thu muc luu .mp3 (mac dinh: <dir.parent>/mp3)")
    parser.add_argument("--lang", default=LANG,
                        help=f"Ngon ngu doc (mac dinh: {LANG})")
    parser.add_argument("--chunk-delay", type=float, default=CHUNK_DELAY,
                        help=f"Delay giua cac chunk khi goi gTTS (mac dinh: {CHUNK_DELAY}s). Giam de tao nhanh hon (rui ro 429 cao hon).")
    parser.add_argument("--chunk-chars", type=int, default=CHUNK_MAX_CHARS,
                        help=f"Do dai toi da moi chunk (mac dinh: {CHUNK_MAX_CHARS}). Tang de it delay hon -> tao nhanh hon.")
    parser.add_argument("--speed", type=float, default=SPEED,
                        help=f"He so toc do doc qua ffmpeg (mac dinh: {SPEED}; 1.0 = giu nguyen). KHONG lam tao nhanh hon, chi lam audio ngan hon.")
    parser.add_argument("--bitrate", default=BITRATE,
                        help=f"Bitrate mp3 dau ra qua ffmpeg (mac dinh: {BITRATE}; '' = giu ~64k goc). 32k -> file nhe hon ~nua.")
    parser.add_argument("--workers", type=int, default=WORKERS,
                        help=f"So thread song song tai chunk (mac dinh: {WORKERS}). Tang de nhanh hon nhung de bi 429 hon.")
    parser.add_argument("--no-auto", dest="no_auto", action="store_true",
                        help="Giu co dinh so thread (--workers), tat tu dong tang/giam theo ket qua.")
    parser.add_argument("--no-vpn", dest="no_vpn", action="store_true",
                        help="Tat tu doi IP qua VPN khi gap 429.")
    parser.add_argument("--vpn", choices=["protonvpn", "warp", "hotspot", "none", "auto"], default="auto",
                        help="Chon loai VPN de tu dong doi IP khi bi block (protonvpn | warp | hotspot | none | auto, mac dinh: auto). "
                             "hotspot: ngat/ket noi lai WiFi hotspot hien tai de lay IP moi tu carrier.")
    parser.add_argument("--nguoc", action="store_true",
                        help="Dao nguoc thu tu quet (mac dinh: uu tien file nho -> lon; bat: uu tien file lon -> nho)")
    parser.add_argument("--max-mb", type=float, default=0.0, dest="max_mb",
                        help="Bo qua file .txt lon hon X MB. 0 = khong gioi han. "
                             "Vi du: --max-mb 5 chi tao mp3 tu file txt <=5MB.")
    parser.add_argument("--all-txt", dest="all_txt", action="store_true",
                        help="Tao mp3 cho MOI file .txt (tat gate). Mac dinh: chi tao tu ban dich da done "
                             "(co trong _translated_progress.json).")
    parser.add_argument("--max-size", dest="max_size", type=float, default=None,
                        help="Chi tao mp3 cho file .txt co kich thuoc < X MB (vi du: --max-size 1.5). "
                             "Mac dinh: khong gioi han kich thuoc.")
    args = parser.parse_args()

    global MAX_TXT_MB
    LANG = args.lang
    CHUNK_DELAY = args.chunk_delay
    CHUNK_MAX_CHARS = args.chunk_chars
    SPEED = args.speed
    BITRATE = args.bitrate
    WORKERS = args.workers
    MIN_WORKERS = args.workers   # san toi thieu = gia tri khoi dong, khong giam duoi day
    AUTO_SCALE  = not args.no_auto
    MAX_TXT_MB = args.max_mb

    # Determine auto VPN type
    is_warp_available = os.path.exists(r"C:\Program Files\Cloudflare\Cloudflare WARP\warp-cli.exe")
    is_proton_available = bool(PROTON_CLI or PROTON_SERVICE)
    
    if args.no_vpn:
        VPN_TYPE = "none"
    elif args.vpn == "auto":
        if is_proton_available:
            VPN_TYPE = "protonvpn"
        elif is_warp_available:
            VPN_TYPE = "warp"
        else:
            VPN_TYPE = "none"
    else:
        VPN_TYPE = args.vpn

    watch_dir = Path(args.dir)
    if not watch_dir.exists():
        print(f"[!] Khong thay thu muc: {watch_dir.resolve()}")
        sys.exit(1)
    mp3_dir = Path(args.mp3) if args.mp3 else (watch_dir.parent / "mp3")
    mp3_dir.mkdir(parents=True, exist_ok=True)

    progress = load_progress(mp3_dir)
    gate_done = not args.all_txt

    if gate_done:
        sync_translated_progress(watch_dir)

    print(f"{'='*60}")
    print("  TXT -> MP3 Watcher (gTTS)")
    print(f"  Theo doi : {watch_dir.resolve()}")
    print(f"  Luu mp3  : {mp3_dir.resolve()}")
    print(f"  Ngon ngu : {LANG}   |  Delay chunk: {CHUNK_DELAY}s   |  Chunk: {CHUNK_MAX_CHARS} ky tu   |  Workers: {WORKERS}")
    hauky = f"speed {SPEED}x, bitrate {BITRATE}" if (abs(SPEED-1.0) > 1e-3 or BITRATE) else "giu nguyen"
    print(f"  Hau ky   : {hauky}" + ("" if FFMPEG else "  [!] CHUA CO ffmpeg -> se bo qua hau ky"))
    if VPN_TYPE != "none":
        if VPN_TYPE == "protonvpn":
            cli_status = f"CLI={PROTON_CLI or 'khong thay'}, Service={'co' if PROTON_SERVICE else 'khong thay'}"
            print(f"  VPN auto-rotate: BAT [protonvpn] ({cli_status})")
            if not USE_PROTON:
                print(f"  [!] CANH BAO: ProtonVPN khong phat hien duoc -> doi IP se that bai!")
        elif VPN_TYPE == "hotspot":
            svc_tag = f"service={HSS_SERVICE}" if HSS_SERVICE else "CANH BAO: khong thay service!"
            print(f"  VPN auto-rotate: BAT [HotspotShield] ({svc_tag})")
        else:
            print(f"  VPN auto-rotate: BAT [{VPN_TYPE}] - gap 429 se tu doi IP")
    else:
        print(f"  VPN auto-rotate: TAT -> gap 429 chi backoff")
    if VPN_TYPE != "none":
        _start_periodic_rotate(600.0)
        print(f"  VPN dinh ky  : rotate moi 10 phut")
    print(f"  Da xong  : {len(progress['done'])} file")
    if gate_done:
        print(f"  Gate     : CHI tao mp3 tu ban dich DA DONE (_translated_progress.json)")
    else:
        print(f"  Gate     : TAT (--all-txt) -> tao mp3 cho moi file .txt")
    print(f"{'='*60}")

    if args.max_size is not None:
        print(f"  Filter   : chi xu ly file .txt < {args.max_size} MB")
    n = scan_once(watch_dir, mp3_dir, progress, gate_done=gate_done, reverse_sort=args.nguoc, max_size_mb=args.max_size)
    print(f"\n[*] Hoan tat quet: {n} file moi da duoc chuyen doi xong.")


if __name__ == "__main__":
    main()
