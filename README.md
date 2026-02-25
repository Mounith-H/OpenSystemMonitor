# OpenSystemMonitor

A lightweight FastAPI-based system monitor for ASUS TUF/ROG laptops running Windows.  
Exposes live hardware stats — CPU, GPU, memory, disk, network, thermals, fan speeds, performance modes, and battery — over a REST API.

> Tested on **ASUS TUF Dash F15 FX517ZM** (Intel i7-12650H · RTX 3060 Laptop · Windows 11)

---

## Features

| Category | Details |
|---|---|
| **CPU** | Usage %, per-core usage, frequency, core count |
| **Memory** | Total, used %, available |
| **Disk** | Total, used % |
| **Network** | Bytes sent / received |
| **Temperatures** | CPU package, core avg/max, GPU core, GPU hotspot (via LibreHardwareMonitor) |
| **Fan Speeds** | CPU & GPU fan RPM + % of max (6600 RPM) via ATK ACPI |
| **Performance Modes** | Read & set CPU mode (Silent / Balanced / Turbo / Performance) |
| **GPU Mode** | Read & set GPU mode (Eco / Standard) via ATK ACPI |
| **Battery** | Charge %, AC plugged status |
| **System Info** | OS, hostname, uptime |

---

## Requirements

- **Windows** (ATK ACPI and LibreHardwareMonitor are Windows-only)
- **Python 3.10+**
- **Administrator privileges** (required for ATK ACPI IOCTL and LHM temperature access)
- ASUS laptop with ATK ACPI driver installed (standard on all ASUS laptops)

---

## Installation

```bash
# 1. Clone the repo
git clone https://github.com/Mounith-H/OpenSystemMonitor.git
cd OpenSystemMonitor

# 2. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt
```

The `libs/` folder already contains the required DLLs:
- `LibreHardwareMonitorLib.dll` (v0.9.3, net6.0)
- `System.Management.dll`

---

## Usage

### Quick Start (Recommended)

Run `monitor.bat` as **Administrator** — it starts the server, waits for it to be ready, then shows a menu:

```
monitor.bat
```

Menu options:
- **[1]** Run verify_server.py (live stats display)
- **[2]** Quit and stop the server
- **[3]** Quit and leave the server running

### Manual Start

```bash
# Run as Administrator
.venv\Scripts\uvicorn.exe main:app --host 0.0.0.0 --port 8000
```

### Verify & Display Stats

```bash
.venv\Scripts\python.exe verify_server.py
```

Optionally target a remote host:

```bash
.venv\Scripts\python.exe verify_server.py --host 192.168.1.100 --port 8000
```

---

## API Reference

Base URL: `http://localhost:8000`

### `GET /health`
Returns server health status.

```json
{ "status": "ok" }
```

### `GET /stats`
Returns all live system stats.

<details>
<summary>Response schema</summary>

```json
{
  "system":  { "os", "hostname", "uptime_seconds" },
  "cpu":     { "usage_percent", "core_count", "frequency_mhz", "per_core_usage_percent" },
  "memory":  { "total_gb", "used_percent", "available_gb" },
  "disk":    { "total_gb", "used_percent" },
  "network": { "bytes_sent", "bytes_received" },
  "thermal": {
    "cpu_package_temp_celsius", "cpu_core_avg_celsius", "cpu_core_max_celsius",
    "cpu_fan_rpm", "cpu_fan_percent",
    "gpu_core_temp_celsius", "gpu_hotspot_celsius",
    "gpu_fan_rpm", "gpu_fan_percent"
  },
  "modes":   { "cpu_mode", "gpu_mode" },
  "battery": { "charge_percent", "ac_plugged" }
}
```
</details>

### `POST /modes`
Set CPU and/or GPU performance mode.

**Request body:**
```json
{
  "cpu_mode": "silent",       // silent | balanced | turbo | performance
  "gpu_mode": "standard"      // eco | standard
}
```

**Response:** current `PerformanceModes` object.

> Mode changes are persisted to `mode_cache.json` so they survive server restarts.

### `GET /debug/lhm`
Returns raw LibreHardwareMonitor sensor dump (useful for debugging temperature sensors).

---

## Architecture

```
monitor.bat          ← One-click launcher (starts server + shows menu)
main.py              ← FastAPI server (all hardware reading logic)
verify_server.py     ← CLI stats display & endpoint verification
_check_health.py     ← Health-poll helper used by monitor.bat
libs/                ← LibreHardwareMonitorLib.dll, System.Management.dll
mode_cache.json      ← Auto-generated; persists last-set performance modes
```

### Hardware Access

| Source | Used For |
|---|---|
| `psutil` | CPU, memory, disk, network, battery |
| `LibreHardwareMonitorLib` (via pythonnet) | CPU & GPU temperatures |
| `ATK ACPI` (`\\.\ATKACPI`, IOCTL `0x0022240C`) | Fan RPMs, CPU/GPU performance modes |

**ATK ACPI Device IDs used:**

| Device | ID |
|---|---|
| CPU Fan | `0x00110013` |
| GPU Fan | `0x00110014` |
| CPU Performance Mode | `0x00120075` |
| GPU ECO Mode | `0x00090020` |
| GPU MUX Switch | `0x00090016` |

### Known Limitations

- **CPU Mode read-back**: The FX517ZM firmware always returns `3` (Performance) via DSTS after a mode change. The server works around this with a file-persisted cache (`mode_cache.json`) — modes set via `POST /modes` are saved and restored on restart.
- **FPS**: Not available via ACPI — requires AMD ADL2 / NVAPI integration (not implemented).
- **GPU Ultimate mode**: Requires a MUX switch + system reboot, so it cannot be set via API at runtime.
- **Admin required**: LHM and ATK ACPI both require the process to run as Administrator.

---

## Dependencies

| Package | Purpose |
|---|---|
| `fastapi` | REST API framework |
| `uvicorn` | ASGI server |
| `psutil` | System metrics |
| `pydantic` | Data models / validation |
| `nvidia-ml-py` | NVML bindings (GPU info) |
| `pythonnet` | .NET interop for LHM |
| `wmi` | Windows Management Instrumentation |

---

## License

MIT
