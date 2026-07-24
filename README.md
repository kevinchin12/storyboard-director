# Storyboard Director

A Codex skill for turning a story idea into a storyboard workflow:

1. script
2. text-only logic check
3. storyboard line art
4. user review in HTML
5. one aggregate video prompt

It is designed for lightweight testing and iteration. Generated images are saved as local files and shown in a single HTML board, instead of being repeatedly pasted back into the chat.

## What You Get

- A reusable Codex skill: `storyboard-director`
- Four optional stage skills:
  - `storyboard-script-planner`
  - `storyboard-lineart-generator`
  - `storyboard-aggregate-prompt`
  - `storyboard-final-frame-optional`
- A session folder for each project:
  - `session.json`
  - `session.html`
  - `assets/`
- Example sessions under `examples/`

## Install

Requirements:

- Python 3.9 or newer
- Pillow

From the project root, install the Python dependency:

```bash
python3 -m pip install -r requirements.txt
```

For a downloaded copy that you may move or delete later, install the skills as copies:

```bash
python3 storyboard-scene-pipeline-skill/scripts/install_storyboard_skills.py --copy
```

This installs the main skill and the four stage skills into `~/.codex/skills`.

For local development, use symlinks so edits are picked up immediately:

```bash
python3 storyboard-scene-pipeline-skill/scripts/install_storyboard_skills.py
```

If you are updating an older install, add `--force`.

Then restart or open a new Codex session so the skills are picked up.

## Start A Session

In Codex, use:

```text
请使用 $storyboard-director。
工作目录：
/path/to/storyboard-scene-pipeline

我会提供故事想法、角色设定图和场景图。
先创建一个新的 session，然后先出脚本包，不要直接生成图片。
```

Or create a session manually:

```bash
python3 storyboard-scene-pipeline-skill/scripts/init_story_session.py "Your Story Title"
```

Open the generated `session.html` to review the storyboard board.

## Default Workflow

1. You provide a story idea, plus optional character design images and scene images.
2. Codex writes a script package with shot text, line-art prompts, and text-only checks.
3. You approve or revise the script package.
4. Codex generates per-shot line art.
5. You review the HTML board and only name the shots that need repair.
6. After line art is confirmed, Codex writes the aggregate video prompt.

By default, the skill does not generate final colored frames. If you want that, explicitly ask for the optional style-reference / final-frame branch.

## Aggregate Prompt Format

If character and scene references were provided:

```text
主体:@对应的角色设定图
场景:@对应的场景图
音乐:不要生成任何背景音乐和旋律，只需要生成场景及动作对应的音效
```

If references were not provided, Codex writes concise subject and scene descriptions instead.

After that, the prompt continues with ordered `Shot 01`, `Shot 02`, etc.

## Important Rules

- Default aspect ratio is `16:9` unless you specify another ratio.
- Line art is contour-only: no shading, hatching, gray fills, texture, or polished rendering.
- Generated images must be saved into the session `assets/` folder and registered in `session.json`.
- The HTML board is the review surface.
- Codex should not re-upload every generated image for AI review. It only inspects images when you point to a specific problem shot.
- Duration is kept internally but hidden from the default HTML.

## Useful Commands

Health check:

```bash
python3 storyboard-scene-pipeline-skill/scripts/doctor_storyboard_skill.py
```

Register a user-supplied character, scene, or style reference:

```bash
python3 storyboard-scene-pipeline-skill/scripts/register_story_reference.py sessions/<run>/session.json --reference-type character --source /path/to/reference.png --label "Lead Character"
```

Render a session:

```bash
python3 storyboard-scene-pipeline-skill/scripts/render_story_session.py sessions/<run>/session.json
```

Validate a session:

```bash
python3 storyboard-scene-pipeline-skill/scripts/validate_story_session.py --profile smoke sessions/<run>/session.json
```

Export a handoff for a new Codex thread:

```bash
python3 storyboard-scene-pipeline-skill/scripts/export_story_handoff.py sessions/<run>/session.json
```

## More Details

For implementation notes, validation rules, packaging, and troubleshooting, see:

`docs/developer-reference.md`

## License

MIT. See `LICENSE`.
