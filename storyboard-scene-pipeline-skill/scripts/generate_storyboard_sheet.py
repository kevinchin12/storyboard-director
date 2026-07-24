#!/usr/bin/env python3

from __future__ import annotations

import argparse
from io import BytesIO
import sys
from pathlib import Path

from storyboard_common import (
    StoryboardError,
    acquire_session_lock,
    asset_path_owner,
    dump_json,
    ensure_state_shape,
    load_json,
    print_error,
    resolve_child_path,
    resolve_state_path,
    resolve_workspace_config,
    run_python_script,
    session_html_path,
    shot_asset_for,
    write_bytes_atomic,
    write_text_atomic,
)


DEFAULT_OUTPUT_NAME = "storyboard-final-3col.jpg"
DEFAULT_LINE_ART_OUTPUT_NAME = "storyboard-line-3col.jpg"
DEFAULT_CELL_WIDTH = 960
DEFAULT_LABEL_HEIGHT = 56
DEFAULT_GAP = 22
DEFAULT_MARGIN = 32


def rel_asset(session_path: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return session_path.parent / path


def normalize_asset_path(session_path: Path, target: Path) -> str:
    try:
        return target.resolve().relative_to(session_path.parent.resolve()).as_posix()
    except ValueError:
        return str(target.resolve())


def fit_image(image, width: int, height: int):
    from PIL import Image

    image = image.convert("RGB")
    scale = min(width / image.width, height / image.height)
    resized = image.resize(
        (round(image.width * scale), round(image.height * scale)),
        Image.Resampling.LANCZOS,
    )
    canvas = Image.new("RGB", (width, height), (255, 255, 255))
    canvas.paste(resized, ((width - resized.width) // 2, (height - resized.height) // 2))
    return canvas


def load_font(size: int):
    from PIL import ImageFont

    candidates = (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Helvetica.ttf",
    )
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def gallery_items(state: dict[str, object], asset_type: str) -> list[dict[str, object]]:
    section_name = "line_art" if asset_type == "line-art" else "final_generation"
    section = state.get(section_name, {})
    if not isinstance(section, dict):
        return []
    gallery = section.get("gallery", [])
    if not isinstance(gallery, list):
        return []
    return [item for item in gallery if isinstance(item, dict)]


def build_sheet(
    state_path: Path,
    state: dict[str, object],
    asset_type: str,
    output_name: str,
    assets_dirname: str,
    cols: int,
    cell_width: int,
    label_height: int,
    gap: int,
    margin: int,
) -> tuple[str, tuple[int, int]]:
    try:
        from PIL import Image, ImageDraw
    except Exception as exc:
        raise StoryboardError(
            problem="缺少图片处理库",
            reason=f"无法导入 Pillow: {exc}",
            next_step="使用带 Pillow 的 Python 运行环境，或先安装 Pillow 后重试。",
        ) from exc

    shots = state.get("shots", [])
    if not isinstance(shots, list) or not shots:
        raise StoryboardError(
            problem="Session 缺少 shots",
            reason="无法从 session.json 读取镜头列表。",
            next_step="先完成 script package，再生成合并分镜图。",
        )

    gallery = gallery_items(state, asset_type)
    if not gallery:
        raise StoryboardError(
            problem="缺少可拼接资产",
            reason=f"找不到 {asset_type} gallery。",
            next_step="先生成并登记对应线稿或最终帧，再生成合并分镜图。",
        )

    sample_item = next(
        (
            item
            for index, shot in enumerate(shots)
            if isinstance(shot, dict)
            for item in [shot_asset_for(gallery, shot, index)]
            if item and str(item.get("path", "")).strip()
        ),
        None,
    )
    if sample_item is None:
        raise StoryboardError(
            problem="缺少可读取的首个分镜资产",
            reason=f"{asset_type} gallery 没有与当前 Shot ID 对应的有效路径。",
            next_step="先按精确 Shot ID 登记至少一张图片，再生成合并分镜图。",
        )
    sample_path = rel_asset(state_path, str(sample_item.get("path", "")))
    try:
        with Image.open(sample_path) as sample:
            ratio = sample.height / sample.width
    except Exception as exc:
        raise StoryboardError(
            problem="无法读取样张",
            reason=f"无法打开 {sample_path}: {exc}",
            next_step="确认 gallery 中的图片路径真实存在且为可读 JPG/PNG/WebP。",
        ) from exc

    frame_height = max(1, round(cell_width * ratio))
    rows = (len(shots) + cols - 1) // cols
    width = margin * 2 + cols * cell_width + (cols - 1) * gap
    height = margin * 2 + rows * (label_height + frame_height) + (rows - 1) * gap
    sheet = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(sheet)
    label_font = load_font(26)

    for index, shot in enumerate(shots):
        if not isinstance(shot, dict):
            continue
        shot_id = str(shot.get("id", f"Shot {index + 1:02d}")).strip()
        item = shot_asset_for(gallery, shot, index)
        if not item:
            raise StoryboardError(
                problem="分镜资产不完整",
                reason=f"{asset_type} gallery 缺少 {shot_id}。",
                next_step="先登记缺失镜头资产，再重新生成合并分镜图。",
            )
        source = rel_asset(state_path, str(item.get("path", "")))
        if not source.exists():
            raise StoryboardError(
                problem="分镜资产文件不存在",
                reason=f"{shot_id} 对应文件不存在: {source}",
                next_step="修复 gallery 路径或重新登记该镜头资产。",
            )

        col = index % cols
        row = index // cols
        x = margin + col * (cell_width + gap)
        y = margin + row * (label_height + frame_height + gap)
        draw.text((x, y + 12), shot_id, fill=(20, 20, 20), font=label_font)
        with Image.open(source) as image:
            fitted = fit_image(image, cell_width, frame_height)
        sheet.paste(fitted, (x, y + label_height))
        draw.rectangle(
            [x, y + label_height, x + cell_width - 1, y + label_height + frame_height - 1],
            outline=(220, 220, 220),
            width=1,
        )

    assets_dir = state_path.parent / assets_dirname
    assets_dir.mkdir(parents=True, exist_ok=True)
    target = resolve_child_path(assets_dir, output_name, "合并分镜图输出路径")
    if target.suffix.lower() not in {".jpg", ".jpeg"}:
        target = target.with_suffix(".jpg")
    output = BytesIO()
    sheet.save(output, "JPEG", quality=92, optimize=True)
    write_bytes_atomic(target, output.getvalue())
    return normalize_asset_path(state_path, target), sheet.size


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a 3-column storyboard sheet from registered session assets.")
    parser.add_argument("session", help="Session directory or session.json path.")
    parser.add_argument("--asset-type", choices=("line-art", "final-frame"), default="final-frame")
    parser.add_argument("--output-name")
    parser.add_argument("--cols", type=int, default=3)
    parser.add_argument("--cell-width", type=int, default=DEFAULT_CELL_WIDTH)
    parser.add_argument("--label-height", type=int, default=DEFAULT_LABEL_HEIGHT)
    parser.add_argument("--gap", type=int, default=DEFAULT_GAP)
    parser.add_argument("--margin", type=int, default=DEFAULT_MARGIN)
    parser.add_argument("--note", default="")
    parser.add_argument("--validate-profile", default="smoke", choices=("smoke", "workflow", "release"))
    parser.add_argument("--workspace-root")
    parser.add_argument("--config")
    args = parser.parse_args()

    try:
        if args.cols <= 0 or args.cell_width <= 0 or args.label_height <= 0 or args.gap < 0 or args.margin < 0:
            raise StoryboardError(
                problem="参数不合法",
                reason="--cols、--cell-width、--label-height 必须为正数；--gap 和 --margin 不能为负数。",
                next_step="改用合法整数后重试。",
            )

        config = resolve_workspace_config(workspace_root=args.workspace_root, config_path=args.config)
        state_path = resolve_state_path(config, args.session)
        session_lock = acquire_session_lock(state_path)
        state = load_json(state_path)
        if not isinstance(state, dict):
            raise StoryboardError(
                problem="Session 结构错误",
                reason=f"{state_path} 不是 JSON object。",
                next_step="检查 session.json，或重新初始化 session。",
            )
        state = ensure_state_shape(state)

        output_name = args.output_name or (
            DEFAULT_LINE_ART_OUTPUT_NAME if args.asset_type == "line-art" else DEFAULT_OUTPUT_NAME
        )
        target = resolve_child_path(state_path.parent / config.assets_dirname, output_name, "合并分镜图输出路径")
        if target.suffix.lower() not in {".jpg", ".jpeg"}:
            target = target.with_suffix(".jpg")
        target_asset_path = normalize_asset_path(state_path, target)
        existing_owner = asset_path_owner(
            state,
            target_asset_path,
            "storyboard_sheet",
            "storyboard_sheet",
        )
        if existing_owner:
            raise StoryboardError(
                problem="合并分镜图输出文件名冲突",
                reason=f"{target_asset_path} 已由 {existing_owner[0]} / {existing_owner[1]} 使用。",
                next_step="删除自定义 --output-name，或为合并分镜图使用唯一 JPG 文件名。",
            )
        html_path = session_html_path(config, state_path)
        original_state_text = state_path.read_text(encoding="utf-8")
        original_html_text = html_path.read_text(encoding="utf-8") if html_path.exists() else None
        original_target = target.read_bytes() if target.exists() else None

        try:
            asset_path, size = build_sheet(
                state_path=state_path,
                state=state,
                asset_type=args.asset_type,
                output_name=output_name,
                assets_dirname=config.assets_dirname,
                cols=args.cols,
                cell_width=args.cell_width,
                label_height=args.label_height,
                gap=args.gap,
                margin=args.margin,
            )

            label = "Final Frame Storyboard Sheet" if args.asset_type == "final-frame" else "Line Art Storyboard Sheet"
            default_note = (
                "3-column stitched JPG storyboard sheet. Shot order preserved, original frame aspect ratio preserved, "
                "no crop, white background, Shot labels only."
            )
            state["storyboard_sheet"] = {
                "label": label,
                "path": asset_path,
                "note": args.note or default_note,
            }
            dump_json(state_path, state)

            render_script = Path(__file__).resolve().parent / "render_story_session.py"
            run_python_script(render_script, ["--config", str(config.config_path), str(state_path)])

            validate_script = Path(__file__).resolve().parent / "validate_story_session.py"
            run_python_script(
                validate_script,
                ["--config", str(config.config_path), "--profile", args.validate_profile, str(state_path)],
            )
        except Exception:
            write_text_atomic(state_path, original_state_text)
            if original_html_text is None:
                if html_path.exists():
                    html_path.unlink()
            else:
                write_text_atomic(html_path, original_html_text)
            if original_target is None:
                if target.exists():
                    target.unlink()
            else:
                write_bytes_atomic(target, original_target)
            raise

        print(state_path)
        print(html_path)
        print(asset_path)
        print(f"{size[0]}x{size[1]}")
        session_lock.close()
        return 0
    except StoryboardError as error:
        print_error(error)
        return 1
    except Exception as error:
        print("问题: 生成合并分镜图发生未预期错误", file=sys.stderr)
        print(f"原因: {error}", file=sys.stderr)
        print("下一步: 检查 session.json、gallery 路径和 Pillow 环境。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
