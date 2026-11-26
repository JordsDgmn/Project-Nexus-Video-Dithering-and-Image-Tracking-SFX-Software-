"""Optional clip and Windows resource monitor for Nexus."""

import ctypes as ct
from ctypes import wintypes as wt
import json
import os
import platform
import shutil
import subprocess
from threading import Thread
import time
import tkinter as tk
from tkinter import ttk

import cv2


def clock(seconds):
    if seconds is None:
        return "—"
    whole = max(0, int(seconds))
    hours, rest = divmod(whole, 3600)
    minutes, remaining = divmod(rest, 60)
    return f"{hours:d}:{minutes:02d}:{remaining:02d}" if hours else f"{minutes:02d}:{remaining:02d}"


def amount(value):
    if value is None:
        return "—"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"
        value /= 1024


def clip_rows(clip):
    if clip is None:
        return [("Video", "No clip loaded")]
    return [
        ("File", clip.path.name), ("Location", str(clip.path)),
        ("Dimensions", f"{clip.width} × {clip.height}"),
        ("Frame rate", f"{clip.fps:g} fps" if clip.fps else "Unknown"),
        ("Frames", f"{clip.frames:,}" if clip.frames else "Unknown"),
        ("Duration", clock(clip.frames / clip.fps) if clip.frames and clip.fps else "Unknown"),
        ("Codec", clip.codec), ("Pixel format", clip.pixel_format),
        ("Source bitrate", f"{clip.bitrate:g} kb/s" if clip.bitrate > 0 else "Unknown"),
        ("Pixel aspect ratio", f"{clip.aspect[0]}:{clip.aspect[1]}" if all(clip.aspect) else "Unknown"),
        ("Rotation metadata", f"{clip.rotation:g}°"),
        ("Decoder", clip.backend), ("File size", amount(clip.size)),
    ]


class MemoryStatus(ct.Structure):
    _fields_ = [("length", wt.DWORD), ("load", wt.DWORD),
                *[(name, ct.c_ulonglong) for name in
                  ("total", "available", "page_total", "page_available",
                   "virtual_total", "virtual_available", "virtual_ext")]]


class ProcessMemory(ct.Structure):
    _fields_ = [("length", wt.DWORD), ("faults", wt.DWORD),
                *[(name, ct.c_size_t) for name in
                  ("peak", "working", "peak_paged", "paged", "peak_nonpaged",
                   "nonpaged", "page", "peak_page")]]


def filetime(value):
    return (value.dwHighDateTime << 32) + value.dwLowDateTime


class Resources:
    def __init__(self):
        self.kernel = ct.WinDLL("kernel32", use_last_error=True)
        self.psapi = ct.WinDLL("psapi", use_last_error=True)
        self.kernel.GetCurrentProcess.restype = wt.HANDLE
        self.psapi.GetProcessMemoryInfo.argtypes = (wt.HANDLE, ct.POINTER(ProcessMemory), wt.DWORD)
        self.previous = None
        self.logical = os.cpu_count() or 1

    def sample(self):
        idle, kernel, user = (wt.FILETIME() for _ in range(3))
        ok = self.kernel.GetSystemTimes(ct.byref(idle), ct.byref(kernel), ct.byref(user))
        total, unused = filetime(kernel) + filetime(user), filetime(idle)
        now, process = time.monotonic(), time.process_time()
        overall = app = None
        if self.previous:
            old_total, old_idle, old_time, old_process = self.previous
            if ok and total > old_total:
                overall = 100 * (1 - (unused - old_idle) / (total - old_total))
            if now > old_time:
                app = 100 * (process - old_process) / (now - old_time) / self.logical
        self.previous = total, unused, now, process
        mem = MemoryStatus()
        mem.length = ct.sizeof(mem)
        mem_ok = self.kernel.GlobalMemoryStatusEx(ct.byref(mem))
        current = ProcessMemory()
        current.length = ct.sizeof(current)
        app_ok = self.psapi.GetProcessMemoryInfo(self.kernel.GetCurrentProcess(),
                                                ct.byref(current), current.length)
        return {
            "cpu": overall, "app_cpu": app, "ram_total": mem.total if mem_ok else None,
            "ram_used": mem.total - mem.available if mem_ok else None,
            "app_ram": current.working if app_ok else None, "peak_ram": current.peak if app_ok else None,
        }


def powershell(script, timeout):
    system = os.environ.get("SystemRoot", r"C:\Windows")
    executable = os.path.join(system, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    result = subprocess.run(
        [executable, "-NoProfile", "-NonInteractive", "-Command",
         "[Console]::OutputEncoding = [Text.UTF8Encoding]::new(); " + script],
        capture_output=True, encoding="utf-8", errors="replace", timeout=timeout,
        creationflags=subprocess.CREATE_NO_WINDOW, check=True,
    )
    return json.loads(result.stdout)


def hardware():
    return powershell(
        '$ErrorActionPreference="Stop"; '
        '$cpu=@(Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors); '
        '$gpu=@(Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion); '
        '$pc=Get-CimInstance Win32_ComputerSystem; '
        '@{cpu=$cpu; gpu=$gpu; model=($pc.Manufacturer+" "+$pc.Model)} | ConvertTo-Json -Compress -Depth 4',
        12,
    )


def gpu_load():
    return powershell(
        '$ErrorActionPreference="Stop"; '
        '$eng=@(Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine '
        '| Group-Object { $_.Name -replace "^pid_[0-9]+_", "" } '
        '| ForEach-Object { ($_.Group | Measure-Object UtilizationPercentage -Sum).Sum }); '
        '$peak=($eng | Measure-Object -Maximum).Maximum; '
        '@{peak=$peak} | ConvertTo-Json -Compress', 9,
    )


def percent(value):
    return f"{min(100, max(0, value)):.1f}%" if value is not None else "—"


class DiagnosticsWindow(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Nexus · Inspector")
        self.geometry("620x460")
        self.minsize(480, 365)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.resources = Resources()
        self.hardware_data = None
        self.gpu = None
        self.probe = None
        self.timer = None
        self.next_gpu = 0
        self.views = {}
        self.last = {}
        tabs = ttk.Notebook(self, padding=8)
        tabs.pack(fill="both", expand=True)
        for tab in ("Video", "Hardware", "Performance"):
            panel = ttk.Frame(tabs)
            tabs.add(panel, text=tab)
            tree = ttk.Treeview(panel, columns=("name", "value"), show="headings", selectmode="browse")
            tree.heading("name", text="Property")
            tree.heading("value", text="Value")
            tree.column("name", width=155, minwidth=105, stretch=False)
            tree.column("value", width=400, minwidth=220)
            yscroll = ttk.Scrollbar(panel, orient="vertical", command=tree.yview)
            xscroll = ttk.Scrollbar(panel, orient="horizontal", command=tree.xview)
            tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
            tree.grid(row=0, column=0, sticky="nsew")
            yscroll.grid(row=0, column=1, sticky="ns")
            xscroll.grid(row=1, column=0, sticky="ew")
            panel.columnconfigure(0, weight=1)
            panel.rowconfigure(0, weight=1)
            self.views[tab] = tree
        tabs.select(2)
        self.worker(hardware, "hardware_data")
        self.refresh()

    def worker(self, callback, attribute):
        def run():
            try:
                result = callback()
            except (OSError, subprocess.SubprocessError, ValueError):
                result = {}
            setattr(self, attribute, result)

        self.probe = Thread(target=run, daemon=True, name="Nexus system information")
        self.probe.start()

    def update_rows(self, tab, rows):
        if self.last.get(tab) == rows:
            return
        self.last[tab] = rows
        tree = self.views[tab]
        existing = tree.get_children()
        for index, values in enumerate(rows):
            if index < len(existing):
                tree.item(existing[index], values=values)
            else:
                tree.insert("", "end", values=values)
        if len(existing) > len(rows):
            tree.delete(*existing[len(rows):])

    def refresh(self):
        app = self.app
        data = self.resources.sample()
        current = time.monotonic()
        if current >= self.next_gpu and (self.probe is None or not self.probe.is_alive()):
            self.worker(gpu_load, "gpu")
            self.next_gpu = current + 6
        video_rows = clip_rows(app.clip) + [("Last export", str(app.result or "—"))]
        if app.result:
            try:
                size = app.result.stat().st_size
            except OSError:
                size = None
            video_rows += [("Export size on disk", amount(size)),
                           ("Export resolution preset", app.last_render_look.quality),
                           ("Export frames", f"{app.count:,}")]
        self.update_rows("Video", video_rows)

        hardware_data = self.hardware_data or {}
        rows = [
            ("Computer", hardware_data.get("model", "Reading hardware…" if self.hardware_data is None else "Unavailable")),
            ("Windows", platform.platform()), ("Logical CPU threads", str(os.cpu_count() or "—")),
            ("Installed memory", amount(data["ram_total"])),
        ]
        for cpu in hardware_data.get("cpu", []):
            rows += [("CPU", cpu.get("Name", "—")), ("Physical cores", str(cpu.get("NumberOfCores", "—")))]
        for gpu in hardware_data.get("gpu", []):
            rows += [("Graphics", gpu.get("Name", "—")), ("Driver", gpu.get("DriverVersion", "—"))]
        if app.clip:
            try:
                free = shutil.disk_usage(app.clip.path.parent).free
            except OSError:
                free = None
            rows.append(("Source drive free", amount(free)))
        rows.extend([("Python runtime", platform.python_version()), ("OpenCV", cv2.__version__)])
        self.update_rows("Hardware", rows)

        stats = app.render_stats
        preview = app.preview_stats
        self.update_rows("Performance", [
            ("App activity", app.activity),
            ("System CPU", percent(data["cpu"])), ("Nexus CPU", percent(data["app_cpu"])),
            ("GPU engine peak", percent((self.gpu or {}).get("peak"))),
            ("System memory", f"{amount(data['ram_used'])} / {amount(data['ram_total'])}"),
            ("Nexus memory", amount(data["app_ram"])), ("Nexus peak memory", amount(data["peak_ram"])),
            ("Preview frame latency", f"{preview:.0f} ms" if preview is not None else "—"),
            ("Preview playback rate", f"{app.preview_fps:.1f} fps" if app.preview_fps is not None else "—"),
            ("Render frames", f"{stats['count']:,} / {stats['total']:,}" if stats.get("total") else f"{stats.get('count', 0):,}"),
            ("Render throughput", f"{stats['fps']:.1f} fps" if stats.get("fps") else "—"),
            ("Render elapsed", clock(stats.get("elapsed"))),
            ("Render time left", clock(stats.get("eta"))),
        ])
        self.timer = self.after(1000, self.refresh)

    def close(self):
        if self.timer is not None:
            self.after_cancel(self.timer)
        self.app.inspector = None
        self.destroy()
