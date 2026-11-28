from dataclasses import asdict, replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import cv2
import numpy as np

from entropy_engine import BOKEH, CUSTOM, PRESETS, PRISM, ExportSpec, Simulator, decode_look, validate_colors
from entropy_library import Library
from entropy_texture import Texture


class StudioTests(unittest.TestCase):
    def test_new_looks_and_textures_close_the_loop(self):
        simulation = Simulator((160, 90))
        texture = Texture(grain=22, tatter=30, ripple=21, halftone=40, chromatic=25)
        for mode in (PRISM, BOKEH):
            with self.subTest(mode=mode):
                look = replace(PRESETS[mode], textures=texture)
                first = simulation.frame(0, look)
                self.assertTrue(np.array_equal(first, simulation.frame(1, look)))
                self.assertTrue(np.any(cv2.absdiff(first, simulation.frame(.21, look))))

    def test_bypassed_stack_can_be_reenabled_after_loading(self):
        saved = Texture(grain=52, ripple=30, enabled=False)
        restored = decode_look(asdict(replace(PRESETS[BOKEH], textures=saved))).textures
        self.assertEqual(restored, saved)
        self.assertFalse(restored.active)
        self.assertTrue(replace(restored, enabled=True).active)

    def test_palette_limit_and_library_rename(self):
        colors = tuple(f"#{i * 71263:06X}" for i in range(1, 11))
        with self.assertRaises(ValueError):
            validate_colors((*colors, "#ABCDEF"))
        with TemporaryDirectory() as path:
            library = Library(Path(path))
            library.save_palette("First palette", colors)
            library.rename("palette", "First palette", "Saved palette")
            look = replace(PRESETS[PRISM], palette=CUSTOM, colors=library.palette("saved palette"),
                           textures=Texture(halftone=56))
            spec = ExportSpec("9:16", 720, 24, 2)
            library.save_preset("First", look, spec)
            library.rename("preset", "First", "Portable")
            self.assertEqual(Library(Path(path)).preset("portable"), (look, spec))
