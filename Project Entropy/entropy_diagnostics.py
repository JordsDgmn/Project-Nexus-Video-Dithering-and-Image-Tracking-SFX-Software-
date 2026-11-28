"""Local issue tracking and a diagnostics window for Entropy."""

from collections import deque
from datetime import datetime
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk


def project_directory():
    if getattr(sys, "frozen", False):
        parent = Path(sys.executable).resolve().parent
        return parent.parent if parent.name.lower() == "dist" else parent
    return Path(__file__).resolve().parent


class SessionLog:
    def __init__(self):
        self.active = {}
        self.history = deque(maxlen=180)
        self.revision = 0
        self.handler = None
        self.path = None
        try:
            folder = project_directory() / ".entropy-data" / "logs"
            folder.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            path = folder / f"entropy-{stamp}-{os.getpid()}.log"
            self.handler = RotatingFileHandler(path, maxBytes=524288, backupCount=2, encoding="utf-8")
            self.handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            self.path = path
        except OSError as error:
            self.issue("Log storage", "The session log could only be kept in memory.", str(error))
        self.record("Session started")

    def record(self, text, detail=None, level=logging.INFO):
        record = text if not detail else text + "\n" + detail.rstrip()
        now = datetime.now().strftime("%H:%M:%S")
        self.history.append(f"{now} {logging.getLevelName(level)} {record}")
        self.revision += 1
        if self.handler is not None:
            entry = logging.LogRecord("entropy", level, "", 0, record, (), None)
            self.handler.handle(entry)

    def issue(self, area, message, detail=None):
        if self.active.get(area) == message:
            return
        self.active[area] = message
        self.record(f"{area}: {message}", detail, logging.ERROR)

    def clear(self, area):
        if area in self.active:
            del self.active[area]
            self.record(f"{area}: recovered")

    def close(self):
        if self.handler is not None:
            self.record("Session ended")
            self.handler.close()
            self.handler = None


class DiagnosticsWindow(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.session = app.diagnostics
        self.title("Entropy · Diagnostics")
        self.geometry("720x475")
        self.minsize(560, 365)
        self.transient(app)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.current = tk.StringVar(self)
        self.last_revision = -1
        self.timer = None

        body = ttk.Frame(self, padding=13)
        body.pack(fill="both", expand=True)
        ttk.Label(body, textvariable=self.current, wraplength=540, justify="left").pack(
            fill="x", pady=(0, 9), anchor="w")
        panel = ttk.Frame(body)
        panel.pack(fill="both", expand=True)
        self.history = tk.Text(panel, wrap="word", font=("Consolas", 10), padx=8, pady=7,
                               bg="#12121b", fg="#f0edf9", selectbackground="#534071",
                               state="disabled")
        scrollbar = ttk.Scrollbar(panel, orient="vertical", command=self.history.yview)
        self.history.configure(yscrollcommand=scrollbar.set)
        self.history.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        row = ttk.Frame(body)
        row.pack(fill="x", pady=(10, 0))
        ttk.Button(row, text="Restart preview", command=app.restart_preview).pack(side="left")
        ttk.Button(row, text="Restart app", command=app.restart_app).pack(side="left", padx=6)
        ttk.Button(row, text="Copy log", command=self.copy).pack(side="right")
        ttk.Button(row, text="Open log folder", command=self.open_log,
                   state="normal" if self.session.path else "disabled").pack(side="right", padx=6)
        self.refresh()

    def refresh(self):
        session = self.session
        if self.last_revision != session.revision:
            self.last_revision = session.revision
            self.current.set("\n".join(f"{area} — {message}" for area, message in session.active.items())
                             or "No active issues. Earlier events are kept below.")
            first, last = self.history.yview()
            self.history.configure(state="normal")
            self.history.delete("1.0", "end")
            self.history.insert("1.0", "\n\n".join(session.history))
            self.history.configure(state="disabled")
            if last > .98:
                self.history.see("end")
            else:
                self.history.yview_moveto(first)
        self.timer = self.after(500, self.refresh)

    def copy(self):
        self.clipboard_clear()
        self.clipboard_append("\n\n".join(self.session.history))

    def open_log(self):
        try:
            os.startfile(self.session.path.parent)
        except OSError as error:
            self.app.issue("Diagnostics", "Could not open the log folder.", str(error))
        else:
            self.app.clear_issue("Diagnostics")

    def close(self):
        if self.timer is not None:
            self.after_cancel(self.timer)
        self.app.diagnostics_window = None
        self.destroy()
