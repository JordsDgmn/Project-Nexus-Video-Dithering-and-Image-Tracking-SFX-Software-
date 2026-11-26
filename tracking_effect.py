"""Render a track and its per-frame positions from a local clip."""

import csv
import math
from pathlib import Path
import tempfile

import cv2
import numpy as np

from dither import BAYER
from track import tracked_frames


TRACKING_BOX = "Tracking box"
TRACKED_DITHER = "Dither follows target"


class Cancelled(Exception):
    pass


def draw_effect(frame, box, mode):
    if box is None:
        if mode == TRACKING_BOX:
            cv2.putText(frame, "TARGET LOST", (8, 24), cv2.FONT_HERSHEY_SIMPLEX,
                        0.6, (55, 85, 255), 2, cv2.LINE_AA)
        return
    x, y, w, h = box
    height, width = frame.shape[:2]
    left, top = max(0, x), max(0, y)
    right, bottom = min(width, x + w), min(height, y + h)
    if left >= right or top >= bottom:
        return
    if mode == TRACKING_BOX:
        cv2.rectangle(frame, (left, top), (right - 1, bottom - 1), (110, 245, 160), 2)
        return
    region = frame[top:bottom, left:right]
    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    rows = (np.arange(top, bottom) - y) % 4
    cols = (np.arange(left, right) - x) % 4
    mask = (gray > BAYER[rows[:, None], cols]).astype(np.uint8) * 255
    region[:] = mask[:, :, None]


def export_track(source, box, destination, mode, cancel, progress):
    positions = destination.with_suffix(".csv")
    if destination.suffix.lower() != ".mp4":
        raise ValueError("Save the output as an MP4 file.")
    if any(path.exists() or path.is_symlink() for path in (destination, positions)):
        raise ValueError("The MP4 or CSV already exists. Choose another filename.")
    if mode not in (TRACKING_BOX, TRACKED_DITHER):
        raise ValueError("Choose a tracking effect.")

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
        padded_width, padded_height = width + width % 2, height + height % 2
        lost = set()
        count = 0

        with tempfile.TemporaryDirectory(prefix=".nexus-", dir=destination.parent) as stage:
            preview = Path(stage) / "preview.mp4"
            data = Path(stage) / "positions.csv"
            writer = cv2.VideoWriter(str(preview), cv2.VideoWriter_fourcc(*"mp4v"),
                                     fps, (padded_width, padded_height))
            try:
                if not writer.isOpened():
                    raise ValueError("Could not open the MP4 encoder.")
                with data.open("w", encoding="utf-8", newline="") as stream:
                    rows = csv.writer(stream)
                    rows.writerow(("frame", "status", "x", "y", "width", "height"))
                    for index, (frame, region) in enumerate(tracked_frames(capture, box)):
                        if cancel.is_set():
                            raise Cancelled
                        if frame.shape[:2] != (height, width):
                            raise ValueError("The video size changed during tracking.")
                        if region is None:
                            lost.add(index)
                            rows.writerow((index, "lost", "", "", "", ""))
                        else:
                            rows.writerow((index, "tracked", *region))
                        draw_effect(frame, region, mode)
                        writer.write(cv2.copyMakeBorder(
                            frame, 0, padded_height - height, 0, padded_width - width,
                            cv2.BORDER_REPLICATE,
                        ))
                        count = index + 1
                        if count == 1 or count % 5 == 0:
                            progress(count, total)
            finally:
                writer.release()

            check = cv2.VideoCapture(str(preview))
            try:
                if not check.read()[0] or round(check.get(cv2.CAP_PROP_FRAME_COUNT)) != count:
                    raise ValueError("The exported preview could not be verified.")
            finally:
                check.release()
            if cancel.is_set():
                raise Cancelled
            # Windows rename refuses to overwrite if a destination was created during tracking.
            positions = data.rename(positions)
            try:
                preview.rename(destination)
            except OSError:
                positions.unlink()
                raise
        return count, lost
    finally:
        capture.release()
