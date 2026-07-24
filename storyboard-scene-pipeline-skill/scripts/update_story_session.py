#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
import subprocess
from pathlib import Path

from storyboard_common import (
    StoryboardError,
    acquire_session_lock,
    dump_json,
    ensure_state_shape,
    load_json,
    print_error,
    resolve_state_path,
    resolve_workspace_config,
    run_python_script,
    session_html_path,
    write_text_atomic,
)


def deep_merge(base: object, patch: object) -> object:
    if isinstance(base, dict) and isinstance(patch, dict):
        merged = dict(base)
        for key, value in patch.items():
            if key in merged:
                merged[key] = deep_merge(merged[key], value)
            else:
                merged[key] = value
        return merged

    if isinstance(base, list) and isinstance(patch, list):
        return patch

    return patch


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply a JSON patch to a storyboard session, then render and optionally validate it.")
    parser.add_argument("session", help="Session directory or session JSON path.")
    parser.add_argument("patch", help="JSON object patch path. Arrays replace existing arrays.")
    parser.add_argument("--validate", action="store_true", help="Validate with the workflow profile after rendering.")
    parser.add_argument("--validate-profile", choices=("smoke", "workflow", "release"), help="Validate with the selected profile.")
    parser.add_argument("--workspace-root", help="Workspace root containing storyboard.config.json.")
    parser.add_argument("--config", help="Path to storyboard.config.json.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        validate_after = args.validate or args.validate_profile is not None
        validate_profile = args.validate_profile or "workflow"
        config = resolve_workspace_config(workspace_root=args.workspace_root, config_path=args.config)
        state_path = resolve_state_path(config, args.session)
        patch_path = Path(args.patch).expanduser().resolve()

        if not state_path.exists():
            raise StoryboardError("Session 文件不存在", f"找不到状态文件: {state_path}", "确认第一个参数是 session 目录或 session.json 路径。")
        if not patch_path.exists():
            raise StoryboardError("Patch 文件不存在", f"找不到 patch: {patch_path}", "确认第二个参数是合法的 patch.json 路径。")

        session_lock = acquire_session_lock(state_path)
        original_state_text = state_path.read_text(encoding="utf-8")
        html_path = session_html_path(config, state_path)
        original_html_text = html_path.read_text(encoding="utf-8") if html_path.exists() else None

        state = load_json(state_path)
        patch = load_json(patch_path)
        if not isinstance(state, dict) or not isinstance(patch, dict):
            raise StoryboardError(
                problem="Session 或 patch 结构错误",
                reason="update 只接受 JSON object 形式的 session 和 patch。",
                next_step="把两个文件的顶层结构改成 JSON object 后重试。",
            )
        merged = ensure_state_shape(deep_merge(state, patch))
        try:
            dump_json(state_path, merged)

            render_script = Path(__file__).resolve().parent / "render_story_session.py"
            run_python_script(render_script, ["--config", str(config.config_path), str(state_path)])

            if validate_after:
                validate_script = Path(__file__).resolve().parent / "validate_story_session.py"
                run_python_script(
                    validate_script,
                    ["--config", str(config.config_path), "--profile", validate_profile, str(state_path)],
                )
        except Exception as exc:
            write_text_atomic(state_path, original_state_text)
            if original_html_text is None:
                if html_path.exists():
                    html_path.unlink()
            else:
                write_text_atomic(html_path, original_html_text)
            if isinstance(exc, subprocess.CalledProcessError):
                detail = "\n".join(part.strip() for part in (exc.stdout or "", exc.stderr or "") if part.strip())
                raise StoryboardError(
                    problem="Session 更新未通过渲染或校验，已自动回滚",
                    reason=detail or f"子命令退出码: {exc.returncode}",
                    next_step="修正 patch 后重试；原 session.json 和 HTML 已恢复。",
                ) from exc
            raise

        print(state_path)
        print(html_path)
        session_lock.close()
        return 0
    except StoryboardError as error:
        print_error(error)
        return 1
    except Exception as error:  # pragma: no cover - defensive CLI fallback
        print("问题: 更新脚本发生未预期错误", file=sys.stderr)
        print(f"原因: {error}", file=sys.stderr)
        print("下一步: 检查 patch.json 和 session.json，必要时先单独运行 render/validate。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
