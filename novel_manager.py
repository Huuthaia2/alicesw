#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Novel Registry Manager - Công cụ quản lý kho truyện đã tải và kiểm tra trùng lặp.
Hỗ trợ quét truyện cũ, trích xuất tên gốc chữ Hán qua Gemini, và đối chiếu trùng lặp (tên/nội dung).
"""

import os
import sys
import json
import re
import argparse
import difflib
from pathlib import Path

# Thêm thư mục hiện tại vào sys.path để import alicesw_downloader
sys.path.append(str(Path(__file__).parent))
try:
    import alicesw_downloader
except ImportError:
    alicesw_downloader = None

# Đường dẫn mặc định
DEFAULT_REGISTRY_PATH = Path("downloaded/downloaded_registry.json")
DEFAULT_ORIGIN_DIR = Path("downloaded/origin")
DEFAULT_TRANSLATED_DIR = Path("downloaded/translated")

def clean_chinese_text(text: str) -> str:
    """
    Giữ lại chỉ ký tự chữ Trung Quốc (chữ Hán CJK Unified Ideographs) để so sánh nội dung chính xác.
    Loại bỏ dấu câu, khoảng trắng, chữ Latin, số, v.v.
    """
    clean_chars = []
    for char in text:
        if '\u4e00' <= char <= '\u9fff':
            clean_chars.append(char)
    return "".join(clean_chars)

def get_content_fingerprint(body: str, length: int = 200) -> str:
    """
    Tạo dấu vân tay từ văn bản chương 1 (lấy N ký tự chữ Hán sạch đầu tiên).
    """
    cleaned = clean_chinese_text(body)
    return cleaned[:length]

def parse_downloaded_txt(filepath: Path) -> dict:
    """
    Đọc file thô dưới downloaded/origin, phân tích header và body.
    """
    content = filepath.read_text(encoding="utf-8", errors="ignore")
    # Tách header ngăn cách bởi 60 dấu bằng
    sep = "=" * 60
    parts = content.split(sep)
    
    header = ""
    body = content
    if len(parts) >= 3:
        header = parts[1]
        body = "".join(parts[2:])
        
    novel_url = ""
    author = "Khong ro"
    viet_title = ""
    
    for line in header.splitlines():
        line = line.strip()
        if line.startswith("Nguồn") or line.startswith("Nguồn      :"):
            m = re.search(r"https?://[^\s]+", line)
            if m:
                novel_url = m.group(0)
        elif line.startswith("Tác giả") or line.startswith("Tác giả    :"):
            author = line.split(":", 1)[-1].strip()
        elif line and not line.startswith("=") and not line.startswith("Tag") and not line.startswith("Chương") and not line.startswith("Tình trạng"):
            if not viet_title:
                viet_title = line
                
    if not viet_title:
        # Fallback lấy từ tên file
        viet_title = filepath.name.split("+")[0].strip()
        
    return {
        "novel_url": novel_url,
        "author": author,
        "viet_title": viet_title,
        "body": body
    }

def call_gemini_for_chinese_title(body_text: str, api_key: str = None) -> str:
    """
    Gọi Gemini API thông qua alicesw_downloader để trích xuất tên gốc tiếng Hán của truyện.
    """
    if not alicesw_downloader:
        print("[!] Không tìm thấy alicesw_downloader.py để gọi Gemini.")
        return ""
        
    # Thiết lập API Key
    if api_key:
        alicesw_downloader.GEMINI_API_KEY = api_key
    elif not alicesw_downloader.GEMINI_API_KEY:
        alicesw_downloader.GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
        
    if not alicesw_downloader.GEMINI_API_KEY:
        print("[!] Không có GEMINI_API_KEY để gọi nhận diện tên truyện.")
        return ""
        
    # Lấy 1500 ký tự đầu tiên của truyện để làm ngữ cảnh gửi Gemini
    snippet = body_text[:1500].strip()
    prompt = (
        "Dưới đây là một phần đoạn văn bản tiếng Trung (chương 1) của một truyện:\n\n"
        f"\"\"\"\n{snippet}\n\"\"\"\n\n"
        "Hãy tìm tên gốc tiếng Trung (chữ Hán tự) chính xác của bộ truyện này (ví dụ: '过年玩牌', '逆袭', '双龙战'...). "
        "Yêu cầu: Chỉ trả về duy nhất tên truyện bằng chữ Hán, không kèm bất kỳ giải thích, dấu ngoặc hay ký tự thừa nào."
    )
    
    # Override system prompt tạm thời của alicesw_downloader để có kết quả tốt nhất
    old_prompt = alicesw_downloader.GEMINI_SYS_PROMPT
    alicesw_downloader.GEMINI_SYS_PROMPT = "You are a helpful assistant specialized in Chinese web novels and text identification."
    try:
        title = alicesw_downloader.gemini_generate(prompt, retries=2)
        if title:
            # Làm sạch kết quả trả về
            title = title.strip().replace("\"", "").replace("'", "")
            # Bỏ các phần giải thích nếu Gemini trả về dài
            title = title.split("\n")[0].split("：")[-1].split(":")[-1].strip()
            return title
    except Exception as e:
        print(f"[!] Lỗi gọi Gemini: {e}")
    finally:
        alicesw_downloader.GEMINI_SYS_PROMPT = old_prompt
        
    return ""

def get_match_details(new_text: str, ref_text: str) -> dict:
    """
    So sánh 2 đoạn văn bản chữ Hán, trả về dict với:
      score        - tỷ lệ khớp (0.0 - 1.0)
      new_snippet  - đoạn 200 ký tự Hán sạch của văn bản mới
      ref_snippet  - đoạn đã lưu trong registry
      longest_match - đoạn chữ Hán trùng khớp dài nhất
    """
    clean_new = clean_chinese_text(new_text)[:200]
    clean_ref = ref_text  # registry đã lưu dạng sạch
    s = difflib.SequenceMatcher(None, clean_new, clean_ref)
    blocks = s.get_matching_blocks()
    best = max(blocks, key=lambda b: b.size, default=None)
    longest = clean_new[best.a: best.a + best.size] if best and best.size > 0 else ""
    return {
        "score": s.ratio(),
        "new_snippet": clean_new,
        "ref_snippet": clean_ref,
        "longest_match": longest,
    }

def load_registry(registry_path: Path) -> dict:
    """
    Tải danh sách đăng ký từ file JSON.
    """
    if registry_path.exists():
        try:
            return json.loads(registry_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[!] Lỗi đọc file registry {registry_path}: {e}")
    return {}

def save_registry(registry_path: Path, registry: dict):
    """
    Ghi danh sách đăng ký vào file JSON.
    """
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        registry_path.write_text(
            json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8"
        )
    except Exception as e:
        print(f"[!] Lỗi ghi file registry {registry_path}: {e}")

def check_duplicate(registry: dict, check_url: str = None, check_title: str = None, check_content: str = None, min_ratio: float = 0.6) -> tuple:
    """
    Kiểm tra trùng lặp dựa trên URL, tên (tiếng Hán/Việt) và vân tay nội dung.
    Trả về (is_duplicate, duplicate_entry, reason, score)
    """
    # 1. Kiểm tra trùng lặp URL
    if check_url:
        for novel_id, entry in registry.items():
            if check_url in entry.get("links", []):
                return True, entry, f"Trùng URL đã tải ({check_url})", 1.0
                
    # 2. Kiểm tra trùng lặp nội dung bằng đoạn mẫu chữ Hán
    if check_content:
        clean_check = clean_chinese_text(check_content)[:200]
        if len(clean_check) >= 20: # Phải có độ dài tối thiểu để so khớp
            for novel_id, entry in registry.items():
                ref_content = entry.get("dau_van_tay_noi_dung", {}).get("doan_mau_chu_han", "")
                if ref_content:
                    s = difflib.SequenceMatcher(None, clean_check, ref_content)
                    ratio = s.ratio()
                    if ratio >= min_ratio:
                        return True, entry, f"Trùng lặp nội dung chương 1 (Độ tương đồng: {ratio*100:.1f}%)", ratio
                        
    # 3. Kiểm tra trùng lặp tên truyện (Fuzzy matching)
    if check_title:
        check_title_clean = check_title.strip().lower()
        for novel_id, entry in registry.items():
            # Kiểm tra tên gốc tiếng Hán
            goc_han = entry.get("ten_goc_han", "").strip().lower()
            if goc_han and goc_han == check_title_clean:
                return True, entry, f"Trùng khớp hoàn toàn tên gốc tiếng Hán ({entry['ten_goc_han']})", 1.0
                
            # Kiểm tra các tên tiếng Việt liên quan
            for vi_title in entry.get("ten_viet_lien_quan", []):
                vi_title_clean = vi_title.strip().lower()
                if check_title_clean in vi_title_clean or vi_title_clean in check_title_clean:
                    # Trùng khớp mờ tên Việt
                    s = difflib.SequenceMatcher(None, check_title_clean, vi_title_clean)
                    ratio = s.ratio()
                    if ratio >= 0.85:
                        return True, entry, f"Nghi ngờ trùng khớp tên Việt ({vi_title}) (Độ khớp: {ratio*100:.1f}%)", ratio

    return False, None, "Truyện mới hoàn toàn", 0.0

def add_novel_to_registry(registry: dict, chinese_title: str, links: list, viet_title: str, author: str, content_body: str, origin_filename: str = "", trans_filename: str = "") -> str:
    """
    Thêm một truyện mới hoặc cập nhật thông tin link/tên cho truyện đã có.
    Trả về novel_id được thêm/cập nhật.
    """
    # Sinh fingerprint
    fingerprint = get_content_fingerprint(content_body)
    
    # Kiểm tra xem có trùng lặp nội dung/tên gốc sẵn trong registry chưa để gộp nhóm
    is_dup, dup_entry, reason, score = check_duplicate(registry, check_title=chinese_title, check_content=content_body)
    
    if is_dup:
        novel_id = dup_entry["truyen_id_chuan"]
        print(f"[*] Phát hiện trùng lặp với truyện ID {novel_id} ({dup_entry['ten_goc_han']}). Đang gộp thông tin...")
        
        # Cập nhật danh sách link
        links_set = set(dup_entry.get("links", []))
        for link in links:
            if link:
                links_set.add(link)
        dup_entry["links"] = sorted(list(links_set))
        
        # Cập nhật tên Việt
        vi_set = set(dup_entry.get("ten_viet_lien_quan", []))
        if viet_title:
            vi_set.add(viet_title)
        dup_entry["ten_viet_lien_quan"] = sorted(list(vi_set))
        
        # Cập nhật file cục bộ
        if origin_filename:
            dup_entry.setdefault("file_cuc_bo", {})["origin"] = origin_filename
        if trans_filename:
            dup_entry.setdefault("file_cuc_bo", {})["translated"] = trans_filename
            
        return novel_id
        
    else:
        # Thêm truyện mới hoàn toàn
        # Sinh novel_id bằng độ dài registry + 10001
        novel_id = str(len(registry) + 10001)
        
        registry[novel_id] = {
            "truyen_id_chuan": novel_id,
            "ten_goc_han": chinese_title or "Chưa rõ",
            "ten_viet_lien_quan": [viet_title] if viet_title else [],
            "tac_gia": author,
            "links": [l for l in links if l],
            "file_cuc_bo": {
                "origin": origin_filename,
                "translated": trans_filename
            },
            "dau_van_tay_noi_dung": {
                "doan_mau_chu_han": fingerprint
            }
        }
        return novel_id

def main():
    parser = argparse.ArgumentParser(description="Novel Registry Manager - Công cụ quản lý và kiểm tra trùng lặp truyện.")
    subparsers = parser.add_subparsers(dest="command", help="Lệnh thực hiện")
    
    # Command: scan
    scan_parser = subparsers.add_parser("scan", help="Quét các file thô trong downloaded/origin để khôi phục cơ sở dữ liệu ban đầu.")
    scan_parser.add_argument("--api-key", type=str, default="", help="Gemini API Key (nếu không có trong biến môi trường)")
    scan_parser.add_argument("--no-gemini", action="store_true", help="Không sử dụng Gemini API để nhận diện tên gốc tiếng Hán")
    scan_parser.add_argument("--limit", type=int, default=0, help="Giới hạn số lượng file xử lý mới (0 = không giới hạn)")
    
    # Command: check
    check_parser = subparsers.add_parser("check", help="Kiểm tra một truyện mới xem có trùng lặp không.")
    check_parser.add_argument("--url", type=str, default="", help="URL truyện mới cần kiểm tra")
    check_parser.add_argument("--title", type=str, default="", help="Tên truyện (tiếng Việt hoặc Hán) cần kiểm tra")
    check_parser.add_argument("--file", type=str, default="", help="File truyện (.txt) cần kiểm tra")
    
    # Command: match
    match_parser = subparsers.add_parser(
        "match",
        help="Nhập đoạn văn chữ Hán để so SequenceMatcher với toàn bộ registry."
    )
    match_parser.add_argument("--text", type=str, default="", help="Đoạn văn chữ Hán cần so khớp (nếu bỏ trống sẽ hỏi nhập)")
    match_parser.add_argument("--top", type=int, default=5, help="Số kết quả cao nhất hiển thị (mặc định 5)")
    match_parser.add_argument("--min", type=float, default=0.0,
                              help="Chỉ hiển thị kết quả >= giá trị này (0.0-1.0, mặc định 0 = hiện top N)")
    match_parser.add_argument("--log", action="store_true",
                              help="Ghi kết quả trùng (>= 60%%) vào downloaded/_duplicate_detected.txt")

    # Command: add
    add_parser = subparsers.add_parser("add", help="Thêm thủ công một link/truyện vào registry.")
    add_parser.add_argument("--title-han", type=str, required=True, help="Tên gốc chữ Hán của truyện")
    add_parser.add_argument("--title-vi", type=str, default="", help="Tên tiếng Việt")
    add_parser.add_argument("--url", type=str, required=True, help="URL truyện")
    add_parser.add_argument("--author", type=str, default="Khong ro", help="Tác giả")

    args = parser.parse_args()
    
    registry_path = DEFAULT_REGISTRY_PATH
    registry = load_registry(registry_path)
    
    if args.command == "scan":
        origin_dir = DEFAULT_ORIGIN_DIR
        if not origin_dir.exists():
            print(f"[!] Thư mục {origin_dir.resolve()} không tồn tại!")
            sys.exit(1)
            
        txt_files = list(origin_dir.glob("*.txt"))
        if not txt_files:
            print(f"[!] Không tìm thấy tệp .txt nào trong {origin_dir.resolve()}")
            sys.exit(1)
            
        print(f"[*] Tổng số file thô tìm thấy: {len(txt_files)}")
        
        # Tạo danh sách các file đã quét để bỏ qua
        scanned_files = set()
        for entry in registry.values():
            orig_file = entry.get("file_cuc_bo", {}).get("origin", "")
            if orig_file:
                scanned_files.add(orig_file)
                
        # Lọc danh sách file chưa quét
        todo_files = [f for f in txt_files if f.name not in scanned_files]
        print(f"[*] Số lượng file chưa quét: {len(todo_files)} (đã bỏ qua {len(scanned_files)} file đã quét)")
        
        if args.limit > 0:
            todo_files = todo_files[:args.limit]
            print(f"[*] Giới hạn quét: {args.limit} file")
            
        if not todo_files:
            print("[*] Không có file mới nào cần quét. Hoàn thành!")
            sys.exit(0)
            
        # Đọc tiến độ trans nếu có để ghép file translated tương ứng
        trans_progress_path = Path("downloaded/_translated_progress.json")
        trans_progress = {}
        if trans_progress_path.exists():
            try:
                trans_progress = json.loads(trans_progress_path.read_text(encoding="utf-8"))
            except Exception:
                pass
                
        # Tìm _origin_progress.json để map novel_id của alicesw
        origin_progress_path = Path("downloaded/_origin_progress.json")
        origin_progress = {}
        if origin_progress_path.exists():
            try:
                origin_progress = json.loads(origin_progress_path.read_text(encoding="utf-8")).get("done", {})
            except Exception:
                pass
        
        # Tạo map ngược từ filename_origin -> novel_id
        origin_filename_to_nid = {v: k for k, v in origin_progress.items()}
        
        count_processed = 0
        for idx, file_path in enumerate(todo_files, 1):
            print(f"\n[{idx}/{len(todo_files)}] Xử lý: {file_path.name}")
            
            # Phân tích file thô
            info = parse_downloaded_txt(file_path)
            body = info["body"]
            
            # Map thông tin từ file progress
            nid = origin_filename_to_nid.get(file_path.name, "")
            trans_file = ""
            if nid and trans_progress:
                trans_file = trans_progress.get(nid, "")
                
            # Trích xuất tên chữ Hán
            chinese_title = ""
            if not args.no_gemini:
                # Thử gọi Gemini lấy tên chữ Hán chuẩn
                print(f"  [-] Đang gửi ngữ cảnh chữ Hán lên Gemini để tìm tên gốc...")
                chinese_title = call_gemini_for_chinese_title(body, api_key=args.api_key)
                if chinese_title:
                    print(f"  [OK] Gemini nhận diện tên gốc: {chinese_title}")
                else:
                    print(f"  [WARN] Gemini không nhận diện được tên gốc.")
                    
            if not chinese_title:
                # Nếu không nhận diện được hoặc bỏ qua Gemini, lấy chữ Hán từ tác giả hoặc tạm đặt placeholder
                chinese_title = f"Chưa rõ ({info['viet_title']})"
                
            # Thêm vào registry
            nid_chuan = add_novel_to_registry(
                registry=registry,
                chinese_title=chinese_title,
                links=[info["novel_url"]],
                viet_title=info["viet_title"],
                author=info["author"],
                content_body=body,
                origin_filename=file_path.name,
                trans_filename=trans_file
            )
            print(f"  [Done] Đã đưa vào registry với ID chuẩn: {nid_chuan}")
            
            # Lưu sau mỗi file để phòng crash/ngắt
            count_processed += 1
            if count_processed % 5 == 0 or idx == len(todo_files):
                save_registry(registry_path, registry)
                print(f"  [System] Đã lưu tiến độ vào registry.")
                
        # Lưu lần cuối
        save_registry(registry_path, registry)
        print(f"\n[OK] Đã quét và cập nhật cơ sở dữ liệu registry! Tổng số truyện trong cơ sở dữ liệu: {len(registry)}")
        
    elif args.command == "check":
        url = args.url
        title = args.title
        file_path = args.file
        
        check_content = ""
        if file_path:
            p = Path(file_path)
            if p.exists():
                info = parse_downloaded_txt(p)
                check_content = info["body"]
                if not title:
                    title = info["viet_title"]
                if not url:
                    url = info["novel_url"]
                    
        is_dup, dup_entry, reason, score = check_duplicate(
            registry=registry,
            check_url=url,
            check_title=title,
            check_content=check_content
        )
        
        print("\n" + "="*50)
        print("  KẾT QUẢ KIỂM TRA TRÙNG LẶP TRUYỆN")
        print("="*50)
        if is_dup:
            print(f"  TRẠNG THÁI : [!] PHÁT HIỆN TRÙNG LẶP ({score*100:.1f}%)")
            print(f"  Lý do      : {reason}")
            print(f"  Tên gốc Hán: {dup_entry['ten_goc_han']}")
            print(f"  Tên Việt   : {', '.join(dup_entry.get('ten_viet_lien_quan', []))}")
            print(f"  Tác giả    : {dup_entry['tac_gia']}")
            print(f"  ID chuẩn   : {dup_entry['truyen_id_chuan']}")
            print(f"  Các link cũ: ")
            for link in dup_entry.get("links", []):
                print(f"    - {link}")
        else:
            print("  TRẠNG THÁI : [OK] TRUYỆN MỚI HOÀN TOÀN")
            print("  Không phát hiện bất kỳ trùng lặp nào về tên truyện hay nội dung chữ Hán.")
        print("="*50 + "\n")
        
    elif args.command == "match":
        # Nhận đoạn text chữ Hán từ argument hoặc nhập tay
        raw_text = args.text.strip()
        if not raw_text:
            print("Nhập đoạn văn chữ Hán cần so khớp (Enter 2 lần để kết thúc):")
            lines = []
            try:
                while True:
                    line = input()
                    if line == "" and lines and lines[-1] == "":
                        break
                    lines.append(line)
            except (EOFError, KeyboardInterrupt):
                pass
            raw_text = "\n".join(lines).strip()

        if not raw_text:
            print("[!] Không có văn bản để so khớp.")
            sys.exit(1)

        clean_input = clean_chinese_text(raw_text)[:200]
        if len(clean_input) < 10:
            print(f"[!] Quá ít ký tự chữ Hán ({len(clean_input)} ký tự). Cần ít nhất 10 ký tự.")
            sys.exit(1)

        print(f"\n[*] Đoạn chữ Hán sạch ({len(clean_input)} ký tự): {clean_input[:60]}...")
        print(f"[*] Đang so khớp với {len(registry)} truyện trong registry...\n")

        # Tính điểm cho tất cả entry có fingerprint
        results = []
        for nid, entry in registry.items():
            ref = entry.get("dau_van_tay_noi_dung", {}).get("doan_mau_chu_han", "")
            if not ref:
                continue
            det = get_match_details(raw_text, ref)
            results.append((det["score"], nid, entry, det))

        results.sort(key=lambda x: x[0], reverse=True)

        top_n = results[:args.top]
        min_score = args.min

        sep = "=" * 70
        print(sep)
        print(f"  TOP {args.top} KẾT QUẢ SO KHỚP NỘI DUNG CHỮ HÁN")
        print(sep)

        DUP_THRESHOLD = 0.6
        log_entries = []

        for rank, (score, nid, entry, det) in enumerate(top_n, 1):
            if score < min_score:
                continue
            flag = "  *** TRÙNG ***" if score >= DUP_THRESHOLD else ""
            print(f"\n[{rank}] Độ khớp: {score*100:.1f}%{flag}")
            print(f"    Tên gốc Hán : {entry.get('ten_goc_han', '(chưa rõ)')}")
            print(f"    Tên Việt    : {'; '.join(entry.get('ten_viet_lien_quan', []))}")
            print(f"    Tác giả     : {entry.get('tac_gia', '')}")
            print(f"    Links       : {'; '.join(entry.get('links', []))}")
            print(f"    File gốc    : {entry.get('file_cuc_bo', {}).get('origin', '')}")
            print(f"    Đoạn nhập   : {det['new_snippet'][:80]}...")
            print(f"    Đoạn lưu    : {det['ref_snippet'][:80]}...")
            print(f"    Đoạn trùng  : {det['longest_match'][:80]}")
            if score >= DUP_THRESHOLD and args.log:
                log_entries.append((entry, det))

        if not top_n or top_n[0][0] < min_score:
            print("  (Không có kết quả nào khớp với ngưỡng đã đặt)")
        print(f"\n{sep}\n")

        # Ghi log nếu --log và có trùng
        if args.log and log_entries:
            import datetime
            log_path = DEFAULT_REGISTRY_PATH.parent / "_duplicate_detected.txt"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with log_path.open("a", encoding="utf-8") as f:
                for dup_entry, det in log_entries:
                    f.write("=" * 78 + "\n")
                    f.write(f"[{ts}] TRÙNG LẶP PHÁT HIỆN QUA LỆNH match\n")
                    f.write("=" * 78 + "\n")
                    f.write(f"Tên gốc Hán   : {dup_entry.get('ten_goc_han', '')}\n")
                    f.write(f"Tên Việt      : {'; '.join(dup_entry.get('ten_viet_lien_quan', []))}\n")
                    f.write(f"Tác giả       : {dup_entry.get('tac_gia', '')}\n")
                    f.write(f"Links         : {'; '.join(dup_entry.get('links', []))}\n")
                    f.write(f"File gốc      : {dup_entry.get('file_cuc_bo', {}).get('origin', '')}\n")
                    f.write(f"\nĐộ khớp       : {det['score']*100:.1f}%\n")
                    f.write(f"\nĐoạn nhập (200 ký tự Hán sạch):\n{det['new_snippet']}\n")
                    f.write(f"\nĐoạn lưu trong registry:\n{det['ref_snippet']}\n")
                    f.write(f"\nĐoạn trùng dài nhất:\n{det['longest_match']}\n")
                    f.write("=" * 78 + "\n\n")
            print(f"[OK] Đã ghi {len(log_entries)} bản ghi trùng vào: {log_path}")

    elif args.command == "add":
        # Thêm thủ công
        nid_chuan = add_novel_to_registry(
            registry=registry,
            chinese_title=args.title_han,
            links=[args.url],
            viet_title=args.title_vi,
            author=args.author,
            content_body=""
        )
        save_registry(registry_path, registry)
        print(f"[OK] Đã thêm thủ công truyện '{args.title_han}' với ID chuẩn {nid_chuan} vào registry.")

    else:
        parser.print_help()

if __name__ == "__main__":
    main()
