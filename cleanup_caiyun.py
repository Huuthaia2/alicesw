import json
from pathlib import Path
import re
import sys
import shutil

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

trans_dir = Path("downloaded/translated")
origin_dir = Path("downloaded/origin")
mp3_dir = Path("downloaded/mp3")
cache_root = Path("downloaded/.cache_translate")

progress_translate_path = trans_dir / "_translate_progress.json"
progress_translated_done_path = Path("downloaded/_translated_progress.json")
progress_translated_failed_path = Path("downloaded/_translated_failed.json")
progress_tts_path = mp3_dir / "_tts_progress.json"

# Read arguments
delete_mode = "--delete" in sys.argv

print("============================================================")
print("  DỌN DẸP BẢN DỊCH VÀ FILE MP3 TẠO BỞI ENGINE CAIYUN")
print(f"  Chế độ: {'THỰC THI XÓA (--delete)' if delete_mode else 'MÔ PHỎNG (DRY-RUN)'}")
print("============================================================")

if not trans_dir.exists():
    print(f"[!] Thư mục dịch {trans_dir} không tồn tại.")
    sys.exit(1)

# Load JSON files
def load_json(p):
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[!] Lỗi đọc file JSON {p.name}: {e}")
    return {}

progress_trans = load_json(progress_translate_path)
progress_translated_done = load_json(progress_translated_done_path)
progress_translated_failed = load_json(progress_translated_failed_path)
progress_tts = load_json(progress_tts_path)

done_trans = progress_trans.setdefault("done", {})
failed_trans = progress_trans.setdefault("failed", {})

done_tts = progress_tts.setdefault("done", {})
failed_tts = progress_tts.setdefault("failed", {})

# Scan translated directory
caiyun_files = []
for txt_file in trans_dir.glob("*.txt"):
    if txt_file.name.startswith("_"):
        continue
    
    # Read first 15 lines to find the translation engine
    engine = None
    novel_url = None
    try:
        with open(txt_file, "r", encoding="utf-8", errors="ignore") as f:
            for _ in range(25):
                line = f.readline()
                if not line:
                    break
                line_strip = line.strip()
                if "Dịch" in line_strip or "Engine" in line_strip:
                    parts = line_strip.split(":", 1)
                    if len(parts) > 1:
                        engine = parts[1].strip()
                if "Nguồn" in line_strip:
                    parts = line_strip.split(":", 1)
                    if len(parts) > 1:
                        novel_url = parts[1].strip()
    except Exception as e:
        print(f"[!] Lỗi đọc file {txt_file.name}: {e}")
        continue
        
    if engine and "caiyun" in engine.lower():
        # Match novel_id from url
        novel_id = None
        if novel_url:
            match = re.search(r"novel/(\d+)\.html", novel_url)
            if match:
                novel_id = match.group(1)
        
        # Look up corresponding origin_name in progress_trans
        origin_name = None
        for orig, val in done_trans.items():
            if val.get("out") == txt_file.name:
                origin_name = orig
                break
                
        # Fallback if not found in done_trans (construct candidate names)
        if not origin_name:
            stem_clean = txt_file.stem
            # e.g. "Name+5 Chuong_end" -> "Name+5 Chuong_origin_end.txt"
            if stem_clean.endswith("_end"):
                candidate = stem_clean.replace("_end", "") + "_origin_end.txt"
            else:
                candidate = stem_clean + "_origin.txt"
            if (origin_dir / candidate).exists():
                origin_name = candidate
                
        caiyun_files.append({
            "txt_path": txt_file,
            "novel_id": novel_id,
            "origin_name": origin_name,
            "engine": engine
        })

print(f"Tìm thấy {len(caiyun_files)} file đã dịch bằng Caiyun:")
for idx, item in enumerate(caiyun_files, 1):
    txt_path = item["txt_path"]
    engine = item["engine"]
    novel_id = item["novel_id"]
    origin_name = item["origin_name"]
    print(f"  {idx:2d}. {txt_path.name} | Engine: {engine} | novel_id: {novel_id or '?'} | origin: {origin_name or '?'}")

if not caiyun_files:
    print("[*] Không có file nào cần dọn dẹp.")
    sys.exit(0)

# Helper function to clean output stem name (copied from txt_to_mp3.py)
def clean_title(name: str) -> str:
    name = re.sub(r"\[[^\]]*\]", " ", name)
    name = re.sub(r"[【】\[\]]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    if name:
        name = name[0].upper() + name[1:].lower()
    return name

def output_stem(stem: str) -> str:
    m = re.match(r"^(.*?)(\+\d+\s*Chuong.*)$", stem)
    if m:
        return clean_title(m.group(1)) + m.group(2)
    return clean_title(stem)

if delete_mode:
    deleted_txt_count = 0
    deleted_mp3_count = 0
    deleted_cache_count = 0
    
    for item in caiyun_files:
        txt_path = item["txt_path"]
        novel_id = item["novel_id"]
        origin_name = item["origin_name"]
        
        # 1. Delete translated file
        if txt_path.exists():
            txt_path.unlink()
            deleted_txt_count += 1
            
        # 2. Delete MP3 file
        mp3_name = f"{output_stem(txt_path.stem)}.mp3"
        mp3_path = mp3_dir / mp3_name
        if mp3_path.exists():
            mp3_path.unlink()
            deleted_mp3_count += 1
            
        # 3. Delete translation cache folder
        if novel_id:
            novel_cache_dir = cache_root / novel_id
            if novel_cache_dir.exists():
                import stat
                import os
                def remove_readonly(func, path, excinfo):
                    try:
                        os.chmod(path, stat.S_IWRITE)
                        func(path)
                    except Exception:
                        pass
                try:
                    shutil.rmtree(novel_cache_dir, onerror=remove_readonly)
                    deleted_cache_count += 1
                except Exception as e:
                    print(f"  [!] Khong the xoa cache truyen {novel_id}: {e}")
                
        # 4. Delete MP3 chunk cache folder
        mp3_cache_dir = mp3_dir / ".cache" / txt_path.stem
        if mp3_cache_dir.exists():
            import stat
            import os
            def remove_readonly(func, path, excinfo):
                try:
                    os.chmod(path, stat.S_IWRITE)
                    func(path)
                except Exception:
                    pass
            try:
                shutil.rmtree(mp3_cache_dir, onerror=remove_readonly)
            except Exception:
                pass
            
        # 5. Clean JSONs
        if origin_name:
            done_trans.pop(origin_name, None)
            failed_trans.pop(origin_name, None)
            
        if novel_id:
            progress_translated_done.pop(novel_id, None)
            progress_translated_failed.pop(novel_id, None)
            
        done_tts.pop(txt_path.name, None)
        failed_tts.pop(txt_path.name, None)
        
    # Save JSON files
    def save_json(p, data):
        try:
            p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"[!] Lỗi ghi file JSON {p.name}: {e}")
            
    save_json(progress_translate_path, progress_trans)
    save_json(progress_translated_done_path, progress_translated_done)
    save_json(progress_translated_failed_path, progress_translated_failed)
    save_json(progress_tts_path, progress_tts)
    
    print("\n[OK] Đã hoàn tất dọn dẹp:")
    print(f"  - Đã xóa {deleted_txt_count} file .txt dịch.")
    print(f"  - Đã xóa {deleted_mp3_count} file .mp3.")
    print(f"  - Đã xóa {deleted_cache_count} thư mục cache dịch.")
    print("  - Đã cập nhật lại trạng thái các file tiến độ JSON.")
else:
    print("\n[*] Đây là bản MÔ PHỎNG. Vui lòng chạy lại lệnh dưới đây để thực thi xóa:")
    print("    python cleanup_caiyun.py --delete")
