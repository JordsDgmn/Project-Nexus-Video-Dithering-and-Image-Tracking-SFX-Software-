from dataclasses import replace
import unittest

import cv2
import numpy as np

from entropy_engine import EXACT, Look, Simulator, clip_timing


class TimingTests(unittest.TestCase):
    def test_extending_clip_keeps_the_six_second_pace(self):
        look = Look(cycles=5)
        for duration in (6, 42, 600, 1800):
            with self.subTest(duration=duration):
                self.assertAlmostEqual(clip_timing(look, duration).motion_cycles / duration, 5 / 6)

    def test_exact_speed_is_continuous_and_zero_stops_only_motion(self):
        look = Look(cycles=5, motion_speed=135, loop_fit=EXACT, rotation_speed=15)
        timing = clip_timing(look, 17)
        self.assertAlmostEqual(timing.motion_cycles / 17, 5 * 1.35 / 6)
        self.assertAlmostEqual(timing.rotation_turns * 360 / 17, 15)
        paused = clip_timing(replace(look, motion_speed=0), 17)
        self.assertEqual(paused.motion_cycles, 0)
        self.assertEqual(paused.rotation_turns, timing.rotation_turns)

    def test_seamless_motion_and_rotation_close_at_both_ends(self):
        look = Look(cycles=3, rotation_speed=33, rotation_angle=17)
        sim = Simulator((120, 80))
        plan = clip_timing(look, 13)
        self.assertEqual(plan.motion_cycles, 7)
        self.assertEqual(plan.rotation_turns, 1)
        self.assertTrue(np.array_equal(sim.frame(0, look, 13), sim.frame(1, look, 13)))
        exact = replace(look, loop_fit=EXACT)
        self.assertFalse(np.array_equal(sim.frame(0, exact, 13), sim.frame(1, exact, 13)))

    def test_rotation_direction_matches_image_rotation(self):
        sim = Simulator((80, 80))
        base = Look(cycles=0)
        frame = sim.frame(0, base, 6)
        clockwise = replace(base, rotation_speed=60)
        counter = replace(clockwise, rotation_direction="Counterclockwise")
        self.assertEqual(clip_timing(counter, 6).rotation_turns, -1)
        self.assertTrue(np.array_equal(sim.frame(.25, clockwise, 6), cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)))
        self.assertTrue(np.array_equal(sim.frame(.25, counter, 6), cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)))
