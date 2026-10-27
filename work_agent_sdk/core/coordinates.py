from __future__ import annotations

from typing import Any

from work_agent_sdk.core.model import ModelCapabilities


def model_space(model: ModelCapabilities, image_size: tuple[int, int]) -> tuple[int, int]:
    space = model.screen_coordinates
    return (int(space[0]), int(space[1])) if space else (int(image_size[0]), int(image_size[1]))


def to_image(point: Any, space: tuple[int, int], image_size: tuple[int, int]) -> tuple[float, float]:
    x, y = point
    return float(x) * image_size[0] / space[0], float(y) * image_size[1] / space[1]


def to_model(point: Any, space: tuple[int, int], image_size: tuple[int, int]) -> tuple[int, int]:
    x, y = point
    return round(float(x) * space[0] / image_size[0]), round(float(y) * space[1] / image_size[1])


__all__ = ["model_space", "to_image", "to_model"]
