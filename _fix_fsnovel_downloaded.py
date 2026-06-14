#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fix tên và tổ chức file trong fsnovel.com/downloaded/:
  1. Xóa ký tự Trung Hoa khỏi tên file
  2. Viết hoa chữ cái đầu tên file
  3. Di chuyển truyện mẹ-con trai vào thư mục con "me-va-con-trai/"

Dùng:
  py _fix_fsnovel_downloaded.py             # xem trước (dry-run)
  py _fix_fsnovel_downloaded.py --apply     # thực thi
"""

import re
import sys
import argparse
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = Path(__file__).parent / "fsnovel.com" / "downloaded"
ME_CON_DIR = BASE / "me-va-con-trai"

CHINESE_RE = re.compile(
    r"[一-鿿㐀-䶿豈-﫿"
    r"⺀-⻿㇀-㇯　-〿]"
)


def has_chinese(text: str) -> bool:
    return bool(CHINESE_RE.search(text))


def remove_chinese(name: str) -> str:
    cleaned = CHINESE_RE.sub("", name)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned


def capitalize_first(name: str) -> str:
    """Viết hoa ký tự chữ đầu tiên, nhưng chỉ khi nó không đứng ngay sau số.
    VD: 'anh chị em' → 'Anh chị em'
        '2 cô gái'   → '2 Cô gái'
        '24h bên mẹ' → '24h Bên mẹ'  (h trong 24h không bị hoa)
        '(♥Fei~...)' → giữ nguyên nếu F đã hoa
    """
    if not name:
        return name
    for i, c in enumerate(name):
        if c.isalpha():
            if i == 0 or not name[i - 1].isdigit():
                return name[:i] + c.upper() + name[i + 1:]
    return name


def is_mother_son(basename: str) -> bool:
    """
    Nhận diện truyện nội dung mẹ-con trai dựa trên tên file.
    Loại trừ: con gái, mẹ chồng, bố mẹ/cha mẹ là đôi vợ chồng.
    """
    n = basename.lower()

    if "mẹ" not in n:
        return False

    # Loại trừ rõ ràng
    if "con gái" in n:
        return False
    if "mẹ chồng" in n:
        return False
    if "con dâu" in n:
        return False
    # "bố mẹ" / "cha mẹ" đứng đầu hoặc ở giữa → chỉ là "bố mẹ" = parents
    if re.search(r"\b(bố mẹ|cha mẹ)\b", n) and "con trai" not in n and "mẹ con" not in n:
        return False

    # Xác nhận rõ là mẹ-con trai
    if "con trai" in n:
        return True
    if "mẹ con" in n:
        return True
    if "anh trai" in n and "mẹ" in n:
        return True
    if re.search(r"(đụ|địt|quái|kiếp|bú)\s*mẹ", n):
        return True
    if re.search(r"mẹ\s*(và|&)\s*con(?!\s*gái)", n):
        return True
    if "loạn luân" in n:
        return True
    if re.search(r"(bên|với|của|tôi và)\s*mẹ", n):
        return True
    if re.search(r"mẹ\s*tôi", n):
        return True

    return False


def new_stem(stem: str) -> str:
    """Tên mới: bỏ ký tự Hán, viết hoa chữ đầu."""
    s = remove_chinese(stem) if has_chinese(stem) else stem
    return capitalize_first(s)


def plan(apply: bool):
    if not BASE.exists():
        print(f"[LỖI] Không tìm thấy thư mục: {BASE}")
        return

    files = sorted(f for f in BASE.iterdir() if f.suffix == ".txt" and f.is_file())
    print(f"Tổng file .txt: {len(files)}")

    rename_plan = []    # (old_path, new_path) - chỉ đổi tên, không di chuyển
    move_plan = []      # (old_path, new_path) - di chuyển sang me-va-con-trai/
    collisions = []

    for f in files:
        stem = new_stem(f.stem)
        new_name = stem + f.suffix

        # Xác định đích
        if is_mother_son(stem):
            dest = ME_CON_DIR / new_name
            plan_list = move_plan
        else:
            dest = BASE / new_name
            plan_list = rename_plan

        if new_name == f.name and dest.parent == f.parent:
            continue  # không thay đổi gì

        # Kiểm tra collision thật sự
        if dest.exists() and dest.resolve() != f.resolve():
            collisions.append((f, dest))
        else:
            plan_list.append((f, dest))

    return rename_plan, move_plan, collisions


def safe_rename(old: Path, new: Path):
    """Đổi tên, xử lý trường hợp chỉ đổi hoa/thường trên Windows."""
    if old.name.lower() == new.name.lower() and old.parent == new.parent:
        tmp = old.with_name(old.name + ".__tmp__")
        old.rename(tmp)
        tmp.rename(new)
    else:
        old.rename(new)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Thực thi (mặc định chỉ xem trước)")
    args = ap.parse_args()

    mode = "THỰC THI" if args.apply else "XEM TRƯỚC (thêm --apply để thực thi)"
    print(f"{'='*65}")
    print(f"  Chế độ: {mode}")
    print(f"  Thư mục: {BASE}")
    print(f"{'='*65}\n")

    result = plan(args.apply)
    if result is None:
        return
    rename_plan, move_plan, collisions = result

    # ── 1. Đổi tên (tại chỗ) ──
    print(f"── Đổi tên tại chỗ ({len(rename_plan)} file) ──")
    for old, new in rename_plan[:10]:
        tag = "[Hán]" if has_chinese(old.stem) else "[Hoa]"
        print(f"  {tag} {old.name}")
        print(f"       → {new.name}")
    if len(rename_plan) > 10:
        print(f"  ... và {len(rename_plan)-10} file khác")

    # ── 2. Di chuyển mẹ-con trai ──
    print(f"\n── Di chuyển mẹ-con trai → me-va-con-trai/ ({len(move_plan)} file) ──")
    for old, new in move_plan[:15]:
        print(f"  {old.name}")
    if len(move_plan) > 15:
        print(f"  ... và {len(move_plan)-15} file khác")

    # ── 3. Collision ──
    if collisions:
        print(f"\n── [BỎ QUA] Trùng tên ({len(collisions)} file) ──")
        for old, new in collisions:
            print(f"  {old.name} → đã tồn tại: {new.name}")

    print(f"\n{'='*65}")
    print(f"  Tổng: {len(rename_plan)} đổi tên, {len(move_plan)} di chuyển, {len(collisions)} bỏ qua")
    if not args.apply:
        print("  → Chạy lại với --apply để thực hiện.")
    print(f"{'='*65}")

    if not args.apply:
        return

    # ── Thực thi ──
    if move_plan and not ME_CON_DIR.exists():
        ME_CON_DIR.mkdir(parents=True)
        print(f"\n[OK] Tạo thư mục: {ME_CON_DIR}")

    errors = 0
    for old, new in rename_plan:
        try:
            safe_rename(old, new)
        except Exception as e:
            print(f"[LỖI] {old.name}: {e}")
            errors += 1

    for old, new in move_plan:
        try:
            safe_rename(old, new)
        except Exception as e:
            print(f"[LỖI] {old.name}: {e}")
            errors += 1

    print(f"\n[XONG] {len(rename_plan)+len(move_plan)-errors} thành công, {errors} lỗi.")


if __name__ == "__main__":
    main()


