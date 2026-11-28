"""Shared settings for detection, overlays, and ASCII previews."""

from dataclasses import dataclass


CLEAN = "Clean blobs"
NETWORK = "Line network"
VECTORS = "Motion vectors"
WORDS = "Word scatter"
ASCII = "ASCII texture"
GRAPHIC_MODES = (CLEAN, NETWORK, VECTORS, WORDS, ASCII)

DETECTORS = ("Features", "Motion blobs", "Bright blobs", "Dark blobs")
MARKS = ("Boxes + text", "Boxes", "Text", "None")
SHAPES = ("Rectangle", "Corners", "Circle", "Crosshair")
LINES = ("Straight", "Curved", "Dashed", "Step")
TEXT_STYLES = ("Plain", "Chip", "Outline", "Serif italic", "Mono")
TEXT_SOURCES = ("ID", "Coordinates", "Custom")
TEXT_SPLITS = ("Lines", "Words", "Phrases")
ASCII_COLORS = ("Source color", "Monochrome", "Accent")
ASCII_BACKDROPS = ("Black", "Original")


@dataclass(frozen=True)
class Graphics:
    detector: str = "Features"
    threshold: int = 32
    interval: int = 5
    min_size: int = 5
    max_size: int = 2500
    spacing: int = 4
    marks: str = "Boxes + text"
    shape: str = "Corners"
    box_scale: int = 100
    stroke: int = 1
    line_style: str = "Straight"
    link_density: int = 1
    link_range: int = 27
    label_style: str = "Plain"
    label_source: str = "ID"
    text_split: str = "Lines"
    custom_text: str = ""
    label_size: int = 100
    label_density: int = 80
    vector_gain: int = 120
    ascii_ramp: str = " .:-=+*#%@"
    ascii_size: int = 10
    ascii_color: str = "Source color"
    ascii_backdrop: str = "Black"
    ascii_dither: bool = True

    def validate(self):
        for key, choices in (
            ("detector", DETECTORS), ("marks", MARKS), ("shape", SHAPES), ("line_style", LINES),
            ("label_style", TEXT_STYLES), ("label_source", TEXT_SOURCES), ("text_split", TEXT_SPLITS),
            ("ascii_color", ASCII_COLORS), ("ascii_backdrop", ASCII_BACKDROPS),
        ):
            if getattr(self, key) not in choices:
                raise ValueError(f"Unknown {key.replace('_', ' ')}.")
        for key, low, high in (
            ("threshold", 1, 254), ("interval", 1, 120), ("min_size", 1, 3000),
            ("max_size", 1, 9500), ("spacing", 0, 30), ("box_scale", 20, 300), ("stroke", 1, 6),
            ("link_density", 0, 6), ("link_range", 0, 100), ("label_size", 40, 250),
            ("label_density", 0, 100), ("vector_gain", 0, 350), ("ascii_size", 5, 40),
        ):
            value = getattr(self, key)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{key.replace('_', ' ').capitalize()} must be {low} to {high}.")
        if self.min_size > self.max_size:
            raise ValueError("Minimum blob area must be at most the maximum.")
        if not isinstance(self.custom_text, str) or len(self.custom_text) > 60000:
            raise ValueError("Custom text must be at most 60,000 characters.")
        if (not isinstance(self.ascii_ramp, str) or not 2 <= len(self.ascii_ramp) <= 64
                or any(ord(char) < 32 or ord(char) > 126 for char in self.ascii_ramp)):
            raise ValueError("Use 2 to 64 printable ASCII glyphs, ordered from light to dense.")
        if type(self.ascii_dither) is not bool:
            raise ValueError("ASCII dithering must be on or off.")
        return self

    def detection_key(self):
        return self.detector, self.threshold, self.interval, self.min_size, self.max_size, self.spacing


def needs_scene_tracks(look):
    if look.mode != ASCII:
        return True
    config = look.graphics
    return (config.marks in ("Boxes + text", "Boxes")
            or (look.labels and config.marks == "Text")
            or (look.links and config.link_density > 0 and config.link_range > 0))
