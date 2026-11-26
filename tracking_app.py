"""Project Nexus desktop workflow for region tracking and effects."""

import math
import os
from pathlib import Path
from queue import Empty, Queue
import sys
from threading import Event, Thread
import time
import tkinter as tk
from tkinter import filedialog, ttk

import cv2
from tkinterdnd2 import DND_FILES, TkinterDnD

from tracking_effect import Cancelled, TRACKED_DITHER, TRACKING_BOX, export_track


BG = "#111827"
TEXT = "#f3f6fd"
MUTED = "#c0cbde"
ACCENT = "#78edbe"


class TrackingApp(TkinterDnD.Tk):
    def __init__(self):
        super().__init__()
        self.title("Project Nexus — Tracking")
        self.geometry("940x720")
        self.minsize(740, 575)
        self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.source = self.first = self.image = self.bounds = None
        self.anchor = self.box = self.selection = None
        self.result = self.player = self.play_job = None
        self.busy = False
        self.cancel = Event()
        self.events = Queue()
        self.mode = tk.StringVar(value=TRACKING_BOX)
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
        self.label(top, text="Video tracking", size=11, color=MUTED).pack(side="left", padx=14)
        self.open_button = self.button(top, "Open video…", self.browse)
        self.open_button.pack(side="right")

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

        bottom = tk.Frame(self, bg=BG)
        bottom.grid(row=2, column=0, sticky="ew", padx=22, pady=(10, 14))
        self.label(bottom, textvariable=self.filename, color=MUTED, wraplength=680).pack(anchor="w")
        bar = tk.Frame(bottom, bg=BG)
        bar.pack(fill="x", pady=(8, 7))
        self.label(bar, text="Effect", color=MUTED).pack(side="left", padx=(0, 8))
        self.effects = ttk.Combobox(bar, textvariable=self.mode, state="readonly",
                                    values=(TRACKING_BOX, TRACKED_DITHER), width=21)
        self.effects.pack(side="left")
        self.preview_button = self.button(bar, "Play preview", self.play_preview, "disabled")
        self.preview_button.pack(side="left", padx=(12, 6))
        self.result_button = self.button(bar, "Open MP4", self.open_result, "disabled")
        self.result_button.pack(side="left")
        self.cancel_button = self.button(bar, "Cancel", self.request_cancel, "disabled")
        self.cancel_button.pack(side="right", padx=(8, 0))
        self.track_button = ttk.Button(bar, text="Track & export", command=self.start,
                                       style="Track.TButton", state="disabled")
        self.track_button.pack(side="right")
        self.progress = ttk.Progressbar(bottom, mode="determinate")
        self.progress.pack(fill="x")
        self.label(bottom, textvariable=self.status, color=ACCENT, wraplength=680).pack(anchor="w", pady=(5, 0))

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
        self.status.set("Drag a rectangle around the object you want to follow.")
        self.track_button.configure(state="disabled")
        self.preview_button.configure(state="disabled")
        self.result_button.configure(state="disabled")
        self.progress.configure(value=0)
        self.show(frame)

    def resize(self, _event):
        if self.player is None:
            self.show(self.first)

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
            if self.box:
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
        if self.first is None or self.busy or self.player is not None:
            return
        point = self.point(event)
        if point != (event.x, event.y):
            return
        self.anchor = point
        if self.selection:
            self.canvas.delete(self.selection)
        self.selection = self.canvas.create_rectangle(*point, *point, outline=ACCENT, width=2)

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
            self.status.set("Drag a larger rectangle around the target.")
        else:
            self.box = (x0, y0, x1 - x0, y1 - y0)
            self.track_button.configure(state="normal")
            self.status.set("Target selected. Choose an effect, then click Track & export.")
        self.show(self.first)

    def start(self):
        if self.busy or self.box is None:
            return
        self.stop_preview()
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
        self.effects.configure(state="disabled")
        self.track_button.configure(state="disabled")
        self.preview_button.configure(state="disabled")
        self.result_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.progress.configure(value=0)
        self.status.set("Tracking and exporting…")
        Thread(target=self.render, args=(self.source, self.box, Path(path), self.mode.get())).start()
        self.after(70, self.poll)

    def render(self, source, box, destination, mode):
        def progress(count, total):
            self.events.put(("progress", (count, total)))

        try:
            count, lost = export_track(source, box, destination, mode, self.cancel, progress)
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
            self.effects.configure(state="readonly")
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
            self.stop_preview()
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
        if not ok:
            self.stop_preview()
            self.status.set(self.summary())
            return
        self.show(frame, preview=True)
        label = " · Target lost" if self.play_index in self.lost else ""
        self.status.set(f"Preview · Frame {self.play_index + 1:,} of {self.count:,}{label}")
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
            self.show(self.first)
        self.preview_button.configure(text="Play preview")

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
