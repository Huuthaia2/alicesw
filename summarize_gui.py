import os
import time
import json
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter.scrolledtext import ScrolledText

import requests

# Thử import google-genai, nếu chưa có sẽ cảnh báo trên GUI
try:
    from google import genai
    from google.genai import types
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

# Cấu hình Ollama (local)
OLLAMA_API_URL = "http://localhost:11434/api/generate"
OLLAMA_BASE_URL = "http://localhost:11434/"
OLLAMA_MODELS = ["qwen2.5:3b", "qwen2.5:7b", "gemma2:2b", "llama3.2:3b"]
# Cửa sổ context cho Ollama (mặc định của Ollama chỉ 2048 → phải tăng để model đọc hết truyện).
# Máy yếu có thể giảm xuống 8192; máy khỏe có thể tăng lên 32768.
OLLAMA_NUM_CTX = 16384

# Chế độ chuẩn bị nội dung trước khi đưa vào model
MODE_CUT = "Cắt 30 KB (đầu + cuối)"
MODE_SAMPLE = "Trích mẫu theo chương (2k/chương + 5k cuối)"
CONTENT_MODES = [MODE_CUT, MODE_SAMPLE]

# Thứ tự xử lý file
SORT_SHORT_FIRST = "Ngắn nhất trước"
SORT_LONG_FIRST = "Dài nhất trước"
SORT_ORDERS = [SORT_SHORT_FIRST, SORT_LONG_FIRST]

# Tông màu giao diện Dark Mode hiện đại
COLOR_BG = "#121212"          # Nền chính
COLOR_SURFACE = "#1e1e1e"     # Nền khung điều khiển
COLOR_TEXT = "#e0e0e0"        # Chữ sáng
COLOR_ACCENT = "#007acc"      # Màu xanh nhấn
COLOR_ACCENT_HOVER = "#0098ff"
COLOR_SUCCESS = "#2ea043"     # Màu xanh lá hoàn thành
COLOR_ERROR = "#f85149"       # Màu đỏ lỗi
COLOR_BORDER = "#30363d"      # Viền

class SummarizerGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        
        self.title("AliceSW - Bộ Công Cụ Tóm Tắt Truyện Bằng AI")
        self.geometry("900x700")
        self.configure(bg=COLOR_BG)
        
        # Biến điều khiển luồng
        self.is_running = False
        self.thread = None
        self.stop_requested = False
        
        # Cấu hình Style cho các widget của ttk
        self.setup_styles()
        
        # Tạo giao diện
        self.create_widgets()
        
        # Tải cấu hình cũ (nếu có)
        self.load_config()
        
        # Kiểm tra thư viện (Gemini là tùy chọn — vẫn có thể dùng Ollama local)
        if not GEMINI_AVAILABLE:
            self.log_message("ℹ️ Chưa cài 'google-genai' — chỉ dùng được nguồn Ollama (local).")
            self.log_message("   Muốn dùng Gemini: chạy 'pip install google-genai'.")

    def setup_styles(self):
        style = ttk.Style()
        style.theme_use('default')
        
        # Style cho Progressbar
        style.configure("TProgressbar",
                        thickness=15,
                        troughcolor=COLOR_SURFACE,
                        background=COLOR_ACCENT,
                        bordercolor=COLOR_BORDER,
                        lightcolor=COLOR_ACCENT,
                        darkcolor=COLOR_ACCENT)

    def create_widgets(self):
        # 1. Khung cấu hình trên cùng (Cấu hình đường dẫn, API Key)
        config_frame = tk.Frame(self, bg=COLOR_SURFACE, bd=1, relief=tk.FLAT, highlightbackground=COLOR_BORDER, highlightthickness=1)
        config_frame.pack(fill=tk.X, padx=15, pady=15)
        
        # Tiêu đề khung cấu hình
        tk.Label(config_frame, text="CẤU HÌNH HỆ THỐNG", font=("Segoe UI", 11, "bold"), bg=COLOR_SURFACE, fg=COLOR_ACCENT).grid(row=0, column=0, columnspan=3, sticky="w", padx=15, pady=10)

        # Nguồn AI: Gemini (cloud) hoặc Ollama (local)
        tk.Label(config_frame, text="Nguồn AI:", font=("Segoe UI", 9), bg=COLOR_SURFACE, fg=COLOR_TEXT).grid(row=1, column=0, sticky="e", padx=15, pady=5)
        self.combo_source = ttk.Combobox(config_frame, font=("Segoe UI", 10), state="readonly", values=["Gemini (cloud)", "Ollama (local)"])
        self.combo_source.current(0)
        self.combo_source.grid(row=1, column=1, sticky="ew", padx=5, pady=5)
        self.combo_source.bind("<<ComboboxSelected>>", self.on_source_change)

        # Nhãn & Ô nhập API Key (chỉ dùng cho Gemini)
        self.lbl_api_key = tk.Label(config_frame, text="Gemini API Key:", font=("Segoe UI", 9), bg=COLOR_SURFACE, fg=COLOR_TEXT)
        self.lbl_api_key.grid(row=2, column=0, sticky="e", padx=15, pady=5)
        self.entry_api_key = tk.Entry(config_frame, font=("Segoe UI", 10), bg="#2d2d2d", fg=COLOR_TEXT, bd=0, insertbackground=COLOR_TEXT, width=50)
        self.entry_api_key.grid(row=2, column=1, sticky="ew", padx=5, pady=5)

        # Chọn model Ollama (chỉ dùng cho Ollama)
        self.lbl_ollama_model = tk.Label(config_frame, text="Model Ollama:", font=("Segoe UI", 9), bg=COLOR_SURFACE, fg=COLOR_TEXT)
        self.combo_ollama_model = ttk.Combobox(config_frame, font=("Segoe UI", 10), values=OLLAMA_MODELS)
        self.combo_ollama_model.set(OLLAMA_MODELS[0])
        # Mặc định ẩn (chỉ hiện khi chọn Ollama) — sẽ được on_source_change bật/tắt

        # Ô nhập Thư mục nguồn
        tk.Label(config_frame, text="Thư mục truyện:", font=("Segoe UI", 9), bg=COLOR_SURFACE, fg=COLOR_TEXT).grid(row=3, column=0, sticky="e", padx=15, pady=5)
        self.entry_src_dir = tk.Entry(config_frame, font=("Segoe UI", 10), bg="#2d2d2d", fg=COLOR_TEXT, bd=0, insertbackground=COLOR_TEXT, width=50)
        self.entry_src_dir.grid(row=3, column=1, sticky="ew", padx=5, pady=5)
        btn_browse_src = tk.Button(config_frame, text="Chọn thư mục", bg="#3a3a3a", fg=COLOR_TEXT, activebackground="#505050", activeforeground=COLOR_TEXT, bd=0, padx=10, command=self.browse_src_dir)
        btn_browse_src.grid(row=3, column=2, padx=15, pady=5)

        # Ô nhập Thư mục đầu ra
        tk.Label(config_frame, text="Thư mục lưu:", font=("Segoe UI", 9), bg=COLOR_SURFACE, fg=COLOR_TEXT).grid(row=4, column=0, sticky="e", padx=15, pady=5)
        self.entry_out_dir = tk.Entry(config_frame, font=("Segoe UI", 10), bg="#2d2d2d", fg=COLOR_TEXT, bd=0, insertbackground=COLOR_TEXT, width=50)
        self.entry_out_dir.grid(row=4, column=1, sticky="ew", padx=5, pady=5)
        btn_browse_out = tk.Button(config_frame, text="Chọn thư mục", bg="#3a3a3a", fg=COLOR_TEXT, activebackground="#505050", activeforeground=COLOR_TEXT, bd=0, padx=10, command=self.browse_out_dir)
        btn_browse_out.grid(row=4, column=2, padx=15, pady=5)

        # Tick: tóm tắt đè lên file đã tóm tắt trước đó (bỏ qua trạng thái "done")
        self.overwrite_var = tk.BooleanVar(value=False)
        self.chk_overwrite = tk.Checkbutton(
            config_frame, text="Ghi đè file đã tóm tắt (làm lại từ đầu)",
            variable=self.overwrite_var, command=self.save_config,
            font=("Segoe UI", 9), bg=COLOR_SURFACE, fg=COLOR_TEXT,
            activebackground=COLOR_SURFACE, activeforeground=COLOR_TEXT,
            selectcolor="#2d2d2d", bd=0, highlightthickness=0
        )
        self.chk_overwrite.grid(row=5, column=1, sticky="w", padx=5, pady=5)

        # Chế độ chuẩn bị nội dung
        tk.Label(config_frame, text="Chế độ nội dung:", font=("Segoe UI", 9), bg=COLOR_SURFACE, fg=COLOR_TEXT).grid(row=6, column=0, sticky="e", padx=15, pady=5)
        self.combo_mode = ttk.Combobox(config_frame, font=("Segoe UI", 10), state="readonly", values=CONTENT_MODES)
        self.combo_mode.set(MODE_CUT)
        self.combo_mode.grid(row=6, column=1, sticky="ew", padx=5, pady=5)
        self.combo_mode.bind("<<ComboboxSelected>>", lambda e: self.save_config())

        # Thứ tự xử lý file
        tk.Label(config_frame, text="Thứ tự xử lý:", font=("Segoe UI", 9), bg=COLOR_SURFACE, fg=COLOR_TEXT).grid(row=7, column=0, sticky="e", padx=15, pady=5)
        self.combo_sort = ttk.Combobox(config_frame, font=("Segoe UI", 10), state="readonly", values=SORT_ORDERS)
        self.combo_sort.set(SORT_SHORT_FIRST)
        self.combo_sort.grid(row=7, column=1, sticky="ew", padx=5, pady=5)
        self.combo_sort.bind("<<ComboboxSelected>>", lambda e: self.save_config())

        config_frame.columnconfigure(1, weight=1)
        self._model_row = 2  # hàng dùng chung cho API Key (Gemini) / Model (Ollama)

        # 2. Khung trạng thái và tiến trình (Ở giữa)
        status_frame = tk.Frame(self, bg=COLOR_SURFACE, bd=1, relief=tk.FLAT, highlightbackground=COLOR_BORDER, highlightthickness=1)
        status_frame.pack(fill=tk.X, padx=15, pady=5)
        
        self.lbl_status = tk.Label(status_frame, text="Trạng thái: Sẵn sàng", font=("Segoe UI", 10, "bold"), bg=COLOR_SURFACE, fg=COLOR_TEXT)
        self.lbl_status.pack(anchor="w", padx=15, pady=10)
        
        # Thanh tiến trình
        self.progress_bar = ttk.Progressbar(status_frame, orient="horizontal", style="TProgressbar", mode="determinate")
        self.progress_bar.pack(fill=tk.X, padx=15, pady=5)
        
        # Nhãn thống kê chi tiết
        self.lbl_stats = tk.Label(status_frame, text="Tổng số: 0 | Đã xử lý: 0 | Còn lại: 0", font=("Segoe UI", 9), bg=COLOR_SURFACE, fg="#8b949e")
        self.lbl_stats.pack(anchor="w", padx=15, pady=5)

        # 3. Khung Nhật Ký Hoạt Động (Log console)
        log_frame = tk.Frame(self, bg=COLOR_BG)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)
        
        tk.Label(log_frame, text="NHẬT KÝ HOẠT ĐỘNG (LOG)", font=("Segoe UI", 9, "bold"), bg=COLOR_BG, fg=COLOR_TEXT).pack(anchor="w", pady=5)
        
        self.log_area = ScrolledText(log_frame, bg="#0d1117", fg="#c9d1d9", insertbackground="#ffffff", bd=1, relief=tk.FLAT, font=("Consolas", 9))
        self.log_area.pack(fill=tk.BOTH, expand=True)

        # 4. Khung nút nhấn điều khiển (Dưới cùng)
        control_frame = tk.Frame(self, bg=COLOR_BG)
        control_frame.pack(fill=tk.X, padx=15, pady=10)
        
        self.btn_start = tk.Button(control_frame, text="Bắt đầu tóm tắt", font=("Segoe UI", 10, "bold"), bg=COLOR_SUCCESS, fg="#ffffff", activebackground="#2ea043", activeforeground="#ffffff", bd=0, width=18, height=2, command=self.start_process)
        self.btn_start.pack(side=tk.LEFT, padx=5)
        
        self.btn_stop = tk.Button(control_frame, text="Tạm dừng", font=("Segoe UI", 10, "bold"), bg="#3a3a3a", fg=COLOR_TEXT, activebackground="#505050", activeforeground=COLOR_TEXT, bd=0, width=15, height=2, state=tk.DISABLED, command=self.stop_process)
        self.btn_stop.pack(side=tk.LEFT, padx=5)
        
        btn_exit = tk.Button(control_frame, text="Thoát", font=("Segoe UI", 10, "bold"), bg="#f85149", fg="#ffffff", activebackground="#cf3b3b", activeforeground="#ffffff", bd=0, width=12, height=2, command=self.destroy)
        btn_exit.pack(side=tk.RIGHT, padx=5)

    def on_source_change(self, event=None):
        # Chuyển đổi hiển thị giữa cấu hình Gemini (API Key) và Ollama (chọn model)
        source = self.combo_source.get()
        if source.startswith("Ollama"):
            self.lbl_api_key.grid_remove()
            self.entry_api_key.grid_remove()
            self.lbl_ollama_model.grid(row=self._model_row, column=0, sticky="e", padx=15, pady=5)
            self.combo_ollama_model.grid(row=self._model_row, column=1, sticky="ew", padx=5, pady=5)
        else:
            self.lbl_ollama_model.grid_remove()
            self.combo_ollama_model.grid_remove()
            self.lbl_api_key.grid(row=self._model_row, column=0, sticky="e", padx=15, pady=5)
            self.entry_api_key.grid(row=self._model_row, column=1, sticky="ew", padx=5, pady=5)
        self.save_config()

    def browse_src_dir(self):
        dir_selected = filedialog.askdirectory(initialdir=self.entry_src_dir.get())
        if dir_selected:
            self.entry_src_dir.delete(0, tk.END)
            self.entry_src_dir.insert(0, os.path.abspath(dir_selected))
            self.save_config()

    def browse_out_dir(self):
        dir_selected = filedialog.askdirectory(initialdir=self.entry_out_dir.get())
        if dir_selected:
            self.entry_out_dir.delete(0, tk.END)
            self.entry_out_dir.insert(0, os.path.abspath(dir_selected))
            self.save_config()

    def log_message(self, text):
        timestamp = time.strftime("[%H:%M:%S] ")
        self.log_area.insert(tk.END, f"{timestamp}{text}\n")
        self.log_area.see(tk.END)

    def load_config(self):
        config_path = "gui_config.json"
        # Đặt các giá trị mặc định của hệ thống
        self.entry_src_dir.insert(0, r"C:\Users\Windows\Documents\MEGA\alicesw\downloaded\translated")
        self.entry_out_dir.insert(0, r"C:\Users\Windows\Documents\MEGA\alicesw\summaries")
        
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    if config.get("api_key"):
                        self.entry_api_key.insert(0, config["api_key"])
                    if config.get("src_dir"):
                        self.entry_src_dir.delete(0, tk.END)
                        self.entry_src_dir.insert(0, config["src_dir"])
                    if config.get("out_dir"):
                        self.entry_out_dir.delete(0, tk.END)
                        self.entry_out_dir.insert(0, config["out_dir"])
                    if config.get("source") in ("Gemini (cloud)", "Ollama (local)"):
                        self.combo_source.set(config["source"])
                    if config.get("ollama_model"):
                        self.combo_ollama_model.set(config["ollama_model"])
                    self.overwrite_var.set(bool(config.get("overwrite", False)))
                    if config.get("content_mode") in CONTENT_MODES:
                        self.combo_mode.set(config["content_mode"])
                    if config.get("sort_order") in SORT_ORDERS:
                        self.combo_sort.set(config["sort_order"])
            except Exception as e:
                self.log_message(f"Lỗi khi đọc file cấu hình: {e}")

        # Áp dụng hiển thị đúng theo nguồn AI đã nạp
        self.on_source_change()

    def save_config(self):
        config = {
            "api_key": self.entry_api_key.get().strip(),
            "src_dir": self.entry_src_dir.get().strip(),
            "out_dir": self.entry_out_dir.get().strip(),
            "source": self.combo_source.get(),
            "ollama_model": self.combo_ollama_model.get().strip(),
            "overwrite": self.overwrite_var.get(),
            "content_mode": self.combo_mode.get(),
            "sort_order": self.combo_sort.get()
        }
        try:
            with open("gui_config.json", 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=4)
        except Exception as e:
            self.log_message(f"Không thể lưu cấu hình: {e}")

    def update_status(self, text, fg_color=COLOR_TEXT):
        self.lbl_status.config(text=f"Trạng thái: {text}", fg=fg_color)

    def start_process(self):
        source = self.combo_source.get()
        api_key = self.entry_api_key.get().strip()
        ollama_model = self.combo_ollama_model.get().strip()
        src_dir = self.entry_src_dir.get().strip()
        out_dir = self.entry_out_dir.get().strip()
        overwrite = self.overwrite_var.get()
        content_mode = self.combo_mode.get()
        sort_order = self.combo_sort.get()

        if source.startswith("Gemini"):
            if not GEMINI_AVAILABLE:
                messagebox.showerror("Lỗi", "Chưa cài google-genai. Chạy: pip install google-genai")
                return
            if not api_key:
                messagebox.showwarning("Thiếu thông tin", "Vui lòng nhập Gemini API Key của bạn!")
                return
        else:  # Ollama (local)
            if not ollama_model:
                messagebox.showwarning("Thiếu thông tin", "Vui lòng chọn model Ollama!")
                return

        if not os.path.exists(src_dir):
            messagebox.showwarning("Lỗi đường dẫn", "Thư mục truyện không tồn tại!")
            return

        self.save_config()

        # Cấu hình biến điều khiển
        self.is_running = True
        self.stop_requested = False
        self.btn_start.config(state=tk.DISABLED, bg="#555555")
        self.btn_stop.config(state=tk.NORMAL, bg=COLOR_ERROR, text="Tạm dừng")

        # Chạy luồng nền xử lý tóm tắt để tránh đơ giao diện
        self.thread = threading.Thread(target=self.run_summarizer, args=(source, api_key, ollama_model, src_dir, out_dir, overwrite, content_mode, sort_order), daemon=True)
        self.thread.start()

    def stop_process(self):
        if self.is_running:
            self.stop_requested = True
            self.update_status("Đang yêu cầu dừng...", COLOR_ERROR)
            self.log_message("⚠️ Hệ thống đang chờ dừng lượt gọi API hiện tại...")
            self.btn_stop.config(state=tk.DISABLED)

    def run_summarizer(self, source, api_key, ollama_model, src_dir, out_dir, overwrite=False, content_mode=MODE_CUT, sort_order=SORT_SHORT_FIRST):
        is_ollama = source.startswith("Ollama")
        client = None
        safety_settings = None

        # 1. Cấu hình nguồn AI
        if is_ollama:
            try:
                requests.get(OLLAMA_BASE_URL, timeout=5)
                self.log_message(f"✅ Ollama đang hoạt động. Model: {ollama_model}")
            except Exception as e:
                self.log_message(f"❌ Không kết nối được Ollama tại {OLLAMA_BASE_URL}: {e}")
                self.log_message("   Hãy chắc chắn Ollama đang chạy (mở app Ollama hoặc lệnh 'ollama serve').")
                self.safe_finish("Lỗi kết nối Ollama", COLOR_ERROR)
                return
            progress_name = "progress_ollama.json"
        else:
            try:
                client = genai.Client(api_key=api_key)
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
            except Exception as e:
                self.log_message(f"❌ Lỗi cấu hình AI: {e}")
                self.safe_finish("Lỗi cấu hình AI", COLOR_ERROR)
                return
            progress_name = "progress_gemini.json"

        # Tạo thư mục đầu ra nếu chưa tồn tại
        os.makedirs(out_dir, exist_ok=True)

        # 2. Đọc tệp tiến trình
        progress_path = os.path.join(os.path.dirname(out_dir), progress_name)
        progress = {}
        if os.path.exists(progress_path):
            try:
                with open(progress_path, 'r', encoding='utf-8') as f:
                    progress = json.load(f)
            except:
                pass

        # 3. Quét tệp truyện
        files_to_process = []
        for root, dirs, filenames in os.walk(src_dir):
            for file in filenames:
                if file.lower().endswith('.txt'):
                    files_to_process.append(os.path.join(root, file))
        
        # Sắp xếp file theo dung lượng (mặc định nhỏ trước; có thể chọn lớn trước)
        reverse_sort = (sort_order == SORT_LONG_FIRST)
        files_to_process.sort(key=lambda x: os.path.getsize(x), reverse=reverse_sort)

        total_files = len(files_to_process)
        if total_files == 0:
            self.log_message("Không tìm thấy file truyện .txt nào.")
            self.safe_finish("Không có file để xử lý", COLOR_TEXT)
            return

        self.log_message(f"Khởi động thành công! Tìm thấy {total_files} file.")
        self.log_message(f"⚙️ Chế độ nội dung: {content_mode} | Thứ tự: {sort_order}")
        if overwrite:
            self.log_message("♻️ Chế độ GHI ĐÈ: sẽ tóm tắt lại cả những file đã xong trước đó.")
        
        # 4. Vòng lặp chính xử lý tệp
        processed_count = 0
        for idx, filepath in enumerate(files_to_process, 1):
            if self.stop_requested:
                self.log_message("🛑 Đã tạm dừng chương trình bởi người dùng.")
                break
                
            filename = os.path.basename(filepath)
            
            # Cập nhật thanh tiến trình & Thống kê
            progress_pct = (idx / total_files) * 100
            self.progress_bar['value'] = progress_pct
            self.lbl_stats.config(text=f"Tổng số: {total_files} | Đang xử lý: {idx}/{total_files} ({progress_pct:.1f}%) | Thư mục: {filename}")
            
            if not overwrite and progress.get(filename) == "done":
                processed_count += 1
                continue
                
            self.update_status(f"Đang xử lý {idx}/{total_files}...", COLOR_ACCENT)
            size_mb = os.path.getsize(filepath) / (1024 * 1024)
            self.log_message(f"[{idx}/{total_files}] Tóm tắt: {filename} ({size_mb:.2f} MB)")
            
            # Thử lại tối đa 5 lần nếu gặp lỗi 429
            retry_count = 0
            success = False
            
            while retry_count < 5 and not success:
                if self.stop_requested:
                    break
                    
                try:
                    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()

                    # Chuẩn bị nội dung theo chế độ đã chọn (cắt 30 KB hoặc trích mẫu theo chương)
                    content = self.prepare_content(content, is_ollama, content_mode)

                    prompt = f"""
Bạn là một trợ lý phân tích văn học chuyên nghiệp. Hãy đọc tác phẩm sau và viết một bản tóm tắt CỰC KỲ CHI TIẾT bằng tiếng Việt, gồm ĐÚNG HAI PHẦN sau (dùng chính xác tiêu đề markdown bên dưới, đúng thứ tự):

### 1. Phân tích các "nhân vật" và mối quan hệ
(Yêu cầu: Liệt kê tất cả các nhân vật chính/chủ thể xuất hiện trong tác phẩm. Phân tích sâu sắc đặc điểm tính cách, hoàn cảnh, vai trò của từng người, cùng mối quan hệ, mâu thuẫn, sự giằng xé và tương tác qua lại giữa họ.)

### 2. Tóm tắt nội dung cốt lõi (Các luận điểm chính / Tình tiết diễn biến)
(Yêu cầu QUAN TRỌNG NHẤT: Liệt kê ĐẦY ĐỦ, chi tiết và kĩ càng NHẤT CÓ THỂ tất cả các tình tiết, sự kiện, biến cố cốt truyện từ đầu đến cuối, theo đúng trình tự thời gian/cấu trúc của tác phẩm. TUYỆT ĐỐI KHÔNG bỏ sót bất kỳ tình tiết nào, kể cả chi tiết nhỏ hay tình tiết phụ. Trình bày dưới dạng danh sách gạch đầu dòng theo diễn biến, càng nhiều mục càng tốt.)

Lưu ý: KHÔNG viết phần Thông tin chung hay phần Nhận xét phong cách. Chỉ trình bày đúng hai phần trên, đúng thứ tự trên.

Nội dung tác phẩm:
{content}
"""
                    if is_ollama:
                        summary_text = self.generate_ollama(ollama_model, prompt)
                        if not summary_text or not summary_text.strip():
                            raise Exception("Nhận phản hồi rỗng từ Ollama.")
                    else:
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
                            raise Exception(f"Không nhận được phản hồi từ AI hoặc nội dung bị chặn{finish_reason}.")

                    # Lưu tóm tắt
                    out_filepath = os.path.join(out_dir, filename)
                    with open(out_filepath, 'w', encoding='utf-8') as out_f:
                        out_f.write(summary_text)
                    
                    # Lưu tiến độ
                    progress[filename] = "done"
                    with open(progress_path, 'w', encoding='utf-8') as f:
                        json.dump(progress, f, ensure_ascii=False, indent=4)
                    
                    self.log_message(f"   -> Thành công! Đã lưu: {filename}")
                    success = True

                    # Nghỉ tránh rate limit — chỉ cần cho API cloud
                    if not is_ollama:
                        time.sleep(5)

                except Exception as e:
                    self.log_message(f"❌ Lỗi xử lý {filename}: {e}")
                    if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                        retry_count += 1
                        if retry_count < 5:
                            wait_time = 30 + retry_count * 10
                            self.log_message(f"⚠️ Đạt giới hạn gọi API (Rate Limit). Thử lại sau {wait_time} giây... (Lần thử {retry_count}/5)")
                            time.sleep(wait_time)
                        else:
                            self.log_message(f"❌ Đã thử lại 5 lần đều thất bại do Rate Limit. Bỏ qua file: {filename}")
                    else:
                        time.sleep(5)
                        break  # Lỗi khác không phải 429 thì không thử lại, chuyển sang file khác
            
            processed_count += 1
            
        # Kết thúc vòng lặp
        if self.stop_requested:
            self.safe_finish("Đã tạm dừng", COLOR_ERROR)
        else:
            self.progress_bar['value'] = 100
            self.safe_finish("Đã hoàn thành toàn bộ!", COLOR_SUCCESS)

    def prepare_content(self, content, is_ollama, content_mode):
        # Gemini có context lớn: chỉ cắt khi cực lớn, không cần trích mẫu
        if not is_ollama:
            if len(content) > 2000000:
                return content[:1500000] + "\n\n...[NỘI DUNG GIỮA BỊ CẮT TRÁNH TRÀN TOKEN]...\n\n" + content[-500000:]
            return content

        # --- Ollama (context nhỏ) ---
        if content_mode == MODE_SAMPLE:
            # Trích mẫu: 2000 ký tự đầu mỗi chương (tách theo mốc ──────) + 5000 ký tự cuối cả file.
            # Giới hạn tổng ~28000 ký tự để vừa context; chương quá nhiều thì tự co ký tự/chương.
            parts = [p for p in content.split("──────") if p.strip()]
            if len(parts) >= 2:
                # Mỗi chương = ngưỡng ÷ số chương, tối đa 2000 ký tự/chương.
                # Nhờ vậy tổng thân luôn ≤ ngưỡng (vừa context), chương ít được nhiều, chương nhiều tự co.
                budget = 30000  # tổng ngân sách cho phần thân (chưa tính 5000 đuôi)
                per_chapter = min(2000, budget // len(parts))
                samples = []
                for i, ch in enumerate(parts, 1):
                    samples.append(f"--- [Đoạn {i}] ---\n{ch.strip()[:per_chapter]}")
                sampled = "\n\n".join(samples) + "\n\n--- [PHẦN CUỐI TRUYỆN] ---\n" + content[-5000:]
                return sampled
            # Không có mốc chương rõ → rơi về cách cắt thường
        # MODE_CUT (mặc định) hoặc fallback
        if len(content) > 30000:
            return content[:20000] + "\n\n...[NỘI DUNG GIỮA BỊ LƯỢC BỚT ĐỂ TRÁNH TRÀN BỘ NHỚ LOCAL]...\n\n" + content[-10000:]
        return content

    def generate_ollama(self, model, prompt):
        # Gọi Ollama local, trả về text tóm tắt (raise nếu lỗi)
        # num_ctx: bắt buộc đặt để model đọc hết nội dung (mặc định Ollama chỉ 2048 token)
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_ctx": OLLAMA_NUM_CTX}
        }
        response = requests.post(OLLAMA_API_URL, json=payload, timeout=600)
        if response.status_code != 200:
            raise Exception(f"Ollama API trả về mã {response.status_code}")
        return response.json().get("response", "")

    def safe_finish(self, status_text, color):
        # Trả các nút bấm về trạng thái ban đầu một cách an toàn từ luồng nền
        self.is_running = False
        self.btn_start.config(state=tk.NORMAL, bg=COLOR_SUCCESS)
        self.btn_stop.config(state=tk.DISABLED, bg="#3a3a3a", text="Tạm dừng")
        self.update_status(status_text, color)

if __name__ == "__main__":
    app = SummarizerGUI()
    app.mainloop()
