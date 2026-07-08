import os
import subprocess
import sys
from pathlib import Path

FOLDER = r"D:\Unity\alicesw\fsnovel.com\temp\Done"
TARGET_KBPS = 32
TOLERANCE = 2000  # bps, skip if bitrate is within 32000 ± 2000


def get_bitrate(path):
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "stream=bit_rate",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True, text=True,
    )
    try:
        return int(result.stdout.strip())
    except ValueError:
        return None


def convert(src):
    tmp = src.with_suffix(".tmp.mp3")
    result = subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(src),
            "-codec:a", "libmp3lame",
            "-b:a", f"{TARGET_KBPS}k",
            "-map_metadata", "0",
            str(tmp),
        ],
        capture_output=True,
    )
    if result.returncode == 0:
        src.unlink()
        tmp.rename(src)
        return True
    else:
        if tmp.exists():
            tmp.unlink()
        print(f"  ERROR: {result.stderr.decode(errors='replace')[-200:]}")
        return False


def main():
    files = sorted(Path(FOLDER).rglob("*.mp3"))
    total = len(files)
    skipped = converted = failed = 0
    target_bps = TARGET_KBPS * 1000

    for i, fp in enumerate(files, 1):
        bitrate = get_bitrate(fp)
        label = f"[{i}/{total}] {fp.name}"

        if bitrate is not None and abs(bitrate - target_bps) <= TOLERANCE:
            print(f"SKIP {label} ({bitrate//1000}kbps)")
            skipped += 1
            continue

        br_str = f"{bitrate//1000}kbps" if bitrate else "?"
        print(f"CONV {label} ({br_str} -> {TARGET_KBPS}kbps) ", end="", flush=True)
        if convert(fp):
            print("OK")
            converted += 1
        else:
            print("FAIL")
            failed += 1

    print(f"\nDone: {converted} converted, {skipped} skipped, {failed} failed / {total} total")


if __name__ == "__main__":
    main()
