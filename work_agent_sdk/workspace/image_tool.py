from __future__ import annotations

import asyncio
import base64
import io
import os
from typing import Annotated

from pydantic import Field

import work_agent_sdk.strings.workspace as strings
from work_agent_sdk.core.errors import ToolError
from work_agent_sdk.core.messages import (
    MediaPart,
    TextPart,
    ToolResult,
    image_mime_type,
)
from work_agent_sdk.core.tool import Context, Tool

# 读取的原图大小上限；缩放后的大小由模型的要求决定
MAX_IMAGE_FILE_BYTES = 20 * 1024 * 1024


class ViewImage(Tool):
    """
    让模型查看一张图片。会话有工作区时通过工作区读取，受沙箱约束；没有工作区，或 local=True 时，
    直接读取后端本机的文件，路径须为完整路径。
    """

    def __init__(self, *, local: bool = False) -> None:
        self.local = local
        super().__init__(
            self._view,
            name="view_image",
            description=self._describe,
            parallel=True,
            annotations={"read_only": True},
        )

    def __repr__(self) -> str:
        return "ViewImage(local=True)" if self.local else "ViewImage()"

    def _describe(self, ctx: Context) -> str:
        if not self.local and ctx.has_resource("workspace"):
            return strings.VIEW_IMAGE_DESCRIPTION_WORKSPACE
        return strings.VIEW_IMAGE_DESCRIPTION_LOCAL

    async def _view(
        self,
        ctx: Context,
        path: Annotated[str, Field(description=strings.VIEW_IMAGE_PATH)],
    ) -> ToolResult:
        if not ctx.model.accepts("image"):
            raise ToolError("当前模型不支持图片输入", code="unsupported")

        workspace = None if self.local else await ctx.resource("workspace")
        try:
            if workspace is not None:
                original = await workspace.files.read_file(path, MAX_IMAGE_FILE_BYTES)
            else:
                original = await asyncio.to_thread(read_local_file, path, MAX_IMAGE_FILE_BYTES)
        except FileNotFoundError:
            raise ToolError(f"文件不存在：{path}", code="not_found") from None
        except IsADirectoryError:
            raise ToolError(f"{path} 是目录，不是文件", code="not_a_file") from None
        except PermissionError:
            raise ToolError(f"没有权限读取 {path}", code="not_readable") from None
        except ValueError as error:
            raise ToolError(str(error), code="invalid_path") from None

        if image_mime_type(original) is None:
            raise ToolError(f"{path} 不是 png、jpg、gif 或 webp 格式的图片", code="not_image")

        # max_image_bytes 是 base64 编码后的大小，原图约为其 3/4
        limit = ctx.model.max_image_bytes * 3 // 4
        try:
            data, mime = await asyncio.to_thread(shrink_image, original, ctx.model.max_image_edge, limit)
        except ValueError as error:
            raise ToolError(f"{path}：{error}", code="too_large") from None

        picture = MediaPart.image(mime=mime, data=base64.b64encode(data).decode(), path=path)
        return ToolResult(
            content=[TextPart(text=strings.VIEW_IMAGE_CAPTION.format(path=path)), picture],
            data={"path": path, "mime": picture.mime},
        )


def read_local_file(path: str, max_size: int) -> bytes:
    full = os.path.expanduser(path)
    if not os.path.isabs(full):
        raise ValueError(strings.VIEW_IMAGE_NOT_ABSOLUTE.format(path=path))
    if os.path.isdir(full):
        raise IsADirectoryError(full)
    if os.path.getsize(full) > max_size:
        raise ValueError(strings.VIEW_IMAGE_FILE_TOO_LARGE.format(limit=max_size // 1_000_000))
    with open(full, "rb") as file:
        return file.read(max_size + 1)


FORMATS = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}
JPEG_QUALITIES = (85, 70, 55)


def shrink_image(data: bytes, max_edge: int, max_bytes: int) -> tuple[bytes, str]:
    mime = image_mime_type(data)
    if mime is None:
        raise ValueError("仅支持 png、jpeg、gif 和 webp 格式的图片")

    try:
        from PIL import Image
    except ImportError:
        if len(data) > max_bytes:
            raise ValueError(f"图片超过 {max_bytes // 1_000_000} MB，压缩需要安装 Pillow") from None
        return data, mime

    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            width, height = image.size
            if max(width, height) <= max_edge and len(data) <= max_bytes:
                return data, mime

            ratio = min(1.0, max_edge / max(width, height))
            picture = image.convert("RGBA" if image.mode in ("RGBA", "LA", "P") else "RGB")
    except (OSError, Image.DecompressionBombError, SyntaxError) as error:
        raise ValueError(f"图片损坏或无法解析：{error}") from None

    size = (max(1, round(width * ratio)), max(1, round(height * ratio)))
    resized = picture.resize(size, Image.LANCZOS) if size != picture.size else picture
    image_format = FORMATS.get(mime, "PNG")
    candidate = _encode(resized, image_format, None)
    if len(candidate) <= max_bytes:
        return candidate, "image/png" if image_format == "PNG" else mime

    current = resized.convert("RGB")
    for _ in range(6):
        for quality in JPEG_QUALITIES:
            candidate = _encode(current, "JPEG", quality)
            if len(candidate) <= max_bytes:
                return candidate, "image/jpeg"
        current = current.resize((max(1, current.width * 3 // 4), max(1, current.height * 3 // 4)), Image.LANCZOS)

    raise ValueError("图片压缩后仍超过大小上限")


def _encode(image, image_format: str, quality: int | None) -> bytes:
    if image_format == "JPEG" and image.mode != "RGB":
        image = image.convert("RGB")

    buffer = io.BytesIO()
    if quality is not None:
        image.save(buffer, format=image_format, quality=quality, optimize=True)
    else:
        image.save(buffer, format=image_format)

    return buffer.getvalue()
