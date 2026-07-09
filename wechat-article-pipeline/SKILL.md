---
name: wechat-article-pipeline
description: Use when a user wants a publish-ready Chinese WeChat/公众号 article package, editable article HTML workbench, article formatting, image-job planning, missing visual jobs, official WeChat draft-box delivery, or explicitly says "打开秘书模式" while drafting or revising Chinese article text.
---

# WeChat Article Pipeline

Produce a usable WeChat article package from the user's topic, draft, source notes, or existing markdown. Default to one complete local package in the current Codex workspace; call the WeChat API stage only when the user explicitly asks for draft-box delivery or preview.

## Core Decisions

- If the user asks to write, make, package, format, or polish a WeChat/公众号 article, proceed with this skill.
- If the user explicitly says "打开秘书模式", enable Secretary Mode for this request only. Use it only to organize the user's already-spoken article mainline; do not infer it from ordinary rough briefs. Read [style-guide.md](references/style-guide.md) and follow the "Secretary Mode" section. Do not mention the mode in the article unless the user asks.
- If the user gives only a rough idea, infer the brief and write. Ask only when ambiguity would change the article conclusion, audience, legal risk, account selection, or delivery target.
- If the user asks for "不配图", "只排版", "直接格式化", or similar, use the no-image path.
- If the user asks to补图, continue, or fix missing assets, use the missing-image path and do not rebuild finished images.
- If the user asks to导入草稿箱, create a WeChat draft through official APIs only. Never use browser automation or private `mp.weixin.qq.com` endpoints for delivery.

## Workspace Contract

Run commands from the user's current article workspace unless the user names another output location. The scripts live in this skill folder, but final artifacts belong in the workspace:

- markdown: `<workspace>/files/<slug>.md`
- focused markdown: `<workspace>/files/<slug>.focused.md`
- image jobs: `<workspace>/files/<slug>.image-jobs.json`
- HTML workbench: `<workspace>/files/<slug>.html`
- sidecar: `<workspace>/files/<slug>.clipboard-assets.js`
- job: `<workspace>/files/<slug>.job.json`
- publish manifest: `<workspace>/files/<slug>.publish-manifest.json`
- images: `<workspace>/image/<slug>/cover.png`, `body-*.png`, `closing.png`
- support files: `<workspace>/files/wechat-article-pipeline/<slug>/`

Do not leave final assets only in `$CODEX_HOME/generated_images` or a temp directory. Do not write finished article packages inside the skill repository unless the user explicitly asks.

## Default Article Path

1. Inspect existing `files/` and `image/` before choosing a slug, so old packages are not overwritten.
2. Draft or revise the article in markdown first. Use [workflow.md](references/workflow.md) for structure and [style-guide.md](references/style-guide.md) for voice, focus marks, technical inline-code rules, and visual grammar.
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

5. Read [image-production.md](references/image-production.md), then use `generation_queue[]` for single-pass image generation. Run image workers in concurrent batches of up to 4 subagents; if the queue has more than 4 images, start the next image as soon as any worker finishes. Save each result directly as `jobs[].output`. Do not inspect the generated images, including the cover; after files exist, continue to packaging and script verification only.
6. Run the same script again without `--plan-only` to build the HTML, job JSON, crop previews, support files, and publish manifest.
7. Run `verify_wechat_article_package.py <workspace>/files/<slug>.html` and fix any failures before delivery.

## Fast Paths

No-image formatting:

```bash
python3 <skill>/scripts/postprocess_wechat_article.py \
  <workspace>/files/<slug>.md \
  <workspace>/files/<slug>.html \
  --no-images \
  --support-dir <workspace>/files/wechat-article-pipeline/<slug>
```

Use this when the user wants a formatted article without generated visuals. This path skips publish-manifest creation by default; add `--publish-manifest` only when a later API handoff is intentional. Official WeChat draft creation may still need a cover asset, depending on the account/API requirement; state that clearly instead of silently inventing one.

No body images, but draft-box delivery:

```bash
python3 <skill>/scripts/postprocess_wechat_article.py \
  <workspace>/files/<slug>.md \
  <workspace>/files/<slug>.html \
  --no-images \
  --publish-manifest \
  --cover-image <workspace>/image/<slug>/cover.png
```

Use this when the user says no配图 but still wants 草稿箱. WeChat `draft/add` requires a cover `thumb_media_id`; here `--no-images` means no body/closing images, not no cover. Generate or reuse exactly one cover asset and do not insert it into the article body.

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

Generate only those listed images, then rerun the default packaging command without `--missing-only`.

## Publishing Path

Read [publishing.md](references/publishing.md) before any draft-box API call. Use the HTML-matched `<slug>.publish-manifest.json` as the handoff file. Run `scripts/publish_wechat_api.py <manifest>` first for local dry-run validation; add `--create-draft --increment-original-issue` only when the user explicitly asks to导入草稿箱 for a normal new article, so the next article number advances after successful draft creation. Omit `--increment-original-issue` when re-creating or fixing an old draft and the user does not want to consume a new original-issue number. Send preview only when separately requested. Never call final publish/group-send APIs by default.

Account credentials and publisher defaults live in local `.env` values, never in article bundles or logs. If multiple accounts are configured and the user did not name one, ask which public account to use before API delivery. If credentials or author fields are missing, ask for the missing values instead of guessing.

## Safety Rules

- Do not overwrite an existing package unless the user asked for that exact slug or file.
- Do not delete old markdown, images, jobs, manifests, or support files without explicit permission.
- Do not install dependencies, modify Codex config, switch accounts, or edit `.env` credentials unless the user explicitly approves that action.
- Do not start nested Codex runtimes or custom image API runners for normal image work.
- Keep `cover.png` as the article hero image. Packaging may derive WeChat crop previews such as `cover.wechat-235.png` and `cover.wechat-1x1.png`; do not replace the original hero with a crop.

## Acceptance Checklist

Before delivery, confirm:

- final HTML is under `<workspace>/files/`
- markdown, job JSON, manifest, and image directory use the same slug
- every requested visual is present or intentionally skipped by `--no-images`
- no unresolved `{{visual:*}}` remains in the HTML
- workbench Markdown uses relative image paths; copy inlines local images only in clipboard HTML
- `verify_wechat_article_package.py` reports `status: ok`
- optional WeChat API result file is reported if draft delivery was run
- final response gives the HTML path first, then markdown/image/manifest paths when relevant

## References

- [workflow.md](references/workflow.md): article structure, interaction defaults, and focus marking.
- [image-production.md](references/image-production.md): single-pass image execution, 4 image worker subagents, and user-requested regeneration.
- [image-rules.json](references/image-rules.json): the single source for image generation, avoid, selection, and image-influence rules.
- [style-guide.md](references/style-guide.md): writing style, Secretary Mode, focus marks, and technical inline-code rules.
- [job-schema.md](references/job-schema.md): image-job and workbench JSON contracts.
- [publishing.md](references/publishing.md): official WeChat draft/preview API procedure.
- [assets/templates/wechat-md-workbench.template.v3.html](assets/templates/wechat-md-workbench.template.v3.html): template asset used by scripts; do not read it unless debugging template behavior.
- `README.md`, `examples/`, and `.env.example` are install/demo assets; do not read them during normal article execution.
