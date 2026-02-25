"""
Remote System Monitor - FastAPI server
Cross-platform system stats API using psutil.

Run with:
    uvicorn main:app --host 0.0.0.0 --port 8000
"""

import os
import platform
import socket
import time
from typing import Optional

import psutil
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Optional thermal / GPU imports (fail gracefully if hardware absent)
# ---------------------------------------------------------------------------

# pynvml — NVIDIA GPU stats (Windows & Linux)
try:
    import pynvml as _pynvml
    _pynvml.nvmlInit()
    _NVML_AVAILABLE: bool = True
except Exception:
    _NVML_AVAILABLE = False

# LibreHardwareMonitorLib — accurate CPU thermal & fan data on Windows
# Requires the DLL in libs/ and Administrator privileges for ring0 access.
_LHM_COMPUTER    = None
_LHM_SensorType  = None
_LHM_HardwareType = None
_LHM_INIT_ERROR: str = "Not attempted"

if os.name == "nt":
    try:
        import pythonnet as _pythonnet
        _pythonnet.load("coreclr")   # must be called before `import clr`
        import clr as _clr

        _libs_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "libs"
        )
        import sys as _sys
        if _libs_dir not in _sys.path:
            _sys.path.insert(0, _libs_dir)

        _clr.AddReference("LibreHardwareMonitorLib")

        from LibreHardwareMonitor.Hardware import (  # type: ignore
            Computer as _Computer,
            HardwareType as _HardwareType,
            SensorType as _SensorType,
        )

        _lhm = _Computer()
        _lhm.IsCpuEnabled         = True
        _lhm.IsMotherboardEnabled = True   # fan headers
        _lhm.IsGpuEnabled         = True   # GPU fan via LHM
        _lhm.Open()

        _LHM_COMPUTER     = _lhm
        _LHM_SensorType   = _SensorType
        _LHM_HardwareType = _HardwareType
        _LHM_INIT_ERROR   = "OK"
    except Exception as _lhm_err:
        _LHM_COMPUTER   = None
        _LHM_INIT_ERROR = str(_lhm_err)

# ---------------------------------------------------------------------------
# ASUS ATK ACPI — fan speed via direct kernel IOCTL (same method as GHelper)
# Works on any ASUS laptop that has the ATK ACPI driver installed.
# No admin required; driver is always loaded by ASUS system software.
# ---------------------------------------------------------------------------
if os.name == "nt":
    import ctypes
    import ctypes.wintypes as _wt
    import struct as _struct

    _kernel32 = ctypes.windll.kernel32  # type: ignore

    # ATK ACPI driver constants (from GHelper / AsusACPI.cs)
    _ATK_PATH        = "\\\\.\\ATKACPI"   # \\.\ATKACPI — correct Windows device namespace
    _ATK_IOCTL       = 0x0022240C
    _DSTS            = 0x53545344   # "DSTS" — read device status
    _DEVS            = 0x53564544   # "DEVS" — write device value
    _ATK_CPU_FAN_ID  = 0x00110013
    _ATK_GPU_FAN_ID  = 0x00110014
    _FAN_MAX_RPM     = 6600          # max fan speed for this laptop (ASUS TUF Dash F15)
    _ATK_CPU_MODE_ID = 0x00120075   # 0=Balanced, 1=Turbo, 2=Silent
    _ATK_GPU_ECO_ID  = 0x00090020   # 0=Standard/off, 1=Eco/on
    _ATK_GPU_MUX_ID  = 0x00090016   # 0=Ultimate (dGPU direct), 1=Optimus (Standard/Eco)

    # Windows CreateFile flags
    _GENERIC_READ        = 0x80000000
    _GENERIC_WRITE       = 0x40000000
    _FILE_SHARE_RW       = 0x00000001 | 0x00000002
    _OPEN_EXISTING       = 3
    _FILE_ATTR_NORMAL    = 0x80
    _INVALID_HANDLE      = -1  # INVALID_HANDLE_VALUE with default c_int restype

    def _atk_read_fan(device_id: int) -> Optional[int]:
        """
        Read a single ASUS ATK fan value via DeviceIoControl.
        Returns RPM (device_value × 100), or None if unavailable.
        Works without Administrator privileges.

        Packet layout (matches GHelper CallMethod / DeviceGet):
          Bytes 0-3  : DSTS method ID (little-endian uint32)
          Bytes 4-7  : arg payload length = 8 (little-endian uint32)
          Bytes 8-11 : device ID (little-endian uint32)
          Bytes 12-15: 0x00 padding
        """
        handle = _kernel32.CreateFileW(
            _ATK_PATH,
            _GENERIC_READ | _GENERIC_WRITE,
            _FILE_SHARE_RW,
            None,
            _OPEN_EXISTING,
            _FILE_ATTR_NORMAL,
            None,
        )
        if handle == _INVALID_HANDLE or handle == 0:
            return None
        try:
            in_buf  = _struct.pack("<IIII", _DSTS, 8, device_id, 0)
            out_buf = ctypes.create_string_buffer(16)
            returned = _wt.DWORD(0)
            ok = _kernel32.DeviceIoControl(
                handle,
                _ATK_IOCTL,
                in_buf, len(in_buf),
                out_buf, 16,
                ctypes.byref(returned),
                None,
            )
            if not ok:
                return None
            raw = _struct.unpack_from("<i", out_buf.raw, 0)[0]
            # GHelper logic: driver returns (true_value + 65536)
            val = raw - 65536
            if val < 0:
                val += 65536
            if val <= 0 or val > 100:
                return None
            return val * 100   # convert to RPM
        finally:
            _kernel32.CloseHandle(handle)

    def _atk_fan_speeds() -> tuple[Optional[int], Optional[int]]:
        """Return (cpu_rpm, gpu_rpm) from the ATK ACPI driver."""
        try:
            return (
                _atk_read_fan(_ATK_CPU_FAN_ID),
                _atk_read_fan(_ATK_GPU_FAN_ID),
            )
        except Exception:
            return None, None

    def _atk_read_device(device_id: int) -> Optional[int]:
        """Read a raw DSTS device value. Returns decoded int (can be negative if unsupported)."""
        handle = _kernel32.CreateFileW(
            _ATK_PATH, _GENERIC_READ | _GENERIC_WRITE,
            _FILE_SHARE_RW, None, _OPEN_EXISTING, _FILE_ATTR_NORMAL, None,
        )
        if handle == _INVALID_HANDLE or handle == 0:
            return None
        try:
            in_buf  = _struct.pack("<IIII", _DSTS, 8, device_id, 0)
            out_buf = ctypes.create_string_buffer(16)
            returned = _wt.DWORD(0)
            ok = _kernel32.DeviceIoControl(
                handle, _ATK_IOCTL, in_buf, len(in_buf),
                out_buf, 16, ctypes.byref(returned), None,
            )
            if not ok:
                return None
            raw = _struct.unpack_from("<i", out_buf.raw, 0)[0]
            return raw - 65536  # GHelper decode: 65536 offset
        finally:
            _kernel32.CloseHandle(handle)

    def _atk_write_device(device_id: int, value: int) -> bool:
        """Write a value to an ATK ACPI device via DEVS IOCTL. Returns True on success."""
        handle = _kernel32.CreateFileW(
            _ATK_PATH, _GENERIC_READ | _GENERIC_WRITE,
            _FILE_SHARE_RW, None, _OPEN_EXISTING, _FILE_ATTR_NORMAL, None,
        )
        if handle == _INVALID_HANDLE or handle == 0:
            return False
        try:
            in_buf  = _struct.pack("<IIII", _DEVS, 8, device_id, value)
            out_buf = ctypes.create_string_buffer(16)
            returned = _wt.DWORD(0)
            ok = _kernel32.DeviceIoControl(
                handle, _ATK_IOCTL, in_buf, len(in_buf),
                out_buf, 16, ctypes.byref(returned), None,
            )
            return bool(ok)
        finally:
            _kernel32.CloseHandle(handle)

    # In-memory mode cache — firmware doesn't echo mode back via DSTS on FX517ZM
    # after a mode change, but DOES return a valid value at startup (always 3 = Performance).
    # Seeded from hardware at startup; updated on every POST /modes call.
    _CPU_MODE_MAP       = {0: "Balanced", 1: "Turbo", 2: "Silent", 3: "Performance", 4: "Manual"}
    _CPU_MODE_WRITE_MAP = {"balanced": 0, "turbo": 1, "silent": 2, "performance": 3}
    _MODE_CACHE_FILE    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mode_cache.json")

    def _read_cpu_mode_from_hw() -> Optional[str]:
        """Read CPU mode directly from ATK hardware (only reliable at boot)."""
        try:
            val = _atk_read_device(_ATK_CPU_MODE_ID)
            if val is None or val < 0:
                return None
            return _CPU_MODE_MAP.get(val)
        except Exception:
            return None

    def _load_mode_cache() -> tuple[Optional[str], Optional[str]]:
        """Load persisted mode from file. Falls back to hardware read for CPU mode."""
        try:
            import json as _json
            with open(_MODE_CACHE_FILE) as f:
                data = _json.load(f)
            return data.get("cpu_mode"), data.get("gpu_mode")
        except Exception:
            return _read_cpu_mode_from_hw(), None

    def _save_mode_cache(cpu_mode: Optional[str], gpu_mode: Optional[str]) -> None:
        """Persist current modes to file so they survive server restarts."""
        try:
            import json as _json
            with open(_MODE_CACHE_FILE, "w") as f:
                _json.dump({"cpu_mode": cpu_mode, "gpu_mode": gpu_mode}, f)
        except Exception:
            pass

    _cached_cpu_mode, _cached_gpu_mode = _load_mode_cache()

    def _get_cpu_mode() -> Optional[str]:
        """Return current CPU mode from cache (hardware at startup, POST /modes after)."""
        return _cached_cpu_mode

    def _set_cpu_mode(mode: str) -> bool:
        """Write CPU performance mode to ATK hardware, update cache and persist."""
        global _cached_cpu_mode
        key = mode.lower()
        val = _CPU_MODE_WRITE_MAP.get(key)
        if val is None:
            return False
        ok = _atk_write_device(_ATK_CPU_MODE_ID, val)
        if ok:
            _cached_cpu_mode = {"balanced": "Balanced", "turbo": "Turbo",
                                 "silent": "Silent", "performance": "Performance"}.get(key, mode)
            _save_mode_cache(_cached_cpu_mode, _cached_gpu_mode)
        return ok

    def _get_gpu_mode() -> Optional[str]:
        """Return current GPU mode from cache, or detect via ECO+MUX flags."""
        if _cached_gpu_mode is not None:
            return _cached_gpu_mode
        # Fall back to hardware detection (MUX and ECO flags are readable)
        try:
            eco = _atk_read_device(_ATK_GPU_ECO_ID)
            mux = _atk_read_device(_ATK_GPU_MUX_ID)
            if eco is None and mux is None:
                return None
            if mux == 0:
                return "Ultimate"
            if eco == 1:
                return "Eco"
            return "Standard"
        except Exception:
            return None

    def _set_gpu_mode(mode: str) -> bool:
        """Write GPU mode (Eco/Standard only — Ultimate requires reboot)."""
        global _cached_gpu_mode
        key = mode.lower()
        if key == "eco":
            ok = _atk_write_device(_ATK_GPU_ECO_ID, 1)
        elif key == "standard":
            ok = _atk_write_device(_ATK_GPU_ECO_ID, 0)
        else:
            return False  # Ultimate requires MUX switch + reboot, skip
        if ok:
            _cached_gpu_mode = {"eco": "Eco", "standard": "Standard"}.get(key, mode)
            _save_mode_cache(_cached_cpu_mode, _cached_gpu_mode)
        return ok

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Remote System Monitor",
    description="Lightweight cross-platform system monitoring API.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # Tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Boot time is constant — read it once at startup to avoid repeated syscalls.
_BOOT_TIME: float = psutil.boot_time()


# ---------------------------------------------------------------------------
# Response models (Pydantic keeps the JSON contract explicit)
# ---------------------------------------------------------------------------

class SystemInfo(BaseModel):
    os: str
    hostname: str
    uptime_seconds: float


class CpuStats(BaseModel):
    usage_percent: float
    per_core_usage_percent: list[float]
    core_count: int
    frequency_mhz: Optional[float]


class MemoryStats(BaseModel):
    total_gb: float
    used_percent: float
    available_gb: float


class DiskStats(BaseModel):
    total_gb: float
    used_percent: float


class NetworkStats(BaseModel):
    bytes_sent: int
    bytes_received: int


class ThermalStats(BaseModel):
    cpu_package_temp_celsius: Optional[float]   # CPU Package (best single value)
    cpu_core_avg_celsius: Optional[float]       # average of all core temps
    cpu_core_max_celsius: Optional[float]       # hottest core
    cpu_fan_rpm: Optional[int]
    cpu_fan_percent: Optional[float]            # 0-100 %
    gpu_core_temp_celsius: Optional[float]      # GPU Core
    gpu_hotspot_celsius: Optional[float]        # GPU Hot Spot
    gpu_fan_rpm: Optional[int]
    gpu_fan_percent: Optional[float]            # 0-100 %


class PerformanceModes(BaseModel):
    cpu_mode: Optional[str]   # Silent, Balanced, Turbo, Performance
    gpu_mode: Optional[str]   # Eco, Standard, Ultimate


class ModeSetRequest(BaseModel):
    cpu_mode: Optional[str] = None   # Silent | Balanced | Turbo | Performance
    gpu_mode: Optional[str] = None   # Eco | Standard  (Ultimate requires reboot)


class BatteryStats(BaseModel):
    charge_percent: Optional[float]
    ac_plugged: Optional[bool]


class SystemStats(BaseModel):
    system: SystemInfo
    cpu: CpuStats
    memory: MemoryStats
    disk: DiskStats
    network: NetworkStats
    thermal: ThermalStats
    modes: PerformanceModes
    battery: BatteryStats


class HealthResponse(BaseModel):
    status: str


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def _gb(bytes_value: int) -> float:
    """Convert bytes to gigabytes, rounded to 2 decimal places."""
    return round(bytes_value / (1024 ** 3), 2)


# ---------------------------------------------------------------------------
# Thermal helpers
# ---------------------------------------------------------------------------

def _lhm_cpu_sensors() -> tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    """
    Read CPU sensors via LibreHardwareMonitorLib.
    Returns (package_temp, core_avg_temp, core_max_temp, fan_rpm).

    Sensor priority:
      - cpu_package : "CPU Package"  (single authoritative value)
      - core_avg    : "Core Average" (LHM pre-computed average of P/E cores)
      - core_max    : "Core Max"     (hottest core)
      - fan_rpm     : first Fan-type sensor on the CPU hardware node
    """
    if _LHM_COMPUTER is None:
        return None, None, None, None
    try:
        package_temp: Optional[float] = None
        core_avg:     Optional[float] = None
        core_max:     Optional[float] = None
        fan_rpm:      Optional[float] = None

        for hw in _LHM_COMPUTER.Hardware:
            if str(hw.HardwareType) != "Cpu":
                continue
            hw.Update()

            for sensor in hw.Sensors:
                val = sensor.Value
                if val is None:
                    continue
                stype = str(sensor.SensorType)
                sname = str(sensor.Name)

                if stype == "Temperature":
                    if sname == "CPU Package":
                        package_temp = round(float(val), 1)
                    elif sname == "Core Average":
                        core_avg = round(float(val), 1)
                    elif sname == "Core Max":
                        core_max = round(float(val), 1)
                elif stype == "Fan" and fan_rpm is None:
                    fan_rpm = round(float(val), 1)

            # Sub-hardware (some platforms expose per-die sensors here)
            for sub in hw.SubHardware:
                sub.Update()
                for sensor in sub.Sensors:
                    val = sensor.Value
                    if val is None:
                        continue
                    if str(sensor.SensorType) == "Fan" and fan_rpm is None:
                        fan_rpm = round(float(val), 1)

        return package_temp, core_avg, core_max, fan_rpm
    except Exception:
        return None, None, None, None


def _lhm_gpu_sensors() -> tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    """
    Read GPU sensors via LHM.
    Returns (core_temp, hotspot_temp, fan_rpm, fan_percent).
    """
    if _LHM_COMPUTER is None:
        return None, None, None, None
    try:
        core_temp:    Optional[float] = None
        hotspot_temp: Optional[float] = None
        fan_rpm:      Optional[float] = None
        fan_pct:      Optional[float] = None

        for hw in _LHM_COMPUTER.Hardware:
            if str(hw.HardwareType) not in ("GpuNvidia", "GpuAmd", "GpuIntel"):
                continue
            hw.Update()

            for sensor in hw.Sensors:
                val = sensor.Value
                if val is None:
                    continue
                stype = str(sensor.SensorType)
                sname = str(sensor.Name)

                if stype == "Temperature":
                    if sname == "GPU Core" and core_temp is None:
                        core_temp = round(float(val), 1)
                    elif sname == "GPU Hot Spot" and hotspot_temp is None:
                        hotspot_temp = round(float(val), 1)
                elif stype == "Fan":
                    if fan_rpm is None:
                        fan_rpm = round(float(val), 1)
                elif stype == "Control":
                    if fan_pct is None:
                        fan_pct = round(float(val), 1)

            break  # use first discrete GPU only

        return core_temp, hotspot_temp, fan_rpm, fan_pct
    except Exception:
        return None, None, None, None


def _cpu_temp_linux() -> Optional[float]:
    """Read CPU temperature on Linux via psutil sensors."""
    try:
        temps = psutil.sensors_temperatures()
        if not temps:
            return None
        # Prefer coretemp (Intel) or k10temp (AMD)
        for key in ("coretemp", "k10temp", "cpu_thermal", "acpitz"):
            if key in temps:
                readings = [t.current for t in temps[key]]
                return round(sum(readings) / len(readings), 1)
        # Fallback: first available sensor group
        first = next(iter(temps.values()))
        return round(first[0].current, 1) if first else None
    except Exception:
        return None


def _cpu_fan_linux() -> Optional[float]:
    """Read CPU fan RPM on Linux via psutil sensors."""
    try:
        fans = psutil.sensors_fans()
        if not fans:
            return None
        for readings in fans.values():
            if readings:
                return round(readings[0].current, 0)
        return None
    except Exception:
        return None


def _gpu_stats_nvidia() -> tuple[Optional[float], Optional[float]]:
    """Return (gpu_temp_celsius, gpu_fan_percent) for the first NVIDIA GPU."""
    if not _NVML_AVAILABLE:
        return None, None
    try:
        handle = _pynvml.nvmlDeviceGetHandleByIndex(0)
        temp = float(_pynvml.nvmlDeviceGetTemperature(
            handle, _pynvml.NVML_TEMPERATURE_GPU
        ))
        try:
            fan = float(_pynvml.nvmlDeviceGetFanSpeed(handle))
        except _pynvml.NVMLError:
            fan = None  # some GPUs / drivers don't expose fan speed
        return temp, fan
    except Exception:
        return None, None


def _get_thermal_stats() -> ThermalStats:
    """Collect thermal and fan data cross-platform."""
    if os.name == "nt":
        pkg_temp, core_avg, core_max, _ = _lhm_cpu_sensors()  # ignore LHM fan (N/A on ASUS)
        gpu_core, gpu_hot, _, _ = _lhm_gpu_sensors()          # fan % comes from ATK RPM instead

        # ATK ACPI — the only reliable fan source on ASUS laptops (GHelper method)
        cpu_fan_rpm, gpu_fan_rpm = _atk_fan_speeds()
        cpu_fan_percent = round(cpu_fan_rpm / _FAN_MAX_RPM * 100, 1) if cpu_fan_rpm is not None else None
        gpu_fan_percent = round(gpu_fan_rpm / _FAN_MAX_RPM * 100, 1) if gpu_fan_rpm is not None else None

        # Supplement GPU temp with pynvml if LHM didn't catch it
        if gpu_core is None:
            nvml_temp, _ = _gpu_stats_nvidia()
            if gpu_core is None:
                gpu_core = nvml_temp

        return ThermalStats(
            cpu_package_temp_celsius=pkg_temp,
            cpu_core_avg_celsius=core_avg,
            cpu_core_max_celsius=core_max,
            cpu_fan_rpm=cpu_fan_rpm,
            cpu_fan_percent=cpu_fan_percent,
            gpu_core_temp_celsius=gpu_core,
            gpu_hotspot_celsius=gpu_hot,
            gpu_fan_rpm=gpu_fan_rpm,
            gpu_fan_percent=gpu_fan_percent,
        )
    else:
        cpu_temp = _cpu_temp_linux()
        cpu_fan  = _cpu_fan_linux()
        gpu_core, gpu_fan_pct = _gpu_stats_nvidia()
        return ThermalStats(
            cpu_package_temp_celsius=cpu_temp,
            cpu_core_avg_celsius=None,
            cpu_core_max_celsius=None,
            cpu_fan_rpm=cpu_fan,
            cpu_fan_percent=None,
            gpu_core_temp_celsius=gpu_core,
            gpu_hotspot_celsius=None,
            gpu_fan_rpm=None,
            gpu_fan_percent=gpu_fan_pct,
        )


def get_system_stats() -> SystemStats:
    """
    Collect and return a snapshot of current system statistics.

    psutil calls here are non-blocking except cpu_percent(interval=None),
    which returns the usage since the last call (or 0.0 on the very first
    call) — no sleeping required.
    """
    # -- System info ---------------------------------------------------------
    system_info = SystemInfo(
        os=platform.platform(),
        hostname=socket.gethostname(),
        uptime_seconds=round(time.time() - _BOOT_TIME, 2),
    )

    # -- CPU -----------------------------------------------------------------
    cpu_freq = psutil.cpu_freq()
    cpu_stats = CpuStats(
        usage_percent=psutil.cpu_percent(interval=None),
        per_core_usage_percent=psutil.cpu_percent(interval=None, percpu=True),
        core_count=psutil.cpu_count(logical=True) or 0,
        frequency_mhz=round(cpu_freq.current, 2) if cpu_freq else None,
    )

    # -- Memory --------------------------------------------------------------
    vm = psutil.virtual_memory()
    memory_stats = MemoryStats(
        total_gb=_gb(vm.total),
        used_percent=vm.percent,
        available_gb=_gb(vm.available),
    )

    # -- Disk (root / C:\ depending on OS) -----------------------------------
    root = "C:\\" if os.name == "nt" else "/"
    disk = psutil.disk_usage(root)
    disk_stats = DiskStats(
        total_gb=_gb(disk.total),
        used_percent=disk.percent,
    )

    # -- Network -------------------------------------------------------------
    net = psutil.net_io_counters()
    network_stats = NetworkStats(
        bytes_sent=net.bytes_sent,
        bytes_received=net.bytes_recv,
    )

    # -- Thermal & fans ------------------------------------------------------
    thermal_stats = _get_thermal_stats()

    # -- Performance modes (ASUS ATK ACPI) -----------------------------------
    if os.name == "nt":
        modes = PerformanceModes(
            cpu_mode=_get_cpu_mode(),
            gpu_mode=_get_gpu_mode(),
        )
    else:
        modes = PerformanceModes(cpu_mode=None, gpu_mode=None)

    # -- Battery -------------------------------------------------------------
    _bat = psutil.sensors_battery()
    battery = BatteryStats(
        charge_percent=round(_bat.percent, 1) if _bat else None,
        ac_plugged=bool(_bat.power_plugged) if _bat else None,
    )

    return SystemStats(
        system=system_info,
        cpu=cpu_stats,
        memory=memory_stats,
        disk=disk_stats,
        network=network_stats,
        thermal=thermal_stats,
        modes=modes,
        battery=battery,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health() -> HealthResponse:
    """Quick liveness check."""
    return HealthResponse(status="ok")


@app.get("/stats", response_model=SystemStats, tags=["Monitoring"])
async def get_stats() -> SystemStats:
    """
    Return a real-time snapshot of system statistics.

    Includes CPU, memory, disk, network, and general system info.
    """
    try:
        return get_system_stats()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to collect stats: {exc}") from exc


@app.post("/modes", response_model=PerformanceModes, tags=["Control"])
async def set_modes(req: ModeSetRequest) -> PerformanceModes:
    """
    Set CPU and/or GPU performance mode.

    CPU modes : Silent | Balanced | Turbo | Performance
    GPU modes : Eco | Standard  (Ultimate requires MUX switch + reboot)

    Changes are applied immediately via the ASUS ATK ACPI driver and cached
    so GET /stats reflects the updated mode.
    """
    if os.name != "nt":
        raise HTTPException(status_code=501, detail="Mode control only supported on Windows")

    errors = []
    if req.cpu_mode is not None:
        if req.cpu_mode.lower() not in _CPU_MODE_WRITE_MAP:
            errors.append(f"Invalid cpu_mode '{req.cpu_mode}'. Valid: Silent, Balanced, Turbo, Performance")
        elif not _set_cpu_mode(req.cpu_mode):
            errors.append(f"Failed to set CPU mode '{req.cpu_mode}' (ATK write failed)")

    if req.gpu_mode is not None:
        if req.gpu_mode.lower() not in ("eco", "standard"):
            errors.append(f"Invalid gpu_mode '{req.gpu_mode}'. Valid: Eco, Standard (Ultimate requires reboot)")
        elif not _set_gpu_mode(req.gpu_mode):
            errors.append(f"Failed to set GPU mode '{req.gpu_mode}' (ATK write failed)")

    if errors:
        raise HTTPException(status_code=400, detail=" | ".join(errors))

    return PerformanceModes(
        cpu_mode=_get_cpu_mode(),
        gpu_mode=_get_gpu_mode(),
    )


@app.get("/debug/lhm", tags=["Debug"])
async def debug_lhm() -> dict:
    """
    Show LibreHardwareMonitor init status and all detected sensor values.
    Run with Administrator privileges to unlock CPU temperature sensors.
    """
    import ctypes
    is_admin: bool = False
    try:
        is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin()) if os.name == "nt" else True
    except Exception:
        pass

    sensors: list[dict] = []
    if _LHM_COMPUTER is not None:
        try:
            for hw in _LHM_COMPUTER.Hardware:
                hw.Update()
                for s in hw.Sensors:
                    sensors.append({
                        "hardware": str(hw.Name),
                        "type":     str(s.SensorType),
                        "name":     str(s.Name),
                        "value":    float(s.Value) if s.Value is not None else None,
                    })
                for sub in hw.SubHardware:
                    sub.Update()
                    for s in sub.Sensors:
                        sensors.append({
                            "hardware": f"{hw.Name} / {sub.Name}",
                            "type":     str(s.SensorType),
                            "name":     str(s.Name),
                            "value":    float(s.Value) if s.Value is not None else None,
                        })
        except Exception as exc:
            sensors = [{"error": str(exc)}]

    return {
        "lhm_status":  _LHM_INIT_ERROR,
        "lhm_active":  _LHM_COMPUTER is not None,
        "is_admin":    is_admin,
        "sensors":     sensors,
    }
