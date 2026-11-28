"""Named, portable Nexus presets and the initial user's Soft Dots look."""

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import sys
from tempfile import NamedTemporaryFile

from dots_effect import DOTS, DotsSettings
from nexus_preview import PREVIEW_QUALITY
from studio_effects import AUTO, FULL_FRAME_MODES, SUBJECT, SURFACE, Look, decode_preset_look


FIRST_NAME = "softdots-bright-halftone"


def default_target(look):
    return AUTO if look.mode in FULL_FRAME_MODES else SUBJECT


@dataclass(frozen=True)
class NexusPreset:
    look: Look
    target: str = AUTO
    preview: str = "Auto"

    def validate(self):
        self.look.validate()
        choices = (AUTO,) if self.look.mode in FULL_FRAME_MODES else (SUBJECT, SURFACE)
        if self.target not in choices:
            raise ValueError("The preset's tracking target does not match its look.")
        if not isinstance(self.preview, str) or self.preview not in PREVIEW_QUALITY:
            raise ValueError("The preset has an unknown preview quality.")
        return self


FIRST_PRESET = NexusPreset(Look(DOTS, dots=DotsSettings(
    size=13, hide_shadows=87, brightness=57, contrast=100,
)))


def library_path():
    if not getattr(sys, "frozen", False):
        return Path(__file__).resolve().parent / ".nexus-runtime" / "presets"
    home = Path(sys.executable).resolve().parent
    if home.name == "release" and home.parent.name == ".nexus-runtime":
        return home.parent / "presets"
    return home / "presets"


def name_path(folder, name):
    name = name.strip()
    if (not name or len(name) > 96 or name.endswith(".") or
            re.search(r'[<>:"/\\|?*\x00-\x1f]', name) or Path(name + ".json").is_reserved()):
        raise ValueError("Enter a Windows file name using 1 to 96 characters.")
    return folder / (name + ".json")


def load_settings(path):
    with path.open(encoding="utf-8-sig") as stream:
        data = json.load(stream)
    look = decode_preset_look(data)
    return NexusPreset(look, data.get("target", default_target(look)),
                       data.get("preview", "Auto")).validate()


def save_settings(path, settings, *, replace=False):
    settings.validate()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False,
                                prefix=".nexus-", suffix=".tmp") as stream:
            temp = Path(stream.name)
            json.dump({"version": 1, **asdict(settings)}, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        if replace:
            temp.replace(path)
        else:
            # Windows refuses to rename over an existing file.
            temp.rename(path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def install_first_preset(folder):
    path = name_path(folder, FIRST_NAME)
    if not path.exists():
        try:
            save_settings(path, FIRST_PRESET)
        except FileExistsError:
            pass
    return path
