"""Tests for ImageEditTool (M10 Photo edit skill / tool).
Validates image inspection, resize, crop, grayscale, filter adjustment,
format conversion, and background removal fallback without external dependencies.
"""
from __future__ import annotations

from pathlib import Path
from PIL import Image
import pytest

from app.schemas.approvals import PermissionLevel
from app.tools.context import ToolContext
from app.tools.errors import ToolValidationError
from app.tools_builtin.image_edit_tool import ImageEditTool


@pytest.fixture
def sample_image(tmp_path: Path) -> Path:
    img_path = tmp_path / "test_input.png"
    img = Image.new("RGB", (100, 100), color="blue")
    # Add a red square in the center
    for x in range(30, 70):
        for y in range(30, 70):
            img.putpixel((x, y), (255, 0, 0))
    img.save(img_path, format="PNG")
    return img_path


@pytest.mark.asyncio
async def test_image_inspect(sample_image: Path, tmp_path: Path):
    tool = ImageEditTool()
    assert tool.permission_for({"action": "inspect"}) == PermissionLevel.L0
    ctx = ToolContext(task_id="t1", permission_level=PermissionLevel.L0, allowed_roots=(tmp_path,))
    res = await tool.execute({"action": "inspect", "input_path": str(sample_image)}, ctx)
    assert res.success is True
    assert res.structured_output["width"] == 100
    assert res.structured_output["height"] == 100


@pytest.mark.asyncio
async def test_image_resize(sample_image: Path, tmp_path: Path):
    tool = ImageEditTool()
    assert tool.permission_for({"action": "resize"}) == PermissionLevel.L1
    out_path = tmp_path / "resized.png"
    ctx = ToolContext(task_id="t1", permission_level=PermissionLevel.L1, allowed_roots=(tmp_path,))
    res = await tool.execute({
        "action": "resize",
        "input_path": str(sample_image),
        "output_path": str(out_path),
        "width": 50,
        "height": 50,
        "keep_aspect": False,
    }, ctx)
    assert res.success is True
    assert out_path.exists()
    with Image.open(out_path) as img:
        assert img.size == (50, 50)


@pytest.mark.asyncio
async def test_image_crop(sample_image: Path, tmp_path: Path):
    tool = ImageEditTool()
    out_path = tmp_path / "cropped.png"
    ctx = ToolContext(task_id="t1", permission_level=PermissionLevel.L1, allowed_roots=(tmp_path,))
    res = await tool.execute({
        "action": "crop",
        "input_path": str(sample_image),
        "output_path": str(out_path),
        "left": 30,
        "top": 30,
        "right": 70,
        "bottom": 70,
    }, ctx)
    assert res.success is True
    with Image.open(out_path) as img:
        assert img.size == (40, 40)


@pytest.mark.asyncio
async def test_image_grayscale(sample_image: Path, tmp_path: Path):
    tool = ImageEditTool()
    out_path = tmp_path / "gray.png"
    ctx = ToolContext(task_id="t1", permission_level=PermissionLevel.L1, allowed_roots=(tmp_path,))
    res = await tool.execute({
        "action": "grayscale",
        "input_path": str(sample_image),
        "output_path": str(out_path),
    }, ctx)
    assert res.success is True
    with Image.open(out_path) as img:
        assert img.mode == "L"


@pytest.mark.asyncio
async def test_image_format_conversion(sample_image: Path, tmp_path: Path):
    tool = ImageEditTool()
    out_path = tmp_path / "converted.jpg"
    ctx = ToolContext(task_id="t1", permission_level=PermissionLevel.L1, allowed_roots=(tmp_path,))
    res = await tool.execute({
        "action": "convert",
        "input_path": str(sample_image),
        "output_path": str(out_path),
        "target_format": "JPEG",
    }, ctx)
    assert res.success is True
    with Image.open(out_path) as img:
        assert img.format == "JPEG"


@pytest.mark.asyncio
async def test_image_remove_background_fallback(sample_image: Path, tmp_path: Path):
    tool = ImageEditTool()
    out_path = tmp_path / "nobg.png"
    ctx = ToolContext(task_id="t1", permission_level=PermissionLevel.L1, allowed_roots=(tmp_path,))
    res = await tool.execute({
        "action": "remove_background",
        "input_path": str(sample_image),
        "output_path": str(out_path),
    }, ctx)
    assert res.success is True
    with Image.open(out_path) as img:
        assert img.mode == "RGBA"
