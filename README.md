# WeChat Article Pipeline Skill

## 中文

这是一个用于生成完整微信公众号文章包的 Codex Skill。它可以从一个选题或方向开始，完成文章正文、配图计划、图片生成、HTML 工作台打包，并在明确要求时通过微信官方 API 直接创建公众号草稿箱草稿。

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
- 输出与 HTML 同名的 `<html文件名>.publish-manifest.json`
- 可通过微信官方 API 上传正文图片、上传封面素材、创建草稿箱草稿并验证草稿
- 只有明确要求时才发送预览；不会自动发布或群发
- 不在 skill 内部嵌套调用 `codex exec`

## 安装

将 skill 目录复制到 Codex 的 skills 目录：

```bash
mkdir -p ~/.codex/skills
rsync -a wechat-article-pipeline/ ~/.codex/skills/wechat-article-pipeline/
```

安装后重启或刷新 Codex。

## 基本流程

在 Codex 中给出一个选题或文章方向即可使用该 skill。默认流程会生成一套可本地审核和编辑的文章包：

1. 先写文章正文
2. 根据写好的文章内容生成按角色划分的图片计划
3. 直接调用 Codex 内置图片生成工具生成题图、正文配图和尾图
4. 将文章和图片打包成一个可编辑的单文件 HTML 工作台
5. 生成同名发布清单，用于后续导入公众号草稿箱

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

打包脚本会默认在 `output.html` 同目录生成 `output.publish-manifest.json`，即 manifest 和 HTML 同名，不再复用固定的 `publish-manifest.json`。

## 直接导入公众号草稿箱

只有当用户明确要求“导入公众号草稿箱”“创建微信草稿”“推送到草稿箱”等操作时，才执行这一阶段。该阶段只使用微信官方 API，不使用 `mp.weixin.qq.com` 私有后台接口，也不会调用发布/群发 API。

先从 `.env.example` 复制出本地 `.env`。真实 `.env` 已被 Git 忽略，上传 GitHub 时不能包含：

```dotenv
WECHAT_APPID=
WECHAT_APPSECRET=
WECHAT_AUTHOR=
WECHAT_PREVIEW_ACCOUNT=
```

如果 `.env` 不存在或缺少 `WECHAT_APPID` / `WECHAT_APPSECRET`，使用 skill 时应先询问用户，然后在本地生成 `.env`，并设置较严格的本地权限。

创建草稿：

```bash
python3 wechat-article-pipeline/scripts/publish_wechat_api.py \
  output.publish-manifest.json \
  --env-file .env \
  --remember \
  --check-draft-switch \
  --verify-draft
```

脚本会完成：

1. 从 `.env` 读取 AppID/AppSecret
2. 获取或复用 stable access token
3. 查询公众号草稿箱开关
4. 上传正文内嵌图片到微信正文图片接口
5. 上传封面图到永久素材接口
6. 调用草稿箱接口创建草稿
7. 可选调用 `draft/get` 验证草稿标题和条目数

发送预览需要额外明确要求，并传入 `--send-preview` 及预览账号参数。正式发布/群发不属于默认自动化范围。

## 仓库结构

```text
.
├── README.md
├── LICENSE
├── examples/
│   ├── method-article.md
│   ├── emotion-article.md
│   ├── method-article.html
│   └── emotion-article.html
└── wechat-article-pipeline/
    ├── SKILL.md
    ├── assets/templates/
    ├── references/
    └── scripts/
```

## 说明

- Codex 内置图片工具通常会把生成图片保存到 `$CODEX_HOME/generated_images`；打包前请将选中的图片复制到项目的图片目录。
- 打包脚本会校验生成的 HTML 是否包含内嵌图片，并确认没有未解析的 `{{visual:*}}` 占位符。
- `.env`、token cache、生成的文章包和图片都不应提交到 GitHub。

---

## English

This Codex skill produces complete WeChat official account article packages. Starting from a topic or direction, it can write the article, plan visuals, generate images, package an editable HTML workbench, and, when explicitly requested, create a WeChat Official Account draft through official WeChat APIs.

The installable skill lives in:

```text
wechat-article-pipeline/
```

## Features

- WeChat/official-account style long-form article workflow
- Method, analysis, and emotional/story visual modes
- Emotional/story content uses illustration logic instead of step diagrams
- Deterministic scripts for image-job planning and HTML packaging
- Single-file editable HTML output with embedded images
- HTML-matched `<html-stem>.publish-manifest.json`
- Official API workflow for body image upload, cover material upload, draft creation, and draft verification
- Preview is sent only when explicitly requested; publishing and mass sending are never automatic
- No nested `codex exec` runtime

## Install

Copy the skill directory into your Codex skills directory:

```bash
mkdir -p ~/.codex/skills
rsync -a wechat-article-pipeline/ ~/.codex/skills/wechat-article-pipeline/
```

Restart or refresh Codex after installing.

## Basic Workflow

Use the skill from Codex with a topic or article direction. By default, it produces a local article package for review and editing:

1. Write the article first
2. Derive a role-based visual plan from the finished article
3. Generate cover/body/closing images directly with Codex's built-in image generation tool
4. Package everything into a single editable HTML workbench
5. Generate a matching publish manifest for optional WeChat draft-box import

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

The packager writes `output.publish-manifest.json` next to `output.html`, so every HTML output gets its own manifest instead of reusing a fixed `publish-manifest.json`.

## Direct WeChat Draft Import

Run this stage only when the user explicitly asks to import/create/push a WeChat Official Account draft. This workflow uses only official WeChat APIs. It does not use private `mp.weixin.qq.com` backend APIs and never calls publish or mass-send APIs.

Create a local `.env` from `.env.example` first. The real `.env` is ignored by Git and must not be uploaded to GitHub:

```dotenv
WECHAT_APPID=
WECHAT_APPSECRET=
WECHAT_AUTHOR=
WECHAT_PREVIEW_ACCOUNT=
```

If `.env` is missing or lacks `WECHAT_APPID` / `WECHAT_APPSECRET`, ask the user for those values, then create the local `.env` with restrictive permissions.

Create a draft:

```bash
python3 wechat-article-pipeline/scripts/publish_wechat_api.py \
  output.publish-manifest.json \
  --env-file .env \
  --remember \
  --check-draft-switch \
  --verify-draft
```

The script will:

1. Read AppID/AppSecret from `.env`
2. Fetch or reuse a stable access token
3. Check the draft-box switch
4. Upload embedded body images to the WeChat body-image API
5. Upload the cover image as permanent material
6. Create the draft through the draft-box API
7. Optionally verify the created draft with `draft/get`

Preview sending requires a separate explicit request plus `--send-preview` and preview-account parameters. Final publishing and mass sending are out of scope by default.

## Repository Layout

```text
.
├── README.md
├── LICENSE
├── examples/
│   ├── method-article.md
│   ├── emotion-article.md
│   ├── method-article.html
│   └── emotion-article.html
└── wechat-article-pipeline/
    ├── SKILL.md
    ├── assets/templates/
    ├── references/
    └── scripts/
```

## Notes

- Codex's built-in image tool normally saves generated files under `$CODEX_HOME/generated_images`; copy accepted images into the project image directory before packaging.
- The packager validates that generated HTML contains embedded images and no unresolved `{{visual:*}}` placeholders.
- `.env`, token cache files, generated article packages, and generated images should not be committed to GitHub.
