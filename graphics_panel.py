"""Live controls for the automatic tracking looks."""

from dataclasses import asdict
import tkinter as tk
from tkinter import colorchooser, ttk

from graphics_settings import (
    ASCII, ASCII_BACKDROPS, ASCII_COLORS, DETECTORS, LINES, MARKS, SHAPES, TEXT_SOURCES,
    TEXT_SPLITS, TEXT_STYLES, Graphics,
)


class GraphicsPanel(tk.Toplevel):
    def __init__(self, app, look):
        super().__init__(app)
        self.app = app
        self.title("Nexus · Live tracking controls")
        self.geometry("650x575")
        self.minsize(590, 540)
        self.protocol("WM_DELETE_WINDOW", self.finish)
        self.pending = None
        self.syncing = False
        self.last_field = ""
        self.valid = True
        self.variables = {}
        for key, value in asdict(look.graphics).items():
            if key != "custom_text":
                self.add_variable(key, value)
        for key in ("opacity", "min_boxes", "max_boxes", "tracking_speed", "links", "labels", "trails", "tint"):
            self.add_variable(key, getattr(look, key))

        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=12, pady=(12, 8))
        for name, builder in (("Detection", self.detection), ("Marks & links", self.marks),
                              ("Text", self.text), ("ASCII", self.ascii_page)):
            frame = ttk.Frame(self.tabs, padding=10)
            frame.columnconfigure(1, weight=1)
            self.tabs.add(frame, text=name)
            builder(frame)
        self.words.insert("1.0", look.graphics.custom_text)
        self.words.edit_modified(False)
        self.words.bind("<<Modified>>", self.text_changed)
        if look.mode == ASCII:
            self.tabs.select(3)
        bottom = ttk.Frame(self, padding=(10, 4))
        bottom.pack(fill="x", padx=12, pady=(0, 9))
        self.message = tk.StringVar(value="Changes update the preview while it plays.")
        ttk.Label(bottom, textvariable=self.message, wraplength=480).pack(side="left", fill="x", expand=True)
        ttk.Button(bottom, text="Close", command=self.finish).pack(side="right")

    def add_variable(self, key, value):
        cls = tk.BooleanVar if type(value) is bool else tk.IntVar if type(value) is int else tk.StringVar
        variable = cls(self, value)
        variable.trace_add("write", lambda *_: self.change(key))
        self.variables[key] = variable

    def detection(self, tab):
        self.select(tab, 0, "Detector", "detector", DETECTORS)
        self.slider(tab, 1, "Threshold", "threshold", 1, 254)
        self.slider(tab, 2, "Detect every N frames", "interval", 1, 120)
        self.slider(tab, 3, "Tracking response", "tracking_speed", 0, 100)
        self.slider(tab, 4, "Min boxes (features)", "min_boxes", 0, 100)
        self.slider(tab, 5, "Max boxes", "max_boxes", 1, 100)
        self.slider(tab, 6, "Spacing (% of short edge)", "spacing", 0, 30)
        self.spin(tab, 7, "Min blob area (× 0.01%)", "min_size", 1, 3000)
        self.spin(tab, 8, "Max blob area (× 0.01%)", "max_size", 1, 9500)
        self.note(tab, 9, "Features use a relative strength threshold. Bright and Dark use luma. Motion uses change between frames. Area limits apply to blobs.")

    def marks(self, tab):
        self.select(tab, 0, "Show", "marks", MARKS)
        self.select(tab, 1, "Box style", "shape", SHAPES)
        self.slider(tab, 2, "Intensity %", "opacity", 0, 100)
        self.slider(tab, 3, "Box size %", "box_scale", 20, 300)
        self.slider(tab, 4, "Stroke weight", "stroke", 1, 6)
        self.select(tab, 5, "Line style", "line_style", LINES)
        self.slider(tab, 6, "Links per target", "link_density", 0, 6)
        self.slider(tab, 7, "Link reach %", "link_range", 0, 100)
        self.slider(tab, 8, "Vector length %", "vector_gain", 0, 350)
        self.switches(tab, 9, (("Draw links", "links"), ("Vector trails", "trails")))
        group = ttk.Frame(tab)
        group.grid(row=10, column=1, columnspan=2, sticky="w")
        self.title_row(tab, 10, "Graphic color")
        ttk.Entry(group, textvariable=self.variables["tint"], width=10).pack(side="left")
        ttk.Button(group, text="Choose…", command=self.color).pack(side="left", padx=(6, 0))
        self.note(tab, 11, "Link reach is a fraction of the frame diagonal. Vector length and trails apply in Motion vectors.")

    def text(self, tab):
        self.select(tab, 0, "Label source", "label_source", TEXT_SOURCES)
        self.select(tab, 1, "Text style", "label_style", TEXT_STYLES)
        self.select(tab, 2, "Split pasted text by", "text_split", TEXT_SPLITS)
        self.slider(tab, 3, "Label size %", "label_size", 40, 250)
        self.slider(tab, 4, "Label density %", "label_density", 0, 100)
        self.switches(tab, 5, (("Show labels", "labels"),))
        text_row = ttk.Frame(tab)
        text_row.grid(row=6, column=0, columnspan=3, pady=(8, 2), sticky="nsew")
        tab.rowconfigure(6, weight=1)
        self.words = tk.Text(text_row, height=7, wrap="word", undo=True,
                             font=("Segoe UI", 10), padx=8, pady=6)
        self.words.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(text_row, orient="vertical", command=self.words.yview)
        scroll.pack(side="right", fill="y")
        self.words.configure(yscrollcommand=scroll.set)
        self.note(tab, 7, "Paste lyrics or any text here. Custom labels stay assigned to the same track ID.")

    def ascii_page(self, tab):
        self.slider(tab, 0, "Glyph size", "ascii_size", 5, 40)
        self.select(tab, 1, "Glyph color", "ascii_color", ASCII_COLORS)
        self.select(tab, 2, "Backdrop", "ascii_backdrop", ASCII_BACKDROPS)
        self.entry(tab, 3, "Glyph ramp", "ascii_ramp")
        self.switches(tab, 4, (("Ordered dithering", "ascii_dither"),))
        self.note(tab, 5, "ASCII texture uses this ramp from light to dense. A leading space leaves the darkest cells empty.")

    def color(self):
        try:
            _, color = colorchooser.askcolor(self.variables["tint"].get(), parent=self)
        except tk.TclError:
            _, color = colorchooser.askcolor(parent=self)
        if color:
            self.variables["tint"].set(color)

    def title_row(self, tab, row, text):
        ttk.Label(tab, text=text, width=26).grid(row=row, column=0, sticky="w", pady=2)

    def select(self, tab, row, caption, key, values):
        self.title_row(tab, row, caption)
        ttk.Combobox(tab, state="readonly", textvariable=self.variables[key],
                     values=values).grid(row=row, column=1, columnspan=2, sticky="ew", pady=2)

    def slider(self, tab, row, caption, key, minimum, maximum):
        self.title_row(tab, row, caption)
        tk.Scale(tab, from_=minimum, to=maximum, resolution=1, orient="horizontal", showvalue=False,
                 variable=self.variables[key], width=12, sliderlength=14, highlightthickness=0,
                 borderwidth=0).grid(row=row, column=1, sticky="ew")
        self.number(tab, row, key, minimum, maximum, 2)

    def spin(self, tab, row, caption, key, minimum, maximum):
        self.title_row(tab, row, caption)
        self.number(tab, row, key, minimum, maximum, 1)

    def number(self, tab, row, key, minimum, maximum, column):
        ttk.Spinbox(tab, from_=minimum, to=maximum, textvariable=self.variables[key], width=6).grid(
            row=row, column=column, sticky="w", padx=(8, 0), pady=2)

    def entry(self, tab, row, caption, key):
        self.title_row(tab, row, caption)
        ttk.Entry(tab, textvariable=self.variables[key]).grid(row=row, column=1, columnspan=2, sticky="ew", pady=2)

    def switches(self, tab, row, fields):
        group = ttk.Frame(tab)
        group.grid(row=row, column=1, columnspan=2, sticky="w", pady=4)
        for caption, key in fields:
            ttk.Checkbutton(group, text=caption, variable=self.variables[key]).pack(side="left", padx=(0, 10))

    @staticmethod
    def note(tab, row, text):
        ttk.Label(tab, text=text, wraplength=510).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(7, 0))

    def text_changed(self, _event):
        if self.words.edit_modified():
            self.words.edit_modified(False)
            self.change("custom_text")

    def change(self, field):
        if self.syncing:
            return
        if field == "detector":
            value = self.variables["detector"].get()
            defaults = {"Features": 32, "Motion blobs": 13, "Bright blobs": 160, "Dark blobs": 64}
            if value in defaults:
                self.syncing = True
                self.variables["threshold"].set(defaults[value])
                self.syncing = False
        self.last_field = field
        if self.pending is None:
            self.pending = self.after(80, self.apply)

    def apply(self):
        self.pending = None
        try:
            values = {key: ctl.get() for key, ctl in self.variables.items()}
            if self.last_field == "max_boxes" and values["min_boxes"] > values["max_boxes"]:
                values["min_boxes"] = values["max_boxes"]
                self.syncing = True
                self.variables["min_boxes"].set(values["min_boxes"])
                self.syncing = False
            words = self.words.get("1.0", "end-1c")
            if self.last_field == "custom_text" and words.strip() and values["label_source"] != "Custom":
                values["label_source"] = "Custom"
                self.syncing = True
                self.variables["label_source"].set("Custom")
                self.syncing = False
            keys = asdict(Graphics())
            config = Graphics(**{key: values.pop(key) for key in keys if key != "custom_text"},
                              custom_text=words).validate()
            self.app.apply_graphics(config, values)
        except (tk.TclError, ValueError) as error:
            self.message.set(str(error))
            self.valid = False
        else:
            self.message.set("Preview updated. Save a preset to reuse these settings.")
            self.valid = True
        return self.valid

    def synchronize(self, look):
        self.valid = True
        if self.pending is not None:
            self.after_cancel(self.pending)
            self.pending = None
        self.syncing = True
        for key, value in asdict(look.graphics).items():
            if key != "custom_text":
                self.variables[key].set(value)
        for key in ("opacity", "min_boxes", "max_boxes", "tracking_speed", "links", "labels", "trails", "tint"):
            self.variables[key].set(getattr(look, key))
        self.words.delete("1.0", "end")
        self.words.insert("1.0", look.graphics.custom_text)
        self.words.edit_modified(False)
        self.syncing = False

    def flush(self):
        if self.pending is not None or self.words.get("1.0", "end-1c") != self.app.graphics.custom_text:
            if self.pending is not None:
                self.after_cancel(self.pending)
            if self.words.get("1.0", "end-1c") != self.app.graphics.custom_text:
                self.last_field = "custom_text"
            return self.apply()
        return self.valid

    def finish(self):
        if self.flush():
            self.close()

    def close(self):
        if self.pending is not None:
            self.after_cancel(self.pending)
        self.app.graphics_panel = None
        self.destroy()
