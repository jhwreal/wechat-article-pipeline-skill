# WeChat Article Pipeline Skill

## English

Codex skill for producing a complete WeChat official account article package:

1. write the article first
2. derive a role-based visual plan from the finished article
3. generate cover/body/closing images directly with Codex's built-in image generation tool
4. package everything into a single editable HTML workbench with images embedded as `data:image` URIs

The installable skill lives in:

```text
wechat-article-pipeline/
```

## Features

- WeChat/公众号 style long-form article workflow
- method, analysis, and emotional/story visual modes
- emotional/story content uses illustration logic instead of step diagrams
- deterministic scripts for image-job planning and HTML packaging
- single-file editable HTML output with embedded images
- no nested `codex exec` runtime

## Install

Copy the skill directory into your Codex skills directory:

```bash
mkdir -p ~/.codex/skills
rsync -a wechat-article-pipeline/ ~/.codex/skills/wechat-article-pipeline/
```

Restart or refresh Codex after installing.

## Basic Workflow

Use the skill from Codex with a topic or article direction. The skill expects Codex itself to call the built-in image generation tool for each planned visual slot.

Manual script flow:

```bash
python3 wechat-article-pipeline/scripts/make_wechat_article_image_jobs.py \
  examples/method-article.md \
  output.image-jobs.json \
  --debug-plan
```

Then generate images directly with Codex's built-in image tool and save them as:

```text
image/<article-slug>/cover.png
image/<article-slug>/body-1.png
image/<article-slug>/body-2.png
image/<article-slug>/closing.png
```

Finally package the editable HTML:

```bash
python3 wechat-article-pipeline/scripts/package_wechat_article_bundle.py \
  examples/method-article.md \
  output.html \
  --plan-json output.image-jobs.json \
  --images-dir image/<article-slug>
```

## Repository Layout

```text
.
├── README.md
├── LICENSE
├── examples/
│   ├── method-article.md
│   ├── emotion-article.md
│   ├── 方法.html
│   └── output 情绪.html
└── wechat-article-pipeline/
    ├── SKILL.md
    ├── agents/openai.yaml
    ├── assets/templates/
    ├── references/
    └── scripts/
```

## Notes

- The skill does not call `codex exec` internally.
- The built-in image tool normally saves generated files under `$CODEX_HOME/generated_images`; copy accepted images into the project image directory before packaging.
- The packager validates that generated HTML contains embedded images and no unresolved `{{visual:*}}` placeholders.

---

## 中文

这是一个用于生成完整微信公众号文章包的 Codex Skill。它会按照下面的顺序工作：

1. 先写文章正文
2. 根据写好的文章内容生成按角色划分的图片计划
3. 直接调用 Codex 内置图片生成工具生成题图、正文配图和尾图
4. 将文章和图片打包成一个可编辑的单文件 HTML 工作台，并把图片以内嵌 `data:image` URI 的形式写入 HTML

可安装的 skill 位于：

```text
wechat-article-pipeline/
```

## 功能特性

- 面向微信公众号/公众号风格的长文创作流程
- 支持方法类、分析类、情绪/故事类视觉模式
- 情绪/故事类内容使用插画逻辑，而不是步骤图或流程图
- 提供确定性的脚本，用于生成图片任务计划和 HTML 打包
- 输出带内嵌图片的单文件可编辑 HTML
- 不在 skill 内部嵌套调用 `codex exec`

## 安装

将 skill 目录复制到 Codex 的 skills 目录：

```bash
mkdir -p ~/.codex/skills
rsync -a wechat-article-pipeline/ ~/.codex/skills/wechat-article-pipeline/
```

安装后重启或刷新 Codex。

## 基本流程

在 Codex 中给出一个选题或文章方向即可使用该 skill。该 skill 会要求 Codex 本身为每个规划好的视觉位置调用内置图片生成工具。

手动脚本流程如下：

```bash
python3 wechat-article-pipeline/scripts/make_wechat_article_image_jobs.py \
  examples/method-article.md \
  output.image-jobs.json \
  --debug-plan
```

然后使用 Codex 内置图片生成工具直接生成图片，并保存为：

```text
image/<article-slug>/cover.png
image/<article-slug>/body-1.png
image/<article-slug>/body-2.png
image/<article-slug>/closing.png
```

最后打包可编辑 HTML：

```bash
python3 wechat-article-pipeline/scripts/package_wechat_article_bundle.py \
  examples/method-article.md \
  output.html \
  --plan-json output.image-jobs.json \
  --images-dir image/<article-slug>
```

## 仓库结构

```text
.
├── README.md
├── LICENSE
├── examples/
│   ├── method-article.md
│   ├── emotion-article.md
│   ├── 方法.html
│   └── output 情绪.html
└── wechat-article-pipeline/
    ├── SKILL.md
    ├── agents/openai.yaml
    ├── assets/templates/
    ├── references/
    └── scripts/
```

## 说明

- 该 skill 不会在内部调用 `codex exec`。
- Codex 内置图片工具通常会把生成图片保存到 `$CODEX_HOME/generated_images`；打包前请将选中的图片复制到项目的图片目录。
- 打包脚本会校验生成的 HTML 是否包含内嵌图片，并确认没有未解析的 `{{visual:*}}` 占位符。
