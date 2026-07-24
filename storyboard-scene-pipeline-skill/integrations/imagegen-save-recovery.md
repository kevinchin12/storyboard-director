# ImageGen Save Recovery

Use this when built-in `image_gen` appears to create an image in chat but the agent does not yet have a reliable project-local file path.

The goal is not to switch providers or ask for API keys. The goal is to recover or register a real local raster file.

Resolve `STORYBOARD_DIRECTOR_ROOT` to the installed/source main skill directory before running commands. This marker flow is serial recovery only; concurrent workers must return explicit source paths or use isolated capture state.

## Preferred Capture Flow

Before calling `image_gen`, write a marker:

```bash
python3 "$STORYBOARD_DIRECTOR_ROOT/scripts/capture_generated_asset.py" SESSION.json --mark --workspace-root /path/to/workspace
```

After `image_gen` returns, capture and register the single unambiguous generated file:

```bash
python3 "$STORYBOARD_DIRECTOR_ROOT/scripts/capture_generated_asset.py" SESSION.json --asset-type line-art --shot-id "Shot 01" --output-name shot01-line.jpg --workspace-root /path/to/workspace
```

For final frames:

```bash
python3 "$STORYBOARD_DIRECTOR_ROOT/scripts/capture_generated_asset.py" SESSION.json --asset-type final-frame --shot-id "Shot 01" --output-name shot01-final.jpg --workspace-root /path/to/workspace
```

The script searches `$CODEX_HOME/generated_images` and `~/.codex/generated_images`, ignores files that existed before the marker, and delegates registration to `register_story_asset.py` only when exactly one new or modified raster file is found. If several candidates appear, it refuses to guess; rerun with an explicit `--source` path. This is why the marker flow is serial-only.

## Known Source Path

If the tool or user gives an explicit local image path, skip discovery:

```bash
python3 "$STORYBOARD_DIRECTOR_ROOT/scripts/capture_generated_asset.py" SESSION.json --asset-type line-art --shot-id "Shot 01" --source /path/to/generated.png --output-name shot01-line.jpg --workspace-root /path/to/workspace
```

## Failure Rule

If no new file is found:

- do not claim the shot is delivered
- do not reference chat-only images from `session.json`
- do not switch to CLI/API generation or ask for provider credentials
- mark the shot as blocked or pending with the attempted prompt
- retry built-in image generation or ask the user for a saved local file path
