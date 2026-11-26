"""Track one region in a local video and write its positions to CSV."""

import argparse
import csv
import os
from pathlib import Path
import tempfile

import cv2


def tracked_frames(capture, box, max_tracking_edge=None):
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

    scale = 1.
    if max_tracking_edge is not None:
        # Avoid shrinking a small target below a useful size.
        scale = min(1., max(max_tracking_edge / max(frame_width, frame_height),
                           40 / min(width, height)))
    data_size = (round(frame_width * scale), round(frame_height * scale))
    ratio_x, ratio_y = data_size[0] / frame_width, data_size[1] / frame_height
    tracker = cv2.TrackerCSRT_create()
    initial = tuple(box)
    if scale < 1:
        left, top = round(x * ratio_x), round(y * ratio_y)
        initial = (left, top, max(1, round((x + width) * ratio_x) - left),
                   max(1, round((y + height) * ratio_y) - top))
        tracking_frame = cv2.resize(frame, data_size, interpolation=cv2.INTER_AREA)
    else:
        tracking_frame = frame
    if tracker.init(tracking_frame, initial) is False:
        raise ValueError("Could not initialize the tracker with the starting box.")
    yield frame, tuple(box)

    while True:
        ok, frame = capture.read()
        if not ok:
            break
        tracking_frame = cv2.resize(frame, data_size, interpolation=cv2.INTER_AREA) if scale < 1 else frame
        found, region = tracker.update(tracking_frame)
        if found and scale < 1:
            left, top, region_width, region_height = region
            x0, y0 = round(left / ratio_x), round(top / ratio_y)
            region = (x0, y0, round((left + region_width) / ratio_x) - x0,
                      round((top + region_height) / ratio_y) - y0)
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

