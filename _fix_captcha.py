#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Quet & sua truyen bi CAPTCHA (noi dung chuong ra rong/null nhung van bi tinh 'done').

Dau hieu chuong loi: file cache <NNNNNN>_orig.txt co qua it chu Han (< MIN_HAN)
-> trang chi co tieu de "第X章" + duong ke, KHONG co noi dung that.

Hanh dong (khi --apply):
  1. Xoa cache chuong loi (_orig.txt + _trans.txt) -> lan sau tai lai dung chuong do.
  2. Xoa file output txt (origin + translated) + .mp3 cua truyen loi (noi dung thieu).
  3. Bo novel_id khoi _progress.json (done/failed) -> tool tai lai truyen do.
  4. Bo entry tuong ung khoi _tts_progress.json.

Cach dung:
  py _fix_captcha.py            # XEM TRUOC (khong xoa gi)
  py _fix_captcha.py --apply    # THUC THI
"""
import os
os.environ.setdefault("PYTHONUNBUFFERED", "1")
import re
import sys
import json
import argparse
from pathlib import Path

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

MIN_HAN = 100  # chuong < 100 chu Han = nghi ngo loi (CAPTCHA page co ~50 chu Han)

CAPTCHA_MARKERS = ['访问验证', '验证码', '当前访问行为触发了安全验证', '请输入验证码', '提示信息']


def han_count(text: str) -> int:
    return sum(1 for c in text if "一" <= c <= "鿿")


def is_captcha_content(text: str) -> bool:
    return any(m in text for m in CAPTCHA_MARKERS)


def scan_cache(cache_root: Path, min_han: int) -> dict:
    """
    Tra ve {novel_id: {'bad': [chap_idx...], 'total': n}} cho moi novel co cache.
    'bad' = danh sach chuong (so thu tu) co cache _orig it chu Han.
    """
    result = {}
    if not cache_root.exists():
        return result
    for nd in sorted(cache_root.glob("*")):
        if not nd.is_dir():
            continue
        origs = sorted(nd.glob("*_orig.txt"))
        if not origs:
            continue
        bad = []
        for f in origs:
            m = re.match(r"(\d+)_orig", f.name)
            if not m:
                continue
            idx = int(m.group(1))
            text = f.read_text(encoding="utf-8", errors="replace")
            if han_count(text) < min_han or is_captcha_content(text):
                bad.append(idx)
        result[nd.name] = {"bad": bad, "total": len(origs)}
    return result


def map_novelid_to_files(*dirs: Path) -> dict:
    """Doc header moi file .txt, trich novel_id tu dong 'Nguon : .../novel/<id>.html'."""
    mapping = {}   # novel_id -> [Path, ...]
    for d in dirs:
        if not d.exists():
            continue
        for f in d.glob("*.txt"):
            if f.name.startswith("_"):
                continue
            try:
                head = f.read_text(encoding="utf-8", errors="replace")[:600]
            except Exception:
                continue
            m = re.search(r"/novel/(\d+)\.html", head)
            if m:
                mapping.setdefault(m.group(1), []).append(f)
    return mapping


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="downloaded")
    ap.add_argument("--apply", action="store_true", help="Thuc thi xoa/sua (mac dinh chi xem truoc)")
    ap.add_argument("--min-han", type=int, default=MIN_HAN,
                    help=f"Nguong chu Han toi thieu moi chuong (mac dinh {MIN_HAN})")
    args = ap.parse_args()

    min_han = args.min_han

    base    = Path(args.base)
    origin  = base / "origin"
    trans   = base / "translated"
    mp3dir  = trans / "mp3"
    cache   = base / ".cache"

    mode = "THUC THI" if args.apply else "XEM TRUOC (chua xoa gi - them --apply de thuc hien)"
    print(f"{'='*68}\n  Sua truyen bi CAPTCHA - che do: {mode}  (nguong han < {min_han})\n{'='*68}")

    cache_info = scan_cache(cache, min_han)
    bad_novels = {nid: info for nid, info in cache_info.items() if info["bad"]}

    # progress tai truyen
    prog_path = base / "_progress.json"
    progress = {"done": [], "failed": {}}
    if prog_path.exists():
        try:
            progress = json.loads(prog_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    done_set = set(progress.get("done", []))

    file_map = map_novelid_to_files(origin, trans)

    if not bad_novels:
        print("\n[OK] Khong tim thay truyen nao co chuong loi. Khong can sua.")
        return

    print(f"\n  Tim thay {len(bad_novels)} truyen co chuong loi:\n")
    files_to_delete = []
    ids_to_undone   = []
    cache_to_delete = []   # (Path _orig, Path _trans)

    for nid in sorted(bad_novels, key=lambda x: int(x) if x.isdigit() else 0):
        info = bad_novels[nid]
        nbad, ntot = len(info["bad"]), info["total"]
        in_done = nid in done_set
        outs = file_map.get(nid, [])
        bad_preview = info["bad"][:8]
        print(f"  novel={nid:>7}  loi {nbad}/{ntot} chuong  done={'CO' if in_done else 'khong'}"
              f"  chuong_loi={bad_preview}{'...' if nbad>8 else ''}")
        for f in outs:
            print(f"       file: {f.parent.name}/{f.name}")
            files_to_delete.append(f)
            # mp3 tuong ung (theo ten translated)
            if f.parent.name == "translated":
                mp3 = mp3dir / f"{f.stem}.mp3"
                if mp3.exists():
                    print(f"       mp3 : mp3/{mp3.name}")
                    files_to_delete.append(mp3)
        if not outs:
            print(f"       (khong tim thay file output - co the chua ghi)")
        if in_done:
            ids_to_undone.append(nid)
        # cache chuong loi
        nd = cache / nid
        for idx in info["bad"]:
            co = nd / f"{idx:06d}_orig.txt"
            ct = nd / f"{idx:06d}_trans.txt"
            cache_to_delete.append((co, ct))

    print(f"\n{'─'*68}")
    print(f"  Tom tat:")
    print(f"    - {len(bad_novels)} truyen loi ({len(ids_to_undone)} dang bi danh dau 'done' sai)")
    print(f"    - {len([f for f in files_to_delete if f.suffix=='.txt'])} file .txt + "
          f"{len([f for f in files_to_delete if f.suffix=='.mp3'])} file .mp3 se bi xoa")
    print(f"    - {sum(len(v['bad']) for v in bad_novels.values())} chuong cache loi se bi xoa")

    if not args.apply:
        print(f"\n  -> Chay lai voi --apply de thuc hien. Sau do chay lai tool tai de tai not chuong loi.")
        print(f"{'='*68}")
        return

    # ── THUC THI ──
    deleted_txt = []
    for f in files_to_delete:
        try:
            f.unlink()
            deleted_txt.append(f)
        except Exception as e:
            print(f"  [LOI] xoa {f.name}: {e}")
    for co, ct in cache_to_delete:
        for c in (co, ct):
            try:
                if c.exists():
                    c.unlink()
            except Exception:
                pass

    # progress tai truyen: bo novel_id khoi done + failed
    new_done = [x for x in progress.get("done", []) if x not in set(ids_to_undone)]
    progress["done"] = new_done
    for nid in ids_to_undone:
        progress.get("failed", {}).pop(nid, None)
    prog_path.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")

    # _tts_progress.json: bo entry cua file translated da xoa
    tts_path = mp3dir / "_tts_progress.json"
    if tts_path.exists():
        try:
            tdata = json.loads(tts_path.read_text(encoding="utf-8"))
            tdone = tdata.get("done", {})
            removed_names = {f.name for f in deleted_txt if f.suffix == ".txt" and f.parent.name == "translated"}
            tdone = {k: v for k, v in tdone.items() if k not in removed_names}
            tdata["done"] = tdone
            tts_path.write_text(json.dumps(tdata, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"  [LOI] cap nhat _tts_progress.json: {e}")

    print(f"\n  [OK] Da xoa {len(deleted_txt)} file output + cache chuong loi.")
    print(f"  [OK] Da bo {len(ids_to_undone)} novel_id khoi 'done' (se tai lai khi chay tool).")
    print(f"  -> Chay lai tool tai (vd: py alicesw_downloader.py <listing-url> --all) de tai not.")
    print(f"{'='*68}")


if __name__ == "__main__":
    main()
