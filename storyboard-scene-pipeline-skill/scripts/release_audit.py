#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from storyboard_common import StoryboardError, load_json, print_error, resolve_workspace_config
from build_public_bundle import build_bundle, safe_manifest_source, validate_bundle_name


PRIVATE_MARKERS = ("Kev" + "in", "嘉" + "文", "Ch" + "in")
PUBLIC_TEXT_EXTENSIONS = {".md", ".json", ".html", ".txt"}
PUBLIC_SOURCE_EXTENSIONS = {".py", ".yaml", ".yml", ".toml", ".sh"}
PUBLIC_SPECIAL_TEXT_FILES = {".gitignore", "LICENSE"}
SENSITIVE_FILENAMES = {".npmrc", ".pypirc"}
SENSITIVE_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".mobileprovision"}
ARCHIVE_SUFFIXES = {".zip", ".tar", ".gz", ".tgz", ".7z", ".rar"}
ABSOLUTE_USER_PATH_RE = re.compile(r"/Users/[A-Za-z0-9._-]+/")
SECRET_PATTERNS = (
    re.compile(r"(?i)(?:sk-proj-|sk-)[A-Za-z0-9_-]{20,}"),
    re.compile(r"-----BEGIN " + r"(?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?i)(?:api[_-]?key|secret|password|token)\s*[:=]\s*['\"][^'\"\n]{12,}['\"]"),
)
EXAMPLE_PROFILES = {
    "character/mibu-bedroom-adventure/session.json": "release",
    "subject/sketch-to-mech-phone-case/session.json": "release",
}


def iter_audit_files(target: Path):
    if target.is_file():
        yield target
        return
    for path in target.rglob("*"):
        if path.is_file():
            yield path


def audit_text_files(target: Path, failures: list[str]) -> None:
    for path in iter_audit_files(target):
        if path.is_symlink():
            failures.append(f"发现符号链接，bundle 可能复制工作区外内容: {path}")
            continue
        if not path.is_file():
            continue
        lowered_name = path.name.lower()
        if (
            lowered_name in SENSITIVE_FILENAMES
            or lowered_name == ".env"
            or lowered_name.startswith(".env.")
            or path.suffix.lower() in SENSITIVE_SUFFIXES
        ):
            failures.append(f"发现敏感配置或密钥文件: {path}")
            continue
        if path.suffix.lower() in ARCHIVE_SUFFIXES:
            failures.append(f"公共 bundle 内不应嵌套压缩包: {path}")
            continue
        if path.name == ".DS_Store":
            failures.append(f"发现 .DS_Store: {path}")
            continue
        if "__pycache__" in path.parts or path.suffix.lower() == ".pyc":
            failures.append(f"发现 Python 临时文件: {path}")
            continue
        suffix = path.suffix.lower()
        if suffix not in PUBLIC_TEXT_EXTENSIONS | PUBLIC_SOURCE_EXTENSIONS and path.name not in PUBLIC_SPECIAL_TEXT_FILES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            failures.append(f"声明为文本但无法按 UTF-8 读取: {path}")
            continue
        if any(pattern.search(text) for pattern in SECRET_PATTERNS):
            failures.append(f"发现疑似凭据或私钥内容: {path}")
        if suffix in PUBLIC_SOURCE_EXTENSIONS:
            if ABSOLUTE_USER_PATH_RE.search(text):
                failures.append(f"发现源码中的用户绝对路径残留: {path}")
            continue
        lowered = text.lower()
        if ABSOLUTE_USER_PATH_RE.search(text):
            failures.append(f"发现绝对路径残留: {path}")
        if ".svg" in lowered:
            failures.append(f"发现 SVG 残留引用: {path}")
        if "data:image/" in lowered or ";base64," in lowered:
            failures.append(f"发现内联图片或编码负载: {path}")
        if "approved" in path.name.lower() or "draft" in path.name.lower():
            failures.append(f"文件名暴露过程态词汇: {path}")


def audit_private_markers(target: Path, failures: list[str]) -> None:
    for path in iter_audit_files(target):
        if not path.is_file():
            continue
        if path.suffix.lower() not in PUBLIC_TEXT_EXTENSIONS | PUBLIC_SOURCE_EXTENSIONS and path.name not in PUBLIC_SPECIAL_TEXT_FILES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for marker in PRIVATE_MARKERS:
            found = (
                bool(re.search(rf"(?<![A-Za-z]){re.escape(marker)}(?![A-Za-z])", text))
                if marker.isascii()
                else marker in text
            )
            if found:
                failures.append(f"公共文件仍含私有标记 `{marker}`: {path}")
                break


def audit_examples(root: Path, failures: list[str]) -> None:
    validate_script = root / "storyboard-scene-pipeline-skill" / "scripts" / "validate_story_session.py"
    render_script = root / "storyboard-scene-pipeline-skill" / "scripts" / "render_story_session.py"
    asset_audit_script = root / "storyboard-scene-pipeline-skill" / "scripts" / "audit_story_assets.py"
    handoff_script = root / "storyboard-scene-pipeline-skill" / "scripts" / "export_story_handoff.py"
    for relative_path, profile in EXAMPLE_PROFILES.items():
        session_path = root / "examples" / relative_path
        if not session_path.exists():
            failures.append(f"示例缺失: {session_path}")
            continue
        with tempfile.TemporaryDirectory(prefix="storyboard-release-audit-") as temp_dir:
            temp_root = Path(temp_dir)
            shutil.copy2(root / "storyboard.config.json", temp_root / "storyboard.config.json")
            (temp_root / "sessions").mkdir()
            working_dir = temp_root / "examples" / session_path.parent.relative_to(root / "examples")
            working_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(session_path.parent, working_dir)
            working_session = working_dir / session_path.name
            workspace_args = ["--workspace-root", str(temp_root)]

            render = subprocess.run(
                ["python3", str(render_script), str(working_session), *workspace_args],
                capture_output=True,
                text=True,
            )
            if render.returncode != 0:
                failures.append(f"示例渲染失败: {session_path}\n{render.stderr.strip()}")
                continue
            validate = subprocess.run(
                ["python3", str(validate_script), "--profile", profile, str(working_session), *workspace_args],
                capture_output=True,
                text=True,
            )
            if validate.returncode != 0:
                failures.append(f"示例校验失败: {session_path}\n{validate.stdout.strip()}\n{validate.stderr.strip()}")
                continue
            asset_audit = subprocess.run(
                ["python3", str(asset_audit_script), str(working_session), *workspace_args],
                capture_output=True,
                text=True,
            )
            if asset_audit.returncode != 0:
                failures.append(f"示例资产审计失败: {session_path}\n{asset_audit.stdout.strip()}\n{asset_audit.stderr.strip()}")
                continue
            handoff_output = working_dir / ".release-audit-handoff.md"
            handoff = subprocess.run(
                ["python3", str(handoff_script), str(working_session), "--output", str(handoff_output), *workspace_args],
                capture_output=True,
                text=True,
            )
            if handoff.returncode != 0:
                failures.append(f"示例 handoff 导出失败: {session_path}\n{handoff.stdout.strip()}\n{handoff.stderr.strip()}")


def load_bundle_targets(root: Path) -> list[Path]:
    manifest_path = root / "public_bundle_manifest.json"
    manifest = load_json(manifest_path)
    if not isinstance(manifest, dict):
        raise StoryboardError("bundle manifest 结构错误", f"{manifest_path} 不是对象。", "修正 public_bundle_manifest.json 后重试。")
    include = manifest.get("include", [])
    if not isinstance(include, list) or not include:
        raise StoryboardError("bundle manifest 缺少 include", f"{manifest_path} 没有有效 include 列表。", "在 manifest 中列出需要公开发布的文件和目录。")
    validate_bundle_name(manifest.get("bundle_name"))
    return [safe_manifest_source(root, item)[1] for item in include]


def audit_built_artifact(bundle_root: Path, failures: list[str]) -> None:
    audit_text_files(bundle_root, failures)
    audit_private_markers(bundle_root, failures)

    main_skill = bundle_root / "storyboard-scene-pipeline-skill" / "SKILL.md"
    if main_skill.exists():
        text = main_skill.read_text(encoding="utf-8")
        if not re.search(r"(?m)^name:\s*storyboard-director\s*$", text):
            failures.append(f"构建产物主 skill 名称不是 storyboard-director: {main_skill}")
    else:
        failures.append(f"构建产物缺少主 Skill: {main_skill}")

    readme = bundle_root / "README.md"
    developer_reference = bundle_root / "docs" / "developer-reference.md"
    if readme.exists() and "docs/developer-reference.md" in readme.read_text(encoding="utf-8") and not developer_reference.exists():
        failures.append("构建产物 README 引用了缺失的 docs/developer-reference.md")

    with tempfile.TemporaryDirectory(prefix="storyboard-install-audit-") as codex_home:
        installer = bundle_root / "storyboard-scene-pipeline-skill" / "scripts" / "install_storyboard_skills.py"
        doctor = bundle_root / "storyboard-scene-pipeline-skill" / "scripts" / "doctor_storyboard_skill.py"
        install = subprocess.run(
            ["python3", str(installer), "--copy", "--codex-home", codex_home],
            capture_output=True,
            text=True,
        )
        if install.returncode != 0:
            failures.append(f"构建产物 copy 安装失败:\n{install.stdout.strip()}\n{install.stderr.strip()}")
            return
        health = subprocess.run(
            [
                "python3",
                str(doctor),
                "--workspace-root",
                str(bundle_root),
                "--codex-home",
                codex_home,
            ],
            capture_output=True,
            text=True,
        )
        if health.returncode != 0:
            failures.append(f"构建产物安装后 doctor 失败:\n{health.stdout.strip()}\n{health.stderr.strip()}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build and audit the exact public storyboard bundle.")
    return parser.parse_args()


def main() -> int:
    parse_args()
    try:
        config = resolve_workspace_config()
        root = config.workspace_root
        failures: list[str] = []
        bundle_targets = load_bundle_targets(root)
        manifest = load_json(root / "public_bundle_manifest.json")
        if not isinstance(manifest, dict):
            raise StoryboardError("bundle manifest 结构错误", "public_bundle_manifest.json 不是对象。", "修正 manifest 后重试。")

        for path in bundle_targets:
            if not path.exists():
                failures.append(f"manifest 指向的公共路径不存在: {path}")

        for path in bundle_targets:
            if not path.exists():
                continue
            audit_text_files(path, failures)
            audit_private_markers(path, failures)
        built_bundle = build_bundle(root, manifest)
        audit_built_artifact(built_bundle, failures)
        audit_examples(built_bundle, failures)

        if failures:
            print("RELEASE AUDIT FAILED")
            for failure in failures:
                print(f"- {failure}")
            return 1

        print("RELEASE AUDIT PASSED")
        print(f"artifact={built_bundle}")
        return 0
    except StoryboardError as error:
        print_error(error)
        return 1
    except Exception as error:  # pragma: no cover - defensive CLI fallback
        print("问题: release audit 发生未预期错误", file=sys.stderr)
        print(f"原因: {error}", file=sys.stderr)
        print("下一步: 先确认公共示例可以渲染，再重新执行审计。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
