import os
import time
import json
from google import genai
from google.genai import types

# Đường dẫn mặc định
SRC_DIR = r"C:\Users\Windows\Documents\MEGA\alicesw\downloaded\translated"
OUT_DIR = r"C:\Users\Windows\Documents\MEGA\alicesw\summaries"
PROGRESS_FILE = r"C:\Users\Windows\Documents\MEGA\alicesw\progress_gemini.json"
KEY_FILE = r"C:\Users\Windows\Documents\MEGA\alicesw\gemini_api_key.txt"

os.makedirs(OUT_DIR, exist_ok=True)

# Lấy API Key từ file hoặc môi trường
api_key = os.environ.get("GEMINI_API_KEY")
if not api_key and os.path.exists(KEY_FILE):
    with open(KEY_FILE, 'r', encoding='utf-8') as kf:
        api_key = kf.read().strip()

if not api_key:
    print(f"❌ KHÔNG TÌM THẤY API KEY!")
    print(f"Vui lòng tạo file chứa API key tại: {KEY_FILE}")
    print(f"Hoặc thiết lập biến môi trường GEMINI_API_KEY.")
    api_key = input("Nhập Gemini API Key của bạn tại đây để tiếp tục: ").strip()
    if api_key:
        with open(KEY_FILE, 'w', encoding='utf-8') as kf:
            kf.write(api_key)

if not api_key:
    print("Không có API Key. Thoát chương trình.")
    exit(1)

client = genai.Client(api_key=api_key)

# Cấu hình tắt toàn bộ bộ lọc an toàn (Safety Settings) để tránh bị chặn truyện 18+
safety_settings = [
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
        threshold=types.HarmBlockThreshold.BLOCK_NONE,
    ),
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
        threshold=types.HarmBlockThreshold.BLOCK_NONE,
    ),
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
        threshold=types.HarmBlockThreshold.BLOCK_NONE,
    ),
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
        threshold=types.HarmBlockThreshold.BLOCK_NONE,
    ),
]

# Đọc tiến độ
progress = {}
if os.path.exists(PROGRESS_FILE):
    try:
        with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
            progress = json.load(f)
    except:
        pass

# Quét file
files_to_process = []
for root, dirs, filenames in os.walk(SRC_DIR):
    for file in filenames:
        if file.lower().endswith('.txt'):
            files_to_process.append(os.path.join(root, file))

# Sắp xếp theo dung lượng tăng dần để xử lý truyện ngắn trước, siêu phẩm sau
files_to_process.sort(key=lambda x: os.path.getsize(x))

print(f"=== HỆ THỐNG TÓM TẮT TRUYỆN GEMINI MIỄN PHÍ ===")
print(f"Tổng số file cần xử lý: {len(files_to_process)}")
print(f"Thư mục lưu kết quả: {OUT_DIR}")
print(f"===============================================")

for idx, filepath in enumerate(files_to_process, 1):
    filename = os.path.basename(filepath)
    
    if progress.get(filename) == "done":
        continue
           retry_count = 0
    success = False
    
    while retry_count < 5 and not success:
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                
            # Cắt bớt nếu file siêu lớn để tránh quá tải token (Giới hạn khoảng 2 triệu ký tự ~ 400.000 từ)
            if len(content) > 2000000:
                print(f"⚠️ Truyện rất dài ({size_mb:.2f} MB). Cắt bớt phần giữa để đảm bảo tóm tắt tối ưu...")
                content = content[:1500000] + "\n\n...[NỘI DUNG GIỮA QUÁ DÀI - BỊ LƯỢC BỚT TRÁNH QUÁ TẢI TOKEN]...\n\n" + content[-500000:]
    
            prompt = f"""
Bạn là một trợ lý phân tích văn học chuyên nghiệp. Hãy đọc tác phẩm sau và viết một bản tóm tắt cực kỳ chi tiết bằng tiếng Việt. Bản tóm tắt CHỈ CẦN tập trung vào hai phần sau đây (vui lòng sử dụng đúng tiêu đề markdown này):
    
### 2. Tóm tắt nội dung cốt lõi (Các luận điểm chính / Tình tiết diễn biến)
(Yêu cầu: Hãy liệt kê đầy đủ, chi tiết và kĩ càng nhất có thể tất cả các tình tiết, sự kiện, biến cố cốt truyện từ đầu đến cuối theo trình tự thời gian hoặc cấu trúc của tác phẩm, không được bỏ sót bất kỳ chi tiết quan trọng nào).
    
### 3. Phân tích các "nhân vật" và mối quan hệ
(Yêu cầu: Liệt kê các nhân vật chính/các chủ thể xuất hiện trong tác phẩm, phân tích sâu sắc đặc điểm tính cách, vai trò của họ và mối quan hệ, sự giằng xé hoặc tương tác qua lại giữa các nhân vật đó).
    
Lưu ý: KHÔNG viết phần Thông tin chung hay phần Nhận xét phong cách. Chỉ trình bày hai phần trên.
    
Nội dung tác phẩm:
{content}
"""
            
            # Gọi API Gemini
            response = client.models.generate_content(
                model='gemini-3.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    safety_settings=safety_settings
                )
            )
            summary_text = response.text
            if summary_text is None or not summary_text.strip():
                finish_reason = ""
                try:
                    if response.candidates:
                        finish_reason = f" (Lý do: {response.candidates[0].finish_reason})"
                except:
                    pass
                raise Exception(f"Nhận phản hồi rỗng từ API hoặc nội dung bị chặn{finish_reason}.")
                
            # Lưu kết quả
            out_filepath = os.path.join(OUT_DIR, filename)
            with open(out_filepath, 'w', encoding='utf-8') as out_f:
                out_f.write(summary_text)
                
            progress[filename] = "done"
            with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
                json.dump(progress, f, ensure_ascii=False, indent=4)
                
            print(f"✅ Đã lưu tóm tắt: {filename}")
            success = True
            
            # Rate limit của Gemini Free là 15 request/phút. Nghỉ 5 giây giữa các lượt.
            time.sleep(5)
            
        except Exception as e:
            print(f"❌ Lỗi khi xử lý file {filename}: {e}")
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                retry_count += 1
                if retry_count < 5:
                    wait_time = 30 + retry_count * 10
                    print(f"⚠️ Đạt Rate Limit của API. Tự động thử lại sau {wait_time} giây... (Lần thử {retry_count}/5)")
                    time.sleep(wait_time)
                else:
                    print(f"❌ Đã thử lại 5 lần đều thất bại do Rate Limit. Bỏ qua file: {filename}")
            else:
                time.sleep(5)
                break  # Lỗi khác thì bỏ qua để tránh lặp vô tận

print("\n🎉 Hoàn thành toàn bộ tiến trình!")
