#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
compress_mp3_gui.py — Giao diện (UI) nén MP3 xuống 32kbps, ghi đè tại chỗ.

Chạy:
  py compress_mp3_gui.py

Cửa sổ cho phép: chọn thư mục, đặt bitrate, quét thư mục con, xem log tiến trình,
bấm Bắt đầu / Dừng. File đã <= bitrate mục tiêu sẽ được bỏ qua.
"""

import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

# Tái dùng logic nén đã kiểm thử trong compress_mp3.py
from compress_mp3 import FFMPEG, is_stable, get_bitrate_kbps, compress


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Nén MP3 → 32kbps")
        self.geometry("720x520")
        self.minsize(600, 440)

        self.folder = tk.StringVar()
        self.bitrate = tk.StringVar(value="32k")
        self.recursive = tk.BooleanVar(value=False)
        self.min_age = tk.IntVar(value=10)

        self._worker = None
        self._stop = threading.Event()
        self._log_q = queue.Queue()

        self._build_ui()
        self.after(100, self._drain_log)

    # ---------- UI ----------
    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}
        frm = ttk.Frame(self)
        frm.pack(fill="x", **pad)

        ttk.Label(frm, text="Thư mục:").grid(row=0, column=0, sticky="w")
        ent = ttk.Entry(frm, textvariable=self.folder)
        ent.grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(frm, text="Chọn…", command=self._pick).grid(row=0, column=2)
        frm.columnconfigure(1, weight=1)

        opt = ttk.Frame(self)
        opt.pack(fill="x", **pad)
        ttk.Label(opt, text="Bitrate:").pack(side="left")
        ttk.Combobox(opt, textvariable=self.bitrate, width=6,
                     values=["16k", "24k", "32k", "48k", "64k", "96k", "128k"],
                     state="readonly").pack(side="left", padx=(4, 16))
        ttk.Checkbutton(opt, text="Gồm thư mục con", variable=self.recursive).pack(side="left")
        ttk.Label(opt, text="   Bỏ qua file vừa sửa (giây):").pack(side="left")
        ttk.Spinbox(opt, from_=0, to=600, textvariable=self.min_age, width=5).pack(side="left")

        btns = ttk.Frame(self)
        btns.pack(fill="x", **pad)
        self.btn_start = ttk.Button(btns, text="▶  Bắt đầu", command=self._start)
        self.btn_start.pack(side="left")
        self.btn_stop = ttk.Button(btns, text="■  Dừng", command=self._request_stop, state="disabled")
        self.btn_stop.pack(side="left", padx=6)

        self.progress = ttk.Progressbar(self, mode="determinate")
        self.progress.pack(fill="x", **pad)
        self.status = ttk.Label(self, text="Sẵn sàng.")
        self.status.pack(fill="x", padx=8)

        logfrm = ttk.Frame(self)
        logfrm.pack(fill="both", expand=True, **pad)
        self.log = tk.Text(logfrm, wrap="none", state="disabled", height=12)
        self.log.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(logfrm, command=self.log.yview)
        sb.pack(side="right", fill="y")
        self.log.config(yscrollcommand=sb.set)

    def _pick(self):
        d = filedialog.askdirectory(title="Chọn thư mục chứa MP3")
        if d:
            self.folder.set(d)

    def _log(self, msg):
        self._log_q.put(msg)

    def _drain_log(self):
        try:
            while True:
                msg = self._log_q.get_nowait()
                self.log.config(state="normal")
                self.log.insert("end", msg + "\n")
                self.log.see("end")
                self.log.config(state="disabled")
        except queue.Empty:
            pass
        self.after(100, self._drain_log)

    # ---------- Chạy ----------
    def _start(self):
        folder = Path(self.folder.get())
        if not self.folder.get() or not folder.is_dir():
            messagebox.showerror("Lỗi", "Hãy chọn một thư mục hợp lệ.")
            return
        if not FFMPEG:
            messagebox.showerror("Lỗi", "Không tìm thấy ffmpeg trong PATH. Cài ffmpeg trước.")
            return
        self._stop.clear()
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self._worker = threading.Thread(target=self._run, args=(folder,), daemon=True)
        self._worker.start()

    def _request_stop(self):
        self._stop.set()
        self._log("[i] Đang yêu cầu dừng… (kết thúc sau file hiện tại)")

    def _set_status(self, text):
        self.after(0, lambda: self.status.config(text=text))

    def _set_progress(self, value, maximum):
        def _upd():
            self.progress.config(maximum=maximum, value=value)
        self.after(0, _upd)

    def _finish(self):
        def _upd():
            self.btn_start.config(state="normal")
            self.btn_stop.config(state="disabled")
        self.after(0, _upd)

    def _run(self, folder: Path):
        bitrate = self.bitrate.get()
        target_kbps = int(bitrate.rstrip("k"))
        min_age = self.min_age.get()
        pattern = "**/*.mp3" if self.recursive.get() else "*.mp3"
        files = sorted(p for p in folder.glob(pattern) if not p.name.endswith(".tmp.mp3"))

        if not files:
            self._log(f"[i] Không có file .mp3 trong: {folder}")
            self._set_status("Không có file để xử lý.")
            self._finish()
            return

        self._log(f"[i] Thư mục: {folder}")
        self._log(f"[i] Bitrate: {bitrate} | {len(files)} file")
        ok = fail = skipped = 0
        total = len(files)
        for i, f in enumerate(files, 1):
            if self._stop.is_set():
                self._log("[i] Đã dừng theo yêu cầu.")
                break
            self._set_progress(i - 1, total)
            self._set_status(f"[{i}/{total}] {f.name}")

            if not is_stable(f, min_age):
                self._log(f"[{i}/{total}] {f.name} → BỎ QUA (đang ghi)")
                skipped += 1
                continue
            cur = get_bitrate_kbps(f)
            if cur is not None and cur <= target_kbps:
                self._log(f"[{i}/{total}] {f.name} → BỎ QUA (đã {cur}kbps)")
                skipped += 1
                continue

            size_before = f.stat().st_size
            kbps_str = f"{cur}kbps" if cur else "?kbps"
            self._log(f"[{i}/{total}] {f.name} ({size_before/1_048_576:.2f} MB, {kbps_str}) …")
            if compress(f, bitrate):
                size_after = f.stat().st_size
                saved = (1 - size_after / size_before) * 100
                self._log(f"        OK → {size_after/1_048_576:.2f} MB (giảm {saved:.0f}%)")
                ok += 1
            else:
                self._log(f"        FAIL")
                fail += 1

        self._set_progress(total, total)
        summary = f"Hoàn thành: {ok} OK, {fail} lỗi, {skipped} bỏ qua / {total} file."
        self._log("\n" + summary)
        self._set_status(summary)
        self._finish()


if __name__ == "__main__":
    App().mainloop()
