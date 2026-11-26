"""Grouped controls for Nexus Soft Dots."""

from dataclasses import asdict
import tkinter as tk
from tkinter import colorchooser, ttk

from dots_effect import (
    BACKDROPS, BLENDS, BLURS, FILTERS, GRADES, GRADIENTS, DotsSettings,
)


class DotsPanel(tk.Toplevel):
    def __init__(self, app, settings):
        super().__init__(app)
        self.app = app
        self.title("Nexus · Soft Dots")
        self.geometry("625x575")
        self.minsize(560, 535)
        self.configure(bg="#111827")
        self.transient(app)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.values = {}
        for key, value in asdict(settings).items():
            kind = tk.BooleanVar if type(value) is bool else tk.IntVar if type(value) is int else tk.StringVar
            self.values[key] = kind(self, value)
        self.message = tk.StringVar(value="Apply updates the current preview frame.")
        book = ttk.Notebook(self)
        book.pack(fill="both", expand=True, padx=15, pady=(15, 7))
        for name, populate in (("Dots", self.dots), ("Backdrop", self.backdrop),
                               ("Tone & blur", self.tone), ("Color", self.color)):
            tab = ttk.Frame(book, padding=10)
            tab.columnconfigure(1, weight=1)
            book.add(tab, text=name)
            populate(tab)
        ttk.Label(self, textvariable=self.message, wraplength=555, background="#111827",
                  foreground="#c0cbde", padding=(15, 0)).pack(fill="x", pady=(3, 5))
        buttons = ttk.Frame(self, padding=(10, 6))
        buttons.pack(fill="x", padx=15, pady=(0, 12))
        ttk.Button(buttons, text="Reset to reference", command=self.reset).pack(side="left")
        ttk.Button(buttons, text="Close", command=self.close).pack(side="right")
        ttk.Button(buttons, text="Apply to preview", command=self.apply).pack(side="right", padx=8)

    def dots(self, tab):
        self.numeric(tab, 0, "size", "Dot size", 3, 80)
        self.choose(tab, 1, "dot_blend", "Blend mode", BLENDS)
        self.numeric(tab, 2, "dot_opacity", "Dot opacity %", 0, 100)
        self.numeric(tab, 3, "coverage", "Coverage %", 0, 100)
        self.switch(tab, 4, "invert_mapping", "Invert brightness mapping")
        self.switch(tab, 5, "show_grid", "Show the underlying dot grid")

    def backdrop(self, tab):
        self.choose(tab, 0, "backdrop", "Mode", BACKDROPS)
        self.numeric(tab, 1, "softness", "Softness (px)", 0, 60)
        self.numeric(tab, 2, "backdrop_opacity", "Opacity %", 0, 100)
        self.pick_color(tab, 3, "backdrop_color", "Solid color")
        ttk.Label(tab, text="Dots only uses a black fill in MP4.", wraplength=460).grid(
            row=4, column=0, columnspan=3, sticky="w", pady=(14, 0))

    def tone(self, tab):
        self.numeric(tab, 0, "hide_shadows", "Hide shadows %", 0, 100)
        self.numeric(tab, 1, "brightness", "Brightness", -100, 100)
        self.numeric(tab, 2, "contrast", "Contrast", -100, 100)
        self.choose(tab, 3, "blur", "Final blur type", BLURS)
        self.numeric(tab, 4, "blur_amount", "Blur amount", 0, 60)
        self.numeric(tab, 5, "blur_angle", "Motion angle", -180, 180)

    def color(self, tab):
        self.choose(tab, 0, "grade", "Color preset", GRADES)
        self.choose(tab, 1, "photo_filter", "Photo filter", tuple(FILTERS))
        self.numeric(tab, 2, "filter_strength", "Filter strength %", 0, 100)
        self.pick_color(tab, 3, "tint", "Tint")
        self.numeric(tab, 4, "tint_opacity", "Tint opacity %", 0, 100)
        self.choose(tab, 5, "tint_blend", "Tint blend", BLENDS)
        self.numeric(tab, 6, "saturation", "Saturation %", 0, 200)
        self.numeric(tab, 7, "vibrance", "Vibrance", -100, 100)
        self.numeric(tab, 8, "hue", "Hue", -180, 180)
        self.choose(tab, 9, "gradient", "Gradient map", tuple(GRADIENTS))
        self.numeric(tab, 10, "grayscale", "Grayscale %", 0, 100)
        self.switch(tab, 11, "invert_image", "Invert finished image")

    @staticmethod
    def label(tab, row, title):
        ttk.Label(tab, text=title, width=20).grid(row=row, column=0, sticky="w", pady=2)

    def choose(self, tab, row, key, title, values):
        self.label(tab, row, title)
        menu = ttk.Combobox(tab, state="readonly", values=values,
                            textvariable=self.values[key], width=22)
        menu.grid(row=row, column=1, sticky="ew", pady=2, columnspan=2)

    def numeric(self, tab, row, key, title, low, high):
        self.label(tab, row, title)
        bar = tk.Scale(tab, from_=low, to=high, resolution=1, orient="horizontal",
                       variable=self.values[key], showvalue=False, highlightthickness=0,
                       borderwidth=0, sliderlength=13, width=13)
        bar.grid(row=row, column=1, sticky="ew", pady=2)
        field = ttk.Spinbox(tab, from_=low, to=high, textvariable=self.values[key], width=6)
        field.grid(row=row, column=2, sticky="e", padx=(10, 0))

    def switch(self, tab, row, key, title):
        ttk.Checkbutton(tab, text=title, variable=self.values[key]).grid(
            row=row, column=1, columnspan=2, sticky="w", pady=4)

    def pick_color(self, tab, row, key, title):
        self.label(tab, row, title)
        field = ttk.Entry(tab, textvariable=self.values[key])
        field.grid(row=row, column=1, sticky="ew", pady=2)
        ttk.Button(tab, text="Choose…", command=lambda: self.choose_color(key)).grid(
            row=row, column=2, padx=(10, 0))

    def choose_color(self, key):
        try:
            _, color = colorchooser.askcolor(self.values[key].get(), parent=self, title="Choose color")
        except tk.TclError:
            _, color = colorchooser.askcolor(parent=self, title="Choose color")
        if color:
            self.values[key].set(color)

    def set_settings(self, settings):
        for key, value in asdict(settings).items():
            self.values[key].set(value)

    def reset(self):
        self.set_settings(DotsSettings())
        self.apply()

    def apply(self):
        try:
            settings = DotsSettings(**{key: value.get() for key, value in self.values.items()}).validate()
            self.app.apply_dots(settings)
        except (tk.TclError, ValueError) as error:
            self.message.set(str(error))
        else:
            self.message.set("Applied. Save a preset to reuse these settings.")

    def close(self):
        self.app.dots_panel = None
        self.destroy()
