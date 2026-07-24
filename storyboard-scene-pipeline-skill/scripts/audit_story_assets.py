#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from storyboard_common import (
    StoryboardError,
    ensure_state_shape,
    is_path_within,
    print_error,
    resolve_state_path,
    resolve_workspace_config,
    session_html_path,
)


INLINE_DATA_TOKENS = ("data:image/", "data:application/", ";base64,")
MAX_SESSION_JSON_BYTES = 1_000_000
MAX_RENDERED_HTML_BYTES = 2_000_000
WARN_ASSET_BYTES = 20_000_000
WARN_LINE_ART_BYTES = 1_500_000


def format_bytes(size: int) -> str:
    units = ("B", "KB", "MB", "GB")
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)}B"
            return f"{value:.1f}{unit}"
        value /= 1024
    return f"{size}B"


def contains_inline_data(text: str) -> bool:
    lowered = text.lower()
    return any(token in lowered for token in INLINE_DATA_TOKENS)


def iter_strings(value: object):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from iter_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_strings(child)


def iter_asset_paths(value: object):
    image_suffixes = (".png", ".jpg", ".jpeg", ".webp")
    for text in iter_strings(value):
        raw = text.strip()
        if not raw or raw.lower().startswith("data:"):
            continue
        if raw.lower().endswith(image_suffixes):
            yield raw


def resolve_asset(state_path: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return state_path.parent / path


def display_asset_path(state_path: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(state_path.parent.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def collect_asset_files(assets_dir: Path) -> list[Path]:
    if not assets_dir.exists():
        return []
    return sorted(path for path in assets_dir.rglob("*") if path.is_file())


def iter_gallery_paths(state: dict[str, object], key: str) -> list[str]:
    section = state.get(key)
    if not isinstance(section, dict):
        return []
    gallery = section.get("gallery")
    if not isinstance(gallery, list):
        return []
    paths: list[str] = []
    for item in gallery:
        if not isinstance(item, dict):
            continue
        raw_path = str(item.get("path", "")).strip()
        if raw_path:
            paths.append(raw_path)
    return paths


def audit(state_path: Path, assets_dirname: str, html_path: Path | None = None) -> tuple[list[str], list[str]]:
    failures: list[str] = []
    warnings: list[str] = []

    raw_state = state_path.read_text(encoding="utf-8")
    state = ensure_state_shape(json.loads(raw_state))
    html_path = html_path or state_path.with_suffix(".html")
    assets_dir = state_path.parent / assets_dirname

    state_bytes = len(raw_state.encode("utf-8"))
    if state_bytes > MAX_SESSION_JSON_BYTES:
        failures.append(f"session.json too large: {format_bytes(state_bytes)}")
    if contains_inline_data(raw_state):
        failures.append("session.json contains inline data/base64 payloads")

    if html_path.exists():
        raw_html = html_path.read_text(encoding="utf-8")
        html_bytes = len(raw_html.encode("utf-8"))
        if html_bytes > MAX_RENDERED_HTML_BYTES:
            failures.append(f"session.html too large: {format_bytes(html_bytes)}")
        if contains_inline_data(raw_html):
            failures.append("session.html contains inline data/base64 payloads")
    else:
        html_bytes = 0
        warnings.append(f"session.html missing: {html_path}")

    missing_refs: list[str] = []
    external_refs: list[str] = []
    inline_refs: list[str] = []
    for raw_path in sorted(set(iter_asset_paths(state))):
        if raw_path.lower().startswith("data:"):
            inline_refs.append(raw_path[:80])
            continue
        resolved = resolve_asset(state_path, raw_path)
        if Path(raw_path).is_absolute() or not is_path_within(resolved, assets_dir):
            external_refs.append(raw_path)
            continue
        if not resolved.exists():
            missing_refs.append(raw_path)

    if inline_refs:
        failures.append(f"inline asset references found: {len(inline_refs)}")
    if external_refs:
        failures.append(f"asset references outside session assets: {', '.join(external_refs[:5])}")
    if missing_refs:
        failures.append(f"missing referenced assets: {', '.join(missing_refs[:5])}")

    asset_files = collect_asset_files(assets_dir)
    total_asset_bytes = sum(path.stat().st_size for path in asset_files)
    large_assets = [path for path in asset_files if path.stat().st_size > WARN_ASSET_BYTES]
    for path in large_assets[:5]:
        warnings.append(f"large asset: {display_asset_path(state_path, path)} ({format_bytes(path.stat().st_size)})")

    for raw_path in iter_gallery_paths(state, "line_art"):
        resolved = resolve_asset(state_path, raw_path)
        if not resolved.exists() or not resolved.is_file():
            continue
        size = resolved.stat().st_size
        if size > WARN_LINE_ART_BYTES:
            warnings.append(
                f"heavy line-art asset: {display_asset_path(state_path, resolved)} ({format_bytes(size)}); "
                "retry as contour-only line art with no shadows, hatching, gray fills, texture, or detail"
            )

    print("STORY SESSION WEIGHT")
    print(f"state={state_path}")
    print(f"session.json={format_bytes(state_bytes)}")
    print(f"session.html={format_bytes(html_bytes) if html_path.exists() else 'missing'}")
    print(f"assets={len(asset_files)} files, {format_bytes(total_asset_bytes)}")
    if asset_files:
        print("largest_assets:")
        for path in sorted(asset_files, key=lambda item: item.stat().st_size, reverse=True)[:5]:
            print(f"- {display_asset_path(state_path, path)} {format_bytes(path.stat().st_size)}")
    if warnings:
        print("WARNINGS")
        for warning in warnings:
            print(f"- {warning}")
    if failures:
        print("FAILED")
        for failure in failures:
            print(f"- {failure}")
    else:
        print("PASSED")

    return failures, warnings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit local raster assets and HTML links for one storyboard session.")
    parser.add_argument("session", help="Session directory or session JSON path.")
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
        failures, _ = audit(
            state_path,
            config.assets_dirname,
            html_path=session_html_path(config, state_path),
        )
        return 1 if failures else 0
    except StoryboardError as error:
        print_error(error)
        return 1
    except Exception as error:  # pragma: no cover - defensive CLI fallback
        print("问题: asset audit 发生未预期错误", file=sys.stderr)
        print(f"原因: {error}", file=sys.stderr)
        print("下一步: 先确认 session.json 可以解析，再重新执行审计。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
