"""
Photo Edit & Image Manipulation Tool for VYOM.
Supports background removal, resizing, cropping, color adjustments, and format conversion
using PIL (Pillow) and optional rembg library.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from app.schemas.approvals import PermissionLevel
from app.tools.base import BaseTool, ToolMetadata
from app.tools.context import ToolContext
from app.tools.errors import ToolValidationError
from app.tools.result import EvidenceItem, ToolResult


class ImageEditTool(BaseTool):
    metadata = ToolMetadata(
        name="image_edit",
        description="Edit, crop, resize, apply filters, convert formats, or remove background from images locally.",
        category="media",
        required_permissions=[PermissionLevel.L0, PermissionLevel.L1],
        risk_level="low",
    )

    def permission_for(self, inputs: dict[str, Any]) -> PermissionLevel:
        action = str(inputs.get("action", "info")).lower()
        return PermissionLevel.L0 if action in {"info", "inspect"} else PermissionLevel.L1

    async def execute(self, inputs: dict[str, Any], context: ToolContext) -> ToolResult:
        from PIL import Image, ImageEnhance, ImageFilter, ImageOps

        action = str(inputs.get("action", "")).strip().lower()
        input_path_str = str(inputs.get("input_path", "")).strip()
        output_path_str = str(inputs.get("output_path", "")).strip()

        if not input_path_str:
            raise ToolValidationError("input_path is required for image operations.")

        input_path = Path(input_path_str).resolve()
        if not input_path.exists() or not input_path.is_file():
            raise ToolValidationError(f"Input image file not found: {input_path_str}")

        if not output_path_str:
            output_path = input_path.with_name(f"{input_path.stem}_edited{input_path.suffix or '.png'}")
        else:
            output_path = Path(output_path_str).resolve()
            output_path.parent.mkdir(parents=True, exist_ok=True)

        with Image.open(input_path) as img:
            original_size = img.size
            original_format = img.format

            if action in {"info", "inspect"}:
                info = {
                    "width": img.width,
                    "height": img.height,
                    "format": img.format,
                    "mode": img.mode,
                    "size_bytes": input_path.stat().st_size,
                }
                return ToolResult.completed(
                    f"Image info for {input_path.name}: {img.width}x{img.height}, format {img.format}",
                    output=info,
                    evidence=[EvidenceItem(type="file", summary=f"Inspected {input_path.name}", data=info)],
                )

            elif action in {"remove_background", "rembg", "bg_remove"}:
                try:
                    import rembg
                    result_img = rembg.remove(img)
                except ImportError:
                    # Fallback: create alpha mask based on corner background color
                    converted = img.convert("RGBA")
                    bg_color = converted.getpixel((0, 0))
                    datas = converted.getdata()
                    new_data = []
                    for item in datas:
                        # Match within tolerance
                        if abs(item[0] - bg_color[0]) < 25 and abs(item[1] - bg_color[1]) < 25 and abs(item[2] - bg_color[2]) < 25:
                            new_data.append((255, 255, 255, 0))
                        else:
                            new_data.append(item)
                    converted.putdata(new_data)
                    result_img = converted

                output_path = output_path.with_suffix(".png")
                result_img.save(output_path, "PNG")
                return ToolResult.completed(
                    f"Background removed successfully. Saved to: {output_path.name}",
                    output={"output_path": str(output_path), "width": result_img.width, "height": result_img.height},
                    evidence=[EvidenceItem(type="file", summary="Background removed", data={"path": str(output_path)})],
                )

            elif action in {"resize", "scale"}:
                width = int(inputs.get("width") or img.width)
                height = int(inputs.get("height") or img.height)
                keep_aspect = bool(inputs.get("keep_aspect", True))
                if keep_aspect and ("width" in inputs and "height" not in inputs):
                    ratio = width / img.width
                    height = int(img.height * ratio)
                elif keep_aspect and ("height" in inputs and "width" not in inputs):
                    ratio = height / img.height
                    width = int(img.width * ratio)

                resized = img.resize((width, height), Image.Resampling.LANCZOS)
                resized.save(output_path)
                return ToolResult.completed(
                    f"Resized image from {original_size} to {resized.size}. Saved to: {output_path.name}",
                    output={"output_path": str(output_path), "width": width, "height": height},
                    evidence=[EvidenceItem(type="file", summary="Image resized", data={"path": str(output_path)})],
                )

            elif action in {"crop"}:
                left = int(inputs.get("left", 0))
                top = int(inputs.get("top", 0))
                right = int(inputs.get("right", img.width))
                bottom = int(inputs.get("bottom", img.height))
                cropped = img.crop((left, top, right, bottom))
                cropped.save(output_path)
                return ToolResult.completed(
                    f"Cropped image to {cropped.size}. Saved to: {output_path.name}",
                    output={"output_path": str(output_path), "size": cropped.size},
                    evidence=[EvidenceItem(type="file", summary="Image cropped", data={"path": str(output_path)})],
                )

            elif action in {"grayscale", "black_and_white", "bw"}:
                gray = ImageOps.grayscale(img)
                gray.save(output_path)
                return ToolResult.completed(
                    f"Converted image to grayscale. Saved to: {output_path.name}",
                    output={"output_path": str(output_path)},
                    evidence=[EvidenceItem(type="file", summary="Converted to grayscale", data={"path": str(output_path)})],
                )

            elif action in {"adjust", "filter", "enhance"}:
                result_img = img.copy()
                if "brightness" in inputs:
                    enhancer = ImageEnhance.Brightness(result_img)
                    result_img = enhancer.enhance(float(inputs["brightness"]))
                if "contrast" in inputs:
                    enhancer = ImageEnhance.Contrast(result_img)
                    result_img = enhancer.enhance(float(inputs["contrast"]))
                if "sharpness" in inputs:
                    enhancer = ImageEnhance.Sharpness(result_img)
                    result_img = enhancer.enhance(float(inputs["sharpness"]))
                if inputs.get("blur"):
                    result_img = result_img.filter(ImageFilter.GaussianBlur(radius=float(inputs.get("blur", 2))))

                result_img.save(output_path)
                return ToolResult.completed(
                    f"Adjusted image properties. Saved to: {output_path.name}",
                    output={"output_path": str(output_path)},
                    evidence=[EvidenceItem(type="file", summary="Image adjusted", data={"path": str(output_path)})],
                )

            elif action in {"convert", "format"}:
                fmt = str(inputs.get("target_format", "PNG")).upper()
                fmt_ext = ".jpg" if fmt in {"JPEG", "JPG"} else f".{fmt.lower()}"
                target_path = output_path if output_path.suffix.lower() in {fmt_ext, f".{fmt.lower()}"} else output_path.with_suffix(fmt_ext)
                if fmt in {"JPEG", "JPG"} and img.mode in {"RGBA", "P"}:
                    converted_img = img.convert("RGB")
                else:
                    converted_img = img
                converted_img.save(target_path, format="JPEG" if fmt in {"JPEG", "JPG"} else fmt)
                return ToolResult.completed(
                    f"Converted image to {fmt}. Saved to: {target_path.name}",
                    output={"output_path": str(target_path), "format": fmt},
                    evidence=[EvidenceItem(type="file", summary=f"Converted to {fmt}", data={"path": str(target_path)})],
                )

            else:
                raise ToolValidationError(f"Unsupported image_edit action: {action}")
