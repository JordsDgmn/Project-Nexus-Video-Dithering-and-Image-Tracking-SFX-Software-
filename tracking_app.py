"""Project Nexus desktop workflow for region tracking and effects."""

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

from scene_effects import CCTV, SCENE_MODES, SceneTracker, paint_scene
from studio_effects import (
    ARTWORK, AUTO, MODES, OUTLINE, PRESETS, QUALITY, SCENE_LOOKS, SUBJECT, SURFACE, Effect, Look,
    box_corners, load_preset, save_preset, valid_quad,
)
from tracking_effect import Cancelled, export_track


BG = "#111827"
TEXT = "#f3f6fd"
MUTED = "#c0cbde"
ACCENT = "#78edbe"


class TrackingApp(TkinterDnD.Tk):
    def __init__(self):
        super().__init__()
        self.title("Project Nexus — Auto Looks")
        self.geometry("1070x740")
        self.minsize(900, 570)
        self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.source = self.first = self.image = self.bounds = None
        self.anchor = self.box = self.selection = None
        self.result = self.player = self.play_job = None
        self.busy = False
        self.cancel = Event()
        self.events = Queue()
        defaults = SCENE_LOOKS[CCTV]
        self.mode = tk.StringVar(value=defaults.mode)
        self.target = tk.StringVar(value=AUTO)
        self.quality = tk.StringVar(value=defaults.quality)
        self.opacity = tk.IntVar(value=defaults.opacity)
        self.detail = tk.IntVar(value=defaults.detail)
        self.tint = defaults.tint
        self.live_look = self.live_tracker = None
        self.still = None
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
        self.settings_toggle = self.button(top, "Advanced", self.toggle_settings)
        self.settings_toggle.pack(side="right")
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

    def settings_row(self, bottom):
        self.advanced = tk.Frame(bottom, bg=BG)
        options = tk.Frame(self.advanced, bg=BG)
        options.pack(fill="x", pady=(6, 0))
        self.targets = self.combo(options, "Track", self.target, (AUTO, SUBJECT, SURFACE), 17)
        self.targets.bind("<<ComboboxSelected>>", self.choose_target)
        self.sizes = self.combo(options, "Output size", self.quality, tuple(QUALITY), 16)
        self.reset = self.button(options, "Clear selection", self.change_target, "disabled")
        self.reset.pack(side="right")
        self.image_button = self.button(options, "Choose image…", self.choose_art, "disabled")
        self.image_button.pack(side="left")

        controls = tk.Frame(self.advanced, bg=BG)
        controls.pack(fill="x", pady=(6, 0))
        self.label(controls, text="Opacity %", color=MUTED).pack(side="left")
        self.opacity_field = ttk.Spinbox(controls, from_=0, to=100, width=4, textvariable=self.opacity)
        self.opacity_field.pack(side="left", padx=(4, 10))
        self.label(controls, text="Detail size", color=MUTED).pack(side="left")
        self.detail_field = ttk.Spinbox(controls, from_=2, to=24, width=4, textvariable=self.detail)
        self.detail_field.pack(side="left", padx=(4, 10))
        self.tint_button = self.button(controls, "Tint", self.choose_tint)
        self.tint_button.pack(side="left")

        self.presets = ttk.Combobox(controls, state="readonly", values=tuple(PRESETS), width=16)
        self.presets.set("Apply a preset…")
        self.presets.pack(side="left", padx=(4, 5))
        self.presets.bind("<<ComboboxSelected>>", self.apply_preset)
        self.load_button = self.button(controls, "Load preset…", self.read_preset)
        self.load_button.pack(side="left", padx=(0, 5))
        self.save_button = self.button(controls, "Save preset…", self.write_preset)
        self.save_button.pack(side="left")
        self.setting_buttons = (
            self.reset, self.opacity_field, self.detail_field,
            self.tint_button, self.load_button, self.save_button,
        )
        self.setting_combos = (self.targets, self.effects, self.sizes, self.presets)

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
        if target == AUTO and self.mode.get() not in SCENE_MODES:
            self.set_look(SCENE_LOOKS[CCTV])
        elif target != AUTO and self.mode.get() in SCENE_MODES:
            self.mode.set(OUTLINE)
        self.change_effect()
        self.change_target()

    def choose_look(self, _event=None):
        mode = self.mode.get()
        if mode in SCENE_MODES:
            self.set_look(SCENE_LOOKS[mode], keep_quality=True)
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
            return Look(self.mode.get(), self.opacity.get(), self.detail.get(), self.tint,
                        self.quality.get(), self.artwork).validate()
        except tk.TclError as error:
            raise ValueError("Enter whole numbers for opacity and detail size.") from error

    def change_effect(self, _event=None):
        self.image_button.configure(state="normal" if self.mode.get() == ARTWORK else "disabled")
        self.tint_button.configure(state="disabled" if self.mode.get() == ARTWORK else "normal")
        if self.mode.get() == ARTWORK:
            name = Path(self.artwork).name if self.artwork else "Choose a PNG or JPG overlay."
            self.status.set(name)

    def choose_tint(self):
        _, color = colorchooser.askcolor(color=self.tint, parent=self, title="Effect tint")
        if color:
            self.tint = color
            self.status.set(f"Tint set to {color}. Click Preview look to see it.")

    def choose_art(self):
        path = filedialog.askopenfilename(parent=self, title="Choose overlay image",
                                          filetypes=[("PNG or JPG", "*.png *.jpg *.jpeg")])
        if path:
            self.artwork = path
            self.status.set(f"Overlay: {Path(path).name}")

    def set_look(self, look, keep_quality=False):
        self.stop_preview()
        self.mode.set(look.mode)
        if not keep_quality:
            self.quality.set(look.quality)
        self.opacity.set(look.opacity)
        self.detail.set(look.detail)
        self.tint, self.artwork = look.tint, look.artwork
        if look.mode in SCENE_MODES:
            self.target.set(AUTO)
            self.change_target()
        elif self.target.get() == AUTO:
            self.target.set(SUBJECT)
            self.change_target()
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
        self.stop_preview()
        self.box = self.anchor = None
        self.still = None
        self.corners.clear()
        automatic = self.target.get() == AUTO
        self.reset.configure(state="disabled" if automatic else "normal")
        state = "normal" if automatic and self.first is not None else "disabled"
        self.track_button.configure(state=state)
        self.look_button.configure(state=state)
        if self.first is None:
            return
        if automatic:
            self.show_scene_still()
            return
        self.show(self.first)
        text = ("Click the surface corners: top left, top right, bottom right, bottom left."
                if self.target.get() == SURFACE else
                "Drag a rectangle around the subject you want to follow.")
        self.status.set(text)

    def show_scene_still(self):
        try:
            look = self.current_look()
            tracker = SceneTracker(look.detail)
            frame = self.preview_size(self.first)
            self.still = paint_scene(frame, tracker.update(frame), look, 0, 30, tracker.crop_ids)
            self.show(self.still)
            self.status.set("Choose a look, preview it in motion, or export.")
        except (cv2.error, ValueError) as error:
            self.show(self.first)
            self.status.set(f"Could not preview look: {error}")

    def preview_size(self, frame):
        height, width = frame.shape[:2]
        scale = min(1., 820 / max(width, height))
        if scale < 1:
            return cv2.resize(frame, (max(1, round(width * scale)), max(1, round(height * scale))),
                              interpolation=cv2.INTER_AREA)
        return frame

    def preview_look(self):
        if self.target.get() == AUTO:
            if self.live_look is not None:
                self.stop_preview()
            else:
                self.preview_scene()
            return
        if self.box is None:
            return
        self.stop_preview()
        try:
            effect = Effect(self.current_look())
            planar = self.target.get() == SURFACE
            quad = np.float32(self.box) if planar else box_corners(self.box)
            frame = self.first.copy()
            effect.apply(frame, quad, planar)
        except (OSError, ValueError, cv2.error) as error:
            self.status.set(f"Could not preview look: {error}")
        else:
            self.show(frame)
            self.status.set("First-frame effect preview. Click Export video to process the clip.")

    def preview_scene(self):
        if self.source is None:
            return
        self.stop_preview()
        try:
            look = self.current_look()
        except ValueError as error:
            self.status.set(str(error))
            return
        self.player = cv2.VideoCapture(str(self.source))
        if not self.player.isOpened():
            self.stop_preview()
            self.status.set("Could not open the clip for preview.")
            return
        self.live_look = look
        self.live_tracker = SceneTracker(look.detail)
        self.play_index = 0
        self.play_fps = self.player.get(cv2.CAP_PROP_FPS) or 30
        self.play_start = time.monotonic()
        self.look_button.configure(text="Stop preview")
        self.play_frame()

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
        cap = cv2.VideoCapture(str(path))
        try:
            ok, frame = cap.read()
        finally:
            cap.release()
        if not ok:
            self.status.set("Could not open that video. Try a file you can play on this PC.")
            return
        self.stop_preview()
        self.source, self.first = path, frame
        self.box = self.result = self.anchor = None
        self.filename.set(path.name)
        self.change_target()
        self.preview_button.configure(state="disabled")
        self.result_button.configure(state="disabled")
        self.progress.configure(value=0)

    def resize(self, _event):
        if self.player is None:
            self.show(self.still if self.still is not None else self.first)

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
        if self.first is None or self.busy or self.player is not None or self.target.get() == AUTO:
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
        if self.target.get() == SURFACE and self.corners and not self.busy and self.player is None:
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
        if self.busy or self.source is None or (self.box is None and self.target.get() != AUTO):
            return
        self.stop_preview()
        try:
            look = self.current_look()
            if look.mode == ARTWORK and not look.artwork:
                raise ValueError("Choose a PNG or JPG overlay first.")
        except ValueError as error:
            self.status.set(str(error))
            return
        planar = self.target.get() == SURFACE
        stem = f"{self.source.stem}-tracked"
        candidate = self.source.with_name(f"{stem}.mp4")
        index = 2
        while candidate.exists() or candidate.with_suffix(".csv").exists():
            candidate = self.source.with_name(f"{stem}-{index}.mp4")
            index += 1
        path = filedialog.asksaveasfilename(
            parent=self, title="Save tracked video and its companion CSV",
            initialdir=candidate.parent, initialfile=candidate.name,
            defaultextension=".mp4", filetypes=[("MP4 video", "*.mp4")],
        )
        if not path:
            return
        self.result = None
        self.busy = True
        self.cancel.clear()
        self.open_button.configure(state="disabled")
        self.settings_toggle.configure(state="disabled")
        for widget in (*self.setting_buttons, *self.setting_combos, self.image_button, self.look_button):
            widget.configure(state="disabled")
        self.track_button.configure(state="disabled")
        self.preview_button.configure(state="disabled")
        self.result_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.progress.configure(value=0)
        self.status.set("Tracking and exporting…")
        Thread(target=self.render, args=(self.source, self.box, Path(path), look, planar)).start()
        self.after(70, self.poll)

    def render(self, source, box, destination, look, planar):
        def progress(count, total):
            self.events.put(("progress", (count, total)))

        try:
            count, lost = export_track(source, box, destination, look, planar, self.cancel, progress)
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
                count, total = data
                self.progress.configure(value=min(99, count * 100 / total) if total > 0 else 0)
                if not self.cancel.is_set():
                    self.status.set(f"Tracking frame {count:,}" + (f" of {total:,}…" if total > 0 else "…"))
                continue
            self.busy = False
            self.open_button.configure(state="normal")
            self.settings_toggle.configure(state="normal")
            for widget in self.setting_combos:
                widget.configure(state="readonly")
            for widget in self.setting_buttons:
                widget.configure(state="normal")
            self.reset.configure(state="disabled" if self.target.get() == AUTO else "normal")
            self.image_button.configure(state="normal" if self.mode.get() == ARTWORK else "disabled")
            if self.mode.get() == ARTWORK:
                self.tint_button.configure(state="disabled")
            self.look_button.configure(state="normal")
            self.track_button.configure(state="normal")
            self.cancel_button.configure(state="disabled")
            self.progress.configure(value=100 if kind == "done" else 0)
            if kind == "done":
                self.result, self.count, self.lost = data
                self.preview_button.configure(state="normal")
                self.result_button.configure(state="normal")
                self.status.set(self.summary())
            else:
                self.status.set(data)
            return

    def summary(self):
        return f"Saved {self.result.name} and CSV. {len(self.lost):,} of {self.count:,} frames lost."

    def request_cancel(self):
        self.cancel.set()
        self.cancel_button.configure(state="disabled")
        self.status.set("Cancelling…")

    def play_preview(self):
        if self.player is not None:
            live = self.live_look is not None
            self.stop_preview()
            if not live:
                self.status.set(self.summary())
                return
        self.player = cv2.VideoCapture(str(self.result))
        if not self.player.isOpened():
            self.stop_preview()
            self.status.set("Could not play the preview here. Try Open MP4.")
            return
        self.play_index = 0
        self.play_fps = self.player.get(cv2.CAP_PROP_FPS) or 30
        self.play_start = time.monotonic()
        self.preview_button.configure(text="Stop preview")
        self.play_frame()

    def play_frame(self):
        self.play_job = None
        ok, frame = self.player.read()
        live = self.live_look is not None
        if not ok or (live and self.play_index >= self.play_fps * 4):
            self.stop_preview()
            self.status.set("Preview finished. Click Export video when you're ready." if live else self.summary())
            return
        if live:
            frame = self.preview_size(frame)
            frame = paint_scene(frame, self.live_tracker.update(frame), self.live_look,
                                self.play_index, self.play_fps, self.live_tracker.crop_ids)
            self.status.set("Previewing the opening 4 seconds…")
        else:
            label = " · Track lost" if self.play_index in self.lost else ""
            self.status.set(f"Export · Frame {self.play_index + 1:,} of {self.count:,}{label}")
        self.show(frame, preview=True)
        self.play_index += 1
        delay = self.play_start + self.play_index / self.play_fps - time.monotonic()
        self.play_job = self.after(max(1, int(delay * 1000)), self.play_frame)

    def stop_preview(self):
        if self.play_job is not None:
            self.after_cancel(self.play_job)
            self.play_job = None
        if self.player is not None:
            self.player.release()
            self.player = None
            self.show(self.still if self.still is not None else self.first)
        self.live_look = self.live_tracker = None
        self.look_button.configure(text="Preview look")
        self.preview_button.configure(text="Watch export")

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
            self.destroy()


if __name__ == "__main__":
    app = TrackingApp()
    if len(sys.argv) == 2:
        app.update_idletasks()
        app.load(Path(sys.argv[1]))
    app.mainloop()
