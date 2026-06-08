#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bao cao tong quan trang thai pipeline: origin -> translated -> mp3.

Doc trang thai tu cac file do alicesw_downloader.py va txt_to_mp3.py ghi:
  downloaded/_origin_progress.json      {novel_id: "ten_file.txt"}  - origin da done
  downloaded/_origin_failed.json        {novel_id: ly_do}           - origin loi
  downloaded/_translated_progress.json  {novel_id: "ten_file.txt"}  - ban dich da done
  downloaded/_translated_failed.json    {novel_id: ly_do}           - ban dich loi
  downloaded/translated/mp3/_tts_progress.json  {done:{txt:rec}, failed:{txt:rec}}
"""
import sys
import json
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE      = Path(__file__).parent
DL        = BASE / "downloaded"
ORIGIN    = DL / "origin"
TRANS     = DL / "translated"
MP3       = TRANS / "mp3"

ORIGIN_PROG = DL / "_origin_progress.json"
ORIGIN_FAIL = DL / "_origin_failed.json"
TRANS_PROG  = DL / "_translated_progress.json"
TRANS_FAIL  = DL / "_translated_failed.json"
TTS_PROG    = MP3 / "_tts_progress.json"

SEP = "─" * 60


def load_flat(p: Path) -> dict:
    """Doc file dict phang {key: value}. Tra ve {} neu khong co/loi."""
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def load_tts(p: Path):
    """Doc _tts_progress.json -> (done, failed). Moi cai la {txt_name: rec}."""
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d.get("done", {}), d.get("failed", {})
    except Exception:
        return {}, {}


def fmt_age(ts: int) -> str:
    if not ts:
        return ""
    diff = int(time.time()) - ts
    if diff < 60:
        return f"{diff}s truoc"
    if diff < 3600:
        return f"{diff//60}p truoc"
    return f"{diff//3600}h truoc"


def _txt_files(d: Path) -> list:
    if not d.exists():
        return []
    return sorted(f for f in d.glob("*.txt") if not f.name.startswith("_"))


def report_stage(label: str, folder: Path, prog: dict, fail: dict, done_note: str):
    """Bao cao 1 stage (origin hoac translated). prog/fail keyed theo novel_id.
    prog value = ten file .txt da ghep. Orphan = file .txt tren dia ma chua co trong progress."""
    files = _txt_files(folder)
    done_names = {str(v) for v in prog.values()}
    orphan = [f for f in files if f.name not in done_names]

    print(f"\n{'═'*60}")
    print(f"  {label}  ({len(files)} file .txt trong {folder})")
    print(SEP)
    print(f"  Done    : {len(prog):3d}  ({done_note})")
    print(f"  Fail    : {len(fail):3d}  (loi - se retry o lan chay sau)")
    print(f"  Orphan  : {len(orphan):3d}  (file .txt tren dia, khong co trong progress)")

    if fail:
        print(f"\n  [Fail - se retry]")
        for nid in sorted(fail):
            val = fail[nid]
            reason = val.get("reason", "") if isinstance(val, dict) else str(val)
            print(f"    ! novel={nid:<8}  {reason[:55]}")

    if orphan:
        print(f"\n  [Orphan - file la, khong khop progress]")
        for f in orphan:
            sz = f.stat().st_size / 1024
            print(f"    ? {f.name[:55]}  ({sz:.0f} KB)")


def report_origin():
    report_stage("ORIGIN", ORIGIN,
                 load_flat(ORIGIN_PROG), load_flat(ORIGIN_FAIL),
                 done_note="da tai du chuong -> da ghep file goc")


def report_translated():
    report_stage("TRANSLATED", TRANS,
                 load_flat(TRANS_PROG), load_flat(TRANS_FAIL),
                 done_note="da dich xong -> da ghep file dich")


def report_mp3():
    tdone, tfail = load_tts(TTS_PROG)
    trans_prog   = load_flat(TRANS_PROG)            # {id: ten_file_dich.txt}
    trans_done_names = {str(v) for v in trans_prog.values()}

    mp3s = list(MP3.glob("*.mp3")) if MP3.exists() else []
    total_size_mb = sum(f.stat().st_size for f in mp3s) / 1024 / 1024

    done_txt = set(tdone.keys())   # ten .txt da co mp3
    fail_txt = set(tfail.keys())   # ten .txt tts loi
    # Pending = ban dich DA DONE nhung chua tao mp3 (va chua bi danh dau loi)
    pending = sorted(n for n in trans_done_names if n not in done_txt and n not in fail_txt)

    print(f"\n{'═'*60}")
    print(f"  MP3 / TTS  ({len(mp3s)} file, {total_size_mb:.1f} MB trong {MP3})")
    print(SEP)
    print(f"  Done    : {len(tdone):3d}  (da co mp3)")
    print(f"  Fail    : {len(fail_txt):3d}  (tts loi - can chay lai)")
    print(f"  Pending : {len(pending):3d}  (ban dich done, chua tao mp3)")

    if fail_txt:
        print(f"\n  [Fail - loi TTS]")
        for name in sorted(fail_txt):
            rec = tfail[name]
            age = fmt_age(rec.get("failed_at", 0)) if isinstance(rec, dict) else ""
            print(f"    ! {name[:60]}  {age}")

    if pending:
        print(f"\n  [Pending - ban dich done, dang cho TTS]")
        for name in pending:
            print(f"    - {name[:60]}")

    # Mp3 co tren dia nhung khong co trong progress (file cu)
    done_mp3s = {v.get("out") for v in tdone.values() if isinstance(v, dict) and v.get("out")}
    orphan = [f for f in mp3s if f.name not in done_mp3s]
    if orphan:
        print(f"\n  [Orphan - mp3 khong co trong progress (co the la file cu)]")
        for f in orphan:
            print(f"    ? {f.name[:60]}")


if __name__ == "__main__":
    try:
        report_origin()
        report_translated()
        report_mp3()
        print(f"\n{'═'*60}\n")
    except Exception as e:
        import traceback
        print(f"\n[LOI] {e}")
        traceback.print_exc()
    input("\nNhan Enter de dong...")
