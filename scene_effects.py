"""Scene-wide tracking graphics for automatic video looks."""

from collections import deque
from dataclasses import dataclass
from math import hypot

import cv2
import numpy as np

from blob_detection import BlobTracker, Region
from graphic_looks import paint_graphics
from graphics_settings import GRAPHIC_MODES, Graphics


CCTV = "CCTV collage"
WEB = "Signal web"
ARCHIVE = "Amber archive"
THERMAL = "Thermal scan"
POETIC = "Poetic traces"
SCENE_MODES = (*GRAPHIC_MODES, CCTV, WEB, ARCHIVE, THERMAL, POETIC)
PHRASES = (
    "A trace of motion", "The light moves on", "Still in view",
    "Where the frame ends", "A moment held", "Between two signals",
    "The shape of passing", "Almost out of sight",
)
PALETTES = {
    ARCHIVE: ((18, 6, 20), (35, 20, 83), (25, 59, 160), (54, 125, 228), (163, 234, 255)),
    THERMAL: ((24, 8, 5), (113, 46, 18), (203, 132, 48), (254, 226, 155), (245, 255, 245)),
    POETIC: ((3, 12, 3), (23, 52, 9), (52, 101, 46), (122, 173, 135), (184, 227, 225)),
}
FLOW = dict(winSize=(21, 21), maxLevel=2)
LUTS = {
    mode: np.array([
        np.interp(np.arange(256), np.linspace(0, 255, len(colors)),
                  [color[channel] for color in colors])
        for channel in range(3)
    ]).T.astype(np.uint8)
    for mode, colors in PALETTES.items()
}


@dataclass
class Point:
    id: int
    position: np.ndarray
    smooth: np.ndarray
    size: float
    trail: deque


class SceneTracker:
    def __init__(self, density, look=None):
        self.points = []
        self.previous = None
        self.crop_ids = [None, None]
        self.next_id = 1
        self.count = 0
        self.config = Graphics()
        self.blobs = None
        self.last_detection = -1000
        self.configure(density, look)

    def configure(self, density, look):
        self.config = look.graphics if look is not None else Graphics()
        self.limit = look.max_boxes if look is not None else 9 + density * 2
        self.minimum = look.min_boxes if look is not None else min(12, self.limit)
        self.response = look.tracking_speed if look is not None else 65
        self.alpha = .20 + .80 * self.response / 100
        self.reseed_interval = self.config.interval
        self.spacing = max(6, min(38 - density, round(105 / self.limit ** .5)))
        self.points = self.points[:self.limit]

    def update(self, frame):
        height, width = frame.shape[:2]
        scale = min(1., 640 / max(height, width))
        size = (max(1, round(width * scale)), max(1, round(height * scale)))
        image = cv2.resize(frame, size, interpolation=cv2.INTER_AREA) if size != (width, height) else frame
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        inverse = np.float32((width / size[0], height / size[1]))
        if self.config.detector != "Features":
            if self.blobs is None:
                self.blobs = BlobTracker()
            return [transform_track(region, inverse) for region in
                    self.blobs.update(gray, self.config, self.limit, self.response)]

        if self.points and self.previous is not None:
            positions = np.float32([point.position for point in self.points]).reshape(-1, 1, 2)
            moved, good, _ = cv2.calcOpticalFlowPyrLK(self.previous, gray, positions, None, **FLOW)
            survivor = []
            if moved is not None:
                backward, status, _ = cv2.calcOpticalFlowPyrLK(gray, self.previous, moved, None, **FLOW)
                if backward is not None:
                    error = np.linalg.norm((backward - positions)[:, 0], axis=1)
                    for point, target, valid in zip(
                            self.points, moved[:, 0], (error < 1.65) & good.ravel() & status.ravel()):
                        if valid and 3 <= target[0] < size[0] - 3 and 3 <= target[1] < size[1] - 3:
                            point.position = target
                            point.smooth = self.alpha * target + (1 - self.alpha) * point.smooth
                            point.trail.append(point.smooth.copy())
                            survivor.append(point)
            self.points = survivor

        if self.count - self.last_detection >= self.reseed_interval and len(self.points) < self.limit:
            self.last_detection = self.count
            spacing = max(self.spacing, round(min(size) * self.config.spacing / 100))
            quality = .003 + (self.config.threshold / 254) ** 2.25 * .92
            mask = np.full(gray.shape, 255, dtype=np.uint8)
            border = min(14, max(3, min(size) // 12))
            mask[:border] = mask[-border:] = 0
            mask[:, :border] = mask[:, -border:] = 0
            for point in self.points:
                cv2.circle(mask, tuple(np.rint(point.position).astype(int)), spacing, 0, -1)
            corners = cv2.goodFeaturesToTrack(
                gray, maxCorners=self.limit - len(self.points), qualityLevel=quality,
                minDistance=spacing, mask=mask,
            )
            self.add_points(corners)
            if len(self.points) < self.minimum:
                spacing = max(4, spacing // 2)
                mask.fill(255)
                mask[:border] = mask[-border:] = 0
                mask[:, :border] = mask[:, -border:] = 0
                for point in self.points:
                    cv2.circle(mask, tuple(np.rint(point.position).astype(int)), spacing, 0, -1)
                self.add_points(cv2.goodFeaturesToTrack(
                    gray, maxCorners=self.minimum - len(self.points), qualityLevel=quality,
                    minDistance=spacing, mask=mask,
                ))

        self.count += 1
        self.previous = gray
        return [
            transform_track(Region(point.id, point.smooth, point.size, np.array(point.trail),
                                   np.float32((2 * point.size, 1.6 * point.size))), inverse)
            for point in self.points
        ]


    def add_points(self, points):
        if points is None:
            return
        for position in points[:, 0]:
            radius = 9 + (self.next_id * 13) % 23
            self.points.append(Point(self.next_id, position.copy(), position.copy(),
                                     radius, deque([position.copy()], maxlen=12)))
            self.next_id += 1


def transform_track(track, factors):
    return Region(track.id, track.position * factors, track.size * float(np.mean(factors)),
                  track.trail * factors, track.extent * factors)


def grade(frame, mode, tick):
    if mode == CCTV:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        subdued = cv2.addWeighted(frame, .78, cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR), .22, 0)
        subdued[::3] = cv2.convertScaleAbs(subdued[::3], alpha=.87)
        return subdued
    if mode == WEB:
        return cv2.convertScaleAbs(frame, alpha=.23)

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    if mode == ARCHIVE:
        exposed = cv2.convertScaleAbs(gray, alpha=1.45, beta=0)
        grain = np.random.default_rng(tick // 2).integers(-17, 18, gray.shape, dtype=np.int16)
        exposed = np.clip(exposed.astype(np.int16) + grain, 0, 255).astype(np.uint8)
        return LUTS[mode][exposed]
    result = LUTS[mode][gray]
    result[(tick % 3)::3] = cv2.convertScaleAbs(result[(tick % 3)::3], alpha=.86)
    return result


def label(image, text, point, color, scale, chip=False, italic=False):
    height, width = image.shape[:2]
    face = cv2.FONT_HERSHEY_SIMPLEX | (cv2.FONT_ITALIC if italic else 0)
    (tw, th), _ = cv2.getTextSize(text, face, scale, 1)
    x = min(max(3, point[0]), max(3, width - tw - 6))
    y = min(max(th + 3, point[1]), height - 4)
    if chip:
        cv2.rectangle(image, (x - 2, y - th - 3), (x + tw + 3, y + 3), color, -1)
        color = (14, 20, 23)
    else:
        cv2.putText(image, text, (x, y), face, scale, (10, 16, 19), 2, cv2.LINE_AA)
    cv2.putText(image, text, (x, y), face, scale, color, 1, cv2.LINE_AA)


def linked_pairs(tracks, mode, dimensions):
    if len(tracks) < 2:
        return set()
    if mode == POETIC:
        order = sorted(range(len(tracks)), key=lambda index: tracks[index][1][1])
        return set(zip(order, order[1:]))
    spread = hypot(*dimensions) * (.55 if mode == WEB else .30)
    positions = np.float32([track[1] for track in tracks])
    pairs = set()
    for index, target in enumerate(positions):
        distances = np.linalg.norm(positions - target, axis=1)
        neighbors = np.argsort(distances)[1:3 if mode == WEB else 2]
        for neighbor in neighbors:
            if 0 < distances[neighbor] < spread:
                pairs.add(tuple(sorted((index, int(neighbor)))))
        if mode == WEB and index % 4 == 0:
            far = np.flatnonzero((distances > spread * .4) & (distances < spread))
            if len(far):
                neighbor = int(far[tracks[index][0] % len(far)])
                pairs.add(tuple(sorted((index, neighbor))))
    return pairs


def crop_windows(image, source, tracks, tone, font, unit, anchors):
    height, width = image.shape[:2]
    if width < 200 or height < 160:
        return
    view_w = round(width * (.23 if height >= width else .15))
    view_h = round(view_w * .78)
    margin = max(9, round(min(height, width) * .05))
    zones = ((width - margin - view_w, round(height * .18)), (margin, round(height * .68)))
    sorted_tracks = sorted(tracks, key=lambda item: item[0])
    used = set()
    for index, (x, y) in enumerate(zones):
        if len(sorted_tracks) <= index:
            break
        side = width * (.35 if index == 0 else .65)
        available = {track[0]: track for track in sorted_tracks if track[0] not in used}
        anchor = available.get(anchors[index])
        if anchor is None:
            anchor = min(available.values(),
                         key=lambda item: hypot((item[1][0] - side) * .6, item[1][1] - y))
        identity, center, radius, _, _ = anchor
        anchors[index] = identity
        used.add(identity)
        px, py = np.rint(center).astype(int)
        crop = max(12, round(radius * 1.35))
        patch = source[max(0, py-crop):min(height, py+crop), max(0, px-crop):min(width, px+crop)]
        if not patch.size:
            continue
        tile = cv2.cvtColor(cv2.resize(patch, (view_w, view_h)), cv2.COLOR_BGR2GRAY)
        tile = cv2.convertScaleAbs(tile, alpha=1.2, beta=-8)
        image[y:y+view_h, x:x+view_w] = tile[:, :, None]
        anchor_x = x if px < x else x + view_w - 1
        cv2.line(image, (px, py), (anchor_x, y), tone, unit, cv2.LINE_AA)
        cv2.rectangle(image, (x, y), (x + view_w - 1, y + view_h - 1), tone, unit, cv2.LINE_AA)
        label(image, f"DETAIL / {identity:03d}", (x + 2, y - 5), tone, font, chip=True)


def paint_scene(frame, tracks, look, index, fps, crop_ids=None):
    if not look.opacity:
        return frame
    if look.mode in GRAPHIC_MODES:
        return paint_graphics(frame, tracks, look, index)
    height, width = frame.shape[:2]
    unit = max(1, round(min(height, width) / 660))
    font = max(.3, min(height, width) / 1650)
    mode = look.mode
    tint = tuple(bytes.fromhex(look.tint[1:])[::-1])
    pale = tuple(int(v * .30 + 178) for v in tint)
    tick = index * look.animation_speed / 100
    image = grade(frame, mode, int(tick))
    pairs = linked_pairs(tracks, mode, (width, height)) if look.links else ()
    for left, right in pairs:
        off = tracks[left][1]
        end = tracks[right][1]
        if mode == CCTV:
            line = np.stack((off, (end[0], off[1]), end))
        elif mode in (POETIC, ARCHIVE):
            line = np.stack((off, end))
        else:
            mid = (off + end) / 2
            bend = 0.16 * (end - off)[::-1] * (1, -1)
            control = mid + bend
            segments = np.linspace(0, 1, 9)[:, None]
            line = (1-segments)**2 * off + 2*(1-segments)*segments*control + segments**2*end
        tone = tuple(int(v * (.63 if mode == WEB else .71)) for v in pale)
        if mode == ARCHIVE:
            delta = end - off
            length = max(1, round(np.linalg.norm(delta)))
            offset = int(tick * 1.6) % (13 * unit)
            for step in range(offset, length, 13 * unit):
                a = np.rint(off + delta * (step / length)).astype(int)
                b = np.rint(off + delta * (min(length, step + 5 * unit) / length)).astype(int)
                cv2.line(image, tuple(a), tuple(b), pale, unit, cv2.LINE_AA)
        else:
            cv2.polylines(image, [np.rint(line).astype(np.int32)], False, tone, unit, cv2.LINE_AA)
            if mode in (WEB, CCTV) and tracks[left][0] % 4 == 0:
                phase = ((tick * .038) + tracks[left][0] * .17) % 1
                point = np.rint(off * (1 - phase) + end * phase).astype(int)
                cv2.circle(image, tuple(point), 2 * unit, tint, -1, cv2.LINE_AA)

    for identity, position, radius, trail, _ in tracks:
        x, y = np.rint(position).astype(int)
        size = max(4, round(radius * (.55 if mode == WEB else .93)))
        ratio = 0.65 + ((identity * 7) % 6) * .16
        span = max(4, round(size * ratio))
        x1, y1, x2, y2 = x-size, y-span, x+size, y+span
        if look.trails and mode == WEB and len(trail) > 2:
            cv2.polylines(image, [np.rint(trail).astype(np.int32)], False, tint, unit, cv2.LINE_AA)
        if mode in (WEB, CCTV) and identity % 3 != 0:
            arm = max(3, size // 3)
            for px, py, sx, sy in ((x1,y1,1,1), (x2,y1,-1,1), (x2,y2,-1,-1), (x1,y2,1,-1)):
                cv2.line(image, (px, py), (px+arm*sx, py), tint, unit, cv2.LINE_AA)
                cv2.line(image, (px, py), (px, py+arm*sy), tint, unit, cv2.LINE_AA)
        else:
            cv2.rectangle(image, (x1, y1), (x2, y2), tint, unit, cv2.LINE_AA)
        cv2.circle(image, (x, y), unit + 1, pale, unit, cv2.LINE_AA)
        if mode == THERMAL:
            value = frame[y, x].mean() if 0 <= x < width and 0 <= y < height else 0
            text = f"L{value:03.0f}"
        elif mode == POETIC:
            text = PHRASES[(identity // 3) % len(PHRASES)] if identity % 3 == 0 else f"{identity:03d}"
        elif mode in (CCTV, ARCHIVE):
            text = f"OBJECT {identity:03d}"
        else:
            text = f"{identity:03d}/{x:04d}.{y:04d}"
        if look.labels and (mode != WEB or identity % 2 == 0):
            label(image, text, (x1, y1 - 5), tint, font, chip=mode in (CCTV, ARCHIVE),
                  italic=mode == POETIC)

    if mode == CCTV:
        if look.crops:
            crop_windows(image, frame, tracks, tint, font, unit,
                         crop_ids if crop_ids is not None else [None, None])
        margin = max(6, round(min(height, width) * .026))
        cv2.rectangle(image, (margin, margin), (width-margin-1, height-margin-1),
                      pale, unit, cv2.LINE_AA)
        seconds = int(index / fps)
        label(image, "CAM 01 / TRACK", (margin*2, margin*2 + 12), pale, font*1.2)
        label(image, f"{seconds//60:02d}:{seconds%60:02d}  F{index:05d}",
              (width - margin*2 - round(170*font), margin*2 + 12), pale, font*1.05)
        label(image, f"REGIONS {len(tracks):02d}", (margin*2, height-margin*2), pale, font*1.2)

    if mode == ARCHIVE:
        margin = max(8, round(min(height, width) * .035))
        bottom = height - margin
        top = bottom - max(16, round(height * .034))
        cv2.rectangle(image, (margin, top), (width - margin, bottom), (21, 17, 35), -1)
        label(image, "FIELD RECORD / MOTION", (margin + 7, bottom - 7), tint, font*1.2)
        label(image, f"{len(tracks):02d} REGIONS", (width - margin - round(220*font), bottom - 7),
              pale, font)
    if look.opacity == 100:
        return image
    return cv2.addWeighted(image, look.opacity/100, frame, 1-look.opacity/100, 0)
