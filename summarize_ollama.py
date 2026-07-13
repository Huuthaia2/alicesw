import os
import json
import requests
import time

OLLAMA_API_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "qwen2.5:3b"  # Nhẹ (~1.9GB), tiếng Việt tốt. Máy khỏe có thể đổi lại "qwen2.5:7b"

SRC_DIR = r"C:\Users\Windows\Documents\MEGA\alicesw\downloaded\translated"
OUT_DIR = r"C:\Users\Windows\Documents\MEGA\alicesw\summaries_local"
PROGRESS_FILE = r"C:\Users\Windows\Documents\MEGA\alicesw\progress_ollama.json"

os.makedirs(OUT_DIR, exist_ok=True)

progress = {}
if os.path.exists(PROGRESS_FILE):
    try:
        with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
            progress = json.load(f)
    except:
        pass

files_to_process = []
for root, dirs, filenames in os.walk(SRC_DIR):
    for file in filenames:
        if file.lower().endswith('.txt'):
            files_to_process.append(os.path.join(root, file))

# Sắp xếp theo kích thước file tăng dần
files_to_process.sort(key=lambda x: os.path.getsize(x))

print(f"=== HỆ THỐNG TÓM TẮT TRUYỆN LOCAL OLLAMA ===")
print(f"Tổng số file cần xử lý: {len(files_to_process)}")
print(f"Thư mục lưu kết quả: {OUT_DIR}")
print(f"Model sử dụng: {MODEL_NAME}")
print(f"===========================================")

# Kiểm tra kết nối tới Ollama
try:
    test_res = requests.get("http://localhost:11434/", timeout=5)
    print("Ollama đang hoạt động bình thường.")
except:
    print("❌ LỖI: Không thể kết nối tới Ollama!")
    print("Vui lòng khởi động Ollama trên máy của bạn trước khi chạy script.")
    exit(1)

for idx, filepath in enumerate(files_to_process, 1):
    filename = os.path.basename(filepath)
    
    if progress.get(filename) == "done":
        continue
        
    size_mb = os.path.getsize(filepath) / (1024 * 1024)
    print(f"\n[{idx}/{len(files_to_process)}] Đang xử lý: {filename} ({size_mb:.2f} MB)...")
    
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
            
        # Model cục bộ giới hạn context window nhỏ hơn.
        # Chúng ta trích xuất khoảng 15.000 ký tự đầu và 5.000 ký tự cuối của văn bản để tránh tràn context.
        if len(content) > 30000:
            print(f"⚠️ Truyện dài ({size_mb:.2f} MB). Cắt bớt phần giữa để tránh tràn bộ nhớ cục bộ...")
            content = content[:20000] + "\n\n...[NỘI DUNG Ở GIỮA BỊ LƯỢC BỚT ĐỂ TRÁNH TRÀN BỘ NHỚ CỦA OLLAMA]...\n\n" + content[-10000:]

        prompt = f"""
Hãy đọc tác phẩm sau và viết một bản tóm tắt chi tiết bằng tiếng Việt bao gồm:
1. Thông tin chung (Tên truyện nếu có, số chương).
2. Tóm tắt cốt truyện cốt lõi (Các biến cố chính, nút thắt, kết cục).
3. Các nhân vật chính và mối quan hệ.
4. Nhận xét thể loại truyện.

Nội dung tác phẩm:
{content}
"""
        
        payload = {
            "model": MODEL_NAME,
            "prompt": prompt,
            "stream": False
        }
        
        # Gửi request đến Ollama
        start_time = time.time()
        response = requests.post(OLLAMA_API_URL, json=payload, timeout=600)
        elapsed = time.time() - start_time
        
        if response.status_code != 200:
            raise Exception(f"Lỗi phản hồi từ Ollama API: {response.status_code}")
            
        response_json = response.json()
        summary_text = response_json.get("response", "")
        
        if not summary_text.strip():
            raise Exception("Nhận phản hồi rỗng từ Ollama.")
            
        out_filepath = os.path.join(OUT_DIR, f"Summary_{filename}")
        with open(out_filepath, 'w', encoding='utf-8') as out_f:
            out_f.write(summary_text)
            
        progress[filename] = "done"
        with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
            json.dump(progress, f, ensure_ascii=False, indent=4)
            
        print(f"✅ Đã lưu tóm tắt (mất {elapsed:.1f} giây): Summary_{filename}")
        
    except Exception as e:
        print(f"❌ Lỗi khi xử lý file {filename}: {e}")
        time.sleep(2)

print("\n🎉 Hoàn thành toàn bộ tiến trình bằng Ollama!")
