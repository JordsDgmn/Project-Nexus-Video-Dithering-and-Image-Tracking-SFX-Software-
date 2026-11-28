"""Rendering jobs, export, and preset storage for Entropy."""

from dataclasses import asdict
import json
import os
from pathlib import Path
from queue import Empty, Full, Queue
import tempfile
from threading import Condition, Thread
from time import perf_counter
import traceback

import cv2

from entropy_engine import ExportSpec, Look, Simulator


class Cancelled(Exception):
    pass


def seconds_label(seconds):
    if seconds is None:
        return "—"
    if seconds < 1:
        return "<1 s"
    minutes, seconds = divmod(round(seconds), 60)
    return f"{minutes:d}m {seconds:02d}s" if minutes else f"{seconds:d} s"


class PreviewWorker:
    """One renderer, one latest request, and one latest reply."""

    def __init__(self):
        self.changed = Condition()
        self.pending = None
        self.closed = False
        self.results = Queue(maxsize=1)
        self.thread = Thread(target=self.run, daemon=True, name="Entropy preview")
        self.thread.start()

    def request(self, ticket, size, phase, look):
        with self.changed:
            self.pending = (ticket, size, phase, look)
            self.changed.notify()

    def close(self):
        with self.changed:
            self.closed = True
            self.pending = None
            self.changed.notify()

    def run(self):
        simulator = None
        previous = None
        while True:
            with self.changed:
                self.changed.wait_for(lambda: self.pending is not None or self.closed)
                if self.closed:
                    return
                ticket, size, phase, look = self.pending
                self.pending = None
            now = perf_counter()
            try:
                if previous != size:
                    simulator = Simulator(size)
                    previous = size
                frame = simulator.frame(phase, look)
                result = (ticket, size, frame, perf_counter() - now, None)
            except Exception as error:
                result = (ticket, size, None, perf_counter() - now,
                          (str(error) or type(error).__name__, traceback.format_exc()))
            try:
                self.results.put_nowait(result)
            except Full:
                try:
                    self.results.get_nowait()
                except Empty:
                    pass
                self.results.put_nowait(result)


def frame_at(simulator, index, spec, look):
    frame = simulator.frame(index / spec.frames, look)
    if spec.internal != spec.size:
        frame = cv2.resize(frame, spec.size, interpolation=cv2.INTER_LINEAR)
    return cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)


def estimate(look, spec):
    look.validate()
    spec.validate()
    start = perf_counter()
    simulator = Simulator(spec.internal)
    setup = perf_counter() - start
    indices = (0, spec.frames // 3, 2 * spec.frames // 3)
    start = perf_counter()
    for index in indices:
        frame_at(simulator, index, spec, look)
    rate = len(indices) / (perf_counter() - start)
    return setup + spec.frames / rate, rate


def export_clip(path, look, spec, cancel, report):
    look.validate()
    spec.validate()
    if path.suffix.lower() != ".mp4":
        raise ValueError("Choose an .mp4 filename.")
    if path.exists() or path.is_symlink():
        raise ValueError("A file with that name already exists. Choose a new name.")
    if not path.parent.is_dir():
        raise ValueError("The output folder does not exist.")
    if cancel.is_set():
        raise Cancelled

    start = perf_counter()
    with tempfile.TemporaryDirectory(prefix=".entropy-", dir=path.parent) as folder:
        temporary = Path(folder) / "loop.mp4"
        writer = cv2.VideoWriter(str(temporary), cv2.VideoWriter_fourcc(*"mp4v"), spec.fps, spec.size)
        try:
            if not writer.isOpened():
                raise ValueError("Could not start the MP4 encoder.")
            simulator = Simulator(spec.internal)
            for index in range(spec.frames):
                if cancel.is_set():
                    raise Cancelled
                writer.write(frame_at(simulator, index, spec, look))
                count = index + 1
                if count < 3 or count % 4 == 0 or count == spec.frames:
                    report("render", count, spec.frames, perf_counter() - start)
        finally:
            writer.release()
        report("verify", spec.frames, spec.frames, perf_counter() - start)
        if cancel.is_set():
            raise Cancelled
        capture = cv2.VideoCapture(str(temporary))
        try:
            dimensions = tuple(round(capture.get(key)) for key in (cv2.CAP_PROP_FRAME_WIDTH, cv2.CAP_PROP_FRAME_HEIGHT))
            count = round(capture.get(cv2.CAP_PROP_FRAME_COUNT))
            ok, _ = capture.read()
            if not ok or dimensions != spec.size or count != spec.frames:
                raise ValueError("The encoded video did not pass verification.")
            capture.set(cv2.CAP_PROP_POS_FRAMES, spec.frames - 1)
            if not capture.read()[0]:
                raise ValueError("Could not read the end of the video.")
        finally:
            capture.release()
        if cancel.is_set():
            raise Cancelled
        # The Windows rename operation also protects against a race with another export.
        temporary.rename(path)
    return perf_counter() - start


def save_preset(path, look, export):
    look.validate()
    export.validate()
    body = {"version": 1, "look": asdict(look), "export": asdict(export)}
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", delete=False, dir=path.parent,
                                         prefix=".entropy-", suffix=".json", encoding="utf-8") as stream:
            temporary = Path(stream.name)
            json.dump(body, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def load_preset(path):
    with path.open(encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("This file is not an Entropy preset.")
    try:
        return Look(**data["look"]).validate(), ExportSpec(**data["export"]).validate()
    except (TypeError, KeyError) as error:
        raise ValueError("The preset contains unknown settings.") from error
