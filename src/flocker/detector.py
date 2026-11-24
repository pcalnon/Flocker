"""Train YOLO detectors for players and the ball with Ultralytics.

Project: Flocker
File: src/flocker/detector.py
Purpose: fine-tune a COCO-pretrained YOLO on flocker.yolo_dataset tiles, with settings suited to top-down video
Author: Paul Calnon
Created: 2026-11-24
License: CC0 1.0 (see LICENSE); Ultralytics is AGPL-3.0, which matters only if software built on it is distributed

Two Ultralytics behaviours are pinned down here:
- When it checks a dataset, Ultralytics downloads Arial.ttf from its GitHub assets unless an Arial font is
  installed (none is on this host). use_bundled_font() points its font lookup at the DejaVu Sans that matplotlib
  ships, so training downloads nothing.
- Its run folders default to a path relative to the working directory, so train() always passes an absolute project
  folder.

Augmentation: the camera looks straight down, so vertical flips are as valid as horizontal ones (flipud 0.5);
rotation stays off because boxes are axis-aligned; scale jitter is kept to +/-25 % because inference runs at the
training scale.
"""

from pathlib import Path

TRAIN_DEFAULTS = {"imgsz": 1280, "epochs": 40, "batch": 8, "workers": 8, "seed": 0, "patience": 15, "flipud": 0.5, "fliplr": 0.5, "degrees": 0.0, "scale": 0.25, "mosaic": 1.0, "close_mosaic": 10, "cache": False, "plots": True}


def use_bundled_font() -> Path:
    """Make Ultralytics use matplotlib's DejaVu Sans instead of downloading Arial.ttf; return the font path."""
    import matplotlib
    import ultralytics.data.utils as data_utils
    import ultralytics.utils.checks as checks
    import ultralytics.utils.plotting as plotting

    font = Path(matplotlib.get_data_path()) / "fonts" / "ttf" / "DejaVuSans.ttf"
    if not font.is_file():
        raise FileNotFoundError(font)

    def check_font(font_name: str = "Arial.ttf") -> Path:
        return font

    for module in (checks, data_utils, plotting):
        if hasattr(module, "check_font"):
            module.check_font = check_font
    return font


def train(data_yaml: str | Path, project: str | Path, name: str, model: str | Path, device: int | str = 0, **overrides) -> Path:
    """Fine-tune ``model`` on ``data_yaml``; return the path of the best weights."""
    use_bundled_font()
    from ultralytics import YOLO

    model_path = Path(model).resolve()
    if not model_path.is_file():
        raise FileNotFoundError(f"{model_path}: pass a local weights file (Ultralytics would otherwise download one)")
    args = {**TRAIN_DEFAULTS, **overrides, "data": str(Path(data_yaml).resolve()), "project": str(Path(project).resolve()), "name": name, "exist_ok": False, "device": device}
    yolo = YOLO(str(model_path))
    yolo.train(**args)
    return Path(yolo.trainer.save_dir) / "weights" / "best.pt"
