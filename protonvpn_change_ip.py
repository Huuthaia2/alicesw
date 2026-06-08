"""
ProtonVPN - đổi server WireGuard tự động (Windows).
Yêu cầu: chạy với quyền Admin.
"""
import json
import base64
import random
import subprocess
import time
import ctypes

CONF_PATH = r"C:\Program Files\Proton\VPN\v4.4.1\ServiceData\WireGuard\ProtonVPN.conf"
SETTINGS_PATH = r"C:\Users\Windows\AppData\Local\Proton\Proton VPN\Storage\GlobalSettings.json"
API_BASE = "https://vpn-api.proton.me"


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


def _decrypt_dpapi(b64_value: str) -> str:
    import win32crypt
    encrypted = base64.b64decode(b64_value)
    _, decrypted = win32crypt.CryptUnprotectData(encrypted, None, None, None, 0)
    token = decrypted.decode("utf-8").strip().strip('"')
    return token


def _get_credentials() -> tuple[str, str]:
    """Trả về (access_token, user_id)."""
    with open(SETTINGS_PATH, encoding="utf-8") as f:
        settings = json.load(f)
    token = _decrypt_dpapi(settings["AccessToken"])
    uid = _decrypt_dpapi(settings["UserId"])
    return token, uid


def _get_servers(access_token: str, user_id: str) -> list:
    import requests
    headers = {
        "Authorization": f"Bearer {access_token}",
        "x-pm-uid": user_id,
        "x-pm-appversion": "WindowsVPN_4.4.1",
        "User-Agent": "ProtonVPN/4.4.1 (Windows)",
    }
    r = requests.get(f"{API_BASE}/vpn/v1/logicals", headers=headers, timeout=15)
    r.raise_for_status()
    return r.json()["LogicalServers"]


def _pick_server(servers: list, exclude_ip: str = None) -> tuple[str, str]:
    candidates = []
    for logical in servers:
        if logical.get("Status") != 1:
            continue
        for sv in logical.get("Servers", []):
            if sv.get("Status") != 1:
                continue
            if not sv.get("X25519PublicKey"):
                continue
            if sv.get("EntryIP") == exclude_ip:
                continue
            candidates.append(sv)

    if not candidates:
        raise RuntimeError("Không tìm thấy server khả dụng")

    chosen = random.choice(candidates)
    return chosen["EntryIP"], chosen["X25519PublicKey"]


def _read_conf() -> dict:
    result = {}
    with open(CONF_PATH, "r") as f:
        for line in f:
            line = line.strip()
            if "=" in line:
                key, _, val = line.partition("=")
                result[key.strip()] = val.strip()
    return result


def _write_conf(new_ip: str, new_pubkey: str):
    with open(CONF_PATH, "r") as f:
        lines = f.readlines()

    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("Endpoint"):
            # giữ port cũ
            old_port = stripped.split(":")[-1] if ":" in stripped else "443"
            new_lines.append(f"Endpoint = {new_ip}:{old_port}\n")
        elif stripped.startswith("PublicKey") and new_lines and any(
            "Peer" in l for l in new_lines[-5:]
        ):
            new_lines.append(f"PublicKey = {new_pubkey}\n")
        else:
            new_lines.append(line)

    with open(CONF_PATH, "w") as f:
        f.writelines(new_lines)


def _restart_service():
    subprocess.run(["sc", "stop", "ProtonVPN WireGuard"], capture_output=True)
    time.sleep(3)
    result = subprocess.run(["sc", "start", "ProtonVPN WireGuard"], capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"Không start được service: {result.stderr.decode()}")
    time.sleep(2)


def change_ip(verbose: bool = True) -> str:
    """Đổi server ProtonVPN WireGuard, trả về IP mới. Cần chạy Admin."""
    if not is_admin():
        raise PermissionError("Cần chạy với quyền Administrator!")

    def log(msg):
        if verbose:
            print(msg)

    log("Đọc access token...")
    token, uid = _get_credentials()

    log("Lấy danh sách server từ ProtonVPN API...")
    servers = _get_servers(token, uid)
    log(f"  → {len(servers)} servers")

    # lấy IP hiện tại để tránh chọn lại
    current_conf = _read_conf()
    current_ip = current_conf.get("Endpoint", "").split(":")[0]

    new_ip, new_pubkey = _pick_server(servers, exclude_ip=current_ip)
    log(f"  → Server mới: {new_ip}")

    log("Cập nhật ProtonVPN.conf...")
    _write_conf(new_ip, new_pubkey)

    log("Restart ProtonVPN WireGuard service...")
    _restart_service()

    log(f"Xong! IP mới: {new_ip}")
    return new_ip


if __name__ == "__main__":
    change_ip()
