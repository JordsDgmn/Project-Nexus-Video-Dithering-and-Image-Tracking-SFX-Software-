from dataclasses import asdict
import json
import unittest

from entropy_app import read_group, resume_settings
from entropy_engine import ExportSpec, Look


class Input:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


def form(configuration, **updates):
    return {key: Input(value) for key, value in (asdict(configuration) | updates).items()}


class SettingsTests(unittest.TestCase):
    def test_blank_seed_does_not_block_other_look_changes(self):
        base = Look()
        latest, issues = read_group(form(base, seed="", hue=85, palette="Lagoon"), base)
        self.assertEqual((latest.seed, latest.hue, latest.palette), (base.seed, 85, "Lagoon"))
        self.assertEqual(issues, ["Seed (Motion) needs a whole number."])

    def test_blank_duration_does_not_block_aspect_change(self):
        base = ExportSpec()
        latest, issues = read_group(form(base, seconds="", ratio="9:16"), base)
        self.assertEqual((latest.seconds, latest.size), (base.seconds, (1080, 1920)))
        self.assertEqual(issues, ["Duration (Export) needs a whole number."])

    def test_bad_field_does_not_discard_the_rest_of_the_form(self):
        base = Look()
        latest, issues = read_group(form(base, seed="12.6", scatter=13), base)
        self.assertEqual((latest.seed, latest.scatter), (base.seed, 13))
        self.assertEqual(len(issues), 1)
        latest, issues = read_group(form(latest, seed="26"), latest)
        self.assertEqual(latest.seed, 26)
        self.assertFalse(issues)

    def test_restart_restores_last_valid_settings_and_phase(self):
        look, spec = Look(hue=63, seed=42), ExportSpec("9:16", 720, 24, 4)
        state = json.dumps({"look": asdict(look), "export": asdict(spec), "phase": .64,
                            "looping": False, "quality": "Sharp"})
        self.assertEqual(resume_settings(["--resume", state]), (look, spec, .64, False, "Sharp"))


if __name__ == "__main__":
    unittest.main()
