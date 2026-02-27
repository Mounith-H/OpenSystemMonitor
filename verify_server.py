"""
verify_server.py — Server verification & stats display script.

Checks that the RemoteSystemMonitor server is running, validates all
endpoints, and pretty-prints the live system stats.

Usage:
    python verify_server.py [--host HOST] [--port PORT]
"""

import argparse
import base64
import hashlib
import json
import os
import socket
import sys
from typing import Any

import urllib.request
import urllib.error

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 8080

RESET  = "\033[0m"
BOLD   = "\033[1m"
GREEN  = "\033[92m"
RED    = "\033[91m"
CYAN   = "\033[96m"
YELLOW = "\033[93m"
WHITE  = "\033[97m"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get(url: str, timeout: int = 5) -> tuple[int, Any]:
    """Perform a GET request. Returns (status_code, parsed_json_or_None)."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read().decode()
            return resp.status, json.loads(body)
    except urllib.error.HTTPError as e:
        return e.code, None
    except urllib.error.URLError:
        return 0, None


def ok(msg: str) -> None:
    print(f"  {GREEN}✔{RESET}  {msg}")


def fail(msg: str) -> None:
    print(f"  {RED}✘{RESET}  {msg}")


def header(title: str) -> None:
    width = 54
    print(f"\n{BOLD}{CYAN}{'─' * width}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'─' * width}{RESET}")


def kv(label: str, value: Any, unit: str = "") -> None:
    label_fmt = f"{YELLOW}{label:<28}{RESET}"
    print(f"    {label_fmt} {WHITE}{value}{unit}{RESET}")


# ---------------------------------------------------------------------------
# Endpoint checks
# ---------------------------------------------------------------------------

def check_server_reachable(base_url: str) -> bool:
    header("1 · Server Reachability")
    status, _ = _get(f"{base_url}/health")
    if status == 0:
        fail(f"Cannot reach server at {base_url}")
        print(f"\n  {RED}Make sure the server is running:{RESET}")
        print("  .venv\\Scripts\\uvicorn main:app --host 0.0.0.0 --port 8080\n")
        return False
    ok(f"Server reachable at {base_url}")
    return True


def check_health(base_url: str) -> bool:
    header("2 · GET /health")
    status, data = _get(f"{base_url}/health")
    if status != 200:
        fail(f"Expected HTTP 200, got {status}")
        return False
    ok(f"HTTP {status} OK")
    if isinstance(data, dict) and data.get("status") == "ok":
        ok(f'Payload correct → {json.dumps(data)}')
        return True
    fail(f"Unexpected payload: {data}")
    return False


def check_stats(base_url: str) -> dict | None:
    header("3 · GET /stats")
    status, data = _get(f"{base_url}/stats")
    if status != 200:
        fail(f"Expected HTTP 200, got {status}")
        return None
    ok(f"HTTP {status} OK")

    required_sections = ["system", "cpu", "memory", "disk", "network"]
    all_ok = True
    for section in required_sections:
        if section in data:
            ok(f"Section '{section}' present")
        else:
            fail(f"Section '{section}' MISSING")
            all_ok = False

    return data if all_ok else None


def check_websocket(host: str, port: int) -> bool:
    header("4 · WS /ws/stats")

    ws_key = base64.b64encode(os.urandom(16)).decode("ascii")
    expected_accept = base64.b64encode(
        hashlib.sha1((ws_key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
    ).decode("ascii")

    request = (
        "GET /ws/stats?interval_ms=1000 HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {ws_key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    ).encode("ascii")

    try:
        with socket.create_connection((host, port), timeout=5) as sock:
            sock.sendall(request)
            response = sock.recv(4096).decode("latin1", errors="replace")
    except Exception as exc:
        fail(f"WebSocket connection failed: {exc}")
        return False

    lines = response.split("\r\n")
    status_line = lines[0] if lines else ""
    headers = {}
    for line in lines[1:]:
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        headers[key.strip().lower()] = value.strip()

    if "101" not in status_line:
        fail(f"Expected HTTP 101 Switching Protocols, got: {status_line or 'no response'}")
        return False

    if headers.get("upgrade", "").lower() != "websocket":
        fail("Missing/invalid 'Upgrade: websocket' header")
        return False

    if "upgrade" not in headers.get("connection", "").lower():
        fail("Missing/invalid 'Connection: Upgrade' header")
        return False

    if headers.get("sec-websocket-accept") != expected_accept:
        fail("Invalid Sec-WebSocket-Accept header")
        return False

    ok("WebSocket handshake successful")
    return True


# ---------------------------------------------------------------------------
# Stats display
# ---------------------------------------------------------------------------

def display_stats(data: dict) -> None:
    header("5 · Live System Stats")

    sys_info = data.get("system", {})
    cpu      = data.get("cpu", {})
    mem      = data.get("memory", {})
    disk     = data.get("disk", {})
    net      = data.get("network", {})

    # System
    print(f"\n  {BOLD}System{RESET}")
    kv("OS",            sys_info.get("os", "N/A"))
    kv("Hostname",      sys_info.get("hostname", "N/A"))
    uptime_sec = sys_info.get("uptime_seconds", 0)
    hours, rem = divmod(int(uptime_sec), 3600)
    mins, secs = divmod(rem, 60)
    kv("Uptime",        f"{hours}h {mins}m {secs}s")

    # CPU
    print(f"\n  {BOLD}CPU{RESET}")
    kv("Total Usage",   sys_info.get("usage_percent", cpu.get("usage_percent", "N/A")), " %")
    kv("Core Count",    cpu.get("core_count", "N/A"), " logical cores")
    freq = cpu.get("frequency_mhz")
    kv("Frequency",     f"{freq} MHz" if freq else "N/A")

    per_core: list = cpu.get("per_core_usage_percent", [])
    if per_core:
        print(f"\n    {YELLOW}{'Per-Core Usage':<28}{RESET}")
        for i, pct in enumerate(per_core):
            bar_len = int(pct / 5)           # each █ = 5 %
            bar     = "█" * bar_len + "░" * (20 - bar_len)
            color   = RED if pct > 80 else (YELLOW if pct > 50 else GREEN)
            print(f"      Core {i:>2}  {color}{bar}{RESET}  {pct:5.1f}%")

    # Memory
    print(f"\n  {BOLD}Memory{RESET}")
    kv("Total RAM",     mem.get("total_gb", "N/A"), " GB")
    kv("Used",          mem.get("used_percent", "N/A"), " %")
    kv("Available",     mem.get("available_gb", "N/A"), " GB")

    # Disk
    print(f"\n  {BOLD}Disk{RESET}")
    kv("Total Size",    disk.get("total_gb", "N/A"), " GB")
    kv("Used",          disk.get("used_percent", "N/A"), " %")

    # Network
    print(f"\n  {BOLD}Network{RESET}")
    sent_mb = round(net.get("bytes_sent", 0) / (1024 ** 2), 2)
    recv_mb = round(net.get("bytes_received", 0) / (1024 ** 2), 2)
    kv("Bytes Sent",    f"{sent_mb} MB")
    kv("Bytes Received",f"{recv_mb} MB")

    # Thermal
    thermal = data.get("thermal", {})
    print(f"\n  {BOLD}Thermal & Fans{RESET}")
    pkg_t     = thermal.get("cpu_package_temp_celsius")
    avg_t     = thermal.get("cpu_core_avg_celsius")
    max_t     = thermal.get("cpu_core_max_celsius")
    cpu_f     = thermal.get("cpu_fan_rpm")
    cpu_fp    = thermal.get("cpu_fan_percent")
    gpu_c     = thermal.get("gpu_core_temp_celsius")
    gpu_hot   = thermal.get("gpu_hotspot_celsius")
    gpu_fr    = thermal.get("gpu_fan_rpm")
    gpu_fp    = thermal.get("gpu_fan_percent")
    kv("CPU Package Temp",   f"{pkg_t} °C"   if pkg_t   is not None else "N/A")
    kv("CPU Core Avg Temp",  f"{round(avg_t,1)} °C" if avg_t is not None else "N/A")
    kv("CPU Core Max Temp",  f"{max_t} °C"   if max_t   is not None else "N/A")
    kv("CPU Fan RPM",        f"{cpu_f} RPM"  if cpu_f   is not None else "N/A")
    kv("CPU Fan Speed",      f"{cpu_fp} %"   if cpu_fp  is not None else "N/A")
    kv("GPU Core Temp",      f"{gpu_c} °C"   if gpu_c   is not None else "N/A")
    kv("GPU Hot Spot Temp",  f"{gpu_hot} °C" if gpu_hot is not None else "N/A")
    kv("GPU Fan RPM",        f"{gpu_fr} RPM" if gpu_fr  is not None else "N/A")
    kv("GPU Fan Speed",      f"{gpu_fp} %"   if gpu_fp  is not None else "N/A")

    # Performance modes
    modes = data.get("modes", {})
    print(f"\n  {BOLD}Performance Modes{RESET}")
    kv("CPU Mode",   modes.get("cpu_mode") or "N/A")
    kv("GPU Mode",   modes.get("gpu_mode") or "N/A")

    # Battery
    bat = data.get("battery", {})
    charge  = bat.get("charge_percent")
    plugged = bat.get("ac_plugged")
    print(f"\n  {BOLD}Battery{RESET}")
    kv("Charge",     f"{charge} %" if charge is not None else "N/A")
    kv("AC Plugged", ("Yes" if plugged else "No") if plugged is not None else "N/A")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Verify RemoteSystemMonitor server.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    base_url = f"http://{args.host}:{args.port}"
    print(f"\n{BOLD}Remote System Monitor — Verification Tool{RESET}")
    print(f"Target: {CYAN}{base_url}{RESET}")

    passed = 0
    total  = 4

    if not check_server_reachable(base_url):
        sys.exit(1)
    passed += 1

    if check_health(base_url):
        passed += 1

    stats_data = check_stats(base_url)
    if stats_data:
        passed += 1

    if check_websocket(args.host, args.port):
        passed += 1

    if stats_data:
        display_stats(stats_data)

    # Summary
    header("Summary")
    color = GREEN if passed == total else RED
    print(f"  {color}{BOLD}{passed}/{total} checks passed{RESET}\n")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
