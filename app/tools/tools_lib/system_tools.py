import os
import shlex
import subprocess
import time
import psutil
import pynvml
from pynvml import NVMLError, NVML_TEMPERATURE_GPU


from ._base import FILE_IO_DIR, _format_timedelta


def _get_gpu_stats() -> str:
    try:
        pynvml.nvmlInit()
        gpu_count = pynvml.nvmlDeviceGetCount()
        if gpu_count == 0: return "- GPU Status: No NVIDIA GPUs detected."
        gpu_reports = ["- GPU Status:"]
        for i in range(gpu_count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            name = pynvml.nvmlDeviceGetName(handle)
            mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            temp = pynvml.nvmlDeviceGetTemperature(handle, NVML_TEMPERATURE_GPU)
            power = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000
            gpu_reports.append(
                f"  - GPU {i} ({name}):\n"
                f"    - Usage: {util.gpu}%\n"
                f"    - VRAM: {mem.used / (1024**3):.2f} GB / {mem.total / (1024**3):.2f} GB ({mem.used/mem.total*100:.1f}%)\n"
                f"    - Temperature: {temp}°C\n"
                f"    - Power Draw: {power:.1f} W"
            )
        return "\n".join(gpu_reports)
    except NVMLError as error:
        return f"- GPU Status: Error retrieving GPU data. Reason: {error}"
    finally:
        # This will now execute for cleanup without overriding the return value.
        try:
            pynvml.nvmlShutdown()
        except NVMLError:
            pass  # Ignore shutdown errors


def get_system_status() -> str:
    """Provides a snapshot of the system's current status, including uptime, CPU, memory, disk, and GPU usage."""
    # ... (implementation is unchanged)
    print(f"--- [Alice/System-Status] --- Getting system status.")
    if not psutil: return "Error: The 'psutil' library is not installed. CPU/RAM stats are unavailable."
    try:
        boot_time_timestamp = psutil.boot_time()
        uptime_seconds = time.time() - boot_time_timestamp
        uptime_str = _format_timedelta(uptime_seconds)
        cpu_usage = psutil.cpu_percent(interval=1)
        mem = psutil.virtual_memory()
        mem_total_gb = mem.total / (1024 ** 3)
        mem_used_gb = mem.used / (1024 ** 3)
        mem_percent = mem.percent
        disk = psutil.disk_usage(os.getcwd())
        disk_total_gb = disk.total / (1024 ** 3)
        disk_used_gb = disk.used / (1024 ** 3)
        disk_percent = disk.percent
        gpu_report = _get_gpu_stats()
        status_report = (
            f"System Status Report:\n"
            f"- Uptime: {uptime_str}\n"
            f"- CPU Load: {cpu_usage}%\n"
            f"- Memory Usage: {mem_used_gb:.2f} GB / {mem_total_gb:.2f} GB ({mem_percent}%)\n"
            f"- Disk Usage: {disk_used_gb:.2f} GB / {disk_total_gb:.2f} GB ({disk_percent}%)\n"
            f"{gpu_report}"
        )
        return status_report
    except Exception as e: return f"Error: Could not retrieve system status. Reason: {e}"


def execute_shell_command(command: str, timeout: int = 60, working_dir: str = None) -> str:
    """
    Executes a non-interactive shell command in a secure manner and returns its output.

    Args:
        command: The command to execute (e.g., 'ls -l'). Should not include 'cd'.
        timeout: The maximum time in seconds to wait for the command.
        working_dir: The directory in which to run the command. If None, uses the default safe directory.
    """
    effective_dir = working_dir or FILE_IO_DIR
    print(f"--- [Alice/Shell-Execute] --- Attempting to run: '{command}' in CWD: '{effective_dir}'")

    if not effective_dir or not os.path.isdir(effective_dir):
        return f"Error: Shell execution failed. The working directory '{effective_dir}' is not valid."

    try:
        command_parts = shlex.split(command)

        # Basic security check (can be expanded)
        if command_parts[0] in ['sudo', 'rm', 'mv']:
            return f"Error: For security reasons, the command '{command_parts[0]}' is blocked."

        result = subprocess.run(
            command_parts,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=effective_dir,  # <-- THE KEY CHANGE IS HERE
            check=False
        )

        # Now the "command not found" error will correctly refer to 'uv', not 'cd'.
        if result.returncode != 0:
            stderr_lower = result.stderr.lower()
            # This check is now more accurate.
            if "command not found" in stderr_lower or "no such file or directory" in stderr_lower:
                return f"Error: The command '{command_parts[0]}' was not found. Please ensure it is installed and in the system's PATH."

        output = f"Exit Code: {result.returncode}\n"
        if result.stdout:
            output += f"--- STDOUT ---\n{result.stdout}\n"
        if result.stderr:
            output += f"--- STDERR ---\n{result.stderr}\n"

        return output.strip()

    except FileNotFoundError:
        # This will now correctly trigger if 'uv' itself isn't found
        return f"Error: Command '{command.split()[0]}' not found. Is it installed and in the PATH?"
    except subprocess.TimeoutExpired:
        return f"Error: Command '{command}' timed out after {timeout} seconds."
    except Exception as e:
        return f"Error: An unexpected error occurred. Reason: {e}"


def get_mapping():
    return {
        "system.execute_command": execute_shell_command,  # Executes a non-interactive shell command with a timeout.
        "system.get_status": get_system_status,  # Provides a snapshot of the server's current status (CPU, RAM, GPU).
    }