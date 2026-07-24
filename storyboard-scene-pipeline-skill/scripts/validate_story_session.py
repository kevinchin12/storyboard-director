#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from storyboard_common import (
    StoryboardError,
    VALID_PROJECT_MODES,
    VALIDATION_PROFILES,
    ensure_state_shape,
    is_path_within,
    normalize_asset_key,
    print_error,
    resolve_state_path,
    resolve_workspace_config,
    session_html_path,
    shot_asset_for,
)


REQUIRED_SHOT_FIELDS = ("id", "duration", "frame", "camera", "action")
REQUIRED_REFERENCE_FIELDS = ("primary_anchor", "continuity_rules", "world_lock", "video_asset_policy")
STAGE_ORDER = ("outline", "script", "revision", "line-art", "style", "final")
SAME_LAYOUT_TOKENS = (
    "same layout",
    "same space",
    "same room",
    "same location",
    "same axis",
    "same route",
    "同一布局",
    "同一空间",
    "同一房间",
    "同一路径",
    "同一地点",
    "同一场景",
    "同轴",
)
ALLOWED_CHANGE_TOKENS = (
    "allowed change",
    "allowed changes",
    "may change",
    "can change",
    "only change",
    "only changes",
    "允许变化",
    "允许改变",
    "可变化",
    "可改变",
    "只允许",
    "仅允许",
)
CAMERA_RELATION_TOKENS = (
    "pullback",
    "pull back",
    "push-in",
    "push in",
    "side-track",
    "side track",
    "orbit",
    "reveal",
    "same axis",
    "same-lens",
    "same lens",
    "wider view",
    "closer view",
    "拉远",
    "推进",
    "侧移",
    "绕行",
    "揭示",
    "同轴",
    "后拉",
)
CONTINUOUS_SHOT_TOKENS = (
    "continuous shot",
    "continuous move",
    "one-shot",
    "one shot",
    "unbroken",
    "no-cut",
    "no cut",
    "same-lens",
    "same lens",
    "one physical camera path",
    "developing master",
    "一镜到底",
    "连续镜头",
    "无剪切",
    "无切",
    "同一虚拟镜头",
)
WIDE_TOKENS = ("wide", "24mm", "35mm", "wide shot", "广角", "大全景", "全景")
TELE_TOKENS = ("telephoto", "85mm", "135mm", "长焦", "tele")
PUSH_TOKENS = ("push-in", "push in", "推进")
PULL_TOKENS = ("pullback", "pull back", "后拉", "拉远")
SEQUENCE_TOKENS = ("then", "after", "before", "随后", "然后", "再", "之后", "最终", "先", "后")
INLINE_DATA_TOKENS = ("data:image/", "data:application/", ";base64,")
MAX_SESSION_JSON_BYTES = 1_000_000
MAX_RENDERED_HTML_BYTES = 2_000_000
MAX_STRING_VALUE_CHARS = 40_000
ASPECT_RATIO_RE = re.compile(r"^\s*\d+(?:\.\d+)?\s*[:xX]\s*\d+(?:\.\d+)?\s*$")
VALID_DISPATCH_MODES = {"multi_agent", "reduced_concurrency", "serial_unavailable"}
VALID_VIDEO_INPUT_MODES = {"text_only", "image_guided"}
AGGREGATE_MUSIC_LINE = "音乐:不要生成任何背景音乐和旋律，只需要生成场景及动作对应的音效"
SHOT_HANDLE_RE = re.compile(r"@(?:assets[/\\])?shot[\s_-]*\d+", re.IGNORECASE)
SHOT_FRAME_ASSET_RE = re.compile(
    r"(?:assets[/\\])?shot[\s_-]*\d+[\s_-]*(?:line|final|storyboard|frame)(?:\.(?:png|jpe?g|webp))?",
    re.IGNORECASE,
)
GENERATED_FRAME_DEPENDENCY_RES = (
    re.compile(
        r"(?:upload|attach|provide|input|use|using|refer(?:ence)?(?:\s+to)?).{0,32}"
        r"(?:storyboard|line[\s-]*art|final\s+frame|start(?:ing)?\s+frame|end(?:ing)?\s+frame|reference\s+frame)",
        re.IGNORECASE,
    ),
    re.compile(r"(?:上传|添加|提供|输入|使用|采用|参照|参考|指定|调用).{0,16}(?:分镜(?:图|画面)?|线稿|最终帧|起始帧|开始帧|结束帧|参考帧)"),
    re.compile(r"(?:将|把|以).{0,8}(?:分镜(?:图|画面)?|线稿|最终帧|起始帧|开始帧|结束帧|参考帧).{0,12}(?:作为|当作|用作|上传|参考)"),
)
GENERATED_STORYBOARD_DEPENDENCY_RES = (
    re.compile(
        r"(?:upload|attach|provide|input|use|using|refer(?:ence)?(?:\s+to)?).{0,32}"
        r"(?:storyboard|line[\s-]*art|final\s+frame)",
        re.IGNORECASE,
    ),
    re.compile(r"(?:上传|添加|提供|输入|使用|采用|参照|参考|指定|调用).{0,16}(?:分镜(?:图|画面)?|线稿|最终帧)"),
    re.compile(r"(?:将|把|以).{0,8}(?:分镜(?:图|画面)?|线稿|最终帧).{0,12}(?:作为|当作|用作|上传|参考)"),
)
NEGATED_GENERATED_INPUT_RES = (
    re.compile(
        r"(?:do(?:es)?\s+not|never).{0,24}(?:require|ask).{0,32}"
        r"(?:upload|attach|provide|input|use).{0,32}"
        r"(?:storyboard|line[\s-]*art|final\s+frame|reference\s+frame)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:不依赖(?:或要求)?|不要求|无需|不需要|不得|禁止).{0,20}"
        r"(?:上传|添加|提供|输入|使用|采用|参照|参考|指定|调用).{0,16}"
        r"(?:分镜(?:图|画面)?|线稿|最终帧|起始帧|开始帧|结束帧|参考帧)"
    ),
)


def resolve_asset(state_path: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return state_path.parent / path


def require(condition: bool, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(message)


def copy_ready_dependency(text: str, *, allow_confirmed_reference_frames: bool = False) -> str | None:
    if SHOT_HANDLE_RE.search(text):
        return "contains an @shotXX handle"
    if SHOT_FRAME_ASSET_RE.search(text):
        return "contains a generated per-shot line/final asset path"
    dependency_text = text
    for pattern in NEGATED_GENERATED_INPUT_RES:
        dependency_text = pattern.sub("", dependency_text)
    dependency_patterns = (
        GENERATED_STORYBOARD_DEPENDENCY_RES
        if allow_confirmed_reference_frames
        else GENERATED_FRAME_DEPENDENCY_RES
    )
    if any(pattern.search(dependency_text) for pattern in dependency_patterns):
        return "requires generated storyboard, line-art, or frame imagery as an external input"
    return None


def validate_copy_ready_video_inputs(
    state: dict[str, object],
    shots: list[dict[str, object]],
    failures: list[str],
) -> None:
    """Enforce the new contract only for sessions that explicitly declare an input mode."""
    video_generation = state.get("video_generation", {})
    if not isinstance(video_generation, dict) or "input_mode" not in video_generation:
        return

    input_mode = str(video_generation.get("input_mode", "")).strip().lower()
    require(
        input_mode in VALID_VIDEO_INPUT_MODES,
        "video_generation.input_mode must be text_only or image_guided",
        failures,
    )

    aggregate = str(state.get("aggregate_video_prompt", "")).strip()
    allow_confirmed_frames = input_mode == "image_guided"
    reason = (
        copy_ready_dependency(aggregate, allow_confirmed_reference_frames=allow_confirmed_frames)
        if aggregate
        else None
    )
    require(reason is None, f"aggregate_video_prompt {reason}", failures)

    for shot in shots:
        shot_id = str(shot.get("id", "Unknown shot"))
        prompt = shot.get("video_prompt")
        if not isinstance(prompt, dict):
            continue
        seedance = str(prompt.get("seedance2", "")).strip()
        reason = (
            copy_ready_dependency(seedance, allow_confirmed_reference_frames=allow_confirmed_frames)
            if seedance
            else None
        )
        require(reason is None, f"{shot_id} visible video prompt {reason}", failures)
        reference_frame = str(prompt.get("reference_frame", "")).strip()
        require(
            not reference_frame or not (SHOT_HANDLE_RE.search(reference_frame) or SHOT_FRAME_ASSET_RE.search(reference_frame)),
            f"{shot_id} video_prompt.reference_frame cannot point to generated per-shot storyboard imagery",
            failures,
        )
        if input_mode == "text_only":
            require(
                not reference_frame,
                f"{shot_id} video_prompt.reference_frame must be empty in text_only mode",
                failures,
            )


def validate_video_reference_frame_files(
    state_path: Path,
    state: dict[str, object],
    shots: list[dict[str, object]],
    assets_dirname: str,
    failures: list[str],
) -> None:
    video_generation = state.get("video_generation", {})
    if not isinstance(video_generation, dict):
        return
    input_mode = str(video_generation.get("input_mode", "")).strip().lower()
    if input_mode != "image_guided":
        return

    assets_dir = state_path.parent / assets_dirname
    for shot in shots:
        shot_id = str(shot.get("id", "Unknown shot"))
        prompt = shot.get("video_prompt")
        if not isinstance(prompt, dict):
            continue
        raw_path = str(prompt.get("reference_frame", "")).strip()
        if not raw_path:
            continue
        require(
            not is_inline_data_reference(raw_path),
            f"{shot_id} video_prompt.reference_frame uses inline image data",
            failures,
        )
        if is_inline_data_reference(raw_path):
            continue
        reference_path = resolve_asset(state_path, raw_path)
        require(
            not Path(raw_path).is_absolute(),
            f"{shot_id} video_prompt.reference_frame uses an absolute path: {raw_path}",
            failures,
        )
        require(
            is_path_within(reference_path, assets_dir),
            f"{shot_id} video_prompt.reference_frame is outside the session assets directory: {raw_path}",
            failures,
        )
        require(reference_path.exists(), f"{shot_id} video_prompt.reference_frame file is missing: {reference_path}", failures)
        require(
            reference_path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"},
            f"{shot_id} video_prompt.reference_frame is not a raster image: {raw_path}",
            failures,
        )


def contains_any(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token in text for token in tokens)


def is_inline_data_reference(text: str) -> bool:
    lowered = text.strip().lower()
    return lowered.startswith("data:") or contains_any(lowered, INLINE_DATA_TOKENS)


def iter_string_values(value: object, path: str = "$"):
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from iter_string_values(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from iter_string_values(child, f"{path}[{index}]")


def validate_session_weight(state_path: Path, raw_state: str, state: dict[str, object], failures: list[str]) -> None:
    raw_bytes = len(raw_state.encode("utf-8"))
    require(
        raw_bytes <= MAX_SESSION_JSON_BYTES,
        f"session.json is too large ({raw_bytes // 1024}KB); keep images as asset file paths, not inline payloads or history dumps",
        failures,
    )
    require(
        not contains_any(raw_state.lower(), INLINE_DATA_TOKENS),
        "session.json contains inline data/base64 payloads; store raster files under assets/ and reference their paths",
        failures,
    )

    oversized = [
        f"{path} ({len(text)} chars)"
        for path, text in iter_string_values(state)
        if len(text) > MAX_STRING_VALUE_CHARS or is_inline_data_reference(text)
    ]
    if oversized:
        sample = ", ".join(oversized[:3])
        require(False, f"session.json has oversized or inline-data string fields: {sample}", failures)


def stage_index(current_stage: object) -> int:
    stage = str(current_stage or "").strip().lower()
    normalized = "line-art" if stage == "line_art" else stage
    normalized = "style" if normalized == "style_reference" else normalized
    normalized = "final" if normalized in {"final_generation", "video_generation"} else normalized
    if normalized not in STAGE_ORDER:
        return 0
    return STAGE_ORDER.index(normalized)


def should_require_line_art(state: dict[str, object], profile: str) -> bool:
    if profile == "release":
        return True
    return stage_index(state.get("current_stage")) >= STAGE_ORDER.index("line-art")


def validate_title_translation(state: dict[str, object], failures: list[str]) -> None:
    # Legacy sessions predate this field; new sessions include it in the state template.
    if "project_title_en" not in state:
        return
    if stage_index(state.get("current_stage")) < STAGE_ORDER.index("script"):
        return
    require(
        bool(str(state.get("project_title_en", "")).strip()),
        "project_title_en is missing; preserve the user's English title or translate project_title before script approval",
        failures,
    )


def should_require_final_assets(state: dict[str, object], profile: str) -> bool:
    if not display_option_enabled(state, "show_final_frames", False):
        return False
    if profile == "release":
        return True
    status = str(state.get("final_generation", {}).get("status", "")).strip().lower()
    return stage_index(state.get("current_stage")) >= STAGE_ORDER.index("final") and any(
        token in status for token in ("ready", "complete", "user review")
    )


def should_require_video_package(state: dict[str, object], profile: str) -> bool:
    video_generation = state.get("video_generation", {})
    if not isinstance(video_generation, dict):
        return False
    if profile == "release":
        return True
    if video_generation.get("require_per_shot_prompts") is not True:
        return False
    status = str(video_generation.get("status", "")).strip().lower()
    return "prompt" in status or "video" in status


def should_require_aggregate_prompt(state: dict[str, object], profile: str) -> bool:
    if profile == "release":
        return True
    video_generation = state.get("video_generation", {})
    if not isinstance(video_generation, dict):
        return False
    status = str(video_generation.get("status", "")).strip().lower()
    return "aggregate" in status or "prompt ready" in status or "prompt complete" in status


def display_option_enabled(state: dict[str, object], key: str, default: bool = False) -> bool:
    options = state.get("display_options", {})
    if not isinstance(options, dict):
        return default
    return options.get(key, default) is True


def validate_text_review(state: dict[str, object], failures: list[str]) -> None:
    review = state.get("text_review")
    if review is None:
        require(
            stage_index(state.get("current_stage")) < STAGE_ORDER.index("line-art"),
            "text_review is required before line-art stage starts",
            failures,
        )
        return
    require(isinstance(review, dict), "text_review must be an object", failures)
    if not isinstance(review, dict):
        return

    required_blocks = ("script_logic_check", "line_art_prompt_preflight")
    for block_name in required_blocks:
        block = review.get(block_name)
        require(isinstance(block, dict), f"text_review.{block_name} must be an object", failures)
        if not isinstance(block, dict):
            continue
        status = str(block.get("status", "")).strip().lower()
        require(bool(status), f"text_review.{block_name} missing status", failures)
        require(bool(str(block.get("summary", "")).strip()), f"text_review.{block_name} missing summary", failures)
        if stage_index(state.get("current_stage")) >= STAGE_ORDER.index("line-art"):
            require(
                status not in {"pending", "not_started", "not started", "waiting"},
                f"text_review.{block_name} is still pending after line-art stage started",
                failures,
            )
            blocking_issues = block.get("blocking_issues", [])
            require(
                isinstance(blocking_issues, list) and not blocking_issues,
                f"text_review.{block_name} still has unresolved blocking issues",
                failures,
            )


def validate_asset_gallery(
    state_path: Path,
    gallery: list[dict[str, object]],
    label: str,
    shots: list[dict[str, object]],
    assets_dirname: str,
    failures: list[str],
) -> None:
    expected_count = len(shots)
    require(
        len(gallery) >= expected_count,
        f"{label} gallery has {len(gallery)} items, expected at least {expected_count}",
        failures,
    )

    seen_paths: dict[str, str] = {}
    for index, shot in enumerate(shots, start=1):
        shot_id = str(shot.get("id", f"shot {index}")).strip() or f"shot {index}"
        item = shot_asset_for(gallery, shot, index - 1)
        require(item is not None, f"{label} gallery missing item for {shot_id}", failures)
        if not item:
            continue

        raw_path = str(item.get("path", "")).strip()
        require(bool(raw_path), f"{label} item for {shot_id} has no path", failures)
        if not raw_path:
            continue
        previous_shot = seen_paths.get(raw_path)
        require(
            previous_shot is None or previous_shot == shot_id,
            f"{label} reuses asset path {raw_path} for both {previous_shot} and {shot_id}",
            failures,
        )
        seen_paths.setdefault(raw_path, shot_id)

        require(not is_inline_data_reference(raw_path), f"{label} item for {shot_id} uses inline data instead of an asset path", failures)
        if is_inline_data_reference(raw_path):
            continue
        require(not raw_path.lower().endswith(".svg"), f"{label} item for {shot_id} uses SVG: {raw_path}", failures)
        asset_path = resolve_asset(state_path, raw_path)
        assets_dir = state_path.parent / assets_dirname
        require(not Path(raw_path).is_absolute(), f"{label} item for {shot_id} uses an absolute path: {raw_path}", failures)
        require(
            is_path_within(asset_path, assets_dir),
            f"{label} item for {shot_id} is outside the session assets directory: {raw_path}",
            failures,
        )
        require(asset_path.exists(), f"{label} item for {shot_id} missing file: {asset_path}", failures)
        require(
            asset_path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"},
            f"{label} item for {shot_id} is not a raster image: {raw_path}",
            failures,
        )


def validate_html_asset_links(
    state_path: Path,
    shots: list[dict[str, object]],
    gallery: list[dict[str, object]],
    label: str,
    html_path: Path,
    failures: list[str],
) -> None:
    if not html_path.exists():
        return

    html = html_path.read_text(encoding="utf-8")
    for index, shot in enumerate(shots):
        item = shot_asset_for(gallery, shot, index)
        if not item:
            continue
        raw_path = str(item.get("path", "")).strip()
        if not raw_path or is_inline_data_reference(raw_path):
            continue
        rendered_path = raw_path if Path(raw_path).is_absolute() else Path(raw_path).as_posix()
        shot_id = str(shot.get("id", f"shot {index + 1}")).strip() or f"shot {index + 1}"
        require(
            raw_path in html or rendered_path in html,
            f"HTML does not include {label} path for {shot_id}: {raw_path}",
            failures,
        )


def validate_video_prompts(
    shots: list[dict[str, object]],
    failures: list[str],
    input_mode: str | None = None,
) -> None:
    for shot in shots:
        shot_id = str(shot.get("id", "Unknown shot"))
        prompt = shot.get("video_prompt")
        require(isinstance(prompt, dict), f"{shot_id} video_prompt is missing or not an object", failures)
        if not isinstance(prompt, dict):
            continue

        seedance = str(prompt.get("seedance2", "")).strip()
        require(bool(seedance), f"{shot_id} missing Seedance 2.0 prompt", failures)
        reference_frame = str(prompt.get("reference_frame", "")).strip()
        if input_mode == "text_only":
            require(not reference_frame, f"{shot_id} video_prompt.reference_frame must be empty in text_only mode", failures)
        elif input_mode == "image_guided":
            require(bool(reference_frame), f"{shot_id} missing video_prompt.reference_frame for image_guided mode", failures)
        else:
            # Preserve the validation contract for sessions created before input_mode existed.
            require(bool(reference_frame), f"{shot_id} missing video_prompt.reference_frame", failures)
        require(bool(str(prompt.get("duration", "")).strip()), f"{shot_id} missing video_prompt.duration", failures)
        require(bool(str(prompt.get("primary_motion", "")).strip()), f"{shot_id} missing video_prompt.primary_motion", failures)
        require(bool(str(prompt.get("camera_motion", "")).strip()), f"{shot_id} missing video_prompt.camera_motion", failures)
        require(
            isinstance(prompt.get("preserve"), list) and bool(prompt.get("preserve")),
            f"{shot_id} video_prompt.preserve must be a non-empty list",
            failures,
        )
        require(
            isinstance(prompt.get("avoid"), list) and bool(prompt.get("avoid")),
            f"{shot_id} video_prompt.avoid must be a non-empty list",
            failures,
        )

        if seedance and input_mode is None:
            require(
                any(
                    token in seedance.lower()
                    for token in ("final frame", "line art", "storyboard", "最终静态帧", "线稿", "分镜", "参考帧", "视觉锁定")
                ),
                f"{shot_id} visible video prompt does not identify its storyboard reference frame",
                failures,
            )
        if seedance and input_mode is not None:
            require(
                copy_ready_dependency(
                    seedance,
                    allow_confirmed_reference_frames=input_mode == "image_guided",
                )
                is None,
                f"{shot_id} visible video prompt depends on generated per-shot storyboard imagery",
                failures,
            )
        if seedance:
            require(
                not re.search(r"\b\d+\s*s\b|\d+\s*秒|\b\d+\s*:\s*\d+\b", seedance, re.IGNORECASE),
                f"{shot_id} visible video prompt should not contain duration or aspect ratio",
                failures,
            )
            require(
                any(token in seedance.lower() for token in ("avoid", "no new", "不要", "避免", "禁止")),
                f"{shot_id} visible video prompt lacks avoid constraint",
                failures,
            )


def validate_aggregate_prompt(
    state: dict[str, object],
    shots: list[dict[str, object]],
    failures: list[str],
    required: bool = False,
) -> None:
    prompt = str(state.get("aggregate_video_prompt", "")).strip()
    if not prompt:
        require(not required, "aggregate_video_prompt is required for this delivery gate", failures)
        return

    require(
        prompt.startswith("主体:"),
        "aggregate_video_prompt must start with the fixed subject line `主体:`",
        failures,
    )
    require("\n场景:" in prompt, "aggregate_video_prompt must include the fixed scene line `场景:`", failures)
    require(AGGREGATE_MUSIC_LINE in prompt, "aggregate_video_prompt must include the exact fixed music instruction", failures)

    require(
        not re.search(r"\b\d+\s*s\b|\d+\s*秒|\b\d+\s*:\s*\d+\b", prompt, re.IGNORECASE),
        "aggregate_video_prompt should not contain duration or aspect ratio",
        failures,
    )

    positions: list[tuple[str, int]] = []
    for shot in shots:
        shot_id = str(shot.get("id", "")).strip()
        matches = list(re.finditer(rf"(?m)^{re.escape(shot_id)}(?:\s*[｜|:]|\s*$)", prompt))
        require(bool(matches), f"aggregate_video_prompt is missing an explicit {shot_id} block", failures)
        require(
            len(matches) <= 1,
            f"aggregate_video_prompt contains duplicate {shot_id} blocks",
            failures,
        )
        if matches:
            positions.append((shot_id, matches[0].start()))

    if len(positions) != len(shots):
        return

    ordered_positions = [position for _, position in positions]
    require(
        ordered_positions == sorted(ordered_positions),
        "aggregate_video_prompt Shot blocks are not in session order",
        failures,
    )

    for index, (shot_id, start) in enumerate(positions):
        end = positions[index + 1][1] if index + 1 < len(positions) else len(prompt)
        block = prompt[start:end]
        require(
            len(block) >= 80,
            f"aggregate_video_prompt {shot_id} block is too brief; describe composition, action and camera motion",
            failures,
        )


def validate_storyboard_sheet(
    state_path: Path,
    state: dict[str, object],
    profile: str,
    html_path: Path,
    assets_dirname: str,
    failures: list[str],
) -> None:
    sheet = state.get("storyboard_sheet")
    require_sheet = display_option_enabled(state, "show_storyboard_sheet", False)
    if not require_sheet:
        return
    if sheet in (None, "", {}):
        if profile == "release" and require_sheet:
            require(False, "storyboard_sheet is missing; generate the 3-column JPG sheet before release", failures)
        return

    require(isinstance(sheet, dict), "storyboard_sheet is not an object", failures)
    if not isinstance(sheet, dict):
        return

    raw_path = str(sheet.get("path", "")).strip()
    if not raw_path:
        if profile == "release" and require_sheet:
            require(False, "storyboard_sheet.path is missing; generate the 3-column JPG sheet before release", failures)
        return

    require(
        not is_inline_data_reference(raw_path),
        "storyboard_sheet.path uses inline data instead of an asset path",
        failures,
    )
    if is_inline_data_reference(raw_path):
        return

    require(not raw_path.lower().endswith(".svg"), f"storyboard_sheet uses SVG instead of a raster JPG: {raw_path}", failures)
    asset_path = resolve_asset(state_path, raw_path)
    require(not Path(raw_path).is_absolute(), f"storyboard_sheet uses an absolute path: {raw_path}", failures)
    require(
        is_path_within(asset_path, state_path.parent / assets_dirname),
        f"storyboard_sheet is outside the session assets directory: {raw_path}",
        failures,
    )
    require(asset_path.exists(), f"storyboard_sheet file missing: {asset_path}", failures)
    require(
        asset_path.suffix.lower() in {".jpg", ".jpeg"},
        f"storyboard_sheet should be a JPG file, got: {raw_path}",
        failures,
    )

    if html_path.exists():
        html = html_path.read_text(encoding="utf-8")
        require(raw_path in html or Path(raw_path).as_posix() in html, f"HTML does not include storyboard_sheet path: {raw_path}", failures)


def validate_production_reference(state: dict[str, object], failures: list[str]) -> None:
    project_mode = str(state.get("project_mode", "")).strip().lower()
    require(bool(project_mode), "project_mode is missing", failures)
    if project_mode:
        require(
            project_mode in VALID_PROJECT_MODES,
            f"project_mode must be one of {sorted(VALID_PROJECT_MODES)}",
            failures,
        )

    refs = state.get("production_reference")
    require(isinstance(refs, dict), "production_reference is missing or not an object", failures)
    if not isinstance(refs, dict):
        return

    for field in REQUIRED_REFERENCE_FIELDS:
        value = refs.get(field)
        require(isinstance(value, list) and bool(value), f"production_reference.{field} must be a non-empty list", failures)


def validate_parallel_generation(state: dict[str, object], shots: list[dict[str, object]], failures: list[str]) -> None:
    if len(shots) < 2:
        return

    parallel = state.get("parallel_generation")
    require(isinstance(parallel, dict), "parallel_generation is required for multi-shot storyboard sessions", failures)
    if not isinstance(parallel, dict):
        return

    require(parallel.get("enabled") is True, "parallel_generation.enabled must be true for multi-shot sessions", failures)
    require(
        parallel.get("multi_agent_required") is True,
        "parallel_generation.multi_agent_required must be true; multi-agent execution is the default for independent image jobs",
        failures,
    )

    dispatch_mode = str(parallel.get("dispatch_mode", "")).strip()
    require(
        dispatch_mode in VALID_DISPATCH_MODES,
        f"parallel_generation.dispatch_mode must be one of {sorted(VALID_DISPATCH_MODES)}",
        failures,
    )
    if dispatch_mode in {"reduced_concurrency", "serial_unavailable"}:
        require(
            bool(str(parallel.get("reduced_concurrency_reason", "")).strip()),
            "parallel_generation.reduced_concurrency_reason is required when dispatch is reduced or serial_unavailable",
            failures,
        )


def validate_video_readiness(state_path: Path, shots: list[dict[str, object]], failures: list[str]) -> None:
    for shot in shots:
        shot_id = str(shot.get("id", "Unknown shot"))
        readiness = shot.get("video_readiness")
        require(isinstance(readiness, dict), f"{shot_id} video_readiness is missing or not an object", failures)
        if not isinstance(readiness, dict):
            continue

        for field in ("status", "motion_intensity", "camera_motion", "risk_level", "test_status"):
            require(bool(str(readiness.get(field, "")).strip()), f"{shot_id} video_readiness missing {field}", failures)

        raw_first_frame = str(readiness.get("first_frame_path", "")).strip()
        if raw_first_frame:
            require(
                not is_inline_data_reference(raw_first_frame),
                f"{shot_id} first frame uses inline data instead of an asset path",
                failures,
            )
            if not is_inline_data_reference(raw_first_frame):
                first_frame = resolve_asset(state_path, raw_first_frame)
                require(first_frame.exists(), f"{shot_id} first frame missing: {first_frame}", failures)
                require(
                    first_frame.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"},
                    f"{shot_id} first frame is not raster: {raw_first_frame}",
                    failures,
                )

        must_preserve = readiness.get("must_preserve")
        require(
            isinstance(must_preserve, list) and bool(must_preserve),
            f"{shot_id} video_readiness.must_preserve must be a non-empty list",
            failures,
        )


def validate_video_test(state: dict[str, object], failures: list[str]) -> None:
    video_test = state.get("video_test")
    if video_test in (None, "", {}):
        return

    require(isinstance(video_test, dict), "video_test is not an object", failures)
    if not isinstance(video_test, dict):
        return

    has_details = any(
        bool(str(video_test.get(field, "")).strip())
        for field in ("status", "shot_selection", "why_this_shot", "next_action")
    ) or bool(video_test.get("pass_criteria"))
    if not has_details:
        return

    for field in ("status", "next_action"):
        require(bool(str(video_test.get(field, "")).strip()), f"video_test missing {field}", failures)

    pass_criteria = video_test.get("pass_criteria")
    if pass_criteria not in (None, ""):
        require(isinstance(pass_criteria, list), "video_test.pass_criteria must be a list", failures)


def validate_shot_continuity_logic(shots: list[dict[str, object]], failures: list[str]) -> None:
    for shot in shots:
        shot_id = str(shot.get("id", "Unknown shot"))
        continuity = str(shot.get("continuity", "")).strip().lower()
        camera = str(shot.get("camera", "")).strip().lower()
        video_prompt = shot.get("video_prompt", {})
        seedance = ""
        if isinstance(video_prompt, dict):
            seedance = str(video_prompt.get("seedance2", "")).strip().lower()
        combined = " ".join(part for part in (continuity, camera, seedance) if part)

        if contains_any(continuity, SAME_LAYOUT_TOKENS):
            require(
                contains_any(continuity, ALLOWED_CHANGE_TOKENS) or contains_any(continuity, CAMERA_RELATION_TOKENS),
                f"{shot_id} continuity claims same-layout continuity but does not state allowed changes or camera relation",
                failures,
            )

        if contains_any(combined, CONTINUOUS_SHOT_TOKENS):
            require(
                contains_any(combined, CAMERA_RELATION_TOKENS),
                f"{shot_id} continuous-shot logic is missing a clear physical camera relation",
                failures,
            )
            if contains_any(combined, WIDE_TOKENS) and contains_any(combined, TELE_TOKENS):
                require(
                    contains_any(combined, SEQUENCE_TOKENS),
                    f"{shot_id} continuous-shot logic mixes wide and telephoto language without a sequenced physical explanation",
                    failures,
                )
            if contains_any(combined, PUSH_TOKENS) and contains_any(combined, PULL_TOKENS):
                require(
                    contains_any(combined, SEQUENCE_TOKENS),
                    f"{shot_id} continuous-shot logic mixes push and pullback without a sequenced physical path",
                    failures,
                )


def validate_html(html_path: Path, failures: list[str]) -> None:
    require(html_path.exists(), f"Rendered HTML missing: {html_path}", failures)
    if not html_path.exists():
        return

    html = html_path.read_text(encoding="utf-8")
    html_bytes = len(html.encode("utf-8"))
    require(
        html_bytes <= MAX_RENDERED_HTML_BYTES,
        f"Rendered HTML is too large ({html_bytes // 1024}KB); keep images as linked assets, not inline payloads",
        failures,
    )
    require(
        not contains_any(html.lower(), INLINE_DATA_TOKENS),
        "HTML contains inline data/base64 payloads; render image links from assets/ paths instead",
        failures,
    )
    require("视频提示词" in html, "HTML is missing the video prompt column", failures)
    require("gemini" not in html.lower(), "HTML should not expose alternate model prompts", failures)
    require("Seedance 2.0" not in html, "HTML should label the visible video prompt generically, not as Seedance 2.0", failures)
    require(".svg" not in html.lower(), "HTML still references SVG assets", failures)
    require("approved" not in html.lower(), "HTML exposes approved/draft process language", failures)
    require("stage 1" not in html.lower() and "stage 2" not in html.lower(), "HTML exposes Stage 1/2 language", failures)


def validate_base(state: dict[str, object], failures: list[str]) -> list[dict[str, object]]:
    aspect_ratio = str(state.get("aspect_ratio", "")).strip()
    require(bool(aspect_ratio), "aspect_ratio is missing; default to 16:9 if the user did not specify one", failures)
    if aspect_ratio:
        require(
            ASPECT_RATIO_RE.match(aspect_ratio) is not None,
            f"aspect_ratio must look like 16:9, 9:16, or 1:1, got {aspect_ratio}",
            failures,
        )
        if ASPECT_RATIO_RE.match(aspect_ratio):
            width_text, height_text = re.split(r"[:xX]", aspect_ratio)
            require(
                float(width_text.strip()) > 0 and float(height_text.strip()) > 0,
                f"aspect_ratio values must be greater than zero, got {aspect_ratio}",
                failures,
            )

    shots = state.get("shots", [])
    require(isinstance(shots, list) and bool(shots), "shots must be a non-empty list", failures)
    if not isinstance(shots, list):
        return []

    seen_shot_keys: set[str] = set()
    for index, shot in enumerate(shots, start=1):
        require(isinstance(shot, dict), f"shot {index} is not an object", failures)
        if not isinstance(shot, dict):
            continue
        for field in REQUIRED_SHOT_FIELDS:
            require(bool(str(shot.get(field, "")).strip()), f"{shot.get('id', f'shot {index}')} missing {field}", failures)
        shot_key = normalize_asset_key(shot.get("id", ""))
        require(bool(shot_key), f"shot {index} id has no usable letters or numbers", failures)
        require(shot_key not in seen_shot_keys, f"duplicate shot id: {shot.get('id', f'shot {index}')}", failures)
        seen_shot_keys.add(shot_key)
    return [shot for shot in shots if isinstance(shot, dict)]


def validate(
    state_path: Path,
    profile: str,
    html_path: Path | None = None,
    assets_dirname: str = "assets",
) -> list[str]:
    failures: list[str] = []
    raw_state = state_path.read_text(encoding="utf-8")
    state = ensure_state_shape(json.loads(raw_state))
    html_path = html_path or state_path.with_suffix(".html")
    validate_session_weight(state_path, raw_state, state, failures)
    shots = validate_base(state, failures)

    if profile == "smoke":
        validate_html(html_path, failures)
        validate_html_asset_links(state_path, shots, state.get("line_art", {}).get("gallery", []), "line_art", html_path, failures)
        if display_option_enabled(state, "show_final_frames", False):
            validate_html_asset_links(state_path, shots, state.get("final_generation", {}).get("gallery", []), "final_generation", html_path, failures)
        return failures

    validate_shot_continuity_logic(shots, failures)
    validate_title_translation(state, failures)
    validate_text_review(state, failures)
    validate_production_reference(state, failures)
    validate_parallel_generation(state, shots, failures)
    validate_copy_ready_video_inputs(state, shots, failures)
    validate_video_reference_frame_files(state_path, state, shots, assets_dirname, failures)
    validate_aggregate_prompt(state, shots, failures, required=should_require_aggregate_prompt(state, profile))
    validate_storyboard_sheet(state_path, state, profile, html_path, assets_dirname, failures)

    if should_require_line_art(state, profile):
        validate_asset_gallery(state_path, state.get("line_art", {}).get("gallery", []), "line_art", shots, assets_dirname, failures)

    if should_require_final_assets(state, profile):
        validate_asset_gallery(state_path, state.get("final_generation", {}).get("gallery", []), "final_generation", shots, assets_dirname, failures)

    if should_require_video_package(state, profile):
        video_generation = state.get("video_generation", {})
        input_mode = None
        if isinstance(video_generation, dict) and "input_mode" in video_generation:
            input_mode = str(video_generation.get("input_mode", "")).strip().lower()
        validate_video_prompts(shots, failures, input_mode=input_mode)
        validate_video_readiness(state_path, shots, failures)
        validate_video_test(state, failures)

    validate_html(html_path, failures)
    validate_html_asset_links(state_path, shots, state.get("line_art", {}).get("gallery", []), "line_art", html_path, failures)
    if display_option_enabled(state, "show_final_frames", False):
        validate_html_asset_links(state_path, shots, state.get("final_generation", {}).get("gallery", []), "final_generation", html_path, failures)
    return failures


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a storyboard session at a smoke, workflow, or release gate.")
    parser.add_argument("session", help="Session directory or session JSON path.")
    parser.add_argument("--profile", default="release", choices=sorted(VALIDATION_PROFILES))
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

        failures = validate(
            state_path,
            args.profile,
            html_path=session_html_path(config, state_path),
            assets_dirname=config.assets_dirname,
        )
        if failures:
            print(f"VALIDATION FAILED ({args.profile})")
            for failure in failures:
                print(f"- {failure}")
            return 1

        print(f"VALIDATION PASSED ({args.profile})")
        return 0
    except StoryboardError as error:
        print_error(error)
        return 1
    except Exception as error:  # pragma: no cover - defensive CLI fallback
        print("问题: 校验脚本发生未预期错误", file=sys.stderr)
        print(f"原因: {error}", file=sys.stderr)
        print("下一步: 检查 session.json 是否损坏，或先运行 doctor_storyboard_skill.py。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
