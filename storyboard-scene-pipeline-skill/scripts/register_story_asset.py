#!/usr/bin/env python3

from __future__ import annotations

import argparse
from io import BytesIO
import re
import shutil
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
    slugify,
    write_bytes_atomic,
    write_text_atomic,
)


ASSET_TYPES = {"line-art", "final-frame"}
DEFAULT_LINE_ART_LONG_EDGE = 1536
DEFAULT_FINAL_FRAME_LONG_EDGE = 2048


def shot_slug(shot_id: str) -> str:
    match = re.fullmatch(r"\s*shot\s*0*(\d+)\s*", shot_id, flags=re.IGNORECASE)
    if match:
        return f"shot{int(match.group(1)):02d}"
    return slugify(shot_id)


def parse_aspect_ratio(value: object) -> tuple[int, int]:
    text = str(value or "16:9").strip().lower().replace("x", ":")
    match = re.match(r"^(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)$", text)
    if not match:
        return 16, 9
    width = float(match.group(1))
    height = float(match.group(2))
    if width <= 0 or height <= 0:
        return 16, 9
    scale = 1000
    return max(1, round(width * scale)), max(1, round(height * scale))


def target_size(aspect_ratio: object, long_edge: int) -> tuple[int, int]:
    ratio_w, ratio_h = parse_aspect_ratio(aspect_ratio)
    if ratio_w >= ratio_h:
        width = long_edge
        height = round(long_edge * ratio_h / ratio_w)
    else:
        height = long_edge
        width = round(long_edge * ratio_w / ratio_h)
    return max(1, width), max(1, height)


def convert_image(source: Path, target: Path, size: tuple[int, int], normalize: bool) -> tuple[int, int]:
    try:
        from PIL import Image, ImageOps
    except Exception as exc:  # pragma: no cover - depends on host image libs
        raise StoryboardError(
            problem="缺少图片处理库",
            reason=f"无法导入 Pillow: {exc}",
            next_step="使用带 Pillow 的 Python 运行环境，或先手动把源图转为 JPG 后再登记。",
        ) from exc

    try:
        image = Image.open(source)
        image = ImageOps.exif_transpose(image).convert("RGB")
    except Exception as exc:
        raise StoryboardError(
            problem="源图片无法读取",
            reason=f"无法打开图片: {source} ({exc})",
            next_step="确认 --source 指向真实 PNG/JPG/WebP 图片，而不是聊天中的预览或不存在的路径。",
        ) from exc

    target.parent.mkdir(parents=True, exist_ok=True)

    if normalize:
        canvas_w, canvas_h = size
        scale = min(canvas_w / image.width, canvas_h / image.height)
        resized_size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
        image = image.resize(resized_size, Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (canvas_w, canvas_h), (255, 255, 255))
        canvas.paste(image, ((canvas_w - resized_size[0]) // 2, (canvas_h - resized_size[1]) // 2))
        image = canvas

    output = BytesIO()
    image.save(output, "JPEG", quality=92, optimize=True)
    write_bytes_atomic(target, output.getvalue())
    return image.size


def normalize_asset_path(session_path: Path, target: Path) -> str:
    try:
        return target.resolve().relative_to(session_path.parent.resolve()).as_posix()
    except ValueError:
        return str(target.resolve())


def gallery_section(asset_type: str) -> str:
    return "line_art" if asset_type == "line-art" else "final_generation"


def default_output_name(shot_id: str, asset_type: str) -> str:
    suffix = "line" if asset_type == "line-art" else "final"
    return f"{shot_slug(shot_id)}-{suffix}.jpg"


def default_label(shot_id: str, asset_type: str) -> str:
    suffix = "Line Draft" if asset_type == "line-art" else "Final"
    return f"{shot_id} {suffix}"


def known_shot_ids(state: dict[str, object]) -> set[str]:
    shots = state.get("shots", [])
    if not isinstance(shots, list):
        return set()
    return {str(shot.get("id", "")).strip() for shot in shots if isinstance(shot, dict) and str(shot.get("id", "")).strip()}


def update_gallery(
    state: dict[str, object],
    asset_type: str,
    shot_id: str,
    asset_path: str,
    label: str,
    note: str,
    expected_shot_ids: set[str],
) -> None:
    section_name = gallery_section(asset_type)
    section = state.setdefault(section_name, {})
    if not isinstance(section, dict):
        raise StoryboardError(
            problem="Session 结构错误",
            reason=f"{section_name} 不是 JSON object。",
            next_step="先修复 session.json，或重新初始化 session。",
        )
    gallery = section.setdefault("gallery", [])
    if not isinstance(gallery, list):
        raise StoryboardError(
            problem="Session gallery 结构错误",
            reason=f"{section_name}.gallery 不是数组。",
            next_step="先修复 gallery，再重新登记资产。",
        )

    entry = {
        "shot_id": shot_id,
        "label": label,
        "path": asset_path,
        "note": note,
    }

    for index, item in enumerate(gallery):
        if isinstance(item, dict) and str(item.get("shot_id", "")).strip() == shot_id:
            gallery[index] = entry
            break
    else:
        gallery.append(entry)

    completed_shot_ids = {
        str(item.get("shot_id", "")).strip()
        for item in gallery
        if isinstance(item, dict) and str(item.get("shot_id", "")).strip() and str(item.get("path", "")).strip()
    }
    gallery_complete = bool(expected_shot_ids) and expected_shot_ids.issubset(completed_shot_ids)

    if asset_type == "line-art":
        if gallery_complete:
            section["status"] = "line-art ready for user review"
        else:
            section["status"] = "line-art generation in progress"
    else:
        if gallery_complete:
            section["status"] = "final frames ready for user review"
        else:
            section["status"] = "final-frame generation in progress"


def main() -> int:
    parser = argparse.ArgumentParser(description="Register a generated storyboard image into a session.")
    parser.add_argument("session", help="Session directory or session.json path.")
    parser.add_argument("--source", required=True, help="Existing local source image path.")
    parser.add_argument("--shot-id", required=True, help='Shot id, for example "Shot 01".')
    parser.add_argument("--asset-type", required=True, choices=sorted(ASSET_TYPES), help="Asset gallery to update.")
    parser.add_argument("--output-name", help="Target filename inside the session assets folder.")
    parser.add_argument("--label", help="Gallery label.")
    parser.add_argument("--note", default="saved for user review", help="Compact gallery note.")
    parser.add_argument(
        "--long-edge",
        type=int,
        help="Long edge for normalized JPG output. Defaults: line-art 1536, final-frame 2048.",
    )
    parser.add_argument("--no-normalize", action="store_true", help="Do not pad/resize to the session aspect ratio.")
    parser.add_argument("--validate-profile", default="smoke", choices=("smoke", "workflow", "release"))
    parser.add_argument("--workspace-root")
    parser.add_argument("--config")
    args = parser.parse_args()

    try:
        config = resolve_workspace_config(workspace_root=args.workspace_root, config_path=args.config)
        state_path = resolve_state_path(config, args.session)
        source = Path(args.source).expanduser().resolve()
        if not source.exists() or not source.is_file():
            raise StoryboardError(
                problem="源图片不存在",
                reason=f"找不到可登记的本地图片: {source}",
                next_step="先确认图片已经真实保存到磁盘，再把该路径传给 --source。",
            )

        session_lock = acquire_session_lock(state_path)
        state = load_json(state_path)
        if not isinstance(state, dict):
            raise StoryboardError(
                problem="Session 结构错误",
                reason=f"{state_path} 不是 JSON object。",
                next_step="检查 session.json，或重新初始化 session。",
            )
        state = ensure_state_shape(state)
        shot_ids = known_shot_ids(state)
        if args.shot_id not in shot_ids:
            known = ", ".join(sorted(shot_ids)) or "none"
            raise StoryboardError(
                problem="Shot ID 不存在",
                reason=f"--shot-id {args.shot_id!r} 不在 session shots 中。已知 Shot: {known}",
                next_step="使用 session.json 里的精确 shots[].id，避免把图片登记到 HTML 不会显示的孤立 gallery 项。",
            )

        assets_dir = state_path.parent / config.assets_dirname
        output_name = args.output_name or default_output_name(args.shot_id, args.asset_type)
        target = resolve_child_path(assets_dir, output_name, "资产输出路径")
        if target.suffix.lower() not in {".jpg", ".jpeg"}:
            target = target.with_suffix(".jpg")
        asset_path = normalize_asset_path(state_path, target)
        expected_section = f"{gallery_section(args.asset_type)}.gallery"
        existing_owner = asset_path_owner(state, asset_path, expected_section, args.shot_id)
        if existing_owner:
            raise StoryboardError(
                problem="资产输出文件名冲突",
                reason=(
                    f"{asset_path} 已登记给 {existing_owner[0]} / {existing_owner[1] or 'unknown shot'}，"
                    f"不能再用于 {expected_section} / {args.shot_id}。"
                ),
                next_step="删除自定义 --output-name，或为当前 Shot 使用唯一 JPG 文件名。",
            )
        if source == target.resolve():
            temp = target.with_suffix(".register-temp.jpg")
            target_for_write = temp
        else:
            target_for_write = target

        long_edge = args.long_edge or (
            DEFAULT_LINE_ART_LONG_EDGE if args.asset_type == "line-art" else DEFAULT_FINAL_FRAME_LONG_EDGE
        )
        if long_edge <= 0 or long_edge > 16384:
            raise StoryboardError(
                problem="图片尺寸参数不合法",
                reason=f"--long-edge 必须在 1 到 16384 之间，收到 {long_edge}。",
                next_step="改用合理的正整数尺寸后重试。",
            )
        html_path = session_html_path(config, state_path)
        original_state_text = state_path.read_text(encoding="utf-8")
        original_html_text = html_path.read_text(encoding="utf-8") if html_path.exists() else None
        original_target = target.read_bytes() if target.exists() else None

        try:
            size = target_size(state.get("aspect_ratio", "16:9"), long_edge)
            width, height = convert_image(source, target_for_write, size, normalize=not args.no_normalize)
            if target_for_write != target:
                shutil.move(str(target_for_write), str(target))

            label = args.label or default_label(args.shot_id, args.asset_type)
            note = f"{args.note}; registered JPG {width}x{height}"
            update_gallery(state, args.asset_type, args.shot_id, asset_path, label, note, shot_ids)
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
            if target_for_write != target and target_for_write.exists():
                target_for_write.unlink()
            raise

        print(state_path)
        print(html_path)
        print(asset_path)
        session_lock.close()
        return 0
    except StoryboardError as error:
        print_error(error)
        return 1
    except Exception as error:  # pragma: no cover - defensive CLI fallback
        print("问题: 资产登记脚本发生未预期错误", file=sys.stderr)
        print(f"原因: {error}", file=sys.stderr)
        print("下一步: 检查 session 路径、源图片路径和参数后重试。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
