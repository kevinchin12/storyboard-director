---
name: storyboard-script-planner
description: "Plan the script package for a storyboard session: ingest story ideas plus optional character/scene references, lock aspect ratio and project mode, write shot text, production anchors, line-art prompts, and text-only script/prompt review. Use this before storyboard line-art generation."
---

# Storyboard Script Planner

Use this sub-skill when the user needs the story/script stage only, or when the main storyboard pipeline delegates script planning.

This sub-skill can run independently. It reads and writes the shared session state:

- `session.json`
- `session.html`
- `assets/`
- `storyboard.config.json`

It does not generate images.

## Runtime Root

Resolve `STORYBOARD_DIRECTOR_ROOT` before running commands:

- installed bundle: `${CODEX_HOME:-$HOME/.codex}/skills/storyboard-director`
- source checkout: the nearest ancestor containing both the main `SKILL.md` and `scripts/`

Use absolute script paths. Do not assume the user's current workspace contains the skill source folder.

## Session Resolution

Use an explicit session path when provided. Initialize a session only for a clearly new story. For continuation without a path, inspect the configured `sessions/` and `examples/` directories and continue automatically only when exactly one session matches. If multiple sessions could match, ask for the exact path; never guess the newest session.

## Scope

Do:

- create or update a session with `scripts/init_story_session.py`
- write `project_title_en`; preserve the wording, capitalization, and punctuation of a user-specified value, otherwise translate `project_title` into a concise natural English story title without asking
- ingest user-provided character, scene, and style images with `scripts/register_story_reference.py`
- set `project_mode`: `character`, `subject`, `spatial`, or `atmospheric`
- set `aspect_ratio`; default to `16:9` when the user did not specify
- write the full shot list
- write `production_reference`
- write per-shot `line_art` prompts
- run text-only script logic review
- run text-only line-art prompt preflight
- render HTML for user review

Do not:

- generate line-art images
- generate final frames
- write the aggregate video prompt after line-art review
- upload generated images for AI visual review
- ask for OpenAI API keys or CLI image fallbacks

## Required Output

Update `session.json` with:

- `project_title`
- `project_title_en` (explicit user value first; otherwise the Agent's translation of `project_title`)
- `project_summary`
- `aspect_ratio`
- `project_mode`
- `visual_references`
- `outline`
- `script`
- `production_reference`
- `character_performance_lock` when relevant
- `shots[]`
- `line_art.prompt_block`
- `text_review.script_logic_check`
- `text_review.line_art_prompt_preflight`

Then render:

```bash
python3 "$STORYBOARD_DIRECTOR_ROOT/scripts/render_story_session.py" SESSION.json --workspace-root /path/to/workspace
```

For patch updates, prefer:

```bash
python3 "$STORYBOARD_DIRECTOR_ROOT/scripts/update_story_session.py" SESSION.json PATCH.json --validate-profile smoke --workspace-root /path/to/workspace
```

The updater replaces arrays. When changing `shots`, provide the complete intended shot list; never send one Shot and expect an in-place merge.

## Planning Rules

Write the first review package as one complete unit. Include storyboard text and production-ready line-art prompts together. Do not make them separate default rounds.

Choose one `project_mode`:

- `character`: people and acting continuity
- `subject`: products, vehicles, mascots, creatures, or objects
- `spatial`: architecture, routes, landscapes, or place-driven sequences
- `atmospheric`: light, weather, material, or mood transitions

Lock the aspect ratio before prompts. Use `16:9` when unspecified.

For video-oriented planning:

- default most shots to `4-6s`
- give each shot one start-to-end visible action beat
- merge dependent micro-shots that cannot sustain four seconds
- split unrelated actions instead of overloading one prompt
- keep any draft copy-ready video prompt text-self-contained: spell out environment/composition, start state, spatial relation, one action path, camera behavior, visible change or landing, and continuity
- treat generated line art and finished frames as internal planning evidence only; never write `@shotXX`, local line/final asset paths, or instructions that require the user to upload a per-shot storyboard image
- keep `video_prompt.reference_frame` empty in the default `text_only` workflow; populate it only after the user explicitly selects `image_guided` and confirms an actual upload image

Set a compact scene budget before the shot list. For six shots, prefer about two main scenes with multiple angles and action phases. Add a location only when story, escalation, or geography requires it.

Write action as visible mechanics:

```text
trigger -> movement process -> landing or held reaction -> spatial relation -> visible result
```

For character work, create `character_performance_lock` and separate stable identity from allowed acting changes. Lock face/age, hair, wardrobe silhouette, key prop, proportion, posture, and movement quality. Allow pose, gaze, hand position, weight shift, step phase, breath, reaction, and camera distance to change.

For spatial or continuous-shot work, name fixed anchors and state the physical camera relation: same axis, push-in, pullback, side-track, orbit, or wider/closer view of the same layout. Do not hide lens jumps inside vague cinematic wording.

Avoid repeating the same camera height or motion grammar across adjacent shots unless the brief explicitly requires formal repetition.

## Text Review Gate

Text review is mandatory before line-art dispatch, but it is not image review.

Script logic review checks:

- shot order and cause-effect
- visible reason each shot exists
- one primary action beat per shot
- start -> process -> landing action path
- camera motivation
- scene geography
- character, prop, weather, light, and effect continuity
- adjacent-shot redundancy

Line-art prompt preflight checks:

- contour-only storyboard line art
- no shadows, gray fills, hatching, texture, material rendering, lighting effects, or decorative polish
- subject, scene, action freeze, camera, depth layers, and aspect ratio are explicit
- reference-image duties are clear
- continuity locks and allowed changes are written for shared-space shots
- avoid rules prevent extra characters, redesigned locations, labels, text, and crowded detail

If either review has unresolved blocking issues, revise the script or prompt before handing off to line-art generation.

Record compact `blocking_issues` and `fixes_applied`; do not write a long critique into session state.

## Handoff

When done, tell the user:

- `session.json` path
- `session.html` path
- whether the script package is ready for approval
- whether line-art generation is blocked by text review issues
