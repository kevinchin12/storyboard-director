---
name: storyboard-lineart-generator
description: "Generate and register per-shot storyboard line-art from an approved storyboard session. Use after script package approval and text-only prompt preflight. Supports parallel/multi-agent generation and updates session JSON/HTML with saved asset paths."
---

# Storyboard Line-Art Generator

Use this sub-skill when the user only wants line-art generation from an existing approved storyboard session, or when the main pipeline delegates the line-art stage.

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

- read the approved `session.json`
- confirm `aspect_ratio` exists; route a missing ratio back to script planning instead of mutating approved inputs
- confirm `text_review.script_logic_check` and `text_review.line_art_prompt_preflight` have no blocking issues
- create a worker queue before image generation
- generate one real raster line-art image per shot
- save or register each result under the session `assets/` folder
- update only `line_art.gallery` and compact status fields
- render `session.html`
- run smoke validation

Do not:

- rewrite the script
- rewrite production anchors unless generation is blocked by a concrete prompt error
- generate final colored frames
- generate aggregate video prompts
- upload generated line art back to AI for visual critique
- ask for API keys or switch to CLI/API image fallback

## Multi-Agent Rule

If there are 2 or more independent shots, build a worker queue before the first image call.

Worker input should be short:

- `session_path`
- `assets_dir`
- `project_mode`
- `aspect_ratio`
- compact `production_reference`
- `shot_id`
- line-art prompt
- needed character/scene reference paths
- target output filename

Worker output must be path-based:

- `shot_id`
- `asset_type: line-art`
- `status`
- `output_path`
- optional `retry_prompt`
- short note

Only the orchestrator edits `session.json` and renders HTML.

Create the full queue before any image call. Default to four concurrent line-art workers. If delegation is unavailable, record `serial_unavailable` and execute the same queue in Shot order.

Parallel workers must return explicit local source paths. Do not use one shared `capture_generated_asset.py` marker across concurrent jobs.

## Line-Art Rules

Line art is a contour and structure map:

- sparse outer contours
- key silhouette lines
- major object boundaries
- horizon, vanishing, or perspective guide lines only when useful
- white or off-white background
- thin clean lines

Avoid:

- shadows
- gray fills
- hatching
- cross-hatching
- stippling
- texture
- material rendering
- lighting effects
- decorative detail
- dense sketch buildup

Each prompt must separately state:

1. shot structure and depth layers
2. camera, eye level, framing, and perspective
3. one frozen action moment
4. contour and avoid constraints

Use this pattern:

```text
Use case: illustration-story
Asset type: storyboard line-art draft for <Shot ID>.
Primary request: real model-created raster line-art image; not SVG, typography, or polished illustration.

SHOT STRUCTURE:
<subject placement, major objects, foreground / midground / background>

CAMERA AND PERSPECTIVE:
<shot size, viewpoint, framing, vanishing point, required alignments>

ACTION LAYER:
<one frozen action moment>

DETAIL LIMIT:
Only outer contours, key silhouettes, major boundaries, minimal face/hand cues, and necessary perspective guides.

STYLE CONSTRAINTS:
Sparse thin contour drawing, locked <aspect_ratio>, plain white or off-white background, long edge around 1536px. No color, shadows, gray fills, hatching, stippling, gradients, texture, material rendering, lighting effects, decorative detail, text, labels, borders, UI, watermark, logos, or extra characters.
```

Use a two-pass blocking-layout then clean-contour process only when preflight identifies concrete perspective or shared-space risk. After one repeated perspective failure, simplify the task to an animation layout or blocking thumbnail instead of repeating the same atmospheric prompt.

Line-art JPGs should normally stay below about `1.5MB`. If one is heavier, retry once with stricter contour-only constraints.

Target new assets as `.jpg`, usually:

```text
assets/shot01-line.jpg
assets/shot02-line.jpg
```

## Registration

After every successful output, register it:

```bash
python3 "$STORYBOARD_DIRECTOR_ROOT/scripts/register_story_asset.py" SESSION.json --asset-type line-art --shot-id "Shot 01" --source SOURCE_IMAGE --output-name shot01-line.jpg --validate-profile smoke --workspace-root /path/to/workspace
```

Verify:

- the registered path is under `assets/`
- `session.json` has the matching `line_art.gallery` item
- `session.html` contains the same path

If the generated source file cannot be located, mark the shot as blocked and keep the prompt for retry. Do not claim delivery from a chat-only image.

Preferred built-in `image_gen` capture:

```bash
python3 "$STORYBOARD_DIRECTOR_ROOT/scripts/capture_generated_asset.py" SESSION.json --mark --workspace-root /path/to/workspace
```

Then call `image_gen`, and register the new local file:

```bash
python3 "$STORYBOARD_DIRECTOR_ROOT/scripts/capture_generated_asset.py" SESSION.json --asset-type line-art --shot-id "Shot 01" --output-name shot01-line.jpg --workspace-root /path/to/workspace
```
