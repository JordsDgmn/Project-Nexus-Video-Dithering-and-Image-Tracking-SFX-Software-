"""Entropy's texture controls and local asset libraries."""

from dataclasses import asdict
from random import randrange
import sqlite3
import tkinter as tk
from tkinter import colorchooser, simpledialog, ttk
import traceback

from entropy_bokeh import (
    APERTURES, BACKDROPS, CAMERA_RECIPES, INDEPENDENT, LAYOUTS, LENS_COLORS, LIGHT_COLORS, MODELS, MOVEMENTS, RANGES,
)
from entropy_bokeh_animation import ANIMATION_RANGES, DRIFT_RATES, FADE_PATTERNS, FADE_RATES, LAYER_PATHS
from entropy_engine import PALETTES, validate_colors
from entropy_style import FORMS, LENS_TINTS, PULSES, Style
from entropy_texture import PRINT_STYLES, Texture


PANEL = "#191925"
TEXT = "#f0edf9"
MUTED = "#afabbd"
ACCENT = "#c7acff"

TEXTURE_RECIPES = {
    "Film wear": Texture(grain=34, grain_size=2, vignette=38, tatter=57, edge_width=5, roughness=82),
    "Paper fibers": Texture(paper=57, fiber_size=36, grain=14, vignette=28),
    "Scratched reel": Texture(scratches=66, scratch_count=16, grain=25, vignette=26),
    "Analog monitor": Texture(scanlines=42, line_spacing=8, chromatic=12, grain=13),
    "Ink print": Texture(grain=19, halftone=66, cell_size=11, angle=33, posterize=38, levels=7),
    "Broken glass": Texture(distort=37, distort_scale=53, ripple=25, ripple_count=8, chromatic=48),
}


STYLE_RECIPES = {
    "Opal ribbons": Style(form="Ribbons", bend=49, stretch_x=40, turbulence=17, glimmer=36, density=74),
    "Prism bloom": Style(form="Facets", bend=42, turbulence=9, flare=65, flare_size=49,
                         flare_x=26, flare_y=25, flare_angle=-24, streaks=68, ghosts=5, tint="Ice"),
    "Stardust": Style(specks=28, glimmer=40, glitter=64, density=140, particle_size=49,
                      drift=24, particle_tint="Warm"),
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


class LiveStackWindow(ToolWindow):
    def __init__(self, app, title, config, commit, recipes, pages, *, size="595x500", reset="Reset stack"):
        super().__init__(app, title, size)
        self.minsize(525, 465)
        self.config_type = type(config)
        self.commit = commit
        self.recipes = recipes
        self.recipe_prompt = f"{title} recipe…"
        self.pending = None
        self.syncing = False
        self.enabled = tk.BooleanVar(self, config.enabled) if hasattr(config, "enabled") else None
        self.values = {}
        for key, value in asdict(config).items():
            if key == 'enabled':
                continue
            kind = tk.BooleanVar if type(value) is bool else tk.IntVar if type(value) is int else tk.StringVar
            self.values[key] = kind(self, value)
            self.values[key].trace_add("write", self.schedule)
        self.toolbar = tk.Frame(self.body, bg=PANEL)
        self.toolbar.pack(fill="x", pady=(0, 8))
        if self.enabled is not None:
            self.enabled.trace_add("write", self.schedule)
            ttk.Checkbutton(self.toolbar, text=f"Enable {title.lower()}", variable=self.enabled).pack(side="left")
        ttk.Button(self.toolbar, text=reset, command=self.reset).pack(side="right")
        self.recipe = ttk.Combobox(self.toolbar, state="readonly", width=20, values=tuple(recipes))
        self.recipe.set(self.recipe_prompt)
        self.recipe.pack(side="right", padx=(0, 7))
        self.recipe.bind("<<ComboboxSelected>>", self.use_recipe)
        self.book = ttk.Notebook(self.body)
        self.book.pack(fill="both", expand=True)
        for name, content in pages:
            page = tk.Frame(self.book, bg=PANEL, padx=10, pady=8)
            self.book.add(page, text=name)
            content(page)
        self.feedback.set("Changes update the preview while it plays or pauses.")
        self.feedback_label()

    def scale(self, parent, title, key, low, high, *, label_width=22, format_value=None):
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill="x", pady=2)
        self.label(row, title, width=label_width).pack(side="left")
        value = self.values[key]
        if format_value is None:
            self.label(row, variable=value, width=4).pack(side="right")
        else:
            readout = self.label(row, format_value(value.get()), width=6)
            readout.pack(side="right")
            value.trace_add("write", lambda *_: readout.configure(text=format_value(value.get())))
        bar = tk.Scale(row, from_=low, to=high, resolution=1, orient="horizontal",
                       variable=self.values[key], showvalue=False, bg=PANEL, fg=TEXT,
                       activebackground=ACCENT, troughcolor="#40354f", highlightthickness=0,
                       borderwidth=0, sliderlength=14, width=14)
        bar.pack(side="left", fill="x", expand=True)

    def choice(self, parent, label, key, choices):
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill="x", pady=4)
        self.label(row, label).pack(side="left")
        ttk.Combobox(row, state="readonly", textvariable=self.values[key],
                     values=choices).pack(side="right")

    def schedule(self, *_):
        if not self.syncing and self.pending is None:
            self.pending = self.after(55, self.apply)

    def apply(self):
        self.pending = None
        values = {key: value.get() for key, value in self.values.items()}
        if self.enabled is not None:
            values["enabled"] = self.enabled.get()
        config = self.config_type(**values).validate()
        self.commit(config)
        self.feedback.set("Changes apply to the preview and the next export.")

    def sync(self, config):
        if self.pending is not None:
            self.after_cancel(self.pending)
            self.pending = None
        self.syncing = True
        if self.enabled is not None:
            self.enabled.set(config.enabled)
        for key, field in self.values.items():
            field.set(getattr(config, key))
        self.syncing = False

    def use_recipe(self, _event=None):
        self.sync(self.recipes[self.recipe.get()])
        self.apply()
        self.recipe.set(self.recipe_prompt)

    def reset(self):
        self.sync(self.config_type())
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


class TexturesWindow(LiveStackWindow):
    def __init__(self, app):
        super().__init__(app, "Textures", app.look.textures, app.apply_textures, TEXTURE_RECIPES,
                         (("Grain & print", self.print_page), ("Distortion", self.warp_page),
                          ("Edges & tone", self.edge_page), ("Surface", self.surface_page)))

    def print_page(self, page):
        self.scale(page, "Film grain", "grain", 0, 100)
        self.scale(page, "Grain size", "grain_size", 1, 12)
        ttk.Checkbutton(page, text="Color grain", variable=self.values["colored_grain"]).pack(anchor="w", pady=4)
        self.scale(page, "Halftone", "halftone", 0, 100)
        self.scale(page, "Print cell size", "cell_size", 3, 36)
        self.scale(page, "Print angle", "angle", 0, 180)
        self.choice(page, "Pattern", "print_style", PRINT_STYLES)

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

    def surface_page(self, page):
        for args in (("Paper fibers", "paper", 0, 100), ("Fiber fineness", "fiber_size", 1, 100),
                     ("Film scratches", "scratches", 0, 100), ("Scratch count", "scratch_count", 1, 40),
                     ("Scanlines", "scanlines", 0, 100), ("Line spacing", "line_spacing", 2, 24)):
            self.scale(page, *args)


class StyleWindow(LiveStackWindow):
    def __init__(self, app):
        super().__init__(app, "Style", app.look.style, app.apply_style, STYLE_RECIPES,
                         (("Form", self.form_page), ("Particles", self.particles_page),
                          ("Lens", self.lens_page), ("Strobe", self.strobe_page)))

    def form_page(self, page):
        self.choice(page, "Shape", "form", FORMS)
        for args in (("Shape strength", "bend", 0, 100), ("Fluidity", "fluidity", 0, 100),
                     ("Horizontal stretch", "stretch_x", -60, 100), ("Vertical stretch", "stretch_y", -60, 100),
                     ("Turbulence", "turbulence", 0, 100), ("Turbulence detail", "detail", 0, 100),
                     ("Flow cycles", "flow_speed", 0, 4)):
            self.scale(page, *args)
        row = tk.Frame(page, bg=PANEL)
        row.pack(fill="x", pady=(8, 0))
        ttk.Button(row, text="Shuffle pattern",
                   command=lambda: self.values["seed"].set(randrange(1000000))).pack(side="left")
        self.label(row, "Seed").pack(side="left", padx=(12, 5))
        self.label(row, variable=self.values["seed"]).pack(side="left")
        self.label(page, "Shape strength bends the simulation. Turbulence adds finer movement.",
                   wraplength=470).pack(anchor="w", pady=(8, 0))

    def particles_page(self, page):
        for args in (("Specks", "specks", 0, 100), ("Glimmer", "glimmer", 0, 100),
                     ("Glitter", "glitter", 0, 100), ("Particle count", "density", 1, 240),
                     ("Particle size", "particle_size", 0, 100), ("Drift", "drift", 0, 100),
                     ("Twinkle cycles", "twinkle_cycles", 0, 6)):
            self.scale(page, *args)
        self.choice(page, "Particle tint", "particle_tint", tuple(LENS_TINTS))
        self.label(page, "Specks are steady dots. Glimmer adds soft pulses. Glitter draws starbursts.",
                   wraplength=470).pack(anchor="w", pady=(8, 0))

    def lens_page(self, page):
        for args in (("Flare strength", "flare", 0, 100), ("Flare size", "flare_size", 0, 100),
                     ("Horizontal position", "flare_x", 0, 100), ("Vertical position", "flare_y", 0, 100),
                     ("Streak angle", "flare_angle", -180, 180), ("Streak strength", "streaks", 0, 100),
                     ("Reflections", "ghosts", 0, 8)):
            self.scale(page, *args)
        self.choice(page, "Light tint", "tint", tuple(LENS_TINTS))

    def strobe_page(self, page):
        self.scale(page, "Exposure boost", "strobe", 0, 100)
        self.scale(page, "Pulses per second", "pulse_rate", 1, 3)
        self.scale(page, "Pulse width (%)", "pulse_width", 10, 85)
        self.choice(page, "Pulse shape", "pulse_shape", PULSES)
        self.label(page, "At zero, strobe is off. Pulse speed stays fixed when clip duration changes.",
                   wraplength=470).pack(anchor="w", pady=(8, 0))


class BokehWindow(LiveStackWindow):
    def __init__(self, app):
        super().__init__(app, "Bokeh camera", app.look.bokeh, app.apply_bokeh, CAMERA_RECIPES,
                         (("Lights", self.lights_page), ("Aperture", self.aperture_page),
                          ("Focus", self.focus_page), ("Movement", self.movement_page),
                          ("Backdrop", self.backdrop_page), ("Lens FX", self.optics_page),
                          ("Fades", self.fade_page), ("Pulses", self.pulse_page)),
                         size="650x520", reset="Reset camera")
        self.minsize(585, 465)
        self.label(self.toolbar, "Renderer").pack(side="left", padx=(0, 7))
        ttk.Combobox(self.toolbar, textvariable=self.values["model"], values=MODELS,
                     state="readonly", width=17).pack(side="left")
        self.update_feedback()
        app.update_idletasks()
        right = app.winfo_rootx() + app.winfo_width()
        left = max(0, min(right - 350, app.winfo_screenwidth() - 670))
        self.geometry(f"+{left}+{max(0, app.winfo_rooty() + 30)}")

    def apply(self):
        super().apply()
        self.update_feedback()

    def sync(self, config):
        super().sync(config)
        self.update_feedback()

    def update_feedback(self):
        model = self.values["model"].get()
        independent = model == INDEPENDENT
        self.book.tab(self.fade_panel, state="normal" if independent else "hidden")
        self.movement_tabs.tab(self.layer_panel, state="normal" if independent else "hidden")
        if independent:
            self.lock_camera.pack(anchor="w", before=self.camera_controls, pady=(0, 4))
            self.legacy_drift.pack_forget()
            self.feedback.set("Light motion and fades use their own clocks. Changes save with your preset.")
        else:
            self.lock_camera.pack_forget()
            self.legacy_drift.pack(fill="x")
            if model == "Classic":
                self.feedback.set("Classic uses the earlier look. Choose Camera or a recipe to use the tabs.")
            else:
                self.feedback.set("Camera settings update live and save with your preset.")

    def controls(self, page, items):
        for label, key in items:
            self.scale(page, label, key, *RANGES[key])

    def note(self, page, text):
        self.label(page, text, wraplength=490).pack(anchor="w", pady=(8, 0))

    def lights_page(self, page):
        self.choice(page, "Arrangement", "layout", LAYOUTS)
        self.choice(page, "Light colors", "light_color", tuple(LIGHT_COLORS))
        self.controls(page, (("Light count", "count"), ("Brightness", "brightness"),
                             ("Source size", "source_size"), ("Size variation", "size_spread"),
                             ("Largest disc (%)", "max_size")))
        self.note(page, "Largest disc caps the unstretched radius relative to the frame’s short edge.")

    def aperture_page(self, page):
        self.choice(page, "Aperture shape", "aperture", APERTURES)
        self.controls(page, (("Blade count", "blades"), ("Blade curvature", "roundness"),
                             ("Blade rotation (°)", "aperture_angle"), ("Ring opening (%)", "obstruction"),
                             ("Edge softness", "edge_softness"), ("Bright rim", "rim"),
                             ("Concentric texture", "onion_rings")))
        self.note(page, "Blade controls apply to Blades. Ring opening sets the size of the dark center.")

    def focus_page(self, page):
        self.controls(page, (("Aperture opening", "opening"), ("Focus distance", "focus"),
                             ("Depth spread", "depth"), ("Sharp range", "focus_range"),
                             ("Focus breathing", "breathing")))
        self.note(page, "Focus distance moves from near to far. Breathing shifts focus gently while the camera moves.")

    def movement_page(self, page):
        self.movement_tabs = ttk.Notebook(page)
        self.movement_tabs.pack(fill="both", expand=True)
        camera = tk.Frame(self.movement_tabs, bg=PANEL, padx=8, pady=8)
        self.layer_panel = tk.Frame(self.movement_tabs, bg=PANEL, padx=8, pady=8)
        self.movement_tabs.add(camera, text="Camera")
        self.movement_tabs.add(self.layer_panel, text="Light layers")
        self.lock_camera = ttk.Checkbutton(camera, text="Lock camera", variable=self.values["camera_locked"])
        self.camera_controls = tk.Frame(camera, bg=PANEL)
        self.camera_controls.pack(fill="x")
        self.choice(self.camera_controls, "Camera movement", "movement", MOVEMENTS)
        self.controls(self.camera_controls, (("Movement cycles", "speed"), ("Horizontal limit (%)", "travel_x"),
                                             ("Vertical limit (%)", "travel_y"), ("Depth parallax", "parallax")))
        self.legacy_drift = tk.Frame(camera, bg=PANEL)
        self.legacy_drift.pack(fill="x")
        self.controls(self.legacy_drift, (("Individual drift", "wander"),))
        self.note(self.camera_controls, "Camera travel is separate from light travel. Lock also stops focus breathing.")
        self.light_layers(self.layer_panel)

    def light_layers(self, page):
        self.choice(page, "Light path", "light_path", LAYER_PATHS)
        self.scale(page, "Horizontal travel (%)", "light_travel_x", *ANIMATION_RANGES["light_travel_x"])
        self.scale(page, "Vertical travel (%)", "light_travel_y", *ANIMATION_RANGES["light_travel_y"])
        columns = tk.Frame(page, bg=PANEL)
        columns.pack(fill="x", pady=(8, 0))
        for title, rates in (("Motion speed", DRIFT_RATES), ("Fade speed", FADE_RATES)):
            column = tk.Frame(columns, bg=PANEL, padx=4)
            column.pack(side="left", fill="x", expand=True)
            self.label(column, title).pack(anchor="w", pady=(0, 3))
            for label, key in zip(("Foreground", "Middle", "Background"), rates):
                self.scale(column, label, key, *ANIMATION_RANGES[key], label_width=11,
                           format_value=lambda value: f"{value}%")
        self.note(page, "At 0%, that layer holds position or keeps steady brightness. Background includes distant lights.")

    def fade_page(self, page):
        self.fade_panel = page
        self.choice(page, "Fade pattern", "fade_pattern", FADE_PATTERNS)
        for label, key in (("Affected lights (%)", "fade_share"), ("Typical interval", "fade_interval"),
                           ("Timing variation (%)", "fade_variation"), ("Minimum light (%)", "fade_floor"),
                           ("Peak light (%)", "fade_peak"), ("Transition softness", "fade_softness")):
            self.scale(page, label, key, *ANIMATION_RANGES[key],
                       format_value=(lambda value: f"{value / 10:.1f} s") if key == "fade_interval" else None)
        row = tk.Frame(page, bg=PANEL)
        row.pack(fill="x", pady=(7, 0))
        ttk.Button(row, text="Shuffle light animation",
                   command=lambda: self.values["animation_seed"].set(randrange(1000000))).pack(side="left")
        self.label(row, "Seed").pack(side="left", padx=(12, 5))
        self.label(row, variable=self.values["animation_seed"]).pack(side="left")
        self.note(page, "Interval sets the pace at 100% fade speed. Seamless clip fits the pattern to the loop.")

    def backdrop_page(self, page):
        self.choice(page, "Backdrop", "backdrop", BACKDROPS)
        self.controls(page, (("Backdrop strength", "backdrop_strength"), ("Distant lights", "far_lights"),
                             ("Haze between lights", "haze")))
        self.note(page, "Set the backdrop color under Light → Background. Distant lights and haze can also sit over black.")

    def optics_page(self, page):
        self.choice(page, "Lens tint", "lens_color", tuple(LENS_COLORS))
        self.controls(page, (("Oval stretch (%)", "squeeze"), ("Edge cat-eye", "cat_eye"),
                             ("Streak strength", "streaks"), ("Streak length", "streak_length"),
                             ("Streak angle (°)", "streak_angle"), ("Spectral splitting", "prism"),
                             ("Aperture fringing", "fringe"), ("Flare strength", "flare"),
                             ("Lens reflections", "ghosts")))
        self.note(page, "Bright moving lights drive the streaks and flares. Set strength above zero to see each effect.")

    def pulse_page(self, page):
        self.controls(page, (("Pulse strength", "pulse_amount"), ("Eligible lights (%)", "pulse_share"),
                             ("Max pulses per sec", "pulse_rate")))
        self.note(page, "A seeded subset of lights pulses at different moments. Set strength to zero to turn pulses off.")


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
