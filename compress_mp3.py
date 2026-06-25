#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
compress_mp3.py — Nén tất cả file MP3 trong thư mục xuống 32kbps (overwrite tại chỗ).

Dùng:
  py compress_mp3.py                    # xử lý thư mục "File3Mb" (cạnh script này)
  py compress_mp3.py --dir D:/folder    # thư mục khác
  py compress_mp3.py --bitrate 64k      # bitrate khác (mặc định 32k)
  py compress_mp3.py --dry-run          # chỉ in danh sách, không làm gì
"""

import sys
import time
import shutil
import argparse
import subprocess
from pathlib import Path

FFMPEG  = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
DEFAULT_DIR = Path(__file__).parent / "File3Mb"
DEFAULT_BITRATE = "32k"
MIN_AGE_SEC = 10  # bỏ qua file được sửa trong vòng N giây gần đây


def is_stable(path: Path, min_age: int) -> bool:
    """True nếu file không bị ghi trong min_age giây qua."""
    age = time.time() - path.stat().st_mtime
    return age >= min_age


def get_bitrate_kbps(path: Path) -> int | None:
    """Trả về bitrate (kbps) của file MP3 qua ffprobe. None nếu không đọc được."""
    if not FFPROBE:
        return None
    try:
        result = subprocess.run(
            [FFPROBE, "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=bit_rate",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, timeout=15
        )
        val = result.stdout.strip()
        if val:
            return int(val) // 1000  # bps -> kbps
    except Exception:
        pass
    return None


def compress(src: Path, bitrate: str) -> bool:
    tmp = src.with_suffix(".tmp.mp3")
    cmd = [
        FFMPEG, "-y", "-i", str(src),
        "-codec:a", "libmp3lame", "-b:a", bitrate,
        "-map_metadata", "0",   # giữ metadata gốc
        str(tmp)
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=120)
        if result.returncode != 0:
            print(f"  [!] ffmpeg lỗi:\n{result.stderr.decode(errors='replace')[-300:]}")
            tmp.unlink(missing_ok=True)
            return False
        # replace nguyên bản
        tmp.replace(src)
        return True
    except Exception as e:
        print(f"  [!] Exception: {e}")
        tmp.unlink(missing_ok=True)
        return False


def main():
    parser = argparse.ArgumentParser(description="Nén MP3 -> 32kbps, overwrite tại chỗ.")
    parser.add_argument("--dir", default=str(DEFAULT_DIR), help="Thư mục chứa file MP3")
    parser.add_argument("--bitrate", default=DEFAULT_BITRATE, help="Bitrate đầu ra (mặc định: 32k)")
    parser.add_argument("--dry-run", action="store_true", help="Chỉ liệt kê file, không chuyển đổi")
    parser.add_argument("--min-age", type=int, default=MIN_AGE_SEC,
                        help=f"Bỏ qua file được sửa trong vòng N giây (mặc định: {MIN_AGE_SEC}s)")
    args = parser.parse_args()

    folder = Path(args.dir)
    if not folder.exists():
        print(f"[!] Không tìm thấy thư mục: {folder}")
        sys.exit(1)

    if not FFMPEG:
        print("[!] Không tìm thấy ffmpeg trong PATH. Cài ffmpeg trước.")
        sys.exit(1)

    mp3_files = sorted(folder.glob("*.mp3"))
    if not mp3_files:
        print(f"[i] Không có file .mp3 nào trong: {folder}")
        return

    print(f"[i] Thư mục : {folder}")
    print(f"[i] Bitrate  : {args.bitrate}")
    print(f"[i] Bỏ qua   : file mtime < {args.min_age}s")
    print(f"[i] Số file  : {len(mp3_files)}")
    if args.dry_run:
        print("[dry-run] Danh sách file sẽ được nén:")
        for f in mp3_files:
            size_mb = f.stat().st_size / 1_048_576
            stable = is_stable(f, args.min_age)
            flag = "" if stable else "  [BỎ QUA - đang ghi]"
            print(f"  {f.name}  ({size_mb:.2f} MB){flag}")
        return

    target_kbps = int(args.bitrate.rstrip("k"))

    ok = fail = skipped = 0
    for i, f in enumerate(mp3_files, 1):
        if not is_stable(f, args.min_age):
            print(f"[{i}/{len(mp3_files)}] {f.name}  -> BỎ QUA (đang ghi)")
            skipped += 1
            continue
        cur_kbps = get_bitrate_kbps(f)
        if cur_kbps is not None and cur_kbps <= target_kbps:
            print(f"[{i}/{len(mp3_files)}] {f.name}  -> BỎ QUA (đã {cur_kbps}kbps)")
            skipped += 1
            continue
        size_before = f.stat().st_size
        kbps_str = f"{cur_kbps}kbps" if cur_kbps else "?kbps"
        print(f"[{i}/{len(mp3_files)}] {f.name}  ({size_before/1_048_576:.2f} MB, {kbps_str}) ...", end=" ", flush=True)
        if compress(f, args.bitrate):
            size_after = f.stat().st_size
            saved_pct = (1 - size_after / size_before) * 100
            print(f"OK  -> {size_after/1_048_576:.2f} MB  (giảm {saved_pct:.0f}%)")
            ok += 1
        else:
            print("FAIL")
            fail += 1

    print(f"\nHoàn thành: {ok} OK, {fail} lỗi, {skipped} bỏ qua / tổng {len(mp3_files)} file.")


if __name__ == "__main__":
    main()
