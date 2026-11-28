"""Apply a monochrome ordered dither to a local video."""

import argparse
import math
import os
from pathlib import Path
import tempfile

import cv2
import numpy as np

from nexus_video import H264Writer, verify_h264


BAYER = np.array(
    [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]],
    dtype=np.uint8,
) * 16 + 8


def apply_filter(source, destination):
    if not source.is_file():
        raise ValueError(f"Video file does not exist: {source}")
    if destination.suffix.lower() != ".mp4":
        raise ValueError("The output filename must end in .mp4.")
    if destination.exists() or destination.is_symlink():
        raise ValueError(f"Output already exists: {destination}")

    capture = cv2.VideoCapture(str(source))
    temporary = None
    try:
        ok, frame = capture.read()
        if not ok:
            raise ValueError(f"Could not decode the first frame: {source}")
        fps = capture.get(cv2.CAP_PROP_FPS)
        if not math.isfinite(fps) or fps <= 0:
            raise ValueError("Could not determine the source frame rate.")

        height, width = frame.shape[:2]
        padded_width = width + width % 2
        padded_height = height + height % 2
        threshold = np.tile(BAYER, ((height + 3) // 4, (width + 3) // 4))
        threshold = threshold[:height, :width]

        with tempfile.NamedTemporaryFile(
            dir=destination.parent, suffix=".mp4", delete=False
        ) as stream:
            temporary = Path(stream.name)

        size = padded_width, padded_height
        count = 0
        with H264Writer(temporary, fps, size) as writer:
            while ok:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                dithered = (gray > threshold).astype(np.uint8) * 255
                dithered = cv2.copyMakeBorder(
                    dithered, 0, padded_height - height,
                    0, padded_width - width, cv2.BORDER_REPLICATE,
                )
                writer.write(cv2.cvtColor(dithered, cv2.COLOR_GRAY2BGR))
                count += 1
                ok, frame = capture.read()
            writer.finish()

        verify_h264(temporary, count, size, fps)
        # On Windows rename fails if another file now occupies the destination.
        os.rename(temporary, destination)
        return count
    finally:
        capture.release()
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path, help="source video")
    parser.add_argument("--output", type=Path, help="destination MP4")
    args = parser.parse_args()
    output = args.output or args.video.with_name(f"{args.video.stem}-dithered.mp4")
    try:
        count = apply_filter(args.video, output)
    except (ValueError, OSError, cv2.error) as error:
        parser.exit(1, f"Filter failed: {error}\n")
    print(f"Saved {count} frames to {output}")


if __name__ == "__main__":
    main()
