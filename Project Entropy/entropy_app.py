"""Project Entropy desktop simulator."""

from collections import deque
from dataclasses import asdict, fields as state_fields, replace
import json
import math
import os
import sqlite3
from pathlib import Path
from queue import Empty, Queue
from random import randrange
import re
import subprocess
import sys
from threading import Event, Thread
from time import perf_counter
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk
import traceback

import cv2

from entropy_diagnostics import DiagnosticsWindow, SessionLog, project_directory
from entropy_engine import (
    BLENDS, CUSTOM, MAX_EXPORT_SECONDS, MODES, PALETTES, POOL, PRESETS, RATIOS, ExportSpec, Look,
    capped, decode_look, validate_colors,
)
from entropy_library import Library
from entropy_studio import PalettesWindow, PresetsWindow, TexturesWindow
from entropy_runtime import Cancelled, PreviewWorker, estimate, export_clip, load_preset, save_preset, seconds_label


BG = "#111119"
PANEL = "#191925"
VIEW = "#080811"
TEXT = "#f0edf9"
MUTED = "#afabbd"
ACCENT = "#c7acff"
GREEN = "#95eaca"
AMBER = "#f6c48d"
BORDER = "#30303e"


PREVIEW_MODES = ("Auto", "Eco", "Sharp")
PREVIEW_TIMEOUT = 4
FIELD_NAMES = {
    "seed": "Seed (Motion)",
    "seconds": "Duration (Export)",
    "fps": "Frame rate (Export)",
    "pixels": "Short edge (Export)",
    "ratio": "Aspect ratio (Export)",
}


def parse_duration(value):
    if type(value) is int:
        return value
    value = value.strip()
    if value.isascii() and value.isdecimal():
        return int(value)
    match = re.fullmatch(r"([0-9]{1,2}):([0-5][0-9])", value)
    if not match:
        raise ValueError("Enter whole seconds or m:ss, such as 12:30.")
    minutes, seconds = map(int, match.groups())
    return minutes * 60 + seconds


def duration_clock(seconds):
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes:02d}:{seconds:02d}"


DURATION_CHOICES = tuple(duration_clock(value) for value in (
    15, 30, 60, 120, 300, 600, 900, 1200, MAX_EXPORT_SECONDS,
))


def duration_field(seconds):
    return duration_clock(seconds) if seconds >= 60 else str(seconds)


def read_group(variables, last):
    values = {item.name: getattr(last, item.name) for item in state_fields(last)}
    issues = []
    for key, old_value in values.items():
        if key not in variables or type(old_value) not in (str, int):
            continue
        label = FIELD_NAMES.get(key, key.replace("_", " ").capitalize())
        try:
            raw = variables[key].get()
            if key == "seconds":
                value = parse_duration(raw)
            else:
                value = int(raw) if type(old_value) is int else raw
        except (ValueError, TypeError, AttributeError, tk.TclError):
            message = ("needs whole seconds or m:ss, such as 12:30." if key == "seconds"
                       else "needs a whole number.")
            issues.append(f"{label} {message}")
            continue
        if value != old_value:
            try:
                replace(last, **{key: value}).validate()
            except ValueError as error:
                issues.append(f"{label}: {error}")
                continue
            values[key] = value
    return type(last)(**values), issues


def resume_settings(args):
    if not args:
        return None
    if len(args) != 2 or args[0] != "--resume":
        raise ValueError("Unrecognized startup settings.")
    data = json.loads(args[1])
    look = decode_look(data["look"])
    spec = ExportSpec(**data["export"]).validate()
    phase, looping, quality = float(data["phase"]), data["looping"], data["quality"]
    if not math.isfinite(phase) or not 0 <= phase <= 1 or type(looping) is not bool or quality not in PREVIEW_MODES:
        raise ValueError("Invalid saved preview state.")
    return look, spec, phase, looping, quality


class EntropyApp(tk.Tk):
    def __init__(self, diagnostics=None, resumed=None):
        self.diagnostics = diagnostics or SessionLog()
        super().__init__()
        self.title("Project : Entropy")
        self.geometry("1210x795")
        self.minsize(1010, 705)
        self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.worker = PreviewWorker()
        self.retired_worker = None
        self.preview_failed = False
        self.resume_after_failure = True
        self.diagnostics_window = None
        self.library = Library(project_directory() / ".entropy-data")
        self.tool_windows = {}
        self.events = Queue()
        self.cancel = Event()
        self.job = None
        self.result = None
        self.photo = self.canvas_image = None
        look, spec, phase, looping, quality = resumed or (Look(), ExportSpec(), 0., True, "Auto")
        self.looping = looping
        self.exiting = False
        self.anchor_time = perf_counter()
        self.anchor_phase = phase
        self.last_due = self.anchor_time
        self.current_ticket = self.revision = 0
        self.pending = None
        self.dirty = True
        self.applied = None
        self.configure_job = None
        self.frame_times = deque(maxlen=24)
        self.frame_latency = None
        self.preview_edge = 440 if look.mode == POOL else 640
        self.good_streak = 0
        self.skipped = 0
        self.presented = 0
        self.last_sample = None
        self.render_rate = None

        self.look, self.export = look, spec
        self.fields = {
            name: self.variable(value, editable=name == "seed")
            for name, value in asdict(look).items() if name not in ("textures", "colors")
        }
        self.output = {
            name: tk.StringVar(value=duration_field(value)) if name == "seconds" else self.variable(value)
            for name, value in asdict(spec).items()
        }
        self.preview_mode = tk.StringVar(value=quality)
        self.position_var = tk.DoubleVar(value=0)
        self.video_time = tk.StringVar(value="0.00 / 6 s")
        self.preview_status = tk.StringVar(value="Starting preview…")
        self.preview_info = tk.StringVar(value="—")
        self.resolution = tk.StringVar()
        self.job_status = tk.StringVar(value="Ready to export")
        self.form_status = tk.StringVar()
        self.issue_text = tk.StringVar(value="Diagnostics")
        self.estimate_text = tk.StringVar(value="Estimate samples the current render settings.")
        self.name = tk.StringVar(value=self.look.mode)

        self.setup_styles()
        self.build()
        for variable in (*self.fields.values(), *self.output.values()):
            variable.trace_add("write", self.schedule_controls)
        self.update_issues()
        self.update_output_label()
        if resumed:
            self.diagnostics.record("Restored the last valid look, export settings, and preview position.")
        self.after(12, self.tick)

    def variable(self, value, editable=False):
        kind = tk.IntVar if type(value) is int and not editable else tk.StringVar
        return kind(value=value)

    def setup_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TButton", font=("Segoe UI", 10), padding=(10, 6),
                        background="#2d293b", foreground=TEXT, bordercolor=BORDER,
                        lightcolor=BORDER, darkcolor=BORDER)
        style.map("TButton", background=[("active", "#403750"), ("disabled", "#282631")],
                  foreground=[("disabled", "#777283")])
        style.configure("Issue.TButton", foreground=AMBER, background="#47353a")
        style.configure("Export.TButton", font=("Segoe UI", 10, "bold"), background=ACCENT,
                        foreground="#1d1330", padding=(14, 8))
        style.map("Export.TButton", background=[("active", "#dbc8ff"), ("disabled", "#383246")],
                  foreground=[("disabled", MUTED)])
        style.configure("TCombobox", fieldbackground="#262433", background="#292638",
                        foreground=TEXT, arrowcolor=ACCENT, bordercolor=BORDER, padding=4)
        style.map("TCombobox", fieldbackground=[("readonly", "#262433")],
                  foreground=[("readonly", TEXT)])
        self.option_add("*TCombobox*Listbox.background", "#262433")
        self.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.option_add("*TCombobox*Listbox.selectBackground", "#554572")
        style.configure("TSpinbox", fieldbackground="#262433", foreground=TEXT,
                        background="#292638", arrowcolor=ACCENT, padding=3)
        style.configure("TNotebook", background=PANEL, borderwidth=0)
        style.configure("TNotebook.Tab", background="#242230", foreground=MUTED,
                        padding=(12, 7), font=("Segoe UI", 10))
        style.map("TNotebook.Tab", background=[("selected", "#393049")], foreground=[("selected", TEXT)])
        style.configure("Horizontal.TProgressbar", background=ACCENT,
                        troughcolor="#292537", bordercolor=BORDER, lightcolor=ACCENT, darkcolor=ACCENT)
        style.configure("Horizontal.TScale", background=ACCENT, troughcolor="#292537", bordercolor=BORDER)

    def label(self, parent, text="", *, variable=None, size=10, color=TEXT, bg=BG, bold=False, **options):
        return tk.Label(parent, text=text, textvariable=variable, anchor="w", justify="left", bg=bg,
                        fg=color, font=("Segoe UI", size, "bold" if bold else "normal"), **options)

    def build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        header = tk.Frame(self, bg=BG)
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=(14, 12))
        self.label(header, "Project : Entropy", size=22, bold=True).pack(side="left")
        self.issue_button = ttk.Button(header, textvariable=self.issue_text, command=self.open_diagnostics)
        self.issue_button.pack(side="right")
        self.save_preset_button = ttk.Button(header, text="Save preset…", command=self.save_named_preset)
        self.save_preset_button.pack(side="right", padx=(0, 7))
        for label, tool in (("Presets", PresetsWindow), ("Palettes", PalettesWindow),
                            ("Textures", TexturesWindow)):
            ttk.Button(header, text=label, command=lambda cls=tool: self.open_tool(cls)).pack(
                side="right", padx=(0, 7))

        content = tk.Frame(self, bg=BG)
        content.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 17))
        content.columnconfigure(0, weight=1)
        content.rowconfigure(0, weight=1)

        studio = tk.Frame(content, bg=BG)
        studio.grid(row=0, column=0, sticky="nsew", padx=(0, 15))
        studio.columnconfigure(0, weight=1)
        studio.rowconfigure(1, weight=1)

        strip = tk.Frame(studio, bg=BG)
        strip.grid(row=0, column=0, sticky="ew", pady=(0, 7))
        self.label(strip, variable=self.name, size=13, bold=True).pack(side="left")
        quality = ttk.Combobox(strip, width=8, state="readonly", textvariable=self.preview_mode,
                               values=("Auto", "Eco", "Sharp"))
        quality.pack(side="right")
        quality.bind("<<ComboboxSelected>>", self.preview_quality)
        self.label(strip, "Preview quality", color=MUTED).pack(side="right", padx=(0, 7))

        self.canvas = tk.Canvas(studio, bg=VIEW, highlightbackground=BORDER, highlightthickness=1)
        self.canvas.grid(row=1, column=0, sticky="nsew")
        self.loading = self.canvas.create_text(0, 0, text="Buffering preview…", fill=MUTED, font=("Segoe UI", 12))
        self.canvas.bind("<Configure>", self.resized)

        playback = tk.Frame(studio, bg=BG)
        playback.grid(row=2, column=0, sticky="ew", pady=(8, 7))
        self.play_button = ttk.Button(playback, text="Pause" if self.looping else "Play",
                                      width=8, command=self.toggle_play)
        self.play_button.pack(side="left")
        self.timeline = ttk.Scale(playback, from_=0, to=1, variable=self.position_var, command=self.seek)
        self.timeline.pack(side="left", fill="x", expand=True, padx=10)
        self.label(playback, variable=self.video_time, color=MUTED, width=19).pack(side="right")

        meter = tk.Frame(studio, bg=BG)
        meter.grid(row=3, column=0, sticky="ew")
        self.state_label = self.label(meter, variable=self.preview_status, color=GREEN, bold=True)
        self.state_label.pack(side="left")
        self.restart_button = ttk.Button(meter, text="Restart preview", command=self.restart_preview)
        self.label(meter, variable=self.preview_info, color=MUTED).pack(side="right")

        side = tk.Frame(content, bg=PANEL, padx=12, pady=11, highlightbackground=BORDER, highlightthickness=1)
        side.grid(row=0, column=1, sticky="nsew")
        side.columnconfigure(0, weight=1)
        side.rowconfigure(2, weight=1)
        effect_header = tk.Frame(side, bg=PANEL)
        effect_header.grid(row=0, column=0, sticky="ew", pady=(0, 5))
        self.label(effect_header, "Effect", size=11, bold=True, bg=PANEL).pack(side="left")
        self.reset_effect_button = ttk.Button(effect_header, text="Effect defaults",
                                              command=self.reset_effect_controls)
        self.reset_effect_button.pack(side="right")
        switches = tk.Frame(side, bg=PANEL)
        switches.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        for i, mode in enumerate(MODES):
            switches.columnconfigure(i % 2, weight=1)
            button = tk.Radiobutton(switches, text=mode, value=mode, variable=self.fields["mode"],
                                   command=self.pick_mode, anchor="w", indicatoron=False, padx=9, pady=8,
                                   width=16, bg="#262433", activebackground="#463950", selectcolor="#49395c",
                                   fg=TEXT, activeforeground=TEXT, relief="flat", borderwidth=0,
                                   highlightthickness=0, font=("Segoe UI", 10))
            button.grid(row=i//2, column=i%2, sticky="ew", padx=(0, 4) if i % 2 == 0 else (4, 0), pady=3)

        tabs = ttk.Notebook(side)
        tabs.grid(row=2, column=0, sticky="nsew")
        for name, build in (("Light", self.light_page), ("Motion", self.motion_page), ("Export", self.export_page)):
            page = tk.Frame(tabs, bg=PANEL, padx=8, pady=5)
            tabs.add(page, text=name)
            build(page)

        self.validation_label = self.label(side, variable=self.form_status, color=AMBER,
                                           bg=PANEL, wraplength=292)
        self.validation_label.grid(row=3, column=0, sticky="ew", pady=(5, 0))
        self.validation_label.grid_remove()
        job = tk.Frame(side, bg=PANEL)
        job.grid(row=4, column=0, sticky="ew", pady=(9, 0))
        actions = tk.Frame(job, bg=PANEL)
        actions.pack(fill="x")
        self.export_button = ttk.Button(actions, text="Export MP4", command=self.start_export, style="Export.TButton")
        self.export_button.pack(side="left")
        self.cancel_button = ttk.Button(actions, text="Cancel", command=self.stop_export, state="disabled")
        self.cancel_button.pack(side="left", padx=6)
        self.result_button = ttk.Button(actions, text="Open", command=self.open_result, state="disabled")
        self.result_button.pack(side="right")
        self.progress = ttk.Progressbar(job, mode="determinate", length=150)
        self.progress.pack(fill="x", pady=(8, 4))
        self.label(job, variable=self.job_status, color=MUTED, bg=PANEL, wraplength=294).pack(fill="x")

    def choice(self, parent, label, variable, values, *, editable=False):
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill="x", pady=2)
        self.label(row, label, bg=PANEL).pack(side="left")
        menu = ttk.Combobox(row, textvariable=variable, state="normal" if editable else "readonly",
                            values=values, width=15)
        menu.pack(side="right")
        menu.bind("<<ComboboxSelected>>", self.schedule_controls)
        return menu

    def slider(self, parent, caption, key, low, high):
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill="x", pady=2)
        self.label(row, caption, bg=PANEL).pack(side="left")
        self.label(row, variable=self.fields[key], color=ACCENT, bg=PANEL, width=4).pack(side="right")
        scale = tk.Scale(row, from_=low, to=high, resolution=1, orient="horizontal", length=120,
                         variable=self.fields[key], command=self.schedule_controls, showvalue=False,
                         bg=PANEL, fg=TEXT, activebackground="#dfceff", troughcolor="#3b314c",
                         highlightthickness=0, borderwidth=0, sliderlength=14, width=12)
        scale.pack(side="right", padx=(5, 5))

    def number(self, parent, caption, variable, low, high, command=None):
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill="x", pady=4)
        self.label(row, caption, bg=PANEL).pack(side="left")
        field = ttk.Spinbox(row, from_=low, to=high, textvariable=variable, width=9,
                            command=command or self.schedule_controls)
        field.pack(side="right")
        field.bind("<Return>", self.schedule_controls)
        field.bind("<FocusOut>", self.schedule_controls)
        return row

    def light_page(self, page):
        self.palette_menu = self.choice(page, "Palette", self.fields["palette"], self.palette_choices(self.look))
        self.choice(page, "Blend", self.fields["blend"], BLENDS)
        for caption, key, low, high in (
                ("Hue shift", "hue", -180, 180), ("Spectrum width", "spectrum", 1, 200),
                ("Saturation", "saturation", 0, 150), ("Dispersion", "dispersion", 0, 100),
                ("Glow", "glow", 0, 100), ("Light intensity", "intensity", 0, 150)):
            self.slider(page, caption, key, low, high)
        row = tk.Frame(page, bg=PANEL)
        row.pack(fill="x", pady=3)
        self.label(row, "Background", bg=PANEL).pack(side="left")
        self.color_chip = tk.Label(row, width=3, bg=self.fields["background"].get())
        self.color_chip.pack(side="right", padx=(6, 0), ipady=4)
        ttk.Button(row, text="Choose…", command=self.choose_color).pack(side="right")

    def motion_page(self, page):
        for caption, key, low, high in (
                ("Scatteredness", "scatter", 0, 100), ("Compactness", "compact", 0, 100),
                ("Cycles per loop", "cycles", 0, 5)):
            self.slider(page, caption, key, low, high)
        self.number(page, "Seed", self.fields["seed"], 0, 999999)
        ttk.Button(page, text="Randomize seed", command=self.randomize).pack(anchor="w", pady=6)
        self.label(page, "A seed keeps the same pattern. Zero cycles holds a still frame.",
                   color=MUTED, bg=PANEL, wraplength=273).pack(fill="x", pady=(4, 0))

    def export_page(self, page):
        self.choice(page, "Aspect ratio", self.output["ratio"], tuple(RATIOS))
        self.choice(page, "Short edge", self.output["pixels"], (720, 1080, 1440))
        self.choice(page, "Frame rate", self.output["fps"], (24, 30, 60))
        self.duration_menu = self.choice(page, "Duration (s or m:ss)", self.output["seconds"],
                                         DURATION_CHOICES, editable=True)
        self.choice(page, "Render detail", self.output["quality"], ("Balanced", "Fine", "Native"))
        self.label(page, variable=self.resolution, color=ACCENT, bg=PANEL, wraplength=290).pack(fill="x", pady=7)
        self.estimate_button = ttk.Button(page, text="Estimate render time", command=self.start_estimate)
        self.estimate_button.pack(anchor="w")
        self.label(page, variable=self.estimate_text, color=MUTED, bg=PANEL, wraplength=280).pack(fill="x", pady=(4, 0))

    def choose_color(self):
        _, color = colorchooser.askcolor(self.fields["background"].get(), parent=self, title="Backdrop color")
        if color:
            self.fields["background"].set(color)
            self.read_controls()

    def randomize(self):
        self.fields["seed"].set(randrange(1000000))
        self.read_controls()

    def open_tool(self, tool):
        window = self.tool_windows.get(tool)
        if window is None or not window.winfo_exists():
            self.tool_windows[tool] = tool(self)
        else:
            if hasattr(window, "refresh"):
                window.refresh()
            window.deiconify()
            window.lift()

    @staticmethod
    def palette_choices(look):
        return (*PALETTES, CUSTOM) if look.colors else tuple(PALETTES)

    def pick_mode(self):
        self.capture_settings()

    def reset_effect_controls(self):
        self.capture_settings()
        defaults = PRESETS[self.look.mode]
        self.apply_look(replace(defaults, textures=self.look.textures, colors=self.look.colors))

    def apply_look(self, look):
        for name, control in self.fields.items():
            control.set(getattr(look, name))
        window = self.tool_windows.get(TexturesWindow)
        if window is not None and window.winfo_exists():
            window.sync(look.textures)
        self.read_controls(look)

    def apply_palette(self, colors):
        colors = validate_colors(colors)
        self.fields["palette"].set(CUSTOM)
        self.read_controls(replace(self.look, palette=CUSTOM, colors=colors))

    def apply_textures(self, texture):
        self.read_controls(replace(self.look, textures=texture))

    def apply_preset(self, look, spec):
        for name, value in asdict(spec).items():
            self.output[name].set(duration_field(value) if name == "seconds" else value)
        self.apply_look(look)

    def flush_textures(self):
        window = self.tool_windows.get(TexturesWindow)
        if window is not None and window.winfo_exists():
            window.flush()

    def capture_settings(self):
        self.flush_textures()
        return self.read_controls()

    def schedule_controls(self, *_event):
        if self.configure_job is None:
            self.configure_job = self.after(32, self.read_controls)

    def read_controls(self, look_base=None):
        if self.configure_job is not None:
            self.after_cancel(self.configure_job)
            self.configure_job = None
        look, look_issues = read_group(self.fields, look_base or self.look)
        spec, export_issues = read_group(self.output, self.export)
        for group, issues in (("Look settings", look_issues), ("Export settings", export_issues)):
            if issues:
                self.issue(group, " ".join(issues))
            else:
                self.clear_issue(group)
        issues = look_issues + export_issues
        if issues:
            self.form_status.set(issues[0] + " Preview is using the last valid value.")
            self.validation_label.grid()
        else:
            self.form_status.set("")
            self.validation_label.grid_remove()
        if (look, spec) != (self.look, self.export):
            self.anchor_phase = self.phase(perf_counter())
            self.anchor_time = perf_counter()
            if look.mode != self.look.mode:
                self.preview_edge = 440 if look.mode == POOL else 560
                self.frame_latency = None
                self.good_streak = 0
            self.look, self.export = look, spec
            self.revision += 1
            self.dirty = True
            if self.job is None:
                self.estimate_text.set("Estimate samples the current render settings.")
        self.name.set(look.mode)
        self.palette_menu.configure(values=self.palette_choices(look))
        self.color_chip.configure(bg=look.background)
        self.update_output_label()
        return not issues

    def update_output_label(self):
        width, height = self.export.size
        work_w, work_h = self.export.internal
        label = f"{width:,} × {height:,} · {self.export.frames:,} frames"
        if (work_w, work_h) != (width, height):
            label += f"\nSimulation at {work_w:,} × {work_h:,}"
        self.resolution.set(label)

    def preview_quality(self, _event=None):
        self.preview_edge = 440 if self.look.mode == POOL else 560
        self.good_streak = 0
        self.revision += 1
        self.dirty = True

    def phase(self, now):
        if not self.looping:
            return self.anchor_phase
        return (self.anchor_phase + (now - self.anchor_time) / self.export.seconds) % 1

    def toggle_play(self):
        if self.preview_failed:
            self.restart_preview()
            return
        now = perf_counter()
        self.anchor_phase = self.phase(now)
        self.anchor_time = now
        self.looping = not self.looping
        self.frame_times.clear()
        self.last_due = now
        self.dirty = True
        self.play_button.configure(text="Pause" if self.looping else "Play")

    def seek(self, value):
        self.anchor_phase = min(1., max(0., float(value)))
        self.anchor_time = perf_counter()
        self.looping = False
        self.play_button.configure(text="Play")
        self.dirty = True
        self.revision += 1

    def resized(self, _event):
        self.canvas.coords(self.loading, self.canvas.winfo_width()/2, self.canvas.winfo_height()/2)
        self.dirty = True

    def preview_size(self):
        quality = self.preview_mode.get()
        edge = {"Auto": self.preview_edge, "Eco": 384, "Sharp": 900}[quality]
        if self.job == "export" and quality == "Auto":
            edge = min(edge, 500)
        width, height = self.export.size
        canvas_w, canvas_h = self.canvas.winfo_width(), self.canvas.winfo_height()
        fit = min(canvas_w / width, canvas_h / height)
        if fit > .05:
            edge = min(edge, round(max(width, height) * fit))
        return capped(self.export.size, max(64, edge))

    def tick(self):
        if self.exiting:
            return
        try:
            self.tick_once()
        except Exception as error:
            self.fail_preview(str(error) or type(error).__name__, traceback.format_exc())
        finally:
            if not self.exiting:
                self.after(9 if self.looping else 22, self.tick)

    def tick_once(self):
        self.handle_events()
        now = perf_counter()
        try:
            reply = self.worker.results.get_nowait()
        except Empty:
            reply = None
        if reply:
            self.accept_preview(reply, now)
        phase = self.phase(now)
        self.position_var.set(phase)
        duration = self.export.seconds
        elapsed = phase * duration
        if duration < 60:
            self.video_time.set(f"{elapsed:.2f} / {duration} s")
        else:
            self.video_time.set(f"{duration_clock(int(elapsed))} / {duration_clock(duration)}")
        visible = self.state() not in ("iconic", "withdrawn")
        if self.preview_failed:
            return
        if self.pending is not None and (not self.worker.thread.is_alive()
                                         or now - self.pending[2] > PREVIEW_TIMEOUT):
            self.fail_preview("The preview stopped responding.")
            return
        if visible and self.pending is None and (self.dirty or self.looping and now >= self.last_due):
            self.current_ticket += 1
            size = self.preview_size()
            if self.looping:
                if self.presented == 0:
                    self.last_due = now
                missed = math.floor(max(0, now - self.last_due) * 30)
                self.skipped += missed
                self.last_due += (missed + 1) / 30
            self.worker.request(self.current_ticket, size, phase, self.look)
            self.pending = (self.current_ticket, self.revision, now, self.look)
            self.dirty = False
        elif visible and self.pending is not None and now - self.pending[2] > .16:
            self.preview_status.set("Buffering preview")
            self.state_label.configure(fg=AMBER)
        if not visible:
            self.last_due = now

    def accept_preview(self, reply, now):
        ticket, size, frame, latency, error = reply
        pending = self.pending
        if pending is None or ticket != pending[0]:
            return
        self.pending = None
        outdated = pending[1] != self.revision
        if error:
            if not outdated:
                self.fail_preview(*error)
            return
        self.draw(frame)
        self.applied = pending[3]
        self.presented += 1
        self.clear_issue("Preview")
        if outdated:
            self.preview_status.set("Updating preview…")
            self.state_label.configure(fg=AMBER)
            return
        if self.looping:
            self.frame_times.append(now)
        self.frame_latency = latency if self.frame_latency is None else .22 * latency + .78 * self.frame_latency
        if self.preview_mode.get() == "Auto" and self.looping:
            if self.frame_latency > .027 and self.preview_edge > 256:
                self.preview_edge = max(256, self.preview_edge - 56)
                self.good_streak = 0
            elif self.frame_latency < .016 and self.preview_edge < 640:
                self.good_streak += 1
                if self.good_streak >= 18:
                    self.preview_edge = min(640, self.preview_edge + 32)
                    self.good_streak = 0
            else:
                self.good_streak = 0
        rate = ((len(self.frame_times)-1) / (self.frame_times[-1] - self.frame_times[0])
                if len(self.frame_times) > 1 and self.frame_times[-1] > self.frame_times[0] else None)
        if not self.looping:
            state, color = "Paused", MUTED
        elif self.preview_mode.get() == "Auto" and self.preview_edge < 640:
            state, color = "Adaptive preview", AMBER
        elif rate is not None and rate < 23:
            state, color = "Preview below target", AMBER
        else:
            state, color = "Live", GREEN
        self.preview_status.set(state)
        self.state_label.configure(fg=color)
        stats = f"{latency * 1000:.1f} ms · {size[0]} × {size[1]}"
        if self.looping and rate is not None:
            stats = f"{rate:.1f} / 30 fps · " + stats
        self.preview_info.set(stats + f" · {self.skipped:,} skipped")

    def draw(self, frame):
        height, width = frame.shape[:2]
        canvas_w, canvas_h = self.canvas.winfo_width(), self.canvas.winfo_height()
        scale = min(canvas_w / width, canvas_h / height)
        draw_w, draw_h = max(1, round(width * scale)), max(1, round(height * scale))
        if (draw_w, draw_h) != (width, height):
            frame = cv2.resize(frame, (draw_w, draw_h), interpolation=cv2.INTER_LINEAR)
        self.photo = tk.PhotoImage(data=f"P6\n{draw_w} {draw_h}\n255\n".encode() + frame.tobytes(), format="PPM")
        self.canvas.itemconfigure(self.loading, state="hidden")
        if self.canvas_image is None:
            self.canvas_image = self.canvas.create_image(canvas_w/2, canvas_h/2, image=self.photo)
        else:
            self.canvas.coords(self.canvas_image, canvas_w/2, canvas_h/2)
            self.canvas.itemconfigure(self.canvas_image, image=self.photo)

    def save_named_preset(self, parent=None, feedback=None):
        notify = feedback or self.job_status.set
        if not self.capture_settings():
            notify("Correct the highlighted setting before saving a preset.")
            return
        look, spec = self.look, self.export
        name = simpledialog.askstring("Save preset", "Name", initialvalue=look.mode,
                                      parent=parent or self)
        if name is None:
            return
        try:
            saved = self.library.save_preset(name, look, spec)
        except (OSError, ValueError, sqlite3.Error) as error:
            self.issue("Library", str(error), traceback.format_exc())
            notify(str(error))
        else:
            self.clear_issue("Library")
            window = self.tool_windows.get(PresetsWindow)
            if window is not None and window.winfo_exists():
                window.refresh(saved)
            notify(f"Saved {saved}.")

    def save(self):
        if not self.capture_settings():
            self.job_status.set("Correct the highlighted setting before saving a preset.")
            return
        name = filedialog.asksaveasfilename(parent=self, title="Save Entropy preset",
                                           defaultextension=".json", filetypes=[("Entropy preset", "*.json")])
        if name:
            try:
                save_preset(Path(name), self.look, self.export)
            except (OSError, ValueError) as error:
                self.issue("Preset", "Could not save the preset.", traceback.format_exc())
                self.job_status.set(f"Preset could not be saved: {error}")
            else:
                self.clear_issue("Preset")
                self.job_status.set(f"Saved preset {Path(name).name}")

    def load(self):
        name = filedialog.askopenfilename(parent=self, title="Load Entropy preset",
                                          filetypes=[("Entropy preset", "*.json")])
        if name:
            try:
                look, spec = load_preset(Path(name))
            except (OSError, ValueError) as error:
                self.issue("Preset", "Could not load the preset.", traceback.format_exc())
                self.job_status.set(f"Preset could not be loaded: {error}")
            else:
                self.clear_issue("Preset")
                self.apply_preset(look, spec)
                self.job_status.set(f"Loaded preset {Path(name).name}")

    def start_estimate(self):
        if self.job is not None:
            return
        if not self.capture_settings():
            self.estimate_text.set("Correct the highlighted setting before estimating.")
            return
        self.job = "estimate"
        self.estimate_text.set("Sampling three frames…")
        self.estimate_button.configure(state="disabled")
        self.export_button.configure(state="disabled")
        look, spec = self.look, self.export

        def run():
            try:
                result = estimate(look, spec)
            except Exception as error:
                self.events.put(("estimate-error", (str(error) or type(error).__name__, traceback.format_exc())))
            else:
                self.events.put(("estimate", (look, spec, *result)))

        Thread(target=run, daemon=True, name="Entropy estimate").start()

    def start_export(self):
        if self.job is not None:
            return
        if not self.capture_settings():
            self.job_status.set("Correct the highlighted setting before exporting.")
            return
        filename = filedialog.asksaveasfilename(
            parent=self, title="Save Entropy video", initialfile=f"Entropy-{self.look.mode.replace(' ', '-')}.mp4",
            defaultextension=".mp4", filetypes=[("MP4 video", "*.mp4")], confirmoverwrite=False,
        )
        if not filename:
            return
        path = Path(filename)
        if path.exists() or path.is_symlink():
            self.issue("Export", "An existing output prevented the export.")
            self.job_status.set("That file exists. Choose a new name.")
            return
        self.job = "export"
        self.cancel.clear()
        self.last_sample = None
        self.render_rate = None
        self.export_button.configure(state="disabled")
        self.estimate_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.result_button.configure(state="disabled")
        self.progress.configure(mode="indeterminate", value=0)
        self.progress.start(12)
        self.job_status.set("Preparing export…")
        self.dirty = True
        look, spec = self.look, self.export

        def progress(kind, count, total, elapsed):
            self.events.put((kind, (count, total, elapsed)))

        def run():
            try:
                elapsed = export_clip(path, look, spec, self.cancel, progress)
            except Cancelled:
                self.events.put(("cancelled", None))
            except Exception as error:
                self.events.put(("error", (str(error) or type(error).__name__, traceback.format_exc())))
            else:
                self.events.put(("done", (path, elapsed, spec)))

        Thread(target=run, name="Entropy export").start()

    def handle_events(self):
        while True:
            try:
                kind, value = self.events.get_nowait()
            except Empty:
                return
            if kind == "render":
                self.render_update(*value)
            elif kind == "verify":
                if not self.cancel.is_set():
                    self.job_status.set("Checking the encoded video…")
            elif kind.startswith("estimate"):
                self.job = None
                self.estimate_button.configure(state="normal")
                self.export_button.configure(state="normal")
                if kind == "estimate":
                    self.clear_issue("Estimate")
                    look, spec, elapsed, rate = value
                    if (look, spec) == (self.look, self.export):
                        self.estimate_text.set(f"About {seconds_label(elapsed)} before encoding · {rate:.1f} fps")
                    else:
                        self.estimate_text.set("Settings changed. Estimate again for this look.")
                else:
                    message, detail = value
                    self.issue("Estimate", message, detail)
                    self.estimate_text.set(f"Estimate unavailable: {message}")
            else:
                self.finish_export(kind, value)

    def render_update(self, count, total, elapsed):
        if str(self.progress.cget("mode")) != "determinate":
            self.progress.stop()
        self.progress.configure(mode="determinate", value=min(99, count / total * 100))
        if self.last_sample is not None:
            previous, before = self.last_sample
            if elapsed > before and count > previous:
                recent = (count - previous) / (elapsed - before)
                self.render_rate = recent if self.render_rate is None else .28 * recent + .72 * self.render_rate
        self.last_sample = (count, elapsed)
        if not self.cancel.is_set():
            suffix = (f" · {self.render_rate:.1f} fps · ~{seconds_label((total - count) / self.render_rate)} left"
                      if self.render_rate and total > count else "")
            self.job_status.set(f"Rendering {count:,} / {total:,}{suffix}")

    def finish_export(self, kind, value):
        self.job = None
        self.progress.stop()
        self.progress.configure(mode="determinate", value=100 if kind == "done" else 0)
        self.export_button.configure(state="normal")
        self.estimate_button.configure(state="normal")
        self.cancel_button.configure(state="disabled")
        if kind == "done":
            self.clear_issue("Export")
            path, elapsed, spec = value
            self.result = path
            self.job_status.set(f"Saved {path.name}\n{seconds_label(elapsed)} · {spec.frames / elapsed:.1f} fps")
        elif kind == "cancelled":
            self.job_status.set("Cancelled. No output was saved.")
        else:
            message, detail = value
            self.issue("Export", message, detail)
            self.job_status.set(f"Export failed: {message}")
        self.dirty = True
        self.result_button.configure(state="normal" if self.result is not None else "disabled")

    def stop_export(self):
        self.cancel.set()
        self.cancel_button.configure(state="disabled")
        self.job_status.set("Cancelling export…")

    def open_result(self):
        if self.result:
            try:
                os.startfile(self.result)
            except OSError as error:
                self.issue("Playback", "Could not open the exported video.", traceback.format_exc())
                self.job_status.set(f"Could not open the export: {error}")
            else:
                self.clear_issue("Playback")

    def update_issues(self):
        count = len(self.diagnostics.active)
        title = "Diagnostics" if not count else f"{count} issue" + ("s" if count != 1 else "")
        self.issue_text.set(title)
        self.issue_button.configure(style="Issue.TButton" if count else "TButton")

    def issue(self, area, message, detail=None):
        self.diagnostics.issue(area, message, detail)
        self.update_issues()

    def clear_issue(self, area):
        if area in self.diagnostics.active:
            self.diagnostics.clear(area)
            self.update_issues()

    def report_callback_exception(self, error_type, error, stack):
        self.issue("Interface", str(error) or error_type.__name__,
                   "".join(traceback.format_exception(error_type, error, stack)))

    def open_diagnostics(self):
        if self.diagnostics_window is None:
            self.diagnostics_window = DiagnosticsWindow(self)
        else:
            self.diagnostics_window.deiconify()
            self.diagnostics_window.lift()

    def fail_preview(self, message, detail=None):
        if not self.preview_failed:
            self.resume_after_failure = self.looping
        self.anchor_phase = self.phase(perf_counter())
        self.looping = self.dirty = False
        self.preview_failed = True
        self.pending = None
        self.issue("Preview", message, detail)
        self.preview_status.set("Preview stopped")
        self.state_label.configure(fg=AMBER)
        self.play_button.configure(text="Restart")
        self.restart_button.pack(side="left", padx=8)

    def restart_preview(self):
        if self.retired_worker is not None and self.retired_worker.thread.is_alive():
            self.issue("Preview", "An earlier preview is still finishing. Restart the app if it remains stuck.")
            return
        self.read_controls()
        now = perf_counter()
        self.anchor_phase = self.phase(now)
        self.anchor_time = self.last_due = now
        self.looping = self.resume_after_failure if self.preview_failed else self.looping
        self.worker.close()
        self.retired_worker = self.worker
        self.worker = PreviewWorker()
        self.revision += 1
        self.pending = None
        self.preview_failed = False
        self.dirty = True
        self.frame_times.clear()
        self.frame_latency = None
        self.good_streak = self.skipped = 0
        self.preview_edge = 440 if self.look.mode == POOL else 560
        self.preview_status.set("Restarting preview…")
        self.play_button.configure(text="Pause" if self.looping else "Play")
        self.restart_button.pack_forget()
        self.diagnostics.record("Preview restarted with the last valid settings.")

    def restart_app(self):
        if self.job == "export":
            self.job_status.set("Finish or cancel the export before restarting the app.")
            return
        self.capture_settings()
        state = json.dumps({"look": asdict(self.look), "export": asdict(self.export),
                            "phase": self.phase(perf_counter()),
                            "looping": self.resume_after_failure if self.preview_failed else self.looping,
                            "quality": self.preview_mode.get()})
        executable = [sys.executable]
        if not getattr(sys, "frozen", False):
            executable.append(str(Path(__file__).resolve()))
        try:
            subprocess.Popen([*executable, "--resume", state], cwd=project_directory(),
                             env={**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"},
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as error:
            self.issue("Restart", str(error), traceback.format_exc())
        else:
            self.diagnostics.record("App restart requested with the last valid settings.")
            self.close()

    def close(self):
        if self.job == "export":
            self.stop_export()
            return
        self.exiting = True
        self.worker.close()
        if self.diagnostics_window is not None:
            self.diagnostics_window.close()
        self.diagnostics.close()
        self.destroy()


def main():
    diagnostics = SessionLog()
    try:
        try:
            resumed = resume_settings(sys.argv[1:])
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            diagnostics.issue("Restore", str(error), traceback.format_exc())
            resumed = None
        EntropyApp(diagnostics, resumed).mainloop()
    except Exception as error:
        diagnostics.issue("Startup", str(error) or type(error).__name__, traceback.format_exc())
        messagebox.showerror("Entropy could not start",
                             f"{error}\n\nSession log: {diagnostics.path or 'Unavailable'}")
    finally:
        diagnostics.close()


if __name__ == "__main__":
    main()
