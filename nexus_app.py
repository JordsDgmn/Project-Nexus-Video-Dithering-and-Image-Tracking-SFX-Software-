"""Project Nexus desktop video filter."""

import os
from pathlib import Path
from queue import Empty, Queue
import sys
from threading import Thread
import tkinter as tk
from tkinter import filedialog, ttk

from tkinterdnd2 import DND_FILES, TkinterDnD

from dither import apply_filter


class VideoFilter(TkinterDnD.Tk):
    def __init__(self):
        super().__init__()
        self.title("Project Nexus")
        self.geometry("660x480")
        self.minsize(600, 460)
        self.configure(bg="#101522")
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.source = None
        self.destination = None
        self.export = None
        self.busy = False
        self.results = Queue()

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Nexus.TButton", padding=(14, 9), font=("Segoe UI", 10))
        style.configure(
            "Export.TButton", padding=(16, 9), font=("Segoe UI", 10, "bold"),
            background="#66e3bf", foreground="#102a25",
        )
        style.map("Export.TButton", background=[("disabled", "#bac5c4"), ("active", "#94f3d7")])
        body = tk.Frame(self, bg="#101522", padx=32, pady=25)
        body.pack(fill="both", expand=True)
        self.label(body, "Project Nexus", 24, "#f1f5ff", bold=True).pack(anchor="w")
        self.label(body, "Black-and-white dither", 12, "#aebbd0").pack(anchor="w", pady=(3, 15))

        drop = tk.Frame(body, bg="#202b40", highlightbackground="#536b91", highlightthickness=1)
        drop.pack(fill="x")
        heading = self.label(drop, "Drop a video here", 15, "#f1f5ff", bold=True)
        heading.pack(pady=(16, 8))
        browse = ttk.Button(drop, text="Browse videos", style="Nexus.TButton", command=self.browse)
        browse.pack(pady=(0, 16))
        for widget in (drop, heading, browse):
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self.drop_video)
        self.browse_button = browse

        self.details = self.label(body, "Choose one video to get started.", 10, "#d9e3f5")
        self.details.pack(fill="x", pady=(13, 0))
        self.label(body, "Exports a silent MP4. Your video stays on this computer.", 10, "#aebbd0").pack(anchor="w", pady=(4, 10))
        actions = tk.Frame(body, bg="#101522")
        actions.pack(fill="x")
        self.save_button = ttk.Button(actions, text="Save as…", style="Nexus.TButton", command=self.save_as, state="disabled")
        self.save_button.pack(side="left")
        self.open_button = ttk.Button(actions, text="Open result", style="Nexus.TButton", command=self.open_result, state="disabled")
        self.open_button.pack(side="left", padx=8)
        self.export_button = ttk.Button(actions, text="Export video", style="Export.TButton", command=self.start_export, state="disabled")
        self.export_button.pack(side="right")

        self.progress = ttk.Progressbar(body, mode="indeterminate")
        self.progress.pack(fill="x", pady=(13, 4))
        self.status = self.label(body, "", 10, "#bdebdc")
        self.status.pack(fill="x")

    def label(self, parent, text, size, color, bold=False):
        return tk.Label(
            parent, text=text, font=("Segoe UI", size, "bold" if bold else "normal"),
            fg=color, bg=parent["bg"], anchor="w", justify="left", wraplength=525,
        )

    def browse(self):
        path = filedialog.askopenfilename(
            parent=self, title="Choose a video",
            filetypes=[("Videos", "*.mp4 *.mov *.avi *.mkv *.webm *.m4v *.wmv"), ("All files", "*.*")],
        )
        if path:
            self.select(Path(path))

    def drop_video(self, event):
        if not self.busy:
            paths = self.tk.splitlist(event.data)
            if len(paths) == 1:
                self.select(Path(paths[0]))
            else:
                self.status.configure(text="Drop one video at a time.")
        return event.action

    def select(self, path):
        if not path.is_file():
            self.status.configure(text="Choose a video file.")
            return
        self.source = path
        self.export = None
        self.set_output(self.next_destination())
        self.save_button.configure(state="normal")
        self.export_button.configure(state="normal")
        self.open_button.configure(state="disabled")
        self.status.configure(text="Ready to export.")

    def next_destination(self):
        stem = f"{self.source.stem}-dithered"
        candidate = self.source.with_name(f"{stem}.mp4")
        index = 2
        while candidate.exists() or candidate.is_symlink():
            candidate = self.source.with_name(f"{stem}-{index}.mp4")
            index += 1
        return candidate

    def set_output(self, path):
        self.destination = path
        self.details.configure(text=f"Video: {self.source.name}\nOutput: {path}")

    def save_as(self):
        path = filedialog.asksaveasfilename(
            parent=self, title="Save exported video", initialdir=self.destination.parent,
            initialfile=self.destination.name, defaultextension=".mp4",
            filetypes=[("MP4 video", "*.mp4")],
        )
        if path:
            if Path(path).exists():
                self.status.configure(text="That file already exists. Choose a new name.")
                return
            self.set_output(Path(path))
            self.status.configure(text="Ready to export.")

    def start_export(self):
        self.busy = True
        for button in (self.browse_button, self.save_button, self.export_button, self.open_button):
            button.configure(state="disabled")
        self.status.configure(text="Exporting video…")
        self.progress.start()
        Thread(target=self.render, args=(self.source, self.destination)).start()
        self.after(80, self.poll)

    def render(self, source, destination):
        try:
            count = apply_filter(source, destination)
        except Exception as error:
            self.results.put((None, str(error)))
        else:
            self.results.put((destination, f"Export complete · {count} frames"))

    def poll(self):
        try:
            path, message = self.results.get_nowait()
        except Empty:
            self.after(80, self.poll)
            return
        self.busy = False
        self.progress.stop()
        self.status.configure(text=message)
        self.browse_button.configure(state="normal")
        self.save_button.configure(state="normal")
        self.export_button.configure(state="normal")
        if path is not None:
            self.export = path
            self.open_button.configure(state="normal")
            self.set_output(self.next_destination())

    def open_result(self):
        try:
            os.startfile(self.export)
        except OSError as error:
            self.status.configure(text=f"Could not open the result: {error}")

    def close(self):
        if self.busy:
            self.status.configure(text="Wait for the export to finish before closing.")
        else:
            self.destroy()


if __name__ == "__main__":
    app = VideoFilter()
    if len(sys.argv) == 2:
        app.select(Path(sys.argv[1]))
    app.mainloop()

