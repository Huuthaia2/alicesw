#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sosing Downloader
=================
Tai truyen tu sosing.com (vd tag https://sosing.com/tag/13/), dich sang tieng
Viet, doi ten rieng sang am Han-Viet, luu ra file .txt trong thu muc txt/.

Sosing.com nam sau Cloudflare (thu thach "Just a moment..."), nen tool dung
SeleniumBase che do UC (undetected Chrome) de vuot Cloudflare. Sau khi lay
duoc HTML, tool tai dung TOAN BO logic dich cua alicesw_downloader (engine
Caiyun -> Google tu xoay) + module hanviet de convert ten rieng Han-Viet.

Cau truc sosing.com:
  - Trang tag:     https://sosing.com/tag/13/                (page 1)
                   https://sosing.com/tag/13/page/2/         (page 2, 3, ...)
  - Link truyen:   https://sosing.com/YYYY/MM/DD/<slug>/     (bai post = 1 truyen)
  - Nhieu chuong:  WordPress phan trang <!--nextpage-->
                   https://sosing.com/YYYY/MM/DD/<slug>/2/   (chuong/trang 2, 3, ...)
  - Noi dung:      div.entry-content  (cac the <p>)
  - Tieu de:       h1.entry-title
  - The loai:      a[rel=tag]
  - Phan trang:    a.post-page-numbers  (so trang)

Cach dung:
  py -u sosing_downloader.py --tag 13
  py -u sosing_downloader.py --tag 13 --max-tag-pages 3 --limit 10
  py -u sosing_downloader.py --url https://sosing.com/tag/13/
  py -u sosing_downloader.py --story https://sosing.com/2026/05/28/<slug>/
  py -u sosing_downloader.py --tag 13 --engine caiyun
  py -u sosing_downloader.py --tag 13 --no-translate      # chi luu ban goc tieng Trung
  py -u sosing_downloader.py --tag 13 --no-resume         # tai lai tu dau (bo qua _done.json)

Resume: moi truyen tai xong duoc ghi vao txt/_done.json. Chay lai cung lenh
se tu bo qua cac truyen da xong -> gian doan giua chung van tiep tuc duoc.

Ve viec CHAY NGAM (da kiem chung tren sosing.com 2026-07):
  - sosing dung Cloudflare Turnstile TUONG TAC (trang "chung minh la nguoi that").
  - HEADLESS / headless2 -> BI CHAN (Cloudflare khong cho browser khong man hinh).
  - Chi CDP thuan (--no-click, khong dung chuot) -> KHONG vuot duoc site nay.
  - Cach chay duy nhat on dinh: HEADED + tu bam Turnstile bang chuot that
    (pyautogui). Cua so Chrome phai dang o truoc man hinh khi bam.
  Thuc te khi chay: tool chi can bam luc gap trang thu thach (chu yeu o TRANG
  DAU moi lan chay); sau khi qua, cookie cf_clearance dung lai cho cac trang
  sau trong cung phien -> phan lon thoi gian (tai + dich) KHONG dung chuot.
  => De "chay nen": cu chay headed, luc thay log "xac nhan la nguoi that" thi
     buong chuot vai giay cho no tu bam; ngoai luc do dung may binh thuong.
  (Profile Chrome co dinh sosing.com/.chrome_profile giup do bi thu thach lai.)

Yeu cau (cai 1 lan):
  py -m pip install seleniumbase translators beautifulsoup4
  (SeleniumBase tu tai chromedriver o lan chay dau; can Google Chrome.)
"""
import os
os.environ.setdefault("PYTHONUNBUFFERED", "1")
import re
import sys
import json
import time
import shutil
import argparse
import threading
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote

from bs4 import BeautifulSoup

# ── UTF-8 console (tranh loi cp1252 khi in tieng Trung/Viet) ──
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ── Tai dung logic dich + convert Han-Viet cua project cha ────
_ROOT = Path(__file__).resolve().parent.parent   # d:\Unity\alicesw
sys.path.insert(0, str(_ROOT))
import alicesw_downloader as dl          # translate_text / translate_title / clean_title
import hanviet as hv                     # hanzi_to_hanviet / has_hanzi
import novel_manager as nm               # get_content_fingerprint / clean_chinese_text

BASE = "https://sosing.com"
THIS_DIR = Path(__file__).resolve().parent
TXT_DIR  = THIS_DIR / "txt"
ORIGIN_DIR = TXT_DIR / "origin"   # ban goc tieng Trung dang JSON (cho luong dich rieng)


# ════════════════════════════════════════════════════════════
#  CHONG TRUNG qua downloaded_registry.json (dung chung voi alicesw)
# ════════════════════════════════════════════════════════════
# Quy tac:
#   - Check trung theo TEN (tieu de Han) VA VAN TAY noi dung (doan_mau_chu_han).
#   - Truyen MOI  -> them ban ghi moi (co van tay) vao registry.
#   - Truyen TRUNG -> them link sosing vao 'links' cua ban ghi da co; file txt
#     dat ten co '_' o dau va noi dung chua thong tin ban ghi trung do.
REGISTRY_PATH = _ROOT / "downloaded" / "downloaded_registry.json"
_REG_LOCKFILE = str(REGISTRY_PATH) + ".lock"
_reg_lock = threading.RLock()    # khoa LUONG (trong 1 tien trinh)
_reg: dict | None = None
_reg_needles: list = []          # [(needle_50chars, id), ...] tu van tay
_reg_titles: dict = {}           # han(title) -> id
_reg_indexed: set = set()        # id da index (de reload tang dan)
_reg_mtime: float = 0.0          # mtime cua file luc load gan nhat
_reg_backed_up = False


class _RegFileLock:
    """Khoa LIEN-TIEN-TRINH (lockfile O_EXCL) — de nhieu tien trinh cung ghi
    registry khong de len nhau. Tu don lock cu (stale) neu tien trinh truoc chet."""
    def __init__(self, timeout: float = 30.0, stale: float = 120.0):
        self.timeout = timeout; self.stale = stale; self.fd = None

    def __enter__(self):
        start = time.time()
        while True:
            try:
                self.fd = os.open(_REG_LOCKFILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                try:
                    os.write(self.fd, str(os.getpid()).encode())
                except Exception:
                    pass
                return self
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(_REG_LOCKFILE) > self.stale:
                        os.remove(_REG_LOCKFILE); continue
                except OSError:
                    pass
                if time.time() - start > self.timeout:
                    return self          # bo cuoc -> chay best-effort (hiem)
                time.sleep(0.1)

    def __exit__(self, *a):
        if self.fd is not None:
            try:
                os.close(self.fd); os.remove(_REG_LOCKFILE)
            except OSError:
                pass
            self.fd = None


def _han_only(t: str) -> str:
    return "".join(c for c in (t or "") if "一" <= c <= "鿿")


# Chuan hoa 简↔繁 ve GIAN THE de dedup khop du nguon la phon the (fsnovel/sosing)
# hay gian the (langyou). Neu khong co opencc thi giu nguyen (chi khop cung he chu).
_t2s_cc = None
def _to_simp(text: str) -> str:
    global _t2s_cc
    if not text:
        return text
    if _t2s_cc is None:
        try:
            from opencc import OpenCC
            _t2s_cc = OpenCC("t2s")
        except Exception:
            _t2s_cc = False
    return _t2s_cc.convert(text) if _t2s_cc else text


def _reg_index_entry(nid: str, e: dict):
    if nid in _reg_indexed:
        return
    _reg_indexed.add(nid)
    fp = _to_simp(e.get("dau_van_tay_noi_dung", {}).get("doan_mau_chu_han", "") or "")
    if len(fp) >= 40:
        _reg_needles.append((fp[:50], nid))
        if len(fp) >= 130:
            _reg_needles.append((fp[80:130], nid))
    for t in [e.get("ten_goc_han", "")] + (e.get("ten_viet_lien_quan", []) or []):
        h = _to_simp(_han_only(t))
        if len(h) >= 2:
            _reg_titles.setdefault(h, nid)


def _reg_mtime_now() -> float:
    try:
        return os.path.getmtime(REGISTRY_PATH)
    except OSError:
        return 0.0


def _load_registry() -> dict:
    """Load lan dau (full index). Cac lan sau dung _reg_reload_if_changed()."""
    global _reg, _reg_mtime
    if _reg is not None:
        return _reg
    try:
        _reg = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        log(f"Khong doc duoc registry ({e}) -> tao moi.", "!")
        _reg = {}
    _reg_mtime = _reg_mtime_now()
    for nid, ent in _reg.items():
        _reg_index_entry(nid, ent)
    return _reg


def _reg_reload_if_changed():
    """Neu file bi tien trinh KHAC ghi (mtime doi) -> nap lai + index TANG DAN
    (chi index ban ghi moi -> nhanh, khong dung lai ca 11k needle)."""
    global _reg, _reg_mtime
    _load_registry()
    m = _reg_mtime_now()
    if m and m != _reg_mtime:
        try:
            _reg = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))  # ~0.05s
            _reg_mtime = m
            for nid, ent in _reg.items():
                if nid not in _reg_indexed:      # chi index cai moi
                    _reg_index_entry(nid, ent)
        except Exception as e:
            log(f"Reload registry loi: {e}", "!")


def _save_registry():
    global _reg_backed_up, _reg_mtime
    if not _reg_backed_up and REGISTRY_PATH.exists():
        try:
            shutil.copy(str(REGISTRY_PATH), str(REGISTRY_PATH) + ".bak")
        except Exception:
            pass
        _reg_backed_up = True
    tmp = str(REGISTRY_PATH) + f".tmp.{os.getpid()}"
    Path(tmp).write_text(json.dumps(_reg, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, str(REGISTRY_PATH))   # ghi nguyen tu, tranh hong file khi dang ghi
    _reg_mtime = _reg_mtime_now()          # cap nhat de khong tu-reload write cua chinh minh


def registry_check_and_update(cn_title: str, chapters_cn: list[str], url: str,
                              vi_title: str = "", translated_path: str = "") -> tuple:
    """So trung + cap nhat registry (an toan da luong).

    Tra ve (is_dup, entry_id, entry_dict):
      - is_dup=True : da co -> da them `url` vao links cua ban ghi trung.
      - is_dup=False: moi   -> da them ban ghi moi (kem van tay).
    """
    sos_clean = _to_simp(nm.clean_chinese_text("".join(chapters_cn)))
    cn_h = _to_simp(_han_only(cn_title))
    # Khoa LUONG (workers) + khoa LIEN-TIEN-TRINH (2 tool chay song song).
    with _reg_lock, _RegFileLock():
        _reg_reload_if_changed()               # nap thay doi cua tien trinh khac
        reg = _reg

        matched_id = None
        for needle, nid in _reg_needles:          # 1) khop VAN TAY noi dung
            if needle and needle in sos_clean:
                matched_id = nid; break
        if not matched_id and cn_h and cn_h in _reg_titles:   # 2) khop TEN
            matched_id = _reg_titles[cn_h]

        if matched_id and matched_id in reg:       # ── TRUNG ──
            ent = reg[matched_id]
            links = ent.setdefault("links", [])
            if url and url not in links:
                links.append(url)
            if vi_title and vi_title not in ent.setdefault("ten_viet_lien_quan", []):
                ent["ten_viet_lien_quan"].append(vi_title)
            _save_registry()
            return True, matched_id, ent

        # ── MOI ── tao ban ghi + van tay
        fp = nm.get_content_fingerprint(chapters_cn[0] if chapters_cn else "", 200)
        maxid = max((int(k) for k in reg if k.isdigit()), default=10000)
        nid = str(maxid + 1)
        ent = {
            "truyen_id_chuan": nid,
            "ten_goc_han": cn_title or "Chưa rõ",
            "ten_viet_lien_quan": [x for x in [vi_title, cn_title] if x],
            "tac_gia": "Khong ro",
            "links": [url] if url else [],
            "file_cuc_bo": {"origin": "", "translated": translated_path},
            "dau_van_tay_noi_dung": {"doan_mau_chu_han": fp},
        }
        reg[nid] = ent
        _reg_index_entry(nid, ent)
        _save_registry()
        return False, nid, ent

# Marker con sot cua trang thu thach Cloudflare (KHONG dung "challenge-platform"
# vi chuoi nay van con trong <script> ke ca khi da qua thu thach).
CF_MARKERS = (
    "请稍候", "請稍候", "Just a moment", "cf_chl_opt", "Checking your browser",
    "正在进行安全验证", "正在進行安全驗證",   # "dang tien hanh xac minh an toan"
    "请验证您是真人", "請驗證您是真人",         # "hay xac minh ban la nguoi that" (Turnstile)
    "验证您是真人", "驗證您是真人",
)

# Link bai post = 1 truyen: /YYYY/MM/DD/<slug>/ (KHONG co so trang o cuoi)
_STORY_RE = re.compile(r"^https?://sosing\.com/\d{4}/\d{2}/\d{2}/[^/]+/?$")


def log(msg: str, tag: str = "*"):
    print(f"[{tag}] {msg}", flush=True)


# ════════════════════════════════════════════════════════════
#  TRINH DUYET (SeleniumBase UC) — vuot Cloudflare
# ════════════════════════════════════════════════════════════
class Browser:
    """Boc SeleniumBase che do CDP (undetected) — vuot Cloudflare Turnstile.

    CDP mode on dinh hon cach GUI-click thuan: khi con o trang thu thach, ta
    goi cdp.gui_click_captcha() / uc_gui_click_captcha() de bam o "xac nhan la
    nguoi that", roi doi trang tan. Neu tu dong khong duoc va dang chay headed,
    nguoi dung co the tu bam o trong cua so Chrome — tool se tu phat hien khi qua.
    """

    def __init__(self, headed: bool = True, profile_dir: str | None = None,
                 no_click: bool = False):
        from seleniumbase import SB  # import tre de loi cai dat hien ro
        kwargs = dict(uc=True, headless=not headed, locale="zh-CN")
        if profile_dir:
            # Profile Chrome co dinh -> cookie cf_clearance duoc luu lai giua cac
            # lan chay. Giai Cloudflare 1 lan, cac lan sau (ke ca --headless) dung
            # lai cookie -> thuong khong bi thu thach nua, khong can bam gi.
            kwargs["user_data_dir"] = profile_dir
        self._cm = SB(**kwargs)
        self.sb = self._cm.__enter__()
        self._activated = False
        self.headed = headed
        self.no_click = no_click

    def _try_solve(self):
        for fn in ("cdp.gui_click_captcha", "uc_gui_click_captcha"):
            try:
                if fn.startswith("cdp"):
                    self.sb.cdp.gui_click_captcha()
                else:
                    self.sb.uc_gui_click_captcha()
                return
            except Exception:
                continue

    def _source(self) -> str:
        for getter in (lambda: self.sb.cdp.get_page_source(),
                       lambda: self.sb.get_page_source()):
            try:
                h = getter()
                if h:
                    return h
            except Exception:
                continue
        return ""

    def get(self, url: str, wait: int | None = None, tries: int = 3) -> str | None:
        """Mo url, giai Cloudflare, tra ve HTML (hoac None neu that bai).

        CDP mode thuong TU vuot Turnstile khong can bam. Khi ket, tool mo lai
        trang (moi lan mo la 1 co hoi CDP tu vuot lai) toi `tries` lan.
        - Che do binh thuong: khi con ket, thu bam Turnstile (dung chuot that).
        - Che do no_click (chay nen): KHONG bao gio dung chuot; chi dua vao CDP
          tu vuot + mo lai. Ban co the de cua so Chrome sang desktop ao khac.
        """
        if wait is None:
            wait = 75 if self.headed else 45
        for attempt in range(tries):
            try:
                if not self._activated:
                    self.sb.activate_cdp_mode(url)
                    self._activated = True
                else:
                    self.sb.cdp.open(url)
            except Exception as e:
                log(f"Loi mo {url}: {e}", "!")
                self.sb.sleep(2)
                continue

            html = ""
            hinted = False
            for i in range(wait):
                html = self._source()
                passed_cf = html and not any(m in html for m in CF_MARKERS)
                # CDP get_page_source() doi khi tra ve DOM chua load xong (chi <head>).
                # Chi coi san sang khi da qua Cloudflare VA than trang WordPress da co.
                if passed_cf and "entry-title" in html and "</body>" in html:
                    return html
                if not passed_cf and not self.no_click and i % 3 == 0:
                    self._try_solve()          # thu bam Turnstile (chuot that)
                    if self.headed and not hinted and i >= 6:
                        log("Cloudflare hoi 'xac nhan la nguoi that' — neu tu bam "
                            "khong duoc, hay TU BAM o trong cua so Chrome.", "!")
                        hinted = True
                self.sb.sleep(1)
            log(f"Chua qua Cloudflare (lan {attempt+1}/{tries}), mo lai: {url}", "!")
        log(f"Van ket o Cloudflare sau {tries} lan thu: {url}", "!")
        return None

    def close(self):
        try:
            self._cm.__exit__(None, None, None)
        except Exception:
            pass


# ════════════════════════════════════════════════════════════
#  PARSE HTML
# ════════════════════════════════════════════════════════════
def collect_story_links(html: str) -> list[str]:
    """Lay danh sach URL truyen tren 1 trang tag (~10 truyen/trang), giu thu tu.

    CHI lay tu tieu de bai trong danh sach chinh (.entry-title a) — tranh vo phai
    link truyen o sidebar (truyen de xuat / moi nhat / xem nhieu) lam sai danh sach.
    """
    soup = BeautifulSoup(html, "html.parser")
    anchors = soup.select(".entry-title a[href]")
    if not anchors:                    # du phong: neu layout doi -> quet ca trang
        anchors = soup.find_all("a", href=True)
    out, seen = [], set()
    for a in anchors:
        href = urljoin(BASE, a["href"].split("#")[0])
        if _STORY_RE.match(href):
            href = href.rstrip("/") + "/"
            if href not in seen:
                seen.add(href)
                out.append(href)
    return out


# Cum tu dac trung cua khoi quang cao/tai tro (loc du phong theo noi dung).
_AD_KEYWORDS = ("好片共享", "搜性站長", "最新推薦", "免費A片", "線上JAV",
                "成人直播", "成人色情", "裸聊", "sponsor")


def _clean_entry_content(soup: BeautifulSoup) -> str:
    """Trich van ban truyen tu div.entry-content.

    Tren sosing.com, van truyen la cac <p> CON TRUC TIEP cua .entry-content;
    con quang cao/tai tro deu nam trong cac <div> (class ngau nhien, .sponsor-block,
    hoac div rong duoc JS do quang cao vao). Vi vay: bo het <div>/<script>/<style>,
    roi chi lay <p> con truc tiep (tru <p class="pages"> la phan trang WordPress).
    """
    ec = soup.select_one(".entry-content") or soup.select_one("article")
    if not ec:
        return ""
    for junk in ec.find_all(["script", "style", "ins", "div", "nav",
                             "figure", "aside", "iframe"]):
        junk.decompose()
    paras = []
    for p in ec.find_all("p", recursive=False):
        cls = " ".join(p.get("class") or [])
        if "pages" in cls:                       # phan trang <p class="pages">
            continue
        t = p.get_text("\n", strip=True)
        if not t:
            continue
        if any(k in t for k in _AD_KEYWORDS):    # loc du phong quang cao dang <p>
            continue
        paras.append(t)
    if not paras:                                # du phong: khong co <p> con truc tiep
        return ec.get_text("\n", strip=True)
    return "\n\n".join(paras)


def parse_story_page(html: str) -> dict:
    """Parse 1 trang truyen -> {title, tags, content, total_pages}."""
    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.select_one("h1.entry-title") or soup.select_one("h1")
    title = title_el.get_text(strip=True) if title_el else ""

    tags = [a.get_text(strip=True) for a in soup.select("a[rel=tag]") if a.get_text(strip=True)]

    content = _clean_entry_content(soup)

    # So trang (chuong) = so lon nhat trong cac .post-page-numbers (+ span.current)
    total = 1
    for el in soup.select(".post-page-numbers"):
        m = re.search(r"\d+", el.get_text(strip=True))
        if m:
            total = max(total, int(m.group(0)))
    # Du phong: doc trong <p class="pages"> "頁: 1 2 3 4"
    pages_el = soup.select_one("p.pages")
    if pages_el:
        nums = [int(n) for n in re.findall(r"\d+", pages_el.get_text())]
        if nums:
            total = max(total, max(nums))
    return {"title": title, "tags": tags, "content": content, "total_pages": total}


# ════════════════════════════════════════════════════════════
#  DICH + CONVERT HAN-VIET
# ════════════════════════════════════════════════════════════
def fix_residual_hanzi(text: str) -> str:
    """Chu Han con sot sau khi dich -> chuyen sang am Han-Viet (fallback catch-all)."""
    if not text or not hv.has_hanzi(text):
        return text
    out = []
    for line in text.split("\n"):
        out.append(hv.hanzi_to_hanviet(line) if hv.has_hanzi(line) else line)
    return "\n".join(out)


def translate_block(text: str) -> str:
    """Dich 1 khoi van ban Trung -> Viet (translate_text tu chia chunk), fix Han sot."""
    if not text.strip():
        return text
    vi, fail = dl.translate_text(text)
    if fail:
        log(f"  {fail} chunk dich loi (giu tam, se fix Han sot)", "!")
    return fix_residual_hanzi(vi)


def translate_title_vi(cn_title: str) -> str:
    """Dich tieu de -> Viet, lam sach cho ten file."""
    vi = dl.translate_title(cn_title)
    vi = fix_residual_hanzi(vi)
    vi = dl.clean_title(vi).strip("_ ")
    return vi or cn_title


def translate_tags_vi(tags: list[str]) -> list[str]:
    out = []
    for t in tags:
        vi = dl.translate_title(t)
        vi = fix_residual_hanzi(vi).strip()
        out.append(vi or t)
    return out


# ════════════════════════════════════════════════════════════
#  GHI FILE
# ════════════════════════════════════════════════════════════
_INVALID_FS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_filename(name: str, maxlen: int = 120) -> str:
    name = _INVALID_FS.sub(" ", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if len(name) > maxlen:
        name = name[:maxlen].rstrip(" .")
    return name or "untitled"


def unique_path(path: Path) -> Path:
    """Tra ve path chua ton tai; neu trung thi them hau to ' (2)', ' (3)'...
    Tranh mat truyen khi nhieu truyen khac noi dung nhung TRUNG TIEU DE."""
    if not path.exists():
        return path
    stem, suf = path.stem, path.suffix
    i = 2
    while True:
        cand = path.with_name(f"{stem} ({i}){suf}")
        if not cand.exists():
            return cand
        i += 1


SEP = "=" * 60


def build_header(vi_title: str, cn_title: str, url: str,
                 tags_vi: list[str], total_pages: int) -> str:
    lines = [
        SEP,
        f"  {vi_title}",
        f"  Tên gốc    : {cn_title}",
        f"  Nguồn      : {url}",
        f"  Thể loại   : {', '.join(tags_vi) if tags_vi else '(không rõ)'}",
        f"  Số chương  : {total_pages}",
        SEP,
        "",
        "",
    ]
    return "\n".join(lines)


def write_story(out_dir: Path, vi_title: str, cn_title: str, url: str,
                tags_vi: list[str], total_pages: int, chapters: list[str],
                name_prefix: str = "", extra_header: str = ""):
    out_dir.mkdir(parents=True, exist_ok=True)
    fname = name_prefix + safe_filename(vi_title) + ".txt"
    path = unique_path(out_dir / fname)
    parts = [build_header(vi_title, cn_title, url, tags_vi, total_pages)]
    if extra_header:
        parts.append(extra_header)
    for i, ch in enumerate(chapters, 1):
        if total_pages > 1:
            parts.append("-" * 60)
            parts.append(f"  [ Phần {i}/{total_pages} ]")
            parts.append("-" * 60)
            parts.append("")
        parts.append(ch.strip())
        parts.append("\n")
    path.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
    return path


def format_registry_info(entry_id: str, entry: dict) -> str:
    """Khoi thong tin ban ghi registry de nhung vao file txt truyen TRUNG."""
    links = entry.get("links", [])
    lines = [
        "-" * 60,
        f"  [TRÙNG] Truyện đã có trong registry — ID {entry_id}",
        f"  Tên gốc Hán  : {entry.get('ten_goc_han', '')}",
        f"  Tên liên quan: {', '.join(entry.get('ten_viet_lien_quan', []))}",
        "  Links:",
        *[f"    - {l}" for l in links],
        "  Bản ghi (JSON):",
        json.dumps(entry, ensure_ascii=False, indent=1),
        "-" * 60,
        "",
    ]
    return "\n".join(lines)


def write_dup_txt(out_dir: Path, vi_title: str, cn_title: str, url: str,
                  entry_id: str, entry: dict) -> Path:
    """Ghi file txt cho truyen TRUNG: ten co '_' o dau, noi dung la thong tin ban ghi."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = unique_path(out_dir / ("_" + safe_filename(vi_title) + ".txt"))
    parts = [
        SEP,
        f"  {vi_title}",
        f"  Tên gốc    : {cn_title}",
        f"  Nguồn mới  : {url}",
        f"  >>> TRÙNG với truyện đã tải (registry ID {entry_id})",
        SEP,
        "",
        format_registry_info(entry_id, entry),
    ]
    path.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
    return path


# ════════════════════════════════════════════════════════════
#  QUY TRINH CHINH
# ════════════════════════════════════════════════════════════
MAX_PAGES = 500   # tran an toan (truyen dai nhat cung khong toi)


def _content_sig(text: str) -> str:
    """Chu ky noi dung (200 ky tu dau, bo khoang trang) de phat hien trang lap lai."""
    return re.sub(r"\s+", "", text)[:200]


def fetch_all_chapters(browser: Browser, story_url: str) -> dict | None:
    """Tai het cac trang (chuong) cua 1 truyen bang cach do TUAN TU /2/, /3/...

    WordPress phan trang bang <!--nextpage-->. Khong dua vao viec parse so trang
    (nguon CDP doi khi thieu khoi phan trang), ma do lien tiep cho den khi:
      - trang khong tai duoc, hoac
      - noi dung rong, hoac
      - noi dung LAP LAI trang 1 (sosing tra ve trang 1 khi so trang vuot gioi han).
    """
    html = browser.get(story_url)
    if not html:
        return None
    info = parse_story_page(html)
    if not info["title"] and not info["content"]:
        log(f"Khong parse duoc truyen: {story_url}", "!")
        return None

    chapters = [info["content"]]
    first_sig = _content_sig(info["content"])
    base = story_url.rstrip("/")
    n = 2
    while n <= MAX_PAGES:
        page_url = f"{base}/{n}/"
        h = browser.get(page_url)
        if not h:                          # thu lai 1 lan truoc khi bo
            h = browser.get(page_url)
        if not h:
            log(f"  trang {n} khong tai duoc -> ket thuc truyen", "!")
            break
        content = parse_story_page(h)["content"]
        if not content.strip():
            break
        if _content_sig(content) == first_sig:   # lap lai trang 1 -> het trang
            break
        chapters.append(content)
        log(f"  -> trang {n} OK ({len(content)} ky tu)")
        n += 1

    info["total_pages"] = len(chapters)
    info["chapters_cn"] = chapters
    return info


def process_story(browser: Browser, story_url: str, do_translate: bool) -> bool:
    log(f"Truyen: {story_url}")
    info = fetch_all_chapters(browser, story_url)
    if not info:
        return False

    cn_title = info["title"] or unquote(urlparse(story_url).path.rstrip("/").split("/")[-1])
    total = info["total_pages"]

    if not do_translate:
        # Luong TACH RIENG: chi luu ban goc (JSON) -> sosing_translate.py dich sau.
        path = save_origin_json(story_url, cn_title, info["tags"], total,
                                info["chapters_cn"])
        log(f"  Da luu goc: {path}", "OK")
        return True

    # ── Check trung TRUOC khi dich (theo ten + van tay noi dung) ──
    vi_title = translate_title_vi(cn_title)
    planned = str(TXT_DIR / (safe_filename(vi_title) + ".txt"))
    is_dup, entry_id, entry = registry_check_and_update(
        cn_title, info["chapters_cn"], story_url, vi_title, translated_path=planned)
    if is_dup:
        path = write_dup_txt(TXT_DIR, vi_title, cn_title, story_url, entry_id, entry)
        log(f"  TRUNG (registry ID {entry_id}) -> them link + luu: {path}", "OK")
        return True

    tags_vi = translate_tags_vi(info["tags"])
    log(f"  Moi (registry ID {entry_id}). Tieu de: {cn_title} -> {vi_title}")
    chapters = []
    for i, cn in enumerate(info["chapters_cn"], 1):
        log(f"  Dich phan {i}/{total} ({len(cn)} ky tu)...")
        chapters.append(translate_block(cn))
    path = write_story(TXT_DIR, vi_title, cn_title, story_url, tags_vi, total, chapters)
    log(f"  Da luu: {path}", "OK")
    return True


def save_origin_json(story_url: str, cn_title: str, tags: list[str],
                     total: int, chapters_cn: list[str]) -> Path:
    """Luu ban goc tieng Trung 1 truyen ra JSON de luong dich xu ly rieng."""
    ORIGIN_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "url": story_url,
        "cn_title": cn_title,
        "tags": tags,
        "total_pages": total,
        "chapters_cn": chapters_cn,
    }
    path = ORIGIN_DIR / (safe_filename(cn_title) + ".json")
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


# ── Resume: nho cac URL truyen da tai xong (txt/_done.json) ──
_PROGRESS_FILE = TXT_DIR / "_done.json"


def _load_done() -> set:
    try:
        import json
        return set(json.loads(_PROGRESS_FILE.read_text(encoding="utf-8")))
    except Exception:
        return set()


def _save_done(done: set):
    try:
        import json
        _PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _PROGRESS_FILE.write_text(json.dumps(sorted(done), ensure_ascii=False, indent=1),
                                  encoding="utf-8")
    except Exception as e:
        log(f"Khong ghi duoc progress: {e}", "!")


def crawl_tag(browser: Browser, tag_url: str, max_tag_pages: int,
              limit: int, do_translate: bool, resume: bool):
    """Duyet cac trang tag, thu thap link truyen, tai va dich tung truyen."""
    story_urls, seen = [], set()
    page = 1
    base = tag_url.rstrip("/") + "/"
    while True:
        page_url = base if page == 1 else f"{base}page/{page}/"
        log(f"Trang tag {page}: {page_url}")
        html = browser.get(page_url)
        if not html:
            break
        links = [u for u in collect_story_links(html) if u not in seen]
        if not links:
            log("Khong con truyen moi -> dung phan trang tag.")
            break
        for u in links:
            seen.add(u)
            story_urls.append(u)
        log(f"  +{len(links)} truyen (tong {len(story_urls)})")
        if limit and len(story_urls) >= limit:
            story_urls = story_urls[:limit]
            break
        if max_tag_pages and page >= max_tag_pages:
            break
        page += 1

    done = _load_done() if resume else set()
    pending = [u for u in story_urls if u not in done]
    log(f"Tong cong {len(story_urls)} truyen | da tai {len(story_urls)-len(pending)} "
        f"| se xu ly {len(pending)}.\n")
    ok = 0
    for idx, url in enumerate(pending, 1):
        log(f"===== [{idx}/{len(pending)}] =====")
        try:
            if process_story(browser, url, do_translate):
                ok += 1
                done.add(url)
                _save_done(done)          # luu ngay de resume an toan khi gian doan
        except Exception as e:
            log(f"Loi xu ly {url}: {e}", "!")
        time.sleep(1.0)
    log(f"\nHoan tat: {ok}/{len(pending)} truyen luu thanh cong.", "OK")


def main():
    ap = argparse.ArgumentParser(description="Tai + dich truyen tu sosing.com")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--tag", help="So tag, vd 13 (=> https://sosing.com/tag/13/)")
    g.add_argument("--url", help="URL trang tag day du")
    g.add_argument("--story", help="URL 1 truyen cu the (bo qua duyet tag)")
    ap.add_argument("--max-tag-pages", type=int, default=0,
                    help="Gioi han so trang tag (0 = het cac trang)")
    ap.add_argument("--limit", type=int, default=0,
                    help="Gioi han so truyen xu ly (0 = tat ca)")
    ap.add_argument("--engine", choices=["free", "caiyun", "google", "gemini"],
                    default="free", help="Engine dich (mac dinh free: Caiyun->Google)")
    ap.add_argument("--gemini-key", default="", help="GEMINI_API_KEY khi --engine gemini")
    ap.add_argument("--no-translate", action="store_true",
                    help="LUONG TACH RIENG: chi lay truyen, luu ban goc JSON vao "
                         "txt/origin/. Chay sosing_translate.py de dich song song.")
    ap.add_argument("--headed", action="store_true", default=True,
                    help="Hien cua so Chrome (mac dinh bat — de vuot Cloudflare on dinh)")
    ap.add_argument("--headless", dest="headed", action="store_false",
                    help="Chay an (co the bi Cloudflare chan hon)")
    ap.add_argument("--no-resume", action="store_true",
                    help="Khong bo qua truyen da tai (tai lai tu dau)")
    ap.add_argument("--profile", default=str(THIS_DIR / ".chrome_profile"),
                    help="Thu muc profile Chrome (luu cookie cf_clearance de vuot "
                         "Cloudflare 1 lan roi dung lai). '' = khong dung profile.")
    ap.add_argument("--no-click", action="store_true",
                    help="KHONG dung chuot that de bam Turnstile (chi dua vao CDP + "
                         "mo lai). LUU Y: da test -> sosing.com KHONG vuot duoc o che "
                         "do nay; chi huu ich cho cac site CF de hon.")
    args = ap.parse_args()

    dl.ENGINE = args.engine
    if args.engine == "gemini":
        dl.GEMINI_API_KEY = args.gemini_key or os.environ.get("GEMINI_API_KEY", "")
        if not dl.GEMINI_API_KEY:
            log("Thieu --gemini-key / GEMINI_API_KEY", "!")
            sys.exit(1)

    do_translate = not args.no_translate
    if do_translate and not dl.TRANSLATE_AVAILABLE and args.engine != "gemini":
        log("Thu vien 'translators' chua co. Chay: py -m pip install translators", "!")
        sys.exit(1)

    log(f"Engine dich: {dl.ENGINE} | Dich: {do_translate} | Output: {TXT_DIR}")
    browser = Browser(headed=args.headed, profile_dir=(args.profile or None),
                      no_click=args.no_click)
    try:
        if args.story:
            process_story(browser, args.story.rstrip("/") + "/", do_translate)
        else:
            tag_url = args.url or f"{BASE}/tag/{args.tag}/"
            crawl_tag(browser, tag_url, args.max_tag_pages, args.limit,
                      do_translate, resume=not args.no_resume)
    finally:
        browser.close()


if __name__ == "__main__":
    main()
