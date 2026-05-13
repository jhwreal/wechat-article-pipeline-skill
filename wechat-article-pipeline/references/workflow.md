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

1. Generate the draft image after the nearby paragraphs are written.
2. Check that the slot role is correct for that position instead of defaulting to another generic theme image.
3. Check whether it matches the paragraph point, feels generic, or competes with the headline.
4. If it fails, regenerate once with a safer and simpler prompt or a different visual direction.
5. Save the approved file with the matching placeholder basename such as `body-2.png`.
6. Package the markdown plus local image directory into the final HTML with `scripts/package_wechat_article_bundle.py`, keeping role metadata in the markdown/job artifacts.

For cover and closing visuals, bias toward quieter composition:
- fewer competing elements
- clearer whitespace around the headline
- no noisy fake UI clutter or text-heavy overlays
