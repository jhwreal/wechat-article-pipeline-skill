# Workflow

Default article structure for explanatory WeChat or Toutiao-style posts aimed at ordinary Chinese readers:

1. Hook the reader with a concrete gap or confusion.
2. Explain the core concept in plain language.
3. Show why the concept matters in real life.
4. Give a simple model, process, or comparison.
5. End with one memorable takeaway.

Default working assumptions:

- audience: general Chinese readers, not specialists
- stance: rational, thoughtful, practical
- length: aim for about 1000 Chinese characters and stay under 2000
- tone: concise, high-density, friend-like explanation
- goal: increase cognition and practical capability, not just “popular science”

Interaction rule:

- If the user provides only a topic or rough idea, infer the rest and write.
- Do not require a separate brief-confirmation round by default.

Visual defaults:

- finish the article first, then decide image placement
- after the user confirms the article copy, run `scripts/mark_wechat_article_focus.py article.md article.focused.md` before deriving image jobs
- use the focus-marked markdown for image jobs, HTML packaging, publish manifest generation, and optional WeChat draft creation
- in roughly every 300 Chinese characters, add at most one markdown blockquote for a genuinely memorable sentence and 1-2 `**bold**` marks for useful key terms, focus words, or concepts
- treat focus marks as reading aids, not decoration; too many marks dilute attention and should be avoided
- do not mark headings, image placeholders, code blocks, inline code, commands, or dense list-only sections
- before any actual image generation, make an internal Image Plan for all slots: article summary -> slot role -> local context -> prompt -> anti-repetition check
- always generate one cover image and one closing image
- aim for about one in-body image per 200 Chinese characters for method articles, and about one stronger in-body illustration per 300-450 Chinese characters for emotional, story, or principle articles
- classify visual mode before assigning roles: `method_visual`, `emotional_illustration`, or `analysis_visual`
- for `emotional_illustration`, avoid numbered/process/checklist/information-card body images and prefer concrete human moments, symbolic scenes, atmosphere, light, tension, silence, and metaphor
- save local image files under `<workspace>/image/<article-slug>/`
- derive image jobs with `python3 scripts/make_wechat_article_image_jobs.py article.md output.image-jobs.json --debug-plan`
- generate those files by directly calling Codex's built-in `image_gen` tool from the current Codex turn; do not start a nested Codex process
- `cover`: opening anchor image for the title area
- `body-1`, `body-2`, `body-3` ...: in-body images tied to nearby paragraph clusters
- `closing`: concluding image tied to the article's final takeaway
- do not default to semantic placeholder names inherited from old SVG layouts; use generic `body-*` beats and let the nearby paragraphs determine the prompt
- `cover` and `closing` should read the full article meaning; each `body-*` image should read the text immediately before that placeholder at roughly the 200-character cadence
- each slot still needs its own role, such as explanation / scene / contrast / detail / metaphor / extension / closing, instead of turning every image into the same theme summary
- rotate subject matter, framing, metaphor, and mood based on article type instead of repeating one stock combination

Keep explanatory visuals close to the paragraph they support.

Visual packaging rule:

1. Confirm the article copy.
2. Run focus marking on the confirmed markdown.
3. Generate the draft image after the nearby paragraphs are written and marked.
4. Check that the slot role is correct for that position instead of defaulting to another generic theme image.
5. Check whether it matches the paragraph point, feels generic, or competes with the headline.
6. If it fails, regenerate once with a safer and simpler prompt or a different visual direction.
7. Save the approved file with the matching placeholder basename such as `body-2.png`.
8. Package the focus-marked markdown plus local image directory into the final HTML with `scripts/package_wechat_article_bundle.py`, keeping role metadata in the markdown/job artifacts.
9. Keep the generated `<html-stem>.publish-manifest.json` next to the HTML. It is the handoff file for the optional WeChat API draft-box stage.

For cover and closing visuals, bias toward quieter composition:
- fewer competing elements
- clearer whitespace around the headline
- no noisy fake UI clutter or text-heavy overlays

Draft-box API stage rule:

- Only run the WeChat API delivery stage when the user explicitly asks for draft-box creation, draft saving, or API publishing assistance.
- Use official WeChat server APIs through `scripts/publish_wechat_api.py`; never use private WeChat backend APIs.
- Read `references/publishing.md` before creating the draft or sending preview.
- Use `<html-stem>.publish-manifest.json` for title, digest, author, cover, body HTML, and optional preview account.
- If WeChat returns IP whitelist, administrator confirmation, credential, permission, or risk-control errors, stop and ask the user to resolve them.
- Create the draft only. Send preview only if the user explicitly asks for preview. Do not call final publish/group-send APIs by default.
