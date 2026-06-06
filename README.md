# WeChat Article Pipeline Skill

## 中文

这是一个用于生成完整微信公众号文章包的 Codex Skill。它可以从一个选题或方向开始，完成文章正文、配图计划、图片生成、HTML 工作台打包，并在明确要求时通过微信官方 API 直接创建公众号草稿箱草稿。

可安装的 skill 位于：

```text
wechat-article-pipeline/
```

## 一、功能特性

- 面向微信公众号/公众号风格的长文创作流程
- 支持方法类、分析类、情绪/故事类视觉模式
- 情绪/故事类内容使用插画逻辑，而不是步骤图或流程图
- 可根据正文自动规划题图、正文配图和尾图
- 输出带内嵌图片的单文件可编辑 HTML
- 可通过微信官方 API 上传正文图片、上传封面素材、创建草稿箱草稿并验证草稿
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
4. 将文章和图片打包成一个可编辑的单文件 HTML 工作台
5. 如果你要求导入公众号草稿箱，再使用微信官方 API 创建草稿

### 文稿来源

文稿可以来自两种方式：

1. 你先用其他大模型或自己写好初稿，再交给 Codex 使用该 skill 排版、配图和打包。
2. 你只给 Codex 一个选题、观点或文章方向，由 Codex 使用该 skill 直接完成初稿。

如果已有初稿，可以直接粘贴正文，并说明目标风格、读者、是否需要压缩篇幅。若没有初稿，可以只描述主题，例如“写一篇面向普通读者的公众号文章，解释某个新趋势/方法/产品”。

### 配图方式

配图也可以来自两种方式：

1. 使用其他图片模型先生成图片，再把图片文件交给 Codex 打包进 HTML。
2. 由 Codex 根据文章内容自动规划题图、正文配图和尾图，并调用内置图片生成能力完成配图。

默认情况下，该 skill 会先写完文章，再根据正文内容生成图片计划，避免先出图再硬套文章。

### 审稿和发布

审稿有两种方式：

1. 输出单文件 HTML 工作台，你在浏览器里打开检查标题、正文、配图和排版，再手工复制到微信公众号后台。
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

正文题图下方的“某某的第 N 篇原创”使用独立字段：默认账号为 `WECHAT_SIGNATURE_AUTHOR` / `WECHAT_ORIGINAL_ISSUE`，命名账号为 `WECHAT_ACCOUNT_<ALIAS>_SIGNATURE_AUTHOR` / `WECHAT_ACCOUNT_<ALIAS>_ORIGINAL_ISSUE`。它和草稿箱 API 使用的 `WECHAT_AUTHOR` 不是同一个字段。

导出草稿箱的正文 HTML 使用 paragraph-only 结构：标题、署名条、图片、引用、列表和黑色代码块都落成连续 `<p>`，不再用 `section` / `div` / `blockquote` / `pre` / `ul` / `ol` 包裹，避免微信编辑器在这些块前后生成多余空行。黑色代码块只保留代码块内部留白。

导入草稿时，Codex 会完成：

1. 从 `.env` 读取所选公众号的 AppID/AppSecret
2. 获取或复用该公众号专属的 stable access token 缓存
3. 查询公众号草稿箱开关
4. 上传正文内嵌图片到微信正文图片接口
5. 上传封面图到永久素材接口
6. 调用草稿箱接口创建草稿
7. 可选调用 `draft/get` 验证草稿标题和条目数

发送预览需要额外明确要求，并传入 `--send-preview` 及预览账号参数。正式发布/群发不属于默认自动化范围。

## 五、仓库结构

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

## 六、说明

- Codex 内置图片工具通常会把生成图片保存到 `$CODEX_HOME/generated_images`；打包前请将选中的图片复制到项目的图片目录。
- 打包脚本会校验生成的 HTML 是否包含内嵌图片，并确认没有未解析的 `{{visual:*}}` 占位符。
- `.env`、token cache、生成的文章包和图片都不应提交到 GitHub。

## 七、版本说明

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
- Method, analysis, and emotional/story visual modes
- Emotional/story content uses illustration logic instead of step diagrams
- Automatic cover/body/closing image planning based on the finished article
- Single-file editable HTML output with embedded images
- Official API workflow for body image upload, cover material upload, draft creation, and draft verification
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
4. Package everything into a single editable HTML workbench
5. If you ask to import it into WeChat, create a draft through the official WeChat API

### Article Source

The article can start in either of two ways:

1. Write or draft it elsewhere first, then ask Codex to use this skill for editing, image planning, and packaging.
2. Give Codex only a topic, point of view, or direction, and let Codex draft the article with this skill.

If you already have a draft, paste the text and describe the target style, audience, and whether it should be shortened. If you do not have a draft, describe the topic directly.

### Images

Images can also come from either of two ways:

1. Generate images with another image model first, then give the files to Codex for packaging.
2. Let Codex plan and generate the cover image, in-body images, and closing image from the article content.

By default, the skill writes the article first and plans images from the finished content, so the visuals match the article rather than forcing the article around pre-made images.

### Review And Publishing

There are two review paths:

1. Output a single editable HTML workbench, open it in a browser, review the title/body/images/layout, then copy it manually into the WeChat editor.
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

The visible "author's Nth original article" label below the cover image uses separate fields: `WECHAT_SIGNATURE_AUTHOR` / `WECHAT_ORIGINAL_ISSUE` for the default account, or `WECHAT_ACCOUNT_<ALIAS>_SIGNATURE_AUTHOR` / `WECHAT_ACCOUNT_<ALIAS>_ORIGINAL_ISSUE` for named accounts. It is separate from `WECHAT_AUTHOR`, which is only for the draft API author field.

Draft-box HTML uses a paragraph-only structure: headings, the signature badge, images, quotes, lists, and black code blocks are emitted as consecutive `<p>` blocks instead of `section` / `div` / `blockquote` / `pre` / `ul` / `ol`, avoiding extra blank editable lines in the WeChat editor. Black code blocks keep only internal padding.

When importing a draft, Codex will:

1. Read the selected account credentials from `.env`
2. Fetch or reuse an account-specific stable access token
3. Check the draft-box switch
4. Upload embedded body images to the WeChat body-image API
5. Upload the cover image as permanent material
6. Create the draft through the draft-box API
7. Optionally verify the created draft with `draft/get`

Preview sending requires a separate explicit request plus `--send-preview` and preview-account parameters. Final publishing and mass sending are out of scope by default.

## 5. Repository Layout

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

## 6. Notes

- Codex's built-in image tool normally saves generated files under `$CODEX_HOME/generated_images`; copy accepted images into the project image directory before packaging.
- The packager validates that generated HTML contains embedded images and no unresolved `{{visual:*}}` placeholders.
- `.env`, token cache files, generated article packages, and generated images should not be committed to GitHub.

## 7. Release Notes

- `V 1.1.0`: Added support for connecting multiple WeChat Official Accounts.
- `V 1.0.0`: Added official WeChat API import for creating Official Account drafts directly.
- `V 0.5.0`: Supported packaging article text and images into editable HTML for manual copy-paste into WeChat.
