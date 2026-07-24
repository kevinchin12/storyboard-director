#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from pathlib import Path

from storyboard_common import StoryboardError, print_error


INSTALL_TARGETS = {
    "storyboard-director": Path("."),
    "storyboard-script-planner": Path("skills/storyboard-script-planner"),
    "storyboard-lineart-generator": Path("skills/storyboard-lineart-generator"),
    "storyboard-aggregate-prompt": Path("skills/storyboard-aggregate-prompt"),
    "storyboard-final-frame-optional": Path("skills/storyboard-final-frame-optional"),
}
LEGACY_MAIN_NAMES = ("storyboard-scene-pipeline",)
COPY_IGNORE = shutil.ignore_patterns(".DS_Store", "__pycache__", "*.pyc", "*.pyo", ".git")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install storyboard pipeline main and sub-skills into CODEX_HOME skills.")
    parser.add_argument(
        "--codex-home",
        default=os.environ.get("CODEX_HOME", str(Path.home() / ".codex")),
        help="Codex home directory. Defaults to $CODEX_HOME, then ~/.codex.",
    )
    parser.add_argument("--copy", action="store_true", help="Copy skill folders instead of creating symlinks.")
    parser.add_argument("--force", action="store_true", help="Replace existing installed entries.")
    parser.add_argument("--dry-run", action="store_true", help="Show actions without changing files.")
    return parser.parse_args()


def skill_root() -> Path:
    return Path(__file__).resolve().parents[1]


def ensure_source(root: Path, relative: Path) -> Path:
    source = (root / relative).resolve()
    if not (source / "SKILL.md").exists():
        raise StoryboardError(
            problem="副 skill 源目录缺失",
            reason=f"找不到 {source / 'SKILL.md'}",
            next_step="确认公共包完整，或重新导出 storyboard skill。",
        )
    return source


def remove_existing(target: Path, force: bool, dry_run: bool) -> None:
    if not target.exists() and not target.is_symlink():
        return
    if dry_run and not force:
        print(f"exists {target}; would keep without --force")
        return
    if not force:
        raise StoryboardError(
            problem="安装目标已存在",
            reason=f"{target} 已存在。",
            next_step="确认不会覆盖本地修改后，加 --force 重试；或先手动备份/删除该目录。",
        )
    if dry_run:
        print(f"would remove {target}")
        return
    if target.is_symlink() or target.is_file():
        target.unlink()
    else:
        shutil.rmtree(target)


def install_one(name: str, source: Path, skills_dir: Path, copy_mode: bool, force: bool, dry_run: bool) -> None:
    target = skills_dir / name
    remove_existing(target, force=force, dry_run=dry_run)
    if target.exists() or target.is_symlink():
        return
    if dry_run:
        action = "copy" if copy_mode else "symlink"
        print(f"would {action} {source} -> {target}")
        return
    skills_dir.mkdir(parents=True, exist_ok=True)
    if copy_mode:
        shutil.copytree(source, target, symlinks=False, ignore=COPY_IGNORE)
    else:
        target.symlink_to(source, target_is_directory=True)
    print(f"installed {name}: {target} -> {source}")


def preflight_install_targets(skills_dir: Path, force: bool, dry_run: bool) -> None:
    if force or dry_run:
        return
    conflicts = [skills_dir / name for name in INSTALL_TARGETS if (skills_dir / name).exists() or (skills_dir / name).is_symlink()]
    if conflicts:
        raise StoryboardError(
            problem="安装目标已存在",
            reason="\n".join(str(path) for path in conflicts),
            next_step="确认不会覆盖本地修改后，加 --force 重试。",
        )


def remove_legacy_aliases(skills_dir: Path, root: Path, force: bool, dry_run: bool) -> None:
    for name in LEGACY_MAIN_NAMES:
        target = skills_dir / name
        if not target.exists() and not target.is_symlink():
            continue
        if target.is_symlink():
            try:
                points_to_root = target.resolve() == root.resolve()
            except OSError:
                points_to_root = False
            if not points_to_root:
                continue
            if dry_run:
                print(f"would remove legacy alias {target}")
            else:
                target.unlink()
                print(f"removed legacy alias {target}")
            continue

        skill_file = target / "SKILL.md" if target.is_dir() else target
        declared_name = ""
        if skill_file.exists() and skill_file.is_file():
            match = re.search(r"(?m)^name:\s*['\"]?([^'\"\s]+)", skill_file.read_text(encoding="utf-8"))
            declared_name = match.group(1) if match else ""
        if declared_name != name:
            continue
        if not force and dry_run:
            print(f"exists legacy copy {target}; would keep without --force")
            continue
        if not force:
            raise StoryboardError(
                problem="发现旧版 copy 安装",
                reason=f"旧主 skill 仍位于 {target}",
                next_step="确认无需保留旧副本后，使用 --force 重新安装。",
            )
        if dry_run:
            print(f"would remove legacy copy {target}")
        elif target.is_dir():
            shutil.rmtree(target)
            print(f"removed legacy copy {target}")
        else:
            target.unlink()
            print(f"removed legacy copy {target}")


def main() -> int:
    try:
        args = parse_args()
        root = skill_root()
        skills_dir = Path(args.codex_home).expanduser().resolve() / "skills"
        sources = {name: ensure_source(root, relative) for name, relative in INSTALL_TARGETS.items()}
        preflight_install_targets(skills_dir, force=args.force, dry_run=args.dry_run)
        remove_legacy_aliases(skills_dir, root, force=args.force, dry_run=args.dry_run)
        for name, source in sources.items():
            install_one(
                name=name,
                source=source,
                skills_dir=skills_dir,
                copy_mode=args.copy,
                force=args.force,
                dry_run=args.dry_run,
            )
        return 0
    except StoryboardError as error:
        print_error(error)
        return 1
    except Exception as error:  # pragma: no cover
        print("问题: 安装脚本发生未预期错误", file=sys.stderr)
        print(f"原因: {error}", file=sys.stderr)
        print("下一步: 检查公共包路径和 Codex skills 目录权限。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
