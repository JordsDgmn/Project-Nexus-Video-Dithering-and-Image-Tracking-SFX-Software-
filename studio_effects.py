"""Configurable looks and planar tracking for Nexus."""

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re

import cv2
import numpy as np

from dither import BAYER
from scene_effects import ARCHIVE, CCTV, POETIC, SCENE_MODES, THERMAL, WEB


AUTO = "Automatic scene"
SUBJECT = "Subject box"
SURFACE = "Surface corners"
OUTLINE = "Tracking outline"
DITHER = "Ordered dither"
MOSAIC = "Pixel mosaic"
SIGNAL = "Signal grid"
ARTWORK = "Image overlay"
MODES = (*SCENE_MODES, OUTLINE, DITHER, MOSAIC, SIGNAL, ARTWORK)
QUALITY = {"Full size": 1.0, "Compact · 75%": .75, "Small · 50%": .5}


@dataclass(frozen=True)
class Look:
    mode: str = OUTLINE
    opacity: int = 100
    detail: int = 6
    tint: str = "#78EDBE"
    quality: str = "Full size"
    artwork: str = ""
    tracking_speed: int = 65
    animation_speed: int = 100
    min_boxes: int = 12
    max_boxes: int = 40
    links: bool = True
    labels: bool = True
    trails: bool = True
    crops: bool = True

    def validate(self):
        if self.mode not in MODES or self.quality not in QUALITY:
            raise ValueError("Unknown effect or export size.")
        if type(self.opacity) is not int or not 0 <= self.opacity <= 100:
            raise ValueError("Opacity must be an integer from 0 to 100.")
        if type(self.detail) is not int or not 2 <= self.detail <= 24:
            raise ValueError("Detail size must be an integer from 2 to 24.")
        if not isinstance(self.tint, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", self.tint):
            raise ValueError("Choose a six-digit tint color.")
        if not isinstance(self.artwork, str):
            raise ValueError("Invalid overlay image path.")
        for key, low, high in (
                ("tracking_speed", 0, 100), ("animation_speed", 0, 250),
                ("min_boxes", 0, 100), ("max_boxes", 1, 100)):
            value = getattr(self, key)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{key.replace('_', ' ').capitalize()} must be {low} to {high}.")
        if self.min_boxes > self.max_boxes:
            raise ValueError("Minimum boxes must be less than or equal to maximum boxes.")
        if any(type(getattr(self, field)) is not bool for field in ("links", "labels", "trails", "crops")):
            raise ValueError("Layer switches must be on or off.")
        return self


SCENE_LOOKS = {
    CCTV: Look(CCTV, 100, 9, "#B8CFED", max_boxes=27),
    WEB: Look(WEB, 100, 20, "#66E8EF", max_boxes=49),
    ARCHIVE: Look(ARCHIVE, 100, 13, "#FFF3C9", max_boxes=35),
    THERMAL: Look(THERMAL, 100, 12, "#A0F5FF", max_boxes=33),
    POETIC: Look(POETIC, 100, 9, "#EEF8D9", max_boxes=27),
}
PRESETS = {
    **SCENE_LOOKS,
    "Tracking guide": Look(),
    "Mint halftone": Look(DITHER, 92, 4, "#8AFFCA"),
    "Amber signal": Look(SIGNAL, 83, 12, "#FFC05C"),
    "Violet mosaic": Look(MOSAIC, 85, 12, "#C99AFF"),
}


def load_preset(path):
    with path.open(encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("look"), dict):
        raise ValueError("This is not a supported Nexus preset.")
    try:
        fields = dict(data["look"])
        if fields.get("mode") in SCENE_MODES and "max_boxes" not in fields:
            detail = fields.get("detail", Look().detail)
            if type(detail) is int and 2 <= detail <= 24:
                fields["max_boxes"] = 9 + detail * 2
        look = Look(**fields).validate()
    except TypeError as error:
        raise ValueError("Preset contains unknown settings.") from error
    return look


def save_preset(path, look):
    look.validate()
    with path.open("x", encoding="utf-8") as stream:
        json.dump({"version": 1, "look": asdict(look)}, stream, indent=2)
        stream.write("\n")


def load_artwork(path):
    if not path:
        raise ValueError("Choose an image for Image overlay.")
    image = cv2.imdecode(np.fromfile(Path(path), dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if image is None or min(image.shape[:2]) < 2:
        raise ValueError("Could not read the overlay image.")
    if image.dtype == np.uint16:
        image = (image >> 8).astype(np.uint8)
    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGRA)
    elif image.shape[2] == 3:
        image = cv2.cvtColor(image, cv2.COLOR_BGR2BGRA)
    elif image.shape[2] != 4:
        raise ValueError("Use a PNG or JPG overlay.")
    return image


def box_corners(box):
    x, y, w, h = box
    return np.float32(((x, y), (x + w, y), (x + w, y + h), (x, y + h)))


def valid_quad(quad):
    return (quad.shape == (4, 2) and np.isfinite(quad).all()
            and cv2.isContourConvex(quad) and cv2.contourArea(quad, oriented=True) >= 25)


def surface_frames(capture, corners):
    """Track a planar patch using optical flow and a robust perspective fit."""
    ok, frame = capture.read()
    if not ok:
        raise ValueError("Could not decode the first video frame.")
    height, width = frame.shape[:2]
    scale = min(1., 960 / max(height, width))
    size = (max(1, round(width * scale)), max(1, round(height * scale)))
    factors = np.float32((size[0] / width, size[1] / height))
    origin = np.float32(corners) * factors
    if not valid_quad(origin):
        raise ValueError("Choose four distinct corners clockwise, starting at top left.")

    def gray(current):
        if size != (width, height):
            current = cv2.resize(current, size, interpolation=cv2.INTER_AREA)
        return cv2.cvtColor(current, cv2.COLOR_BGR2GRAY)

    def features(image, polygon, existing=None):
        mask = np.zeros(image.shape, dtype=np.uint8)
        cv2.fillConvexPoly(mask, np.rint(polygon).astype(np.int32), 255)
        if existing is not None:
            for x, y in np.rint(existing.reshape(-1, 2)).astype(np.int32):
                cv2.circle(mask, (int(x), int(y)), 6, 0, -1)
        return cv2.goodFeaturesToTrack(image, maxCorners=140, qualityLevel=.012,
                                       minDistance=6, mask=mask)

    previous = gray(frame)
    points = features(previous, origin)
    if points is None or len(points) < 8:
        raise ValueError("This surface needs more visible texture. Choose a larger textured area.")
    reference = points.copy()
    yield frame, origin / factors

    while True:
        ok, frame = capture.read()
        if not ok:
            break
        quad = None
        if points is not None:
            current = gray(frame)
            moved, forward, _ = cv2.calcOpticalFlowPyrLK(previous, current, points, None)
            if moved is not None:
                backward, status, _ = cv2.calcOpticalFlowPyrLK(current, previous, moved, None)
                if backward is not None:
                    consistent = np.linalg.norm((backward - points).reshape(-1, 2), axis=1) < 1.6
                    good = consistent & forward.ravel().astype(bool) & status.ravel().astype(bool)
                    if np.count_nonzero(good) >= 6:
                        matrix, inliers = cv2.findHomography(reference[good], moved[good], cv2.RANSAC, 2.5)
                        if (matrix is not None and np.count_nonzero(inliers) >= 6
                                and abs(np.linalg.det(matrix)) > 1e-5):
                            candidate = cv2.perspectiveTransform(origin[None], matrix)[0]
                            if (valid_quad(candidate) and np.abs(candidate).max() < 4 * max(size)
                                    and cv2.contourArea(candidate) < 4 * size[0] * size[1]):
                                quad = candidate
                                keep = inliers.ravel().astype(bool)
                                points, reference = moved[good][keep], reference[good][keep]
                                if len(points) < 35:
                                    extra = features(current, quad, points)
                                    if extra is not None:
                                        back = cv2.perspectiveTransform(extra, np.linalg.inv(matrix))
                                        finite = np.isfinite(back).all(axis=(1, 2))
                                        points = np.concatenate((points, extra[finite]))
                                        reference = np.concatenate((reference, back[finite]))
            previous = current
            if quad is None:
                points = None
        yield frame, None if quad is None else quad / factors


class Effect:
    def __init__(self, look):
        self.look = look.validate()
        self.tint = np.frombuffer(bytes.fromhex(look.tint[1:])[::-1], dtype=np.uint8)
        self.art = None
        self.patch_size = None
        if look.mode == ARTWORK:
            art = load_artwork(look.artwork)
            scale = min(1., 1440 / max(art.shape[:2]))
            pixels = art.astype(np.float32) / 255
            pixels[:, :, :3] *= pixels[:, :, 3:4]
            self.art = cv2.resize(pixels, None, fx=scale, fy=scale,
                                  interpolation=cv2.INTER_AREA) if scale < 1 else pixels

    def apply(self, frame, quad, planar):
        mode = self.look.mode
        if quad is None:
            if mode == OUTLINE:
                cv2.putText(frame, "TARGET LOST", (8, 24), cv2.FONT_HERSHEY_SIMPLEX,
                            .6, (55, 85, 255), 2, cv2.LINE_AA)
            return
        if not self.look.opacity:
            return
        x, y, w, h = cv2.boundingRect(quad)
        height, width = frame.shape[:2]
        left, top, right, bottom = max(0, x), max(0, y), min(width, x + w), min(height, y + h)
        if left >= right or top >= bottom:
            return
        region = frame[top:bottom, left:right]
        local = quad - np.float32((left, top))
        pixels = np.rint(local).astype(np.int32)
        opacity = self.look.opacity / 100
        detail = self.look.detail
        if mode == OUTLINE and opacity == 1:
            cv2.polylines(region, [pixels], True, tuple(map(int, self.tint)),
                          max(1, detail // 3), cv2.LINE_AA)
            return

        if mode == OUTLINE:
            styled = region.copy()
            cv2.polylines(styled, [pixels], True, tuple(map(int, self.tint)),
                          max(1, detail // 3), cv2.LINE_AA)
            cv2.addWeighted(styled, opacity, region, 1 - opacity, 0, dst=region)
            return
        if mode == ARTWORK:
            art_h, art_w = self.art.shape[:2]
            source = box_corners((0, 0, art_w - 1, art_h - 1))
            transform = cv2.getPerspectiveTransform(source, local)
            warped = cv2.warpPerspective(self.art, transform, (right - left, bottom - top))
            alpha = warped[:, :, 3:4] * opacity
            region[:] = np.clip(warped[:, :, :3] * (opacity * 255) + region * (1 - alpha), 0, 255)
            return

        # Rectify only the selected patch for perspective-stable texture coordinates.
        if planar:
            if self.patch_size is None:
                a, b, c, d = local
                patch_w = max(2, min(width, round(max(np.linalg.norm(b - a), np.linalg.norm(c - d)))))
                patch_h = max(2, min(height, round(max(np.linalg.norm(d - a), np.linalg.norm(c - b)))))
                self.patch_size = patch_w, patch_h
            patch_w, patch_h = self.patch_size
            rectangle = box_corners((0, 0, patch_w - 1, patch_h - 1))
            forward = cv2.getPerspectiveTransform(local, rectangle)
            patch = cv2.warpPerspective(region, forward, (patch_w, patch_h),
                                        borderMode=cv2.BORDER_REPLICATE)
        else:
            patch = region
        styled = self.texture(patch)
        if planar:
            styled = cv2.warpPerspective(styled, cv2.getPerspectiveTransform(rectangle, local),
                                          (right - left, bottom - top))
            mask = np.zeros(region.shape[:2], dtype=np.uint8)
            cv2.fillConvexPoly(mask, pixels, 255)
            mixed = cv2.addWeighted(styled, opacity, region, 1 - opacity, 0)
            cv2.copyTo(mixed, mask, region)
        else:
            cv2.addWeighted(styled, opacity, region, 1 - opacity, 0, dst=region)

    def texture(self, patch):
        height, width = patch.shape[:2]
        detail = self.look.detail
        if self.look.mode == MOSAIC:
            small = cv2.resize(patch, (max(1, width // detail), max(1, height // detail)),
                               interpolation=cv2.INTER_AREA)
            tiled = cv2.resize(small, (width, height), interpolation=cv2.INTER_NEAREST)
            color = np.broadcast_to(self.tint, tiled.shape).copy()
            return cv2.addWeighted(tiled, .84, color, .16, 0)

        gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
        if self.look.mode == DITHER:
            spacing = max(1, detail // 2)
            rows = (np.arange(height) // spacing) % 4
            cols = (np.arange(width) // spacing) % 4
            level = np.where(gray > BAYER[rows[:, None], cols], 255, 22).astype(np.uint8)
        else:
            soft = cv2.GaussianBlur(gray, (3, 3), 0)
            edges = cv2.Canny(soft, 35, 100)
            level = np.maximum(gray // 3, edges)
            level[::detail, :] = np.maximum(level[::detail, :], 95)
            level[:, ::detail] = np.maximum(level[:, ::detail], 72)
            level[2::4] //= 2
        return ((level[:, :, None].astype(np.uint16) * self.tint) // 255).astype(np.uint8)
