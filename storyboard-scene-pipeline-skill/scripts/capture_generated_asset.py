#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from storyboard_common import StoryboardError, print_error, resolve_state_path, resolve_workspace_config, write_text_atomic


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
MARKER_NAME = ".imagegen-capture-marker.json"


def candidate_roots(extra_roots: list[str]) -> list[Path]:
    roots: list[Path] = []
    for raw in extra_roots:
        if raw.strip():
            roots.append(Path(raw).expanduser())

    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
    roots.append(codex_home / "generated_images")
    roots.append(Path.home() / ".codex" / "generated_images")

    unique: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        resolved = root.resolve() if root.exists() else root.expanduser()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique


def iter_images(root: Path):
    if not root.exists():
        return
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
            yield path


def snapshot(roots: list[Path]) -> dict[str, object]:
    files: dict[str, float] = {}
    for root in roots:
        for path in iter_images(root) or []:
            try:
                files[str(path.resolve())] = path.stat().st_mtime
            except OSError:
                continue
    return {"created_at": time.time(), "files": files}


def write_marker(state_path: Path, roots: list[Path]) -> Path:
    marker = state_path.parent / MARKER_NAME
    write_text_atomic(marker, json.dumps(snapshot(roots), ensure_ascii=False, indent=2) + "\n")
    return marker


def load_marker(state_path: Path) -> dict[str, object]:
    marker = state_path.parent / MARKER_NAME
    if not marker.exists():
        raise StoryboardError(
            problem="缺少生图前标记",
            reason=f"找不到 {marker}",
            next_step="在调用 image_gen 前先运行本脚本的 --mark。",
        )
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StoryboardError(
            problem="生图标记损坏",
            reason=f"{marker} 不是合法 JSON: {exc}",
            next_step="重新运行 --mark，然后重新生图。",
        ) from exc
    if not isinstance(data, dict):
        raise StoryboardError("生图标记结构错误", f"{marker} 不是对象。", "重新运行 --mark。")
    return data


def find_newest_after_marker(state_path: Path, roots: list[Path]) -> Path:
    marker = load_marker(state_path)
    before_files = marker.get("files", {})
    if not isinstance(before_files, dict):
        before_files = {}
    created_at = float(marker.get("created_at", 0) or 0)

    candidates: dict[Path, float] = {}
    for root in roots:
        for path in iter_images(root) or []:
            try:
                resolved = str(path.resolve())
                mtime = path.stat().st_mtime
            except OSError:
                continue
            previous_mtime = before_files.get(resolved)
            if previous_mtime is not None and mtime <= float(previous_mtime) + 0.001:
                continue
            if previous_mtime is None and mtime + 0.001 < created_at:
                continue
            candidates[path.resolve()] = mtime

    if not candidates:
        searched = "\n".join(str(root) for root in roots)
        raise StoryboardError(
            problem="没有找到新的本地生图文件",
            reason=f"在生图前标记之后，未发现新的 PNG/JPG/WebP。\n搜索目录:\n{searched}",
            next_step="确认 image_gen 是否真实落盘；如果只有聊天预览，重试内置生图或让用户提供已保存文件路径。",
        )
    if len(candidates) > 1:
        candidate_lines = "\n".join(
            str(path)
            for path, _ in sorted(candidates.items(), key=lambda item: item[1], reverse=True)
        )
        raise StoryboardError(
            problem="生图标记后出现多个候选文件",
            reason=f"无法安全判断哪张图片属于当前 Shot:\n{candidate_lines}",
            next_step="不要自动选择最新文件；改用 --source 明确传入当前 worker 返回的本地图片路径。",
        )
    return next(iter(candidates))


def run_register(
    script_dir: Path,
    state_path: Path,
    source: Path,
    asset_type: str,
    shot_id: str,
    output_name: str | None,
    validate_profile: str,
    config_path: Path,
) -> subprocess.CompletedProcess[str]:
    args = [
        "python3",
        str(script_dir / "register_story_asset.py"),
        str(state_path),
        "--asset-type",
        asset_type,
        "--shot-id",
        shot_id,
        "--source",
        str(source),
        "--validate-profile",
        validate_profile,
        "--config",
        str(config_path),
    ]
    if output_name:
        args.extend(["--output-name", output_name])
    return subprocess.run(args, capture_output=True, text=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture a newly generated image_gen file and register it into a storyboard session.")
    parser.add_argument("session", help="Session directory or session.json path.")
    parser.add_argument("--asset-type", choices=("line-art", "final-frame"), help="Asset gallery to update.")
    parser.add_argument("--shot-id", help='Shot id, for example "Shot 01".')
    parser.add_argument("--output-name", help="Target filename inside the session assets folder.")
    parser.add_argument("--source", help="Known source image path. If provided, skip generated_images search.")
    parser.add_argument("--search-root", action="append", default=[], help="Extra root to search for generated images.")
    parser.add_argument("--mark", action="store_true", help="Write a before-image-generation marker and exit.")
    parser.add_argument("--validate-profile", default="smoke", choices=("smoke", "workflow", "release"))
    parser.add_argument("--workspace-root")
    parser.add_argument("--config")
    return parser.parse_args()


def main() -> int:
    try:
        args = parse_args()
        config = resolve_workspace_config(workspace_root=args.workspace_root, config_path=args.config)
        state_path = resolve_state_path(config, args.session)
        if not state_path.exists() or not state_path.is_file():
            raise StoryboardError(
                problem="Session 文件不存在",
                reason=f"找不到状态文件: {state_path}",
                next_step="先创建或确认 session.json，再写生图标记。",
            )
        roots = candidate_roots(args.search_root)

        if args.mark:
            marker = write_marker(state_path, roots)
            print(marker)
            return 0

        if not args.asset_type or not args.shot_id:
            raise StoryboardError(
                problem="缺少登记参数",
                reason="非 --mark 模式必须提供 --asset-type 和 --shot-id。",
                next_step="补充 asset type 与 shot id 后重试。",
            )

        source = Path(args.source).expanduser().resolve() if args.source else find_newest_after_marker(state_path, roots)
        if not source.exists():
            raise StoryboardError(
                problem="源图片不存在",
                reason=f"找不到可登记的图片: {source}",
                next_step="确认 --source 路径，或重新用 --mark + image_gen + 本脚本捕获。",
            )

        script_dir = Path(__file__).resolve().parent
        result = run_register(
            script_dir=script_dir,
            state_path=state_path,
            source=source,
            asset_type=args.asset_type,
            shot_id=args.shot_id,
            output_name=args.output_name,
            validate_profile=args.validate_profile,
            config_path=config.config_path,
        )
        if result.returncode != 0:
            raise StoryboardError(
                problem="图片捕获成功但登记失败",
                reason=(result.stdout + result.stderr).strip() or f"register_story_asset.py exit {result.returncode}",
                next_step="按错误信息修正 shot id、源图或 session 后重试。",
            )
        marker = state_path.parent / MARKER_NAME
        if marker.exists():
            marker.unlink()
        print(result.stdout.strip())
        return 0
    except StoryboardError as error:
        print_error(error)
        return 1
    except Exception as error:  # pragma: no cover
        print("问题: 生图捕获脚本发生未预期错误", file=sys.stderr)
        print(f"原因: {error}", file=sys.stderr)
        print("下一步: 检查 session、标记文件、generated_images 目录和参数后重试。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
