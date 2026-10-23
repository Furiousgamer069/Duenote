"""Safe photo loading: size limits, corrupt-file handling, EXIF rotation, resizing."""
import hashlib
import io

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_BYTES = 15 * 1024 * 1024      # 15 MB upload limit
MAX_PIXELS = 40_000_000           # refuse decompression bombs
MODEL_LONG_SIDE = 1600            # measured: Gemma reads both sample pages correctly at this size


class ImageProblem(Exception):
    pass


def load_photo(data):
    """bytes -> (RGB PIL image, page_id). Raises ImageProblem with a friendly message."""
    if not data:
        raise ImageProblem("The file is empty.")
    if len(data) > MAX_BYTES:
        raise ImageProblem(f"Photo is too large ({len(data) // 1_000_000} MB). Limit is 15 MB.")
    try:
        probe = Image.open(io.BytesIO(data))
        if probe.width * probe.height > MAX_PIXELS:
            raise ImageProblem("Photo has too many pixels. Please use a normal phone photo.")
        probe.verify()
        image = Image.open(io.BytesIO(data))
        image = ImageOps.exif_transpose(image).convert("RGB")
    except ImageProblem:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as e:
        raise ImageProblem("This file isn't a readable photo (it may be corrupted).") from e
    return image, page_id_for(data)


def page_id_for(data):
    return "p-" + hashlib.sha256(data).hexdigest()[:12]


def for_model(image):
    """Shrink so the longest side is at most MODEL_LONG_SIDE (keeps aspect ratio)."""
    image = image.copy()
    image.thumbnail((MODEL_LONG_SIDE, MODEL_LONG_SIDE))
    return image


def rotate(image, degrees):
    return image.rotate(-degrees, expand=True)
