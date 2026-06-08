#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cập nhật header (Tag, Tình trạng) cho các file .txt đã tải.
Không đụng nội dung chương. Tự đổi tên thêm _end nếu hoàn thành.

Chạy:
  py _update_headers.py                     # cả hai thư mục, 1 luồng
  py _update_headers.py --workers 10        # 10 luồng song song
  py _update_headers.py --dry-run           # xem trước
  py _update_headers.py --folder origin     # chỉ origin
"""

import re
import sys
import time
import threading
import argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, str(Path(__file__).parent))
from alicesw_downloader import (
    get_novel_info, _TAG_MAP, _STATUS_CN_MAP, _is_completed,
)
import hanviet as _hv

BASE     = Path(__file__).parent / "downloaded"
SEP60    = "=" * 60
SEP_RE   = re.compile(r"^={50,}$")
NGUON_RE = re.compile(r"(?:Ngu[oồ]n|Nguon)\s*:\s*(https?://\S+)")
CHUONG_RE= re.compile(r"(?:Ch[uươ][oơ]ng|Chuong)\s*:\s*(\d+)")
DICH_RE  = re.compile(r"(?:D[iị]ch)\s*:\s*(.+)")

DRY_RUN  = False
_print_lock = threading.Lock()
ORIGIN_PROGRESS = {}

def load_origin_progress():
    global ORIGIN_PROGRESS
    progress_path = BASE / "_origin_progress.json"
    if progress_path.exists():
        import json
        try:
            ORIGIN_PROGRESS = json.loads(progress_path.read_text(encoding="utf-8"))
        except Exception:
            pass


def _log(*args, **kwargs):
    with _print_lock:
        print(*args, **kwargs)


def _tag_vi(t: str) -> str:
    if t in _TAG_MAP:
        return _TAG_MAP[t]
    return _hv.hanzi_to_hanviet(t) if _hv.has_hanzi(t) else t


def _resolve_tags(info: dict) -> list[str]:
    raw_vi = info.get("tags_vi") or []
    raw_cn = info.get("tags_cn") or []
    raw = raw_vi if raw_vi else raw_cn
    seen: set[str] = set()
    result = []
    for t in raw:
        t = t.lstrip("#").strip()
        if not t:
            continue
        translated = _tag_vi(t)
        key = translated.lower()
        if key not in seen:
            seen.add(key)
            result.append(translated)
    return result


def _build_header(novel_info: dict, total: str, engine: str,
                  is_origin: bool) -> str:
    tags_vi = _resolve_tags(novel_info)
    raw_status = novel_info.get("status_vi") or novel_info.get("status_cn", "")
    status_vi  = _STATUS_CN_MAP.get(raw_status, raw_status)

    lines = [SEP60]
    lines.append(f"  {novel_info['title']}")
    author = novel_info['author']
    author_vi = _hv.hanzi_to_hanviet(author) if _hv.has_hanzi(author) else author
    lines.append(f"  Tác giả    : {author_vi}")
    lines.append(f"  Nguồn      : {novel_info['novel_url']}")
    if tags_vi:
        lines.append(f"  Tag        : {', '.join('#' + t[:1].upper() + t[1:] for t in tags_vi)}")
    lines.append(f"  Chương     : {total}")
    if status_vi:
        lines.append(f"  Tình trạng : {status_vi}")
    if engine and not is_origin:
        lines.append(f"  Dịch       : {engine}")
    lines.append(SEP60)
    return "\n".join(lines)


def _split_header_body(text: str):
    lines = text.splitlines()
    # 1. Thử phân tích theo dòng kẻ ngăn cách (separator-based split)
    sep_idx = [i for i, ln in enumerate(lines) if SEP_RE.match(ln.strip())]
    if len(sep_idx) >= 2:
        end = sep_idx[1]
        return lines[:end + 1], "\n".join(lines[end + 1:])

    # 2. Thử phân tích theo các từ khóa trường thông tin (không có dòng kẻ)
    patterns = [
        re.compile(r"^\s*(?:T[aá]c gi[aả]|Tac gia)\s*:"),
        re.compile(r"^\s*(?:Ngu[oồ]n|Nguon)\s*:"),
        re.compile(r"^\s*(?:Ch[uươ]ng|Chuong)\s*:"),
        re.compile(r"^\s*(?:T[iị]nh tr[aạ]ng|Tinh trang)\s*:"),
        re.compile(r"^\s*(?:D[iị]ch|Dich)\s*:"),
        re.compile(r"^\s*Tag\s*:")
    ]

    last_idx = -1
    for i in range(min(15, len(lines))):
        ln = lines[i]
        if any(p.search(ln) for p in patterns):
            last_idx = i

    if last_idx != -1:
        body_start = last_idx + 1
        while body_start < len(lines) and not lines[body_start].strip():
            body_start += 1
        return lines[:last_idx + 1], "\n".join(lines[body_start:])

    return None, None


def process_file(filepath: Path) -> tuple[bool, str]:
    """
    Xử lý 1 file. Trả về (changed: bool, message: str).
    Thread-safe: không dùng print trực tiếp.
    """
    text = filepath.read_text(encoding="utf-8")
    header_lines, body = _split_header_body(text)
    if header_lines is None:
        return False, f"[!] Không có header chuẩn: {filepath.name}"

    header_str = "\n".join(header_lines)
    m_url = NGUON_RE.search(header_str)
    if not m_url:
        return False, f"[!] Không tìm thấy URL: {filepath.name}"
    novel_url = m_url.group(1).strip()

    m_ch   = CHUONG_RE.search(header_str)
    total  = m_ch.group(1) if m_ch else "?"
    m_dich = DICH_RE.search(header_str)
    engine = m_dich.group(1).strip() if m_dich else ""
    is_origin = "_origin" in filepath.stem

    try:
        info = get_novel_info(novel_url)
    except Exception as e:
        return False, f"[!] Lỗi fetch {filepath.name}: {e}"
    if not info:
        return False, f"[!] Không lấy được info: {filepath.name}"

    # 1. Trích xuất tên truyện tiếng Việt chuẩn từ novel_id qua _origin_progress.json
    vi_title = ""
    novel_id = ""
    m = re.search(r"/novel/(\d+)\.html", novel_url)
    if m:
        novel_id = m.group(1)

    if novel_id and novel_id in ORIGIN_PROGRESS:
        origin_name = ORIGIN_PROGRESS[novel_id]
        m_orig = re.match(r"^(.*?)\+\d+\s+Chuong(?:_origin)?(_end)?\.txt$", origin_name, re.IGNORECASE)
        if m_orig:
            vi_title = m_orig.group(1).strip("_ ")

    # 2. Nếu không tìm thấy, lấy từ chính tên file hiện tại
    if not vi_title:
        stem = filepath.stem
        m_stem = re.match(r"^(.*?)\+\d+\s+Chuong(?:_origin)?(_end)?$", stem, re.IGNORECASE)
        if m_stem:
            vi_title = m_stem.group(1).strip("_ ")

    # Fallback cuối cùng nếu vẫn rỗng
    if not vi_title:
        vi_title = info.get("title", "").strip("_ ")

    info["title"] = vi_title

    raw_tags   = _resolve_tags(info)
    raw_status = info.get("status_vi") or info.get("status_cn", "")
    status_vi  = _STATUS_CN_MAP.get(raw_status, raw_status)

    new_header  = _build_header(info, total, engine, is_origin)
    new_content = new_header + "\n" + body
    changed     = new_content != text

    completed = _is_completed(raw_status)
    _end = "_end" if completed else ""
    _orig = "_origin" if is_origin else ""
    new_stem = f"{vi_title}+{total} Chuong{_orig}{_end}"
    new_path = filepath.with_name(new_stem + filepath.suffix)
    renamed  = new_path != filepath

    tag_str = ', '.join(raw_tags) if raw_tags else '(trống)'
    lines_out = [
        f"\n[*] {filepath.name}",
        f"    Tag        : {tag_str}",
        f"    Tình trạng : {status_vi or '(trống)'}",
    ]

    if not changed and not renamed:
        lines_out.append("    (không thay đổi)")
        return False, "\n".join(lines_out)

    if DRY_RUN:
        if changed:  lines_out.append("    [DRY] Sẽ update header")
        if renamed:  lines_out.append(f"    [DRY] Sẽ đổi tên -> {new_path.name}")
        return True, "\n".join(lines_out)

    if changed:
        filepath.write_text(new_content, encoding="utf-8")
        lines_out.append("    [OK] Đã cập nhật header")

    if renamed:
        if new_path.exists():
            lines_out.append(f"    [!] File đích đã tồn tại, bỏ qua đổi tên")
        else:
            filepath.rename(new_path)
            lines_out.append(f"    [OK] Đổi tên -> {new_path.name}")

    return True, "\n".join(lines_out)


def run(folders: list[Path], workers: int = 1, delay: float = 0.0, limit: int = 0):
    all_files: list[Path] = []
    for folder in folders:
        if not folder.exists():
            continue
        files = sorted(f for f in folder.iterdir()
                       if f.suffix == ".txt" and not f.name.startswith("_"))
        _log(f"\n{'='*60}")
        _log(f"Thư mục: {folder.name}  ({len(files)} file)")
        _log(f"{'='*60}")
        all_files.extend(files)

    if limit > 0:
        all_files = all_files[:limit]

    updated = 0
    done    = 0
    total_f = len(all_files)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(process_file, f): f for f in all_files}
        for fut in as_completed(futures):
            ok, msg = fut.result()
            done += 1
            if ok:
                updated += 1
            _log(f"[{done}/{total_f}] {msg}")
            if delay > 0:
                time.sleep(delay)

    _log(f"\n{'='*60}")
    mode = "[DRY RUN] " if DRY_RUN else ""
    _log(f"{mode}Hoàn tất: {updated}/{total_f} file được cập nhật.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Cập nhật Tag + Tình trạng cho tất cả file đã tải")
    parser.add_argument("--dry-run", action="store_true",
                        help="Chỉ xem trước, không ghi file")
    parser.add_argument("--workers", type=int, default=1,
                        help="Số luồng song song (mặc định 1, khuyên dùng <=10)")
    parser.add_argument("--delay", type=float, default=0.0,
                        help="Delay giữa các request, giây (mặc định 0)")
    parser.add_argument("--folder", choices=["origin", "translated", "both"],
                        default="both",
                        help="Thư mục xử lý (mặc định: cả hai)")
    parser.add_argument("--limit", type=int, default=0,
                        help="Giới hạn số file xử lý, 0 = tất cả (dùng để test)")
    parser.add_argument("--test-url", metavar="URL", default="",
                        help="Debug: fetch 1 URL và in raw tags/status rồi thoát")
    args = parser.parse_args()

    DRY_RUN = args.dry_run

    folders = []
    if args.folder in ("origin", "both"):
        folders.append(BASE / "origin")
    if args.folder in ("translated", "both"):
        folders.append(BASE / "translated")

    if args.test_url:
        # Chế độ debug: fetch 1 URL và in raw info
        print(f"[DEBUG] Fetch: {args.test_url}")
        info = get_novel_info(args.test_url)
        if not info:
            print("[!] Không lấy được thông tin")
        else:
            print(f"  title    : {info.get('title')}")
            print(f"  tags_vi  : {info.get('tags_vi')}")
            print(f"  tags_cn  : {info.get('tags_cn')}")
            print(f"  status_vi: {info.get('status_vi')}")
            print(f"  status_cn: {info.get('status_cn')}")
        sys.exit(0)

    load_origin_progress()
    run(folders, workers=args.workers, delay=args.delay, limit=args.limit)
