"""Background clip inspection and seekable, single-decoder previews."""

from dataclasses import dataclass
import math
from pathlib import Path
from queue import Queue
from threading import Condition, Thread

import cv2
import numpy as np

from dots_effect import DOTS, DotsRenderer
from graphics_settings import needs_scene_tracks
from scene_effects import SCENE_MODES, SceneTracker, paint_scene
from studio_effects import Effect, box_corners, surface_frames
from track import tracked_frames


@dataclass(frozen=True)
class Clip:
    path: Path
    width: int
    height: int
    fps: float
    frames: int
    codec: str
    size: int
    backend: str
    bitrate: float
    pixel_format: str
    aspect: tuple
    rotation: float


@dataclass(frozen=True)
class PreviewSpec:
    path: Path
    look: object = None
    selection: tuple = None
    planar: bool = False


class Superseded(Exception):
    pass


def fourcc(code):
    value = int(code)
    return "".join(chr((value >> (8 * shift)) & 255) for shift in range(4)
                   if 32 <= ((value >> (8 * shift)) & 255) < 127) or "Unknown"


def clip_info(path, capture, frame):
    rate = capture.get(cv2.CAP_PROP_FPS)
    count = capture.get(cv2.CAP_PROP_FRAME_COUNT)
    codec = fourcc(capture.get(cv2.CAP_PROP_FOURCC))
    pixel_format = fourcc(capture.get(cv2.CAP_PROP_CODEC_PIXEL_FORMAT))
    aspect = (int(capture.get(cv2.CAP_PROP_SAR_NUM)), int(capture.get(cv2.CAP_PROP_SAR_DEN)))
    return Clip(path, frame.shape[1], frame.shape[0],
                rate if math.isfinite(rate) and rate > 0 else 0.0,
                int(count) if math.isfinite(count) and count > 0 else 0,
                codec, path.stat().st_size, capture.getBackendName(),
                capture.get(cv2.CAP_PROP_BITRATE), pixel_format, aspect,
                capture.get(cv2.CAP_PROP_ORIENTATION_META))


def inspect_clip(path):
    capture = cv2.VideoCapture(str(path))
    try:
        ok, frame = capture.read()
        if not ok:
            raise ValueError("Could not decode the first frame of this video.")
        return clip_info(path, capture, frame), frame
    finally:
        capture.release()


def preview_size(frame):
    height, width = frame.shape[:2]
    if max(width, height) <= 820:
        return frame
    scale = 820 / max(width, height)
    return cv2.resize(frame, (max(1, round(width * scale)), max(1, round(height * scale))),
                      interpolation=cv2.INTER_AREA)


class Stream:
    def __init__(self, spec):
        self.spec = spec
        self.capture = cv2.VideoCapture(str(spec.path))
        if not self.capture.isOpened():
            self.close()
            raise ValueError("Could not open this clip for preview.")
        self.index = -1
        self.last = None
        self.fps = self.capture.get(cv2.CAP_PROP_FPS) or 30
        self.auto = spec.look is not None and spec.look.mode in SCENE_MODES
        self.track = self.auto and needs_scene_tracks(spec.look)
        self.dots = DotsRenderer(spec.look.dots) if spec.look is not None and spec.look.mode == DOTS else None
        self.manual = (spec.look is not None and self.dots is None
                       and not self.auto and spec.selection is not None)
        self.tracker = self.iterator = self.effect = None
        self.raw = None
        self.tracks = ()

    def retune(self, spec):
        if not (self.auto and spec.path == self.spec.path and spec.look is not None
                and spec.look.mode in SCENE_MODES):
            return False
        old, new = self.spec.look, spec.look
        self.spec = spec
        track = needs_scene_tracks(new)
        changed = track != self.track
        self.track = track
        if self.track and (changed or old.graphics.detection_key() != new.graphics.detection_key()
                           or old.detail != new.detail):
            self.tracker = None
            self.last = None
        else:
            if self.track and self.tracker is not None:
                self.tracker.configure(new.detail, new)
            if self.raw is not None:
                self.tracks = self.tracks[:new.max_boxes] if self.track else ()
                self.last = paint_scene(self.raw, self.tracks, new, self.index, self.fps,
                                        self.tracker.crop_ids if self.track and self.tracker else None)
        return True

    def close(self):
        self.capture.release()

    def jump(self, index):
        self.capture.set(cv2.CAP_PROP_POS_FRAMES, index)
        position = self.capture.get(cv2.CAP_PROP_POS_FRAMES)
        if abs(position - index) > .5:
            raise ValueError("This video codec could not seek to the selected frame.")
        self.index = index - 1

    def frame_at(self, target, cancelled, progress):
        if target == self.index and self.last is not None:
            return self.last
        if self.track and (self.tracker is None or target < self.index or target > self.index + 15):
            self.jump(max(0, target - 10))
            self.tracker = SceneTracker(self.spec.look.detail, self.spec.look)
        elif self.manual and (self.iterator is None or target < self.index):
            self.jump(0)
            self.effect = Effect(self.spec.look)
            if self.spec.planar:
                self.iterator = surface_frames(self.capture, self.spec.selection)
            else:
                self.iterator = tracked_frames(self.capture, self.spec.selection, max_tracking_edge=960)
        elif not (self.track or self.manual) and target != self.index + 1:
            self.jump(target)

        while self.index < target:
            if cancelled():
                raise Superseded
            if self.manual:
                try:
                    original, region = next(self.iterator)
                except StopIteration as error:
                    raise EOFError from error
                frame = preview_size(original)
                quad = None
                if region is not None:
                    quad = region if self.spec.planar else box_corners(region)
                    quad = quad * (frame.shape[1] / original.shape[1], frame.shape[0] / original.shape[0])
                    quad = np.float32(quad)
                self.effect.apply(frame, quad, self.spec.planar)
            else:
                ok, original = self.capture.read()
                if not ok:
                    raise EOFError
                frame = preview_size(original)
                if self.auto:
                    self.raw = frame
                    self.tracks = self.tracker.update(frame) if self.track else ()
                    frame = paint_scene(frame, self.tracks, self.spec.look, self.index + 1,
                                        self.fps, self.tracker.crop_ids if self.track else None)
                elif self.dots is not None:
                    frame = self.dots.frame(frame)
            self.index += 1
            self.last = frame
            if self.manual and self.index < target and self.index % 12 == 0:
                progress(self.index, target)
        return self.last


class PreviewWorker:
    """Keep at most one pending request and one open video decoder."""

    def __init__(self):
        self.condition = Condition()
        self.replies = Queue()
        self.pending = None
        self.serial = 0
        self.closed = False
        Thread(target=self.run, daemon=True, name="Nexus preview").start()

    def request(self, command, *args):
        with self.condition:
            self.serial += 1
            self.pending = (self.serial, command, args)
            self.condition.notify()
            return self.serial

    def invalidate(self):
        with self.condition:
            self.serial += 1
            self.pending = None

    def stop(self):
        with self.condition:
            self.closed = True
            self.condition.notify()

    def run(self):
        stream = None
        try:
            while True:
                with self.condition:
                    self.condition.wait_for(lambda: self.pending is not None or self.closed)
                    if self.closed:
                        return
                    token, command, args = self.pending
                    self.pending = None

                def cancelled():
                    with self.condition:
                        return self.closed or self.serial != token

                def report(index, target):
                    self.replies.put((token, "progress", (index, target)))

                try:
                    if command == "reset":
                        if stream is not None:
                            stream.close()
                            stream = None
                        continue
                    if command == "open":
                        if stream is not None:
                            stream.close()
                            stream = None
                        result = inspect_clip(args[0])
                    else:
                        spec, frame = args
                        if stream is not None and stream.spec != spec and not stream.retune(spec):
                            stream.close()
                            stream = None
                        if stream is None:
                            stream = Stream(spec)
                        result = frame, stream.frame_at(frame, cancelled, report)
                except Superseded:
                    continue
                except EOFError:
                    self.replies.put((token, "end", None))
                except Exception as error:
                    if stream is not None:
                        stream.close()
                        stream = None
                    self.replies.put((token, "error", str(error) or "Unknown video error."))
                else:
                    if not cancelled():
                        self.replies.put((token, command, result))
        finally:
            if stream is not None:
                stream.close()
