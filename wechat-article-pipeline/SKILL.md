---
name: wechat-article-pipeline
description: Use when producing Chinese WeChat/公众号 article packages, editable workbenches, image planning, WeChat draft API delivery, Toutiao/Xiaohongshu Chrome sync, three-platform drafts, or explicit "打开秘书模式" requests.
---

# WeChat Article Pipeline

Produce a complete local article package from the user's topic, draft, notes, or markdown. Call delivery stages only when requested.

## Core Decisions

- Use this skill for writing, packaging, formatting, or polishing a WeChat/公众号 article.
- If the user says "打开秘书模式", enable it for this request only and read its section in [style-guide.md](references/style-guide.md). Do not infer or mention it unless asked.
- Infer a brief from rough ideas. Ask only when ambiguity changes the conclusion, audience, legal risk, account, or delivery target.
- If the user asks for "不配图", "只排版", "直接格式化", or similar, use the no-image path.
- If the user asks to补图, continue, or fix missing assets, use the missing-image path and do not rebuild finished images.
- If the user asks to导入草稿箱, create a WeChat draft through official APIs only. Never use browser automation or private `mp.weixin.qq.com` endpoints for delivery.
- Toutiao: use Chrome + Computer Use and [publishing-toutiao.md](references/publishing-toutiao.md).
- Toutiao publish authorization: a user-authored instruction to “发头条”, “发布头条”, or schedule a Toutiao post is already the confirmation to submit that same content to Toutiao at the stated time. Do not ask for a second publish confirmation in the same workflow; pause only when a material choice is missing or changed, or for CAPTCHA, authentication, or a platform hard blocker.
- Xiaohongshu: use Chrome + Computer Use and [publishing-xiaohongshu.md](references/publishing-xiaohongshu.md).
- Three-platform sync: read [publishing-three-platform.md](references/publishing-three-platform.md), initialize its state, then create WeChat → Toutiao → Xiaohongshu drafts.

## Workspace Contract

Keep final artifacts in the current workspace unless the user names another location:

- markdown: `<workspace>/files/<slug>.md`
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
8. Start the local persistence server after every verified workbench build:

```bash
python3 <skill>/scripts/serve_wechat_workbench.py \
  <workspace>/files/<slug>.html \
  --workspace <workspace>
```

Keep it running. Deliver `WORKBENCH_URL` before `HTML_PATH`; direct-file mode is preview/copy-only.

Mount only the active platform preview from the sole Markdown source. Cache semantic HTML and build copy adapters lazily. The platform selector drives one current-format copy button and a preflight summary. Toutiao uses WeChat HTTPS image receipts; Xiaohongshu embeds images only while copying.

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

Read [publishing.md](references/publishing.md) before WeChat API calls. Dry-run first. First draft consumes its issue. Later same-conversation, same-slug drafts use `--same-session-revision`: current counter minus one, no advance. Never publish/group-send by default.

After every live WeChat API command, inspect its result before doing any other work. If it returns `40164` or says the current IP is not in the Official Account API whitelist, treat that as an immediate hard stop for the entire delivery chain: do not retry, upload more assets, continue to Toutiao/Xiaohongshu, or perform unrelated packaging while the user waits. Immediately tell the user that publishing has stopped, show the outbound IP from the error, and ask them to add it to the WeChat Official Account IP whitelist. End the turn and resume only once the whitelist update is acknowledged.

For Toutiao, read [publishing-toutiao.md](references/publishing-toutiao.md) before the first browser write. Use Chrome on the loopback workbench; use Computer Use only to paste into the external editor. Follow its state machine, one-shot paste rule, submission latch, and recovery budget.

For Xiaohongshu, read [publishing-xiaohongshu.md](references/publishing-xiaohongshu.md) before the first browser write. Use Computer Use for system-clipboard paste and Chrome for heading/image QA. Auto-save is not draft proof. Never repeat a possible final submission.

## Safety Rules

- Do not overwrite an existing package unless the user asked for that exact slug or file.
- Do not delete old markdown, images, jobs, manifests, or support files without explicit permission.
- Do not install dependencies, modify Codex config, switch accounts, or edit `.env` credentials unless the user explicitly approves that action.
- Do not start nested Codex runtimes or custom image API runners for normal image work.
- Keep `cover.png` as the hero; derived WeChat crop previews never replace it.
- Enable Toutiao `头条首发` only when the user confirms eligibility.
- Do not use Xiaohongshu creator-platform private APIs, Cookie export, localStorage export, token extraction, or request replay for delivery.
- Publish no external hyperlinks in WeChat, Toutiao, or Xiaohongshu bodies. Preserve source names as plain text and remove every external `href` before delivery.
- Never absorb or defer a WeChat `40164` error inside a longer workflow. Surface it to the user immediately as a blocking result.

## Acceptance Checklist

Before delivery, confirm:

- final HTML is under `<workspace>/files/`
- markdown, job JSON, image directory, and any requested manifest use the same slug
- every requested visual is present or intentionally skipped by `--no-images`
- every generated visual is strict 3:2 landscape unless the user explicitly requested another ratio
- no unresolved `{{visual:*}}` remains in the HTML
- workbench Markdown uses relative image paths; WeChat and Xiaohongshu copy inline image data, while image-bearing Toutiao copy requires an equal ordered set of HTTPS body-image URLs from the successful WeChat draft receipt
- the platform dropdown renders WeChat, Toutiao, and Xiaohongshu from the same Markdown; Toutiao/Xiaohongshu copies retain semantic headings and original image positions
- normal Toutiao/Xiaohongshu handoff is exactly one workbench copy and one system paste; if structure or platform-image hard gates fail, preserve the diagnostic draft and stop instead of silently repairing it paragraph by paragraph or image by image
- `verify_wechat_article_package.py` reports `status: ok`
- platform deliveries report result files, status, verified structure/images, and any public URL
- WeChat, Toutiao, and Xiaohongshu body content contains zero external hyperlinks
- workbench persistence server remains running and delivery gives its loopback URL before the HTML path
- when no HTML workbench was produced, give the main artifact path first, then supporting paths

## References

- [workflow.md](references/workflow.md): article structure, interaction defaults, and focus marking.
- [image-production.md](references/image-production.md): single-pass image execution, capacity-aware image workers, and user-requested regeneration.
- [image-rules.json](references/image-rules.json): the single source for image generation, avoid, selection, and image-influence rules.
- [style-guide.md](references/style-guide.md): writing style, Secretary Mode, focus marks, and technical inline-code rules.
- [job-schema.md](references/job-schema.md): image-job and workbench JSON contracts.
- [publishing.md](references/publishing.md): official WeChat draft/preview API procedure.
- [publishing-three-platform.md](references/publishing-three-platform.md): resumable WeChat → Toutiao → Xiaohongshu draft synchronization and aggregate results.
- [publishing-toutiao.md](references/publishing-toutiao.md): Chrome + Computer Use Toutiao draft, publish, and public-page QA procedure.
- [publishing-xiaohongshu.md](references/publishing-xiaohongshu.md): Chrome + Computer Use Xiaohongshu long-article draft, two-level heading preservation, image verification, publish, and public-page QA procedure.
- [assets/templates/wechat-md-workbench.template.v3.html](assets/templates/wechat-md-workbench.template.v3.html): template asset used by scripts; do not read it unless debugging template behavior.
- Read [.env.example](.env.example) only for requested API setup.
