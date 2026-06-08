import json
import re
import sys
from pathlib import Path

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

trans_dir = Path("downloaded/translated")
origin_dir = Path("downloaded/origin")

progress_translate_path = trans_dir / "_translate_progress.json"
progress_translated_done_path = Path("downloaded/_translated_progress.json")
progress_translated_failed_path = Path("downloaded/_translated_failed.json")

def load_json(p):
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

def save_json(p, data):
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

progress_trans = load_json(progress_translate_path)
progress_translated_done = load_json(progress_translated_done_path)
progress_translated_failed = load_json(progress_translated_failed_path)

done_trans = progress_trans.setdefault("done", {})
failed_trans = progress_trans.setdefault("failed", {})

print("============================================================")
print("  ĐỒNG BỘ TIẾN ĐỘ DỊCH THUẬT TỪ THƯ MỤC TRANSLATED")
print("============================================================")

added_count = 0
sync_trans_count = 0

for txt_file in trans_dir.glob("*.txt"):
    if txt_file.name.startswith("_"):
        continue
    
    # 1. Parse novel_id from header
    novel_id = None
    novel_url = None
    try:
        with open(txt_file, "r", encoding="utf-8", errors="ignore") as f:
            for _ in range(25):
                line = f.readline()
                if not line:
                    break
                line_strip = line.strip()
                if "Nguồn" in line_strip or "Nguon" in line_strip:
                    parts = line_strip.split(":", 1)
                    if len(parts) > 1:
                        novel_url = parts[1].strip()
                        break
    except Exception:
        pass
        
    if novel_url:
        match = re.search(r"novel/(\d+)\.html", novel_url)
        if match:
            novel_id = match.group(1)
            
    # 2. Match corresponding origin file to get origin_name and size/mtime signature
    origin_name = None
    stem = txt_file.stem
    
    # Try direct mapping first
    if stem.endswith("_end"):
        candidate = stem.replace("_end", "") + "_origin_end.txt"
    else:
        candidate = stem + "_origin.txt"
        
    origin_path = origin_dir / candidate
    if origin_path.exists():
        origin_name = candidate
    else:
        # Try finding closest match in origin
        clean_txt_name = txt_file.name.replace("_end.txt", ".txt")
        for orig in origin_dir.glob("*.txt"):
            if orig.name.startswith("_"):
                continue
            clean_orig_name = orig.name.replace("_origin", "").replace("_end", "").replace("_origin_end", "")
            if clean_orig_name == clean_txt_name:
                origin_name = orig.name
                origin_path = orig
                break

    # 3. Synchronize status
    updated_any = False
    if novel_id:
        if novel_id not in progress_translated_done:
            progress_translated_done[novel_id] = txt_file.name
            progress_translated_failed.pop(novel_id, None)
            print(f"[+] Đồng bộ: {txt_file.name} -> novel_id {novel_id}")
            added_count += 1
            updated_any = True
            
    if origin_name and origin_path:
        if origin_name not in done_trans:
            st = origin_path.stat()
            done_trans[origin_name] = {
                "size": st.st_size,
                "mtime": int(st.st_mtime),
                "out": txt_file.name
            }
            failed_trans.pop(origin_name, None)
            print(f"[+] Đồng bộ tiến độ gốc: {origin_name} -> {txt_file.name}")
            sync_trans_count += 1
            updated_any = True

save_json(progress_translate_path, progress_trans)
save_json(progress_translated_done_path, progress_translated_done)
save_json(progress_translated_failed_path, progress_translated_failed)

print("------------------------------------------------------------")
print(f"[OK] Đã hoàn tất đồng bộ:")
print(f"  - Thêm {added_count} truyện vào _translated_progress.json")
print(f"  - Thêm {sync_trans_count} truyện vào _translate_progress.json")
