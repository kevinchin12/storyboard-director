#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import IO


CONFIG_FILENAME = "storyboard.config.json"
DEFAULT_SESSION_DIR = "sessions"
DEFAULT_EXAMPLES_DIR = "examples"
DEFAULT_ASSETS_DIR = "assets"
DEFAULT_STATE_FILENAME = "session.json"
DEFAULT_HTML_FILENAME = "session.html"
VALID_PROJECT_MODES = {"character", "subject", "spatial", "atmospheric"}
VALIDATION_PROFILES = {"smoke", "workflow", "release"}


class StoryboardError(RuntimeError):
    def __init__(self, problem: str, reason: str, next_step: str) -> None:
        super().__init__(problem)
        self.problem = problem
        self.reason = reason
        self.next_step = next_step


@dataclass
class WorkspaceConfig:
    workspace_root: Path
    config_path: Path
    sessions_dir: Path
    examples_dir: Path
    assets_dirname: str
    state_filename: str
    html_filename: str


def print_error(error: StoryboardError) -> None:
    print(f"问题: {error.problem}", file=sys.stderr)
    print(f"原因: {error.reason}", file=sys.stderr)
    print(f"下一步: {error.next_step}", file=sys.stderr)


def load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise StoryboardError(
            problem="JSON 文件不存在",
            reason=f"找不到文件: {path}",
            next_step="确认路径是否正确，或先运行初始化脚本创建 session。",
        ) from exc
    except json.JSONDecodeError as exc:
        raise StoryboardError(
            problem="JSON 文件无法解析",
            reason=f"{path} 不是合法 JSON: {exc}",
            next_step="修正 JSON 语法后重试。",
        ) from exc


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    target_mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
            temp_path = Path(handle.name)
        os.chmod(temp_path, target_mode)
        temp_path.replace(path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def write_bytes_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    target_mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
            temp_path = Path(handle.name)
        os.chmod(temp_path, target_mode)
        temp_path.replace(path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def dump_json(path: Path, payload: object) -> None:
    write_text_atomic(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def slugify(text: str) -> str:
    lowered = text.strip().lower()
    cleaned = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", lowered)
    collapsed = re.sub(r"-{2,}", "-", cleaned).strip("-")
    return collapsed or "story-session"


def resolve_script_root() -> Path:
    return Path(__file__).resolve().parents[1]


def find_config(start: Path) -> Path | None:
    current = start.resolve()
    for candidate in [current, *current.parents]:
        config_path = candidate / CONFIG_FILENAME
        if config_path.exists():
            return config_path
    return None


def resolve_workspace_config(workspace_root: str | None = None, config_path: str | None = None) -> WorkspaceConfig:
    if workspace_root:
        root = Path(workspace_root).expanduser().resolve()
        candidate = root / CONFIG_FILENAME
        if not candidate.exists():
            raise StoryboardError(
                problem="工作区配置缺失",
                reason=f"在指定目录中找不到 {CONFIG_FILENAME}: {candidate}",
                next_step="在工作区根目录创建配置文件，或改用 --config 指向配置文件。",
            )
        config_file = candidate
    elif config_path:
        config_file = Path(config_path).expanduser().resolve()
        if not config_file.exists():
            raise StoryboardError(
                problem="配置文件不存在",
                reason=f"找不到配置文件: {config_file}",
                next_step="确认 --config 路径，或先在工作区根目录放置 storyboard.config.json。",
            )
    else:
        discovered = find_config(Path.cwd())
        if not discovered:
            raise StoryboardError(
                problem="无法发现工作区配置",
                reason=f"从当前目录向上查找不到 {CONFIG_FILENAME}",
                next_step="在工作区根目录创建 storyboard.config.json，或用 --workspace-root / --config 明确指定。",
            )
        config_file = discovered

    payload = load_json(config_file)
    if not isinstance(payload, dict):
        raise StoryboardError(
            problem="配置文件结构错误",
            reason=f"{config_file} 不是 JSON object。",
            next_step="将 storyboard.config.json 改成对象结构，并包含 paths 字段。",
        )

    paths = payload.get("paths", {})
    if not isinstance(paths, dict):
        raise StoryboardError(
            problem="配置文件缺少 paths",
            reason=f"{config_file} 中的 paths 字段不存在或不是对象。",
            next_step="在 storyboard.config.json 中添加 paths.sessions_dir 等字段。",
        )

    root = config_file.parent.resolve()

    def config_directory(field: str, default: str) -> Path:
        raw_value = str(paths.get(field, default)).strip()
        raw_path = Path(raw_value)
        candidate = (root / raw_path).resolve()
        if not raw_value or raw_path.is_absolute() or candidate == root or not is_path_within(candidate, root):
            raise StoryboardError(
                problem="工作区路径配置不安全",
                reason=f"paths.{field} 必须是工作区内的相对目录: {raw_value!r}",
                next_step=f"把 paths.{field} 改成类似 {default!r} 的相对路径。",
            )
        return candidate

    def config_name(field: str, default: str) -> str:
        raw_value = str(paths.get(field, default)).strip()
        raw_path = Path(raw_value)
        if not raw_value or raw_path.is_absolute() or raw_path.name != raw_value or raw_value in {".", ".."}:
            raise StoryboardError(
                problem="Session 文件名配置不安全",
                reason=f"paths.{field} 必须是单个文件或目录名: {raw_value!r}",
                next_step=f"把 paths.{field} 改成类似 {default!r} 的名称。",
            )
        return raw_value

    sessions_dir = config_directory("sessions_dir", DEFAULT_SESSION_DIR)
    examples_dir = config_directory("examples_dir", DEFAULT_EXAMPLES_DIR)
    assets_dirname = config_name("assets_dirname", DEFAULT_ASSETS_DIR)
    state_filename = config_name("state_filename", DEFAULT_STATE_FILENAME)
    html_filename = config_name("html_filename", DEFAULT_HTML_FILENAME)
    if sessions_dir == examples_dir:
        raise StoryboardError(
            problem="工作区目录配置冲突",
            reason="paths.sessions_dir 和 paths.examples_dir 不能指向同一个目录。",
            next_step="为 sessions_dir 和 examples_dir 使用不同的工作区内相对目录。",
        )
    if len({assets_dirname, state_filename, html_filename}) != 3:
        raise StoryboardError(
            problem="Session 名称配置冲突",
            reason="paths.assets_dirname、paths.state_filename 和 paths.html_filename 必须互不相同。",
            next_step="分别使用类似 assets、session.json 和 session.html 的名称。",
        )

    return WorkspaceConfig(
        workspace_root=root,
        config_path=config_file,
        sessions_dir=sessions_dir,
        examples_dir=examples_dir,
        assets_dirname=assets_dirname,
        state_filename=state_filename,
        html_filename=html_filename,
    )


def ensure_workspace_dirs(config: WorkspaceConfig) -> None:
    config.sessions_dir.mkdir(parents=True, exist_ok=True)
    config.examples_dir.mkdir(parents=True, exist_ok=True)


def session_paths(config: WorkspaceConfig, session_dir: Path) -> tuple[Path, Path, Path]:
    return (
        session_dir / config.state_filename,
        session_dir / config.html_filename,
        session_dir / config.assets_dirname,
    )


def session_html_path(config: WorkspaceConfig, state_path: Path) -> Path:
    return state_path.resolve().parent / config.html_filename


def is_path_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def resolve_child_path(parent: Path, raw_path: str, label: str) -> Path:
    relative = Path(raw_path)
    if relative.is_absolute():
        raise StoryboardError(
            problem=f"{label} 不能使用绝对路径",
            reason=f"收到工作目录之外的输出路径: {raw_path}",
            next_step="只传 assets/ 目录内的相对文件名或相对子目录。",
        )
    target = (parent / relative).resolve()
    if target == parent.resolve() or not is_path_within(target, parent):
        raise StoryboardError(
            problem=f"{label} 超出 assets 目录",
            reason=f"输出路径会写到 session assets 之外: {raw_path}",
            next_step="删除 .. 或绝对路径，只使用 assets/ 内部路径。",
        )
    return target


def infer_session_dir(config: WorkspaceConfig, state_path: Path) -> Path:
    if state_path.is_dir():
        return state_path.resolve()
    return state_path.resolve().parent


def resolve_state_path(config: WorkspaceConfig, raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        cwd_candidate = (Path.cwd() / path).resolve()
        workspace_candidate = (config.workspace_root / path).resolve()
        path = cwd_candidate if cwd_candidate.exists() else workspace_candidate
    if path.is_dir():
        path = path / config.state_filename
    resolved = path.resolve()
    if not any(is_path_within(resolved, root) for root in (config.sessions_dir, config.examples_dir)):
        raise StoryboardError(
            problem="Session 路径超出工作区",
            reason=f"Session 必须位于配置的 sessions/ 或 examples/ 目录内: {resolved}",
            next_step="把 session 放回当前 storyboard 工作区，或使用匹配该 session 的 --workspace-root / --config。",
        )
    return resolved


def acquire_session_lock(state_path: Path, timeout_seconds: float = 30.0) -> IO[str]:
    """Acquire a process lock for one session's read-modify-write transaction."""
    lock_path = state_path.resolve().parent / ".storyboard-session.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+", encoding="utf-8")
    deadline = time.monotonic() + timeout_seconds

    try:
        if os.name == "nt":  # pragma: no cover - exercised on Windows hosts
            import msvcrt

            while True:
                try:
                    handle.seek(0)
                    if handle.read(1) == "":
                        handle.write("\0")
                        handle.flush()
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise StoryboardError(
                            "Session 正在被其他进程更新",
                            f"等待写锁超时: {lock_path}",
                            "等待当前登记或更新完成后重试。",
                        )
                    time.sleep(0.05)
        else:
            import fcntl

            while True:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise StoryboardError(
                            "Session 正在被其他进程更新",
                            f"等待写锁超时: {lock_path}",
                            "等待当前登记或更新完成后重试。",
                        )
                    time.sleep(0.05)
    except Exception:
        handle.close()
        raise

    return handle


def registered_asset_claims(state: dict[str, object]) -> list[tuple[str, str, str]]:
    claims: list[tuple[str, str, str]] = []

    visual = state.get("visual_references", {})
    if isinstance(visual, dict):
        for field in ("characters", "scenes"):
            items = visual.get(field, [])
            if not isinstance(items, list):
                continue
            for index, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                path = str(item.get("path", "")).strip()
                if path:
                    key = str(item.get("label", "")).strip() or str(index)
                    claims.append((path, f"visual_references.{field}", key))

    style = state.get("style_reference", {})
    if isinstance(style, dict):
        items = style.get("assets", [])
        if isinstance(items, list):
            for index, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                path = str(item.get("path", "")).strip()
                if path:
                    key = str(item.get("label", "")).strip() or str(index)
                    claims.append((path, "style_reference.assets", key))

    for section_name in ("line_art", "final_generation"):
        section = state.get(section_name, {})
        if not isinstance(section, dict):
            continue
        gallery = section.get("gallery", [])
        if not isinstance(gallery, list):
            continue
        for index, item in enumerate(gallery):
            if not isinstance(item, dict):
                continue
            path = str(item.get("path", "")).strip()
            if path:
                key = (
                    str(item.get("shot_id", "")).strip()
                    or str(item.get("label", "")).strip()
                    or str(index)
                )
                claims.append((path, f"{section_name}.gallery", key))

    sheet = state.get("storyboard_sheet", {})
    if isinstance(sheet, dict):
        path = str(sheet.get("path", "")).strip()
        if path:
            claims.append((path, "storyboard_sheet", "storyboard_sheet"))

    return claims


def asset_path_owner(
    state: dict[str, object],
    asset_path: str,
    expected_section: str,
    expected_key: str,
) -> tuple[str, str] | None:
    for path, section, key in registered_asset_claims(state):
        if path == asset_path and (section, key) != (expected_section, expected_key):
            return section, key
    return None


def normalize_asset_key(value: object) -> str:
    return "".join(character for character in str(value or "").strip().casefold() if character.isalnum())


def asset_has_explicit_shot_key(item: dict[str, object]) -> bool:
    return any(str(item.get(field, "")).strip() for field in ("shot_id", "shot", "id"))


def asset_matches_shot(item: dict[str, object], shot: dict[str, object]) -> bool:
    shot_key = normalize_asset_key(shot.get("id", ""))
    if not shot_key:
        return False

    has_explicit_key = False
    for field in ("shot_id", "shot", "id"):
        candidate = str(item.get(field, "")).strip()
        if not candidate:
            continue
        has_explicit_key = True
        if normalize_asset_key(candidate) == shot_key:
            return True

    if has_explicit_key:
        return False

    shot_tokens = re.findall(r"[^\W_]+", str(shot.get("id", "")).casefold(), flags=re.UNICODE)
    label_tokens = re.findall(r"[^\W_]+", str(item.get("label", "")).casefold(), flags=re.UNICODE)
    if shot_tokens and len(label_tokens) >= len(shot_tokens):
        for index in range(len(label_tokens) - len(shot_tokens) + 1):
            if label_tokens[index : index + len(shot_tokens)] == shot_tokens:
                return True

    label_key = normalize_asset_key(item.get("label", ""))
    return bool(label_key and not any(character.isdigit() for character in shot_key) and label_key.startswith(shot_key))


def shot_asset_for(
    gallery: list[dict[str, object]],
    shot: dict[str, object],
    index: int,
) -> dict[str, object] | None:
    # Explicit Shot IDs always win over legacy label or positional inference.
    for item in gallery:
        if asset_has_explicit_shot_key(item) and asset_matches_shot(item, shot):
            return item

    for item in gallery:
        if not asset_has_explicit_shot_key(item) and asset_matches_shot(item, shot):
            return item

    # Legacy unkeyed galleries may coexist with newly keyed entries during migration.
    # Positional fallback is safe only when the item at this exact index is unkeyed.
    if index < len(gallery) and not asset_has_explicit_shot_key(gallery[index]):
        return gallery[index]
    return None


def normalize_video_prompt(prompt: object) -> dict[str, object]:
    base = {
        "seedance2": "",
        "reference_frame": "",
        "duration": "",
        "primary_motion": "",
        "camera_motion": "",
        "preserve": [],
        "avoid": [],
        "audio": "",
        "notes": "",
    }
    if isinstance(prompt, dict):
        base.update(prompt)
    elif prompt:
        base["seedance2"] = str(prompt)
    return base


def ensure_state_shape(state: dict[str, object]) -> dict[str, object]:
    shots = state.get("shots", [])
    if isinstance(shots, list):
        normalized = []
        for shot in shots:
            if isinstance(shot, dict):
                copy = dict(shot)
                copy["video_prompt"] = normalize_video_prompt(copy.get("video_prompt"))
                normalized.append(copy)
            else:
                normalized.append(shot)
        state["shots"] = normalized
    return state


def run_python_script(script_path: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(script_path), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def discover_sessions(config: WorkspaceConfig) -> list[Path]:
    if not config.sessions_dir.exists():
        return []
    return sorted(path for path in config.sessions_dir.iterdir() if path.is_dir())
