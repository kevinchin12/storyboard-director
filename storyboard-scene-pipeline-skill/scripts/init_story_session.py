#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from storyboard_common import (
    StoryboardError,
    dump_json,
    ensure_workspace_dirs,
    load_json,
    print_error,
    resolve_workspace_config,
    run_python_script,
    session_paths,
    slugify,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or reopen a storyboard session.")
    parser.add_argument("title", help="Story or project title.")
    parser.add_argument("--new", action="store_true", help="Always create a separate session, even when the title already exists.")
    parser.add_argument("--workspace-root", help="Workspace root containing storyboard.config.json.")
    parser.add_argument("--config", help="Path to storyboard.config.json.")
    args = parser.parse_args()

    try:
        title = args.title.strip()

        if not title:
            raise StoryboardError("标题为空", "没有解析到有效的故事标题。", "传入非空标题后重试。")

        config = resolve_workspace_config(workspace_root=args.workspace_root, config_path=args.config)
        ensure_workspace_dirs(config)

        slug = slugify(title)
        matches = sorted(config.sessions_dir.glob(f"*-{slug}"))
        if matches and not args.new:
            state_path, _, _ = session_paths(config, matches[-1])
            run_python_script(
                Path(__file__).resolve().parent / "render_story_session.py",
                ["--config", str(config.config_path), str(state_path)],
            )
            print(state_path)
            return 0

        created = datetime.now().strftime("%Y%m%d-%H%M%S")
        session_dir = config.sessions_dir / f"{created}-{slug}"
        collision_index = 2
        while session_dir.exists():
            session_dir = config.sessions_dir / f"{created}-{collision_index}-{slug}"
            collision_index += 1
        state_path, _, assets_dir = session_paths(config, session_dir)
        session_dir.mkdir(parents=True, exist_ok=True)
        assets_dir.mkdir(parents=True, exist_ok=True)

        skill_root = Path(__file__).resolve().parents[1]
        template_path = skill_root / "assets" / "story_session_state.template.json"
        if not template_path.exists():
            raise StoryboardError("状态模板缺失", f"找不到模板文件: {template_path}", "确认 skill 目录完整，或重新复制公共包。")

        state = load_json(template_path)
        if not isinstance(state, dict):
            raise StoryboardError("模板结构错误", f"{template_path} 不是 JSON object。", "修正模板文件后重试。")
        state["project_title"] = title
        state["project_summary"] = "待补充故事摘要。这个页面用于集中记录故事想法、角色设定图、场景图、脚本、线稿和合并版提示词。"
        dump_json(state_path, state)

        run_python_script(
            Path(__file__).resolve().parent / "render_story_session.py",
            ["--config", str(config.config_path), str(state_path)],
        )
        print(state_path)
        return 0
    except StoryboardError as error:
        print_error(error)
        return 1
    except Exception as error:  # pragma: no cover - defensive CLI fallback
        print("问题: 初始化脚本发生未预期错误", file=sys.stderr)
        print(f"原因: {error}", file=sys.stderr)
        print("下一步: 检查公共包是否完整，或先运行 doctor_storyboard_skill.py。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
