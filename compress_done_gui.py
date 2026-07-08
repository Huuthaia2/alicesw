#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
compress_done_gui.py — Nén MP3 trong thư mục Done -> 32kbps, có cửa sổ tiến độ.
"""

import shutil
import subprocess
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk, scrolledtext

TARGET_DIR = Path(r"C:\Users\Windows\Documents\MEGA\Python\alicesw\downloaded\mp3\File5-10Mb\Done")
BITRATE    = "32k"
TARGET_KBPS = 32
MIN_AGE_SEC = 5
FFMPEG  = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


def get_bitrate_kbps(path: Path):
    if not FFPROBE:
        return None
    try:
        r = subprocess.run(
            [FFPROBE, "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=bit_rate",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, timeout=15
        )
        val = r.stdout.strip()
        if val:
            return int(val) // 1000
    except Exception:
        pass
    return None


def compress(src: Path) -> bool:
    tmp = src.with_suffix(".tmp.mp3")
    try:
        r = subprocess.run(
            [FFMPEG, "-y", "-i", str(src),
             "-codec:a", "libmp3lame", "-b:a", BITRATE,
             "-map_metadata", "0", str(tmp)],
            capture_output=True, timeout=180
        )
        if r.returncode != 0:
            tmp.unlink(missing_ok=True)
            return False
        tmp.replace(src)
        return True
    except Exception:
        tmp.unlink(missing_ok=True)
        return False


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("MP3 Compressor — Done folder")
        self.geometry("700x480")
        self.resizable(True, True)
        self._build_ui()
        self._stop = False
        self.after(200, self._start_worker)

    def _build_ui(self):
        pad = {"padx": 10, "pady": 4}

        # Stats row
        stats_fr = tk.Frame(self)
        stats_fr.pack(fill="x", **pad)
        self._lbl_total  = tk.Label(stats_fr, text="Tổng: –",  anchor="w", width=14)
        self._lbl_ok     = tk.Label(stats_fr, text="✓ OK: 0",  anchor="w", width=12, fg="#1a7a1a")
        self._lbl_skip   = tk.Label(stats_fr, text="↷ Skip: 0", anchor="w", width=12, fg="#888")
        self._lbl_fail   = tk.Label(stats_fr, text="✗ Lỗi: 0", anchor="w", width=12, fg="#c0392b")
        for w in (self._lbl_total, self._lbl_ok, self._lbl_skip, self._lbl_fail):
            w.pack(side="left")

        # Progress bar
        self._progress = ttk.Progressbar(self, mode="determinate")
        self._progress.pack(fill="x", padx=10, pady=2)

        # Current file label
        self._lbl_cur = tk.Label(self, text="Đang quét...", anchor="w",
                                  wraplength=680, justify="left")
        self._lbl_cur.pack(fill="x", padx=10)

        # Log
        self._log = scrolledtext.ScrolledText(self, state="disabled",
                                               font=("Consolas", 9), height=20)
        self._log.pack(fill="both", expand=True, padx=10, pady=4)
        self._log.tag_config("ok",   foreground="#1a7a1a")
        self._log.tag_config("skip", foreground="#888888")
        self._log.tag_config("fail", foreground="#c0392b")
        self._log.tag_config("info", foreground="#2255aa")

        # Stop button
        self._btn = tk.Button(self, text="Dừng", command=self._on_stop,
                               bg="#e74c3c", fg="white", font=("Arial", 10, "bold"))
        self._btn.pack(pady=6)

    def _log_line(self, text, tag=""):
        self._log.configure(state="normal")
        self._log.insert("end", text + "\n", tag)
        self._log.see("end")
        self._log.configure(state="disabled")

    def _on_stop(self):
        self._stop = True
        self._btn.configure(text="Đang dừng...", state="disabled")

    def _start_worker(self):
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        if not FFMPEG:
            self.after(0, self._log_line, "[!] Không tìm thấy ffmpeg trong PATH.", "fail")
            return
        if not TARGET_DIR.exists():
            self.after(0, self._log_line, f"[!] Không tìm thấy thư mục:\n{TARGET_DIR}", "fail")
            return

        files = sorted(TARGET_DIR.glob("*.mp3"))
        total = len(files)
        if total == 0:
            self.after(0, self._log_line, f"[i] Không có file .mp3 nào trong:\n{TARGET_DIR}", "info")
            return

        self.after(0, lambda: self._lbl_total.configure(text=f"Tổng: {total}"))
        self.after(0, lambda: self._progress.configure(maximum=total))
        self.after(0, self._log_line, f"[i] Thư mục: {TARGET_DIR}", "info")
        self.after(0, self._log_line, f"[i] Tổng file: {total}", "info")

        ok = fail = skip = 0
        for i, f in enumerate(files, 1):
            if self._stop:
                self.after(0, self._log_line, "— Đã dừng theo yêu cầu —", "info")
                break

            label = f"[{i}/{total}] {f.name}"
            self.after(0, lambda l=label: self._lbl_cur.configure(text=l))
            self.after(0, lambda v=i: self._progress.configure(value=v))

            # check file ổn định
            age = time.time() - f.stat().st_mtime
            if age < MIN_AGE_SEC:
                msg = f"↷  {f.name}  (đang ghi, bỏ qua)"
                self.after(0, self._log_line, msg, "skip")
                skip += 1
                self.after(0, lambda s=skip: self._lbl_skip.configure(text=f"↷ Skip: {s}"))
                continue

            cur_kbps = get_bitrate_kbps(f)
            if cur_kbps is not None and cur_kbps <= TARGET_KBPS:
                msg = f"↷  {f.name}  (đã {cur_kbps}kbps)"
                self.after(0, self._log_line, msg, "skip")
                skip += 1
                self.after(0, lambda s=skip: self._lbl_skip.configure(text=f"↷ Skip: {s}"))
                continue

            size_before = f.stat().st_size
            kbps_str = f"{cur_kbps}kbps" if cur_kbps else "?kbps"
            if compress(f):
                size_after = f.stat().st_size
                saved = (1 - size_after / size_before) * 100
                msg = f"✓  {f.name}  ({size_before/1e6:.2f}MB {kbps_str} → {size_after/1e6:.2f}MB, -{saved:.0f}%)"
                self.after(0, self._log_line, msg, "ok")
                ok += 1
                self.after(0, lambda o=ok: self._lbl_ok.configure(text=f"✓ OK: {o}"))
            else:
                msg = f"✗  {f.name}  FAIL"
                self.after(0, self._log_line, msg, "fail")
                fail += 1
                self.after(0, lambda e=fail: self._lbl_fail.configure(text=f"✗ Lỗi: {e}"))

        summary = f"\nHoàn thành: {ok} OK  |  {skip} skip  |  {fail} lỗi  /  {total} file"
        self.after(0, self._log_line, summary, "info")
        self.after(0, lambda: self._lbl_cur.configure(text="✓ Xong!"))
        self.after(0, lambda: self._btn.configure(text="Đóng", bg="#2c3e50", state="normal",
                                                   command=self.destroy))


if __name__ == "__main__":
    App().mainloop()
