# Storyboard Director

一个可分享的故事板工作流 Skill：把故事想法、场景图和角色设定图整理成分镜脚本、线稿规划和合并版提示词，并把 review surface 统一沉淀到单个 HTML。

这份项目同时提供两种使用形态：

- `Codex Skill 包`：主 skill 名为 `storyboard-director`，源码目录仍是 `storyboard-scene-pipeline-skill`
- `项目模板`：直接 clone 当前目录，在任意工作区内创建和运行 session

## Quickstart

如果只是要在新对话里测试 skill，直接复制根目录 `README.md` 中 **Start A Session** 的提示词。

### 作为项目模板使用

1. 进入工作区根目录，确认存在 `storyboard.config.json`
2. 初始化一个 session：

```bash
python3 storyboard-scene-pipeline-skill/scripts/init_story_session.py "你的故事标题"
```

3. 更新 session：

```bash
python3 storyboard-scene-pipeline-skill/scripts/update_story_session.py sessions/<timestamp>-<slug>/session.json patch.json --validate-profile smoke
```

4. 登记用户提供的人物、场景或风格参考图：

```bash
python3 storyboard-scene-pipeline-skill/scripts/register_story_reference.py sessions/<timestamp>-<slug>/session.json --reference-type character --source /path/to/reference.png --label "Lead Character"
```

5. 单独重渲染：

```bash
python3 storyboard-scene-pipeline-skill/scripts/render_story_session.py sessions/<timestamp>-<slug>/session.json
```

6. 可选：生成 3 列最终画面合并图：

```bash
python3 storyboard-scene-pipeline-skill/scripts/generate_storyboard_sheet.py sessions/<timestamp>-<slug>/session.json --asset-type final-frame --validate-profile workflow
```

该脚本只在你启用“风格参考 -> 最终画面”可选分支后使用。它会读取已登记的 `final_generation.gallery`，按 Shot 顺序拼成 `assets/storyboard-final-3col.jpg`，写入 `storyboard_sheet`，并重渲染 HTML。默认线稿流程不需要生成最终画面合集图。

7. 校验：

```bash
python3 storyboard-scene-pipeline-skill/scripts/validate_story_session.py --profile smoke sessions/<timestamp>-<slug>/session.json
python3 storyboard-scene-pipeline-skill/scripts/validate_story_session.py --profile workflow sessions/<timestamp>-<slug>/session.json
python3 storyboard-scene-pipeline-skill/scripts/validate_story_session.py --profile release sessions/<timestamp>-<slug>/session.json
```

8. 审计 session 体积，或导出新线程 handoff：

```bash
python3 storyboard-scene-pipeline-skill/scripts/audit_story_assets.py sessions/<timestamp>-<slug>/session.json
python3 storyboard-scene-pipeline-skill/scripts/export_story_handoff.py sessions/<timestamp>-<slug>/session.json
```

9. 运行健康检查和发布审计：

```bash
python3 storyboard-scene-pipeline-skill/scripts/doctor_storyboard_skill.py
python3 storyboard-scene-pipeline-skill/scripts/build_public_bundle.py
python3 storyboard-scene-pipeline-skill/scripts/release_audit.py
```

10. 修改脚本后运行回归测试（仅依赖标准库和 Pillow）：

```bash
python3 -m unittest discover -s tests
```

### 作为 Codex Skill 安装使用

1. 把 `storyboard-scene-pipeline-skill` 复制到你的 skill 目录
2. 在目标工作区根目录放置一份 `storyboard.config.json`
3. 在目标工作区里执行：

```bash
python3 /path/to/storyboard-scene-pipeline-skill/scripts/init_story_session.py "你的故事标题" --workspace-root /path/to/workspace
```

如果你的配置文件不在工作区根目录，也可以改用：

```bash
python3 /path/to/storyboard-scene-pipeline-skill/scripts/init_story_session.py "你的故事标题" --config /path/to/storyboard.config.json
```

## 目录结构

```text
storyboard-scene-pipeline/
├── storyboard.config.json
├── storyboard-scene-pipeline-skill/
│   ├── SKILL.md
│   ├── assets/
│   ├── scripts/
│   └── skills/
│       ├── storyboard-script-planner/
│       ├── storyboard-lineart-generator/
│       ├── storyboard-aggregate-prompt/
│       └── storyboard-final-frame-optional/
├── sessions/
│   └── <timestamp>-<slug>/
│       ├── session.json
│       ├── session.html
│       └── assets/
└── examples/
    ├── character/
    ├── subject/
    ├── spatial/
    └── atmospheric/
```

## `project_mode` 选择指南

- `character`：角色驱动。重点是角色身份、服装、表情、动作连续性。
- `subject`：非人主体驱动。重点是生物、产品、道具、载具等主体的形态和材质一致性。
- `spatial`：空间驱动。重点是地点识别、空间逻辑、机位连续性。
- `atmospheric`：氛围驱动。重点是光线、材质、天气、节奏和世界观情绪。

推荐流程：

1. 用户提供故事想法，以及数量不定的场景图和角色设定图；这些参考图写入 HTML 的 `角色设定图 / 场景图` 区域。
2. 一次性生成 `script package`：`project_mode`、`aspect_ratio`、可审核的分镜文字、production anchors、逐镜 line-art prompts 和文本审查结果。用户没指定画面比例时默认 `16:9`。第一轮默认就给分镜文字、线稿脚本、脚本逻辑审查和线稿提示词预检；不拆成先写分镜、再补线稿提示词。
3. 用户确认脚本包；小修直接改同一版，不开第二套脚本。
4. 生成前执行文本审查：脚本逻辑审查检查因果、镜头功能、动作路径、机位动机和连续性；线稿提示词预检检查 contour-only、主体/场景/动作/构图/透视锁和 avoid rules。这里不上传生成后的图片给 AI 看。
5. 线稿按镜头拆成并行 worker 任务：多 Agent 执行是默认必选项，子 Agent 只负责生成并返回本地路径，主 Agent 统一写 JSON、刷新 HTML，不让 AI 回看审核。生成前必须写入 `parallel_generation.dispatch_mode`。
6. 用户在 HTML 里看完整线稿，只点名需要返修的镜头；AI 只在这些点名返修里看图。
7. 线稿确认后，生成合并版提示词。默认不生成最终画面、不生成最终画面合集图。
8. 只有当用户明确要求生成最终画面时，才启用最终画面分支；风格输入可以是参考图，也可以是文字风格锁。

## Skill 入口结构

主入口：

- `storyboard-scene-pipeline-skill/SKILL.md`

副 skill 入口：

- `storyboard-scene-pipeline-skill/skills/storyboard-script-planner/SKILL.md`
  用于故事想法、角色/场景参考、脚本包、文本审查和线稿提示词预检。
- `storyboard-scene-pipeline-skill/skills/storyboard-lineart-generator/SKILL.md`
  用于读取已确认 session，执行多 Agent / 并行线稿生成，登记资产并刷新 HTML。
- `storyboard-scene-pipeline-skill/skills/storyboard-aggregate-prompt/SKILL.md`
  用于线稿确认后生成固定前置区 + ordered Shot blocks 的合并版提示词。
- `storyboard-scene-pipeline-skill/skills/storyboard-final-frame-optional/SKILL.md`
  只在用户明确要求风格参考和最终画面时使用。

每个副 skill 都可以独立承担一个阶段，但安装包必须同时包含主 skill 的运行脚本。副 skill 先把 `STORYBOARD_DIRECTOR_ROOT` 解析为 `${CODEX_HOME:-$HOME/.codex}/skills/storyboard-director`，再从其 `scripts/` 运行命令。所有阶段必须围绕同一个 `session.json` / `session.html` / `assets/` 工作，不要依赖聊天历史作为状态源。

推荐安装方式是从公共包根目录运行：

```bash
python3 storyboard-scene-pipeline-skill/scripts/install_storyboard_skills.py
```

默认会把主 skill 和 4 个副 skill 以 symlink 安装到 `~/.codex/skills`，适合测试时直接改项目源码。正式发给不改源码的人时，可以改用复制安装：

```bash
python3 storyboard-scene-pipeline-skill/scripts/install_storyboard_skills.py --copy
```

如果是从旧安装更新，使用 `--force`。

安装器默认读取 `$CODEX_HOME`，未设置时才使用 `~/.codex`。

## 最终交付物

面向 AI 视频平台测试时，session 最终至少应产出：

- 用户提供的角色设定图和场景图，显示在 HTML 的参考图片区。
- 每个 Shot 的线稿图，可作为结构、构图和镜头关系参考。
- 一个 `aggregate_video_prompt`，用于整片生成或整片平台测试。它必须以固定前置区开始，然后按顺序逐个描述所有 Shot，并为每个 Shot 写清环境/构图、起始状态与空间关系、主体动作路径、镜头运动、可见变化和落点；不能只列镜头名称。平台直贴提示词不写时长和画幅，也不得要求用户上传或 `@` 内部生成的逐镜线稿、最终帧、分镜合成板或本地资产路径。时长默认只保留在 JSON 内部规划字段，不在 HTML 页面展示。

合并版提示词固定前置区：

```text
主体:@对应的角色设定图
场景:@对应的场景图
音乐:不要生成任何背景音乐和旋律，只需要生成场景及动作对应的音效
```

如果没有提供角色设定和场景图：

```text
主体:（Codex 生成角色设定描述）
场景:（Codex 生成场景描述）
音乐:不要生成任何背景音乐和旋律，只需要生成场景及动作对应的音效
```

可选交付物：

- 如果用户要求提供风格参考后生成对应画面，再生成每个 Shot 的最终静态帧。
- 同时可生成 `storyboard_sheet`，即 3 列最终画面 JPG 合并图。

默认资产格式：

- 新生成的线稿保存为 `.jpg`；可选最终静态帧和 3 列最终画面合集图也保存为 `.jpg`。
- 历史 session 里的 `.png`、`.jpeg`、`.webp` 路径仍可继续读取，但新 worker 任务默认给 `.jpg` 目标路径。
- 如果图像模型只返回 PNG，用 `register_story_asset.py` 登记；它会复制/转换成 session `assets/` 下的 JPG，再写入 `session.json` 和 HTML。
- 默认不生成 3 列最终画面合集图。只有启用最终画面分支后，才用 `generate_storyboard_sheet.py` 生成 3 列 JPG 合并图；不要在 session 目录里临时维护一次性拼图脚本，除非正在开发这个 bundled script 本身。
- `register_story_asset.py` 必须使用 session 中真实存在的 `shots[].id`。如果 `--shot-id` 写错，脚本应失败，而不是创建不会显示的孤立 gallery 项。
- 线稿默认登记长边约 `1536px`；最终静态帧默认长边约 `2048px`，除非你用 `--long-edge` 显式覆盖。
- 不要因为内置 `image_gen` 没有立刻落盘，就改走本地 OpenAI CLI/API fallback。正常 storyboard 生图流程不应该要求用户提供 `OPENAI_API_KEY` 或任何 API key。
- 如果内置生图后找不到本地文件，先用 `capture_generated_asset.py` 的 `--mark` / 捕获流程从 `$CODEX_HOME/generated_images` 或 `~/.codex/generated_images` 找出新图并注册；详细规则见 `storyboard-scene-pipeline-skill/integrations/imagegen-save-recovery.md`。如果捕获失败，再把对应 Shot 标成 `blocked_asset_not_found`，保留提示词，重试内置生图或让用户提供已保存文件路径；不要把没有路径的聊天图片当成交付资产。
- 如果用户要求风格参考后生成对应画面，才进入 style lock 和最终画面生成；否则 HTML 默认隐藏所有画面相关区域。

## 性能与线程卫生

这套流程会生成很多图。如果把图片、历史记录或长篇过程复盘直接塞进同一个 Codex thread，慢的主要原因通常不是网络，而是线程和上下文变重。

默认规则：

- 每个故事或项目尽量使用独立 thread；旧 thread 只保留简短 handoff，不继续跑主流程。
- 图片只保存到当前 session 的 `assets/` 目录；`session.json`、`session.html` 和聊天里只引用本地路径。
- 每张线稿都必须按 `shot_id` 写回对应 gallery 项，再重渲染 HTML；不能只靠数组顺序、聊天记忆或“刚生成的是第几张”判断。最终帧只在可选分支里同样登记。
- 生成结果不算交付，除非本地文件存在，并且对应图片路径已经出现在 `session.html` 里。
- 默认不把生成后的线稿再上传给 AI 审核。只有用户点名某个问题镜头、或明确要求 AI 帮忙诊断时，才上传这一轮必须看的 1-3 张图。
- 不把内联图片数据、截图原文、长历史、压缩记录或生成日志塞进 `session.json`。
- 一个 session 结束后，用 5-10 行记录当前状态、关键路径和下一步，不复制完整 HTML 或图片内容进新对话。
- 如果 validator 报 session 过大，优先清理内联图片或历史字段，而不是继续扩大上下文。

当前脚本会拦截：

- `session.json` 超过约 1MB
- `session.html` 超过约 2MB
- JSON/HTML 中出现内联图片或数据负载
- 单个字符串字段异常变长，疑似塞入历史或图片内容

推荐运行节奏：

1. 故事 / 参考图阶段：用 `register_story_reference.py` 将用户提供的角色、场景或风格图保存到 `assets/`，写入对应参考列表，HTML 在故事板前显示这些参考图。
2. 线稿生成阶段：主 Agent 必须先创建 per-shot worker queue；有子 Agent 能力时并行出图，没有时按同一队列串行执行。每张只记录本地路径和简短状态，按 `shot_id` 写入 `line_art.gallery`，重渲染 HTML 并确认路径出现，不做 AI 视觉评审。
3. 用户复核阶段：HTML 是主 review surface；用户点名问题镜头后再进入 targeted repair。
4. 合并提示词阶段：线稿确认后生成 `aggregate_video_prompt`，固定前置区写主体、场景和音乐，后续按 Shot 顺序展开。
5. 可选最终画面阶段：只有用户要求提供风格参考并生成对应画面时，才启用 style lock、`final_generation.gallery`、画面栏和最终画面合集图。
6. 线程变慢或跨天继续时：运行 `export_story_handoff.py`，在新 thread 粘贴 handoff 文件内容和 session 路径。

校验节奏：

- 日常小 patch：使用 `update_story_session.py --validate-profile smoke`，或只 render HTML。单独运行 validator 时使用 `validate_story_session.py --profile smoke`。
- 人工确认点：跑 `--profile workflow`，确认字段、结构、HTML 都能继续往下一阶段走。
- 最终交付 / 对外分享：才跑 `--profile release`、`release_audit.py` 和 `build_public_bundle.py`。
- 不要在每一次图片生成、每一次文字微调后都跑完整 release audit。

## 提示词控制 / AI 不审核流程

公开版默认走 `prompt_control_no_ai_review`。目标不是放弃质量，而是把质量控制前移到脚本包、脚本逻辑审查和提示词预检里，生成后由用户在 HTML 里复核。

### 5 个必要关口

1. `Script Package Gate`
   一次确认脚本、项目模式、画面比例、连续性锚点、线稿提示词和文本审查结果。不要把 `project_mode`、画面比例、分镜文字、线稿计划拆成多轮。用户没指定画面比例时默认 `16:9`。

2. `Text Review Gate`
   生成前只审文字：脚本逻辑审查负责镜头顺序、因果、动作路径、机位动机和连续性；线稿提示词预检负责 contour-only 约束、主体/场景/动作/构图/透视锁和 avoid rules。这个关口不上传生成后的线稿给 AI 看。

3. `Rolling Generation`
   线稿按镜头拆成并行生成任务。子 Agent 只生成图片并返回路径；主 Agent 保存文件、写入 JSON、刷新 HTML。AI 不默认回看、不写长评审。

4. `User HTML Review`
   用户在 HTML 里看整组线稿，只点名需要修改的镜头。没被点名的镜头不进入返工。

5. `Aggregate Prompt Package`
   合并版提示词一次生成。固定前置区写主体、场景、音乐；后续按 Shot 顺序处理，不设单镜测试关口。

### 默认跳过或合并的步骤

- 不单独做 `mode_lock` 轮次，除非 brief 模糊。
- 不单独做 `reference_lock` 轮次；production anchors 写进 script package。
- 不把 `revision` 作为固定阶段；只有用户提出修改时才进入修订。
- 不单独等待 `line-art prompt plan` 确认；它随 script package 一起确认。
- 不单独等待 `style reference lock` 确认；默认流程没有风格参考和最终画面生成。只有用户明确要求时才进入可选分支。
- 不逐镜头做长篇视觉复盘；成功图片只记录路径和 `saved for user review`，问题镜头才展开。

### 多 Agent 并行生图

默认必须优先规划的是生图 worker queue，不是审核 worker。只要线稿或最终帧批次里有 `2` 个及以上互不依赖的镜头，主 Agent 必须先创建 worker queue，再开始生图；不能先串行画 Shot 01，再临时决定是否并行。使用这个 skill 默认等同于开启多 Agent 生图执行，除非用户明确要求串行，或当前工具环境没有可调用子 Agent / worker 能力。

- 主 Agent 负责脚本包、prompt preflight、风格规则、任务队列、状态写入和 HTML 渲染。
- 主 Agent 在生成前必须写入 `parallel_generation.dispatch_mode`：`multi_agent`、`reduced_concurrency` 或 `serial_unavailable`。
- 子 Agent 只拿单个 Shot 或小批 Shot 的生图提示词、锁定画面比例、必要参考路径和目标输出路径。
- 子 Agent 输出只允许包含：`shot_id`、`asset_type`、`status`、`output_path`、可选 `retry_prompt`、一句简短 note。
- 子 Agent 不改 `session.json`，不渲染 HTML，不重写脚本，不评价其他镜头。
- 主 Agent 收到结果后按完成顺序串行合并：检查文件存在、patch 对应 gallery/path、重渲染 HTML、必要时跑 smoke validation；HTML 展示顺序仍按 Shot 顺序。
- 默认并发：线稿 `4` 个 worker，最终帧 `3` 个 worker。
- 如果当前工具环境不能使用子 Agent，仍然要使用同一 worker queue，只是按 Shot 顺序串行执行；这叫 `serial_unavailable`，不是跳过队列规划，并且必须在 `reduced_concurrency_reason` 写清工具限制。
- 真人、强产品一致性、精确地标、可读文字、连续空间镜头，可以把最终帧 worker 降到 `1-2`，但必须在 `parallel_generation.reduced_concurrency_reason` 里写清原因。

### 线稿复杂度

线稿只用于锁结构，不是插画稿。

- 只要外轮廓、主体剪影、主要物体边界、地平线 / 消失点 / 少量透视辅助线。
- 不要阴影、投影、明暗面、灰度填充、排线、交叉排线、点描、纸纹、材质、光效和装饰细节。
- 背景保持白色或浅米白，不要大面积灰色。
- 线条保持细、干净、稀疏。
- 线稿长边默认约 `1536px`，除非用户明确要求高清线稿。
- 单张线稿通常应低于约 `1.5MB`；如果超过，优先说明提示词太复杂，重跑 contour-only 版本。

### 什么时候不能压缩

- brief 本身不清楚，必须先问一个短问题。
- 角色、产品、地标、建筑、车、人脸、文字等存在强一致性风险。
- 用户在 HTML 里点名某个问题镜头，必须只修这个镜头，不批量扩大错误。
- 用户明确要求逐镜头精修或正式交付级审查。

## 商业片 / 产品片注意事项

商业片、产品片、运动片、车片和其他冲击力导向项目，不能只依靠“高级”“动感”这类形容词。脚本阶段就要检查：

- 相邻镜头的景别、角度、镜头运动和主体状态是否有明显差异。
- 每个镜头是否有一个明确可见的动作幅度，例如光扫、压缩、推进、环绕、材质响应或最终锁定。
- 单镜头提示词是否可以直接贴到平台，而不是只看起来专业但缺少可执行动作。
- 整片提示词是否逐 Shot 描述了画面、动作和镜头运动，并同时约束主体一致性、风格一致性、镜头顺序和禁忌项。

默认脚本策略会比静态故事板稍微激进：不论是角色片、主体片、空间片还是氛围片，都要优先设计可见的动作、镜头、光线或环境变化，而不是只写漂亮但静止的画面。

## 动作与连续性增强规则

脚本阶段建议默认按下面这套方式写镜头，不要只写抽象氛围：

- `动作` 优先写成可见行为，推荐公式：`起点姿态/触发 -> 可见动作过程 -> 落点/停顿反应 -> 空间关系 -> 可见结果`
- 一个镜头只承担一个主要动作节拍；如果一条镜头里已经出现两个以上核心动作，优先拆镜
- 如果你写的是情绪，必须落成姿态、距离、视线、手部动作、阻挡关系或道具状态
- `continuity` 不只写什么不能变，也要写什么可以变化，例如机位距离、光线状态、道具损耗、动作阶段
- 如果后一镜只是同一空间的拉远、推进或同轴延续，要明确写成 `同一布局的拉远/推进/侧移`，不要让模型误判成一个新场景

### 人物片增强规则

人物片不能只写“一个女孩走过去”“男人转身”“角色很难过”。脚本包必须先写 `character_performance_lock`，再进入分镜和视频提示词。

- 身份锁：脸部年龄感、发型、服装剪影、关键道具、身体比例、姿态和运动质感。
- 表演路径：起始姿态 / 视线 / 手部位置 -> 可见动作过程 -> 落点姿态或停顿反应。
- 参考职责：角色图只锁身份、脸、体型、服装和比例；动作参考视频只锁身体运动或节奏；运镜参考视频只锁镜头路径；音频只锁节奏和氛围。
- 允许变化：姿态、视线、手部位置、步态阶段、光线状态、机位距离。
- 禁止漂移：改脸、年龄感变化、换衣服、关键道具消失、身体比例变化、把动作参考里的人物或场景带进来。

角色视频提示词必须写成 `主体身份 -> 起始状态 -> 主要动作路径 -> 镜头运动 -> 必须保留 -> 允许变化 -> 避免`。如果一条 prompt 里同时出现走路、转身、伸手、说话、反应等多个不相干动作，默认拆成多镜头。

连续镜头、无人机片、车片、空间揭示片，额外建议：

- 默认按 `one physical camera path` 来理解，不把每一镜写成互相断开的独立机位
- 默认一条连续运动使用一个虚拟镜头；景别变化优先解释成物理位移，不要无解释切换焦段
- 避免无原因的 push-in 接 pullback、wide 接 tele、或同一条连续运动里随机换镜头语法

如果是 `spatial` 模式，或多镜头共享一个地点 / 路径 / 房间 / 车内 / 山脊揭示空间，建议显式加一个“空间连续性锁”：

- 固定锚点：河道、桥梁、门、窗、楼梯、屋脊、山脊、桌面、地平线、入口方向
- 机位关系：同轴、拉远、推进、侧移、绕行、揭示
- 允许变化项：只写真正允许变的内容，例如灯光状态、角色姿态、道具开合、镜头距离

视频阶段仍然要保持分层，不要混成一个 prompt：

- 故事板 / 线稿 / 最终静态帧：用于用户查看和内部编写时锁定结构，不作为默认平台上传依赖
- 单镜头视频提示词：用于平台直贴执行
- 整片汇总提示词：用于整片 storyboard reference 的导演逻辑

新 session 默认使用 `video_generation.input_mode: text_only`，所有 `video_prompt.reference_frame` 保持空值。只有用户明确选择图像引导流程并确认实际会上传的图片时，才切换为 `image_guided`；显式引用只允许用户实际提供的产品、主体、角色、场景或风格参考。

## 空间片测试经验

广州高速无人机城市片这一轮测试，已经验证出下面这些规则需要固化：

- `spatial` 片不能只写“城市大景 + 高速飞行”。脚本阶段必须先确定一条清楚的空间路线，例如 `贴水进入城市 -> 地标环绕 -> 建筑峡谷 -> 老城屋顶 -> 山脊揭示 -> 英雄收尾`，否则后续静态帧和视频提示词都会漂。
- 时间推进不能只写成“白天到夜晚”。如果末段有傍晚和夜景，必须在脚本里显式保留一个 `日落前冷暖平衡 -> 蓝调初夜` 的缓冲层，否则静态帧会出现硬切时间感。
- 相邻镜头不能只换地点不换语法。至少要主动拉开其中一项：景别、运动方向、遮挡逻辑、空间尺度、时间层次。
- `aggregate_video_prompt` 不能只靠一段全局氛围描述。它必须逐 Shot 写清画面环境、主体动作、镜头运动和可见变化，否则模型会把整片交给自由发挥。
- 单镜头视频提示词必须是“可直贴平台”的文本自包含成品文案，而不是内部分析说明。至少要明确：环境/构图、起始状态和空间关系、主要动作路径、镜头运动、可见变化或落点、保留项、避免项；不得用“参考某张分镜图”代替这些画面事实。
- 收尾英雄镜头如果承接傍晚镜头，默认优先使用 `蓝调傍晚 / 蓝调初夜`，不要直接跳成纯黑深夜，除非脚本明确要做强烈昼夜跨越。
- 对于城市、建筑、山体这类几何敏感片型，只在提示词里写清空间路线、地标、透视和运动路径；默认流程仍按 Shot 顺序处理，不设置单镜测试关口。

如果用户另外要求小范围平台测试，可用下面这些标准自行挑镜头：

- 几何或运动是否容易漂移
- 地标方位是否关键
- 时间推进或镜头连续性是否容易出错

这不是默认生成顺序，也不是 AI 审核关口。

## 跨项目测试结论

已经固化成 skill 规则的共性结论：

- 修改意见先路由层级。凡是影响剧情因果、镜头数量、空间、天气/时间、角色身份或连续性的反馈，都先改脚本和 `production_reference`，再传播到线稿、合并版提示词和交付文件。
- 参考图必须分工。角色图锁脸、发型、体型、服装、鞋和个人道具；风格图只锁光线、色彩、氛围、阴影体量和完成度；故事脚本锁地点、道具、天气转场、揭示顺序和镜头逻辑。
- 加入新角色参考后，要搜索并清理旧身份描述。不能只追加“参考新图”，同时保留旧的头发、外套、年龄感或剪影描述。
- 天气和时间转场属于脚本逻辑，不是最后靠颜色提示词补救。比如“蓝天白云 -> 变暗 -> 白云变灰 -> 乌云聚集 -> 陨石边缘出现”必须贯穿 shot frame、action、continuity、video prompt 和 aggregate prompt。
- 预览拼图不能冒充逐镜线稿或最终帧。默认流程只承诺已登记的 `line_art.gallery` 和合并版提示词；最终帧只在可选分支里成立。
- 动作片先判断主体 agency。攻击、躲避、反应、压制、占领是不同镜头任务；不要让一套低角度冲刺语法重复占满整组镜头。
- 线程变重后立刻切到 path-only：只保存文件、更新 JSON/HTML、导出 handoff；除非用户点名问题镜头，不再上传或回看整批图片。

## 必须人工确认的步骤

- 脚本包：完整脚本、项目模式、画面比例、连续性锚点、线稿提示词、脚本逻辑审查和线稿提示词预检
- HTML 线稿故事板：用户看完整线稿，并点名需要返修的镜头
- 合并版提示词包：固定主体/场景/音乐前置区，加按 Shot 顺序展开的镜头提示词
- 最终交付前确认

## 常见报错

- `无法发现工作区配置`
  原因：当前目录向上找不到 `storyboard.config.json`
  处理：进入正确工作区，或传 `--workspace-root` / `--config`

- `Session 文件不存在`
  原因：传入的是错误路径，或把 session 目录名写错了
  处理：确认路径里包含 `session.json`

- `VALIDATION FAILED (workflow)`
  原因：当前阶段缺少必要字段，或 HTML 没有重渲染
  处理：先跑 `render_story_session.py`，再按失败项补字段

- `VALIDATION FAILED (release)`
  原因：最终交付仍缺线稿 raster 资产、合并版提示词结构字段，或可选最终画面分支缺资产
  处理：先补齐 `line_art.gallery` 和文本自包含的 `aggregate_video_prompt`；只有显式启用 `image_guided` 时才补用户确认的输入图路径。如果启用了最终画面分支，再补最终帧和合并图

- `session.json is too large` 或 `contains inline data/base64 payloads`
  原因：session 里混入了内联图片、长历史或过大的生成记录
  处理：把图片另存到 `assets/`，JSON 只保留相对路径；旧线程用简短 handoff 接到新线程

## 示例

- `examples/character/mibu-bedroom-adventure`：8 镜人物故事完整案例，包含角色与风格参考、线稿、最终画面、合并视频提示词和最终画面合集
- `examples/subject/sketch-to-mech-phone-case`：8 镜产品视频完整案例，包含多张产品结构参考、线稿、最终画面、拆解组装提示词和最终画面合集
