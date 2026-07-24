#!/usr/bin/env python3

from __future__ import annotations

import shutil
import os
import re
import sys
from argparse import ArgumentParser
from pathlib import Path

from storyboard_common import CONFIG_FILENAME, StoryboardError, print_error, resolve_workspace_config


def parse_args() -> object:
    parser = ArgumentParser(description="Check storyboard skill installation and workspace wiring.")
    parser.add_argument("--workspace-root", help="Workspace root containing storyboard.config.json.")
    parser.add_argument("--config", help="Path to storyboard.config.json.")
    parser.add_argument("--codex-home", default=os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    parser.add_argument("--skip-install-check", action="store_true", help="Check source/workspace files only.")
    return parser.parse_args()


def main() -> int:
    try:
        args = parse_args()
        if sys.version_info < (3, 9):
            raise StoryboardError(
                problem="Python 版本过低",
                reason=f"当前版本是 {sys.version.split()[0]}，storyboard scripts 需要 Python 3.9 或更新版本。",
                next_step="切换到 Python 3.9+ 后重新运行 doctor。",
            )
        if shutil.which("python3") is None:
            raise StoryboardError(
                problem="缺少 python3",
                reason="当前环境无法找到 python3，可执行脚本无法运行。",
                next_step="先安装 Python 3，再重新执行 doctor。",
            )
        try:
            from PIL import Image  # noqa: F401
        except Exception as exc:
            raise StoryboardError(
                problem="缺少 Pillow",
                reason=f"资产登记脚本需要 Pillow 读写 PNG/JPG/WebP: {exc}",
                next_step="使用带 Pillow 的 Python 环境，或先安装 Pillow 后再登记生成图片。",
            ) from exc
        if not hasattr(Image, "Resampling"):
            raise StoryboardError(
                problem="Pillow 版本过低",
                reason="当前 Pillow 缺少 Image.Resampling，图片缩放脚本需要 Pillow 9.1 或更新版本。",
                next_step="运行 `python3 -m pip install -r requirements.txt` 后重新执行 doctor。",
            )

        config = resolve_workspace_config(args.workspace_root, args.config)
        skill_root = Path(__file__).resolve().parents[1]
        required_files = [
            skill_root / "SKILL.md",
            skill_root / "agents" / "openai.yaml",
            skill_root / "assets" / "story_session_template.html",
            skill_root / "assets" / "story_session_state.template.json",
            skill_root / "integrations" / "imagegen-save-recovery.md",
            skill_root / "skills" / "storyboard-script-planner" / "SKILL.md",
            skill_root / "skills" / "storyboard-script-planner" / "agents" / "openai.yaml",
            skill_root / "skills" / "storyboard-lineart-generator" / "SKILL.md",
            skill_root / "skills" / "storyboard-lineart-generator" / "agents" / "openai.yaml",
            skill_root / "skills" / "storyboard-aggregate-prompt" / "SKILL.md",
            skill_root / "skills" / "storyboard-aggregate-prompt" / "agents" / "openai.yaml",
            skill_root / "skills" / "storyboard-final-frame-optional" / "SKILL.md",
            skill_root / "skills" / "storyboard-final-frame-optional" / "agents" / "openai.yaml",
            skill_root / "scripts" / "capture_generated_asset.py",
            skill_root / "scripts" / "init_story_session.py",
            skill_root / "scripts" / "install_storyboard_skills.py",
            skill_root / "scripts" / "audit_story_assets.py",
            skill_root / "scripts" / "export_story_handoff.py",
            skill_root / "scripts" / "generate_storyboard_sheet.py",
            skill_root / "scripts" / "register_story_asset.py",
            skill_root / "scripts" / "register_story_reference.py",
            skill_root / "scripts" / "render_story_session.py",
            skill_root / "scripts" / "update_story_session.py",
            skill_root / "scripts" / "validate_story_session.py",
        ]
        missing = [str(path) for path in required_files if not path.exists()]
        if missing:
            raise StoryboardError(
                problem="公共 skill 文件不完整",
                reason="缺少以下必要文件:\n" + "\n".join(missing),
                next_step="重新复制完整的 storyboard-scene-pipeline-skill 公共包。",
            )

        if not config.config_path.exists():
            raise StoryboardError(
                problem="工作区配置缺失",
                reason=f"找不到 {CONFIG_FILENAME}: {config.config_path}",
                next_step="在工作区根目录放置 storyboard.config.json。",
            )

        if not args.skip_install_check:
            expected_skills = (
                "storyboard-director",
                "storyboard-script-planner",
                "storyboard-lineart-generator",
                "storyboard-aggregate-prompt",
                "storyboard-final-frame-optional",
            )
            skills_dir = Path(args.codex_home).expanduser().resolve() / "skills"
            install_failures: list[str] = []
            for expected_name in expected_skills:
                installed = skills_dir / expected_name
                skill_file = installed / "SKILL.md"
                if not skill_file.exists():
                    install_failures.append(f"缺少或已断开的安装项: {installed}")
                    continue
                match = re.search(r"(?m)^name:\s*['\"]?([^'\"\s]+)", skill_file.read_text(encoding="utf-8"))
                actual_name = match.group(1) if match else ""
                if actual_name != expected_name:
                    install_failures.append(f"安装名不一致: {skill_file} 声明 {actual_name!r}，应为 {expected_name!r}")

            legacy = skills_dir / "storyboard-scene-pipeline"
            if legacy.exists() or legacy.is_symlink():
                install_failures.append(f"仍存在旧主 skill 安装项: {legacy}")
            if install_failures:
                raise StoryboardError(
                    problem="Codex skill 安装状态不完整",
                    reason="\n".join(install_failures),
                    next_step="运行 install_storyboard_skills.py --force，然后重新打开 Codex session。",
                )

        config.sessions_dir.mkdir(parents=True, exist_ok=True)
        config.examples_dir.mkdir(parents=True, exist_ok=True)

        print("DOCTOR PASSED")
        print(f"workspace_root={config.workspace_root}")
        print(f"config={config.config_path}")
        print(f"sessions_dir={config.sessions_dir}")
        print(f"examples_dir={config.examples_dir}")
        if not args.skip_install_check:
            print(f"skills_dir={skills_dir}")
        return 0
    except StoryboardError as error:
        print_error(error)
        return 1
    except Exception as error:  # pragma: no cover - defensive CLI fallback
        print("问题: doctor 脚本发生未预期错误", file=sys.stderr)
        print(f"原因: {error}", file=sys.stderr)
        print("下一步: 确认配置文件和公共包目录完整。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
