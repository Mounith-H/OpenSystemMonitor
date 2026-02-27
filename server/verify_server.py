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
        print("  .venv\\Scripts\\uvicorn main:app --app-dir server --host 0.0.0.0 --port 8080\n")
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

    required_sections = ["system", "cpu", "memory", "disk", "network", "thermal", "modes", "battery"]
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

def _fmt_value(value: Any) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _print_tree(value: Any, indent: int = 4) -> None:
    pad = " " * indent

    if isinstance(value, dict):
        if not value:
            print(f"{pad}{WHITE}<empty>{RESET}")
            return
        for key, sub_value in value.items():
            if isinstance(sub_value, (dict, list)):
                print(f"{pad}{YELLOW}{key}{RESET}")
                _print_tree(sub_value, indent + 2)
            else:
                print(f"{pad}{YELLOW}{key:<28}{RESET} {WHITE}{_fmt_value(sub_value)}{RESET}")
        return

    if isinstance(value, list):
        if not value:
            print(f"{pad}{WHITE}<empty>{RESET}")
            return
        for idx, item in enumerate(value):
            if isinstance(item, (dict, list)):
                print(f"{pad}{YELLOW}[{idx}]{RESET}")
                _print_tree(item, indent + 2)
            else:
                print(f"{pad}{YELLOW}[{idx}] {RESET}{WHITE}{_fmt_value(item)}{RESET}")
        return

    print(f"{pad}{WHITE}{_fmt_value(value)}{RESET}")

def display_stats(data: dict) -> None:
    header("5 · Full Laptop Stats (/stats)")
    _print_tree(data, indent=4)


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
