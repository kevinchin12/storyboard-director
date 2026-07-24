---
name: storyboard-aggregate-prompt
description: "Write the aggregate video prompt for a confirmed line-art storyboard session. Use after the user confirms line art. Produces the fixed subject/scene/music preface plus ordered Shot blocks without redesigning the storyboard."
---

# Storyboard Aggregate Prompt

Use this sub-skill when the user only wants the final merged video prompt from an existing storyboard session, or when the main pipeline delegates the aggregate prompt stage.

This sub-skill can run independently from a `session.json`.

## Runtime Root

Resolve `STORYBOARD_DIRECTOR_ROOT` before running commands:

- installed bundle: `${CODEX_HOME:-$HOME/.codex}/skills/storyboard-director`
- source checkout: the nearest ancestor containing both the main `SKILL.md` and `scripts/`

Use absolute script paths. Do not assume the current workspace contains the skill source folder.

## Session Resolution

Use the explicit session path when provided. Without one, inspect configured `sessions/` and `examples/` and proceed only when exactly one session matches the request. If several sessions could match, ask for the exact path; never choose the newest session by guesswork.

## Scope

Do:

- read the confirmed shot list
- read registered character design and scene references
- read confirmed line-art paths
- write `aggregate_video_prompt`
- update per-shot `video_prompt` fields only when useful
- render HTML

Do not:

- redesign characters
- reorder, merge, skip, or invent shots
- generate line-art images
- generate final frames
- include duration or aspect ratio in copy-ready platform prompt text
- require the user to upload, attach, or `@` generated line art, finished frames, storyboard sheets, or local per-shot assets
- use the aggregate prompt to repair weak script logic; route that back to script planning

## Required Preface

If user-provided character design and scene images exist, start with:

```text
主体:@对应的角色设定图
场景:@对应的场景图
音乐:不要生成任何背景音乐和旋律，只需要生成场景及动作对应的音效
```

If references are missing, write concise descriptions:

```text
主体:（Codex 生成角色设定描述）
场景:（Codex 生成场景描述）
音乐:不要生成任何背景音乐和旋律，只需要生成场景及动作对应的音效
```

Then continue with ordered shot blocks:

```text
Shot 01 | <scene role>: <composition/environment>. <subject action>. Camera: <camera motion>. Motion cue: <what visibly changes>.
Shot 02 | ...

Global continuity: <identity, world, style, geometry and avoid rules>.
```

This ordered aggregate prompt is the default deliverable after line-art confirmation. A separate platform test is optional and must not create a priority-shot checkpoint.

## Per-Shot Requirements

Every Shot block must include:

- environment or composition
- starting state and spatial relation
- subject action
- camera motion or locked-off behavior
- visible motion cue and landing state
- continuity or preservation rules when needed

Avoid:

- duration language
- aspect-ratio language
- internal workflow jargon
- vague cinematic filler
- new characters or locations not present in the approved storyboard
- `@shotXX`, `shotXX-line/final` paths, or phrases such as “use/upload the storyboard, line art, or final frame”

Use confirmed line art and optional finished frames as silent authoring guidance, and translate their relevant composition, geometry, and state into words. The copy-ready result must work without those internally generated images. Only actual user-supplied product, subject, character, scene, or style references may remain as explicit upload references.

Default to `video_generation.input_mode: text_only` and keep `video_prompt.reference_frame` empty. Use `image_guided` only when the user explicitly requests it and confirms the exact upload image; do not silently substitute a generated storyboard asset.

For every Shot, carry one visible motion beat and one camera relationship. The block must be directly pasteable, not a list of internal notes.

For character shots, include:

- stable identity anchor
- starting pose, gaze, hands, body weight, and nearby object relation
- one action path with visible process
- landing pose or held reaction
- camera relationship
- preserve and allowed-change rules

Split walking, turning, reaching, and reacting into separate shots unless they form one deliberately slow continuous path.

For subject, spatial, and atmospheric work, strengthen at least one visible change per Shot: material response, camera travel, light sweep, environmental reaction, impact, reveal, or final lock-off. Avoid repeating the same visual grammar across adjacent Shots.

Keep suggested duration in JSON. Do not put duration or aspect ratio wording in copy-ready prompt text.

Before handoff, verify:

- the exact subject, scene, and music preface is present
- every session Shot appears exactly once and in order
- every block states environment/composition, action, camera, and visible change
- every block states its own start state, spatial relation, and landing state without relying on a per-shot image
- global continuity covers identity, world, style, geometry, and avoid rules
- no style reference imports unrelated subjects or scenery
- no block contains `@shotXX`, a line/final asset path, or an instruction to upload generated storyboard imagery
- explicit references name only images the user actually supplied or confirmed for an image-guided workflow

## Update

Patch the session, then render:

```bash
python3 "$STORYBOARD_DIRECTOR_ROOT/scripts/update_story_session.py" SESSION.json PATCH.json --validate-profile smoke --workspace-root /path/to/workspace
```

Use workflow validation before final handoff:

```bash
python3 "$STORYBOARD_DIRECTOR_ROOT/scripts/validate_story_session.py" --profile workflow SESSION.json --workspace-root /path/to/workspace
```

The updater replaces arrays. Aggregate-stage patches should normally update `aggregate_video_prompt` and per-shot prompts only when the complete `shots` array is intentionally supplied.
