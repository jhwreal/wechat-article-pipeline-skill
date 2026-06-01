# Style Guide

Tone:
- explanatory
- grounded
- readable by ordinary readers
- not academic
- not marketing-heavy
- rational and thoughtful
- like a capable friend talking to Chinese internet readers

Writing rules:
- lead with the reader's confusion, not with jargon
- prefer short paragraphs
- explain a term before expanding it
- use bullets only when they help comprehension
- keep each section doing one job
- when the article has clear internal turns, use `##` section headings before relying on visual emphasis
- use `**...**` for a whole core sentence that deserves the green key-sentence treatment
- keep the pink accent style available for future manual use, but do not add automatic pink keyword marks by default
- for technical, tool, coding, workflow, system-building, or tutorial articles, format concrete technical terms with markdown inline code backticks: project/repo names, file and directory names, paths, commands, environment variables, API names, script names, config keys, and literal UI/control names
- treat inline-code technical-term formatting as a required readability layer for technical articles; it is not keyword accent marking and not focus marking
- do not wrap broad concepts or ordinary business terms in backticks just to create visual emphasis
- use `> ...` only for a genuinely strong quote, and convert the original sentence instead of repeating it
- keep the article compact: under 2000 Chinese characters by default, aim near 1000
- optimize for completion rate: cut padding, keep information density high
- bias toward practical cognition gains, not empty attitude or slogan writing

Visual rules:
- keep the article workbench/theme on the existing green template unless the user explicitly asks to change the overall theme color
- vary the visual direction through image content, composition, and scene treatment first; do not rely on rotating the whole page color to fake variety
- use Codex's built-in image generation tool directly for cover, closing, and in-body visuals
- first derive jobs with `scripts/make_wechat_article_image_jobs.py`; after current Codex generates and saves images into the workspace, package with `scripts/package_wechat_article_bundle.py`
- do not start a nested Codex runtime, use `scripts/image_gen.py`, produce SVG placeholders, or add a custom image API runner in the default workflow
- finish the article first, then generate one cover image and one closing image; method articles can use roughly one in-body image per 200 Chinese characters, while emotional, story, or principle articles should use fewer, stronger illustrations at roughly one per 300-450 Chinese characters
- choose visual mode before body roles: `method_visual` for steps/tools/processes, `emotional_illustration` for stories/emotions/life principles, and `analysis_visual` for evidence/mechanism/trend pieces
- default body visuals should sit in the middle lane: light explainer illustrations, not dense infographics and not mood-only art
- a light explainer illustration uses one concrete scene or object plus 2-3 short annotations, relation lines, small nodes, icons, or visible consequences to explain exactly one local point
- limit light explainers to three information blocks and one main arrow chain; if it needs more, split the idea or simplify the article beat
- in `emotional_illustration`, body visuals must use illustration logic: human moments, symbolic scenes, light, space, objects, tension, silence, and metaphor; do not use numbered steps, arrows, process diagrams, checklist cards, information cards, UI panels, or icon matrices
- emotional body visuals still need a useful local signal: a concrete situation, consequence, choice, pressure source, or key object; do not settle for generic atmosphere
- before generating, build an internal image plan so each slot has a role, a local context, a content focus, and an anti-repetition rule
- save generated files under `<workspace>/image/<article-slug>/` with placeholder-aligned basenames such as `cover`, `body-1`, and `closing`
- write `cover` and `closing` from the full article meaning, and write each `body-*` prompt from the roughly 200 Chinese characters immediately before that placeholder instead of using generic article art
- treat `body-*` slots like different editing beats: explanation, scene, contrast, detail, metaphor, extension, emotion; do not flatten them into one repeated theme image
- keep in-body placeholder names generic as `body-*`; image meaning comes from the paragraph block, not from old SVG layout labels
- avoid noisy backgrounds and fake interface clutter
- prefer one-file delivery, with support files as optional extras
- default to the 200-character in-body rhythm unless the article structure clearly supports fewer, stronger images
- keep cover and closing visuals compositionally conservative unless the user explicitly wants a bolder poster-like treatment
- do not let decorative symbols or fake UI elements compete with the main title
- if a visual looks crowded, generic, off-topic, or purely atmospheric, choose a simpler light-explainer prompt instead of trying to save the fancy one
- always run a post-generation visual check before embedding into the final HTML
- preserve hidden markdown/job metadata for each slot role when packaging so a single bad image can be reworked later without re-guessing its intent

Default visual directions to rotate between:
- `mint-editorial`: default page/workbench green theme and calm explanatory direction; treat this as the baseline unless the user explicitly asks to change the overall theme
- `ink-journal`: warmer paper-like editorial look, better for commentary and media analysis
- `blueprint-news`: cooler newsroom/data feel, better for case studies and evidence-led pieces
- `paper-notes`: softer notebook feel, better for method and personal reflection pieces

Do not reuse the same image treatment blindly across consecutive articles. If a new article still feels like the last one in another color, change the prompt logic and subject matter instead of pushing the same composition again.

Post-render check:
- headline area stays clear
- the image clearly supports the paragraph it sits beside
- no broken text rendering or accidental embedded words inside the image
- no “almost centered” or “almost relevant” filler composition
- if uncertain, regenerate once with a safer layout
