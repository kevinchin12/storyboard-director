#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from storyboard_common import (
    StoryboardError,
    ensure_state_shape,
    print_error,
    resolve_state_path,
    resolve_workspace_config,
    session_html_path,
    shot_asset_for,
    write_text_atomic,
)


def compact(text: object, limit: int = 180) -> str:
    value = " ".join(str(text or "").split())
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def shot_gallery_path(state: dict[str, object], section: str, shot: dict[str, object], index: int) -> str:
    block = state.get(section, {})
    if not isinstance(block, dict):
        return ""
    gallery = block.get("gallery", [])
    if not isinstance(gallery, list):
        gallery = []

    typed_gallery = [item for item in gallery if isinstance(item, dict)]
    item = shot_asset_for(typed_gallery, shot, index)
    return str(item.get("path", "")).strip() if item else ""


def style_paths(state: dict[str, object]) -> list[str]:
    block = state.get("style_reference", {})
    if not isinstance(block, dict):
        return []
    assets = block.get("assets", [])
    if not isinstance(assets, list):
        return []
    paths = []
    for item in assets:
        if isinstance(item, dict):
            raw_path = str(item.get("path", "")).strip()
            if raw_path:
                paths.append(raw_path)
    return paths


def display_option_enabled(state: dict[str, object], key: str, default: bool = False) -> bool:
    options = state.get("display_options", {})
    if not isinstance(options, dict):
        return default
    return options.get(key, default) is True


def list_items(items: object, limit: int = 3) -> str:
    if not isinstance(items, list) or not items:
        return "- 未填写"
    return "\n".join(f"- {compact(item, 140)}" for item in items[:limit])


def render_handoff(state_path: Path, state: dict[str, object], html_path: Path, assets_dirname: str) -> str:
    session_dir = state_path.parent
    shots = state.get("shots", [])
    if not isinstance(shots, list):
        shots = []
    refs = state.get("production_reference", {})
    if not isinstance(refs, dict):
        refs = {}
    show_durations = display_option_enabled(state, "show_durations", False)

    rows: list[str] = []
    for index, shot in enumerate(shots):
        if not isinstance(shot, dict):
            continue
        video_prompt = shot.get("video_prompt", {})
        has_video = isinstance(video_prompt, dict) and bool(str(video_prompt.get("seedance2", "")).strip())
        row_values = [
            compact(shot.get("id", ""), 36),
            compact(shot.get("frame", ""), 110).replace("|", "/"),
            compact(shot.get("action", ""), 110).replace("|", "/"),
            compact(shot.get("camera", ""), 90).replace("|", "/"),
            shot_gallery_path(state, "line_art", shot, index) or "missing",
            shot_gallery_path(state, "final_generation", shot, index) or "missing",
            "present" if has_video else "missing",
        ]
        if show_durations:
            row_values.insert(1, compact(shot.get("duration", ""), 20))
        rows.append("| " + " | ".join(row_values) + " |")

    style_asset_lines = "\n".join(f"- {path}" for path in style_paths(state)) or "- 未记录风格参考路径"
    if show_durations:
        shot_header = "| Shot | Time | Frame | Action | Camera | Line Art | Final Frame | Video Prompt |\n| --- | --- | --- | --- | --- | --- | --- | --- |"
        empty_row = "| 未填写 |  |  |  |  |  |  |  |"
    else:
        shot_header = "| Shot | Frame | Action | Camera | Line Art | Final Frame | Video Prompt |\n| --- | --- | --- | --- | --- | --- | --- |"
        empty_row = "| 未填写 |  |  |  |  |  |  |"
    shot_table = "\n".join(rows) if rows else empty_row

    return f"""# Story Session Handoff

- Generated: {datetime.now().strftime("%Y-%m-%d %H:%M")}
- Project: {compact(state.get("project_title", "Story Session"), 120)}
- Workflow mode: {compact(state.get("workflow_mode", "prompt_control_no_ai_review"), 40)}
- Mode: {compact(state.get("project_mode", ""), 40)}
- Current stage: {compact(state.get("current_stage", ""), 40)}
- Session JSON: {state_path}
- Session HTML: {html_path}
- Assets dir: {session_dir / assets_dirname}

## Next Action

{compact(state.get("next_action", "未填写"), 320)}

## Short-Context Rule

- Do not paste the full HTML, images, or old chat history into the next thread.
- Upload only the 1-3 images needed for the current step when the model must inspect pixels.
- Keep persistent state path-based: update `session.json`, save images under `assets/`, re-render `session.html`.

## Production Anchors

Primary anchor:
{list_items(refs.get("primary_anchor", []))}

Continuity:
{list_items(refs.get("continuity_rules", []))}

World lock:
{list_items(refs.get("world_lock", []))}

## Style References

{style_asset_lines}

## Shot Snapshot

{shot_header}
{shot_table}
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export a compact Markdown handoff from a storyboard session.")
    parser.add_argument("session", help="Session directory or session JSON path.")
    parser.add_argument("--output", help="Markdown output path. Defaults to handoff.md beside the session.")
    parser.add_argument("--workspace-root", help="Workspace root containing storyboard.config.json.")
    parser.add_argument("--config", help="Path to storyboard.config.json.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        config = resolve_workspace_config(workspace_root=args.workspace_root, config_path=args.config)
        state_path = resolve_state_path(config, args.session)
        if not state_path.exists():
            raise StoryboardError(
                problem="Session 文件不存在",
                reason=f"找不到状态文件: {state_path}",
                next_step="确认传入的是 session 目录或 session.json 路径。",
            )

        state = ensure_state_shape(json.loads(state_path.read_text(encoding="utf-8")))
        output_path = Path(args.output).expanduser().resolve() if args.output else state_path.parent / "handoff.md"
        write_text_atomic(
            output_path,
            render_handoff(state_path, state, session_html_path(config, state_path), config.assets_dirname),
        )
        print(output_path)
        return 0
    except StoryboardError as error:
        print_error(error)
        return 1
    except Exception as error:  # pragma: no cover - defensive CLI fallback
        print("问题: handoff 导出发生未预期错误", file=sys.stderr)
        print(f"原因: {error}", file=sys.stderr)
        print("下一步: 先确认 session.json 可以解析，再重新执行导出。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
