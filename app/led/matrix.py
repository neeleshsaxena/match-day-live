from __future__ import annotations

import os
from pathlib import Path

from PIL import Image

from .canvas import HEIGHT, WIDTH

PREVIEW_PATH = Path(os.environ.get("LED_PREVIEW_PATH", "/tmp/led-preview.png"))
PREVIEW_SCALE = int(os.environ.get("LED_PREVIEW_SCALE", "8"))


class PNGSink:
    """Dev sink: writes each frame as a scaled-up PNG so it's visible in a browser.

    Uses write-then-rename so a polling browser never reads a half-written file.
    """

    def __init__(self, path: Path = PREVIEW_PATH, scale: int = PREVIEW_SCALE):
        self.path = path
        self.tmp_path = path.with_suffix(path.suffix + ".tmp")
        self.scale = scale
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def display(self, img: Image.Image) -> None:
        if self.scale != 1:
            img = img.resize((WIDTH * self.scale, HEIGHT * self.scale), Image.NEAREST)
        img.save(self.tmp_path, format="PNG")
        os.replace(self.tmp_path, self.path)


class HzellerSink:
    """Pi sink: pushes frames to the HUB75 panel via rpi-rgb-led-matrix."""

    def __init__(self) -> None:
        from rgbmatrix import RGBMatrix, RGBMatrixOptions

        opts = RGBMatrixOptions()
        opts.rows = HEIGHT
        opts.cols = WIDTH
        opts.chain_length = 1
        opts.parallel = 1
        opts.hardware_mapping = "adafruit-hat"
        opts.gpio_slowdown = int(os.environ.get("LED_GPIO_SLOWDOWN", "2"))
        opts.brightness = int(os.environ.get("LED_BRIGHTNESS", "60"))
        self.matrix = RGBMatrix(options=opts)

    def display(self, img: Image.Image) -> None:
        self.matrix.SetImage(img.convert("RGB"))


def get_sink():
    """Auto-detect: hzeller on Pi (if rgbmatrix installed), PNG sink otherwise."""
    if os.environ.get("LED_SINK") == "png":
        return PNGSink()
    try:
        import rgbmatrix  # noqa: F401
    except ImportError:
        return PNGSink()
    return HzellerSink()
