"""Render a subject or surface track and its per-frame positions."""

from contextlib import nullcontext
import csv
import math
from pathlib import Path
import tempfile

import cv2
import numpy as np

from dots_effect import DOTS, DotsRenderer
from graphics_settings import needs_scene_tracks
from scene_effects import SCENE_MODES, SceneTracker, paint_scene, transform_track
from studio_effects import Effect, QUALITY, box_corners, surface_frames
from track import tracked_frames


class Cancelled(Exception):
    pass


def decoded_frames(capture, tracker):
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        yield frame, tracker.update(frame) if tracker is not None else None


def writes_tracking_data(look):
    return look.mode != DOTS and needs_scene_tracks(look)


def export_track(source, selection, destination, look, planar, cancel, progress, finalizing=None):
    positions = destination.with_suffix(".csv")
    if destination.suffix.lower() != ".mp4":
        raise ValueError("Save the output as an MP4 file.")
    is_dots = look.mode == DOTS
    has_data = writes_tracking_data(look)
    targets = (destination, positions) if has_data else (destination,)
    if any(path.exists() or path.is_symlink() for path in targets):
        raise ValueError("An output already exists. Choose another filename.")
    look.validate()
    automatic = look.mode in SCENE_MODES
    effect = None if automatic or is_dots else Effect(look)
    dots = DotsRenderer(look.dots) if is_dots else None
    scene = SceneTracker(look.detail, look) if automatic and has_data else None

    capture = cv2.VideoCapture(str(source))
    try:
        fps = capture.get(cv2.CAP_PROP_FPS)
        if not math.isfinite(fps) or fps <= 0:
            raise ValueError("Could not read the video's frame rate.")
        total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if width <= 0 or height <= 0:
            raise ValueError("Could not read the video's size.")
        scale = QUALITY[look.quality]
        render_size = (max(2, round(width * scale)), max(2, round(height * scale)))
        render_w, render_h = render_size
        padded_size = (render_w + render_w % 2, render_h + render_h % 2)
        factors = np.float32((render_w / width, render_h / height))
        resize = render_size != (width, height)
        pad = padded_size != render_size
        lost = set()
        count = 0
        if automatic or is_dots:
            tracks = decoded_frames(capture, scene)
        else:
            tracks = surface_frames(capture, selection) if planar else tracked_frames(
                capture, selection, max_tracking_edge=960
            )

        with tempfile.TemporaryDirectory(prefix=".nexus-", dir=destination.parent) as stage:
            preview = Path(stage) / "preview.mp4"
            data = Path(stage) / "positions.csv"
            writer = cv2.VideoWriter(str(preview), cv2.VideoWriter_fourcc(*"mp4v"), fps, padded_size)
            try:
                if not writer.isOpened():
                    raise ValueError("Could not open the MP4 encoder.")
                csv_file = data.open("w", encoding="utf-8", newline="") if has_data else nullcontext()
                with csv_file as stream:
                    rows = csv.writer(stream) if stream is not None else None
                    header = ("frame", "status", "x", "y", "width", "height")
                    corners = ("tl_x", "tl_y", "tr_x", "tr_y", "br_x", "br_y", "bl_x", "bl_y")
                    if automatic and rows is not None:
                        rows.writerow(("frame", "status", "id", "center_x", "center_y", "radius"))
                    elif rows is not None:
                        rows.writerow(header + corners if planar else header)
                    for index, (frame, region) in enumerate(tracks):
                        if cancel.is_set():
                            raise Cancelled
                        if frame.shape[:2] != (height, width):
                            raise ValueError("The video size changed during tracking.")
                        quad = None
                        if automatic and rows is not None:
                            if region:
                                for identity, center, radius, _, _ in region:
                                    rows.writerow((index, "tracked", identity,
                                                   round(float(center[0]), 2), round(float(center[1]), 2),
                                                   round(radius, 2)))
                            else:
                                lost.add(index)
                                rows.writerow((index, "lost", "", "", "", ""))
                        elif rows is None:
                            pass
                        elif region is None:
                            lost.add(index)
                            rows.writerow((index, "lost", *([""] * (12 if planar else 4))))
                        elif planar:
                            quad = region
                            rows.writerow((index, "tracked", *cv2.boundingRect(quad),
                                           *[round(float(v), 2) for v in quad.flat]))
                        else:
                            quad = box_corners(region)
                            rows.writerow((index, "tracked", *region))
                        if resize:
                            frame = cv2.resize(frame, render_size, interpolation=cv2.INTER_AREA)
                            if quad is not None:
                                quad = quad * factors
                        if automatic:
                            region = region or ()
                            if resize:
                                region = [transform_track(track, factors) for track in region]
                            frame = paint_scene(frame, region, look, index, fps,
                                                scene.crop_ids if scene is not None else None)
                        elif is_dots:
                            frame = dots.frame(frame)
                        else:
                            effect.apply(frame, quad, planar)
                        if pad:
                            frame = cv2.copyMakeBorder(frame, 0, padded_size[1] - render_h, 0,
                                                       padded_size[0] - render_w, cv2.BORDER_REPLICATE)
                        writer.write(frame)
                        count = index + 1
                        if count == 1 or count % 5 == 0:
                            progress(count, total)
            finally:
                writer.release()

            progress(count, total)
            if finalizing is not None:
                finalizing()
            check = cv2.VideoCapture(str(preview))
            try:
                if not check.read()[0] or round(check.get(cv2.CAP_PROP_FRAME_COUNT)) != count:
                    raise ValueError("The exported preview could not be verified.")
            finally:
                check.release()
            if cancel.is_set():
                raise Cancelled
            if not has_data:
                preview.rename(destination)
                return count, lost
            positions = data.rename(positions)
            try:
                preview.rename(destination)
            except OSError:
                positions.unlink()
                raise
        return count, lost
    finally:
        capture.release()
