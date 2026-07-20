# WeChat Article Pipeline Skill

## 中文

这是一个用于生成完整微信公众号文章包的 Codex Skill。它可以从一个选题或方向开始，完成文章正文、配图计划、图片生成、HTML 工作台打包，并在明确要求时通过微信官方 API 直接创建公众号草稿箱草稿。

可安装的 skill 位于：

```text
wechat-article-pipeline/
```

## 一、功能特性

- 面向微信公众号/公众号风格的长文创作流程
- 支持“秘书模式”：忠实整理用户已经口述出的文章主线，保留原有观点、顺序、例子、语气和节奏，不擅自改写成新的 AI 大纲
- 支持方法类、分析类、情绪/故事类视觉模式
- 情绪/故事类内容使用插画逻辑，而不是步骤图或流程图
- 可根据正文自动规划题图、正文配图和尾图
- 输出可持续编辑的本地 HTML 工作台，可将修改写回 Markdown、HTML 和发布数据；图片保留在独立目录，复制富文本时临时内嵌图片
- 支持无配图排版、只补缺失图片、单张图片重做，以及只修改标题、正文或配图等增量处理路径
- 可通过微信官方 API 上传正文图片、上传封面素材、创建并验证草稿；中断后可保留进度继续处理，并可在成功创建新草稿后安全递增原创篇号
- 只有明确要求时才发送预览；不会自动发布或群发

## 二、安装

推荐在 Codex App 或 Codex CLI 中直接粘贴下面这段话，让 Codex 帮你安装：

```text
请从 GitHub 安装这个 Codex skill：https://github.com/jhwreal/wechat-article-pipeline-skill ，安装其中的 wechat-article-pipeline skill 到本机 Codex skills 目录。
```

也可以手工将 skill 目录复制到 Codex 的 skills 目录：

```bash
mkdir -p ~/.codex/skills
rsync -a wechat-article-pipeline/ ~/.codex/skills/wechat-article-pipeline/
```

安装后重启或刷新 Codex。

## 三、使用方法

在 Codex 中说明你要写的公众号文章主题、方向或已有初稿即可。默认流程会生成一套可本地审核和编辑的文章包：

1. 先写文章正文
2. 根据写好的文章内容生成按角色划分的图片计划
3. 直接调用 Codex 内置图片生成工具生成题图、正文配图和尾图
4. 将文章打包成可编辑 HTML 工作台，并用相对路径引用独立图片目录；复制富文本时再临时把图片写入剪贴板 HTML
5. 如果你要求导入公众号草稿箱，再使用微信官方 API 创建草稿

### 文稿来源

文稿可以来自两种方式：

1. 你先用其他大模型或自己写好初稿，再交给 Codex 使用该 skill 排版、配图和打包。
2. 你只给 Codex 一个选题、观点或文章方向，由 Codex 使用该 skill 直接完成初稿。

如果已有初稿，可以直接粘贴正文，并说明目标风格、读者、是否需要压缩篇幅。若没有初稿，可以只描述主题，例如“写一篇面向普通读者的公众号文章，解释某个新趋势/方法/产品”。

### 秘书模式

当你已经通过口述或长段文字给出了文章的核心判断、叙述顺序、例子和表达节奏，可以明确说“打开秘书模式”。该模式只整理你已经说出的文章主线，保留开头、结论、例子顺序、重复锚点、情绪力度和说话习惯，主要修正断句、段落、明显口误、重复口头语和局部衔接。

秘书模式不会自行扩大主题、补写一套更完整的观点、增加平衡框架，或把文章改造成更像报告的 AI 大纲。原素材存在关键缺口时，Codex 会指出缺口或询问，而不是替你发明新的主张。

### 配图方式

配图也可以来自两种方式：

1. 使用其他图片模型先生成图片，再把图片文件交给 Codex 打包进 HTML。
2. 由 Codex 根据文章内容自动规划题图、正文配图和尾图，并调用内置图片生成能力完成配图。

默认情况下，该 skill 会先写完文章，再根据正文内容生成图片计划，避免先出图再硬套文章。

### 增量处理和快速路径

不必每次都重新生成完整文章包。该 skill 会根据你的要求只处理发生变化的部分：

1. 如果要求“不配图”“只排版”，只生成正文和工作台，不规划正文图片。
2. 如果已有文章只缺少部分图片，只生成缺失的图片，不重做已经完成的素材。
3. 如果只对某一张图片不满意，只重新生成并替换对应位置的图片。
4. 如果只要求修改标题、正文、排版或配图，只更新对应资产，不重跑无关阶段。
5. 如果正文不需要配图但仍要导入公众号草稿箱，可以只准备微信接口必需的封面图，封面不会被插入正文。

### 审稿和发布

审稿有两种方式：

1. 输出 HTML 工作台。通过 Codex 启动的本地工作台地址打开后，可以继续修改 Markdown，并将最新内容写回 HTML、源 Markdown、任务数据和已配置的发布清单；输入内容会先保存到浏览器缓存，停止编辑后自动写入，也可以点击“保存”立即写入。直接打开独立 HTML 时为预览/复制只读模式，工作台会明确提示改用本地服务地址。图片文件保留在项目的 `image/<slug>/` 目录，复制富文本时工作台会临时把本地图片转成剪贴板 HTML 里的图片数据。
2. 在已绑定公众号凭据的情况下，让 Codex 调用微信官方 API 直接创建公众号草稿，然后到公众号草稿箱里检查。

该 skill 只负责创建草稿和可选发送预览，不会自动群发或发布。

## 四、直接导入公众号草稿箱

只有当用户明确要求“导入公众号草稿箱”“创建微信草稿”“推送到草稿箱”等操作时，才执行这一阶段。该阶段只使用微信官方 API，不使用 `mp.weixin.qq.com` 私有后台接口，也不会调用发布/群发 API。

### 绑定公众号

先进入微信开发者平台：

```text
https://developers.weixin.qq.com/platform
```

在平台里找到公众号相关设置，完成三件事：

1. 获取公众号的 `AppID`
2. 生成或查看 `AppSecret`
3. 将本机公网 IP 加入接口调用白名单

本机公网 IP 可以通过常见的“查询本机 IP”网站查看。白名单里要填写的是公网出口 IP，不一定是局域网里的 `192.168.x.x` 或 `10.x.x.x` 地址。如果网络环境变化，例如切换公司、家里、热点或 VPN，公网 IP 可能也会变化，需要重新加入白名单。

拿到 `AppID` 和 `AppSecret` 后，把这两个值告诉 Codex，并说明公众号名称。Codex 会在本机生成本地配置文件；这个文件只保存在本机，不应提交到 GitHub，也不要贴到公开聊天或文档里。

如果只绑定一个公众号，后续导入草稿时通常不需要再指定公众号名称。如果绑定了多个公众号，导入草稿前需要告诉 Codex 要导入到哪一个公众号。

正文题图下方的“某某的第 N 篇原创”使用独立字段：默认账号为 `WECHAT_SIGNATURE_AUTHOR` / `WECHAT_ORIGINAL_ISSUE`，命名账号为 `WECHAT_ACCOUNT_<ALIAS>_SIGNATURE_AUTHOR` / `WECHAT_ACCOUNT_<ALIAS>_ORIGINAL_ISSUE`。它和草稿箱 API 使用的 `WECHAT_AUTHOR` 不是同一个字段。正常创建一篇全新草稿时，可以在草稿创建成功后安全递增原创篇号；重新创建或修复旧稿时可以不递增，避免错误占用新篇号。

命名账号的 `<ALIAS>` 建议只使用大写英文、数字和下划线，并避免以 `_SIGNATURE`、`_ORIGINAL`、`_PREVIEW` 结尾；这些后缀和 `AUTHOR`、`ISSUE`、`ACCOUNT` 等字段组合后会形成保留字段名。公众号展示名请放在 `WECHAT_ACCOUNT_<ALIAS>_NAME`。

导出草稿箱的正文 HTML 使用 paragraph-only 结构：标题、署名条、图片、引用、列表和黑色代码块都落成连续 `<p>`，不再用 `section` / `div` / `blockquote` / `pre` / `ul` / `ol` 包裹，避免微信编辑器在这些块前后生成多余空行。黑色代码块只保留代码块内部留白。

导入草稿时，Codex 会完成：

1. 从 `.env` 读取所选公众号的 AppID/AppSecret
2. 获取或复用该公众号专属的 stable access token 缓存
3. 查询公众号草稿箱开关
4. 上传正文内嵌图片到微信正文图片接口
5. 上传封面图到永久素材接口
6. 调用草稿箱接口创建草稿
7. 可选调用 `draft/get` 验证草稿标题和条目数

草稿导入会把关键步骤和远端返回结果写入本地结果文件。如果草稿已经创建，但后续验证、预览或原创篇号更新失败，可以从已保存的结果继续完成剩余步骤，避免重新上传素材或重复创建草稿。对于无法确认微信端是否已经成功执行的中断，流程会停止并明确提示，而不会贸然再创建一份草稿。

发送预览需要额外明确要求，并传入 `--send-preview` 及预览账号参数。正式发布/群发不属于默认自动化范围。

## 五、仓库结构

```text
.
├── README.md
├── LICENSE
├── examples/
│   ├── assets/
│   ├── method-article.md
│   ├── emotion-article.md
│   ├── method-article.html
│   ├── emotion-article.html
│   ├── method-article.clipboard-assets.js
│   └── emotion-article.clipboard-assets.js
└── wechat-article-pipeline/
    ├── .env.example
    ├── SKILL.md
    ├── agents/openai.yaml
    ├── assets/templates/
    ├── references/
    └── scripts/
```

## 六、说明

- Codex 内置图片工具通常会把生成图片保存到 `$CODEX_HOME/generated_images`；打包前请将选中的图片复制到项目的图片目录。
- 打包脚本会校验生成的 HTML 没有未解析的 `{{visual:*}}` 占位符，并确认工作台里的图片引用已经落成相对路径；工作台复制按钮会在复制时临时内嵌图片，不会污染左侧 Markdown。
- 非 macOS 环境运行图片打包/发布流程前请安装 Pillow；macOS 对部分封面裁剪预览可使用系统 `sips`，但 Pillow 仍建议用于发布前正文图片压缩。
- CI 会运行 Python/Node 测试、Skill 结构校验、完整“图片规划 + 工作台打包 + 发布清单 + API dry-run”冒烟测试，并在测试通过后验证安装包。
- `.env`、token cache、生成的文章包和图片都不应提交到 GitHub。

## 七、版本说明

- `V 1.5.0（当前版本）`：新增今日头条 Chrome 草稿与发布流程；强化工作台事务恢复和路径边界，发布清单改为显式生成，收紧图片任务/草稿校验，并补齐完整 CI 冒烟测试与安装元数据。
- `V 1.1.0`：增加接入多个公众号的能力。
- `V 1.0.0`：支持调用微信官方 API，直接导入微信公众号草稿箱。
- `V 0.5.0`：支持将文稿和配图打包成可编辑 HTML，需手工复制到微信公众号后台。

---

## English

This Codex skill produces complete WeChat official account article packages. Starting from a topic or direction, it can write the article, plan visuals, generate images, package an editable HTML workbench, and, when explicitly requested, create a WeChat Official Account draft through official WeChat APIs.

The installable skill lives in:

```text
wechat-article-pipeline/
```

## 1. Features

- WeChat/official-account style long-form article workflow
- Secretary Mode for faithfully organizing an already-spoken article mainline while preserving the user's judgments, order, examples, voice, and cadence instead of replacing them with a new AI outline
- Method, analysis, and emotional/story visual modes
- Emotional/story content uses illustration logic instead of step diagrams
- Automatic cover/body/closing image planning based on the finished article
- Persistent local HTML workbench editing that can write changes back to Markdown, HTML, and publishing data, while keeping images separate and inlining them only when copying rich HTML
- Incremental paths for no-image formatting, missing-image repair, single-image regeneration, and title/body/layout/image-only changes
- Official API workflow for image upload, draft creation, and verification, with recoverable interrupted runs and safe original-issue increment after a new draft succeeds
- Preview is sent only when explicitly requested; publishing and mass sending are never automatic

## 2. Install

In Codex App or Codex CLI, paste this prompt and let Codex install the skill:

```text
Please install this Codex skill from GitHub: https://github.com/jhwreal/wechat-article-pipeline-skill . Install the wechat-article-pipeline skill into my local Codex skills directory.
```

You can also copy the skill directory manually:

```bash
mkdir -p ~/.codex/skills
rsync -a wechat-article-pipeline/ ~/.codex/skills/wechat-article-pipeline/
```

Restart or refresh Codex after installing.

## 3. Usage

In Codex, describe the WeChat Official Account article topic, direction, or draft you already have. By default, the skill produces a local package for review and editing:

1. Write the article first
2. Derive a role-based visual plan from the finished article
3. Generate cover/body/closing images directly with Codex's built-in image generation tool
4. Package the article into an editable HTML workbench that references the separate image folder, then temporarily inlines images only when copying rich HTML
5. If you ask to import it into WeChat, create a draft through the official WeChat API

### Article Source

The article can start in either of two ways:

1. Write or draft it elsewhere first, then ask Codex to use this skill for editing, image planning, and packaging.
2. Give Codex only a topic, point of view, or direction, and let Codex draft the article with this skill.

If you already have a draft, paste the text and describe the target style, audience, and whether it should be shortened. If you do not have a draft, describe the topic directly.

### Secretary Mode

If you have already supplied the article's main judgment, narrative order, examples, and speaking rhythm through dictation or a long rough passage, explicitly say `打开秘书模式` (Open Secretary Mode). The mode organizes what you already said while preserving the opening, conclusion, example order, repeated anchors, emotional pressure, and speaking cadence. It mainly fixes sentence breaks, paragraphs, obvious slips, duplicated filler, and local transitions.

Secretary Mode does not broaden the thesis, invent a more complete argument, add a balancing framework, or replace your structure with a report-like AI outline. If the source has a material gap, Codex identifies or asks about it instead of inventing a new claim.

### Images

Images can also come from either of two ways:

1. Generate images with another image model first, then give the files to Codex for packaging.
2. Let Codex plan and generate the cover image, in-body images, and closing image from the article content.

By default, the skill writes the article first and plans images from the finished content, so the visuals match the article rather than forcing the article around pre-made images.

### Incremental And Fast Paths

You do not need to rebuild the complete article package for every change. The skill can limit work to the affected layer:

1. For “no images” or “format only,” produce the article and workbench without planning body images.
2. If an existing article is missing only some images, generate only those missing assets.
3. If one image is unsatisfactory, regenerate and replace only that slot.
4. For a title-, body-, layout-, or image-only request, update the corresponding assets without rerunning unrelated stages.
5. For draft delivery without body images, provide only the cover required by the WeChat API and keep it out of the article body.

### Review And Publishing

There are two review paths:

1. Output an editable HTML workbench. When opened through the local workbench URL started by Codex, Markdown edits can be written back to the HTML, source Markdown, job data, and any configured publishing manifest. Input is cached immediately, saved to project files after editing pauses, and can also be persisted with Save. Opening the standalone HTML directly is preview/copy-only; it locks editing and points back to the loopback service URL. Image files stay in `image/<slug>/`; the copy button temporarily embeds them in clipboard HTML.
2. After binding Official Account credentials, ask Codex to create a WeChat draft through the official API, then review it in the WeChat draft box.

The skill creates drafts and can optionally send previews. It does not automatically publish or mass-send.

## 4. Direct WeChat Draft Import

Run this stage only when the user explicitly asks to import/create/push a WeChat Official Account draft. This workflow uses only official WeChat APIs. It does not use private `mp.weixin.qq.com` backend APIs and never calls publish or mass-send APIs.

### Bind An Official Account

Open the WeChat developer platform:

```text
https://developers.weixin.qq.com/platform
```

Find the Official Account settings and complete three steps:

1. Get the Official Account `AppID`
2. Generate or view the `AppSecret`
3. Add this computer's public IP address to the API whitelist

You can find the public IP with any common "what is my IP" website. The whitelist needs the public outbound IP, not necessarily a local `192.168.x.x` or `10.x.x.x` address. If you switch networks, such as office, home, mobile hotspot, or VPN, the public IP may change and must be added again.

After you have the `AppID` and `AppSecret`, give them to Codex and include the Official Account name. Codex will create a local config file on this machine. Keep that file local; do not commit it to GitHub or paste it into public chats or documents.

If only one Official Account is bound, future draft imports usually do not need an account name. If multiple accounts are bound, tell Codex which Official Account to use before importing a draft.

The visible "author's Nth original article" label below the cover image uses separate fields: `WECHAT_SIGNATURE_AUTHOR` / `WECHAT_ORIGINAL_ISSUE` for the default account, or `WECHAT_ACCOUNT_<ALIAS>_SIGNATURE_AUTHOR` / `WECHAT_ACCOUNT_<ALIAS>_ORIGINAL_ISSUE` for named accounts. It is separate from `WECHAT_AUTHOR`, which is only for the draft API author field. For a normal new article, the issue number can be advanced safely after draft creation succeeds; recreating or repairing an older draft can leave the counter unchanged so it does not consume a new issue number.

For named accounts, keep `<ALIAS>` to uppercase ASCII letters, numbers, and underscores, and avoid aliases ending in `_SIGNATURE`, `_ORIGINAL`, or `_PREVIEW`; those suffixes combine with field names such as `AUTHOR`, `ISSUE`, and `ACCOUNT` into reserved keys. Store the public display name in `WECHAT_ACCOUNT_<ALIAS>_NAME`.

Draft-box HTML uses a paragraph-only structure: headings, the signature badge, images, quotes, lists, and black code blocks are emitted as consecutive `<p>` blocks instead of `section` / `div` / `blockquote` / `pre` / `ul` / `ol`, avoiding extra blank editable lines in the WeChat editor. Black code blocks keep only internal padding.

When importing a draft, Codex will:

1. Read the selected account credentials from `.env`
2. Fetch or reuse an account-specific stable access token
3. Check the draft-box switch
4. Upload embedded body images to the WeChat body-image API
5. Upload the cover image as permanent material
6. Create the draft through the draft-box API
7. Optionally verify the created draft with `draft/get`

Draft delivery records important steps and remote results in a local result file. If the draft was created but a later verification, preview, or issue-number update fails, the remaining work can continue from the saved result instead of uploading assets again or creating another draft. If an interruption leaves the remote outcome unknowable, the workflow stops and reports the uncertainty rather than risking a duplicate draft.

Preview sending requires a separate explicit request plus `--send-preview` and preview-account parameters. Final publishing and mass sending are out of scope by default.

## 5. Repository Layout

```text
.
├── README.md
├── LICENSE
├── examples/
│   ├── assets/
│   ├── method-article.md
│   ├── emotion-article.md
│   ├── method-article.html
│   ├── emotion-article.html
│   ├── method-article.clipboard-assets.js
│   └── emotion-article.clipboard-assets.js
└── wechat-article-pipeline/
    ├── .env.example
    ├── SKILL.md
    ├── agents/openai.yaml
    ├── assets/templates/
    ├── references/
    └── scripts/
```

## 6. Notes

- Codex's built-in image tool normally saves generated files under `$CODEX_HOME/generated_images`; copy accepted images into the project image directory before packaging.
- The packager validates that generated HTML has no unresolved `{{visual:*}}` placeholders and that workbench image references have been resolved to relative paths. The workbench copy button inlines images only in clipboard HTML, not in the editable Markdown.
- Install Pillow before running image packaging/publishing workflows on non-macOS systems. macOS can use the built-in `sips` fallback for some cover-crop previews, but Pillow is still recommended for pre-upload body-image compression.
- CI runs Python and Node tests, validates the installable skill, executes the full image-plan + package + manifest + API dry-run smoke path, and then verifies the distributable archive.
- `.env`, token cache files, generated article packages, and generated images should not be committed to GitHub.

## 7. Release Notes

- `V 1.5.0 (current version)`: Added the Chrome-based Toutiao draft and publishing workflow; hardened workbench recovery and path boundaries, made publish manifests opt-in, tightened image-job/draft validation, and added full CI smoke coverage plus install metadata.
- `V 1.1.0`: Added support for connecting multiple WeChat Official Accounts.
- `V 1.0.0`: Added official WeChat API import for creating Official Account drafts directly.
- `V 0.5.0`: Supported packaging article text and images into editable HTML for manual copy-paste into WeChat.
