"""Reusable image utilities built on OpenCV and NumPy.

This module is independent of DeepFace, recognition and database code. It also
defines ``BoundingBox``, the shared geometry type used by detection, tracking
and drawing.

Conventions:
    * Images are OpenCV-style ``uint8`` arrays of shape ``(H, W, 3)`` in BGR
      channel order unless a function says otherwise.
    * Functions named ``draw_*`` modify the image IN PLACE and return it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

import cv2
import numpy as np
import numpy.typing as npt

Image = npt.NDArray[np.uint8]
Color = tuple[int, int, int]

COLOR_KNOWN: Final[Color] = (0, 200, 0)  # BGR green
COLOR_UNKNOWN: Final[Color] = (0, 0, 255)  # BGR red
COLOR_NEUTRAL: Final[Color] = (255, 160, 0)  # BGR blue-ish
COLOR_TEXT: Final[Color] = (255, 255, 255)


class InvalidImageError(ValueError):
    """Raised when image data is missing, corrupted, or has an unusable shape."""


# ----------------------------------------------------------------------
# Geometry
# ----------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class BoundingBox:
    """Axis-aligned box in pixel coordinates (top-left origin)."""

    x: int
    y: int
    width: int
    height: int

    @property
    def x2(self) -> int:
        """Right edge (exclusive)."""
        return self.x + self.width

    @property
    def y2(self) -> int:
        """Bottom edge (exclusive)."""
        return self.y + self.height

    @property
    def area(self) -> int:
        """Box area in pixels (0 for degenerate boxes)."""
        return max(self.width, 0) * max(self.height, 0)

    def to_xyxy(self) -> tuple[int, int, int, int]:
        """Return ``(x1, y1, x2, y2)``."""
        return self.x, self.y, self.x2, self.y2

    def iou(self, other: BoundingBox) -> float:
        """Intersection-over-Union with another box, in ``[0, 1]``."""
        ix1, iy1 = max(self.x, other.x), max(self.y, other.y)
        ix2, iy2 = min(self.x2, other.x2), min(self.y2, other.y2)
        inter = max(ix2 - ix1, 0) * max(iy2 - iy1, 0)
        union = self.area + other.area - inter
        return inter / union if union > 0 else 0.0

    def clamp(self, image_width: int, image_height: int) -> BoundingBox | None:
        """Clip the box to the image. Returns None if nothing remains."""
        x1, y1 = max(self.x, 0), max(self.y, 0)
        x2, y2 = min(self.x2, image_width), min(self.y2, image_height)
        if x2 <= x1 or y2 <= y1:
            return None
        return BoundingBox(x1, y1, x2 - x1, y2 - y1)

    def expand(
        self, margin_ratio: float, image_width: int, image_height: int
    ) -> BoundingBox | None:
        """Grow the box by ``margin_ratio`` of its size per side, then clamp."""
        dx = int(self.width * margin_ratio)
        dy = int(self.height * margin_ratio)
        grown = BoundingBox(
            self.x - dx, self.y - dy, self.width + 2 * dx, self.height + 2 * dy
        )
        return grown.clamp(image_width, image_height)


# ----------------------------------------------------------------------
# Validation / decoding
# ----------------------------------------------------------------------
def validate_image(image: object) -> None:
    """Raise ``InvalidImageError`` unless ``image`` is a usable BGR frame."""
    if not isinstance(image, np.ndarray):
        raise InvalidImageError("Image must be a NumPy array")
    if image.size == 0:
        raise InvalidImageError("Image is empty")
    if image.dtype != np.uint8:
        raise InvalidImageError(f"Image dtype must be uint8, got {image.dtype}")
    if image.ndim != 3 or image.shape[2] != 3:
        raise InvalidImageError(
            f"Image must have shape (H, W, 3), got {tuple(image.shape)}"
        )


def is_valid_image(image: object) -> bool:
    """Boolean form of :func:`validate_image`."""
    try:
        validate_image(image)
    except InvalidImageError:
        return False
    return True


def decode_image_bytes(data: bytes) -> Image:
    """Decode uploaded bytes (JPEG, PNG, ...) into a BGR image.

    Raises:
        InvalidImageError: If the bytes are empty or not a decodable image.
    """
    if not data:
        raise InvalidImageError("Empty image data")
    buffer = np.frombuffer(data, dtype=np.uint8)
    try:
        image = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
    except cv2.error as exc:
        raise InvalidImageError("Image data could not be decoded") from exc
    if image is None:
        raise InvalidImageError("Image data could not be decoded")
    validate_image(image)
    return image


# ----------------------------------------------------------------------
# Disk I/O (byte-based so non-ASCII paths also work on Windows)
# ----------------------------------------------------------------------
def read_image(path: str | Path) -> Image:
    """Read an image file from disk as a BGR array."""
    file_path = Path(path)
    try:
        data = np.fromfile(file_path, dtype=np.uint8)
    except OSError as exc:
        raise InvalidImageError(f"Cannot read image file: {file_path}") from exc
    return decode_image_bytes(data.tobytes())


def write_image(
    path: str | Path, image: Image, *, quality: int = 95, create_dirs: bool = True
) -> Path:
    """Encode and write an image to disk; the format follows the suffix.

    A missing suffix defaults to ``.jpg``.
    """
    validate_image(image)
    file_path = Path(path)
    if not file_path.suffix:
        file_path = file_path.with_suffix(".jpg")
    if create_dirs:
        file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(encode_image(image, file_path.suffix, quality=quality))
    return file_path


def encode_image(image: Image, extension: str = ".jpg", *, quality: int = 90) -> bytes:
    """Encode an image (e.g. for an API response). ``extension`` like ``.jpg``."""
    validate_image(image)
    ext = extension if extension.startswith(".") else f".{extension}"
    params: list[int] = []
    if ext.lower() in (".jpg", ".jpeg"):
        params = [cv2.IMWRITE_JPEG_QUALITY, int(quality)]
    try:
        ok, encoded = cv2.imencode(ext, image, params)
    except cv2.error as exc:
        raise InvalidImageError(f"Cannot encode image as '{ext}'") from exc
    if not ok:
        raise InvalidImageError(f"Cannot encode image as '{ext}'")
    return encoded.tobytes()


# ----------------------------------------------------------------------
# Transformations
# ----------------------------------------------------------------------
def resize_max_side(image: Image, max_side: int) -> tuple[Image, float]:
    """Downscale so the longest side is at most ``max_side`` (aspect preserved).

    Never upscales. Returns ``(image, scale)`` where ``scale <= 1``; when no
    resize is needed the SAME array is returned (no copy) with ``scale == 1.0``.
    Divide detected coordinates by ``scale`` to map them back to the original.
    """
    validate_image(image)
    if max_side <= 0:
        raise ValueError("max_side must be positive")
    height, width = image.shape[:2]
    longest = max(height, width)
    if longest <= max_side:
        return image, 1.0
    scale = max_side / longest
    new_size = (max(int(round(width * scale)), 1), max(int(round(height * scale)), 1))
    return cv2.resize(image, new_size, interpolation=cv2.INTER_AREA), scale


def bgr_to_rgb(image: Image) -> Image:
    """Convert BGR to RGB (returns a new array)."""
    validate_image(image)
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


def rgb_to_bgr(image: Image) -> Image:
    """Convert RGB to BGR (returns a new array)."""
    validate_image(image)
    return cv2.cvtColor(image, cv2.COLOR_RGB2BGR)


def to_grayscale(image: Image) -> npt.NDArray[np.uint8]:
    """Convert a BGR image to single-channel grayscale."""
    validate_image(image)
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def crop_face(image: Image, bbox: BoundingBox, margin_ratio: float = 0.0) -> Image:
    """Crop ``bbox`` (optionally enlarged by ``margin_ratio``) from ``image``.

    The box is clamped to the image. The result is contiguous (a small copy of
    only the crop), so it stays valid after the source frame is reused.

    Raises:
        InvalidImageError: If the box lies outside the image.
    """
    validate_image(image)
    height, width = image.shape[:2]
    region = bbox.expand(margin_ratio, width, height)
    if region is None:
        raise InvalidImageError("Bounding box lies outside the image")
    x1, y1, x2, y2 = region.to_xyxy()
    return np.ascontiguousarray(image[y1:y2, x1:x2])


# ----------------------------------------------------------------------
# Drawing (in place)
# ----------------------------------------------------------------------
def _draw_text_box(
    image: Image, text: str, origin: tuple[int, int], color: Color, scale: float = 0.55
) -> None:
    """Draw text on a filled background whose bottom-left is ``origin``."""
    font = cv2.FONT_HERSHEY_SIMPLEX
    (text_w, text_h), baseline = cv2.getTextSize(text, font, scale, 1)
    img_h, img_w = image.shape[:2]
    x = min(max(origin[0], 0), max(img_w - text_w - 4, 0))
    y = min(max(origin[1], text_h + 4), img_h - baseline - 1)
    cv2.rectangle(
        image, (x, y - text_h - 4), (x + text_w + 4, y + baseline), color, cv2.FILLED
    )
    cv2.putText(image, text, (x + 2, y - 2), font, scale, COLOR_TEXT, 1, cv2.LINE_AA)


def draw_bounding_box(
    image: Image, bbox: BoundingBox, color: Color = COLOR_NEUTRAL, thickness: int = 2
) -> Image:
    """Draw a face rectangle in place."""
    validate_image(image)
    cv2.rectangle(image, (bbox.x, bbox.y), (bbox.x2, bbox.y2), color, thickness)
    return image


def draw_track_id(
    image: Image, bbox: BoundingBox, track_id: int, color: Color = COLOR_NEUTRAL
) -> Image:
    """Draw ``ID <n>`` above the box (in place). Track IDs are not person IDs."""
    validate_image(image)
    _draw_text_box(image, f"ID {track_id}", (bbox.x, bbox.y), color)
    return image


def draw_identity_label(
    image: Image, bbox: BoundingBox, label: str, color: Color = COLOR_NEUTRAL
) -> Image:
    """Draw an identity label below the box (in place)."""
    validate_image(image)
    _draw_text_box(image, label, (bbox.x, bbox.y2 + 18), color)
    return image


def annotate_face(
    image: Image,
    bbox: BoundingBox,
    *,
    track_id: int | None = None,
    label: str | None = None,
    matched: bool | None = None,
) -> Image:
    """Draw box, optional track ID and optional label with match-based color."""
    color = (
        COLOR_NEUTRAL
        if matched is None
        else (COLOR_KNOWN if matched else COLOR_UNKNOWN)
    )
    draw_bounding_box(image, bbox, color)
    if track_id is not None:
        draw_track_id(image, bbox, track_id, color)
    if label:
        draw_identity_label(image, bbox, label, color)
    return image