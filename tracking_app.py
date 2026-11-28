"""Project Nexus desktop workflow for region tracking and effects."""

from dataclasses import replace as with_settings
import math
import os
from pathlib import Path
from queue import Empty, Queue
import sys
from threading import Event, Thread
import time
import tkinter as tk
from tkinter import colorchooser, filedialog, ttk

import cv2
import numpy as np
from tkinterdnd2 import DND_FILES, TkinterDnD

from dots_effect import DOTS
from dots_panel import DotsPanel
from graphics_panel import GraphicsPanel
from graphics_settings import CLEAN, GRAPHIC_MODES
from nexus_diagnostics import DiagnosticsWindow, clock
from nexus_preview import PreviewSpec, PreviewWorker
from scene_effects import CCTV, SCENE_MODES
from studio_effects import (
    ARTWORK, AUTO, FULL_FRAME_LOOKS, FULL_FRAME_MODES, MODES, OUTLINE,
    PRESETS, QUALITY, SCENE_LOOKS, SUBJECT, SURFACE, Look,
    load_preset, save_preset, valid_quad,
)
from tracking_effect import Cancelled, export_track, writes_tracking_data


BG = "#111827"
TEXT = "#f3f6fd"
MUTED = "#c0cbde"
ACCENT = "#78edbe"


class TrackingApp(TkinterDnD.Tk):
    def __init__(self):
        super().__init__()
        self.title("Project Nexus — Tracking Lab")
        self.geometry("1100x780")
        self.minsize(920, 650)
        self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.source = self.first = self.image = self.bounds = None
        self.anchor = self.box = self.selection = None
        self.result = self.play_job = self.scrub_job = self.preview_poll = None
        self.clip = self.displayed = self.inspector = self.dots_panel = self.graphics_panel = None
        self.worker = PreviewWorker()
        self.preview_token = self.pending_since = None
        self.preview_stats = self.preview_fps = self.last_presented = None
        self.preview_channel = "source"
        self.preview_playing = self.loading_clip = self.busy = False
        self.position = 0
        self.activity = "Ready"
        self.render_stats = {}
        self.render_started = 0.0
        self.render_last_sample = None
        self.cancel = Event()
        self.events = Queue()
        defaults = FULL_FRAME_LOOKS[CLEAN]
        self.dots, self.graphics = defaults.dots, defaults.graphics
        self.mode = tk.StringVar(value=defaults.mode)
        self.target = tk.StringVar(value=AUTO)
        self.quality = tk.StringVar(value=defaults.quality)
        self.opacity = tk.IntVar(value=defaults.opacity)
        self.detail = tk.IntVar(value=defaults.detail)
        self.tint = defaults.tint
        self.tracking_speed = tk.IntVar(value=defaults.tracking_speed)
        self.animation_speed = tk.IntVar(value=defaults.animation_speed)
        self.min_boxes = tk.IntVar(value=defaults.min_boxes)
        self.max_boxes = tk.IntVar(value=defaults.max_boxes)
        self.links = tk.BooleanVar(value=defaults.links)
        self.labels = tk.BooleanVar(value=defaults.labels)
        self.trails = tk.BooleanVar(value=defaults.trails)
        self.crops = tk.BooleanVar(value=defaults.crops)
        self.timeline_value = tk.DoubleVar(value=0)
        self.timeline_label = tk.StringVar(value="00:00 / —")
        self.compare = tk.BooleanVar(value=False)
        self.advanced_visible = False
        self.artwork = ""
        self.corners = []
        self.filename = tk.StringVar(value="No video selected")
        self.status = tk.StringVar(value="Drop a video from File Explorer or click Open video.")

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Nexus.TButton", padding=(12, 7), font=("Segoe UI", 10))
        style.configure("Track.TButton", background=ACCENT, foreground="#11251f",
                        font=("Segoe UI", 10, "bold"), padding=(15, 7))
        style.map("Track.TButton", background=[("disabled", "#aebbc5"), ("active", "#a7ffd7")])
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        top = tk.Frame(self, bg=BG)
        top.grid(row=0, column=0, sticky="ew", padx=22, pady=(16, 12))
        self.label(top, text="Project Nexus", size=22, bold=True).pack(side="left")
        self.inspector_button = self.button(top, "Inspector", self.show_inspector)
        self.inspector_button.pack(side="right", padx=(8, 0))
        self.settings_toggle = self.button(top, "Advanced", self.toggle_settings)
        self.settings_toggle.pack(side="right")
        self.graphics_button = self.button(top, "Live controls", self.open_graphics)
        self.graphics_button.pack(side="right", padx=(8, 0))
        self.dots_button = self.button(top, "Dots settings", self.open_dots)
        self.dots_button.pack(side="right", padx=8)
        self.open_button = self.button(top, "Open video…", self.browse)
        self.open_button.pack(side="right", padx=(0, 8))

        self.canvas = tk.Canvas(self, bg="#080d17", highlightthickness=1,
                                highlightbackground="#405270", cursor="crosshair")
        self.canvas.grid(row=1, column=0, sticky="nsew", padx=22)
        for widget in (self, self.canvas):
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self.drop)
        self.canvas.bind("<Configure>", self.resize)
        self.canvas.bind("<ButtonPress-1>", self.press)
        self.canvas.bind("<B1-Motion>", self.drag)
        self.canvas.bind("<ButtonRelease-1>", self.release)
        self.canvas.bind("<Button-3>", self.undo_corner)

        bottom = tk.Frame(self, bg=BG)
        bottom.grid(row=2, column=0, sticky="ew", padx=22, pady=(10, 14))
        self.label(bottom, textvariable=self.filename, color=MUTED, wraplength=680).pack(anchor="w")
        timeline = tk.Frame(bottom, bg=BG)
        timeline.pack(fill="x", pady=(5, 0))
        self.first_button = ttk.Button(timeline, text="First frame", command=self.return_first, state="disabled")
        self.first_button.pack(side="left", padx=(0, 8))
        self.scrubber = ttk.Scale(timeline, from_=0, to=1, variable=self.timeline_value,
                                  command=self.on_scrub, state="disabled", takefocus=True)
        self.scrubber.pack(side="left", fill="x", expand=True)
        self.label(timeline, textvariable=self.timeline_label, color=MUTED, width=16).pack(side="left", padx=9)
        self.compare_button = ttk.Checkbutton(timeline, text="Original", variable=self.compare,
                                               command=self.toggle_original, state="disabled")
        self.compare_button.pack(side="right")
        bar = tk.Frame(bottom, bg=BG)
        bar.pack(fill="x", pady=(8, 7))
        self.effects = self.combo(bar, "Look", self.mode, MODES, 18)
        self.effects.bind("<<ComboboxSelected>>", self.choose_look)
        self.look_button = self.button(bar, "Preview look", self.preview_look, "disabled")
        self.look_button.pack(side="left")
        self.settings_row(bottom)
        self.preview_button = self.button(bar, "Watch export", self.play_preview, "disabled")
        self.preview_button.pack(side="left", padx=(12, 6))
        self.result_button = self.button(bar, "Open MP4", self.open_result, "disabled")
        self.result_button.pack(side="left")
        self.cancel_button = self.button(bar, "Cancel", self.request_cancel, "disabled")
        self.cancel_button.pack(side="right", padx=(8, 0))
        self.track_button = ttk.Button(bar, text="Export video", command=self.start,
                                       style="Track.TButton", state="disabled")
        self.track_button.pack(side="right")
        self.progress = ttk.Progressbar(bottom, mode="determinate")
        self.progress.pack(fill="x")
        self.label(bottom, textvariable=self.status, color=ACCENT, wraplength=680).pack(anchor="w", pady=(5, 0))
        self.change_effect()


    def settings_row(self, bottom):
        self.advanced = ttk.Notebook(bottom)
        motion, layers, files = (tk.Frame(self.advanced, bg=BG, padx=8, pady=7) for _ in range(3))
        for widget, name in ((motion, "Tracking & motion"), (layers, "Layers"), (files, "Presets & export")):
            self.advanced.add(widget, text=name)

        target_row = tk.Frame(motion, bg=BG)
        target_row.pack(fill="x")
        self.targets = self.combo(target_row, "Track", self.target, (AUTO, SUBJECT, SURFACE), 17)
        self.targets.bind("<<ComboboxSelected>>", self.choose_target)
        self.reset = self.button(target_row, "Clear selection", self.change_target, "disabled")
        self.reset.pack(side="left")
        fields = tk.Frame(motion, bg=BG)
        fields.pack(fill="x", pady=(5, 0))
        self.motion_fields = (
            self.spin(fields, "Tracking speed", self.tracking_speed, 0, 100),
            self.spin(fields, "Animation %", self.animation_speed, 0, 250),
            self.spin(fields, "Min boxes", self.min_boxes, 0, 100),
            self.spin(fields, "Max boxes", self.max_boxes, 1, 100),
        )
        self.label(motion, text="Automatic looks · higher tracking speed reacts faster; box minimum depends on visible detail.",
                   color=MUTED).pack(anchor="w", pady=(4, 0))

        appearance = tk.Frame(layers, bg=BG)
        appearance.pack(fill="x")
        self.opacity_field = self.spin(appearance, "Opacity %", self.opacity, 0, 100)
        self.detail_field = self.spin(appearance, "Detail size", self.detail, 2, 24)
        self.tint_button = self.button(appearance, "Tint", self.choose_tint)
        self.tint_button.pack(side="left")
        self.image_button = self.button(appearance, "Choose image…", self.choose_art, "disabled")
        self.image_button.pack(side="left", padx=6)
        switches = tk.Frame(layers, bg=BG)
        switches.pack(fill="x", pady=(6, 0))
        self.layer_fields = tuple(
            ttk.Checkbutton(switches, text=label, variable=value, command=self.refresh_current)
            for label, value in (("Links", self.links), ("Labels", self.labels),
                                 ("Trails", self.trails), ("Live crops", self.crops))
        )
        for button in self.layer_fields:
            button.pack(side="left", padx=(0, 10))
        self.label(layers, text="Scene layers apply where supported by the selected look.", color=MUTED).pack(anchor="w", pady=(4, 0))

        self.sizes = self.combo(files, "Output size", self.quality, tuple(QUALITY), 16)
        self.presets = ttk.Combobox(files, state="readonly", values=tuple(PRESETS), width=17)
        self.presets.set("Apply a preset…")
        self.presets.pack(side="left", padx=(0, 6))
        self.presets.bind("<<ComboboxSelected>>", self.apply_preset)
        self.load_button = self.button(files, "Load preset…", self.read_preset)
        self.load_button.pack(side="left", padx=(0, 5))
        self.save_button = self.button(files, "Save preset…", self.write_preset)
        self.save_button.pack(side="left")
        self.setting_buttons = (
            self.reset, self.opacity_field, self.detail_field, self.tint_button,
            self.load_button, self.save_button, *self.motion_fields, *self.layer_fields,
        )
        self.setting_combos = (self.targets, self.effects, self.sizes, self.presets)

    def spin(self, parent, label, variable, low, high):
        self.label(parent, text=label, color=MUTED).pack(side="left")
        field = ttk.Spinbox(parent, from_=low, to=high, width=5, textvariable=variable,
                            command=self.refresh_current)
        field.pack(side="left", padx=(4, 12))
        field.bind("<Return>", self.refresh_current)
        return field

    def show_inspector(self):
        if self.inspector is None:
            self.inspector = DiagnosticsWindow(self)
        else:
            self.inspector.deiconify()
            self.inspector.lift()

    def open_graphics(self):
        if self.mode.get() not in GRAPHIC_MODES or self.busy:
            return
        if self.graphics_panel is None:
            self.graphics_panel = GraphicsPanel(self, self.current_look())
        else:
            self.graphics_panel.deiconify()
            self.graphics_panel.lift()

    def apply_graphics(self, config, values):
        if self.busy or self.mode.get() not in GRAPHIC_MODES:
            raise ValueError("Live controls are available in the tracking looks before export.")
        look = with_settings(self.current_look(), graphics=config, **values).validate()
        self.graphics = look.graphics
        self.tint = look.tint
        for key in ("opacity", "tracking_speed", "min_boxes", "max_boxes", "links", "labels", "trails"):
            getattr(self, key).set(getattr(look, key))
        if self.clip is None or self.loading_clip or self.compare.get():
            return
        if self.preview_playing and self.preview_channel == "source":
            # The next frame request takes the current settings without pausing playback.
            return
        self.pause_preview()
        self.preview_channel = "source"
        self.request_frame(self.position)

    def open_dots(self):
        if self.mode.get() != DOTS or self.busy:
            return
        if self.dots_panel is None:
            self.dots_panel = DotsPanel(self, self.dots)
        else:
            self.dots_panel.deiconify()
            self.dots_panel.lift()

    def apply_dots(self, settings):
        if self.busy or self.mode.get() != DOTS:
            raise ValueError("Finish the export and select Soft Dots before editing.")
        self.dots = settings
        self.refresh_current()

    def toggle_settings(self):
        self.advanced_visible = not self.advanced_visible
        if self.advanced_visible:
            self.advanced.pack(fill="x", before=self.progress, pady=(0, 8))
            self.settings_toggle.configure(text="Hide advanced")
        else:
            self.advanced.pack_forget()
            self.settings_toggle.configure(text="Advanced")

    def choose_target(self, _event=None):
        target = self.target.get()
        if target == AUTO and self.mode.get() not in FULL_FRAME_MODES:
            self.set_look(SCENE_LOOKS[CCTV])
        elif target != AUTO and self.mode.get() in FULL_FRAME_MODES:
            self.mode.set(OUTLINE)
        self.change_effect()
        self.change_target()

    def choose_look(self, _event=None):
        mode = self.mode.get()
        if mode in FULL_FRAME_MODES:
            look = FULL_FRAME_LOOKS[mode]
            if mode in GRAPHIC_MODES and self.graphics.custom_text:
                look = with_settings(look, graphics=with_settings(
                    look.graphics, custom_text=self.graphics.custom_text
                ))
            self.set_look(look, keep_quality=True)
        elif self.target.get() == AUTO:
            self.target.set(SUBJECT)
            self.change_target()
        self.change_effect()

    def combo(self, parent, label, variable, values, width):
        self.label(parent, text=label, color=MUTED).pack(side="left", padx=(0, 5))
        combo = ttk.Combobox(parent, textvariable=variable, state="readonly", values=values, width=width)
        combo.pack(side="left", padx=(0, 12))
        return combo

    def current_look(self):
        try:
            return Look(
                self.mode.get(), self.opacity.get(), self.detail.get(), self.tint,
                self.quality.get(), self.artwork, tracking_speed=self.tracking_speed.get(),
                animation_speed=self.animation_speed.get(), min_boxes=self.min_boxes.get(),
                max_boxes=self.max_boxes.get(), links=self.links.get(), labels=self.labels.get(),
                trails=self.trails.get(), crops=self.crops.get(), dots=self.dots,
                graphics=self.graphics,
            ).validate()
        except tk.TclError as error:
            raise ValueError("Enter whole numbers for opacity and detail size.") from error

    def change_effect(self, _event=None):
        is_dots = self.mode.get() == DOTS
        self.dots_button.configure(state="normal" if is_dots and not self.busy else "disabled")
        is_graphics = self.mode.get() in GRAPHIC_MODES
        self.graphics_button.configure(state="normal" if is_graphics and not self.busy else "disabled")
        if not is_graphics and self.graphics_panel is not None:
            self.graphics_panel.close()
        if not is_dots and self.dots_panel is not None:
            self.dots_panel.close()
        self.image_button.configure(state="normal" if self.mode.get() == ARTWORK else "disabled")
        self.tint_button.configure(state="disabled" if self.mode.get() == ARTWORK or is_dots else "normal")
        for control in (self.opacity_field, self.detail_field):
            control.configure(state="disabled" if is_dots else "normal")
        state = "normal" if self.mode.get() in SCENE_MODES else "disabled"
        for widget in (*self.motion_fields, *self.layer_fields):
            widget.configure(state=state)
        if self.mode.get() == ARTWORK:
            name = Path(self.artwork).name if self.artwork else "Choose a PNG or JPG overlay."
            self.status.set(name)

    def choose_tint(self):
        _, color = colorchooser.askcolor(color=self.tint, parent=self, title="Effect tint")
        if color:
            self.tint = color
            self.refresh_current()

    def choose_art(self):
        path = filedialog.askopenfilename(parent=self, title="Choose overlay image",
                                          filetypes=[("PNG or JPG", "*.png *.jpg *.jpeg")])
        if path:
            self.artwork = path
            self.status.set(f"Overlay: {Path(path).name}")
            if self.box is not None:
                self.refresh_current()


    def set_look(self, look, keep_quality=False):
        automatic = look.mode in FULL_FRAME_MODES
        changed_target = automatic != (self.target.get() == AUTO)
        self.mode.set(look.mode)
        if not keep_quality:
            self.quality.set(look.quality)
        for field in ("opacity", "detail", "tracking_speed", "animation_speed",
                      "min_boxes", "max_boxes", "links", "labels", "trails", "crops"):
            getattr(self, field).set(getattr(look, field))
        self.tint, self.artwork, self.dots, self.graphics = look.tint, look.artwork, look.dots, look.graphics
        if self.graphics_panel is not None and look.mode in GRAPHIC_MODES:
            self.graphics_panel.synchronize(look)
        if self.dots_panel is not None and look.mode == DOTS:
            self.dots_panel.set_settings(self.dots)
        if changed_target:
            self.target.set(AUTO if automatic else SUBJECT)
            self.change_target()
        else:
            self.refresh_current()
        self.change_effect()

    def apply_preset(self, _event):
        name = self.presets.get()
        self.set_look(PRESETS[name])
        self.presets.set("Apply a preset…")
        self.status.set(f"Applied {name}.")

    def read_preset(self):
        path = filedialog.askopenfilename(parent=self, title="Load a Nexus preset",
                                          filetypes=[("Nexus preset", "*.json")])
        if path:
            try:
                self.set_look(load_preset(Path(path)))
            except (OSError, ValueError) as error:
                self.status.set(f"Could not load preset: {error}")
            else:
                self.status.set(f"Loaded preset {Path(path).stem}.")

    def write_preset(self):
        path = filedialog.asksaveasfilename(parent=self, title="Save a new Nexus preset",
                                           defaultextension=".json",
                                           filetypes=[("Nexus preset", "*.json")])
        if path:
            try:
                save_preset(Path(path), self.current_look())
            except FileExistsError:
                self.status.set("That preset already exists. Choose a new name.")
            except (OSError, ValueError) as error:
                self.status.set(f"Could not save preset: {error}")
            else:
                self.status.set(f"Saved preset {Path(path).stem}.")


    def change_target(self, _event=None):
        if self.loading_clip:
            return
        self.box = self.anchor = None
        self.corners.clear()
        self.stop_preview()
        automatic = self.target.get() == AUTO
        self.reset.configure(state="disabled" if automatic else "normal")
        state = "normal" if automatic and self.first is not None else "disabled"
        self.track_button.configure(state=state)
        self.look_button.configure(state=state)
        if self.first is None:
            return
        if automatic:
            self.request_frame(0, reason="Preparing preview…")
            return
        self.show(self.first)
        text = ("Click the surface corners: top left, top right, bottom right, bottom left."
                if self.target.get() == SURFACE else
                "Drag a rectangle around the subject you want to follow.")
        self.status.set(text)

    def refresh_current(self, _event=None):
        if self.clip is None or self.loading_clip or self.busy:
            return
        if self.target.get() != AUTO and self.box is None:
            return
        self.pause_preview()
        self.preview_channel = "source"
        self.compare.set(False)
        self.request_frame(self.position, reason="Updating look…")

    def preview_look(self):
        self.toggle_play("source")

    def label(self, parent, size=10, color=TEXT, bold=False, **kwargs):
        return tk.Label(parent, bg=BG, fg=color, anchor="w", justify="left",
                        font=("Segoe UI", size, "bold" if bold else "normal"), **kwargs)

    def button(self, parent, text, command, state="normal"):
        return ttk.Button(parent, text=text, command=command, state=state,
                          style="Nexus.TButton")

    def browse(self):
        path = filedialog.askopenfilename(
            parent=self, title="Choose a video",
            filetypes=[("Video files", "*.mp4 *.mov *.avi *.mkv *.webm *.m4v *.wmv"),
                       ("All files", "*.*")],
        )
        if path:
            self.load(Path(path))

    def drop(self, event):
        if self.busy:
            return "refuse_drop"
        paths = self.tk.splitlist(event.data)
        if len(paths) != 1:
            self.status.set("Drop one video file at a time.")
            return "refuse_drop"
        self.load(Path(paths[0]))
        return event.action


    def load(self, path):
        if self.busy:
            return
        if not path.is_file():
            self.status.set("Choose a video file.")
            return
        self.stop_preview()
        self.loading_clip = True
        self.track_button.configure(state="disabled")
        self.look_button.configure(state="disabled")
        for widget in (self.scrubber, self.first_button, self.compare_button):
            widget.configure(state="disabled")
        self.begin_buffer("Opening video…")
        self.submit_preview("open", path)

    def accept_clip(self, clip, frame):
        self.loading_clip = False
        self.clip = clip
        self.source, self.first = clip.path, frame
        self.box = self.result = self.anchor = None
        self.compare.set(False)
        self.filename.set(f"{clip.path.name}   ·   {clip.width} × {clip.height}"
                          + (f"   ·   {clip.fps:g} fps" if clip.fps else ""))
        self.preview_button.configure(state="disabled")
        self.result_button.configure(state="disabled")
        self.set_timeline(0)
        self.scrubber.configure(state="normal" if clip.frames > 1 else "disabled")
        self.first_button.configure(state="normal")
        self.compare_button.configure(state="normal")
        self.change_target()

    def resize(self, _event):
        frame = self.displayed if self.displayed is not None else self.first
        self.show(frame, preview=self.displayed is not None)

    def show(self, frame, preview=False):
        canvas = self.canvas
        canvas.delete("all")
        self.selection = None
        width, height = canvas.winfo_width(), canvas.winfo_height()
        if frame is None:
            canvas.create_text(width / 2, height / 2 - 10, text="Drop a video here",
                               fill=TEXT, font=("Segoe UI", 23, "bold"))
            canvas.create_text(width / 2, height / 2 + 28, text="or click Open video",
                               fill=MUTED, font=("Segoe UI", 11))
            return
        source_h, source_w = frame.shape[:2]
        scale = min(width / source_w, height / source_h)
        w, h = max(1, int(source_w * scale)), max(1, int(source_h * scale))
        x, y = (width - w) // 2, (height - h) // 2
        rgb = cv2.cvtColor(cv2.resize(frame, (w, h)), cv2.COLOR_BGR2RGB)
        self.image = tk.PhotoImage(data=f"P6\n{w} {h}\n255\n".encode() + rgb.tobytes(), format="PPM")
        canvas.create_image(x, y, image=self.image, anchor="nw")
        if not preview:
            self.bounds = (x, y, w, h)
            if self.target.get() == SURFACE:
                points = [(x + cx * w / source_w, y + cy * h / source_h)
                          for cx, cy in self.corners]
                if len(points) >= 2:
                    line = points + points[:1] if len(points) == 4 else points
                    canvas.create_line(line, fill=ACCENT, width=2)
                for index, (px, py) in enumerate(points, 1):
                    canvas.create_oval(px - 4, py - 4, px + 4, py + 4, fill=ACCENT, outline="")
                    canvas.create_text(px + 11, py - 9, text=str(index), fill=ACCENT)
            elif self.box:
                bx, by, bw, bh = self.box
                self.selection = canvas.create_rectangle(
                    x + bx * w / source_w, y + by * h / source_h,
                    x + (bx + bw) * w / source_w, y + (by + bh) * h / source_h,
                    outline=ACCENT, width=2,
                )

    def point(self, event):
        x, y, w, h = self.bounds
        return max(x, min(event.x, x + w)), max(y, min(event.y, y + h))

    def press(self, event):
        if (self.first is None or self.busy or self.loading_clip or self.displayed is not None
                or self.target.get() == AUTO):
            return
        point = self.point(event)
        if point != (event.x, event.y):
            return
        if self.target.get() == SURFACE:
            self.add_corner(point)
            return
        self.anchor = point
        if self.selection:
            self.canvas.delete(self.selection)
        self.selection = self.canvas.create_rectangle(*point, *point, outline=ACCENT, width=2)

    def add_corner(self, point):
        if len(self.corners) == 4:
            self.corners.clear()
        x, y, w, h = self.bounds
        source_h, source_w = self.first.shape[:2]
        self.corners.append(((point[0] - x) * source_w / w, (point[1] - y) * source_h / h))
        self.refresh_corners()

    def undo_corner(self, _event):
        if (self.target.get() == SURFACE and self.corners and not self.busy
                and not self.loading_clip and self.displayed is None):
            self.corners.pop()
            self.refresh_corners()

    def refresh_corners(self):
        good = len(self.corners) == 4 and valid_quad(np.float32(self.corners))
        self.box = tuple(self.corners) if good else None
        for button in (self.track_button, self.look_button):
            button.configure(state="normal" if good else "disabled")
        if len(self.corners) < 4:
            names = ("top left", "top right", "bottom right", "bottom left")
            message = f"Click the {names[len(self.corners)]} corner."
        elif good:
            message = "Surface selected. Preview the effect or click Export video."
        else:
            message = "Choose four corners clockwise from top left. Right-click to undo."
        self.status.set(message)
        self.show(self.first)

    def drag(self, event):
        if self.anchor is not None and self.selection is not None:
            self.canvas.coords(self.selection, *self.anchor, *self.point(event))

    def release(self, event):
        if self.anchor is None:
            return
        x, y, w, h = self.bounds
        source_h, source_w = self.first.shape[:2]
        end_x, end_y = self.point(event)
        left, right = sorted((self.anchor[0], end_x))
        top, bottom = sorted((self.anchor[1], end_y))
        self.anchor = None
        x0, y0 = int((left - x) * source_w / w), int((top - y) * source_h / h)
        x1 = math.ceil((right - x) * source_w / w)
        y1 = math.ceil((bottom - y) * source_h / h)
        if x1 - x0 < 4 or y1 - y0 < 4 or min(right - left, bottom - top) < 4:
            self.box = None
            self.track_button.configure(state="disabled")
            self.look_button.configure(state="disabled")
            self.status.set("Drag a larger rectangle around the target.")
        else:
            self.box = (x0, y0, x1 - x0, y1 - y0)
            self.track_button.configure(state="normal")
            self.look_button.configure(state="normal")
            self.status.set("Target selected. Choose an effect, then click Export video.")
        self.show(self.first)

    def start(self):
        if (self.busy or self.loading_clip or self.source is None
                or (self.box is None and self.target.get() != AUTO)):
            return
        if self.graphics_panel is not None:
            self.graphics_panel.flush()
        self.stop_preview()
        try:
            look = self.current_look()
            if look.mode == ARTWORK and not look.artwork:
                raise ValueError("Choose a PNG or JPG overlay first.")
        except ValueError as error:
            self.status.set(str(error))
            return
        planar = self.target.get() == SURFACE
        has_data = writes_tracking_data(look)
        suffix = "dots" if look.mode == DOTS else "tracked" if has_data else "ascii"
        stem = f"{self.source.stem}-{suffix}"
        candidate = self.source.with_name(f"{stem}.mp4")
        index = 2
        while candidate.exists() or (has_data and candidate.with_suffix(".csv").exists()):
            candidate = self.source.with_name(f"{stem}-{index}.mp4")
            index += 1
        path = filedialog.asksaveasfilename(
            parent=self, title="Save tracked video and its companion CSV" if has_data else "Save effect video",
            initialdir=candidate.parent, initialfile=candidate.name,
            defaultextension=".mp4", filetypes=[("MP4 video", "*.mp4")],
        )
        if not path:
            return
        if self.dots_panel is not None:
            self.dots_panel.close()
        if self.graphics_panel is not None:
            self.graphics_panel.close()
        self.dots_button.configure(state="disabled")
        self.graphics_button.configure(state="disabled")
        self.result = None
        self.busy = True
        self.cancel.clear()
        self.render_started = time.monotonic()
        self.render_last_sample = None
        self.render_stats = {"count": 0, "total": self.clip.frames, "elapsed": 0}
        self.last_render_look = look
        self.activity = "Preparing export"
        self.open_button.configure(state="disabled")
        self.settings_toggle.configure(state="disabled")
        for widget in (*self.setting_buttons, *self.setting_combos, self.image_button, self.look_button):
            widget.configure(state="disabled")
        self.track_button.configure(state="disabled")
        self.preview_button.configure(state="disabled")
        self.result_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        for widget in (self.scrubber, self.first_button, self.compare_button):
            widget.configure(state="disabled")
        self.progress.configure(mode="indeterminate", value=0)
        self.progress.start(12)
        self.status.set("Preparing export…")
        Thread(target=self.render, args=(self.source, self.box, Path(path), look, planar)).start()
        self.after(70, self.poll)

    def render(self, source, box, destination, look, planar):
        def progress(count, total):
            self.events.put(("progress", (count, total, time.monotonic())))

        try:
            count, lost = export_track(
                source, box, destination, look, planar, self.cancel, progress,
                finalizing=lambda: self.events.put(("finalizing", None)),
            )
        except Cancelled:
            self.events.put(("stop", "Tracking cancelled. No new export saved."))
        except Exception as error:
            self.events.put(("stop", f"Export failed: {error}"))
        else:
            self.events.put(("done", (destination, count, lost)))

    def poll(self):
        while True:
            try:
                kind, data = self.events.get_nowait()
            except Empty:
                self.after(70, self.poll)
                return
            if kind == "progress":
                self.render_progress(*data)
                continue
            if kind == "finalizing":
                if not self.cancel.is_set():
                    self.activity = "Finalizing export"
                    self.status.set("Finalizing MP4…" if not writes_tracking_data(self.last_render_look) else
                                    "Finalizing MP4 and tracking data…")
                continue
            self.busy = False
            self.progress.stop()
            self.render_stats["elapsed"] = time.monotonic() - self.render_started
            self.render_stats["eta"] = None
            self.activity = "Ready"
            self.open_button.configure(state="normal")
            self.settings_toggle.configure(state="normal")
            for widget in self.setting_combos:
                widget.configure(state="readonly")
            for widget in self.setting_buttons:
                widget.configure(state="normal")
            self.reset.configure(state="disabled" if self.target.get() == AUTO else "normal")
            self.change_effect()
            self.scrubber.configure(state="normal" if self.clip.frames > 1 else "disabled")
            self.first_button.configure(state="normal")
            self.compare_button.configure(state="normal")
            self.look_button.configure(state="normal")
            self.track_button.configure(state="normal")
            self.cancel_button.configure(state="disabled")
            self.progress.configure(mode="determinate", value=100 if kind == "done" else 0)
            if kind == "done":
                self.result, self.count, self.lost = data
                self.render_stats["count"] = self.count
                self.preview_button.configure(state="normal")
                self.result_button.configure(state="normal")
                self.status.set(self.summary())
            else:
                self.status.set(data)
            return


    def render_progress(self, count, total, now):
        elapsed = now - self.render_started
        previous = self.render_last_sample
        fps = self.render_stats.get("fps")
        if count > 1 and previous and count > previous[0]:
            sample = (count - previous[0]) / max(.001, now - previous[1])
            fps = sample if fps is None else .35 * sample + .65 * fps
        elif count > 1 and fps is None:
            fps = count / max(.001, elapsed)
        if not previous or count > previous[0]:
            self.render_last_sample = count, now
        eta = (total - count) / fps if total > count and fps else None
        self.render_stats = {"count": count, "total": total, "elapsed": elapsed,
                             "fps": fps, "eta": eta}
        if total > 0:
            if str(self.progress.cget("mode")) != "determinate":
                self.progress.stop()
            self.progress.configure(mode="determinate", value=min(99, 100 * count / total))
        if self.cancel.is_set():
            return
        if total and count >= total:
            self.activity = "Finalizing export"
            self.status.set("Finalizing MP4…" if not writes_tracking_data(self.last_render_look) else
                                    "Finalizing MP4 and tracking data…")
            return
        self.activity = "Rendering"
        message = f"Rendering {count:,}" + (f" / {total:,}" if total else " frames")
        if fps:
            message += f"  ·  {fps:.1f} fps"
        if eta is not None:
            message += f"  ·  about {clock(eta + 1)} left"
        self.status.set(message)

    def summary(self):
        duration = clock(self.render_stats.get("elapsed"))
        if not writes_tracking_data(self.last_render_look):
            return f"Saved {self.result.name} in {duration} · {self.count:,} frames."
        return f"Saved {self.result.name} and CSV in {duration}. {len(self.lost):,} of {self.count:,} frames lost."

    def request_cancel(self):
        self.cancel.set()
        self.cancel_button.configure(state="disabled")
        self.activity = "Cancelling export"
        self.status.set("Cancelling…")

    def play_preview(self):
        self.toggle_play("export")

    def timeline_length(self):
        if self.preview_channel == "export" and self.result is not None:
            return self.count
        return self.clip.frames if self.clip is not None else 0

    def set_timeline(self, frame):
        self.position = frame
        total = self.timeline_length()
        rate = (self.clip.fps or 30) if self.clip is not None else 30
        self.scrubber.configure(to=max(1, total - 1))
        self.timeline_value.set(frame)
        self.timeline_label.set(f"{clock(frame / rate)} / {clock(total / rate) if total else '—'}")

    def toggle_play(self, channel):
        if self.busy or self.loading_clip or self.clip is None:
            return
        if self.preview_playing and self.preview_channel == channel:
            self.pause_preview()
            self.status.set("Preview paused. Drag the timeline to inspect another frame.")
            return
        self.pause_preview()
        if self.preview_channel != channel:
            self.preview_channel = channel
            self.set_timeline(0)
        if self.timeline_length() and self.position >= self.timeline_length() - 1:
            self.set_timeline(0)
        self.preview_playing = True
        self.last_presented = None
        button = self.preview_button if channel == "export" else self.look_button
        button.configure(text="Pause")
        self.request_frame(self.position, reason="Buffering preview…")

    def on_scrub(self, value):
        if self.clip is None or self.loading_clip or self.busy or self.timeline_length() < 2:
            return
        self.pause_preview()
        self.worker.invalidate()
        self.preview_token = None
        frame = min(self.timeline_length() - 1, max(0, round(float(value))))
        self.set_timeline(frame)
        if self.scrub_job is not None:
            self.after_cancel(self.scrub_job)
        self.scrub_job = self.after(110, self.finish_scrub)

    def finish_scrub(self):
        self.scrub_job = None
        self.request_frame(self.position, reason="Seeking to selected frame…")

    def return_first(self):
        if self.loading_clip or self.busy:
            return
        self.stop_preview()
        if self.target.get() == AUTO:
            self.request_frame(0, reason="Preparing preview…")
        elif self.first is not None:
            self.status.set("First frame. Draw or adjust the tracking selection here.")

    def toggle_original(self):
        if self.clip is None or self.loading_clip or self.busy:
            return
        self.pause_preview()
        self.preview_channel = "source"
        self.request_frame(self.position, reason="Updating preview…")

    def pause_preview(self):
        self.preview_playing = False
        if self.play_job is not None:
            self.after_cancel(self.play_job)
            self.play_job = None
        self.look_button.configure(text="Preview look")
        self.preview_button.configure(text="Watch export")
        if self.activity == "Playing preview":
            self.activity = "Ready"

    def stop_preview(self):
        self.pause_preview()
        if self.scrub_job is not None:
            self.after_cancel(self.scrub_job)
            self.scrub_job = None
        self.worker.request("reset")
        self.preview_token = None
        if self.preview_poll is not None:
            self.after_cancel(self.preview_poll)
            self.preview_poll = None
        self.end_buffer()
        self.preview_channel = "source"
        self.displayed = None
        self.set_timeline(0)
        self.show(self.first)

    def begin_buffer(self, text):
        self.activity = text.rstrip("…")
        self.status.set(text)
        if str(self.progress.cget("mode")) != "indeterminate":
            self.progress.configure(mode="indeterminate", value=0)
            self.progress.start(12)

    def end_buffer(self):
        if not self.busy and str(self.progress.cget("mode")) == "indeterminate":
            self.progress.stop()
            self.progress.configure(mode="determinate", value=0)
        if not self.busy:
            self.activity = "Ready"

    def request_frame(self, frame, reason=None):
        self.play_job = None
        if self.clip is None or self.loading_clip or self.busy:
            return
        if self.preview_channel == "export" and self.result is not None:
            spec = PreviewSpec(self.result)
        else:
            try:
                look = None if self.compare.get() else self.current_look()
                spec = PreviewSpec(self.source, look, self.box, self.target.get() == SURFACE)
            except ValueError as error:
                self.pause_preview()
                self.end_buffer()
                self.status.set(str(error))
                return
        if reason:
            self.begin_buffer(reason)
        self.submit_preview("frame", spec, frame)

    def submit_preview(self, command, *args):
        self.preview_token = self.worker.request(command, *args)
        self.pending_since = time.monotonic()
        if self.preview_poll is None:
            self.preview_poll = self.after(12, self.poll_preview)

    def poll_preview(self):
        self.preview_poll = None
        while True:
            try:
                token, kind, data = self.worker.replies.get_nowait()
            except Empty:
                break
            if token != self.preview_token:
                continue
            if kind == "progress":
                self.status.set(f"Buffering · tracking {data[0] + 1:,} / {data[1] + 1:,}")
                continue
            self.preview_token = None
            latency = time.monotonic() - self.pending_since
            self.end_buffer()
            if kind == "open":
                self.accept_clip(*data)
            elif kind == "frame":
                self.preview_stats = latency * 1000
                self.show_preview_frame(*data, latency)
            else:
                opening = self.loading_clip
                self.loading_clip = False
                self.pause_preview()
                if opening and self.clip is not None:
                    self.scrubber.configure(state="normal" if self.clip.frames > 1 else "disabled")
                    self.first_button.configure(state="normal")
                    self.compare_button.configure(state="normal")
                    state = "normal" if self.target.get() == AUTO or self.box else "disabled"
                    self.track_button.configure(state=state)
                    self.look_button.configure(state=state)
                self.status.set("End of preview." if kind == "end" else f"Could not load frame: {data}")
        if self.preview_token is not None and self.preview_poll is None:
            if self.preview_playing and time.monotonic() - self.pending_since > .24:
                self.begin_buffer("Buffering preview…")
            self.preview_poll = self.after(12, self.poll_preview)

    def show_preview_frame(self, frame, image, latency):
        self.displayed = image
        self.show(image, preview=True)
        self.set_timeline(frame)
        total = self.timeline_length()
        track_lost = self.preview_channel == "export" and frame in self.lost
        label = "Export" if self.preview_channel == "export" else ("Original" if self.compare.get() else "Preview")
        if self.preview_channel == "source" and self.target.get() != AUTO and self.box is None:
            label = "Source preview · use First frame to select a target"
        position = f"frame {frame + 1:,}" + (f" / {total:,}" if total else "")
        self.status.set(f"{label}  ·  {position}" + ("  ·  Track lost" if track_lost else ""))
        if self.preview_playing:
            now = time.monotonic()
            if self.last_presented is not None:
                speed = 1 / max(.001, now - self.last_presented)
                self.preview_fps = speed if self.preview_fps is None else .25 * speed + .75 * self.preview_fps
            else:
                self.preview_fps = None
            self.last_presented = now
            if total and frame + 1 >= total:
                self.pause_preview()
                self.activity = "Ready"
            else:
                self.activity = "Playing preview"
                rate = self.clip.fps or 30
                delay = max(1, round((1 / rate - latency) * 1000))
                self.play_job = self.after(delay, self.request_frame, frame + 1)

    def open_result(self):
        try:
            os.startfile(self.result)
        except OSError as error:
            self.status.set(f"Could not open the MP4: {error}")

    def close(self):
        if self.busy:
            self.request_cancel()
        else:
            self.stop_preview()
            self.worker.stop()
            if self.inspector is not None:
                self.inspector.close()
            if self.dots_panel is not None:
                self.dots_panel.close()
            if self.graphics_panel is not None:
                self.graphics_panel.close()
            self.destroy()


if __name__ == "__main__":
    app = TrackingApp()
    if len(sys.argv) == 2:
        app.update_idletasks()
        app.load(Path(sys.argv[1]))
    app.mainloop()
