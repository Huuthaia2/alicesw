import re
import json
from pathlib import Path
import sys

# Thêm thư mục hiện tại vào sys.path để import alicesw_downloader
sys.path.insert(0, str(Path.cwd()))
from alicesw_downloader import translate_title, clean_title

def get_novel_id_from_file(filepath):
    try:
        text = filepath.read_text(encoding="utf-8")
        m = re.search(r"Nguồ[nN]\s*:\s*https://www.alicesw.com/novel/(\d+)\.html", text)
        if m:
            return m.group(1)
    except Exception as e:
        print(f"Lỗi đọc file {filepath.name}: {e}")
    return None

def has_chinese(text):
    return any('\u4e00' <= c <= '\u9fff' for c in text)

def main():
    origin_dir = Path("downloaded/origin")
    translated_dir = Path("downloaded/translated")
    
    origin_progress_path = Path("downloaded/_origin_progress.json")
    translate_progress_path = Path("downloaded/translated/_translate_progress.json")
    
    # Load progress files
    origin_progress = {}
    if origin_progress_path.exists():
        with open(origin_progress_path, "r", encoding="utf-8") as f:
            origin_progress = json.load(f)
            
    translate_progress = {}
    if translate_progress_path.exists():
        with open(translate_progress_path, "r", encoding="utf-8") as f:
            translate_progress = json.load(f)
            
    # Lặp qua các file trong downloaded/origin
    for f in sorted(origin_dir.iterdir()):
        if f.suffix != ".txt" or not has_chinese(f.name):
            continue
            
        print(f"\n==================================================")
        print(f"Đang xử lý file gốc: {f.name}")
        
        # 1. Tìm novel_id
        novel_id = get_novel_id_from_file(f)
        if not novel_id:
            print(f"[!] Không tìm thấy novel_id trong file!")
            continue
        print(f"-> Novel ID: {novel_id}")
        
        # 2. Phân tích tên file hiện tại
        stem = f.stem
        # Nhận diện số chương và hậu tố
        m = re.match(r"^(.*?)\+(\d+)\s+Chuong(_origin)?(_end)?$", stem, re.IGNORECASE)
        if not m:
            print(f"[!] Tên file không đúng định dạng chuẩn: {f.name}")
            continue
            
        cn_title = m.group(1).strip()
        total_chapters = m.group(2)
        is_origin_suffix = m.group(3) or ""
        is_end_suffix = m.group(4) or ""
        
        # 3. Dịch tiêu đề
        vi_title = translate_title(cn_title)
        
        # Bổ sung sửa đổi đặc biệt (Manual Override)
        if "扶她" in cn_title or "扶她的世界" in cn_title:
            vi_title = "Chào mừng đến với thế giới Futa"
        
        vi_title = clean_title(vi_title).strip("_ ")
        print(f"-> Tiêu đề tiếng Trung: {cn_title}")
        print(f"-> Tiêu đề dịch tiếng Việt: {vi_title}")
        
        # 4. Tạo tên file mới cho file origin
        new_origin_name = f"{vi_title}+{total_chapters} Chuong{is_origin_suffix}{is_end_suffix}.txt"
        new_origin_path = f.with_name(new_origin_name)
        
        # 5. Cập nhật header bên trong file origin
        try:
            text = f.read_text(encoding="utf-8")
            lines = text.splitlines()
            if len(lines) >= 3 and lines[0].startswith("==="):
                lines[1] = f"  {vi_title}"
                new_text = "\n".join(lines)
                f.write_text(new_text, encoding="utf-8")
                print(f"[OK] Đã cập nhật tiêu đề dòng 2 bên trong file origin.")
        except Exception as e:
            print(f"[!] Lỗi cập nhật header file origin: {e}")
            
        # 6. Đổi tên file origin trên đĩa
        if new_origin_path.exists() and new_origin_path != f:
            print(f"[!] File đích đã tồn tại: {new_origin_name}. Xóa file cũ...")
            f.unlink()
        else:
            f.rename(new_origin_path)
            print(f"[OK] Đã đổi tên file origin -> {new_origin_name}")
            
        # 7. Cập nhật _origin_progress.json
        if novel_id in origin_progress:
            origin_progress[novel_id] = new_origin_name
            print(f"[OK] Đã cập nhật _origin_progress.json cho ID {novel_id}.")
            
        # 8. Xử lý file dịch (trong downloaded/translated) tương ứng
        # Thường file dịch có tên là: cn_title+total_chapters Chuong[_end].txt
        # Chúng ta cần tìm file dịch tương ứng và đổi tên
        translated_file_found = None
        
        # Tìm trong translate_progress ("done" hoặc "failed")
        old_trans_name = None
        for category in ["done", "failed"]:
            cat_dict = translate_progress.get(category, {})
            for orig_k, v in cat_dict.items():
                # Kiểm tra xem key trong translate_progress có chứa cn_title và khớp số chương không
                if cn_title in orig_k and f"+{total_chapters} Chuong" in orig_k:
                    old_trans_name = v.get("out")
                    break
            if old_trans_name:
                break
                
        # Nếu tìm thấy hoặc tìm trực tiếp trên đĩa
        if old_trans_name:
            trans_path = translated_dir / old_trans_name
            if trans_path.exists():
                translated_file_found = trans_path
        else:
            # Tìm trực tiếp trên đĩa theo dạng chứa cn_title
            for tf in translated_dir.iterdir():
                if tf.suffix == ".txt" and cn_title in tf.name and f"+{total_chapters} Chuong" in tf.name:
                    translated_file_found = tf
                    old_trans_name = tf.name
                    break
                    
        if translated_file_found:
            print(f"-> Tìm thấy file dịch tương ứng: {translated_file_found.name}")
            
            # Tạo tên file dịch mới
            # File dịch mới sẽ có tên là: vi_title+total_chapters Chuong[_end].txt
            m_trans = re.match(r"^(.*?)\+(\d+)\s+Chuong(_end)?$", translated_file_found.stem, re.IGNORECASE)
            is_trans_end = ""
            if m_trans:
                is_trans_end = m_trans.group(3) or ""
            new_trans_name = f"{vi_title}+{total_chapters} Chuong{is_trans_end}.txt"
            new_trans_path = translated_file_found.with_name(new_trans_name)
            
            # Cập nhật header bên trong file dịch
            try:
                t_text = translated_file_found.read_text(encoding="utf-8")
                t_lines = t_text.splitlines()
                if len(t_lines) >= 3 and t_lines[0].startswith("==="):
                    t_lines[1] = f"  {vi_title}"
                    new_t_text = "\n".join(t_lines)
                    translated_file_found.write_text(new_t_text, encoding="utf-8")
                    print(f"[OK] Đã cập nhật tiêu đề dòng 2 bên trong file dịch.")
            except Exception as e:
                print(f"[!] Lỗi cập nhật header file dịch: {e}")
                
            # Đổi tên file dịch trên đĩa
            if new_trans_path.exists() and new_trans_path != translated_file_found:
                print(f"[!] File dịch đích đã tồn tại: {new_trans_name}. Xóa file cũ...")
                translated_file_found.unlink()
            else:
                translated_file_found.rename(new_trans_path)
                print(f"[OK] Đã đổi tên file dịch -> {new_trans_name}")
                
            # Cập nhật _translate_progress.json
            # Cần cập nhật cả key (tên file origin cũ -> mới) và giá trị out (tên file dịch cũ -> mới)
            updated_progress = False
            for category in ["done", "failed"]:
                cat_dict = translate_progress.setdefault(category, {})
                for orig_k in list(cat_dict.keys()):
                    if cn_title in orig_k and f"+{total_chapters} Chuong" in orig_k:
                        # Tạo key mới bằng cách thay cn_title bằng vi_title
                        new_orig_k = orig_k.replace(cn_title, vi_title)
                        val = cat_dict.pop(orig_k)
                        val["out"] = new_trans_name
                        cat_dict[new_orig_k] = val
                        print(f"[OK] Đã cập nhật _translate_progress.json ({category}) cho file dịch.")
                        updated_progress = True
                        break
                if updated_progress:
                    break
        else:
            print(f"[?] Không tìm thấy file dịch tương ứng cho truyện này.")
            
    # Save progress files
    if origin_progress:
        with open(origin_progress_path, "w", encoding="utf-8") as f:
            json.dump(origin_progress, f, ensure_ascii=False, indent=2)
            print(f"\n[OK] Đã lưu _origin_progress.json")
            
    if translate_progress:
        with open(translate_progress_path, "w", encoding="utf-8") as f:
            json.dump(translate_progress, f, ensure_ascii=False, indent=2)
            print(f"[OK] Đã lưu _translate_progress.json")

if __name__ == "__main__":
    main()
