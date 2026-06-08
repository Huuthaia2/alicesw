#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cross-process file lock cho ProtonVPN rotate — tranh 2 process disconnect/connect cung luc."""
import os
import time
from pathlib import Path

_LOCK_FILE = Path(__file__).parent / ".vpn_rotate.lock"
_TIME_FILE = Path(__file__).parent / ".vpn_last_rotate"
_LOCK_TIMEOUT = 15   # cho toi 15s; het timeout -> skip rotation
_STALE_AGE   = 90    # lock file qua 90s -> coi la stale (process kia chet)


def acquire(timeout: float = _LOCK_TIMEOUT) -> bool:
    """Giu lock. Tra ve True neu thanh cong, False neu het timeout."""
    deadline = time.monotonic() + timeout
    while True:
        if _LOCK_FILE.exists():
            try:
                age = time.time() - _LOCK_FILE.stat().st_mtime
                if age > _STALE_AGE:
                    _LOCK_FILE.unlink(missing_ok=True)
            except OSError:
                pass

        try:
            fd = os.open(str(_LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return True
        except FileExistsError:
            pass

        if time.monotonic() >= deadline:
            return False
        time.sleep(1)


def release():
    """Giai phong lock."""
    try:
        _LOCK_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def elapsed_since_last() -> float | None:
    """Tra ve so giay tu lan rotate truoc, hoac None neu chua co."""
    try:
        ts = float(_TIME_FILE.read_text(encoding="utf-8").strip())
        return time.time() - ts
    except Exception:
        return None


def record_rotation():
    """Ghi timestamp hien tai sau khi rotate xong."""
    try:
        _TIME_FILE.write_text(str(time.time()), encoding="utf-8")
    except OSError:
        pass
