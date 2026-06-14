import os
import sys
import re
import time
import json
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


# Configure console to support UTF-8
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Import fsnovel_downloader
sys.path.insert(0, str(Path(__file__).parent))
try:
    import fsnovel_downloader as fd
    fd._load_glossary()
except ImportError as e:
    print(f"Error importing fsnovel_downloader: {e}")
    sys.exit(1)

# Ensure translators is enabled
fd.ENGINE = "free"  # fallback to caiyun -> google

CHINESE_RE = re.compile(r'[\u4e00-\u9fff]')

def has_chinese(text):
    return bool(CHINESE_RE.search(text))

def translate_block_with_retry(text, retries=3):
    """Translate a block of text, retrying on failure or if Chinese characters remain."""
    if not text.strip():
        return text
    
    for attempt in range(retries):
        try:
            # translate_text returns (translated_text, fail_count)
            translated, fail_count = fd.translate_text(text)
            translated = fd.apply_glossary(translated)
            
            # Check if translation was successful (didn't return original or fail count is 0)
            if fail_count == 0 and not has_chinese(translated):
                return translated
            
            # If failed or still has Chinese, wait and retry
            print(f"  [Warning] Translation attempt {attempt+1} failed or has residual Chinese. Retrying...")
            time.sleep(2 * (attempt + 1))
        except Exception as e:
            print(f"  [Warning] Translation error on attempt {attempt+1}: {e}")
            time.sleep(2 * (attempt + 1))
            
    # If all retries failed, fallback to whatever we got
    try:
        translated, _ = fd.translate_text(text)
        return fd.apply_glossary(translated)
    except Exception:
        return text

def translate_paragraphs_group(paragraphs, is_entire_file=False):
    """Translate a list of paragraphs in groups to minimize API calls."""
    translated_paras = []
    
    # We group paragraphs into blocks of up to 3000 characters to be safe
    current_block = []
    current_length = 0
    
    # helper function to process a block
    def process_block(block_paras):
        block_text = "\n\n".join(block_paras)
        trans_block = translate_block_with_retry(block_text)
        trans_paras = trans_block.split("\n\n")
        
        # If the number of paragraphs matches, return them one-to-one
        if len(trans_paras) == len(block_paras):
            return trans_paras
        else:
            # If not matching, we fallback to translating paragraph-by-paragraph to preserve structure
            print(f"  [Info] Block paragraph count mismatch ({len(trans_paras)} vs {len(block_paras)}). Falling back to paragraph-by-paragraph translation...")
            fallback_paras = []
            for p in block_paras:
                if has_chinese(p):
                    fallback_paras.append(translate_block_with_retry(p))
                else:
                    fallback_paras.append(p)
            return fallback_paras

    # Group paragraphs
    for p in paragraphs:
        # If we are translating the entire file, we group everything
        # If not, we only translate paragraphs that have Chinese
        if is_entire_file or has_chinese(p):
            p_len = len(p)
            if current_length + p_len + 2 > 3000 and current_block:
                translated_paras.extend(process_block(current_block))
                current_block = [p]
                current_length = p_len
            else:
                current_block.append(p)
                current_length += p_len + 2
        else:
            # Flush current block if we hit a Vietnamese paragraph
            if current_block:
                translated_paras.extend(process_block(current_block))
                current_block = []
                current_length = 0
            translated_paras.append(p)
            
    # Flush remaining
    if current_block:
        translated_paras.extend(process_block(current_block))
        
    return translated_paras

def process_file(file_path, state, progress_path):
    print(f"\nProcessing file: {file_path.name}")
    
    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        print(f"Error reading file {file_path.name}: {e}")
        return False
        
    lines = content.splitlines()
    header_end_idx = -1
    
    # Detect header (between '===' lines)
    if len(lines) > 0 and lines[0].startswith("==="):
        for idx in range(1, min(10, len(lines))):
            if lines[idx].startswith("==="):
                header_end_idx = idx
                break
                
    header_lines = []
    body_lines = []
    
    if header_end_idx != -1:
        header_lines = lines[:header_end_idx+1]
        body_lines = lines[header_end_idx+1:]
    else:
        body_lines = lines

    # Reconstruct body text and split by paragraphs (\n\n)
    body_text = "\n".join(body_lines).strip()
    paragraphs = [p.strip() for p in body_text.split("\n\n") if p.strip()]
    
    # Calculate initial Chinese ratio in body
    total_len = max(sum(len(p) for p in paragraphs), 1)
    han_len = sum(len(CHINESE_RE.findall(p)) for p in paragraphs)
    ratio = han_len / total_len
    
    print(f"  Chinese character ratio in body: {ratio*100:.2f}% ({han_len} characters)")
    
    if han_len == 0:
        print("  No Chinese characters in body. Skipping body translation.")
        translated_paras = paragraphs
    else:
        # If ratio is high (e.g. >= 15%), we translate the entire file in groups
        # If low, we only translate paragraphs containing Chinese
        is_entire = ratio >= 0.15
        print(f"  Translating body (is_entire_file={is_entire})...")
        translated_paras = translate_paragraphs_group(paragraphs, is_entire_file=is_entire)

    # Process header
    header_updated = False
    title_vi = ""
    if header_lines:
        new_header_lines = list(header_lines)
        # Line index 1 is usually the title line: "  <Title>"
        if len(new_header_lines) >= 3:
            title_line = new_header_lines[1]
            title_text = title_line.strip()
            if has_chinese(title_text):
                print(f"  Translating header title: {title_text}")
                title_vi = fd.translate_title(title_text)
                title_vi = fd.apply_glossary(title_vi)
                new_header_lines[1] = f"  {title_vi}"
                header_updated = True
                print(f"  => {title_vi}")
            else:
                title_vi = title_text
                
            # Line index 4 is usually Tags
            for h_idx in range(2, len(new_header_lines)):
                if "Tags" in new_header_lines[h_idx]:
                    tags_line = new_header_lines[h_idx]
                    if has_chinese(tags_line):
                        print(f"  Translating header tags: {tags_line}")
                        parts = tags_line.split(":", 1)
                        if len(parts) == 2:
                            tags_cn = [t.strip() for t in parts[1].split(",")]
                            tags_vi_list = [fd._tag_vi(t) for t in tags_cn]
                            new_header_lines[h_idx] = f"  Tags       : {', '.join(tags_vi_list)}"
                            header_updated = True
        header_lines = new_header_lines

    # Construct final content
    header_text = "\n".join(header_lines) if header_lines else ""
    body_translated_text = "\n\n".join(translated_paras)
    final_content = ""
    if header_text:
        final_content = header_text + "\n\n" + body_translated_text + "\n"
    else:
        final_content = body_translated_text + "\n"
        
    # Write to a temporary file first, then replace
    temp_path = file_path.with_suffix(".tmp")
    try:
        temp_path.write_text(final_content, encoding="utf-8")
    except Exception as e:
        print(f"Error writing temp file: {e}")
        return False
        
    # Double check if we need to rename the file (if filename contains Chinese or title changed)
    original_name = file_path.name
    new_name = original_name
    
    # If the filename itself has Chinese, we rename it using title_vi or translate the filename
    if has_chinese(original_name):
        if title_vi:
            clean_title = fd.sanitize_filename(title_vi)
            new_name = f"{clean_title}.txt"
        else:
            print(f"  Translating filename: {original_name}")
            translated_name = fd.translate_title(original_name.replace(".txt", ""))
            new_name = fd.sanitize_filename(translated_name) + ".txt"
            
    new_file_path = file_path.parent / new_name
    
    # Rename and replace
    try:
        # Backup original
        backup_path = file_path.with_suffix(".bak")
        if file_path.exists():
            shutil.copy2(file_path, backup_path)
            
        # Replace original with temp
        if file_path.exists():
            file_path.unlink()
        temp_path.rename(new_file_path)
        
        # Remove backup if successful
        if backup_path.exists():
            backup_path.unlink()
            
        print(f"  [OK] Successfully saved: {new_name}")
    except Exception as e:
        print(f"  [ERR] Error renaming/saving file: {e}")
        if temp_path.exists():
            temp_path.unlink()
        return False

    # Sync progress file if filename changed
    if new_name != original_name:
        with state_lock:
            updated_progress = False
            # Find the URL that maps to the original name and update it
            for url, fname in list(state["done"].items()):
                if fname == original_name:
                    state["done"][url] = new_name
                    updated_progress = True
                    print(f"  [OK] Updated progress.json: '{original_name}' -> '{new_name}'")
                    
            if updated_progress:
                try:
                    progress_path.write_text(json.dumps(state["done"], ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
                except Exception as e:
                    print(f"  [Warning] Error writing progress.json: {e}")
                
    return True

state_lock = threading.Lock()

def main():
    target_dir = Path("D:/Thư mục mới/alicesw/fsnovel.com/downloaded")
    progress_path = target_dir / "_progress.json"
    
    state = {"done": {}, "failed": {}}
    if progress_path.exists():
        try:
            state["done"] = json.loads(progress_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"Error reading progress file: {e}")
            
    # Read the report to find files with Chinese characters
    report_path = Path("D:/Thư mục mới/alicesw/fsnovel_untranslated_report.txt")
    if not report_path.exists():
        print(f"Report not found at {report_path}. Run _check_fsnovel_untranslated.py first.")
        return
        
    report_content = report_path.read_text(encoding="utf-8")
    
    # Find files listed under both UNTRANSLATED and PARTIALLY UNTRANSLATED sections
    files_to_process = []
    lines = report_content.splitlines()
    
    collect = False
    for line in lines:
        if "=== UNTRANSLATED FILES" in line or "=== PARTIALLY UNTRANSLATED FILES" in line:
            collect = True
            continue
        if collect:
            line_strip = line.strip()
            if not line_strip:
                continue
            # Match line starting with spaces and filename: "  Name.txt: X chars (Y%)"
            match = re.match(r"^(.+?\.txt):\s*\d+\s*chars", line_strip)
            if match:
                fname = match.group(1).strip()
                fpath = target_dir / fname
                if fpath.exists():
                    files_to_process.append(fpath)
                    
    print(f"Found {len(files_to_process)} files to translate from report.")
    
    limit = 10
    is_all = False
    if len(sys.argv) > 1 and sys.argv[1] == "--all":
        limit = len(files_to_process)
        is_all = True
        print("Running in '--all' mode. Processing all files in parallel (5 workers).")
    else:
        print(f"Processing first {limit} files for testing. Run with '--all' to process all files.")
        
    success_count = 0
    if is_all:
        def task_wrapper(args):
            idx, fpath = args
            print(f"\n[{idx}/{len(files_to_process)}] Starting: {fpath.name}")
            ok = process_file(fpath, state, progress_path)
            if ok:
                print(f"[{idx}/{len(files_to_process)}] Finished successfully: {fpath.name}")
            else:
                print(f"[{idx}/{len(files_to_process)}] Failed: {fpath.name}")
            return ok

        tasks = list(enumerate(files_to_process[:limit], 1))
        with ThreadPoolExecutor(max_workers=5) as executor:
            results = list(executor.map(task_wrapper, tasks))
        success_count = sum(1 for r in results if r)
    else:
        for idx, fpath in enumerate(files_to_process[:limit], 1):
            print(f"\n--- [{idx}/{min(limit, len(files_to_process))}] ---")
            ok = process_file(fpath, state, progress_path)
            if ok:
                success_count += 1
            
    print(f"\nFinished processing. Successful: {success_count}/{min(limit, len(files_to_process))}")

if __name__ == "__main__":
    main()

