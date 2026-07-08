#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
webp_to_gif_gui.py — Tool chuyển đổi WebP sang GIF (tĩnh hoặc động), hỗ trợ cả FFmpeg và Pillow.
Giao diện Tkinter hiện đại, tối ưu, đa luồng.
"""

import sys
import shutil
import subprocess
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
try:
    from PIL import Image
    HAS_PILLOW = True
except ImportError:
    Image = None
    HAS_PILLOW = False

# Đảm bảo console Windows xuất UTF-8 tránh lỗi ký tự tiếng Việt
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

FFMPEG = shutil.which("ffmpeg")

def is_animated_webp(file_path: Path) -> bool:
    """Kiểm tra xem file WebP có phải là ảnh động hay không (chứa chunk ANIM)"""
    try:
        with open(file_path, 'rb') as f:
            # Đọc 4096 bytes đầu tiên là đủ để tìm ANIM chunk
            data = f.read(4096)
            return b'ANIM' in data
    except Exception:
        return False

def install_pillow() -> bool:
    """Tự động cài đặt Pillow vào môi trường Python hiện hành"""
    try:
        import subprocess
        # Ẩn cửa sổ console trên Windows khi chạy subprocess
        startupinfo = None
        if sys.platform.startswith("win"):
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
        res = subprocess.run(
            [sys.executable, "-m", "pip", "install", "Pillow"],
            capture_output=True, startupinfo=startupinfo, timeout=60
        )
        return res.returncode == 0
    except Exception:
        return False


class WebPToGIFApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("WebP to GIF Converter — by Antigravity")
        self.geometry("800x600")
        self.resizable(True, True)
        self.configure(bg="#1e1e2e") # Mocha Base Theme
        
        self.selected_files = []
        self.selected_dir = None
        self._stop = False
        
        self._setup_styles()
        self._build_ui()
        self._check_ffmpeg()

    def _setup_styles(self):
        # Thiết lập theme tối và font chữ hiện đại
        self.colors = {
            "bg": "#1e1e2e",
            "card": "#252538",
            "accent": "#89b4fa",
            "accent_hover": "#b4befe",
            "text": "#cdd6f4",
            "text_muted": "#a6adc8",
            "success": "#a6e3a1",
            "fail": "#f38ba8",
            "warning": "#f9e2af"
        }
        
        style = ttk.Style()
        style.theme_use("clam")
        
        # Cấu hình phong cách chung cho các widget
        style.configure("TFrame", background=self.colors["bg"])
        style.configure("Card.TFrame", background=self.colors["card"], relief="flat")
        style.configure("TLabel", background=self.colors["bg"], foreground=self.colors["text"], font=("Segoe UI", 10))
        style.configure("Card.TLabel", background=self.colors["card"], foreground=self.colors["text"], font=("Segoe UI", 10))
        style.configure("Title.TLabel", background=self.colors["bg"], foreground=self.colors["accent"], font=("Segoe UI", 14, "bold"))
        
        # Style cho entry và checkbutton
        style.configure("TEntry", fieldbackground=self.colors["card"], foreground=self.colors["text"], insertcolor=self.colors["text"], bordercolor="#45475a")
        style.configure("TCheckbutton", background=self.colors["bg"], foreground=self.colors["text"])
        style.map("TCheckbutton", background=[("active", self.colors["bg"])], foreground=[("active", self.colors["accent"])])
        
        # Combobox
        style.configure("TCombobox", fieldbackground=self.colors["card"], background=self.colors["card"], foreground=self.colors["text"])
        
        # Progressbar
        style.configure("TProgressbar", thickness=15, troughcolor="#313244", background=self.colors["accent"])

    def _build_ui(self):
        pad = {"padx": 15, "pady": 6}
        
        # Header
        header_fr = ttk.Frame(self)
        header_fr.pack(fill="x", padx=15, pady=10)
        lbl_title = ttk.Label(header_fr, text="🚀 WebP to GIF Converter", style="Title.TLabel")
        lbl_title.pack(side="left")
        
        self.lbl_ffmpeg_status = ttk.Label(header_fr, text="Đang kiểm tra FFmpeg...", font=("Segoe UI", 9, "italic"))
        self.lbl_ffmpeg_status.pack(side="right")

        # ----------------------------------------------------
        # Frame chính: Chia làm cột trái (Cấu hình) và phải (File list & Log)
        # ----------------------------------------------------
        main_body = ttk.Frame(self)
        main_body.pack(fill="both", expand=True, padx=15, pady=5)
        
        # Cột Trái: Controls (320px)
        left_fr = ttk.Frame(main_body, width=320)
        left_fr.pack(side="left", fill="y", padx=(0, 10))
        left_fr.pack_propagate(False)
        
        # --- Group 1: Chọn Nguồn ---
        src_fr = ttk.LabelFrame(left_fr, text=" Chọn nguồn đầu vào ", padding=10)
        src_fr.pack(fill="x", pady=(0, 10))
        
        btn_select_files = tk.Button(src_fr, text="Chọn Files (.webp)", command=self._select_files,
                                     bg="#313244", fg=self.colors["text"], activebackground="#45475a",
                                     activeforeground=self.colors["accent"], font=("Segoe UI", 9, "bold"), relief="flat", bd=0, height=2)
        btn_select_files.pack(fill="x", pady=4)
        
        btn_select_dir = tk.Button(src_fr, text="Chọn Thư mục chứa WebP", command=self._select_dir,
                                   bg="#313244", fg=self.colors["text"], activebackground="#45475a",
                                   activeforeground=self.colors["accent"], font=("Segoe UI", 9, "bold"), relief="flat", bd=0, height=2)
        btn_select_dir.pack(fill="x", pady=4)
        
        # Entry hiển thị đường dẫn đã chọn hoặc cho phép dán đường dẫn
        lbl_path = ttk.Label(src_fr, text="Đường dẫn nguồn:")
        lbl_path.pack(anchor="w", pady=(8, 2))
        self.ent_src_path = ttk.Entry(src_fr)
        self.ent_src_path.pack(fill="x")
        self.ent_src_path.bind("<KeyRelease>", self._on_path_entry_change)

        # --- Group 2: Cấu hình Output ---
        cfg_fr = ttk.LabelFrame(left_fr, text=" Cấu hình GIF đầu ra ", padding=10)
        cfg_fr.pack(fill="x", pady=(0, 10))
        
        # Engine
        ttk.Label(cfg_fr, text="Công cụ chuyển đổi:").pack(anchor="w", pady=2)
        self.var_engine = tk.StringVar(value="FFmpeg" if FFMPEG else "Pillow")
        self.cb_engine = ttk.Combobox(cfg_fr, textvariable=self.var_engine, values=["FFmpeg", "Pillow"], state="readonly")
        self.cb_engine.pack(fill="x", pady=(0, 8))
        
        # Max Scale Width (Giúp tối ưu size cho game mobile)
        ttk.Label(cfg_fr, text="Độ rộng tối đa (Width px, 0 = giữ nguyên):").pack(anchor="w", pady=2)
        self.var_scale_width = tk.StringVar(value="0")
        self.cb_scale = ttk.Combobox(cfg_fr, textvariable=self.var_scale_width, values=["0", "256", "320", "512", "720", "1080"])
        self.cb_scale.pack(fill="x", pady=(0, 8))

        # Speed Multiplier
        ttk.Label(cfg_fr, text="Tốc độ GIF (Hệ số nhân):").pack(anchor="w", pady=2)
        self.var_speed = tk.StringVar(value="1.0")
        self.cb_speed = ttk.Combobox(cfg_fr, textvariable=self.var_speed, values=["0.5", "1.0", "1.25", "1.5", "2.0"], state="readonly")
        self.cb_speed.pack(fill="x", pady=(0, 8))
        
        # Optimize size (Chỉ có tác dụng với Pillow)
        self.var_optimize = tk.BooleanVar(value=True)
        self.chk_optimize = ttk.Checkbutton(cfg_fr, text="Tối ưu dung lượng (Optimize)", variable=self.var_optimize)
        self.chk_optimize.pack(anchor="w", pady=4)
        
        # Overwrite existing GIF
        self.var_overwrite = tk.BooleanVar(value=True)
        self.chk_overwrite = ttk.Checkbutton(cfg_fr, text="Ghi đè file GIF đã tồn tại", variable=self.var_overwrite)
        self.chk_overwrite.pack(anchor="w", pady=4)

        # Delete source WebP on success
        self.var_delete_source = tk.BooleanVar(value=True)
        self.chk_delete_source = ttk.Checkbutton(cfg_fr, text="Xóa file WebP gốc sau khi thành công", variable=self.var_delete_source)
        self.chk_delete_source.pack(anchor="w", pady=4)

        # Output Folder Options
        ttk.Label(cfg_fr, text="Thư mục lưu kết quả:").pack(anchor="w", pady=(8, 2))
        self.var_out_mode = tk.StringVar(value="same_as_input")
        self.rb_same_dir = ttk.Radiobutton(cfg_fr, text="Cùng thư mục với file WebP gốc", variable=self.var_out_mode, value="same_as_input", command=self._toggle_custom_out)
        self.rb_same_dir.pack(anchor="w", pady=2)
        self.rb_custom_dir = ttk.Radiobutton(cfg_fr, text="Thư mục tự chọn bên dưới...", variable=self.var_out_mode, value="custom", command=self._toggle_custom_out)
        self.rb_custom_dir.pack(anchor="w", pady=2)
        
        self.ent_out_path = ttk.Entry(cfg_fr, state="disabled")
        self.ent_out_path.pack(fill="x", pady=2)
        self.btn_browse_out = tk.Button(cfg_fr, text="Chọn Thư mục Lưu", command=self._select_out_dir,
                                        bg="#313244", fg=self.colors["text"], activebackground="#45475a",
                                        activeforeground=self.colors["accent"], font=("Segoe UI", 8), relief="flat", bd=0, state="disabled")
        self.btn_browse_out.pack(anchor="e", pady=2)

        # Cột Phải: Logs & Files queue
        right_fr = ttk.Frame(main_body)
        right_fr.pack(side="right", fill="both", expand=True)
        
        # Queue / Status labels
        stats_fr = ttk.Frame(right_fr)
        stats_fr.pack(fill="x", pady=(0, 6))
        self.lbl_queue = ttk.Label(stats_fr, text="Danh sách chuyển đổi: 0 file", font=("Segoe UI", 10, "bold"))
        self.lbl_queue.pack(side="left")
        
        # Action Buttons
        self.btn_start = tk.Button(stats_fr, text="Bắt đầu Convert", command=self._start_conversion,
                                   bg="#a6e3a1", fg="#11111b", activebackground="#b4befe",
                                   font=("Segoe UI", 10, "bold"), relief="flat", padx=15, pady=4)
        self.btn_start.pack(side="right", padx=5)
        
        self.btn_stop = tk.Button(stats_fr, text="Dừng lại", command=self._on_stop,
                                  bg="#f38ba8", fg="#11111b", activebackground="#b4befe",
                                  font=("Segoe UI", 10, "bold"), relief="flat", padx=15, pady=4, state="disabled")
        self.btn_stop.pack(side="right", padx=5)

        # Log & Text area
        self.txt_log = scrolledtext.ScrolledText(right_fr, state="disabled", font=("Consolas", 9), bg="#181825", fg=self.colors["text"], insertbackground=self.colors["text"])
        self.txt_log.pack(fill="both", expand=True, pady=(0, 8))
        self.txt_log.tag_config("ok", foreground=self.colors["success"])
        self.txt_log.tag_config("fail", foreground=self.colors["fail"])
        self.txt_log.tag_config("warn", foreground=self.colors["warning"])
        self.txt_log.tag_config("info", foreground=self.colors["accent"])
        
        # Progress Bar
        self.progress = ttk.Progressbar(right_fr, mode="determinate")
        self.progress.pack(fill="x", pady=(0, 5))
        self.lbl_current_file = ttk.Label(right_fr, text="Sẵn sàng.", font=("Segoe UI", 9, "italic"), foreground=self.colors["text_muted"])
        self.lbl_current_file.pack(anchor="w")

    def _check_ffmpeg(self):
        if FFMPEG:
            self.lbl_ffmpeg_status.configure(text="✓ Đã tìm thấy FFmpeg", foreground=self.colors["success"])
            self.log("[Hệ thống] Đã tìm thấy FFmpeg trong hệ thống. Đề xuất sử dụng FFmpeg để chất lượng GIF tốt nhất.", "ok")
            if not HAS_PILLOW:
                self.cb_engine.configure(values=["FFmpeg"], state="readonly")
                self.var_engine.set("FFmpeg")
                self.log("[Hệ thống] Lưu ý: Không tìm thấy thư viện Pillow. Chế độ chuyển đổi Pillow đã bị vô hiệu hóa.", "warn")
        else:
            if HAS_PILLOW:
                self.lbl_ffmpeg_status.configure(text="✗ Không tìm thấy FFmpeg (Dùng Pillow)", foreground=self.colors["warning"])
                self.cb_engine.configure(values=["Pillow"], state="readonly")
                self.var_engine.set("Pillow")
                self.log("[Hệ thống] Cảnh báo: Không tìm thấy FFmpeg trong PATH. Mặc định sẽ dùng Pillow (chuyển đổi pure Python).", "warn")
            else:
                self.lbl_ffmpeg_status.configure(text="✗ Thiếu cả FFmpeg & Pillow", foreground=self.colors["fail"])
                self.cb_engine.configure(values=["Không có"], state="disabled")
                self.var_engine.set("Không có")
                self.log("[Hệ thống] LỖI HỆ THỐNG: Máy của bạn thiếu cả công cụ FFmpeg lẫn thư viện Python Pillow!", "fail")
                self.log("[Hệ thống] Vui lòng chạy lệnh sau để cài thư viện Pillow: pip install Pillow", "info")
                messagebox.showerror("Thiếu công cụ", "Ứng dụng phát hiện máy của bạn thiếu cả FFmpeg và thư viện Pillow.\n\nVui lòng cài đặt Pillow (chạy lệnh: pip install Pillow) hoặc cài đặt FFmpeg để sử dụng.")

    def log(self, text, tag=""):
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", text + "\n", tag)
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def _toggle_custom_out(self):
        if self.var_out_mode.get() == "custom":
            self.ent_out_path.configure(state="normal")
            self.btn_browse_out.configure(state="normal", bg="#313244")
        else:
            self.ent_out_path.configure(state="disabled")
            self.btn_browse_out.configure(state="disabled", bg="#1e1e2e")

    def _select_files(self):
        files = filedialog.askopenfilenames(
            title="Chọn các file WebP để convert",
            filetypes=[("WebP Images", "*.webp")]
        )
        if files:
            # Loại bỏ nháy đơn/kép và khoảng trắng (Clean Terminal Drag Link rule)
            cleaned_files = [Path(f.strip("'\" ")) for f in files]
            self.selected_files = cleaned_files
            self.selected_dir = None
            
            # Cập nhật UI
            self.ent_src_path.delete(0, tk.END)
            self.ent_src_path.insert(0, str(cleaned_files[0].parent))
            self.lbl_queue.configure(text=f"Danh sách chuyển đổi: {len(cleaned_files)} files")
            self.log(f"[Nguồn] Đã chọn {len(cleaned_files)} file lẻ.", "info")

    def _select_dir(self):
        dir_path = filedialog.askdirectory(title="Chọn thư mục chứa các file WebP")
        if dir_path:
            cleaned_dir = dir_path.strip("'\" ")
            self.selected_dir = Path(cleaned_dir)
            self.selected_files = []
            
            # Cập nhật UI
            self.ent_src_path.delete(0, tk.END)
            self.ent_src_path.insert(0, cleaned_dir)
            self._scan_directory_webp(self.selected_dir)

    def _select_out_dir(self):
        dir_path = filedialog.askdirectory(title="Chọn thư mục lưu file GIF kết quả")
        if dir_path:
            self.ent_out_path.delete(0, tk.END)
            self.ent_out_path.insert(0, dir_path.strip("'\" "))

    def _on_path_entry_change(self, event):
        # Khi user paste hoặc gõ tay đường dẫn vào Entry
        path_str = self.ent_src_path.get().strip("'\" ")
        if not path_str:
            return
        
        path = Path(path_str)
        if path.is_file() and path.suffix.lower() == ".webp":
            self.selected_files = [path]
            self.selected_dir = None
            self.lbl_queue.configure(text="Danh sách chuyển đổi: 1 file")
        elif path.is_dir():
            self.selected_dir = path
            self.selected_files = []
            self._scan_directory_webp(path)
        else:
            self.lbl_queue.configure(text="Đường dẫn nguồn không hợp lệ!")

    def _scan_directory_webp(self, directory: Path):
        try:
            # Quét đệ quy sâu vào các thư mục con (rglob) và hỗ trợ cả chữ hoa/chữ thường (.webp, .WEBP)
            files = sorted([f for f in directory.rglob("*") if f.is_file() and f.suffix.lower() == ".webp"])
            self.selected_files = files
            self.lbl_queue.configure(text=f"Danh sách chuyển đổi: {len(files)} files")
            self.log(f"[Nguồn] Đã tìm thấy {len(files)} file WebP trong thư mục '{directory.name}' (bao gồm tất cả thư mục con).", "info")
        except Exception as e:
            self.log(f"[Lỗi] Không thể quét thư mục: {e}", "fail")

    def _on_stop(self):
        self._stop = True
        self.btn_stop.configure(text="Đang dừng...", state="disabled")
        self.log("[Hệ thống] Đang dừng tác vụ theo yêu cầu...", "warn")

    def _start_conversion(self):
        if not self.selected_files:
            messagebox.showwarning("Cảnh báo", "Vui lòng chọn file WebP hoặc thư mục nguồn chứa WebP trước!")
            return
        
        # Validate output directory
        if self.var_out_mode.get() == "custom":
            out_path_str = self.ent_out_path.get().strip("'\" ")
            if not out_path_str:
                messagebox.showwarning("Cảnh báo", "Vui lòng chọn thư mục lưu kết quả!")
                return
            out_dir = Path(out_path_str)
            if not out_dir.exists():
                try:
                    out_dir.mkdir(parents=True, exist_ok=True)
                except Exception as e:
                    messagebox.showerror("Lỗi", f"Không thể tạo thư mục lưu kết quả: {e}")
                    return
        
        # Khóa các nút điều khiển để tránh click nhiều lần
        self.btn_start.configure(state="disabled", bg="#585b70")
        self.btn_stop.configure(state="normal")
        self._stop = False
        
        # Kiểm tra xem có file WebP động nào cần xử lý không
        has_animated = any(is_animated_webp(f) for f in self.selected_files)
        
        if has_animated and not HAS_PILLOW:
            ans = messagebox.askyesno(
                "Cần thư viện bổ sung",
                "Phát hiện có file WebP động cần chuyển đổi, nhưng FFmpeg không hỗ trợ giải mã WebP động.\n\n"
                "Bạn có muốn ứng dụng tự động cài đặt thư viện Pillow (PIL) để xử lý không?"
            )
            if ans:
                self.log("[Hệ thống] Đang tải và cài đặt Pillow tự động qua pip...", "warn")
                self.lbl_current_file.configure(text="Đang cài đặt thư viện Pillow...")
                threading.Thread(target=self._install_and_start_worker, daemon=True).start()
                return
            else:
                self.log("[Cảnh báo] Người dùng từ chối cài đặt Pillow. Các file WebP động sẽ bị lỗi/bỏ qua.", "warn")
        
        # Chạy trực tiếp trong luồng background
        threading.Thread(target=self._worker_thread, daemon=True).start()

    def _install_and_start_worker(self):
        success = install_pillow()
        if success:
            global HAS_PILLOW, Image
            try:
                from PIL import Image
                HAS_PILLOW = True
                self.log("[Hệ thống] Cài đặt Pillow thành công! Đã kích hoạt chế độ convert WebP động.", "ok")
                self.after(0, lambda: self.cb_engine.configure(values=["FFmpeg", "Pillow"]))
            except Exception as e:
                self.log(f"[Lỗi] Import Pillow thất bại sau khi cài đặt: {e}", "fail")
        else:
            self.log("[Lỗi] Không thể cài đặt Pillow tự động. Vui lòng tự chạy lệnh: pip install Pillow", "fail")
            self.after(0, lambda: messagebox.showerror("Lỗi cài đặt", "Không thể tự động cài đặt Pillow. Các file WebP động sẽ bị lỗi khi convert."))
            
        # Vẫn tiếp tục chạy worker, file động nào bị lỗi sẽ báo riêng lẻ
        self._worker_thread()

    def _worker_thread(self):
        total = len(self.selected_files)
        self.after(0, lambda: self.progress.configure(maximum=total, value=0))
        
        engine = self.var_engine.get()
        out_mode = self.var_out_mode.get()
        custom_out_dir = Path(self.ent_out_path.get().strip("'\" ")) if out_mode == "custom" else None
        
        try:
            scale_w = int(self.var_scale_width.get())
        except ValueError:
            scale_w = 0
            
        try:
            speed_mult = float(self.var_speed.get())
        except ValueError:
            speed_mult = 1.0
            
        optimize = self.var_optimize.get()
        overwrite = self.var_overwrite.get()
        delete_source = self.var_delete_source.get()
        
        self.log(f"\n==========================================", "info")
        self.log(f"[Chạy] Bắt đầu convert {total} files bằng {engine}...", "info")
        self.log(f"[Cấu hình] Scale Width: {'Không' if scale_w == 0 else f'{scale_w}px (Even scale)'} | Speed: {speed_mult}x | Tối ưu: {optimize}", "info")
        self.log(f"==========================================\n", "info")
        
        success_count = 0
        fail_count = 0
        skip_count = 0
        
        start_time = time.time()
        
        for idx, file_path in enumerate(self.selected_files, 1):
            if self._stop:
                self.log("[Hệ thống] Đã dừng chuyển đổi.", "warn")
                break
                
            self.after(0, lambda i=idx, f=file_path.name: self._update_progress_ui(i, f))
            
            # Xác định file output
            if out_mode == "same_as_input":
                gif_path = file_path.with_suffix(".gif")
            else:
                # Nếu quét từ thư mục, ta giữ nguyên cấu trúc thư mục con ở thư mục đích
                if self.selected_dir:
                    try:
                        relative_path = file_path.relative_to(self.selected_dir)
                        gif_path = (custom_out_dir / relative_path).with_suffix(".gif")
                        gif_path.parent.mkdir(parents=True, exist_ok=True)
                    except Exception:
                        gif_path = custom_out_dir / f"{file_path.stem}.gif"
                else:
                    gif_path = custom_out_dir / f"{file_path.stem}.gif"
                
            # Kiểm tra ghi đè
            if gif_path.exists() and not overwrite:
                self.log(f"[{idx}/{total}] ↷ Bỏ qua: {file_path.name} (File GIF đã tồn tại)", "warn")
                skip_count += 1
                continue
                
            # Thực hiện convert
            is_anim = is_animated_webp(file_path)
            
            if is_anim:
                # Nếu là WebP động, bắt buộc dùng Pillow vì FFmpeg không hỗ trợ decode WebP động
                if HAS_PILLOW:
                    self.log(f"[{idx}/{total}] ℹ WebP động → Tự động dùng Pillow để decode: {file_path.name}", "info")
                    err = self._convert_via_pillow(file_path, gif_path, scale_w, speed_mult, optimize)
                else:
                    err = "FFmpeg không hỗ trợ giải mã WebP động, và máy chưa cài thư viện Pillow (PIL)."
            else:
                # WebP tĩnh, dùng engine đã cấu hình
                if engine == "FFmpeg" and FFMPEG:
                    err = self._convert_via_ffmpeg(file_path, gif_path, scale_w, speed_mult)
                else:
                    err = self._convert_via_pillow(file_path, gif_path, scale_w, speed_mult, optimize)
                
            if err is None:
                # Tính kích thước trước và sau để báo cáo
                try:
                    size_in = file_path.stat().st_size / (1024 * 1024)
                    size_out = gif_path.stat().st_size / (1024 * 1024)
                    ratio = (1 - size_out / size_in) * 100
                    self.log(f"[{idx}/{total}] ✓ Thành công: {file_path.name} ({size_in:.2f}MB → {size_out:.2f}MB, giảm {ratio:.1f}%)", "ok")
                except Exception:
                    self.log(f"[{idx}/{total}] ✓ Thành công: {file_path.name}", "ok")
                
                # Xóa file WebP gốc nếu được chọn
                if delete_source:
                    try:
                        file_path.unlink()
                        self.log(f"      🗑 Đã xóa file gốc: {file_path.name}", "info")
                    except Exception as e:
                        self.log(f"      [Lỗi] Không thể xóa file gốc: {e}", "warn")
                        
                success_count += 1
            else:
                self.log(f"[{idx}/{total}] ✗ Lỗi: {file_path.name} — {err}", "fail")
                fail_count += 1
                
        elapsed = time.time() - start_time
        summary = f"\n[Hoàn tất] Tổng thời gian: {elapsed:.2f}s | Thành công: {success_count} | Lỗi: {fail_count} | Bỏ qua: {skip_count}"
        self.log(summary, "info" if fail_count == 0 else "warn")
        
        # Reset UI
        self.after(0, self._reset_ui_after_job)

    def _update_progress_ui(self, index, filename):
        self.progress.configure(value=index)
        self.lbl_current_file.configure(text=f"Đang xử lý [{index}/{len(self.selected_files)}]: {filename}")

    def _reset_ui_after_job(self):
        self.btn_start.configure(state="normal", bg="#a6e3a1")
        self.btn_stop.configure(state="disabled")
        self.lbl_current_file.configure(text="Hoàn thành!")

    # ----------------------------------------------------
    # Core Logic 1: Convert WebP to GIF via FFmpeg
    # ----------------------------------------------------
    def _convert_via_ffmpeg(self, in_path: Path, out_path: Path, scale_width: int, speed_mult: float) -> str:
        try:
            # Xây dựng bộ lọc filter_complex của FFmpeg để có bảng màu tối ưu (lanczos + palettegen/paletteuse)
            # Dùng filter_complex giúp xử lý độ trong suốt (transparency) cực tốt của WebP sang GIF.
            filters = []
            
            # 1. Xử lý speed multiplier (setpts)
            if speed_mult != 1.0:
                # PTS/speed_mult tăng tốc độ, ví dụ speed=2.0 -> PTS/2 -> chạy nhanh gấp đôi
                filters.append(f"setpts=PTS/{speed_mult}")
            
            # 2. Xử lý scaling (tỉ lệ giữ nguyên, width chẵn để tránh lỗi encoder - FFmpeg Even Scale)
            if scale_width > 0:
                filters.append(f"scale={scale_width}:-2:flags=lanczos")
            
            # Gom bộ lọc chuẩn
            filter_str = ",".join(filters) if filters else ""
            
            # Phân tách để gen palette nhằm tối ưu màu sắc GIF (split[a][b]; [a]palettegen[p]; [b][p]paletteuse)
            # Điều này giúp tránh hiện tượng vỡ màu của GIF
            if filter_str:
                filter_complex = f"[0:v]{filter_str},split[a][b];[a]palettegen=stats_mode=single[p];[b][p]paletteuse=new=1"
            else:
                filter_complex = "[0:v]split[a][b];[a]palettegen=stats_mode=single[p];[b][p]paletteuse=new=1"
                
            cmd = [
                FFMPEG, "-y",
                "-i", str(in_path),
                "-filter_complex", filter_complex,
                str(out_path)
            ]
            
            # Chạy command ẩn cửa sổ console trên Windows
            startupinfo = None
            if sys.platform.startswith("win"):
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                
            res = subprocess.run(cmd, capture_output=True, startupinfo=startupinfo, timeout=120)
            if res.returncode != 0:
                err_msg = res.stderr.decode("utf-8", errors="ignore")
                return err_msg.strip()
            return None
        except subprocess.TimeoutExpired:
            return "FFmpeg quá thời gian xử lý (timeout 120s)."
        except Exception as e:
            return str(e)

    # ----------------------------------------------------
    # Core Logic 2: Convert WebP to GIF via Pillow (Pure Python)
    # ----------------------------------------------------
    def _convert_via_pillow(self, in_path: Path, out_path: Path, scale_width: int, speed_mult: float, optimize: bool) -> str:
        if not HAS_PILLOW:
            return "Thư viện Pillow (PIL) chưa được cài đặt trong môi trường Python này."
        try:
            im = Image.open(in_path)
            is_animated = getattr(im, "is_animated", False) and im.n_frames > 1
            
            # Hàm phụ trợ resize giữ đúng aspect ratio và bảo đảm chiều cao chẵn
            def resize_frame(frame, width):
                if width <= 0:
                    return frame
                w, h = frame.size
                ratio = h / w
                new_h = int(width * ratio)
                # Đảm bảo chiều cao chẵn (để đồng bộ quy tắc tối ưu)
                if new_h % 2 != 0:
                    new_h += 1
                return frame.resize((width, new_h), Image.Resampling.LANCZOS)
            
            if is_animated:
                frames = []
                durations = []
                
                # Trích xuất và convert từng frame
                for i in range(im.n_frames):
                    im.seek(i)
                    frame_copy = im.copy()
                    
                    # Resize nếu được cấu hình
                    if scale_width > 0:
                        frame_copy = resize_frame(frame_copy, scale_width)
                        
                    # Chuyển sang RGBA để xử lý transparency đồng đều
                    if frame_copy.mode != "RGBA":
                        frame_copy = frame_copy.convert("RGBA")
                        
                    # Tính toán thời gian hiển thị frame (áp dụng speed multiplier)
                    dur = frame_copy.info.get("duration", 100)
                    dur = int(max(10, dur / speed_mult))
                    durations.append(dur)
                    
                    # Convert sang palette mode 'P'
                    # Để có độ trong suốt chất lượng tốt, ta dùng tính năng tự thích ứng của Pillow
                    # và dùng disposal=2 lúc lưu để frame trước không đè lên frame sau.
                    frames.append(frame_copy)
                
                # Lưu tất cả các frame thành file GIF động
                frames[0].save(
                    out_path,
                    save_all=True,
                    append_images=frames[1:],
                    duration=durations,
                    loop=im.info.get("loop", 0),
                    optimize=optimize,
                    disposal=2 # Rất quan trọng để tránh lưu ảnh ma (trail/ghosting) khi có transparency
                )
            else:
                # Ảnh tĩnh
                if scale_width > 0:
                    im = resize_frame(im, scale_width)
                
                if im.mode == "RGBA":
                    p_im = im.convert("P", palette=Image.Palette.ADAPTIVE, colors=256)
                    p_im.save(out_path, optimize=optimize)
                else:
                    im.save(out_path, optimize=optimize)
                    
            return None
        except Exception as e:
            return str(e)


if __name__ == "__main__":
    app = WebPToGIFApp()
    app.mainloop()
