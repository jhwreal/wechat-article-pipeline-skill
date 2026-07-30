---
name: wechat-article-pipeline
description: Use when a user wants a publish-ready Chinese WeChat/公众号 article package, editable article HTML workbench, article formatting, image-job planning, missing visual jobs, official WeChat draft-box delivery, synchronized 今日头条 draft/publishing through Chrome, or explicitly says "打开秘书模式" while drafting or revising Chinese article text.
---

# WeChat Article Pipeline

Produce a complete local article package from the user's topic, draft, notes, or markdown. Call delivery stages only when requested.

## Core Decisions

- If the user asks to write, make, package, format, or polish a WeChat/公众号 article, proceed with this skill.
- If the user says "打开秘书模式", enable it for this request only and read its section in [style-guide.md](references/style-guide.md). Do not infer or mention it unless asked.
- If the user gives only a rough idea, infer the brief and write. Ask only when ambiguity would change the article conclusion, audience, legal risk, account selection, or delivery target.
- If the user asks for "不配图", "只排版", "直接格式化", or similar, use the no-image path.
- If the user asks to补图, continue, or fix missing assets, use the missing-image path and do not rebuild finished images.
- If the user asks to导入草稿箱, create a WeChat draft through official APIs only. Never use browser automation or private `mp.weixin.qq.com` endpoints for delivery.
- For explicitly requested Toutiao sync or publishing, use Chrome plus Computer Use and read [publishing-toutiao.md](references/publishing-toutiao.md). Use Computer Use for the system-clipboard rich-text copy/paste handoff; use Chrome for page inspection, settings, submission, and verification. This does not change the WeChat API-only rule.

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

5. Read [image-production.md](references/image-production.md), then run its single-pass queue with currently available worker slots. Default every visual to strict 3:2 landscape. Verify files and dimensions only; regenerate invalid ratios before packaging.
6. Run the same script again without `--plan-only` to build the HTML, job JSON, crop previews, and support files. Add `--publish-manifest` only when the user requested API draft-box handoff.
7. Run `verify_wechat_article_package.py <workspace>/files/<slug>.html` and fix any failures before delivery.
8. After every verified HTML workbench build, start the local persistence server before delivery. This is the default for any task that produces an HTML workbench, even when the user did not explicitly ask to open it:

```bash
python3 <skill>/scripts/serve_wechat_workbench.py \
  <workspace>/files/<slug>.html \
  --workspace <workspace>
```

Keep it running. Deliver `WORKBENCH_URL` first and `HTML_PATH` second. Use the loopback URL for editing; direct-file mode is preview/copy-only.

## Fast Paths

No-image formatting:

```bash
python3 <skill>/scripts/postprocess_wechat_article.py \
  <workspace>/files/<slug>.md \
  <workspace>/files/<slug>.html \
  --no-images \
  --support-dir <workspace>/files/wechat-article-pipeline/<slug>
```

This removes existing `{{visual:*}}` placeholders and skips the manifest unless `--publish-manifest` is supplied. Draft delivery may still require a cover.

No body images, but draft-box delivery:

```bash
python3 <skill>/scripts/postprocess_wechat_article.py \
  <workspace>/files/<slug>.md \
  <workspace>/files/<slug>.html \
  --no-images \
  --publish-manifest \
  --cover-image <workspace>/image/<slug>/cover.png
```

For no配图 draft delivery, generate or reuse one cover for WeChat's required `thumb_media_id`; do not insert it into the body.

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

Read [publishing.md](references/publishing.md) before WeChat API calls. Dry-run first; create drafts only when requested. A signed manifest automatically advances the issue counter after success; do not rely on callers remembering an extra flag. Never publish/group-send by default.

For Toutiao, read [publishing-toutiao.md](references/publishing-toutiao.md) before the first browser write. Use Computer Use for workbench rich-text system copy/paste, never the browser virtual clipboard; use Chrome for inspection and publishing. Submit only when authorized. For scheduled publishing, follow the reference's exact state machine and one-shot submission latch: a repeated button label is not state proof, and any possible final submission forbids retrying, hiding, deleting, or creating a replacement until the management page is checked and the user authorizes any recovery.

## Safety Rules

- Do not overwrite an existing package unless the user asked for that exact slug or file.
- Do not delete old markdown, images, jobs, manifests, or support files without explicit permission.
- Do not install dependencies, modify Codex config, switch accounts, or edit `.env` credentials unless the user explicitly approves that action.
- Do not start nested Codex runtimes or custom image API runners for normal image work.
- Keep `cover.png` as the article hero image. Packaging may derive WeChat crop previews such as `cover.wechat-235.png` and `cover.wechat-1x1.png`; do not replace the original hero with a crop.
- Enable Toutiao `头条首发` only when the user confirms eligibility.
- Publish no external hyperlinks in WeChat or Toutiao bodies. Preserve source names as plain text and remove every external `href` before delivery.

## Acceptance Checklist

Before delivery, confirm:

- final HTML is under `<workspace>/files/`
- markdown, job JSON, image directory, and any requested manifest use the same slug
- every requested visual is present or intentionally skipped by `--no-images`
- every generated visual is strict 3:2 landscape unless the user explicitly requested another ratio
- no unresolved `{{visual:*}}` remains in the HTML
- workbench Markdown uses relative image paths; copy inlines local images only in clipboard HTML
- `verify_wechat_article_package.py` reports `status: ok`
- optional WeChat API result file is reported if draft delivery was run
- optional Toutiao delivery reports its status and verified public URL
- scheduled Toutiao delivery has exactly one same-day row for the exact title, and that row shows the expected `将于 MM-DD HH:mm 发布`
- WeChat and Toutiao body content contains zero external hyperlinks
- workbench persistence server remains running and delivery gives its loopback URL before the HTML path
- when no HTML workbench was produced, give the main artifact path first, then supporting paths when relevant

## References

- [workflow.md](references/workflow.md): article structure, interaction defaults, and focus marking.
- [image-production.md](references/image-production.md): single-pass image execution, capacity-aware image workers, and user-requested regeneration.
- [image-rules.json](references/image-rules.json): the single source for image generation, avoid, selection, and image-influence rules.
- [style-guide.md](references/style-guide.md): writing style, Secretary Mode, focus marks, and technical inline-code rules.
- [job-schema.md](references/job-schema.md): image-job and workbench JSON contracts.
- [publishing.md](references/publishing.md): official WeChat draft/preview API procedure.
- [publishing-toutiao.md](references/publishing-toutiao.md): Chrome + Computer Use Toutiao draft, publish, and public-page QA procedure.
- [assets/templates/wechat-md-workbench.template.v3.html](assets/templates/wechat-md-workbench.template.v3.html): template asset used by scripts; do not read it unless debugging template behavior.
- Read [.env.example](.env.example) only for requested API setup.
