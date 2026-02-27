import json
import os
import sys


def _none_payload() -> dict:
    return {
        "cpu_package_temp_celsius": None,
        "cpu_core_avg_celsius": None,
        "cpu_core_max_celsius": None,
        "cpu_fan_rpm": None,
        "gpu_core_temp_celsius": None,
        "gpu_hotspot_celsius": None,
        "gpu_fan_rpm": None,
        "gpu_fan_percent": None,
    }


def main() -> int:
    payload = _none_payload()

    try:
        import pythonnet
        pythonnet.load("coreclr")
        import clr

        libs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "libs")
        if libs_dir not in sys.path:
            sys.path.insert(0, libs_dir)

        clr.AddReference("LibreHardwareMonitorLib")
        from LibreHardwareMonitor.Hardware import Computer

        comp = Computer()
        comp.IsCpuEnabled = True
        comp.IsMotherboardEnabled = True
        comp.IsGpuEnabled = True
        comp.Open()

        cpu_package = None
        core_avg = None
        core_max = None
        cpu_fan = None
        gpu_core = None
        gpu_hot = None
        gpu_fan = None
        gpu_fan_pct = None

        for hw in comp.Hardware:
            hw_type = str(hw.HardwareType)
            if hw_type == "Cpu":
                hw.Update()
                for sensor in hw.Sensors:
                    val = sensor.Value
                    if val is None:
                        continue
                    stype = str(sensor.SensorType)
                    sname = str(sensor.Name)
                    if stype == "Temperature":
                        if sname == "CPU Package":
                            cpu_package = round(float(val), 1)
                        elif sname == "Core Average":
                            core_avg = round(float(val), 1)
                        elif sname == "Core Max":
                            core_max = round(float(val), 1)
                    elif stype == "Fan" and cpu_fan is None:
                        cpu_fan = round(float(val), 1)

            if hw_type in ("GpuNvidia", "GpuAmd", "GpuIntel"):
                hw.Update()
                for sensor in hw.Sensors:
                    val = sensor.Value
                    if val is None:
                        continue
                    stype = str(sensor.SensorType)
                    sname = str(sensor.Name)
                    if stype == "Temperature":
                        if sname == "GPU Core" and gpu_core is None:
                            gpu_core = round(float(val), 1)
                        elif sname == "GPU Hot Spot" and gpu_hot is None:
                            gpu_hot = round(float(val), 1)
                    elif stype == "Fan" and gpu_fan is None:
                        gpu_fan = round(float(val), 1)
                    elif stype == "Control" and gpu_fan_pct is None:
                        gpu_fan_pct = round(float(val), 1)

        payload.update(
            {
                "cpu_package_temp_celsius": cpu_package,
                "cpu_core_avg_celsius": core_avg,
                "cpu_core_max_celsius": core_max,
                "cpu_fan_rpm": cpu_fan,
                "gpu_core_temp_celsius": gpu_core,
                "gpu_hotspot_celsius": gpu_hot,
                "gpu_fan_rpm": gpu_fan,
                "gpu_fan_percent": gpu_fan_pct,
            }
        )

        try:
            comp.Close()
        except Exception:
            pass

    except Exception:
        pass

    print(json.dumps(payload), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
