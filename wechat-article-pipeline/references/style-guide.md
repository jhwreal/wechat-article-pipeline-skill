# Style Guide

Use this file for article voice, focus marks, and visual direction. Do not use it as the command runbook; `SKILL.md` owns execution paths.

## Voice

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

## Focus Marks

- Use `##` headings for real structural turns before adding emphasis.
- Use `**...**` for one useful core sentence in a focus zone.
- Use `> ...` only for an original sentence strong enough to become a pull quote.
- Do not repeat a sentence just to create a quote.
- Keep `==...==` available for manual pink accent use, but do not add automatic pink keywords by default.
- For technical articles, use markdown inline code for exact project names, repos, files, directories, paths, commands, environment variables, APIs, scripts, config keys, and literal UI/control names.
- Do not wrap broad ideas or ordinary business terms in backticks.

## Visual Modes

Image generation, avoid, selection, and image-influence rules live only in [image-rules.json](image-rules.json). Do not duplicate them here; edit that JSON when image behavior needs tuning.
