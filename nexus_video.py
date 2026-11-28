"""H.264 MP4 export using the local FFmpeg encoder."""

from fractions import Fraction
import math
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryFile

import cv2
import numpy as np


def ffmpeg_path():
    if getattr(sys, "frozen", False):
        bundled = Path(sys._MEIPASS) / "ffmpeg.exe"
        if bundled.is_file():
            return str(bundled)
    local = Path(__file__).resolve().parent / ".nexus-runtime" / "ffmpeg"
    binary = local / "ffmpeg-9.1-essentials_build" / "bin" / "ffmpeg.exe"
    if binary.is_file():
        return str(binary)
    available = shutil.which("ffmpeg")
    if available:
        return available
    raise ValueError("The H.264 encoder is missing. Open the current Nexus executable with FFmpeg included.")


class H264Writer:
    def __init__(self, path, fps, size):
        width, height = size
        rate = str(Fraction(fps).limit_denominator(100000))
        self.shape = height, width, 3
        self.command = [
            ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-nostdin", "-xerror", "-y",
            "-f", "rawvideo", "-pixel_format", "bgr24", "-video_size", f"{width}x{height}",
            "-framerate", rate, "-i", "pipe:0", "-map", "0:v:0", "-an",
            "-filter_threads", "2", "-vf", "scale=out_color_matrix=bt709,format=yuv420p",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-threads", "4",
            "-profile:v", "high", "-pix_fmt", "yuv420p", "-tag:v", "avc1",
            "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
            "-movflags", "+faststart", str(path),
        ]
        self.path = path
        self.process = None
        self.errors = None

    def __enter__(self):
        self.errors = TemporaryFile(dir=self.path.parent)
        try:
            self.process = subprocess.Popen(
                self.command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=self.errors,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as error:
            self.errors.close()
            raise ValueError("Could not start the H.264 encoder.") from error
        return self

    def failure(self):
        self.errors.seek(0)
        lines = self.errors.read(4096).decode(errors="replace").splitlines()
        detail = " ".join(line.strip() for line in lines if line.strip())
        return ValueError(f"H.264 export failed. {detail}" if detail else "H.264 export failed.")

    def write(self, frame):
        if frame.dtype != np.uint8 or frame.shape != self.shape:
            raise ValueError("The rendered frame does not match the export size or pixel format.")
        try:
            self.process.stdin.write(memoryview(np.ascontiguousarray(frame)).cast("B"))
        except (BrokenPipeError, OSError) as error:
            raise self.failure() from error

    def finish(self, cancel=None):
        try:
            self.process.stdin.close()
        except (BrokenPipeError, OSError) as error:
            raise self.failure() from error
        while self.process.poll() is None:
            if cancel is not None and cancel.is_set():
                return False
            try:
                self.process.wait(timeout=.2)
            except subprocess.TimeoutExpired:
                continue
        if self.process.returncode:
            raise self.failure()
        return True

    def __exit__(self, *_):
        process = self.process
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        finally:
            try:
                process.stdin.close()
            except OSError:
                pass
            self.errors.close()


def verify_h264(path, count, size, fps):
    capture = cv2.VideoCapture(str(path))
    try:
        tag = (int(capture.get(cv2.CAP_PROP_FOURCC)) & 0xffffffff).to_bytes(4, "little").lower()
        dimensions = tuple(round(capture.get(k)) for k in (cv2.CAP_PROP_FRAME_WIDTH, cv2.CAP_PROP_FRAME_HEIGHT))
        frames = round(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        rate = capture.get(cv2.CAP_PROP_FPS)
        if (tag not in {b"h264", b"avc1"} or dimensions != size or frames != count or count < 1
                or not math.isclose(rate, fps, abs_tol=.001) or not capture.read()[0]):
            raise ValueError("The H.264 video did not pass verification.")
        if count > 1:
            capture.set(cv2.CAP_PROP_POS_FRAMES, count - 1)
            if not capture.read()[0]:
                raise ValueError("Could not decode the final frame of the H.264 export.")
    finally:
        capture.release()
