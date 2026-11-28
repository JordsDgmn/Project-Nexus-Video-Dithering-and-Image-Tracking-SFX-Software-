"""Entropy's texture controls and local asset libraries."""

from dataclasses import asdict
import sqlite3
import tkinter as tk
from tkinter import colorchooser, simpledialog, ttk
import traceback

from entropy_engine import PALETTES, validate_colors
from entropy_texture import PRINT_STYLES, Texture


PANEL = "#191925"
TEXT = "#f0edf9"
MUTED = "#afabbd"
ACCENT = "#c7acff"

TEXTURE_RECIPES = {
    "Film wear": Texture(grain=34, grain_size=2, vignette=38, tatter=57, edge_width=5, roughness=82),
    "Ink print": Texture(grain=19, halftone=66, cell_size=11, angle=33, posterize=38, levels=7),
    "Broken glass": Texture(distort=37, distort_scale=53, ripple=25, ripple_count=8, chromatic=48),
}


class ToolWindow(tk.Toplevel):
    def __init__(self, app, title, size):
        super().__init__(app)
        self.app = app
        self.title(f"Entropy · {title}")
        self.geometry(size)
        self.transient(app)
        self.configure(bg=PANEL)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.feedback = tk.StringVar(self)
        self.body = tk.Frame(self, bg=PANEL, padx=13, pady=12)
        self.body.pack(fill="both", expand=True)

    def label(self, parent, text="", variable=None, **kwargs):
        return tk.Label(parent, text=text, textvariable=variable, bg=PANEL, fg=TEXT,
                        anchor="w", justify="left", font=("Segoe UI", 10), **kwargs)

    def feedback_label(self):
        self.label(self.body, variable=self.feedback, wraplength=544).pack(fill="x", pady=(8, 0))

    def success(self, message):
        self.app.clear_issue("Library")
        self.feedback.set(message)

    def attempt(self, operation, *args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except (ValueError, OSError, sqlite3.Error) as error:
            self.app.issue("Library", str(error), traceback.format_exc())
            self.feedback.set(str(error))
            return None


class TexturesWindow(ToolWindow):
    def __init__(self, app):
        super().__init__(app, "Textures", "590x465")
        self.minsize(525, 420)
        self.pending = None
        self.syncing = False
        self.enabled = tk.BooleanVar(self, app.look.textures.enabled)
        self.values = {}
        for key, value in asdict(app.look.textures).items():
            if key == 'enabled':
                continue
            kind = tk.BooleanVar if type(value) is bool else tk.IntVar if type(value) is int else tk.StringVar
            self.values[key] = kind(self, value)
            self.values[key].trace_add("write", self.schedule)
        self.enabled.trace_add("write", self.schedule)
        top = tk.Frame(self.body, bg=PANEL)
        top.pack(fill="x", pady=(0, 8))
        ttk.Checkbutton(top, text="Enable textures", variable=self.enabled).pack(side="left")
        ttk.Button(top, text="Reset stack", command=self.reset).pack(side="right")
        self.recipe = ttk.Combobox(top, state="readonly", width=15, values=tuple(TEXTURE_RECIPES))
        self.recipe.set("Texture recipe…")
        self.recipe.pack(side="right", padx=(0, 7))
        self.recipe.bind("<<ComboboxSelected>>", self.use_recipe)
        self.book = ttk.Notebook(self.body)
        self.book.pack(fill="both", expand=True)
        self.pages = []
        for name, content in (
                ("Grain & print", self.print_page), ("Distortion", self.warp_page), ("Edges & tone", self.edge_page)):
            page = tk.Frame(self.book, bg=PANEL, padx=10, pady=8)
            self.book.add(page, text=name)
            self.pages.append(page)
            content(page)
        self.feedback.set("Changes update the preview while it plays or pauses.")
        self.feedback_label()

    def scale(self, parent, title, key, low, high):
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill="x", pady=2)
        self.label(row, title, width=19).pack(side="left")
        self.label(row, variable=self.values[key], width=4).pack(side="right")
        bar = tk.Scale(row, from_=low, to=high, resolution=1, orient="horizontal",
                       variable=self.values[key], showvalue=False, bg=PANEL, fg=TEXT,
                       activebackground=ACCENT, troughcolor="#40354f", highlightthickness=0,
                       borderwidth=0, sliderlength=14, width=14)
        bar.pack(side="left", fill="x", expand=True)

    def print_page(self, page):
        self.scale(page, "Film grain", "grain", 0, 100)
        self.scale(page, "Grain size", "grain_size", 1, 12)
        ttk.Checkbutton(page, text="Color grain", variable=self.values["colored_grain"]).pack(anchor="w", pady=4)
        self.scale(page, "Halftone", "halftone", 0, 100)
        self.scale(page, "Print cell size", "cell_size", 3, 36)
        self.scale(page, "Print angle", "angle", 0, 180)
        row = tk.Frame(page, bg=PANEL)
        row.pack(fill="x", pady=4)
        self.label(row, "Pattern").pack(side="left")
        ttk.Combobox(row, state="readonly", textvariable=self.values["print_style"],
                     values=PRINT_STYLES).pack(side="right")

    def warp_page(self, page):
        for args in (("Distortion", "distort", 0, 100), ("Distortion scale", "distort_scale", 1, 100),
                     ("Ripple", "ripple", 0, 100), ("Ripple rings", "ripple_count", 1, 24),
                     ("Color separation", "chromatic", 0, 100)):
            self.scale(page, *args)

    def edge_page(self, page):
        for args in (("Tattered edges", "tatter", 0, 100), ("Edge width", "edge_width", 2, 30),
                     ("Edge roughness", "roughness", 0, 100), ("Vignette", "vignette", 0, 100),
                     ("Posterize", "posterize", 0, 100), ("Tone levels", "levels", 2, 32)):
            self.scale(page, *args)
        self.label(page, "Tattered edges reveal the selected background color.").pack(anchor="w", pady=5)

    def schedule(self, *_):
        if not self.syncing and self.pending is None:
            self.pending = self.after(55, self.apply)

    def apply(self):
        self.pending = None
        config = Texture(**{key: value.get() for key, value in self.values.items()},
                         enabled=self.enabled.get()).validate()
        self.app.apply_textures(config)
        self.feedback.set("Preview and export use the enabled texture stack.")

    def sync(self, texture):
        if self.pending is not None:
            self.after_cancel(self.pending)
            self.pending = None
        self.syncing = True
        self.enabled.set(texture.enabled)
        for key, field in self.values.items():
            field.set(getattr(texture, key))
        self.syncing = False

    def use_recipe(self, _event=None):
        self.sync(TEXTURE_RECIPES[self.recipe.get()])
        self.apply()
        self.recipe.set("Texture recipe…")

    def reset(self):
        self.sync(Texture())
        self.apply()

    def flush(self):
        if self.pending is not None:
            self.after_cancel(self.pending)
            self.pending = None
            if not self.app.exiting:
                self.apply()

    def destroy(self):
        self.flush()
        super().destroy()


class LibraryWindow(ToolWindow):
    def __init__(self, app, title, size, kind):
        super().__init__(app, title, size)
        self.kind = kind
        self.name = tk.StringVar(self)
        row = tk.Frame(self.body, bg=PANEL)
        row.pack(fill="x", pady=(0, 8))
        self.label(row, "Saved " + ("palettes" if kind == "palette" else "presets")).pack(side="left")
        self.entries = ttk.Combobox(row, textvariable=self.name, state="readonly", width=28)
        self.entries.pack(side="left", padx=9, fill="x", expand=True)
        ttk.Button(row, text="Rename…", command=self.rename).pack(side="right")
        self.refresh()

    def refresh(self, selected=None):
        names = self.attempt(self.app.library.list, self.kind)
        if names is None:
            return
        self.entries.configure(values=names)
        current = selected or self.name.get()
        self.name.set(current if current in names else (names[0] if names else ""))

    def ask_name(self, title, initial=""):
        return simpledialog.askstring(title, "Name", initialvalue=initial, parent=self)

    def rename(self):
        old = self.name.get()
        if not old:
            self.feedback.set("Select a saved entry first.")
            return
        name = self.ask_name("Rename " + self.kind, old)
        if name is not None:
            updated = self.attempt(self.app.library.rename, self.kind, old, name)
            if updated:
                self.refresh(updated)
                self.success(f"Renamed to {updated}.")


class PresetsWindow(LibraryWindow):
    def __init__(self, app):
        super().__init__(app, "Presets", "615x255", "preset")
        self.minsize(560, 235)
        row = tk.Frame(self.body, bg=PANEL)
        row.pack(fill="x", pady=(5, 5))
        ttk.Button(row, text="Apply preset", command=self.use).pack(side="left")
        ttk.Button(row, text="Save current as…", command=self.save_current).pack(side="left", padx=6)
        ttk.Button(row, text="Update selected", command=self.update_selected).pack(side="left")
        files = tk.Frame(self.body, bg=PANEL)
        files.pack(fill="x", pady=5)
        ttk.Button(files, text="Open preset file…", command=app.load).pack(side="left")
        ttk.Button(files, text="Export current to JSON…", command=app.save).pack(side="left", padx=6)
        self.feedback_label()

    def use(self):
        data = self.attempt(self.app.library.preset, self.name.get())
        if data is not None:
            self.app.apply_preset(*data)
            self.success(f"Applied {self.name.get()}.")

    def save_current(self):
        self.app.save_named_preset(self, self.feedback.set)

    def update_selected(self):
        name = self.name.get()
        if not name:
            self.feedback.set("Select a saved preset first.")
        elif self.app.capture_settings():
            self.save_named(name, True)
        else:
            self.feedback.set("Correct the highlighted field before saving.")

    def save_named(self, name, replace=False):
        result = self.attempt(self.app.library.save_preset, name, self.app.look, self.app.export, replace)
        if result:
            self.refresh(result)
            self.success(f"Saved {result}.")


class PalettesWindow(LibraryWindow):
    def __init__(self, app):
        super().__init__(app, "Palettes", "615x505", "palette")
        self.minsize(550, 460)
        base = app.look.colors or PALETTES.get(app.look.palette, PALETTES["Opal"])
        self.colors = list(base[:-1] if len(base) > 1 and base[0] == base[-1] and not app.look.colors else base)
        ttk.Button(self.body, text="Load saved palette", command=self.use_saved).pack(anchor="w", pady=(0, 7))
        content = tk.Frame(self.body, bg=PANEL)
        content.pack(fill="both", expand=True)
        self.swatches = tk.Listbox(content, height=10, selectmode="browse", exportselection=False,
                                  font=("Consolas", 11), bg="#262433", fg=TEXT, highlightthickness=0)
        self.swatches.pack(side="left", fill="both", expand=True)
        controls = tk.Frame(content, bg=PANEL)
        controls.pack(side="right", fill="y", padx=(10, 0))
        for label, command in (
                ("Add color…", self.add), ("Edit color…", self.edit), ("Remove color", self.remove),
                ("Move up", lambda: self.move(-1)), ("Move down", lambda: self.move(1))):
            ttk.Button(controls, text=label, command=command).pack(fill="x", pady=2)
        self.hex_color = tk.StringVar(self)
        self.swatches.bind("<<ListboxSelect>>", self.select_color)
        hex_row = tk.Frame(self.body, bg=PANEL)
        hex_row.pack(fill="x", pady=(7, 0))
        self.label(hex_row, "Hex").pack(side="left")
        entry = ttk.Entry(hex_row, textvariable=self.hex_color, width=12)
        entry.pack(side="left", padx=6)
        entry.bind("<Return>", lambda _event: self.set_hex())
        ttk.Button(hex_row, text="Set selected color", command=self.set_hex).pack(side="left")

        footer = tk.Frame(self.body, bg=PANEL)
        footer.pack(fill="x", pady=(8, 0))
        ttk.Button(footer, text="Apply to preview", command=self.apply).pack(side="left")
        ttk.Button(footer, text="Save palette as…", command=self.save_current).pack(side="left", padx=7)
        self.feedback_label()
        self.redraw()

    def index(self):
        match = self.swatches.curselection()
        return match[0] if match else None

    def redraw(self, index=0):
        self.swatches.delete(0, "end")
        for number, color in enumerate(self.colors, 1):
            rgb = tuple(bytes.fromhex(color[1:]))
            light = .213*rgb[0] + .715*rgb[1] + .072*rgb[2]
            self.swatches.insert("end", f"  {number:2d}   {color}")
            self.swatches.itemconfigure(number-1, background=color,
                                        foreground="#131321" if light>142 else "#ffffff")
        if self.colors:
            self.swatches.selection_set(min(len(self.colors)-1, index))
        self.select_color()

    def select_color(self, _event=None):
        index = self.index()
        self.hex_color.set(self.colors[index] if index is not None else "")

    def use_saved(self):
        colors = self.attempt(self.app.library.palette, self.name.get())
        if colors:
            self.colors = list(colors)
            self.redraw()
            self.app.apply_palette(colors)
            self.success(f"Applied {self.name.get()}.")

    def add(self):
        if len(self.colors) == 10:
            self.feedback.set("A palette can hold up to ten colors.")
            return
        _, color = colorchooser.askcolor("#C3A9FF", parent=self)
        if color:
            self.colors.append(color.upper())
            self.redraw(len(self.colors)-1)

    def edit(self):
        index = self.index()
        if index is not None:
            _, color = colorchooser.askcolor(self.colors[index], parent=self)
            if color:
                self.colors[index] = color.upper()
                self.redraw(index)

    def set_hex(self):
        index = self.index()
        if index is not None:
            color = self.attempt(validate_colors, (self.hex_color.get().strip(),))
            if color:
                self.colors[index] = color[0]
                self.redraw(index)

    def remove(self):
        index = self.index()
        if index is None:
            return
        if len(self.colors) < 2:
            self.feedback.set("Keep at least one color in the palette.")
            return
        self.colors.pop(index)
        self.redraw(index)

    def move(self, offset):
        index = self.index()
        if index is not None and 0 <= index+offset < len(self.colors):
            self.colors[index], self.colors[index+offset] = self.colors[index+offset], self.colors[index]
            self.redraw(index+offset)

    def apply(self):
        colors = self.attempt(validate_colors, self.colors)
        if colors:
            self.app.apply_palette(colors)
            self.success("Applied colors to the preview.")

    def save_current(self):
        name = self.ask_name("Save palette", self.name.get())
        if name is not None:
            saved = self.attempt(self.app.library.save_palette, name, self.colors)
            if saved:
                self.refresh(saved)
                self.app.apply_palette(tuple(self.colors))
                self.success(f"Saved {saved}.")
