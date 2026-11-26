"""Track one region in a local video and write its positions to CSV."""

import argparse
import csv
import os
from pathlib import Path
import tempfile

import cv2


def tracked_frames(capture, box):
    """Yield each decoded frame and its tracked box, or None on tracking loss."""
    ok, frame = capture.read()
    if not ok:
        raise ValueError("Could not decode the first video frame.")
    x, y, width, height = box
    frame_height, frame_width = frame.shape[:2]
    if (
        x < 0 or y < 0 or width <= 0 or height <= 0
        or x + width > frame_width or y + height > frame_height
    ):
        raise ValueError(
            f"The starting box must fit inside the {frame_width}x{frame_height} first frame."
        )

    tracker = cv2.TrackerCSRT_create()
    if tracker.init(frame, tuple(box)) is False:
        raise ValueError("Could not initialize the tracker with the starting box.")
    yield frame, tuple(box)

    while True:
        ok, frame = capture.read()
        if not ok:
            break
        found, region = tracker.update(frame)
        yield frame, region if found else None


def track(video, box, output):
    if not video.is_file():
        raise ValueError(f"Video file does not exist: {video}")
    if video.resolve() == output.resolve() or (
        output.exists() and video.samefile(output)
    ):
        raise ValueError("The CSV output must be separate from the source video.")

    capture = cv2.VideoCapture(str(video))
    temporary = None
    try:
        frames = tracked_frames(capture, box)
        first = next(frames)
        with tempfile.NamedTemporaryFile(
            mode="w", newline="", encoding="utf-8",
            dir=output.parent, prefix=".nexus-", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            writer = csv.writer(stream)
            writer.writerow(("frame", "status", "x", "y", "width", "height"))
            writer.writerow((0, "tracked", *first[1]))
            count = 1
            lost = 0
            for _, region in frames:
                if region is None:
                    writer.writerow((count, "lost", "", "", "", ""))
                    lost += 1
                else:
                    writer.writerow((count, "tracked", *region))
                count += 1

        os.replace(temporary, output)
        return count, lost
    finally:
        capture.release()
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path, help="source video")
    parser.add_argument(
        "--box", required=True, type=int, nargs=4,
        metavar=("X", "Y", "WIDTH", "HEIGHT"),
        help="starting rectangle in pixels, measured from the top-left corner",
    )
    parser.add_argument("--output", required=True, type=Path, help="destination CSV")
    args = parser.parse_args()
    try:
        count, lost = track(args.video, args.box, args.output)
    except (ValueError, OSError, cv2.error) as error:
        parser.exit(1, f"Tracking failed: {error}\n")
    print(f"Saved {count} frames ({lost} lost) to {args.output}")


if __name__ == "__main__":
    main()

