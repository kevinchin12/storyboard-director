# Storyboard Director

一套用于 Codex 的故事板制作 Skill。

它可以把故事想法整理成完整的分镜脚本，生成逐镜线稿，并将分镜文字、参考图、线稿和提示词汇总到一个本地 HTML 页面中。线稿确认后，它还会生成一份按镜头顺序编排的视频提示词。

图片只保存为本地文件，`session.json` 和 HTML 只记录路径，不会反复把整批图片塞回对话。这可以减少上下文膨胀，也方便长项目通过 Session 路径继续工作。

## 它能做什么

- 根据故事想法规划完整分镜
- 同时生成分镜文字和逐镜线稿提示词
- 在生图前检查剧情逻辑、动作路径和画面连续性
- 默认使用多个 Agent 并行生成逐镜线稿
- 在一个 HTML 页面中集中审核全部镜头
- 只返修你点名的问题镜头
- 生成按 Shot 顺序排列的视频提示词
- 按需生成逐镜最终画面
- 按需生成线稿或最终画面的分镜集合图

## 默认流程与确认节点

### 1. 脚本包确认

你提供故事想法，以及可选的人物、主体、场景或风格参考图。

Skill 会一次性生成：

- 故事梗概和分镜结构
- 画面比例
- 完整分镜文字
- 人物、主体、场景和连续性规则
- 逐镜线稿提示词
- 剧情逻辑检查
- 线稿提示词预检

**确认节点：**脚本包生成后暂停。确认后才进入线稿生成。

### 2. 线稿确认

脚本确认后，主 Agent 会先建立完整的镜头任务队列，再安排多个子 Agent 并行生成线稿。

每张线稿完成后会：

- 保存到当前 Session 的 `assets/`
- 按 Shot ID 登记到 `session.json`
- 自动更新本地 HTML
- 保持原始分镜顺序

Skill 默认不对生成后的整批图片再做一轮 AI 视觉审核。

**确认节点：**全部线稿进入 HTML 后暂停。你只需要指出有问题的镜头，例如“修改 Shot 03”。

### 3. 视频提示词确认

线稿确认后，Skill 会生成：

- 固定的主体、场景和音乐说明
- 按顺序排列的 Shot 提示词
- 每个镜头完整的环境、动作、机位和落点描述
- 一份可以直接复制使用的合并视频提示词

默认提示词使用 `text_only`，不强制重新上传内部生成的线稿、最终画面或分镜集合图。

**确认节点：**合并视频提示词生成后暂停，供你复制、修改或适配具体视频模型。

### 4. 最终交付检查

交付前会检查：

- Shot 是否完整且顺序正确
- 图片路径是否真实存在
- JSON 与 HTML 是否一致
- 视频提示词是否缺镜或重复
- Session 是否混入内联图片、聊天历史或超大字段

如果任务已经非常明确，也可以授权连续执行完整流程。连续执行不会取消文本检查，也不会开启整批图片的 AI 视觉审核。

## 两项重要的可选交付

除了逐镜线稿和视频提示词，Storyboard Director 还可以提供两项重要交付：

1. **逐镜最终画面**
2. **分镜集合图**

这两项默认关闭，需要明确提出后才会生成。

## 逐镜最终画面

线稿确认后，可以继续生成每个 Shot 对应的彩色最终画面。

最终画面不是重新设计分镜，而是在已经确认的线稿基础上完成风格化。它必须保持：

- 相同的 Shot 数量和顺序
- 已确认的人物身份
- 已确认的主体和产品结构
- 已确认的场景空间关系
- 已确认的动作与构图
- 相邻镜头的时间、天气和光线连续性

可以提供一张或多张风格参考图，也可以直接提供电影写实、水彩、动画、广告摄影等文字风格说明。

主 Agent 会先整理统一的风格规则，再安排子 Agent 生成逐镜最终画面。图片会保存并登记到当前 Session：

```text
assets/shot01-final.jpg
assets/shot02-final.jpg
assets/shot03-final.jpg
```

最终画面会自动进入 HTML，按照 Shot 顺序显示。你仍然可以只返修点名的镜头，不需要重新生成整套画面。

**确认节点：**逐镜最终画面全部进入 HTML 后暂停，等待人工确认。

## 分镜集合图

分镜集合图会把已经确认的逐镜图片，按照 Shot 顺序排成一张完整的大图。

它可以使用两种素材生成：

- 逐镜线稿
- 逐镜最终画面

默认采用三列布局，保留每个镜头的原始画面比例，不裁切、不改变构图，并显示清晰的 Shot 编号。

可能产生的文件包括：

```text
assets/storyboard-line-3col.jpg
assets/storyboard-final-3col.jpg
```

分镜集合图适合用于：

- 快速查看整套镜头节奏
- 检查镜头顺序和视觉连续性
- 与团队或客户集中沟通
- 保存项目阶段性成果
- 作为完整故事板的集中预览

分镜集合图是额外的集中交付文件，**不会替代逐镜图片**。每个 Shot 的独立线稿或最终画面仍会保留在 `assets/` 中，并继续作为 HTML 和 Session 的正式资产。

分镜集合图主要用于人工审核、集中预览和团队沟通，不会自动成为视频提示词的依赖。当前 `image_guided` 流程只引用用户明确提供并确认会上传的参考图，内部生成的分镜集合图不会被静默塞回视频生成流程。

## 其他可选功能

### 参考图

可以提供数量不定的人物设定图、产品或主体参考图、场景参考图和风格参考图。参考图会复制到当前 Session 的 `assets/`，并显示在 HTML 中。

### 自定义画面比例

默认比例为 `16:9`，也可以指定 `9:16`、`1:1`、`4:3`、`2.39:1` 或其他比例。画面比例会在脚本阶段锁定，并传递给所有子 Agent。

### 项目模式

- `character`：人物身份、表演和服装连续性
- `subject`：产品、汽车、鞋子、道具或其他主体
- `spatial`：城市、建筑、路线和空间关系
- `atmospheric`：天气、光线、材质和时间变化

### 独立运行副 Skill

- `storyboard-script-planner`：只做脚本和文本检查
- `storyboard-lineart-generator`：只生成和登记线稿
- `storyboard-aggregate-prompt`：只生成合并视频提示词
- `storyboard-final-frame-optional`：只运行最终画面分支

所有阶段都围绕同一个 `session.json`、`session.html` 和 `assets/` 工作。

## 安装

环境要求：

- Python 3.9 或更新版本
- Pillow 9.1 或更新版本

在项目根目录安装依赖：

```bash
python3 -m pip install -r requirements.txt
```

下载后使用复制安装：

```bash
python3 storyboard-scene-pipeline-skill/scripts/install_storyboard_skills.py --copy
```

这会将主 Skill 和四个副 Skill 安装到 `~/.codex/skills`。

本地开发时可以使用符号链接安装：

```bash
python3 storyboard-scene-pipeline-skill/scripts/install_storyboard_skills.py
```

更新旧安装时添加 `--force`。安装后重新打开一个 Codex 任务。

## 开始一个 Session

在 Codex 中输入：

```text
请使用 $storyboard-director。
工作目录：
/path/to/storyboard-scene-pipeline

我会提供故事想法、角色设定图和场景图。
先创建一个新的 session，然后先出脚本包，不要直接生成图片。
```

也可以手动创建：

```bash
python3 storyboard-scene-pipeline-skill/scripts/init_story_session.py "Your Story Title"
```

创建后打开生成的 `session.html` 进行审核。

## 开启最终画面与分镜集合图

需要逐镜最终画面：

```text
线稿确认了。现在进入最终画面分支，使用我提供的风格参考生成全部 Shot 的最终画面。
```

需要线稿集合图：

```text
请把已经确认的逐镜线稿生成一张三列分镜集合图。
```

需要最终画面集合图：

```text
最终画面确认了。请按 Shot 顺序生成一张三列最终分镜集合图。
```

## 常用命令

健康检查：

```bash
python3 storyboard-scene-pipeline-skill/scripts/doctor_storyboard_skill.py
```

登记人物、场景或风格参考图：

```bash
python3 storyboard-scene-pipeline-skill/scripts/register_story_reference.py sessions/<run>/session.json --reference-type character --source /path/to/reference.png --label "Lead Character"
```

生成线稿分镜集合图：

```bash
python3 storyboard-scene-pipeline-skill/scripts/generate_storyboard_sheet.py sessions/<run>/session.json --asset-type line-art
```

生成最终画面分镜集合图：

```bash
python3 storyboard-scene-pipeline-skill/scripts/generate_storyboard_sheet.py sessions/<run>/session.json --asset-type final-frame
```

校验 Session：

```bash
python3 storyboard-scene-pipeline-skill/scripts/validate_story_session.py --profile smoke sessions/<run>/session.json
```

为新任务导出简短 handoff：

```bash
python3 storyboard-scene-pipeline-skill/scripts/export_story_handoff.py sessions/<run>/session.json
```

## English Summary

Storyboard Director is a Codex skill for turning a story idea into a path-based storyboard workflow. It plans the script, runs text-only logic checks, generates per-shot line art through parallel agents, presents the work in one local HTML review board, and writes ordered video prompts.

Optional deliverables include per-shot styled final frames and three-column storyboard sheets built from either line art or final frames. Generated images stay on disk; JSON, HTML, and chat carry only compact state and local paths.

## 更多说明

实现细节、校验规则、打包方式和故障排查见：

`docs/developer-reference.md`

## License

MIT. See `LICENSE`.
