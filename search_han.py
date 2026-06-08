#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Công cụ tìm kiếm đoạn văn chữ Hán thông minh (Smart & Fuzzy Search)
Bỏ qua dấu câu, khoảng trắng, xuống dòng và hỗ trợ khớp sai lệch/thiếu từ (tối thiểu 60%)
"""

import os
import sys
import time
import unicodedata
import difflib
from pathlib import Path

# Cấu hình đường dẫn mặc định
DEFAULT_DIR = Path(r"c:\Users\Z\Documents\Python\alicesw\downloaded\origin")

# Kích hoạt hỗ trợ mã màu ANSI trên Windows console
if os.name == 'nt':
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        # GetStdHandle(-11) is STD_OUTPUT_HANDLE
        hOut = kernel32.GetStdHandle(-11)
        mode = ctypes.c_ulong()
        if kernel32.GetConsoleMode(hOut, ctypes.byref(mode)):
            kernel32.SetConsoleMode(hOut, mode.value | 0x0004)
    except Exception:
        pass

# Mã màu ANSI
C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_RED = "\033[31m"
C_GREEN = "\033[32m"
C_YELLOW = "\033[33m"
C_BLUE = "\033[34m"
C_CYAN = "\033[36m"
C_GRAY = "\033[90m"

def clean_console():
    """Xóa màn hình console."""
    os.system('cls' if os.name == 'nt' else 'clear')

def clean_string(text: str) -> tuple:
    """
    Trích xuất chuỗi ký tự sạch (bỏ qua mọi khoảng trắng, xuống dòng, và dấu câu cả Trung/Latin)
    và lưu lại mapping vị trí của ký tự sạch trỏ ngược về chỉ số trong văn bản gốc.
    """
    clean_chars = []
    mapping = []
    for idx, char in enumerate(text):
        cat = unicodedata.category(char)
        # Bỏ qua khoảng trắng (isspace), ký tự phân tách (Z), ký tự điều khiển (C), dấu câu (P)
        if cat.startswith(('Z', 'C', 'P')) or char.isspace() or char in ('\u3000', '\u200b'):
            continue
        clean_chars.append(char)
        mapping.append(idx)
    return "".join(clean_chars), mapping

def clean_query(q: str) -> str:
    """Chỉ loại bỏ dấu câu và khoảng trắng khỏi từ khóa tìm kiếm."""
    clean_chars = []
    for char in q:
        cat = unicodedata.category(char)
        if cat.startswith(('Z', 'C', 'P')) or char.isspace() or char in ('\u3000', '\u200b'):
            continue
        clean_chars.append(char)
    return "".join(clean_chars)

def load_and_cache_files(txt_files: list) -> list:
    """Đọc toàn bộ file, chia dòng và tiền xử lý lưu vào cache để tìm kiếm tức thì."""
    cached = []
    total = len(txt_files)
    
    print(f"[*] Đang tải và chỉ mục hóa {total} tệp văn bản vào RAM. Vui lòng đợi...")
    
    for i, file_path in enumerate(txt_files, 1):
        percent = int(i * 100 / total)
        bar_len = 30
        filled_len = int(bar_len * i // total)
        bar = '█' * filled_len + '-' * (bar_len - filled_len)
        print(f"\r    [{bar}] {percent}% ({i}/{total}) tệp: {file_path.name[:30]}...", end="", flush=True)
        
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            lines_raw = content.splitlines()
            lines_cache = []
            
            for line_idx, line_raw in enumerate(lines_raw, 1):
                if not line_raw.strip():
                    continue
                line_clean, line_mapping = clean_string(line_raw)
                if not line_clean:
                    continue
                lines_cache.append({
                    "line_num": line_idx,
                    "raw": line_raw,
                    "clean": line_clean,
                    "chars": set(line_clean),
                    "mapping": line_mapping
                })
                
            cached.append({
                "file_name": file_path.name,
                "file_path": file_path,
                "lines": lines_cache
            })
        except Exception:
            pass
            
    print(f"\n{C_GREEN}[OK] Đã hoàn thành chỉ mục hóa toàn bộ dữ liệu!{C_RESET}\n")
    return cached

def search_in_cache(cached_files: list, query: str, min_ratio: float = 0.6) -> list:
    """Tìm kiếm từ khóa trong cache, hỗ trợ khớp mờ (Fuzzy) và không phân biệt dấu câu/khoảng trắng."""
    q_clean = clean_query(query)
    if not q_clean:
        return []
        
    q_chars = set(q_clean)
    q_len = len(q_clean)
    
    # Bộ lọc nhanh: số lượng ký tự trùng tối thiểu giữa query và line
    if q_len >= 5:
        min_overlap = int(len(q_chars) * 0.5)
    else:
        min_overlap = max(1, len(q_chars) - 1)
        
    results = []
    
    for item in cached_files:
        matches = []
        for line in item["lines"]:
            line_clean = line["clean"]
            line_chars = line["chars"]
            
            # 1. Bộ lọc nhanh Set Intersection (C-level speed)
            if len(q_chars.intersection(line_chars)) < min_overlap:
                continue
                
            # 2. So khớp chi tiết bằng SequenceMatcher
            s = difflib.SequenceMatcher(None, q_clean, line_clean)
            blocks = [b for b in s.get_matching_blocks() if b.size > 0]
            if not blocks:
                continue
                
            total_match_len = sum(b.size for b in blocks)
            ratio = total_match_len / q_len
            
            if ratio >= min_ratio:
                start_clean_idx = min(b.b for b in blocks)
                end_clean_idx = max(b.b + b.size for b in blocks)
                
                # Ràng buộc khoảng cách vùng khớp (tránh khớp rải rác xa nhau)
                span_len = end_clean_idx - start_clean_idx
                if span_len > q_len * 1.5 + 10:
                    continue
                    
                # Ánh xạ lại chỉ số gốc trong dòng
                mapping = line["mapping"]
                start_orig = mapping[start_clean_idx]
                end_orig = mapping[end_clean_idx - 1] + 1
                
                # Tạo chuỗi highlight
                line_raw = line["raw"]
                before = line_raw[:start_orig]
                matched_text = line_raw[start_orig:end_orig]
                after = line_raw[end_orig:]
                
                highlighted = f"{before}{C_BOLD}{C_RED}{matched_text}{C_RESET}{after}".strip()
                
                matches.append({
                    "line_num": line["line_num"],
                    "highlighted": highlighted,
                    "score": ratio
                })
                
        if matches:
            # Sắp xếp các kết quả trong file theo điểm số trùng khớp giảm dần
            matches.sort(key=lambda x: x["score"], reverse=True)
            results.append({
                "file_name": item["file_name"],
                "file_path": item["file_path"],
                "matches": matches,
                "max_score": matches[0]["score"]
            })
            
    # Sắp xếp các file theo điểm số cao nhất giảm dần
    results.sort(key=lambda x: x["max_score"], reverse=True)
    return results

def main():
    clean_console()
    print(f"{C_CYAN}{'='*60}{C_RESET}")
    print(f"  {C_BOLD}{C_YELLOW}CÔNG CỤ TÌM KIẾM CHỮ HÁN THÔNG MINH (Fuzzy & Smart Search){C_RESET}")
    print(f"  Thư mục gốc: {C_GREEN}{DEFAULT_DIR.resolve()}{C_RESET}")
    print(f"  * Tính năng: Không cần đúng dấu câu, khoảng trắng, xuống dòng.")
    print(f"  * Khớp mờ  : Hỗ trợ viết thiếu từ/sai từ (độ chính xác >= 60%).")
    print(f"{C_CYAN}{'='*60}{C_RESET}\n")

    if not DEFAULT_DIR.exists():
        print(f"{C_RED}[!] Lỗi: Thư mục không tồn tại: {DEFAULT_DIR.resolve()}{C_RESET}")
        sys.exit(1)

    txt_files = list(DEFAULT_DIR.glob("*.txt"))
    if not txt_files:
        print(f"{C_RED}[!] Lỗi: Không tìm thấy tệp .txt nào trong thư mục.{C_RESET}")
        sys.exit(1)
        
    # Tải dữ liệu vào RAM
    cached_files = load_and_cache_files(txt_files)
    
    print(f"[*] Nhập từ khóa chữ Hán cần tìm kiếm. Gõ {C_YELLOW}'q'{C_RESET} hoặc {C_YELLOW}'exit'{C_RESET} để thoát.\n")

    while True:
        try:
            query = input(f"{C_BOLD}{C_CYAN}Nhập chữ Hán cần tìm: {C_RESET}").strip()
            if not query:
                continue
            if query.lower() in ('q', 'exit', 'quit'):
                print(f"\n{C_GREEN}[*] Cảm ơn bạn đã sử dụng công cụ. Tạm biệt!{C_RESET}")
                break
                
            print(f"[*] Đang tìm kiếm thông minh & khớp mờ: '{C_YELLOW}{query}{C_RESET}'...")
            start_time = time.time()
            
            # Tìm kiếm với độ trùng khớp tối thiểu 60%
            all_results = search_in_cache(cached_files, query, min_ratio=0.6)
            elapsed = time.time() - start_time
            
            # Hiển thị kết quả
            if not all_results:
                print(f"\n{C_RED}[!] Không tìm thấy kết quả nào trùng khớp cho từ khóa '{query}'.{C_RESET}\n")
                continue
                
            total_matches = sum(len(f["matches"]) for f in all_results)
            print(f"\n{C_GREEN}[OK] Tìm thấy {total_matches} kết quả trùng khớp >= 60% trong {len(all_results)} file (thời gian: {elapsed:.4f}s):{C_RESET}")
            print(f"{C_GRAY}{'-'*60}{C_RESET}")
            
            for file_idx, item in enumerate(all_results, 1):
                file_link = f"file:///{item['file_path'].as_posix()}"
                print(f"\n{C_BOLD}{C_BLUE}[{file_idx}] Tệp: {item['file_name']} (Khớp lớn nhất: {item['max_score']*100:.1f}%) {C_RESET}")
                print(f"    Đường dẫn: {C_GRAY}{file_link}{C_RESET}")
                for match in item["matches"]:
                    print(f"    {C_YELLOW}Dòng {match['line_num']} (Độ khớp {match['score']*100:.1f}%):{C_RESET} {match['highlighted']}")
            
            print(f"\n{C_CYAN}{'='*60}{C_RESET}\n")
            
        except KeyboardInterrupt:
            print(f"\n\n{C_GREEN}[*] Tạm biệt!{C_RESET}")
            break
        except Exception as e:
            print(f"{C_RED}[!] Lỗi hệ thống: {e}{C_RESET}\n")

if __name__ == "__main__":
    main()
