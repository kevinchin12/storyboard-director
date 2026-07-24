#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from html import escape
from pathlib import Path

from storyboard_common import (
    StoryboardError,
    ensure_state_shape,
    is_path_within,
    print_error,
    resolve_state_path,
    resolve_workspace_config,
    session_html_path,
    shot_asset_for,
    write_text_atomic,
)

def e(text: object) -> str:
    return escape("" if text is None else str(text), quote=True)


def nl2br(text: object) -> str:
    return e(text).replace("\n", "<br />")


def display_title(title: object) -> str:
    text = str(title or "Story Session").strip()
    # Titles should describe the project, not encode platform timing.
    text = re.sub(r"\s*(约|大概|大约)?\s*\d+\s*(s|秒|分钟|min)\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text or "Story Session"


def duration_html(duration: object) -> str:
    value = str(duration or "").strip()
    if not value:
        return ""
    return f'{nl2br(value)} <span class="duration-note">建议时长</span>'


def resolve_asset_path(state_path: Path, asset_path: str) -> str:
    if not asset_path:
        return ""
    if asset_path.strip().lower().startswith("data:"):
        return ""
    if re.match(r"^[a-z][a-z0-9+.-]*:", asset_path.strip(), flags=re.IGNORECASE):
        return ""
    path = Path(asset_path)
    if path.is_absolute():
        return ""
    if not is_path_within(state_path.parent / path, state_path.parent):
        return ""
    return path.as_posix()


def asset_cell_html(item: dict[str, str] | None, state_path: Path, empty_text: str) -> str:
    if not item:
        return f'<div class="empty">{e(empty_text)}</div>'

    label = e(item.get("label", "Asset"))
    note = nl2br(item.get("note", ""))
    raw_path = str(item.get("path", "")).strip()
    resolved = resolve_asset_path(state_path, raw_path) if raw_path else ""
    if resolved:
        return (
            '<div class="asset-stack">'
            f'<div class="asset-frame"><img src="{e(resolved)}" alt="{label}" loading="lazy" decoding="async" /></div>'
            f'<a class="asset-link" href="{e(resolved)}">{e(raw_path)}</a>'
            "</div>"
        )
    return f'<div class="asset-frame">{note or e(empty_text)}</div>'


def is_enabled(state: dict[str, object], key: str, default: bool = False) -> bool:
    options = state.get("display_options", {})
    if not isinstance(options, dict):
        return default
    value = options.get(key, default)
    return value is True


def reference_asset_html(item: dict[str, object], state_path: Path, empty_text: str) -> str:
    label = e(item.get("label", "Reference"))
    raw_path = str(item.get("path", "")).strip()
    description = nl2br(item.get("description", "") or item.get("note", ""))
    resolved = resolve_asset_path(state_path, raw_path) if raw_path else ""
    if resolved:
        image_html = (
            f'<div class="asset-frame"><img src="{e(resolved)}" alt="{label}" loading="lazy" decoding="async" /></div>'
            f'<a class="asset-link" href="{e(resolved)}">{e(raw_path)}</a>'
        )
    else:
        image_html = f'<div class="asset-frame">{e(empty_text)}</div>'
    return (
        '<article class="asset-card">'
        f'<div class="asset-label">{label}</div>'
        f'{image_html}'
        f'<div class="meta-value">{description}</div>'
        '</article>'
    )


def reference_group_html(items: object, state_path: Path, empty_text: str) -> str:
    if not isinstance(items, list) or not items:
        return f'<div class="empty">{e(empty_text)}</div>'
    cards = [
        reference_asset_html(item, state_path, empty_text)
        for item in items
        if isinstance(item, dict) and (str(item.get("path", "")).strip() or str(item.get("description", "")).strip())
    ]
    return '<div class="reference-grid">' + "".join(cards) + "</div>" if cards else f'<div class="empty">{e(empty_text)}</div>'


def visual_references_html(state: dict[str, object], state_path: Path) -> str:
    if not is_enabled(state, "show_visual_references", True):
        return ""
    refs = state.get("visual_references", {})
    if not isinstance(refs, dict):
        refs = {}
    return """
      <section class="panel">
        <h2>角色设定与场景图</h2>
        <div class="reference-layout">
          <div>
            <div class="overview-subhead"><div class="overview-subtitle">角色设定图</div></div>
            <div style="height: 12px;"></div>
            {characters}
          </div>
          <div>
            <div class="overview-subhead"><div class="overview-subtitle">场景图</div></div>
            <div style="height: 12px;"></div>
            {scenes}
          </div>
        </div>
      </section>
    """.format(
        characters=reference_group_html(refs.get("characters", []), state_path, "暂无角色设定图，等待上传"),
        scenes=reference_group_html(refs.get("scenes", []), state_path, "暂无场景图，等待上传"),
    )


def prompt_list_html(items: object) -> str:
    if not isinstance(items, list) or not items:
        return ""
    return "".join(f"<li>{nl2br(item)}</li>" for item in items if str(item).strip())


def video_prompt_html(prompt: object) -> str:
    if not isinstance(prompt, dict):
        text = str(prompt or "").strip()
        return nl2br(text) if text else "待填写"

    seedance = str(prompt.get("seedance2", "")).strip()

    parts = []
    if seedance:
        parts.append(f'<div class="prompt-block"><textarea class="prompt-copy" readonly>{e(seedance)}</textarea></div>')
    return "".join(parts) if parts else "待填写"


def list_html(items: object) -> str:
    if not isinstance(items, list) or not items:
        return '<div class="empty">待填写</div>'
    return "<ul>" + "".join(f"<li>{nl2br(item)}</li>" for item in items) + "</ul>"


def compact_list_html(items: object, empty_text: str = "无") -> str:
    if not isinstance(items, list) or not items:
        return f'<div class="meta-value">{e(empty_text)}</div>'
    entries = "".join(f"<li>{nl2br(item)}</li>" for item in items if str(item).strip())
    return f"<ul>{entries}</ul>" if entries else f'<div class="meta-value">{e(empty_text)}</div>'


def review_block_html(review: object, title: str) -> str:
    if not isinstance(review, dict):
        review = {}
    return """
      <article class="card review-card">
        <div class="overview-subhead">
          <div class="overview-subtitle">{title}</div>
          <span class="review-status">{status}</span>
        </div>
        <div class="body-text">{summary}</div>
        <div>
          <span class="info-label">阻塞项</span>
          <div class="body-text">{blocking_issues}</div>
        </div>
        <div>
          <span class="info-label">已修正</span>
          <div class="body-text">{fixes_applied}</div>
        </div>
      </article>
    """.format(
        title=e(title),
        status=e(review.get("status", "pending")),
        summary=nl2br(review.get("summary", "待填写")),
        blocking_issues=compact_list_html(review.get("blocking_issues", [])),
        fixes_applied=compact_list_html(review.get("fixes_applied", [])),
    )


def text_review_html(state: dict[str, object]) -> str:
    if not is_enabled(state, "show_text_review", False):
        return ""
    review = state.get("text_review", {})
    if not isinstance(review, dict):
        review = {}
    return """
      <section class="panel">
        <h2>文本审查</h2>
        <div class="card">
          <div class="body-text">{rules}</div>
        </div>
        <div style="height: 14px;"></div>
        <div class="text-review-grid">
          {script_logic}
          {line_art_preflight}
        </div>
      </section>
    """.format(
        rules=list_html(review.get("rules", [])),
        script_logic=review_block_html(review.get("script_logic_check", {}), "脚本逻辑"),
        line_art_preflight=review_block_html(review.get("line_art_prompt_preflight", {}), "线稿预检"),
    )


def project_mode_label(project_mode: object) -> str:
    labels = {
        "character": "角色驱动",
        "subject": "主体驱动",
        "spatial": "空间驱动",
        "atmospheric": "氛围驱动",
    }
    return labels.get(str(project_mode or "").strip().lower(), "待判断")


def readiness_summary_html(shots: list[dict[str, object]], show_durations: bool) -> str:
    if not shots:
        return '<div class="empty">暂无镜头 readiness。</div>'

    rows = []
    for shot in shots:
        readiness = shot.get("video_readiness", {})
        if not isinstance(readiness, dict):
            readiness = {}
        row_class = "readiness-row" if show_durations else "readiness-row readiness-row-no-duration"
        rows.append(
            """
            <div class="{row_class}">
              <div class="readiness-shot">{id}</div>
              {duration_cell}
              <div>{risk}</div>
              <div>{motion}</div>
              <div>{test}</div>
            </div>
            """.format(
                row_class=row_class,
                id=e(shot.get("id", "")),
                duration_cell=f'<div>{e(shot.get("duration", ""))}</div>' if show_durations else "",
                risk=e(readiness.get("risk_level", "待填写")),
                motion=e(readiness.get("motion_intensity", "待填写")),
                test=e(readiness.get("test_status", "待填写")),
            )
        )

    duration_head = "<div>Time</div>" if show_durations else ""
    row_class = "readiness-row" if show_durations else "readiness-row readiness-row-no-duration"
    return (
        '<div class="readiness-table">'
        f'<div class="{row_class} readiness-head">'
        f'<div>Shot</div>{duration_head}<div>Risk</div><div>Motion</div><div>Test</div>'
        '</div>'
        + "".join(rows)
        + "</div>"
    )


def video_delivery_html(state: dict[str, object]) -> str:
    refs = state.get("production_reference", {})
    if not isinstance(refs, dict):
        refs = {}
    video_test = state.get("video_test", {})
    if not isinstance(video_test, dict):
        video_test = {}
    platform_check = video_test.get("shot_selection") or "默认不指定优先镜头"

    return """
      <div class="delivery-grid">
        <div class="delivery-card">
          <span class="info-label">项目模式</span>
          <div class="body-text">{project_mode}</div>
        </div>
        <div class="delivery-card">
          <span class="info-label">主要锚点</span>
          <div class="body-text">{primary_anchor}</div>
        </div>
        <div class="delivery-card">
          <span class="info-label">连续性规则</span>
          <div class="body-text">{continuity_rules}</div>
        </div>
        <div class="delivery-card">
          <span class="info-label">世界锚点</span>
          <div class="body-text">{world_lock}</div>
        </div>
        <div class="delivery-card">
          <span class="info-label">平台测试说明</span>
          <div class="body-text"><strong>{platform_check}</strong><br />{why_this_shot}</div>
        </div>
        <div class="delivery-card">
          <span class="info-label">可选检查项</span>
          <div class="body-text">{pass_criteria}</div>
        </div>
      </div>
      <div style="height: 14px;"></div>
      {readiness}
    """.format(
        project_mode=e(project_mode_label(state.get("project_mode"))),
        primary_anchor=list_html(refs.get("primary_anchor", [])),
        continuity_rules=list_html(refs.get("continuity_rules", [])),
        world_lock=list_html(refs.get("world_lock", [])),
        platform_check=e(platform_check),
        why_this_shot=nl2br(video_test.get("why_this_shot", "待填写")),
        pass_criteria=list_html(video_test.get("pass_criteria", [])),
        readiness=readiness_summary_html(state.get("shots", []), is_enabled(state, "show_durations", False)),
    )


def shot_boards_html(
    shots: list[dict[str, str]],
    line_gallery: list[dict[str, str]],
    final_gallery: list[dict[str, str]],
    state_path: Path,
    show_final_frames: bool,
    show_durations: bool,
) -> str:
    if not shots:
        return '<div class="empty">还没有故事板镜头。</div>'

    boards = []
    for index, shot in enumerate(shots):
        line_item = shot_asset_for(line_gallery, shot, index)
        final_item = shot_asset_for(final_gallery, shot, index)
        final_asset_html = ""
        if show_final_frames:
            final_asset_html = """
                  <div class="asset-card">
                    <div class="asset-label">Frame</div>
                    {final_asset}
                  </div>
            """.format(final_asset=asset_cell_html(final_item, state_path, "暂无画面稿"))
        duration_span = (
            f'<span class="shot-duration">{duration_html(shot.get("duration", ""))}</span>'
            if show_durations
            else ""
        )
        boards.append(
            """
            <article class="shot-board">
              <div class="shot-head">
                <div class="shot-title">
                  <span class="shot-id">{id}</span>
                  {duration}
                </div>
              </div>
              <div class="shot-layout">
                <div class="asset-grid">
                  <div class="asset-card">
                    <div class="asset-label">Line Art</div>
                    {line_art_asset}
                  </div>
                  {final_asset_html}
                </div>
                <div class="info-grid">
                  <div class="info-card">
                    <span class="info-label">画面</span>
                    <div class="info-value">{frame}</div>
                  </div>
                  <div class="info-card">
                    <span class="info-label">镜头</span>
                    <div class="info-value">{camera}</div>
                  </div>
                  <div class="info-card">
                    <span class="info-label">动作</span>
                    <div class="info-value">{action}</div>
                  </div>
                  <div class="info-card">
                    <span class="info-label">视频提示词</span>
                    <div class="info-value video-prompt">{video_prompt}</div>
                  </div>
                </div>
              </div>
            </article>
            """.format(
                id=e(shot.get("id", "")),
                duration=duration_span,
                frame=nl2br(shot.get("frame", "")),
                action=nl2br(shot.get("action", "")),
                camera=nl2br(shot.get("camera", "")),
                video_prompt=video_prompt_html(shot.get("video_prompt", "")),
                line_art_asset=asset_cell_html(line_item, state_path, "暂无线稿"),
                final_asset_html=final_asset_html,
            )
        )

    return "".join(boards)


def overview_asset_html(item: dict[str, str] | None, state_path: Path, empty_text: str) -> str:
    if not item:
        return f'<div class="overview-frame">{e(empty_text)}</div>'

    raw_path = str(item.get("path", "")).strip()
    note = nl2br(item.get("note", "")) or e(empty_text)
    label = e(item.get("label", "Asset"))
    resolved = resolve_asset_path(state_path, raw_path) if raw_path else ""
    if resolved:
        return f'<div class="overview-frame"><img src="{e(resolved)}" alt="{label}" loading="lazy" decoding="async" /></div>'
    return f'<div class="overview-frame">{note}</div>'


def overview_grid_html(
    shots: list[dict[str, str]],
    gallery: list[dict[str, str]],
    state_path: Path,
    empty_text: str,
    show_durations: bool,
) -> str:
    cards = []
    for index, shot in enumerate(shots):
        item = shot_asset_for(gallery, shot, index)
        cards.append(
            """
            <article class="overview-card">
              <div class="overview-shot">
                <span class="overview-id">{id}</span>
                {duration}
              </div>
              {asset}
            </article>
            """.format(
                id=e(shot.get("id", "")),
                duration=f'<span class="overview-duration">{duration_html(shot.get("duration", ""))}</span>' if show_durations else "",
                asset=overview_asset_html(item, state_path, empty_text),
            )
        )

    return '<div class="overview-grid">' + "".join(cards) + "</div>"


def aggregate_sheet_inline_html(state: dict[str, object], state_path: Path) -> str:
    if not is_enabled(state, "show_storyboard_sheet", False):
        return ""
    sheet = state.get("storyboard_sheet", {})
    if not isinstance(sheet, dict):
        return ""
    raw_path = str(sheet.get("path", "")).strip()
    resolved = resolve_asset_path(state_path, raw_path) if raw_path else ""
    if not resolved:
        return ""
    label = str(sheet.get("label", "")).strip() or "合并分镜图"
    return """
      <div class="aggregate-sheet-area">
        <div class="overview-label">{label}</div>
        <a class="aggregate-sheet-frame" href="{path}" download>
          <img src="{path}" alt="{label}" loading="lazy" decoding="async" />
        </a>
      </div>
    """.format(
        label=e(label),
        path=e(resolved),
    )


def aggregate_prompt_html(state: dict[str, object], state_path: Path) -> str:
    prompt = str(state.get("aggregate_video_prompt", "")).strip()
    body = '<div class="empty">暂无汇总版视频提示词。</div>'
    if prompt:
        body = f'<div class="prompt-block"><textarea class="prompt-copy aggregate-prompt-copy" readonly>{e(prompt)}</textarea></div>'
    sheet = aggregate_sheet_inline_html(state, state_path)
    card_class = "aggregate-prompt-card has-sheet" if sheet else "aggregate-prompt-card"
    if sheet:
        body = f'{sheet}<div class="aggregate-prompt-area">{body}</div>'
    return f"""
        <section class="panel">
          <h2>合并提示词及分镜</h2>
          <div class="{card_class}">
          {body}
          </div>
        </section>
    """


def storyboard_sheet_section_html(state: dict[str, object], state_path: Path) -> str:
    sheet = storyboard_sheet_html(state, state_path)
    if "暂无合并分镜图" in sheet:
        return ""
    return f"""
        <div>
          <div class="overview-subhead">
            <div class="overview-subtitle">合并分镜图</div>
          </div>
          <div style="height: 12px;"></div>
          {sheet}
        </div>
    """


def storyboard_sheet_html(state: dict[str, object], state_path: Path) -> str:
    sheet = state.get("storyboard_sheet", {})
    if not isinstance(sheet, dict):
        sheet = {}
    raw_path = str(sheet.get("path", "")).strip()
    note = str(sheet.get("note", "")).strip()
    resolved = resolve_asset_path(state_path, raw_path) if raw_path else ""
    if not resolved:
        return '<div class="empty">暂无合并分镜图。</div>'
    return """
      <div class="storyboard-sheet-card">
        <div class="overview-label">3列合并分镜图</div>
        <a class="storyboard-sheet-frame" href="{path}" download>
          <img src="{path}" alt="Combined storyboard sheet" loading="lazy" decoding="async" />
        </a>
        <a class="asset-link" href="{path}" download>{raw_path}</a>
        <div class="meta-value">{note}</div>
      </div>
    """.format(
        path=e(resolved),
        raw_path=e(raw_path),
        note=nl2br(note) if note else "点击图片或文件名下载。",
    )

def shot_overview_html(
    shots: list[dict[str, str]],
    line_gallery: list[dict[str, str]],
    final_gallery: list[dict[str, str]],
    state_path: Path,
    state: dict[str, object],
) -> str:
    if not shots:
        return '<div class="empty">还没有可总览的镜头。</div>'

    show_final_frames = is_enabled(state, "show_final_frames", False)
    show_durations = is_enabled(state, "show_durations", False)
    final_section = ""
    if show_final_frames:
        final_section = """
        <div>
          <div class="overview-subhead">
            <div class="overview-subtitle">画面总览</div>
          </div>
          <div style="height: 12px;"></div>
          {final_grid}
        </div>
        """.format(final_grid=overview_grid_html(shots, final_gallery, state_path, "暂无画面稿", show_durations))
    return """
      <div class="overview-section">
        <div>
        <div class="overview-subhead">
            <div class="overview-subtitle">线稿总览</div>
          </div>
          <div style="height: 12px;"></div>
          {line_grid}
        </div>
        {final_section}
      </div>
    """.format(
        line_grid=overview_grid_html(shots, line_gallery, state_path, "暂无线稿", show_durations),
        final_section=final_section,
    )


def render(state_path: Path, html_path: Path | None = None) -> Path:
    skill_root = Path(__file__).resolve().parents[1]
    template_path = skill_root / "assets" / "story_session_template.html"
    state = ensure_state_shape(json.loads(state_path.read_text(encoding="utf-8")))
    template = template_path.read_text(encoding="utf-8")

    html_path = html_path or state_path.with_suffix(".html")
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    replacements = {
        "{{PROJECT_TITLE}}": e(state.get("project_title", "Story Session")),
        "{{DISPLAY_TITLE}}": e(display_title(state.get("project_title", "Story Session"))),
        "{{PROJECT_TITLE_EN}}": e(
            str(state.get("project_title_en", "")).strip() or "Storyboard Director"
        ),
        "{{PROJECT_SUMMARY}}": nl2br(state.get("project_summary", "")),
        "{{ASPECT_RATIO}}": e(state.get("aspect_ratio", "16:9")),
        "{{LAST_UPDATED}}": e(now),
        "{{STATE_FILE}}": e(state_path.name),
        "{{OUTLINE_TEXT}}": nl2br(state.get("outline", {}).get("text", "")),
        "{{VISUAL_REFERENCES}}": visual_references_html(state, state_path),
        "{{TEXT_REVIEW}}": text_review_html(state),
        "{{VIDEO_DELIVERY}}": video_delivery_html(state),
        "{{SHOT_BOARDS}}": shot_boards_html(
            state.get("shots", []),
            state.get("line_art", {}).get("gallery", []),
            state.get("final_generation", {}).get("gallery", []),
            state_path,
            is_enabled(state, "show_final_frames", False),
            is_enabled(state, "show_durations", False),
        ),
        "{{SHOT_OVERVIEW}}": shot_overview_html(
            state.get("shots", []),
            state.get("line_art", {}).get("gallery", []),
            state.get("final_generation", {}).get("gallery", []),
            state_path,
            state,
        ),
        "{{AGGREGATE_PROMPT_SECTION}}": aggregate_prompt_html(state, state_path),
    }

    rendered = template
    for key, value in replacements.items():
        rendered = rendered.replace(key, value)

    rendered = "\n".join(line.rstrip() for line in rendered.splitlines()) + "\n"
    write_text_atomic(html_path, rendered)
    return html_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a storyboard session JSON into its HTML review board.")
    parser.add_argument("session", help="Session directory or session JSON path.")
    parser.add_argument("--workspace-root", help="Workspace root containing storyboard.config.json.")
    parser.add_argument("--config", help="Path to storyboard.config.json.")
    args = parser.parse_args()

    try:
        config = resolve_workspace_config(workspace_root=args.workspace_root, config_path=args.config)
        state_path = resolve_state_path(config, args.session)
        if not state_path.exists():
            raise StoryboardError(
                problem="Session 文件不存在",
                reason=f"找不到状态文件: {state_path}",
                next_step="确认传入的是 session 目录或 session.json 路径。",
            )

        html_path = render(state_path, session_html_path(config, state_path))
        print(html_path)
        return 0
    except StoryboardError as error:
        print_error(error)
        return 1
    except Exception as error:  # pragma: no cover - defensive CLI fallback
        print("问题: 渲染脚本发生未预期错误", file=sys.stderr)
        print(f"原因: {error}", file=sys.stderr)
        print("下一步: 检查 session.json 结构，或先运行 doctor_storyboard_skill.py。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
