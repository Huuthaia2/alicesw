#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AliceSW Translate Watcher
=========================
Tach RIENG khau DICH ra khoi khau TAI. Theo doi thu muc origin/ (ban goc tieng
Trung do alicesw_downloader.py --no-translate tao ra), dich tung truyen sang
tieng Viet -> luu vao translated/.  Chay SONG SONG voi tool tai (2 cua so).

Pipeline 3 tang (giong txt_to_mp3 watcher):
    alicesw_downloader.py --no-translate   -> downloaded/origin/*.txt
    alicesw_translate.py  (file nay)        -> downloaded/translated/*.txt
    txt_to_mp3.py                           -> downloaded/translated/mp3/*.mp3

Dac diem:
  - Tai dung TOAN BO logic dich cua alicesw_downloader (engine Caiyun->Google
    tu xoay moi chunk, retry, chong block) qua import -> khong nhan doi code.
  - Dich SONG SONG nhieu chuong (--translate-workers, mac dinh 3).
  - Resume tung chuong: moi chuong dich xong cache rieng -> gian doan van tiep tuc.
  - Ghi state THONG NHAT (_translated_progress.json key novel_id) cho gate TTS + _report.py.
  - Quy uoc: chua DONE thi khong giu file .txt (cache van giu de chay lai).
  - File origin dang ghi do (chua on dinh) thi bo qua, doi lan quet sau.

Cach dung:
  py -u alicesw_translate.py                      # quet downloaded/origin -> downloaded/translated
  py -u alicesw_translate.py --translate-workers 3
  py -u alicesw_translate.py --once               # chay 1 lan roi thoat
  py -u alicesw_translate.py --engine gemini --gemini-key XXX
"""
import os
os.environ.setdefault("PYTHONUNBUFFERED", "1")
import re
import sys
import json
import time
import argparse
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

# ── Tai dung logic dich + tien ich cua tool tai ──
import alicesw_downloader as dl
import hanviet as hv   # chuyen ten pinyin -> Han Viet (catch-all)
import _vpn_lock

TRANSLATE_WORKERS = 1   # so chuong dich song song BEN TRONG 1 file (giam xuong 1 khi dung file-workers)
FILE_WORKERS      = 3   # so file dich SONG SONG (mac dinh 3 file cung luc)
_log_file_lock    = threading.Lock()

# Catch-all ten rieng: CHI cum 2+ tu hoa lien tiep (vd "Chen Tian", "Liu Xuemei").
# Tranh dung tu don trong van xuoi tieng Viet -> "Anna"/"Lisa" (1 tu) khong bi nham.
_NAME_RE_MULTI = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b")

def convert_names_safe(text: str) -> int:
    """Chuyen cac cum 2+ tu pinyin viet hoa -> Han Viet (sua text qua bien tham chieu khong duoc,
    nen tra ve (text_moi, so_cum_doi) qua closure). Tra ve so cum da doi; text_moi luu o _last[0]."""
    n = [0]
    def _repl(m):
        original = m.group(0)
        words = original.split()
        # Tat ca tu phai tach duoc pinyin va KHONG tu nao thuoc KEEP_AS_IS (Martin, Yuko...)
        if any(w in hv.KEEP_AS_IS for w in words):
            return original
        if not all(hv._segment(w.lower()) for w in words):
            return original
        converted = " ".join(hv._convert_word(w) for w in words)
        if converted != original:
            n[0] += 1
        return converted
    convert_names_safe._last = _NAME_RE_MULTI.sub(_repl, text)
    return n[0]

# ── Glossary: ten rieng pinyin -> Han Viet (xem glossary.json + _scan_names.py) ──
_GLOSSARY_FILE = Path(__file__).parent / "glossary.json"
_glossary: dict = {}

def _load_glossary():
    global _glossary
    if _GLOSSARY_FILE.exists():
        try:
            _glossary = json.loads(_GLOSSARY_FILE.read_text(encoding="utf-8"))
        except Exception:
            _glossary = {}

def apply_glossary(text: str) -> str:
    """Thay the ten rieng pinyin bang Han Viet theo glossary.json."""
    if not _glossary or not text:
        return text
    for src, dst in _glossary.items():
        text = text.replace(src, dst)
    return text

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SCAN_INTERVAL   = 3.0    # giay: bao lau quet 1 lan
FILE_STABLE_SEC = 3.0    # file origin phai "yen" >= 3s moi xu ly (tranh doc do tai)


# ════════════════════════════════════════════════════════════
#  PARSE FILE ORIGIN (ban goc gop) -> metadata + danh sach chuong
# ════════════════════════════════════════════════════════════
def parse_origin_header(text: str) -> dict | None:
    """
    Doc header file origin (do write_full_book ghi, separators=True):
        ============================================================
          <title>
          Tác giả    : <author>
          Nguồn      : <url .../novel/<id>.html>
          Tag        : ... (optional)
          Chương     : <total>
          Tình trạng : ... (optional)
        ============================================================
    Tra ve {title, author, url, novel_id, total, tags_vi, status_vi} hoac None neu khong hop le.
    """
    head = text[:1500]
    
    url = None
    author = "Khong ro"
    total = 0
    tags_vi = []
    status_vi = ""
    
    for line in head.splitlines():
        line_strip = line.strip()
        if not line_strip or ":" not in line_strip:
            continue
        parts = line_strip.split(":", 1)
        key = parts[0].strip().lower()
        val = parts[1].strip()
        
        # Check URL/Nguồn
        if "ngu" in key:
            url = val
        # Check Tác giả
        elif "tác" in key or "tac" in key:
            author = val
        # Check Chương
        elif "chư" in key or "chu" in key:
            try:
                total = int(val)
            except ValueError:
                pass
        # Check Tag
        elif "tag" in key:
            tags_vi = [t.strip() for t in val.split(",")]
        # Check Tình trạng
        elif "tình" in key or "tinh" in key:
            status_vi = val

    if not url:
        return None
        
    m_id = re.search(r"/novel/(\d+)", url)
    if not m_id:
        return None

    # Get title: it should be the line that has no colon, is not empty, is not all "=", and is before any metadata lines
    title = "Khong ro"
    for line in head.splitlines():
        line_strip = line.strip()
        if not line_strip:
            continue
        if set(line_strip) == {"="}:
            continue
        if ":" in line_strip:
            # Metadata block starts, so the title must have been before this
            break
        title = line_strip
        break

    return {
        "title":      title,
        "author":     author,
        "url":        url,
        "novel_id":   m_id.group(1),
        "total":      total,
        "tags_vi":    tags_vi,
        "status_vi":  status_vi,
    }


def split_origin_chapters(text: str) -> list:
    """
    Tach file origin gop thanh danh sach (ch_title, content).
    Phan cach GIUA chuong = dong '─' x50; phan cach trong tieu de chuong = '─' x40.
    content giu nguyen cac doan cach nhau "\\n\\n".
    """
    lines = text.splitlines()
    # Bo header: ket thuc o dong toan '=' lan thu 2
    eq_idx = [i for i, l in enumerate(lines) if l.strip() and set(l.strip()) == {"="}]
    body_start = (eq_idx[1] + 1) if len(eq_idx) >= 2 else 0
    body = "\n".join(lines[body_start:])

    chapters = []
    for block in re.split(r"─{50,}", body):   # tach theo separator giua chuong (>=50)
        block = block.strip()
        if not block:
            continue
        parts = re.split(r"─{40,}", block, maxsplit=1)   # tach tieu de | noi dung
        if len(parts) == 2:
            ch_title = parts[0].strip()
            content  = parts[1].strip()
        else:
            head_line, _, rest = block.partition("\n")
            ch_title = head_line.strip()
            content  = rest.strip()
        chapters.append((ch_title, content))
    return chapters


# ════════════════════════════════════════════════════════════
#  TRANG THAI (nho file origin nao da dich xong)
# ════════════════════════════════════════════════════════════
def load_progress(trans_dir: Path) -> dict:
    p = trans_dir / "_translate_progress.json"
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("done", {})
                data.setdefault("failed", {})
                data.setdefault("last_ip", "")
                return data
        except Exception:
            pass
    return {"done": {}, "failed": {}, "last_ip": ""}


def save_progress(trans_dir: Path, data: dict):
    try:
        (trans_dir / "_translate_progress.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"  [!] Khong luu duoc trang thai: {e}")


def update_unified_translated(out_dir: Path, novel_id: str, trans_name: str, ok: bool, reason: str | dict = ""):
    """Cap nhat state THONG NHAT (key novel_id) cho gate TTS + _report.py:
      out_dir/_translated_progress.json  {novel_id: ten_file.txt}
      out_dir/_translated_failed.json    {novel_id: ly_do}
    Chi ghi 2 file 'translated' (KHONG dung file 'origin' cua tool tai -> khong tranh chap khi
    chay song song). Dung cung dinh dang/duong dan voi alicesw_downloader."""
    pp = dl._state_paths(out_dir)
    def _load(p):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}
    done = _load(pp["trans_done"])
    fail = _load(pp["trans_fail"])
    if ok:
        done[novel_id] = trans_name
        fail.pop(novel_id, None)
    else:
        fail[novel_id] = reason or "con doan dich loi / chu Han sot"
        done.pop(novel_id, None)
    try:
        pp["trans_done"].write_text(json.dumps(done, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        pp["trans_fail"].write_text(json.dumps(fail, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    except Exception as e:
        print(f"  [!] Khong luu duoc _translated_progress: {e}")


def sync_progress_files(origin_dir: Path, trans_dir: Path):
    """
    Dong bo va lam sach:
      1. trans_dir/../_translated_progress.json
      2. trans_dir/../_translated_failed.json
      3. trans_dir/_translate_progress.json (dung de watch/check needs_processing)
    dua tren cac file thuc te dang co tren dia.
    """
    print(f"\n[~] Dang tu dong dong bo hoa tien do dich thuat...")
    out_dir = trans_dir.parent
    pp = dl._state_paths(out_dir)
    
    def _load_json(p, default):
        if p.exists():
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                return d if isinstance(d, dict) else default
            except Exception:
                pass
        return default
        
    trans_done = _load_json(pp["trans_done"], {})
    trans_fail = _load_json(pp["trans_fail"], {})
    
    translate_progress = _load_json(trans_dir / "_translate_progress.json", {"done": {}, "failed": {}, "last_ip": ""})
    done_trans = translate_progress.setdefault("done", {})
    failed_trans = translate_progress.setdefault("failed", {})

    # Xoa cac record trong trans_done neu file dich khong con ton tai
    stale_done_ids = []
    for nid, fname in list(trans_done.items()):
        if not (trans_dir / fname).exists():
            stale_done_ids.append(nid)
            trans_done.pop(nid)
    if stale_done_ids:
        print(f"  [-] Xoa {len(stale_done_ids)} muc khoi _translated_progress.json do file dich bi mat.")

    # Quet thu muc translated/
    txt_files = sorted(f for f in trans_dir.glob("*.txt") if not f.name.startswith("_"))
    
    added_done = 0
    added_trans = 0

    for txt_file in txt_files:
        # Lay novel_id tu header
        novel_id = None
        # Uu tien lay tu trans_done de tranh phai mo doc file
        for nid, fname in trans_done.items():
            if fname == txt_file.name:
                novel_id = nid
                break
                
        if not novel_id:
            try:
                with open(txt_file, "r", encoding="utf-8", errors="ignore") as f:
                    for _ in range(30):
                        line = f.readline()
                        if not line:
                            break
                        line_strip = line.strip()
                        if "Nguồn" in line_strip or "Nguon" in line_strip:
                            parts = line_strip.split(":", 1)
                            if len(parts) > 1:
                                url = parts[1].strip()
                                match = re.search(r"novel/(\d+)", url)
                                if match:
                                    novel_id = match.group(1)
                                    break
            except Exception:
                pass
                
        if novel_id:
            if novel_id not in trans_done:
                trans_done[novel_id] = txt_file.name
                trans_fail.pop(novel_id, None)
                added_done += 1
                
        # Tim file origin tuong ung
        origin_name = None
        stem = txt_file.stem
        if stem.endswith("_end"):
            candidate = stem.replace("_end", "") + "_origin_end.txt"
        else:
            candidate = stem + "_origin.txt"
            
        origin_path = origin_dir / candidate
        if origin_path.exists():
            origin_name = candidate
        else:
            clean_txt_name = txt_file.name.replace("_end.txt", ".txt")
            for orig in origin_dir.glob("*.txt"):
                if orig.name.startswith("_"):
                    continue
                clean_orig_name = orig.name.replace("_origin", "").replace("_end", "").replace("_origin_end", "")
                if clean_orig_name == clean_txt_name:
                    origin_name = orig.name
                    origin_path = orig
                    break
                    
        if origin_name and origin_path:
            st = origin_path.stat()
            sig = {"size": st.st_size, "mtime": int(st.st_mtime), "out": txt_file.name}
            
            rec = done_trans.get(origin_name)
            if not rec or rec.get("size") != sig["size"] or rec.get("mtime") != sig["mtime"] or rec.get("out") != sig["out"]:
                done_trans[origin_name] = sig
                failed_trans.pop(origin_name, None)
                added_trans += 1

    # Clear bat ky record done nao neu file dich hoac file origin khong con ton tai
    stale_origins = []
    for orig_name, rec in list(done_trans.items()):
        out_name = rec.get("out", "")
        if not (origin_dir / orig_name).exists() or not (trans_dir / out_name).exists():
            stale_origins.append(orig_name)
            done_trans.pop(orig_name)
    if stale_origins:
        print(f"  [-] Xoa {len(stale_origins)} entry loi thoi trong _translate_progress.json.")

    try:
        pp["trans_done"].write_text(json.dumps(trans_done, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        pp["trans_fail"].write_text(json.dumps(trans_fail, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        (trans_dir / "_translate_progress.json").write_text(json.dumps(translate_progress, ensure_ascii=False, indent=2), encoding="utf-8")
        if added_done > 0 or added_trans > 0 or stale_done_ids or stale_origins:
            print(f"  [OK] Dong bo xong: +{added_done} vao _translated_progress.json, +{added_trans} vao _translate_progress.json")
    except Exception as e:
        print(f"  [!] Loi khi ghi file dong bo: {e}")


def file_sig(p: Path) -> dict:
    st = p.stat()
    return {"size": st.st_size, "mtime": int(st.st_mtime)}


def needs_processing(origin: Path, trans_dir: Path, progress: dict, force_retry_failed: bool = False) -> bool:
    """Can dich neu: chua tung dich, file origin da sua, hoac file translated bi xoa, hoac force_retry_failed cho file loi."""
    # 1. Neu nam trong done: so sanh signature
    done_rec = progress.get("done", {}).get(origin.name)
    if done_rec:
        sig = file_sig(origin)
        sig_changed = (done_rec.get("size") != sig["size"] or done_rec.get("mtime") != sig["mtime"])
        out_name = done_rec.get("out")
        out_ok = bool(out_name) and (trans_dir / out_name).exists()
        if out_ok and not sig_changed:
            return False
        return True

    # 2. Neu nam trong failed: retry neu co co force_retry_failed hoac file origin thay doi
    fail_rec = progress.get("failed", {}).get(origin.name)
    if fail_rec:
        sig = file_sig(origin)
        sig_changed = (fail_rec.get("size") != sig["size"] or fail_rec.get("mtime") != sig["mtime"])
        if force_retry_failed or sig_changed:
            return True
        return False

    # 3. Chua tung dich (khong co trong done va failed)
    return True


# ════════════════════════════════════════════════════════════
#  DICH 1 FILE ORIGIN -> FILE TRANSLATED
# ════════════════════════════════════════════════════════════
def _han_ratio(text: str) -> float:
    han = sum(1 for c in text if "一" <= c <= "鿿")
    return han / max(len(text), 1)


def _log_han_residual_details(file_name: str, novel_id: str, chapter_idx: int, chapter_title: str, para_details: list):
    log_file = Path("downloaded/_han_residual_details.log")
    try:
        bad_paras = []
        for idx, (para, eng, has_err) in enumerate(para_details, 1):
            if not para.strip():
                continue
            han_c = sum(1 for c in para if "一" <= c <= "鿿")
            if han_c > 0:
                ratio = han_c / len(para)
                bad_paras.append((idx, ratio, para.strip(), eng, has_err))
        
        if not bad_paras:
            return

        lines = []
        lines.append("=" * 80)
        lines.append(f"File    : {file_name}")
        lines.append(f"Novel ID: {novel_id}")
        lines.append(f"Chuong  : {chapter_idx} - {chapter_title}")
        lines.append("-" * 80)
        for idx, ratio, text, eng, has_err in bad_paras:
            err_tag = "[LOI]" if has_err else "[SOT]"
            lines.append(f"[Doan {idx:3d}] ({ratio*100:5.1f}% Han) {err_tag}[{eng}]: {text}")
        lines.append("\n")
        
        with _log_file_lock:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
    except Exception:
        pass


def process_origin_file(origin: Path, trans_dir: Path, cache_root: Path) -> tuple:
    """
    Dich 1 file origin. Tra ve (ok: bool, out_name: str | None).
    ok=True khi dich het, khong con chunk loi / chu Han sot.
    """
    text = origin.read_text(encoding="utf-8", errors="replace")
    meta = parse_origin_header(text)
    if not meta:
        print(f"  [bo qua] {origin.name}: khong doc duoc header (thieu 'Nguon').")
        return False, None

    chapters = split_origin_chapters(text)
    if not chapters:
        print(f"  [bo qua] {origin.name}: khong tach duoc chuong nao.")
        return False, None

    novel_id = meta["novel_id"]
    total = meta["total"] or len(chapters)
    cache_dir = cache_root / novel_id
    cache_dir.mkdir(parents=True, exist_ok=True)

    # ── Xác định tiêu đề tiếng Việt chuẩn trực tiếp từ tên file origin ──
    # Định dạng file origin: <Tiêu Đề Việt>+<Số Chương> Chuong_origin[_end].txt
    match = re.match(r"^(.*?)\+\d+\s+Chuong_origin(_end)?\.txt$", origin.name, re.IGNORECASE)
    if match:
        title = match.group(1).strip()
    else:
        # Fallback nếu tên file không đúng định dạng chuẩn
        title_cache = cache_dir / "title_vi.txt"
        if title_cache.exists() and title_cache.stat().st_size > 0:
            title_vi = title_cache.read_text(encoding="utf-8").strip()
        else:
            title_vi = dl.translate_title(meta["title"])
            if title_vi and title_vi != meta["title"]:
                title_cache.write_text(title_vi, encoding="utf-8")
        title = dl.clean_title(dl.sanitize_filename(title_vi or meta["title"]))

    _end = "_end" if "_origin_end" in origin.name else ""
    trans_file = trans_dir / f"{title}+{total} Chuong{_end}.txt"

    print(f"\n[>] {origin.name}")
    print(f"    -> {trans_file.name}  ({len(chapters)} chuong)")

    dl._engine_stats = {}   # reset dem engine cho truyen nay
    trans_texts = {}
    failed_chunks = 0
    residual_details = []
    state_lock = threading.Lock()

    # ── Pha 1: doc cache, gom chuong CAN dich ──
    todo = []   # [(i, ch_title, content, cache_trans), ...]
    for i, (ch_title, content) in enumerate(chapters, 1):
        cache_trans = cache_dir / f"{i:06d}_trans.txt"
        if cache_trans.exists() and cache_trans.stat().st_size > 20:
            cached = cache_trans.read_text(encoding="utf-8")
            if _han_ratio(cached) < 0.05:
                trans_texts[i] = cached
                continue
        todo.append((i, ch_title, content, cache_trans))

    ntodo = len(todo)
    if trans_texts:
        dl._log(f"(cache) {len(trans_texts)}/{len(chapters)} chuong da dich.")

    def _translate_one(arg):
        nonlocal failed_chunks
        i, ch_title, content, cache_trans = arg
        vi_title = dl.translate_title(ch_title)
        translated, fail_count, para_details = dl.translate_text(content, return_details=True)   # tra ve (text, so_chunk_fail, details)
        vi_paras = translated.split("\n\n")
        trans_text = dl.format_chapter_text(vi_title, vi_paras, separators=False)
        han = _han_ratio(trans_text)
        with state_lock:
            trans_texts[i] = trans_text
            
            # Thu thap cac doan co chua chu Han hoac loi
            bad_paras_in_ch = []
            for idx, (para, eng, has_err) in enumerate(para_details, 1):
                if not para.strip():
                    continue
                han_c = sum(1 for c in para if "一" <= c <= "鿿")
                if han_c > 0 or has_err:
                    ratio_ch = han_c / len(para)
                    bad_paras_in_ch.append({
                        "chapter": vi_title,
                        "para_idx": idx,
                        "han_ratio": ratio_ch,
                        "text": para.strip(),
                        "engine": eng,
                        "has_err": has_err
                    })
            if bad_paras_in_ch:
                residual_details.extend(bad_paras_in_ch)

            if fail_count > 0 or han >= 0.05:
                failed_chunks += max(fail_count, 1)
                dl._log(f"[{i:3d}/{len(chapters)}] Con {han*100:.0f}% Han sot -> khong cache, dich lai lan sau", "warn")
                _log_han_residual_details(origin.name, novel_id, i, vi_title, para_details)
            else:
                cache_trans.write_text(trans_text, encoding="utf-8")
                dl._log(f"[{i:3d}/{len(chapters)}] Dich xong: {vi_title[:50]}", "ok")

    # ── Pha 2: dich song song (chuong dau khoi dong tuan tu de init session engine) ──
    if todo:
        if TRANSLATE_WORKERS > 1 and ntodo > 1:
            dl._log(f"Dich {ntodo} chuong ({TRANSLATE_WORKERS} luong song song)...")
            _translate_one(todo[0])
            with ThreadPoolExecutor(max_workers=TRANSLATE_WORKERS) as pool:
                list(pool.map(_translate_one, todo[1:]))
        else:
            dl._log(f"Dich {ntodo} chuong (tuan tu)...")
            for arg in todo:
                _translate_one(arg)

    # ── Ghi file ban dich (tai dung write_full_book cua tool tai) ──
    info = {
        "title": title,
        "author": meta["author"],
        "novel_url": meta["url"],
        "tags_vi": meta.get("tags_vi", []),
        "status_vi": meta.get("status_vi", ""),
    }
    if dl._engine_stats:
        tot = sum(dl._engine_stats.values())
        engine_label = " / ".join(
            f"{e.capitalize()} {round(n*100/tot)}%"
            for e, n in sorted(dl._engine_stats.items(), key=lambda x: -x[1]))
    else:
        engine_label = "Caiyun -> Google"

    dl.cleanup_old_count_files(trans_dir, title, trans_file.name)
    dl.write_full_book(trans_file, info, trans_texts, total, engine=engine_label, separators=True)

    # ── Fix ten rieng: glossary (ban duyet tay) truoc, roi convert_names catch-all (cum 2+ tu) ──
    _load_glossary()
    raw = trans_file.read_text(encoding="utf-8", errors="ignore")
    n_gloss = sum(raw.count(k) for k in _glossary if k in raw) if _glossary else 0
    fixed = apply_glossary(raw) if _glossary else raw
    n_auto = convert_names_safe(fixed)        # tu dong cho ten Trung con sot
    fixed = convert_names_safe._last
    if fixed != raw:
        trans_file.write_text(fixed, encoding="utf-8")
        dl._log(f"Fix ten rieng: glossary {n_gloss} lan, tu dong {n_auto} cum", "ok")

    # ── Kiem tra chu Han con sot ──
    full = trans_file.read_text(encoding="utf-8", errors="ignore")
    ratio = _han_ratio(full)
    size_mb = trans_file.stat().st_size / 1024 / 1024
    out_dir = trans_dir.parent   # downloaded/ -> noi chua state thong nhat (cho gate TTS + _report)
    if failed_chunks > 0 or ratio >= 0.05:
        dl._log(f"Ban dich: {trans_file.name} ({size_mb:.2f} MB) [{engine_label}] "
                f"- con loi ({failed_chunks} chunk, {ratio*100:.1f}% Han) -> chay lai se dich not", "warn")
        # Quy uoc: chua DONE -> khong giu file .txt (tranh ban thieu chuong / con Han); cache van giu.
        try:
            trans_file.unlink()
        except Exception:
            pass
            
        # Gioi han so luong chi tiet loi de tranh file JSON qua nang (>50)
        max_details = 50
        truncated_details = residual_details[:max_details]
        
        reason_dict = {
            "reason": f"{failed_chunks} chunk loi / {ratio*100:.1f}% Han sot",
            "han_details": [
                f"[{item['chapter']} - Doan {item['para_idx']}] ({item['han_ratio']*100:.1f}% Han) "
                f"[{item['engine']}{' - LOI' if item['has_err'] else ''}]: {item['text']}"
                for item in truncated_details
            ]
        }
        if len(residual_details) > max_details:
            reason_dict["han_details"].append(f"... va con {len(residual_details) - max_details} doan khac.")
            
        update_unified_translated(out_dir, novel_id, trans_file.name, ok=False, reason=reason_dict)
        return False, trans_file.name
    dl._log(f"Ban dich: {trans_file.name} ({size_mb:.2f} MB) [{engine_label}]", "ok")
    update_unified_translated(out_dir, novel_id, trans_file.name, ok=True)
    return True, trans_file.name


# ════════════════════════════════════════════════════════════
#  VONG QUET
# ════════════════════════════════════════════════════════════
def scan_once(origin_dir: Path, trans_dir: Path, cache_root: Path, progress: dict,
              file_workers: int = 1, force_retry_failed: bool = False, reverse: bool = False) -> int:
    done = progress["done"]
    processed = 0
    now = time.time()
    prog_lock = threading.Lock()

    # Uu tien file NHO truoc -> co thanh qua som; --nguoc -> file TO truoc
    files = sorted(origin_dir.glob("*.txt"), key=lambda p: p.stat().st_size, reverse=reverse)
    pending = []
    skipped_done = 0
    skipped_failed = 0
    for origin in files:
        if origin.name.startswith("_"):
            continue
        if not needs_processing(origin, trans_dir, progress, force_retry_failed):
            if origin.name in progress.get("done", {}):
                skipped_done += 1
            elif origin.name in progress.get("failed", {}):
                skipped_failed += 1
            continue
        if now - origin.stat().st_mtime < FILE_STABLE_SEC:
            print(f"  [cho] {origin.name} vua thay doi, doi on dinh...", end="\r")
            continue
        pending.append(origin)

    total_files = len(files)
    dl._log(f"Quet thu muc: tim thay {total_files} file origin.")
    dl._log(f"Da bo qua: {skipped_done} file da dich xong, {skipped_failed} file loi truoc do (cho IP moi).")
    dl._log(f"Hang doi dich: {len(pending)} file can xu ly.")
    if pending:
        dl._log("Top 3 file nho nhat chuan bi dich:")
        for idx, origin in enumerate(pending[:3], 1):
            dl._log(f"  {idx}. {origin.name} ({origin.stat().st_size/1024:.2f} KB)")

    def _process_one(origin: Path):
        nonlocal processed
        try:
            ok, out_name = process_origin_file(origin, trans_dir, cache_root)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            print(f"  [!] Loi dich {origin.name}: {str(e)[:150]}")
            return
        with prog_lock:
            if ok and out_name:
                done[origin.name] = {**file_sig(origin), "out": out_name}
                progress.setdefault("failed", {}).pop(origin.name, None)
                save_progress(trans_dir, progress)
                processed += 1
            elif out_name:
                progress.setdefault("failed", {})[origin.name] = {
                    **file_sig(origin),
                    "out": out_name,
                    "failed_at": int(time.time())
                }
                save_progress(trans_dir, progress)

    if file_workers > 1 and len(pending) > 1:
        dl._log(f"Dich {len(pending)} file ({file_workers} file song song)...")
        with ThreadPoolExecutor(max_workers=file_workers) as pool:
            list(pool.map(_process_one, pending))
    else:
        for origin in pending:
            _process_one(origin)

    return processed


def _get_ip_info() -> tuple:
    """Lay IP public hien tai va ma quoc gia. Tra ve ('', '') neu loi."""
    import requests
    try:
        r = requests.get("https://www.cloudflare.com/cdn-cgi/trace", timeout=8)
        ip = ""
        loc = ""
        for ln in r.text.splitlines():
            if ln.startswith("ip="):
                ip = ln[3:].strip()
            elif ln.startswith("loc="):
                loc = ln[4:].strip()
        return ip, loc
    except Exception:
        pass
    return "", ""


def main():
    global TRANSLATE_WORKERS
    parser = argparse.ArgumentParser(
        description="Tool: dich tat ca file origin (tieng Trung) trong thu muc -> translated (tieng Viet).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--dir", default="downloaded/origin",
                        help="Thu muc chua file origin can dich (mac dinh: downloaded/origin)")
    parser.add_argument("--out", default="",
                        help="Thu muc luu ban dich (mac dinh: <dir>/../translated)")
    parser.add_argument("--engine", choices=["free", "gemini", "caiyun", "google"], default="free",
                        help="Engine dich: free (Caiyun->Google) | gemini (can API key) | caiyun (chi dung Caiyun) | google (chi dung Google Dịch)")
    parser.add_argument("--gemini-key", default="",
                        help="Gemini API key (hoac bien moi truong GEMINI_API_KEY)")
    parser.add_argument("--gemini-model", default=dl.GEMINI_MODEL,
                        help=f"Model Gemini (mac dinh: {dl.GEMINI_MODEL})")
    parser.add_argument("--translate-workers", dest="translate_workers", type=int, default=TRANSLATE_WORKERS,
                        help=f"So chuong dich song song BEN TRONG 1 file (mac dinh {TRANSLATE_WORKERS}). "
                             f"Nen giu = 1 khi dung --file-workers.")
    parser.add_argument("--file-workers", dest="file_workers", type=int, default=FILE_WORKERS,
                        help=f"So FILE dich SONG SONG (mac dinh {FILE_WORKERS}). "
                             f"Moi file dung engine rieng, khong tranh chap.")
    parser.add_argument("--nguoc", action="store_true", default=False,
                        help="Dao thu tu: dich file TO truoc (mac dinh: file NHO truoc)")
    parser.add_argument("--once", action="store_true", default=False,
                        help="Quet 1 lan roi thoat (mac dinh: chay 1 lan, flag nay giu lai de tuong thich)")
    parser.add_argument("--retry-failed", dest="retry_failed", action="store_true", default=False,
                        help="Buoc retry TAT CA file trong danh sach failed, bat ke IP co doi khong.")
    parser.add_argument("--vpn", choices=["protonvpn", "warp", "none", "auto"], default="auto",
                        help="Chon loai VPN de tu dong doi IP khi bi block (protonvpn | warp | none | auto, mac dinh: auto)")
    args = parser.parse_args()

    TRANSLATE_WORKERS = max(1, args.translate_workers)
    file_workers = max(1, args.file_workers)

    # ── Cau hinh engine dich tren module tool tai (translate_text doc cac global nay) ──
    dl.ENGINE = args.engine
    dl.GEMINI_MODEL = args.gemini_model
    dl.GEMINI_API_KEY = args.gemini_key or os.environ.get("GEMINI_API_KEY", "")

    # Determine auto VPN type
    is_warp_available = os.path.exists(r"C:\Program Files\Cloudflare\Cloudflare WARP\warp-cli.exe")
    is_proton_available = bool(dl.PROTON_CLI or dl.PROTON_SERVICE)
    
    if args.vpn == "auto":
        if is_proton_available:
            dl.VPN_TYPE = "protonvpn"
        elif is_warp_available:
            dl.VPN_TYPE = "warp"
        else:
            dl.VPN_TYPE = "none"
    else:
        dl.VPN_TYPE = args.vpn

    if args.engine == "gemini" and not dl.GEMINI_API_KEY:
        print("[!] Engine gemini can API key (--gemini-key XXX hoac set GEMINI_API_KEY).")
        sys.exit(1)
    if args.engine in ("free", "caiyun", "google") and not dl.TRANSLATE_AVAILABLE:
        print("[!] Khong co thu vien 'translators'. Chay: py -m pip install translators")
        sys.exit(1)

    origin_dir = Path(args.dir)
    if not origin_dir.exists():
        print(f"[!] Khong thay thu muc origin: {origin_dir.resolve()}")
        sys.exit(1)
    trans_dir  = Path(args.out) if args.out else (origin_dir.parent / "translated")
    trans_dir.mkdir(parents=True, exist_ok=True)
    cache_root = origin_dir.parent / ".cache_translate"   # cache dich RIENG (khong dung chung voi tool tai)
    cache_root.mkdir(parents=True, exist_ok=True)

    # Dong bo hoa tien do khi bat dau chay script
    sync_progress_files(origin_dir, trans_dir)

    progress = load_progress(trans_dir)

    # Truncate detail log file at startup
    try:
        Path("downloaded/_han_residual_details.log").write_text("", encoding="utf-8")
    except Exception:
        pass

    print(f"{'='*60}")
    print("  AliceSW Translate Tool")
    print(f"  Doc origin : {origin_dir.resolve()}")
    print(f"  Luu dich   : {trans_dir.resolve()}")
    if args.engine == "gemini":
        eng = f"Gemini ({dl.GEMINI_MODEL})"
    elif args.engine == "caiyun":
        eng = "Caiyun Only"
    elif args.engine == "google":
        eng = "Google Only"
    else:
        eng = "Caiyun -> Google"
    print(f"  Engine     : {eng}")
    print(f"  Dich       : {file_workers} file song song  x  {TRANSLATE_WORKERS} chuong/file")
    print(f"  VPN xoay IP: {f'BAT [{dl.VPN_TYPE}]' if dl.VPN_TYPE != 'none' else 'TAT'}")
    print(f"  Da dich    : {len(progress['done'])} truyen")
    print(f"{'='*60}")

    # ── Kiem tra xem co IP fake moi khong (tranh ip that VN) ──
    last_ip = progress.get("last_ip", "")
    current_ip, current_loc = _get_ip_info()

    force_retry_failed = False

    # --retry-failed: buoc retry thu cong, bo qua toan bo logic IP
    if args.retry_failed:
        force_retry_failed = True
        dl._log(f"[VPN] --retry-failed: Ep retry tat ca file failed (IP={current_ip or '?'}).", "ok")
    elif current_ip and current_loc != "VN":
        # Day la mot IP fake hop le
        if current_ip != last_ip:
            if last_ip:
                dl._log(f"[VPN] Phat hien IP fake moi: {current_ip} (loc={current_loc}). Se quet va dich lai list loi!", "ok")
            else:
                dl._log(f"[VPN] Khoi tao IP fake hien tai: {current_ip} (loc={current_loc}). Luon retry list loi.", "ok")
            force_retry_failed = True
            progress["last_ip"] = current_ip
            save_progress(trans_dir, progress)
        else:
            # IP fake KHONG DOI -> khong tu dong retry; dung --retry-failed neu muon ep
            dl._log(f"[VPN] IP fake khong doi: {current_ip} (loc={current_loc}). Dung --retry-failed neu muon ep retry.", "warn")
    else:
        # Dang o IP that (loc=VN hoac khong co ket noi internet/VPN)
        if current_ip:
            dl._log(f"[VPN] Dang dung IP that: {current_ip} (loc={current_loc}). Khong cap nhat lich su IP fake.", "warn")
        else:
            dl._log(f"[VPN] Khong lay duoc thong tin IP public.", "warn")

    # Chay quet dung 1 lan roi thoat
    n = scan_once(origin_dir, trans_dir, cache_root, progress, file_workers, force_retry_failed, reverse=args.nguoc)
    
    # Dong bo hoa tien do lan cuoi khi ket thuc
    sync_progress_files(origin_dir, trans_dir)
    
    print(f"\n[*] Xong: {n} truyen dich xong.")


if __name__ == "__main__":
    main()
