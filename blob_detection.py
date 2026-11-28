"""Connected-component detection and persistent blob IDs."""

from collections import deque
from dataclasses import dataclass
from typing import NamedTuple

import cv2
import numpy as np


class Region(NamedTuple):
    id: int
    position: np.ndarray
    size: float
    trail: np.ndarray
    extent: np.ndarray


@dataclass
class Blob:
    id: int
    position: np.ndarray
    extent: np.ndarray
    velocity: np.ndarray
    smooth: np.ndarray
    trail: deque
    missed: int = 0


KERNEL = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))


class BlobTracker:
    def __init__(self):
        self.previous = None
        self.blobs = []
        self.next_id = 1
        self.count = 0
        self.last_detection = -1000
        self.scan_count = 0

    def update(self, gray, settings, limit, response):
        height, width = gray.shape
        smoothed = cv2.GaussianBlur(gray, (5, 5), 0)
        self.blobs = self.blobs[:limit]
        elapsed = self.count - self.last_detection
        if elapsed >= settings.interval:
            boxes = self.detect(smoothed, settings, limit)
            self.match(boxes, limit, max(1, min(settings.interval, elapsed)), min(height, width))
            self.last_detection = self.count
            self.scan_count += 1
        else:
            for blob in self.blobs:
                blob.position = blob.position + blob.velocity
        self.previous = smoothed
        self.count += 1

        alpha = .18 + .82 * response / 100
        for blob in self.blobs:
            blob.position = np.clip(blob.position, (0, 0), (width - 1, height - 1)).astype(np.float32)
            blob.smooth = alpha * blob.position + (1 - alpha) * blob.smooth
            blob.trail.append(blob.smooth.copy())
        return [Region(blob.id, blob.smooth, float(np.mean(blob.extent)) / 2,
                       np.array(blob.trail), blob.extent) for blob in self.blobs]

    def detect(self, image, settings, limit):
        if settings.detector == "Motion blobs":
            if self.previous is None:
                return []
            change = cv2.absdiff(image, self.previous)
            mask = cv2.compare(change, settings.threshold, cv2.CMP_GE)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, KERNEL)
        elif settings.detector == "Bright blobs":
            mask = cv2.compare(image, settings.threshold, cv2.CMP_GE)
        else:
            mask = cv2.compare(image, settings.threshold, cv2.CMP_LE)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, KERNEL)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        area = image.shape[0] * image.shape[1]
        lo, hi = (max(7, area * settings.min_size / 10000), area * settings.max_size / 10000)
        spacing = min(image.shape) * settings.spacing / 100
        candidates = []
        for contour in contours:
            if not lo <= cv2.contourArea(contour) <= hi:
                continue
            x, y, w, h = cv2.boundingRect(contour)
            center = np.float32((x + w / 2, y + h / 2))
            candidates.append((w * h, center, np.float32((w, h))))
        selected = []
        for _, center, extent in sorted(candidates, key=lambda item: -item[0]):
            if all(np.linalg.norm(center - pos) >= spacing for pos, _ in selected):
                selected.append((center, extent))
            if len(selected) >= limit:
                break
        return selected

    def match(self, candidates, limit, elapsed, frame_edge):
        pairs = []
        for i, blob in enumerate(self.blobs):
            estimate = blob.position + blob.velocity
            for j, (center, extent) in enumerate(candidates):
                dist = float(np.linalg.norm(estimate - center))
                if dist < max(frame_edge * .09, np.mean(blob.extent) * .78):
                    area_scale = (float(np.prod(extent)) + 1) / (float(np.prod(blob.extent)) + 1)
                    if .20 < area_scale < 5:
                        pairs.append((dist + abs(np.log(area_scale)) * 7, i, j))
        used_blobs, used_candidates = set(), set()
        for _, i, j in sorted(pairs):
            if i in used_blobs or j in used_candidates:
                continue
            blob = self.blobs[i]
            center, extent = candidates[j]
            previous_observation = blob.position - blob.velocity * max(0, elapsed - 1)
            motion = (center - previous_observation) / elapsed
            blob.velocity = motion * .70 + blob.velocity * .30
            blob.position = center.copy()
            blob.extent = .55 * extent + .45 * blob.extent
            blob.missed = 0
            used_blobs.add(i)
            used_candidates.add(j)
        kept = []
        for i, blob in enumerate(self.blobs):
            if i not in used_blobs:
                blob.missed += 1
                blob.velocity *= .7
            if blob.missed < 2:
                kept.append(blob)
        self.blobs = kept
        for j, (position, extent) in enumerate(candidates):
            if j in used_candidates:
                continue
            if len(self.blobs) == limit:
                break
            self.blobs.append(Blob(self.next_id, position.copy(), extent.copy(), np.zeros(2, np.float32),
                                   position.copy(), deque(maxlen=16)))
            self.next_id += 1
