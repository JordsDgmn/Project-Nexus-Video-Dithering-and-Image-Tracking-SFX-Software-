"""Check the live camera controls, playback, and legacy preset behavior."""

from dataclasses import replace
import math
import unittest

import cv2
import numpy as np

from entropy_bokeh import CAMERA_RECIPES, MOVEMENTS, BokehSettings, aperture_stamp, light_pulse, move_light
from entropy_engine import BOKEH, PRESETS, ExportSpec, Simulator
from entropy_runtime import decode_preset, preset_document


class BokehTests(unittest.TestCase):
    def setUp(self):
        self.sim = Simulator((232, 144))
        self.look = PRESETS[BOKEH]

    def test_aperture_shapes_have_different_silhouettes(self):
        round_mask = aperture_stamp("Round", 5, 0, 0, 44, 10, 20, 0)
        blade_mask = aperture_stamp("Blades", 5, 0, 27, 44, 10, 20, 0)
        ring_mask = aperture_stamp("Ring", 5, 0, 0, 44, 10, 20, 0)
        self.assertGreater(np.mean(cv2.absdiff(round_mask, blade_mask)), .01)
        center = np.s_[45:57, 45:57]
        self.assertLess(ring_mask[center].mean(), round_mask[center].mean() * .08)

    def test_controls_change_the_render_independently(self):
        reference = self.sim.frame(.23, self.look)
        for changes in (dict(count=3), dict(opening=95), dict(focus=2), dict(depth=12),
                        dict(backdrop="Black"), dict(far_lights=100), dict(haze=100),
                        dict(squeeze=225), dict(cat_eye=100), dict(streaks=100),
                        dict(fringe=100), dict(flare=100), dict(lens_color="Cold blue")):
            with self.subTest(changes=changes):
                config = replace(self.look.bokeh, **changes)
                frame = self.sim.frame(.23, replace(self.look, bokeh=config))
                self.assertGreater(cv2.absdiff(reference, frame).max(), 2)
        dark = replace(self.look.bokeh, brightness=0, backdrop="Black")
        frame = self.sim.frame(.23, replace(self.look, bokeh=dark))
        self.assertEqual(frame.max(), 0)

    def test_movement_keeps_limits_and_still_freezes_sources(self):
        for mode in MOVEMENTS:
            config = replace(self.look.bokeh, movement=mode, wander=100, speed=4)
            t = np.linspace(0, math.tau, 130)
            for time in t:
                dx, dy, _ = move_light(config, time, -.9, .7, .16, .83)
                self.assertLessEqual(abs(dx), 1.)
                self.assertLessEqual(abs(dy), 1.)
        still = replace(self.look, bokeh=replace(self.look.bokeh, movement="Still", pulse_amount=0))
        np.testing.assert_array_equal(self.sim.frame(.2, still), self.sim.frame(.75, still))

    def test_pulses_are_seeded_local_and_taper_at_slot_edges(self):
        config = BokehSettings(pulse_amount=100, pulse_share=25, pulse_rate=3)
        samples = np.linspace(0, 8, 481)
        first = [light_pulse(1, .13, .31, 208, config, t) for t in samples]
        second = [light_pulse(6, .13, .31, 208, config, t) for t in samples]
        self.assertGreater(max(first), .6)
        self.assertNotEqual(first, second)
        self.assertTrue(all(light_pulse(1, .50, .31, 208, config, t) == 0 for t in samples))
        self.assertTrue(all(light_pulse(1, .13, .31, 208, config, n / 3) == 0 for n in range(25)))

    def test_recipes_loop_and_legacy_presets_keep_classic_model(self):
        spec = ExportSpec(seconds=17)
        for recipe in CAMERA_RECIPES.values():
            with self.subTest(recipe=recipe):
                look = replace(self.look, bokeh=replace(recipe, pulse_amount=60))
                self.assertEqual(decode_preset(preset_document(look, spec)), (look, spec))
                start = self.sim.frame(0, look, spec.seconds)
                np.testing.assert_array_equal(start, self.sim.frame(1, look, spec.seconds))
                self.assertLess(cv2.absdiff(start, self.sim.frame(.99999, look, spec.seconds)).mean(), .8)
        previous = preset_document(self.look, spec)
        del previous["look"]["bokeh"]
        classic, _ = decode_preset(previous)
        self.assertEqual(classic.bokeh.model, "Classic")
        sim = Simulator((232, 144))
        self.assertGreater(sim.frame(.2, classic).max(), 10)
        self.assertIsNone(sim.camera)
