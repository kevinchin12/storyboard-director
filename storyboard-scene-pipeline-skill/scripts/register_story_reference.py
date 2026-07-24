#!/usr/bin/env python3

from __future__ import annotations

import argparse
from contextlib import closing
from io import BytesIO
import sys
from pathlib import Path

from storyboard_common import (
    StoryboardError,
    acquire_session_lock,
    asset_path_owner,
    dump_json,
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


REFERENCE_TYPES = {"character", "scene", "style"}
DEFAULT_LONG_EDGE = 2048


def convert_reference(source: Path, target: Path, long_edge: int) -> tuple[int, int]:
    try:
        from PIL import Image, ImageOps
    except Exception as exc:  # pragma: no cover - depends on host image libs
        raise StoryboardError(
            "缺少图片处理库",
            f"无法导入 Pillow: {exc}",
            "运行 `python3 -m pip install -r requirements.txt` 后重试。",
        ) from exc

    try:
        image = ImageOps.exif_transpose(Image.open(source)).convert("RGB")
    except Exception as exc:
        raise StoryboardError(
            "参考图无法读取",
            f"无法打开图片: {source} ({exc})",
            "确认 --source 指向真实 PNG/JPG/WebP 文件。",
        ) from exc

    if max(image.size) > long_edge:
        image.thumbnail((long_edge, long_edge), Image.Resampling.LANCZOS)
    output = BytesIO()
    image.save(output, "JPEG", quality=92, optimize=True)
    write_bytes_atomic(target, output.getvalue())
    return image.size


def reference_list(state: dict[str, object], reference_type: str) -> list[dict[str, object]]:
    if reference_type in {"character", "scene"}:
        visual = state.setdefault("visual_references", {})
        if not isinstance(visual, dict):
            raise StoryboardError("Session 结构错误", "visual_references 不是对象。", "先修复 session.json 后重试。")
        field = "characters" if reference_type == "character" else "scenes"
        items = visual.setdefault(field, [])
    else:
        style = state.setdefault("style_reference", {})
        if not isinstance(style, dict):
            raise StoryboardError("Session 结构错误", "style_reference 不是对象。", "先修复 session.json 后重试。")
        items = style.setdefault("assets", [])

    if not isinstance(items, list):
        raise StoryboardError("参考图列表结构错误", f"{reference_type} reference list 不是数组。", "先修复 session.json 后重试。")
    return items


def default_label(reference_type: str, index: int) -> str:
    labels = {
        "character": "Character Reference",
        "scene": "Scene Reference",
        "style": "Style Reference",
    }
    return f"{labels[reference_type]} {index:02d}"


def update_reference(
    items: list[dict[str, object]],
    reference_type: str,
    label: str,
    asset_path: str,
    description: str,
) -> None:
    note_field = "note" if reference_type == "style" else "description"
    entry = {"label": label, "path": asset_path, note_field: description}
    for index, item in enumerate(items):
        if isinstance(item, dict) and str(item.get("label", "")).strip() == label:
            items[index] = entry
            return
    for index, item in enumerate(items):
        if isinstance(item, dict) and not str(item.get("path", "")).strip():
            items[index] = entry
            return
    items.append(entry)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Save and register a user-supplied character, scene, or style reference.")
    parser.add_argument("session", help="Session directory or session JSON path.")
    parser.add_argument("--source", required=True, help="Existing local PNG/JPG/WebP source path.")
    parser.add_argument("--reference-type", required=True, choices=sorted(REFERENCE_TYPES))
    parser.add_argument("--output-name", help="Target JPG filename inside the session assets folder.")
    parser.add_argument("--label", help="Reference label. Reusing a label replaces that entry.")
    parser.add_argument("--description", default="user-supplied reference", help="Compact identity, scene, or style role.")
    parser.add_argument("--long-edge", type=int, default=DEFAULT_LONG_EDGE)
    parser.add_argument("--workspace-root")
    parser.add_argument("--config")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.long_edge <= 0 or args.long_edge > 16384:
            raise StoryboardError(
                "图片尺寸参数不合法",
                f"--long-edge 必须在 1 到 16384 之间，收到 {args.long_edge}。",
                "改用合理的正整数尺寸后重试。",
            )

        config = resolve_workspace_config(workspace_root=args.workspace_root, config_path=args.config)
        state_path = resolve_state_path(config, args.session)
        source = Path(args.source).expanduser().resolve()
        if not source.exists() or not source.is_file():
            raise StoryboardError("参考图不存在", f"找不到本地图片: {source}", "确认 --source 指向真实保存的图片文件。")

        with closing(acquire_session_lock(state_path)):
            state = load_json(state_path)
            if not isinstance(state, dict):
                raise StoryboardError("Session 结构错误", f"{state_path} 不是 JSON object。", "检查 session.json 后重试。")
            items = reference_list(state, args.reference_type)
            populated_count = sum(
                1 for item in items if isinstance(item, dict) and str(item.get("path", "")).strip()
            )
            label = args.label or default_label(args.reference_type, populated_count + 1)
            output_name = args.output_name or f"{slugify(label)}.jpg"
            target = resolve_child_path(state_path.parent / config.assets_dirname, output_name, "参考图输出路径")
            if target.suffix.lower() not in {".jpg", ".jpeg"}:
                target = target.with_suffix(".jpg")
            asset_path = target.relative_to(state_path.parent).as_posix()
            expected_section = {
                "character": "visual_references.characters",
                "scene": "visual_references.scenes",
                "style": "style_reference.assets",
            }[args.reference_type]
            existing_owner = asset_path_owner(state, asset_path, expected_section, label)
            if existing_owner:
                raise StoryboardError(
                    "参考图输出路径冲突",
                    f"{asset_path} 已由 {existing_owner[0]} / {existing_owner[1]} 使用，不能再分配给 {label!r}。",
                    "改用不同的 --output-name，或复用原标签来替换该参考项。",
                )

            html_path = session_html_path(config, state_path)
            original_state_text = state_path.read_text(encoding="utf-8")
            original_html_text = html_path.read_text(encoding="utf-8") if html_path.exists() else None
            original_target = target.read_bytes() if target.exists() else None
            try:
                width, height = convert_reference(source, target, args.long_edge)
                update_reference(
                    items,
                    args.reference_type,
                    label,
                    asset_path,
                    f"{args.description}; registered JPG {width}x{height}",
                )
                dump_json(state_path, state)
                script_dir = Path(__file__).resolve().parent
                run_python_script(
                    script_dir / "render_story_session.py",
                    ["--config", str(config.config_path), str(state_path)],
                )
                run_python_script(
                    script_dir / "validate_story_session.py",
                    ["--config", str(config.config_path), "--profile", "smoke", str(state_path)],
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
        return 0
    except StoryboardError as error:
        print_error(error)
        return 1
    except Exception as error:  # pragma: no cover
        print("问题: 参考图登记发生未预期错误", file=sys.stderr)
        print(f"原因: {error}", file=sys.stderr)
        print("下一步: 检查 session、源图片和输出文件名后重试。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
