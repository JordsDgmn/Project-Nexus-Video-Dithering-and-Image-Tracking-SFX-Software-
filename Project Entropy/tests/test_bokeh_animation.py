"""Tests for the independent camera, layer clocks, and light fades."""

from dataclasses import replace
import unittest

import cv2
import numpy as np

from entropy_bokeh import CAMERA_RECIPES, INDEPENDENT, move_light
from entropy_bokeh_animation import FADE_PATTERNS, LightAnimation
from entropy_engine import BOKEH, PRESETS, ExportSpec, Simulator
from entropy_runtime import decode_preset, preset_document


class AnimationTests(unittest.TestCase):
    def setUp(self):
        self.recipe = CAMERA_RECIPES["Living lights"]

    def test_camera_lock_leaves_light_motion_independent(self):
        config = replace(self.recipe, movement="Dolly", focus=80, breathing=40, fade_pattern="Off")
        self.assertEqual(move_light(config, 1.4, .6, -.5, .4, .2, independent=True), (0., 0., 1.))
        self.assertNotEqual(move_light(replace(config, camera_locked=False), 1.4, .6, -.5, .4, .2,
                                       independent=True), (0., 0., 1.))
        sim = Simulator((240, 144))
        look = replace(PRESETS[BOKEH], bokeh=config, cycles=0)
        self.assertGreater(cv2.absdiff(sim.frame(0., look), sim.frame(.17, look)).max(), 5)
        still = replace(look, bokeh=replace(config, light_path="Still"))
        np.testing.assert_array_equal(sim.frame(0., still), sim.frame(.17, still))
        # Lock also removes global camera movement and breathing even when the scene clock runs.
        still = replace(still, cycles=1)
        np.testing.assert_array_equal(sim.frame(0., still), sim.frame(.17, still))

    def test_motion_and_fade_clocks_can_each_freeze_one_layer(self):
        config = replace(self.recipe, foreground_speed=200, middle_speed=100, background_speed=0,
                         foreground_fade=0, middle_fade=100, background_fade=200, fade_share=100)
        animation = LightAnimation(config, 6, False)
        self.assertEqual(animation.drift_clocks, (2., 1., 0.))
        self.assertEqual(animation.drift(1, 2, .13), (0., 0.))
        self.assertNotEqual(animation.drift(1, 0, .13), animation.drift(1, 1, .13))
        self.assertEqual(animation.gain(1, 0, .4, .13), 1.)
        self.assertNotEqual(animation.fade_clocks[1], animation.fade_clocks[2])

    def test_exact_speed_uses_elapsed_time_independently_of_duration(self):
        config = replace(self.recipe, fade_share=100)
        short = LightAnimation(config, 6, False)
        long = LightAnimation(config, 1800, False)
        for i in range(3):
            np.testing.assert_allclose(short.drift(7, i, 2.7/6), long.drift(7, i, 2.7/1800))
            self.assertAlmostEqual(short.gain(7, i, .4, 2.7/6), long.gain(7, i, .4, 2.7/1800))

    def test_fade_patterns_have_distinct_local_bounded_curves_and_close(self):
        curves = []
        for pattern in FADE_PATTERNS:
            config = replace(self.recipe, fade_pattern=pattern, fade_share=100, fade_floor=5, fade_peak=172)
            light = LightAnimation(config, 9, True)
            curve = [light.gain(8, 0, .4, t/128) for t in range(129)]
            curves.append(curve)
            self.assertAlmostEqual(curve[0], curve[-1])
            self.assertTrue(all(.05 <= value <= 1.72 for value in curve))
            if pattern != "Off":
                self.assertGreater(max(curve) - min(curve), .1)
                self.assertNotEqual(curve, [light.gain(2, 0, .75, t/128) for t in range(129)])
        self.assertEqual(len({tuple(curve) for curve in curves}), len(FADE_PATTERNS))
        dark_subset = LightAnimation(replace(self.recipe, fade_share=0), 9, True)
        self.assertEqual(dark_subset.gain(8, 0, .4, .65), 1.)
        short = LightAnimation(replace(self.recipe, fade_share=100, fade_interval=160), 1, True)
        samples = [short.gain(8, 0, .4, t/36) for t in range(37)]
        self.assertGreater(max(samples) - min(samples), .01)

    def test_saving_and_old_camera_preset_compatibility(self):
        look = replace(PRESETS[BOKEH], bokeh=replace(self.recipe, fade_interval=37, camera_locked=False))
        spec = ExportSpec(seconds=13)
        sim = Simulator((232, 144))
        body = preset_document(look, spec)
        saved, _ = decode_preset(body)
        self.assertEqual(saved.bokeh.model, INDEPENDENT)
        self.assertEqual(look, saved)
        np.testing.assert_array_equal(sim.frame(0, saved, spec.seconds), sim.frame(1, saved, spec.seconds))
        self.assertLess(cv2.absdiff(sim.frame(0, saved, spec.seconds),
                                    sim.frame(.99999, saved, spec.seconds)).mean(), .5)
        v6_look = replace(PRESETS[BOKEH], bokeh=CAMERA_RECIPES["Festival lights"])
        old = preset_document(v6_look, spec)
        for key in set(old["look"]["bokeh"]) - {
            "model", "layout", "light_color", "count", "brightness", "source_size", "size_spread", "max_size",
            "pulse_amount", "pulse_share", "pulse_rate", "aperture", "blades", "roundness", "aperture_angle",
            "obstruction", "edge_softness", "rim", "onion_rings", "opening", "focus", "depth", "focus_range",
            "breathing", "movement", "speed", "travel_x", "travel_y", "parallax", "wander", "backdrop",
            "backdrop_strength", "far_lights", "haze", "squeeze", "cat_eye", "streaks", "streak_length",
            "streak_angle", "prism", "fringe", "flare", "ghosts", "lens_color",
        }:
            del old["look"]["bokeh"][key]
        self.assertEqual(decode_preset(old), (v6_look, spec))
