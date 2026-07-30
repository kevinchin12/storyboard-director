---
name: storyboard-director
description: "Run a prompt-controlled story-to-storyboard workflow: ingest a story idea and optional character/scene references, prepare an approved shot package, generate and register per-shot line art, collect user review in one HTML board, and deliver one ordered aggregate video prompt. Use for complete storyboard runs or for coordinating the included stage skills. Finished colored frames are optional and only run when explicitly requested."
---

# Storyboard Director

Turn one story brief into a path-based storyboard session with compact state, real raster line art, one HTML review board, and one aggregate video prompt.

Do not use this skill for a one-off image prompt or for skipping directly to final colored images.

## Default Flow

1. Ingest the brief and optional character/scene reference images.
2. Create one session and write the script package, including per-shot line-art prompts and text-only review results.
3. Pause for script-package approval unless the user explicitly authorizes the full run.
4. Generate and register per-shot line art through a worker queue. Do not run AI visual review after generation.
5. Render the HTML board and pause for user line-art review.
6. Repair only user-named shots.
7. After line-art confirmation, write one aggregate video prompt with the fixed subject/scene/music preface and every Shot in order.
8. Run the finished-frame branch only when the user explicitly requests finished frames. Accept either an image style reference or a text style lock.

Default aspect ratio is `16:9`. Keep durations in JSON and hidden in HTML unless the user asks to show them.

## First-Response Orientation

Show this compact orientation only when both conditions are true: this is the first `storyboard-director` response in the current Codex task, and no existing storyboard session can be resolved for the current story. Include it even when the user already supplied a story, brief, or reference assets.

Present it in the user's language under two short labeled groups. In Chinese, use the headings `基本流程` and `可选交付`, and use the established terms `逐镜最终画面` and `分镜合集图` rather than alternate translations:

**Basic flow**

1. Script planning: organize the story into an ordered shot package, write per-shot line-art prompts, and run text-only checks for logic, action paths, and continuity. Pause for script approval.
2. Line-art production: after approval, dispatch multiple workers to generate per-shot line art, register every image, and collect the ordered results in the local HTML review board. Pause for line-art approval.
3. Prompt delivery: after line-art approval, deliver complete per-shot video prompts and one ordered aggregate prompt.

**Optional deliverables**

- Finished frames based on the approved shots and a supplied image or text style reference.
- A line-art or finished-frame storyboard sheet arranged in Shot order.
- Prompt adaptation for a named video model or an explicitly requested image-guided workflow.

Keep both groups compact, then immediately continue with the user's supplied material in the same response. The orientation is informational, not a new approval gate or a reason to delay setup. Do not ask the user to repeat or re-upload inputs just to present it. Once shown, do not repeat it in the same Codex task even if a session has not been created yet. Do not show it when continuing a resolvable existing session, later stage, or repair turn, and omit it when the user explicitly asks to skip the introduction.

## Copy-Ready Prompt Independence

Copy-ready aggregate and per-shot video prompts are text-self-contained. Use confirmed line art and optional finished frames only as silent authoring guidance, then translate every relevant visual fact into words. Never require the user to upload, attach, or `@` internally generated line art, finished frames, storyboard sheets, or local asset paths.

Every Shot prompt must explicitly state the environment/composition, start state and spatial relation, one visible action path, camera behavior, visible change or landing state, and necessary continuity. Only actual user-supplied product, subject, character, scene, or style references may remain as explicit upload references.

Set `video_generation.input_mode` to `text_only` by default and leave every `video_prompt.reference_frame` empty. Use `image_guided` and populate a reference frame only when the user explicitly requests an image-guided workflow and confirms the exact image they will upload.

## Stage Routing

This file owns orchestration and shared invariants. Load only the stage skill needed for the current work:

- Script package and text review: `skills/storyboard-script-planner/SKILL.md`
- Line-art generation and registration: `skills/storyboard-lineart-generator/SKILL.md`
- Aggregate prompt: `skills/storyboard-aggregate-prompt/SKILL.md`
- Optional finished frames: `skills/storyboard-final-frame-optional/SKILL.md`

When the user requests one stage only, use that stage skill directly. Do not load unrelated stage instructions.

## Runtime Root

Resolve `STORYBOARD_DIRECTOR_ROOT` to the directory containing this `SKILL.md`. Use scripts from its absolute `scripts/` path. Do not assume the user's current working directory contains `storyboard-scene-pipeline-skill/`.

The project workspace is separate. It must contain `storyboard.config.json` and stores sessions under its configured sessions directory.

## Shared Session Contract

Use one session directory per run:

```text
session.json
session.html
assets/
```

- `session.json` is the source of truth.
- `session.html` is the local review surface.
- `assets/` contains copied/converted project images.
- Chat is for decisions and targeted repair, not persistent state.

Never hand-edit HTML as the primary update method. Patch JSON, render HTML, then validate.

Initialize a run:

```bash
python3 "$STORYBOARD_DIRECTOR_ROOT/scripts/init_story_session.py" "Story Title" --workspace-root /path/to/workspace
```

Use `--new` only for a separate run. Continue an existing session when the story already has one.

### Session Resolution

- Use an explicit session path whenever the user provides one.
- For a clearly new story, initialize a new session.
- For continuation without a path, inspect the configured `sessions/` and `examples/` directories. Continue automatically only when exactly one matching session exists.
- When multiple sessions could match, ask for the exact session path. Never guess from modification time or silently choose the newest directory.

### Title Translation

Always write `project_title_en` during script planning. If the user explicitly supplies `project_title_en`, preserve its wording, capitalization, and punctuation. Otherwise, translate `project_title` into a concise, natural English story title without asking for confirmation. Do not replace the translation with a product label such as `Storyboard Director`.

Update state:

```bash
python3 "$STORYBOARD_DIRECTOR_ROOT/scripts/update_story_session.py" SESSION.json PATCH.json --validate-profile smoke --workspace-root /path/to/workspace
```

`update_story_session.py` deep-merges objects but replaces arrays. Never submit a one-item `shots` or `gallery` patch expecting an in-place merge. For generated images, use `register_story_asset.py`; for array edits, provide the complete intended array.

Register every user-supplied character, scene, or style reference before writing prompts:

```bash
python3 "$STORYBOARD_DIRECTOR_ROOT/scripts/register_story_reference.py" SESSION.json \
  --reference-type character \
  --source /local/reference.png \
  --label "Lead Character" \
  --description "identity and wardrobe lock" \
  --workspace-root /path/to/workspace
```

This copies and normalizes the image into session `assets/`, updates the correct reference list, renders HTML, and runs smoke validation. Do not leave user references as external absolute paths or chat-only attachments.

## Project Modes

Choose one mode before shot planning:

- `character`: face, wardrobe, props, acting, and body continuity
- `subject`: product, vehicle, mascot, creature, or object identity
- `spatial`: place identity, geography, camera path, and fixed anchors
- `atmospheric`: light, weather, material, mood, and temporal rhythm

If the brief is ambiguous enough to change image planning, ask one short clarification before line-art dispatch.

## Review Contract

Text review is mandatory before line-art dispatch and uses text only. It checks:

- shot order, cause-effect, and editing function
- one visible action path per shot
- camera motivation and scene geography
- character, prop, weather, light, and effect continuity
- contour-only line-art prompt completeness

Record compact results in:

- `text_review.script_logic_check`
- `text_review.line_art_prompt_preflight`

Do not upload generated line art, final frames, or video results for routine AI review. Inspect pixels only when the user names a problem shot or requests targeted diagnosis.

## Parallel Image Contract

For any line-art or finished-frame batch with two or more independent shots:

1. Build the complete worker queue before the first image call.
2. Use available multi-agent or worker delegation by default.
3. Keep the orchestrator as the only writer of `session.json` and HTML.
4. Give each worker only global locks, one shot job, required reference paths, and a target filename.
5. Require path-only output: `shot_id`, `asset_type`, `status`, `output_path`, optional retry prompt, and one short note.
6. Merge results by exact Shot ID while preserving storyboard order.

Default concurrency is up to four line-art workers and three finished-frame workers. Reduce finished-frame concurrency to one or two for exact people, products, landmarks, readable text, or tightly continuous spaces, and record the reason.

Use `serial_unavailable` only when delegation is unavailable or blocked by tool policy. Serial fallback still uses the built-in image tool and the same prebuilt queue; it never means CLI/API fallback.

The shared `capture_generated_asset.py` marker is a serial recovery mechanism. Do not let concurrent workers share one marker. Parallel workers must return explicit local source paths or use isolated per-worker capture state.

## Asset Contract

- Generate real raster images with the strongest available image model.
- Save new review assets as JPG by default.
- Line art: `assets/shot01-line.jpg`, long edge about `1536px`.
- Optional finished frame: `assets/shot01-final.jpg`, default long edge `2048px`.
- Store only project-relative `assets/` paths in JSON and HTML.
- Reject absolute paths, `..` traversal, inline image data, SVG substitutes, and `$CODEX_HOME/generated_images` delivery paths.
- A chat preview is not a delivered asset.

Register every successful image with the exact session Shot ID:

```bash
python3 "$STORYBOARD_DIRECTOR_ROOT/scripts/register_story_asset.py" SESSION.json \
  --asset-type line-art \
  --shot-id "Shot 01" \
  --source /local/generated/source.png \
  --output-name shot01-line.jpg \
  --validate-profile smoke \
  --workspace-root /path/to/workspace
```

If a serial built-in image call does not return a path, follow `integrations/imagegen-save-recovery.md`. Never ask for `OPENAI_API_KEY` or switch to a local image CLI unless the user explicitly chooses an external-provider workflow.

## HTML Contract

Keep the visible board simple:

- project title, summary, and aspect ratio
- character and scene references
- ordered Shot cards with frame, camera, action, line art, and one visible video prompt
- line-art overview and aggregate prompt

Keep text-review results in `session.json` for validation, but hide them from the HTML board by default. Hide durations and finished-frame sections by default. Show finished frames and a storyboard sheet only after that branch is explicitly enabled.

Physical worker completion order may vary; JSON, HTML, and sheets must always preserve Shot order.

## Revision Routing

Classify feedback before editing:

- Multi-shot cause-effect, order, geography, action, or continuity problem: return to script planning and propagate the fix forward.
- Single prompt risk before generation: revise only that shot prompt.
- Single generated-image defect: inspect and repair only that named shot.
- Style, palette, texture, or finish change with stable structure: keep script and line art fixed; use the optional finished-frame branch only if requested.

If the user says the whole result is bad, stop generation and rebuild shot logic. Do not keep polishing images around a weak script.

## Approval Gates

Pause at:

1. script package ready for review
2. HTML line-art board ready for review
3. aggregate prompt ready
4. final delivery preflight

If the user explicitly authorizes an uninterrupted full run, that authorization satisfies internal review pauses for that run. It does not authorize external sends or other write operations outside the local project.

## Context Budget

- Keep session JSON as compact state, never a transcript.
- Store images on disk and pass paths.
- Default pixel-inspection input is one to three files.
- Do not paste HTML, image payloads, compaction logs, or full history into patches or handoffs.
- For a heavy thread, export a short handoff and continue in a fresh thread by file path.

```bash
python3 "$STORYBOARD_DIRECTOR_ROOT/scripts/export_story_handoff.py" SESSION.json --workspace-root /path/to/workspace
```

## Validation

Use smoke checks for routine patches, workflow checks at human gates, and release checks only for sharing or final delivery.

```bash
python3 "$STORYBOARD_DIRECTOR_ROOT/scripts/validate_story_session.py" --profile smoke SESSION.json --workspace-root /path/to/workspace
python3 "$STORYBOARD_DIRECTOR_ROOT/scripts/validate_story_session.py" --profile workflow SESSION.json --workspace-root /path/to/workspace
python3 "$STORYBOARD_DIRECTOR_ROOT/scripts/audit_story_assets.py" SESSION.json --workspace-root /path/to/workspace
```

Before sharing the skill package, run `doctor_storyboard_skill.py`, the repository tests, and `release_audit.py`.

## Hard Constraints

- Do not generate line art before script approval or explicit full-run authorization.
- Do not dispatch image workers while text review has blocking issues.
- Do not generate finished frames by default.
- Do not redesign approved shots while writing the aggregate prompt.
- Do not make a copy-ready prompt depend on generated per-shot line art, final frames, storyboard sheets, `@shotXX` handles, or local asset paths.
- Do not populate `video_prompt.reference_frame` by default; it is reserved for an explicitly selected `image_guided` workflow.
- Do not silently choose serial generation for an independent multi-shot batch.
- Do not let workers edit session state or HTML.
- Do not map assets by gallery position when Shot IDs exist.
- Do not claim completion when the saved asset or rendered HTML path is missing.
- Do not use HTML, SVG, canvas, Mermaid, or code drawing as a substitute for requested storyboard images.
