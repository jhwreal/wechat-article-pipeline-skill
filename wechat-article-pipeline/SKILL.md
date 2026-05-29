---
name: wechat-article-pipeline
description: "Create a full WeChat/公众号 article package from a topic or direction, including article structure, self-media-style markdown content, built-in Codex image generation for supporting visuals, a single-file editable HTML workbench, and an optional official WeChat API workflow that uploads images and creates a WeChat draft. Use when the user wants a publish-ready long-form WeChat article or explicitly asks to push the article package into the WeChat draft box."
---

# WeChat Article Pipeline

Build one coherent WeChat article package from a single user idea: topic -> article -> derive image jobs from the article content -> directly generate images with Codex's built-in image tool -> editable single-file HTML -> publish manifest. This skill has two stages:

1. Generate the article HTML package. This is the default stage and must be the only stage unless the user explicitly asks for API draft delivery.
2. Push the generated package to the WeChat draft box through official WeChat server APIs. Run this only when the user explicitly asks to push/create/save a WeChat draft. Sending preview is a separate explicit request.

## Core rules

1. Write the article first. Do not generate visuals before the argument is clear.
2. Use self-media explanatory writing, not stiff report prose.
3. Keep the final delivery centered on a single editable HTML workbench file, with every generated image embedded inside the HTML as a `data:image/...;base64,...` URI.
4. Keep the existing workbench/template green as the default page theme. Do not rotate the whole article theme color just to avoid repetition unless the user explicitly asks for a different palette.
5. Use Codex's built-in `image_gen` tool as the visual engine. Never start a nested Codex runtime from inside this skill.
6. Save approved generated files under `<workspace>/image/<article-slug>/`, where `<workspace>` is the current Codex working directory unless the user specifies another output location.
7. After the article is finished, always generate one cover image, one closing image, and in-body visuals at roughly one image per 200 Chinese characters of body copy. Treat the 200-character cadence as a density target, not a rigid quota.
8. Before generating images, make an internal Image Plan: article summary -> slot roles -> local context -> per-slot prompt -> anti-repetition check.
9. Write image prompts from the actual nearby paragraph content. Each image should support the local argument, not act as generic decoration.
10. Keep prompt wording concrete, visually direct, and article-specific. Use the finished copy to drive scene, subject, and emphasis.
11. Do not let every image summarize the full article. Cover and closing can read the whole article meaning; each `body-*` slot must mainly serve its own local context and role.
12. Force variation across the image set: role, scene, composition, visual distance, emotional tone, abstraction level, and information density should not collapse into one repeated prompt shape.
13. Self-check every generated visual before embedding it into the HTML. If a visual is noisy, generic, off-topic, or awkward, regenerate it once with a safer and simpler direction.
14. Prefer a clean and conservative result over decorative complexity. Do not keep a technically valid image if it looks like filler.
15. Default to single-shot execution. If the user gives a topic, rough idea, source fragments, or a short direction, infer the missing brief and proceed without making them repeat themselves.
16. Only ask follow-up questions when the ambiguity would materially change the article's conclusion, audience, or risk profile. Otherwise, choose a reasonable default and keep moving.
17. Determine the article type before visual generation and make the image language follow it.
18. Avoid repetition by changing subject matter, framing, scene logic, and image mood first. Do not fake variation by swapping colors on the same idea.
19. Before choosing image roles, classify the visual mode as `method_visual`, `emotional_illustration`, or `analysis_visual`.
20. Use `method_visual` only when the article is truly teaching steps, tools, workflows, checklists, or procedures. It may use process nodes, arrows, numbered steps, checklist cards, comparison diagrams, and compact information graphics.
21. Use `emotional_illustration` for stories, emotional essays, life principles, relationship pieces, ordinary-person reflections, and articles that primarily need resonance or atmosphere. It must use illustration logic: human moments, symbolic scenes, light, space, objects, tension, silence, and metaphor. Do not use numbered steps, arrows, process diagrams, checklist cards, information cards, UI panels, or icon matrices in body images for this mode.
22. Use `analysis_visual` for industry, mechanism, evidence, and trend pieces. It may use evidence, contrast, mechanism, and restrained metaphor, but should avoid process graphics unless the local paragraph is actually procedural.
23. After the user confirms the article copy, and before deriving image jobs, run the focus-marking step so the final article contains core sentence highlights and occasional pull quotes for reader attention.
24. Apply reading-focus marks in this order: first make the structure clear with useful `##` section headings while drafting; then mark one core sentence in a zone with `**...**` so it renders green; finally, only when a sentence is genuinely quotable, turn that original sentence into a markdown blockquote. Never duplicate a sentence just to create a pull quote. Keep the pink accent style available in the template, but do not add automatic pink keyword marks by default.
25. For technical, tool, coding, workflow, system-building, or tutorial articles, apply technical-term formatting during drafting: wrap concrete project names, repository names, file names, directory names, paths, commands, environment variables, API names, script names, config keys, and literal UI/control names in markdown inline code backticks. This is required terminology formatting, not automatic keyword accent marking and not key-sentence focus marking. Do not overuse it for ordinary conceptual words or broad business ideas.
26. When the user asks to create a WeChat draft, read [publishing.md](references/publishing.md) and use only official WeChat APIs. Do not use private WeChat backend APIs or browser automation against `mp.weixin.qq.com`.
27. Store AppID/AppSecret only in a local `.env` copied from `.env.example`; `.env` must be ignored by Git and never written into final article bundles or logs. If the file is missing or lacks credentials, ask the user for AppID/AppSecret, then generate the local `.env`.
28. Never call final publishing/group-send APIs by default. Stop after creating the draft unless the user separately asks to send a preview. Never imply API-created drafts have original declaration, reward account, or collection set, because the public draft API does not expose those fields.

## Default assumptions

Unless the user explicitly overrides them, use these defaults:

- target reader: Chinese users on WeChat official accounts or Toutiao
- stance: rational, thoughtful, aimed at helping ordinary readers build cognition and practical ability
- length: under 2000 Chinese characters, aim for about 1000 with high information density
- tone: like a capable friend explaining something clearly
- visual density: one generated cover image, one generated closing image, and roughly one in-body image per 200 Chinese characters for method articles; for emotional, story, or principle articles, use fewer and stronger in-body images at roughly 300-450 Chinese characters per image
- output mode: single editable HTML file first, with images embedded directly in the HTML; local image assets and job/support files are only supporting files
- theme color: keep the existing template green unless the user explicitly asks to change it
- backend delivery: do not run by default; when explicitly requested, use the HTML-matched `<html-stem>.publish-manifest.json`, publisher defaults from the local `.env`, and official API credentials from either default `WECHAT_APPID` / `WECHAT_APPSECRET` or a selected named account group in that `.env`

If the user only provides a rough idea, internally infer:
- topic
- target reader
- core claim
- length target
- tone
- visual density and the image jobs that Codex will execute directly with the built-in image tool after writing

## Workflow

### 1. Draft the article brief

Infer or define:
- topic
- target reader
- core claim
- length target
- tone
- visual plan

Use [workflow.md](references/workflow.md) for the default structure.

Do not stop to confirm the brief unless the user explicitly asks for planning first or the direction is too ambiguous to produce a defensible draft.

### 2. Draft the markdown article

Write the article in markdown first.

Use:
- [style-guide.md](references/style-guide.md)
- [workflow.md](references/workflow.md)

Reserve the visual slots after the article is written. Default to one generated cover image and one generated closing image. For method articles, use about one in-body image per 200 Chinese characters. For emotional, story, or principle articles, use a slower rhythm, roughly one stronger in-body illustration per 300-450 Chinese characters, then trim or merge if adjacent paragraphs are better served by one stronger image.

Typical placeholder choices should use markdown image syntax:

```markdown
![题图]({{visual:cover}})
![配图1]({{visual:body-1}})
![配图2]({{visual:body-2}})
![配图3]({{visual:body-3}})
![尾图]({{visual:closing}})
```

The packager also tolerates bare `{{visual:name}}` placeholders and converts them into markdown images, but the markdown-image form above is preferred.

### 3. Derive image jobs from the written article

After the article copy is approved, create a focus-marked markdown copy before generating image jobs:

```bash
python3 scripts/mark_wechat_article_focus.py article.md article.focused.md
```

This command must:
- keep the prose unchanged except for markdown marking
- prefer clear `##` section structure from the article draft itself
- add `**...**` to the most useful core sentence in a focus zone so it renders as the green key sentence
- convert an existing memorable sentence to `> ...` only when it is strong enough; do not append a repeated quote after the paragraph
- skip headings, image placeholders, code fences, inline code, and command/list-heavy blocks
- avoid visual noise by keeping the default to one green sentence and zero or one strong pull quote per zone

Use `article.focused.md` as the source for image-job derivation, packaging, and optional WeChat API draft delivery.

Generate an internal Image Plan before any actual image call.

First classify the article into one of these working types:
- news explanation
- viewpoint/commentary
- practical how-to
- feature/story
- industry analysis

Then divide the article into image beats.

Choose the visual mode before assigning body roles:
- `method_visual`: use `inline_steps`, `inline_checklist`, `inline_detail`, `inline_contrast`, `inline_data_card`, and related method-friendly roles when the article is teaching steps, tools, workflows, or checklists.
- `emotional_illustration`: use `inline_human_moment`, `inline_tension`, `inline_symbolic_scene`, `inline_silence`, `inline_scene`, `inline_metaphor`, and `inline_emotion` for stories, emotions, life principles, and "讲道理" pieces. Body images in this mode must not become numbered diagrams, process graphics, checklist cards, information cards, UI panels, or icon matrices.
- `analysis_visual`: use `inline_explanation`, `inline_contrast`, `inline_evidence`, `inline_detail`, `inline_metaphor`, and occasional scenes for industry or mechanism analysis.

Use nearby paragraphs as the source of truth. For each beat:
- assign a slot role such as `hero_cover`, `inline_explanation`, `inline_scene`, `inline_contrast`, `inline_detail`, `inline_metaphor`, `inline_extension`, or `closing_image`
- identify the paragraph range it supports
- summarize the local point in one sentence
- write one concrete image prompt that reflects that point
- add anti-repetition guards so the new slot does not reuse the same scene/composition/metaphor as earlier slots
- keep the placeholder aligned with that paragraph block

Aim for one generated cover image and one generated closing image overall. For `method_visual`, use roughly one in-body image per 200 Chinese characters. For `emotional_illustration`, prefer fewer but stronger images, roughly one in-body image per 300-450 Chinese characters; a 1000-character article may only need two or three body illustrations.

Default placeholder naming:
- `cover`
- `body-1`, `body-2`, `body-3` ...
- `closing`

Prefer:
- one generated cover image
- one generated closing image tied to the article's final takeaway
- content-driven in-body visuals placed at roughly 200-character intervals
- fewer but stronger in-body images when several adjacent paragraphs support the same visual idea

Normal execution path after the article exists:

```bash
python3 scripts/mark_wechat_article_focus.py article.md article.focused.md
python3 scripts/make_wechat_article_image_jobs.py article.focused.md output.image-jobs.json --debug-plan
```

This command must:
- read the focus-marked finished article markdown
- derive an internal Image Plan plus the final `cover`, `closing`, and `body-*` image jobs from the article content itself
- generate planning metadata for `cover` and `closing` from the full-article meaning, while each `body-*` image uses its local role plus the nearby paragraphs instead of reusing the cover/closing logic
- preserve per-image role metadata in the generated markdown/job artifacts so one slot can be regenerated later without guessing what it was for

### 4. Directly Generate Images With Codex

After `output.image-jobs.json` is written, read its `jobs` array. For each job:

- use the system `imagegen` skill / built-in `image_gen` tool directly from the current Codex turn
- use `job.prompt` as the main prompt, preserving `must_include`, `must_avoid`, `composition`, `visual_mode`, and `content_focus`
- generate exactly one bitmap image for that slot
- copy the selected generated image from `$CODEX_HOME/generated_images/...` into the workspace image directory using the placeholder basename: `cover.png`, `body-1.png`, `closing.png`, etc.
- never leave a final article asset only under `$CODEX_HOME/generated_images`
- inspect the generated image before accepting it; if it fails the role, regenerate once with a simpler, stricter prompt

Default image directory:

```bash
mkdir -p ./image/<article-slug>
```

Use the job's `output` field to choose the filename. If the field is relative, resolve it under the image directory.

Do not use `scripts/image_gen.py` or any custom image API runner unless the user explicitly asks for the imagegen CLI/API fallback. This skill's default path is the current Codex turn's built-in image generation capability.

### 5. Build the editable HTML workbench

After all image files exist:

```bash
python3 scripts/package_wechat_article_bundle.py article.md output.html \
  --plan-json output.image-jobs.json \
  --images-dir ./image/<article-slug> \
  --support-dir ./files/wechat-article-pipeline/<article-slug>
```

This packager will:
- read markdown with `{{visual:name}}` placeholders
- discover matching local files such as `cover.png`, `body-1.png`, and `closing.png`
- write a job JSON automatically
- embed every matched image into the final HTML as a `data:image/...;base64,...` URI
- generate a content-fingerprinted storage key so a newly generated HTML does not load stale browser localStorage from an older file with the same title
- fail if any visual placeholder remains unresolved or if the generated HTML still points to local image files
- build the final editable single-file HTML workbench
- write `<html-stem>.publish-manifest.json` next to the HTML by default for WeChat backend draft/preview automation
- optionally emit support files and a quality report

Before generating visuals, pick a visual direction explicitly. Keep the page/theme chrome on the existing green template unless the user asks otherwise; vary the image treatment, composition, and subject matter instead.

Useful article-type to visual-direction mappings:
- news explanation: sharper, evidence-led, cleaner newsroom or blueprint feel
- viewpoint/commentary: stronger contrast, fewer cards, more poster-like cover
- practical how-to: clearer procedural scenes, calmer palette, steps and checklists only when the local paragraph is actually procedural
- emotional or feature writing: use cinematic illustration, concrete human moments, symbolic spaces, light, tension, silence, and metaphor; avoid all numbered/process/checklist/information-card body images
- industry analysis: restrained palette, concrete metaphors, less decorative cover treatment

Do not default to named SVG-card patterns such as `compare`, `definition`, `steps`, or other layout-led placeholders. The sequence is now content-led: write the article, mark `body-*` beats, generate images from those paragraph blocks, and keep `cover` and `closing` as required special cases.

Within one article, vary the visual mix. Across unrelated articles, actively avoid repeating the same cover framing, same middle-image rhythm, or same symbolic metaphor.

Before locking the plan, do a quick anti-repetition check:
- does this look too similar to the last unrelated article package
- is the chosen cover treatment appropriate for this article type
- are image content, composition, and scene treatment genuinely different, rather than just the palette
- if this still looks like the last article in another color, rewrite the prompt and regenerate instead of forcing it through

Before packaging, inspect each visual against these minimum checks:
- no crowded center area in the cover
- no visual element that competes with the headline
- no generic “AI wallpaper” that ignores the paragraph it is supposed to support
- no obviously awkward spacing, text rendering, or off-topic symbolism

If a visual fails this bar, retry once with a safer prompt or a different visual direction and use that version in the final package.

### 6. Optional second stage: push to WeChat draft box by official API

Only do this when the user explicitly asks for draft creation, draft-box upload, API publishing assistance, or similar delivery. Do not run this stage for ordinary article-generation requests.

Read [publishing.md](references/publishing.md), then:

1. Use the generated `<html-stem>.publish-manifest.json` as the source of truth for only the fields the official draft API can set: title, author, digest, body HTML, cover image, body images, and optional preview account.
2. Use `scripts/publish_wechat_api.py` to:
   - fetch or reuse `access_token` through `cgi-bin/stable_token`;
   - upload body images through `cgi-bin/media/uploadimg`;
   - upload the cover through `cgi-bin/material/add_material?type=image`;
   - create the draft through `cgi-bin/draft/add`;
   - send preview through `cgi-bin/message/mass/preview` only when the user explicitly asks for preview sending.
3. If WeChat returns IP whitelist, administrator confirmation, credential, or permission errors, report the exact official error and stop for the user to resolve it.
4. Stop after the draft is created. Do not call publish/group-send APIs unless separately requested and confirmed.

Publisher defaults and API credentials live in a local `.env` file copied from `.env.example`. This file is excluded from Git and must never be uploaded to GitHub.

```text
.env
```

Shape:

```dotenv
WECHAT_APPID=
WECHAT_APPSECRET=
WECHAT_ACCOUNT_NAME=
WECHAT_AUTHOR=
WECHAT_PREVIEW_ACCOUNT=
```

For multiple public accounts, use ASCII aliases for environment variable names and a separate account-name field for matching:

```dotenv
WECHAT_ACCOUNT_JUZI_NAME=橘子
WECHAT_ACCOUNT_JUZI_APPID=
WECHAT_ACCOUNT_JUZI_APPSECRET=
WECHAT_ACCOUNT_JUZI_AUTHOR=
WECHAT_ACCOUNT_JUZI_PREVIEW_ACCOUNT=
```

`NAME` is the account selector used by `--account`. `AUTHOR` is only the article byline and must not be used to identify credentials.

When `.env` contains exactly one named account, use it by default if the user has not specified an account. When `.env` contains multiple named accounts and the user has not specified which one to use, ask the user to choose by public account name before creating the draft.

If `.env` does not exist or lacks credentials for the selected account, ask the user for the account name, AppID, and AppSecret, then create the file locally with restrictive permissions. The GitHub version must include `.env.example` and setup instructions, but never `.env`.

Create a draft:

```bash
python3 scripts/publish_wechat_api.py output.publish-manifest.json \
  --env-file /path/to/.env \
  --account 橘子 \
  --remember \
  --check-draft-switch \
  --verify-draft
```

Omit `--account` only when using the default `WECHAT_APPID` / `WECHAT_APPSECRET` pair or when `.env` contains exactly one named account.

Add `--send-preview` only when the user explicitly asks to send a preview.

Use `--dry-run` first when validating a package without calling WeChat.

Low-level fallback when a job JSON already exists:

```bash
python3 scripts/build_wechat_article_workbench.py job.json output.html
```

This will:
- read image assets from local files, embedded payloads, or URLs
- embed them into markdown as data URIs when given base64 or local file paths
- inject the markdown into the workbench template
- output a single HTML file
- optionally save raw markdown, resolved asset references, and a quality report

## Output policy

Default deliverables:
- single-file editable HTML workbench with generated images embedded as data URIs
- `<html-stem>.publish-manifest.json` for optional WeChat API draft/preview automation
- source markdown
- local image assets or asset references
- job JSON
- quality report for resolved visuals

Default interaction policy:
- take one input from the user and produce the package
- avoid multi-round brief collection unless necessary
- optimize for a usable first draft instead of a “fully confirmed” plan

Save the final HTML under `<workspace>/files/` unless the user asks otherwise.
Default image output directory: `<workspace>/image/<article-slug>/`.

## Resources

- [workflow.md](references/workflow.md) — article workflow and section expectations
- [style-guide.md](references/style-guide.md) — tone, pacing, and visual defaults
- [job-schema.md](references/job-schema.md) — JSON contract for the build script
- [publishing.md](references/publishing.md) — official API workflow for WeChat drafts and previews
- [wechat-md-workbench.template.v3.html](assets/templates/wechat-md-workbench.template.v3.html) — editable HTML workbench template used by the build scripts
