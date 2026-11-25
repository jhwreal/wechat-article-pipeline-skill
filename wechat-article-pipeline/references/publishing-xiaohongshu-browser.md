# 小红书 Browser Subagent（内置浏览器）长文同步流程

发布前按 [自动检查与隐藏记录](pre-publish-check.md) 处理：用户未明确跳过且当前稿无有效检查时，自动检查并在对话中报告结果；无待决定的内容问题就继续本次授权流程，不询问是否开始检查。草稿、立即/定时发布均适用，同篇同版跨平台复用结果。

## 适用边界与互斥守卫

- **仅当当前 Agent 运行时不具备操作真实前台应用的 Computer Use，但具备内置浏览器 / Browser Subagent（如 Antigravity）时使用本流程。**
- 如果当前运行时具备真实前台应用 Computer Use（如 Codex 的原生 Computer Use 或 `@oai/sky`），**必须返回 [publishing-xiaohongshu.md](publishing-xiaohongshu.md)**，严禁使用本文件，严禁混用 Computer Use 与浏览器自动化。
- 如果运行时既无 Computer Use 也无浏览器能力，降级为本地工作台交付，由用户手工复制粘贴。
- 严格遵守官方能力边界：不调用、复制或固化 `creator.xiaohongshu.com` 的私有接口、Cookie、localStorage、token 或页面内部请求；不绕过登录或 CAPTCHA。

## 权威内容与格式契约

完整继承 [publishing-xiaohongshu.md](publishing-xiaohongshu.md) 的内容与结构标准：

- 以用户确认的最终 Markdown / 本地工作台正文为准，不从小红书自动保存旧草稿反向覆盖本地稿。
- 标题直接读取 Markdown 第一个 H1，可见字符数上限为 64；超过 64 字禁止进入排版或提交。正文不得重复文章标题、公众号原创篇号或微信签名。
- 外部链接数量必须为 0，来源名称保留纯文本。
- 两级标题映射必须完整保留：
  - Markdown `##` → 小红书 `h1`
  - Markdown `###` 及更深标题 → 小红书 `h2`
- 小红书长文编辑器通常会剥离粘贴文本中的 `strong`/`b` 加粗标记，不把加粗保留作为硬门槛。

## 内置浏览器端到端执行顺序

先识别实际后端，结果文件记录 `browser_backend`。Antigravity App 单标签后端记录 `built-in`；先只读检查目标账号、登录态和空编辑器，再在子代理自己的同一标签打开工作台。复制成功后在同一标签重新导航到平台入口，再次确认账号和空编辑器。支持标签切换的 Chrome 后端记录 `chrome-devtools`，可以保留编辑器标签，另开工作台标签复制后切回。复制后填写标题时使用直接输入，保持富文本剪贴板内容。浏览器权限受限时遵循当前后端的接管流程；若无法执行富文本粘贴或读回规定证据，交付工作台和已知状态供人工核验。

执行前确认本地工作台服务可达（`http://127.0.0.1:<port>/files/<slug>.html`），并记录 Markdown 第一个 H1、预期图片数、预期 `h1` 数（Markdown `##` 数量）、预期 `h2` 数（Markdown `###+` 数量）以及首段、两个正文哨兵句和末段。

1. **检查登录态与干净长文编辑器**：
   - 在内置浏览器中打开 `https://creator.xiaohongshu.com/publish/publish?from=homepage&target=article`。
   - 若跳转至登录页（如 `creator.xiaohongshu.com/login`）或出现验证码，立即暂停并请用户在内置浏览器窗格完成登录；用户确认后在同一 browser subagent 会话中继续。
   - 点击“新的创作”进入干净的长文编辑器（初始字数为 0）。若编辑区已有来源不明的旧草稿，立即停止，不得覆盖。
2. **工作台一次复制（唯一正文入口）**：
   - 按上述后端规则打开本地工作台 URL，将顶部平台选择下拉框切换为 `小红书格式`（`xiaohongshu`）。
   - 核对复制前检查（标题长度 ≤ 64、一级/二级标题数、图片数、可一键复制），点击一次主复制按钮 `复制为小红书格式`。
   - 状态栏须显示“已复制小红书格式”。预期 0 张时核对“无正文图片”；有图时核对实际 N 张图片及 `embedded-data`。
3. **小红书长文编辑器一次粘贴**：
   - 按后端路径返回并确认干净的小红书长文编辑器，填入标题（≤ 64 字）。
   - 点击聚焦 `.ProseMirror` 正文区，执行一次真实粘贴快捷键（macOS 使用 `Meta+v` / Cmd+V，其他系统使用 `Control+v`）。
   - 等待最多 15 秒，观察正文与图片上传结果，期间只做只读观测，禁止再次粘贴。
4. **只读 DOM 审计（不得伪造通过）**：
   - 核验首段、哨兵句与末段完整无截断。
   - 核验标题 DOM：`h1` 数量等于预期 `##` 数量、`h2` 数量等于预期 `###+` 数量，且文字与顺序完全一致；若标题被降级为 `<p>`，判定一次粘贴验收失败并停止。
   - 核验外链数量为 0、无图片占位文字残留、引用/列表语义保留。
   - 按 [图片和发布核验](publishing-xiaohongshu.md#handoff-checks) 运行 `images`；依据正文顺序、完整托管 URL 和相邻段落确认图片位置。无法读到图片地址或标题层级时，保留草稿并标注待人工核验。
5. **缺图处理**。平台可能在跨站粘贴时剥离图片。若部分缺图或 `verified_images == 0` 且预期有图，记录真实的已验证数、预期数和缺失位置。**不得点击 `一键排版`、暂存确认或发布**。用户明确授权补图后，可用浏览器获准的原生文件选择器在缺失位置上传原图，记录实际 `image_repairs`，再完整核验并区分一次粘贴与补传结果。
6. **草稿**。标题、正文、层级、链接、图片及重复稿检查全部通过，等待上传和自动保存完成，再点击一次“一键排版”，核验排版后暂存。从草稿列表按精确标题重新打开，回读标题层级、首中末段和图片位置并重跑图片检查；重开与读回成功才记录 `draft_reopened=true` 和 `draft_verified=true`；预期和实测计数以重开后的核验为准。
7. **公开提交**。只在用户已授权的账号、可见范围及立即或定时模式下，执行 [提交核验](publishing-xiaohongshu.md#handoff-checks) 的 `pre-submit`。定时入口缺失或读不回完整北京时间则停在草稿。退出码为 0 且所有内容门槛已通过，才可执行对应的最终按钮一次。已有提交锁必须只读核验。

## 可审计结果记录

每次同步在 `<workspace>/files/<slug>.xiaohongshu-result.json` 中记录（与 [publishing-xiaohongshu.md](publishing-xiaohongshu.md) 保持字段对齐并显式标注驱动）：

- `ui_driver`: 固定为 `browser-subagent`
- `browser_backend`、`clipboard_path`（记录实际路径）、`missing_slots`、发布授权与最终页面读回值
- `clipboard_strategy`: 按工作台实际回执记录（如 `native-selection` 或 `clipboard-html`）；读不到时标为未知
- `delivery_source_fingerprint`: 本轮三平台/文章源指纹
- `title`、`mode`（`draft` / `publish` / `schedule` / `test`）、`editor_url`
- `expected_images`、`verified_images`、`expected_h1`、`verified_h1`、`expected_h2`、`verified_h2`
- `external_links`、`first_sentinel`、`middle_sentinels`、`last_sentinel`
- `platform_preview`: `xiaohongshu`
- `heading_repairs`、`image_repairs`（正常一次粘贴必须为 `0`；若经用户授权通过原生控件补图，如实记录张数）
- `draft_reopened`、`draft_verified`、`submission_maybe_sent`、`management_status`、`public_url`
- `official_api_available`: `false`、`official_share_sdk_usable_for_full_sync`: `false`
