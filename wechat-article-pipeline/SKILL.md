---
name: wechat-article-pipeline
description: Use when producing Chinese WeChat/公众号 article packages, checking articles on "检查" or "检查一下", editable workbenches, image planning, WeChat draft API delivery, Toutiao/Xiaohongshu Chrome sync, three-platform drafts, or explicit "打开秘书模式" requests.
---

# WeChat Article Pipeline

Create local article packages or check existing drafts; run external draft creation or publishing only when requested.

## Core Decisions

- For article "检查" or "检查一下", read [Check Mode](references/article-check.md) before drafting. Report findings and improvements; edit only when requested. Respect narrower checks.
- When the user asks to annotate a term, follow [annotations.md](references/annotations.md): use “（注1）” in the text and numbered explanations in a final appendix.
- Read [writing-donts.md](references/writing-donts.md) before drafting or revising; check articles against it before delivery, repackaging, or publishing, preserving its contextual scope and user-text rules.
- The first Markdown H1 is the canonical title; rename it there and require it.
- Enable secretary mode only on explicit "打开秘书模式", for this request; read [style-guide.md](references/style-guide.md). Do not mention it unless asked.
- Infer briefs from rough ideas. Integrate additions and corrections as reader-facing prose per [workflow.md](references/workflow.md), preserving explicit verbatim instructions and quotations.
- For "不配图", "只排版", or "直接格式化", use the no-image path. If image generation is unavailable, follow the capability fallback in [image-production.md](references/image-production.md); do not silently drop requested images.
- For 补图, continuation, or missing assets, use the missing-image path; preserve finished images.
- If the user asks to导入草稿箱, create a WeChat draft through official APIs only. Never use browser automation or private `mp.weixin.qq.com` endpoints for delivery.
- Toutiao: use Computer Use to operate the user's real Chrome end to end and follow [publishing-toutiao.md](references/publishing-toutiao.md). Do not use Browser/Chrome browser automation, Playwright, CDP, DOM evaluation, or background tab objects for any Toutiao UI step.
- Toutiao publish authorization: a user-authored instruction to “发头条”, “发布头条”, or schedule a Toutiao post is already the confirmation to submit that same content to Toutiao at the stated time. Do not ask for a second publish confirmation in the same workflow; pause only when a material choice is missing or changed, or for CAPTCHA, authentication, or a platform hard blocker.
- Xiaohongshu: use Chrome + Computer Use and [publishing-xiaohongshu.md](references/publishing-xiaohongshu.md).
- Three-platform sync: read [publishing-three-platform.md](references/publishing-three-platform.md), initialize its state, then create WeChat → Toutiao → Xiaohongshu drafts.

## Workspace Contract

Keep final artifacts in the current workspace unless the user names another location:

- markdown: `<workspace>/files/<slug>.md`
- check report: `<workspace>/files/<slug>.check.md`
- focused markdown: `<workspace>/files/<slug>.focused.md`
- image jobs: `<workspace>/files/<slug>.image-jobs.json`
- HTML workbench: `<workspace>/files/<slug>.html`
- job: `<workspace>/files/<slug>.job.json`
- optional publish manifest: `<workspace>/files/<slug>.publish-manifest.json`
- images: `<workspace>/image/<slug>/cover.png`, `body-*.png`, `closing.png`

Keep final assets out of temp directories and `$CODEX_HOME/generated_images`.

## Default Article Path

1. Inspect `files/` and `image/` before choosing a slug.
2. Draft in markdown first. Use [workflow.md](references/workflow.md) and [style-guide.md](references/style-guide.md).
3. Place visual placeholders in the markdown only when images are desired: `cover`, `body-1`, `body-2`, ..., `closing`.
4. Run the orchestration script once for planning:

```bash
python3 <skill>/scripts/postprocess_wechat_article.py \
  <workspace>/files/<slug>.md \
  <workspace>/files/<slug>.html \
  --workspace <workspace> \
  --article-slug <slug> \
  --jobs-out <workspace>/files/<slug>.image-jobs.json \
  --focused-article-out <workspace>/files/<slug>.focused.md \
  --support-dir <workspace>/files/wechat-article-pipeline/<slug> \
  --plan-only
```

5. Read [image-production.md](references/image-production.md), run its single-pass queue with currently available worker slots, and enforce strict 3:2 visuals.
6. Rerun without `--plan-only` to build the package. Add `--publish-manifest` only for requested API draft handoff.
7. Run `verify_wechat_article_package.py <workspace>/files/<slug>.html` and fix any failures before delivery.
8. Follow [delivery.md](references/delivery.md): an editable workbench gets a verified running URL first, then its HTML file; static-file requests get files directly.

Mount only the active platform preview from the sole Markdown source. Cache semantic HTML; embed images only while copying.

## Fast Paths

No-image formatting:

```bash
python3 <skill>/scripts/postprocess_wechat_article.py \
  <workspace>/files/<slug>.md \
  <workspace>/files/<slug>.html \
  --no-images \
  --support-dir <workspace>/files/wechat-article-pipeline/<slug>
```

No body images, but draft-box delivery:

```bash
python3 <skill>/scripts/postprocess_wechat_article.py \
  <workspace>/files/<slug>.md \
  <workspace>/files/<slug>.html \
  --no-images \
  --publish-manifest \
  --cover-image <workspace>/image/<slug>/cover.png
```

No-image WeChat drafts still need one cover for `thumb_media_id`; keep it out of the body.

Missing-image jobs only:

```bash
python3 <skill>/scripts/postprocess_wechat_article.py \
  <workspace>/files/<slug>.md \
  <workspace>/files/<slug>.html \
  --workspace <workspace> \
  --article-slug <slug> \
  --jobs-out <workspace>/files/<slug>.image-jobs.json \
  --missing-only \
  --plan-only
```

Generate only listed images, then package without `--missing-only`.

## Publishing Path

Read [publishing.md](references/publishing.md) before WeChat API calls. Dry-run first. First draft consumes its issue. Later same-conversation, same-slug drafts use `--same-session-revision`: reuse that article's saved signature, no advance. Never publish/group-send by default.

Inspect every live WeChat API result immediately. On `40164` or an IP-allowlist error, stop the entire delivery chain: do not retry, upload, package, or continue to Toutiao/Xiaohongshu. Report the outbound IP, ask the user to allowlist it, end the turn, and resume only after acknowledgment.

For Toutiao and Xiaohongshu, load their publishing reference before the first browser write. Follow each platform’s handoff, verification, submission latch, and recovery limits. Never repeat a possible final submission.

## Safety Rules

- Do not overwrite an existing package unless the user asked for that exact slug or file.
- Do not delete old markdown, images, jobs, manifests, or support files without explicit permission.
- Do not install dependencies, modify agent config, switch accounts, or edit `.env` credentials unless the user explicitly approves that action.
- Do not start nested agent runtimes or custom image API runners for normal image work.
- Keep `cover.png` as the hero; derived WeChat crop previews never replace it.
- Enable Toutiao `头条首发` only when the user confirms eligibility.
- Do not use Xiaohongshu creator-platform private APIs, Cookie export, localStorage export, token extraction, or request replay for delivery.
- Publish no external hyperlinks in WeChat, Toutiao, or Xiaohongshu bodies. Keep source names as plain text; evidence links belong in separate check reports or support files.

## Acceptance Checklist

For article packages, confirm:

- artifacts stay under the workspace, share one slug, contain every requested 3:2 visual, and leave no unresolved `{{visual:*}}`
- `verify_wechat_article_package.py` reports `status: ok`; delivery matches [delivery.md](references/delivery.md), including a reachable server for editable workbenches
- Markdown uses relative image paths; all previews derive from it and preserve semantic headings and image positions
- Toutiao manual copy must not require a WeChat draft: use complete HTTPS receipts when available, otherwise embed all original images (including GIF), never loopback image URLs. Verify target-editor uploads before claiming delivery; Xiaohongshu embeds images during copy
- Toutiao uses only Computer Use against the real foreground Chrome, with one workbench copy and one system paste; Xiaohongshu keeps its own documented handoff. On a hard gate, preserve the diagnostic draft and stop
- delivery reports result paths, status, verified structure/images, and any public URL; platform bodies contain no external links
- added or revised prose stands alone for readers without chat residue, respecting requested verbatim text and quotations

## References

- Drafting: [workflow.md](references/workflow.md), [style-guide.md](references/style-guide.md).
- Images: [image-production.md](references/image-production.md), [image-rules.json](references/image-rules.json).
- Contracts: [job-schema.md](references/job-schema.md).
- Delivery: [publishing.md](references/publishing.md), [publishing-three-platform.md](references/publishing-three-platform.md), [publishing-toutiao.md](references/publishing-toutiao.md), [publishing-xiaohongshu.md](references/publishing-xiaohongshu.md).
- Debug workbench rendering only: [wechat-md-workbench.template.v3.html](assets/templates/wechat-md-workbench.template.v3.html).
- Read [.env.example](.env.example) only for requested API setup.
