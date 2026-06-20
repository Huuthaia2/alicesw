import os
import sys
import re
from pathlib import Path

# Configure console to support UTF-8
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CHINESE_RE = re.compile(r'[\u4e00-\u9fff]')

def check_file(f):
    try:
        content = f.read_text(encoding="utf-8", errors="ignore")
        match = CHINESE_RE.search(content)
        if match:
            # If it has Chinese, count them to get ratio
            han_count = len(CHINESE_RE.findall(content))
            ratio = han_count / len(content)
            return f.name, han_count, ratio
    except Exception as e:
        print(f"Error reading {f.name}: {e}")
    return None

def main():
    target_dir = Path("D:/Thư mục mới/alicesw/fsnovel.com/downloaded")
    if not target_dir.exists():
        print(f"Directory not found: {target_dir}")
        return

    txt_files = list(target_dir.glob("*.txt"))
    print(f"Total txt files: {len(txt_files)}")

    with_chinese = []
    for idx, f in enumerate(txt_files):
        res = check_file(f)
        if res:
            with_chinese.append(res)
        if idx % 500 == 0 and idx > 0:
            print(f"Checked {idx}/{len(txt_files)} files...", flush=True)

    # Sort by ratio descending
    with_chinese.sort(key=lambda x: x[2], reverse=True)
    
    # Save report
    report_file = Path("D:/Thư mục mới/alicesw/fsnovel_untranslated_report.txt")
    
    untranslated = [] # ratio >= 0.15
    partially_untranslated = [] # ratio < 0.15
    
    for name, count, ratio in with_chinese:
        if ratio >= 0.15:
            untranslated.append((name, count, ratio))
        else:
            partially_untranslated.append((name, count, ratio))
            
    with open(report_file, "w", encoding="utf-8") as rf:
        rf.write(f"=== FSNOVEL UNTRANSLATED REPORT ===\n")
        rf.write(f"Total files checked: {len(txt_files)}\n")
        rf.write(f"Total files with Chinese characters: {len(with_chinese)}\n")
        rf.write(f"  - Untranslated (>= 15% Chinese): {len(untranslated)}\n")
        rf.write(f"  - Partially Untranslated (< 15% Chinese): {len(partially_untranslated)}\n\n")
        
        rf.write(f"=== UNTRANSLATED FILES (>= 15% Chinese) ===\n")
        for name, count, ratio in untranslated:
            rf.write(f"  {name}: {count} chars ({ratio*100:.2f}%)\n")
            
        rf.write(f"\n=== PARTIALLY UNTRANSLATED FILES (< 15% Chinese) ===\n")
        for name, count, ratio in partially_untranslated:
            rf.write(f"  {name}: {count} chars ({ratio*100:.2f}%)\n")
            
    print(f"Report saved to: {report_file}")
    print(f"Untranslated: {len(untranslated)} files")
    print(f"Partially untranslated: {len(partially_untranslated)} files")

if __name__ == "__main__":
    main()
