# Style Guide

Use this file for article voice, focus marks, and visual direction. Do not use it as the command runbook; `SKILL.md` owns execution paths.

## Voice

- Read [writing-donts.md](writing-donts.md) before writing or revising; use it as the single maintained writing rule library and check the finished text against its scope.
- Write in Chinese by default.
- Sound like a capable friend explaining something clearly.
- Lead with the reader's confusion or stakes, not jargon.
- Prefer short paragraphs and concrete examples.
- Explain a term before expanding it.
- Keep each section doing one job.
- Cut padding, throat-clearing, generic AI phrasing, and slogan endings.
- Use bullets only when they improve scanning.
- Avoid report, paper, marketing-page, and formal PR prose unless requested.

## Secretary Mode

Trigger only when the user explicitly says `打开秘书模式`. Treat the mode name as internal: do not print a "秘书模式" heading, label, or explanation in the article unless the user asks.

Use it for oral-mainline cleanup when the user has already supplied the article's main judgment, order, examples, and rhythm. Do not use it for ordinary topic briefs, source summarization, or full article invention.

- Preserve the user's opening line, conclusion, example order, repetition anchors, emotional pressure, and speaking cadence.
- Keep the user's terms when they work. Polish only sentence breaks, paragraphing, obvious口误, duplicated filler, and local transitions.
- Do not replace the user's structure or vocabulary with a cleaner AI outline.
- Do not broaden the thesis, add a balanced framework, add solutions, add caveats, or turn the piece into a report unless the user asks.
- Do not explain punchlines before they land. If a sentence is meant to be a hard judgment, keep it as a hard judgment.
- Prefer concrete everyday examples before abstract names and definitions when the user spoke that way.
- Reuse deliberate repeated anchors, especially final-return lines such as "AI 就主导了系统"; do not replace them with varied synonyms just to sound polished.
- If the source material has a gap, mark the gap or ask; do not invent a new main argument.
- For substantial rewrites when an article slug or draft folder exists, save a versioned draft before replacing the current draft.

Self-check before finalizing: if the result is smoother but less like the user speaking, revise back toward the user's phrasing.

Avoid default translator/explainer phrases in this mode: `换句话说`, `简单说`, `翻译成人话`, `这意味着`, `真正的问题是`, `从本质上看`, `值得注意的是`, `我们需要意识到`, `由此可见`, `综上所述`.

## Term Annotations

When the user requests a term annotation, follow [annotations.md](annotations.md) for Arabic-numbered inline markers and the final appendix.

## Focus Marks

- Use `##` headings for real structural turns before adding emphasis.
- While drafting, actively choose the few judgments readers should remember or share. Mark the strongest existing sentences with `> ...` in the source Markdown; the WeChat style renders these as a light-gray box with a colored left border. Selection is an editorial judgment about meaning, evidence, and rhythm, not a keyword score.
- A pull quote should express a specific, supported insight in the author's voice and remain understandable when read on its own. Preserve qualifications that affect its truth; do not exaggerate, invent evidence, or add slogans to make it more shareable. Do not rewrite prose into formulaic phrases such as “真正……不是……而是……” to trigger a scorer.
- Keep pull quotes scarce. For an ordinary 1000–2000-character article, 1–3 is a useful starting range, not a quota or a universal cap. Short posts may need fewer; longer pieces may justify more. Avoid consecutive boxes, one box per section, and boxes occupying most of the text. Distinguish necessary source quotations or reading-note excerpts from emphasis boxes when judging density.
- Promote a sentence in place, near its supporting explanation or at a meaningful turn; do not duplicate it elsewhere just to create a quote. Use `**...**` for secondary emphasis, without making every paragraph bold or wrapping the entire pull quote in bold by default.
- Keep `==...==` available for manual pink accent use, but do not add automatic pink keywords by default.
- Keep focus marks out of headings, image placeholders, code fences, inline code, commands, and dense list-only sections.
- For technical articles, use markdown inline code for exact project names, repos, files, directories, paths, commands, environment variables, APIs, scripts, config keys, and literal UI/control names.
- Do not wrap broad ideas or ordinary business terms in backticks.

### Focus Review

Perform this editorial check before article delivery and during a full article check; respect narrower requests such as typo-only checks or image-only repairs.

- Read the actual final Markdown and, when producing HTML, inspect the rendered WeChat preview: do the selected sentences carry the core judgment, retain necessary context, and create useful visual pauses? Check both missing emphasis and excessive, repetitive, or misplaced boxes. Passing the package verifier or the keyword scorer does not complete this review.
- If a strong sentence already exists but is unmarked, identify its location and suggest `> ...`; apply it when drafting or editing is authorized. For check-only requests, leave the article unchanged and report the suggestion.
- If no sentence merits a pull quote, explicitly report “缺少值得突出、便于读者记住或转述的核心判断” as a recommended improvement. Explain where the argument or ending needs work; offer a concrete structural adjustment and 1–3 candidate sentences with proposed placement, grounded in the article's existing facts and stance. Label these as suggestions, identify any missing support, and do not silently insert them into a checked article. For inherently procedural or reference-only material, explain that fit and offer a useful takeaway without manufacturing a sweeping claim.
- Zero boxes must be an explained editorial choice, not an unnoticed omission. Missing pull quotes alone are not a factual error or a publishing blocker: deliver the article with the issue and suggestions visible to the user. The goal is clearer reading and more memorable, shareable ideas, not a promise of reach or a required box count.

## Visual Modes

Image generation, avoid, selection, and image-influence rules live only in [image-rules.json](image-rules.json). Do not duplicate them here; edit that JSON when image behavior needs tuning.
