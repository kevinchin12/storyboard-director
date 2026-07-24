---
name: storyboard-final-frame-optional
description: "Optional branch for generating final styled storyboard frames from approved line art. Use only when the user explicitly asks for finished frames; accept either a user-provided style image or a text style lock."
---

# Storyboard Final Frame Optional

Use this sub-skill only when the user explicitly asks to generate finished frames. Accept either a style-reference image or a text style lock.

This branch is not part of the default storyboard flow.

## Runtime Root

Resolve `STORYBOARD_DIRECTOR_ROOT` before running commands:

- installed bundle: `${CODEX_HOME:-$HOME/.codex}/skills/storyboard-director`
- source checkout: the nearest ancestor containing both the main `SKILL.md` and `scripts/`

Use absolute script paths. Do not assume the current workspace contains the skill source folder.

## Session Resolution

Use the explicit session path when provided. Without one, inspect configured `sessions/` and `examples/` and proceed only when exactly one session matches the request. If several sessions could match, ask for the exact path; never choose the newest session by guesswork.

## Scope

Do:

- read an existing approved `session.json`
- ingest style reference images or text style locks
- set `display_options.show_final_frames` to `true`
- generate final frames from approved line art plus style rules
- save/register final frames under `assets/`
- optionally generate the final-frame storyboard sheet when requested
- render HTML with final-frame sections visible

Do not:

- run by default
- generate final frames before script and line art are approved
- change shot order, character identity, composition, or line-art structure
- treat a style reference as permission to copy unrelated subjects or scenery
- upload generated final frames for AI review unless the user names a problem shot
- ask for API keys or switch to CLI/API image fallback

## Style Translation

Style references may control:

- color logic
- texture
- line quality
- rendering finish
- atmosphere
- lighting mood

They must not override:

- character identity
- scene anchors
- composition
- camera angle
- action freeze
- approved line-art structure

## Multi-Agent Rule

For two or more independent frames, build the full queue first and use up to three workers. Reduce concurrency to one or two for exact people, products, landmarks, readable text, or tightly continuous spaces, and record the reason.

Workers generate images and return explicit local source paths only. The orchestrator alone registers assets, edits session state, and renders HTML. Never share one capture marker across concurrent workers.

## Prompt Shape

Use this structure:

```text
Use case: sketch-to-render / illustration-story
Asset type: final static storyboard frame for <Shot ID>.
Input references: <style image role>; <line-art image role>.

Primary request:
Generate a final colored static frame in the locked project aspect ratio <aspect_ratio> by combining the saved line-art composition with the style reference. Real image-model raster output only.

LOCKED STRUCTURE FROM LINE ART:
<composition, camera, subject placement, action, key objects, depth relationships>

STYLE TRANSLATION FROM REFERENCE IMAGE:
<medium, texture, paper, line quality, palette mapping, finish level>

IMPORTANT AVOID:
Do not copy unrelated subjects or scenery from the style reference. Do not add text, readable labels, logos, captions, panel borders, UI, watermarks, extra characters, or composition changes. Preserve the line-art structure.
```

## Registration

Register each final frame:

```bash
python3 "$STORYBOARD_DIRECTOR_ROOT/scripts/register_story_asset.py" SESSION.json --asset-type final-frame --shot-id "Shot 01" --source SOURCE_IMAGE --output-name shot01-final.jpg --validate-profile smoke --workspace-root /path/to/workspace
```

For a storyboard sheet:

```bash
python3 "$STORYBOARD_DIRECTOR_ROOT/scripts/generate_storyboard_sheet.py" SESSION.json --asset-type final-frame --validate-profile workflow --workspace-root /path/to/workspace
```

Preferred built-in `image_gen` capture is the same as line art:

```bash
python3 "$STORYBOARD_DIRECTOR_ROOT/scripts/capture_generated_asset.py" SESSION.json --mark --workspace-root /path/to/workspace
```

Then call `image_gen`, and register:

```bash
python3 "$STORYBOARD_DIRECTOR_ROOT/scripts/capture_generated_asset.py" SESSION.json --asset-type final-frame --shot-id "Shot 01" --output-name shot01-final.jpg --workspace-root /path/to/workspace
```
