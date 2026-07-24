#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

from storyboard_common import StoryboardError, is_path_within, load_json, print_error, resolve_workspace_config


COPY_IGNORE = shutil.ignore_patterns(".DS_Store", "__pycache__", "*.pyc", "*.pyo", ".git")


def validate_bundle_name(value: object) -> str:
    bundle_name = str(value or "storyboard-scene-pipeline-public").strip() or "storyboard-scene-pipeline-public"
    if Path(bundle_name).name != bundle_name or bundle_name in {".", ".."}:
        raise StoryboardError(
            "bundle_name 不安全",
            f"bundle_name 必须是单个目录名，收到: {bundle_name!r}",
            "删除路径分隔符和 .. 后重试。",
        )
    return bundle_name


def safe_manifest_source(root: Path, raw_path: object) -> tuple[Path, Path]:
    raw_text = str(raw_path).strip()
    relative = Path(raw_text)
    unresolved_source = root / relative
    source = unresolved_source.resolve()
    if not raw_text or relative in {Path("."), Path("..")} or relative.is_absolute() or source == root or not is_path_within(source, root):
        raise StoryboardError(
            "公共 bundle 路径不安全",
            f"manifest include 必须是仓库内的具体文件或子目录: {raw_path!r}",
            "删除空路径、仓库根目录、绝对路径或 .. 路径后重试。",
        )
    if unresolved_source.is_symlink():
        raise StoryboardError(
            "公共 bundle 路径是符号链接",
            f"manifest include 不能直接指向符号链接: {raw_path!r}",
            "改为仓库内的真实文件或目录。",
        )
    return relative, source


def reject_symlinks(source: Path) -> None:
    candidates = [source] if source.is_file() else source.rglob("*")
    for candidate in candidates:
        if candidate.is_symlink():
            raise StoryboardError(
                "公共 bundle 含符号链接",
                f"符号链接可能把仓库外文件带入分享包: {candidate}",
                "把链接替换成受控文件，或从 manifest 中移除对应目录。",
            )


def build_bundle(root: Path, manifest: dict[str, object]) -> Path:
    bundle_name = validate_bundle_name(manifest.get("bundle_name"))
    include = manifest.get("include", [])
    if not isinstance(include, list) or not include:
        raise StoryboardError("bundle manifest 缺少 include", "public_bundle_manifest.json 里没有有效 include 列表。", "把需要公开发布的文件和目录写入 include。")

    dist_root = root / "dist"
    if dist_root.is_symlink() or not is_path_within(dist_root, root):
        raise StoryboardError("dist 目录不安全", f"dist 必须是仓库内的真实目录: {dist_root}", "移除外部符号链接后重试。")
    dist_root.mkdir(parents=True, exist_ok=True)
    dist_dir = dist_root / bundle_name
    if not is_path_within(dist_dir, dist_root):
        raise StoryboardError("bundle 输出越界", f"输出目录超出 dist/: {dist_dir}", "修正 bundle_name 后重试。")
    if dist_dir.is_symlink():
        raise StoryboardError("bundle 输出目录不安全", f"输出目录不能是符号链接: {dist_dir}", "删除该符号链接后重试。")

    sources: list[tuple[Path, Path]] = []
    for raw_relative in include:
        relative_path, source = safe_manifest_source(root, raw_relative)
        if is_path_within(source, dist_root):
            raise StoryboardError(
                "公共 bundle 不能包含 dist",
                f"manifest include 指向构建输出目录: {source}",
                "从 include 中删除 dist 或其子目录。",
            )
        if not source.exists():
            raise StoryboardError("公共 bundle 源文件缺失", f"manifest 指向的路径不存在: {source}", "补齐文件，或从 manifest 里删掉该项。")
        reject_symlinks(source)
        sources.append((relative_path, source))

    staging_dir = Path(tempfile.mkdtemp(prefix=f".{bundle_name}.staging-", dir=dist_root))
    backup_dir = dist_root / f".{bundle_name}.backup-{os.getpid()}"
    try:
        for relative_path, source in sources:
            target = staging_dir / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, target, dirs_exist_ok=True, ignore=COPY_IGNORE)
            else:
                shutil.copy2(source, target)

        if backup_dir.exists() or backup_dir.is_symlink():
            raise StoryboardError("bundle 备份目录冲突", f"临时备份路径已存在: {backup_dir}", "删除残留备份目录后重试。")
        if dist_dir.exists():
            dist_dir.replace(backup_dir)
        try:
            staging_dir.replace(dist_dir)
        except Exception:
            if backup_dir.exists() and not dist_dir.exists():
                backup_dir.replace(dist_dir)
            raise
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        return dist_dir
    finally:
        if staging_dir.exists():
            shutil.rmtree(staging_dir)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the public storyboard bundle from public_bundle_manifest.json.")
    return parser.parse_args()


def main() -> int:
    parse_args()
    try:
        config = resolve_workspace_config()
        root = config.workspace_root
        manifest_path = root / "public_bundle_manifest.json"
        manifest = load_json(manifest_path)
        if not isinstance(manifest, dict):
            raise StoryboardError("bundle manifest 结构错误", f"{manifest_path} 不是对象。", "修正 public_bundle_manifest.json 后重试。")
        print(build_bundle(root, manifest))
        return 0
    except StoryboardError as error:
        print_error(error)
        return 1
    except Exception as error:  # pragma: no cover - defensive CLI fallback
        print("问题: 构建 public bundle 时发生未预期错误", file=sys.stderr)
        print(f"原因: {error}", file=sys.stderr)
        print("下一步: 检查 manifest 和源文件完整性后重试。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
